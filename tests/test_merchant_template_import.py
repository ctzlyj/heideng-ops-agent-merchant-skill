"""Exercise workbook imports through the isolated local listing entry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openpyxl import Workbook, load_workbook
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "mature/listing/scripts/merchant_template_import.py"


class MerchantTemplateImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.product_headers = ["来源平台", "来源商品链接", "来源商品ID", "商品标题", "来源店铺名称",
                                "主图文件夹", "详情图文件夹", "视频文件", "目标类目", "目标类目ID", "主图模式"]
        self.sku_headers = ["来源商品ID", "来源SKU ID", "商家SKU", "款式名称", "尺寸或规格",
                            "完整源销售属性", "SKU图片路径", "来源当前有效价", "库存", "是否启用"]
        for name in ("主图", "详情"):
            (self.root / name).mkdir()
            Image.new("RGB", (800, 800), "white").save(self.root / name / "01.jpg")
        self.category = {"id": 7822, "name": "试验装订耗材"}
        self.rules = {
            "category": self.category, "categoryAttributes": [],
            "productDefaults": {"brandId": 15, "brandName": "样品牌", "freightTemplateId": "1",
                                "freightTemplateLabel": "运费", "mainImageMode": "single_set",
                                "sevenDayReturnCode": "1", "sevenDayReturnLabel": "支持", "stock": 17},
            "pricing": {"targetArrivalMultiplier": "0.8", "belowCompetitor": 0, "nationalSubsidyRate": 0,
                        "activityDiscountRate": 0, "coupon": 0},
        }
        self.reference = {"category": self.category, "brands": [{"brandId": 15}],
                          "media": {"defaultCategoryId": "9", "categories": [{"categoryId": "9"}]},
                          "componentCatalog": [], "schema": {"componentList": []}}
        self.add_dimension("装订孔数", 1)
        self.product = ["淘宝", "https://example.invalid/fixture", "SPU1", "测试装订耗材", "测试店",
                        "主图", "详情", None, self.category["name"], self.category["id"], "单套主图"]
        self.skus = [
            ["SPU1", "sku" + str(i), code, "", "", json.dumps({"装订孔数": value, "材料": "纸"}),
             "主图/01.jpg", 50, stock, "是"]
            for i, (code, value, stock) in enumerate([("001", "六孔", 0), ("001", "九孔", 2), ("", "四孔", None)])
        ]

    def add_dimension(self, title, index):
        code = "sale-prop-" + str(index)
        self.reference["componentCatalog"].append({"path": "root/SKUS/VenderCategoryValue", "componentCode": code,
                                                  "title": title, "required": True})
        self.reference["schema"]["componentList"].append({"componentCode": code, "componentTitle": title,
                                                         "extra": {"dim": index}})

    def run_import(self, *, historical_defaults=False):
        book = Workbook()
        products = book.active
        products.title = "商品信息"
        products.append(self.product_headers)
        products.append(self.product)
        detail = book.create_sheet("SKU明细")
        detail.append(self.sku_headers)
        for row in self.skus:
            detail.append(row)
        if isinstance(self.skus[0][2], int):
            detail["C2"].number_format = "000"
        book.save(self.root / "商家模板.xlsx")
        book.close()
        home = self.root / "state"
        args = ["--input", str(self.root / "商家模板.xlsx"), "--output-root", str(self.root / "drafts")]
        for flag, data in (("rules", self.rules), ("reference", self.reference)):
            if historical_defaults:
                path = home / "mature" / "listing" / "config" / f"modern-decorative-painting.{flag}.json"
            else:
                path = self.root / (flag + ".json")
                args += ["--" + flag, str(path)]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/mature_entry.py"), str(ENTRY), *args],
                                env={**os.environ, "HEIDENG_MERCHANT_HOME": str(home)},
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload, (result.stdout, result.stderr))
        self.assertEqual(result.returncode, 0 if payload["ok"] else 1)
        return payload

    def test_other_category_keeps_codes_facts_prices_and_dimension(self):
        self.skus[0][2] = 1
        result = self.run_import()
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["published"])
        files = result["results"][0]
        manifest = json.loads(Path(files["manifest"]).read_text(encoding="utf-8"))
        listing = json.loads(Path(files["listing"]).read_text(encoding="utf-8"))
        self.assertEqual((manifest["targetCategoryId"], listing["category"]["id"]), (7822, 7822))
        self.assertNotIn("sourceCategoryIds", manifest)
        self.assertNotIn("categoryIds", manifest)
        self.assertEqual((manifest["sourceSpu"], manifest["sourceSku"]), ("SPU1", "sku0"))
        self.assertEqual(manifest["sourceFixedSkuProperties"], {"材料": ["纸"]})
        self.assertNotIn("stock", manifest["variants"][2])
        self.assertEqual([s["stock"] for s in listing["skus"]], [0, 2, 17])
        self.assertEqual([s["vendorSku"] for s in listing["skus"]], ["001", "001", ""])
        self.assertEqual([s["jdPrice"] for s in listing["skus"]], [40, 40, 40])
        self.assertEqual(listing["product"]["saleAttributeComponents"]["style"]["attrName"], "装订孔数")
        self.assertNotIn("inferredProductForm", listing["product"])
        self.assertNotIn("mountingValueId", listing["skus"][0])
        workbook = load_workbook(files["auditWorkbook"])
        try:
            sheet = workbook["SKU明细"]
            self.assertEqual([sheet[key].value for key in ("C2", "C3", "D3", "E3", "E4", "E5")],
                             ["装订孔数", "六孔", None, "001", "001", None])
        finally:
            workbook.close()

    def test_category_mismatch_cannot_use_unrelated_rules(self):
        self.reference["category"] = {"id": 35381, "name": "现代装饰画"}
        result = self.run_import()
        self.assertIn("不一致", result["error"])
        self.assertFalse((self.root / "drafts").exists())

    def test_source_price_uses_each_workbook_price_without_promotion_parameters(self):
        self.rules["pricing"] = {"mode": "source-price"}
        self.skus[1][7] = 12.34
        result = self.run_import()
        self.assertTrue(result["ok"], result)
        files = result["results"][0]
        listing = json.loads(Path(files["listing"]).read_text(encoding="utf-8"))
        self.assertEqual([s["jdPrice"] for s in listing["skus"]], [50, 12.34, 50])
        report = json.loads((Path(files["folder"]) / "pricing-verification.json").read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "source-price")
        self.assertTrue(report["ok"])
        self.assertNotIn("expectedArrivalPrice", report["rows"][1])
        listing["skus"][1]["jdPrice"] = 12.33
        changed = Path(files["folder"]) / "recheck.json"
        changed.write_text(json.dumps(listing), encoding="utf-8")
        recheck = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/mature_entry.py"),
                                  str(ENTRY.with_name("jdo_listing_mvp.py")), "preflight", "--input", str(changed),
                                  "--reference", str(self.root / "reference.json")],
                                 env={**os.environ, "HEIDENG_MERCHANT_HOME": str(self.root / "state")},
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(recheck.returncode, 2)
        self.assertIn("原价", "".join(json.loads(recheck.stdout)["errors"]))

    def test_three_dimensions_route_to_general_tool(self):
        for dim, name in enumerate(("包装数量", "颜色"), start=2):
            self.add_dimension(name, dim)
            for row in self.skus:
                attrs = json.loads(row[5])
                attrs[name] = row[1] + name
                row[5] = json.dumps(attrs)
        result = self.run_import()
        self.assertIn("photo-listing", result["error"])
        self.assertFalse((self.root / "drafts").exists())

    def test_required_vendor_code_fails_without_leaving_draft_and_can_retry(self):
        self.reference["componentCatalog"].append({"componentCode": "SkuVendorSku", "required": True})
        result = self.run_import()
        self.assertIn("商家编码", result["error"])
        self.assertEqual(list((self.root / "drafts").iterdir()), [])
        self.skus[2][2] = "003"
        self.assertTrue(self.run_import()["ok"])

    def test_legacy_painting_columns_and_local_rules(self):
        self.category.update(id=35381, name="现代装饰画")
        self.rules["productDefaults"]["mainImageMode"] = "multi_set"
        self.reference["componentCatalog"] = []
        self.reference["schema"]["componentList"] = []
        self.add_dimension("颜色", 1)
        self.add_dimension("尺寸", 2)
        self.product[3] = "测试挂轴"
        self.product[-3:] = ["现代装饰画", 35381, "多套主图"]
        self.sku_headers[2] = "商家SKU（商家编码，必填）"
        self.product_headers.append("来源类目ID")
        self.product.append(561)
        self.rules["category"]["sourceId"] = 561
        for index, row in enumerate(self.skus):
            style, size = [("青松", "20cm"), ("青松", "30cm"), ("山河", "20cm")][index]
            row[3:6] = [style, size, json.dumps({"颜色分类": style, "幅面": size})]
        result = self.run_import(historical_defaults=True)
        self.assertTrue(result["ok"], result)
        manifest = json.loads(Path(result["results"][0]["manifest"]).read_text(encoding="utf-8"))
        evidence = manifest["templateImport"]
        self.assertEqual(manifest["sourceCategoryIds"], [561])
        self.assertEqual(evidence["inference"]["salesDimensionNames"], ["颜色分类", "幅面"])
        self.assertNotIn("productFormLabel", evidence["inference"])
        self.assertEqual(Path(evidence["rules"]).name, "modern-decorative-painting.rules.json")


if __name__ == "__main__":
    unittest.main()
