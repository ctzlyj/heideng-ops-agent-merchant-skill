#!/usr/bin/env python3
"""Parse the merchant-facing workbook and build local-only Jingmai drafts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openpyxl import load_workbook

import jd_product_mover as mover
import jdo_listing_mvp as jingmai
from photo_contract import walk_components
from source_pricing import component_mode, component_source_audit


PRODUCT_SHEET = "商品信息"
SKU_SHEET = "SKU明细"
PRODUCT_HEADERS = {
    "来源平台", "来源商品链接", "来源商品ID", "商品标题", "来源店铺名称",
    "主图文件夹", "详情图文件夹", "视频文件", "目标类目", "目标类目ID", "主图模式",
}
SKU_HEADERS = {
    "来源商品ID", "来源SKU ID", "款式名称", "尺寸或规格",
    "完整源销售属性", "SKU图片路径", "来源当前有效价", "库存", "是否启用",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
PLATFORM_PREFIX = {"京东": "JD", "淘宝": "TB", "天猫": "TM", "jd": "JD", "taobao": "TB", "tmall": "TM"}
VENDOR_HEADER = "商家SKU"
VENDOR_HEADERS = {VENDOR_HEADER, "商家编码", "商家SKU（商家编码，必填）", "商家SKU（商家编码）"}
PHOTO_LISTING = "可在实拍上新任务包使用 run photo-listing -- set-facts --package <任务包> --facts <商品事实.json>，按当前类目组件填写真实 SKU 和销售属性"


class TemplateImportError(RuntimeError):
    pass


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def table_rows(workbook: Any, sheet_name: str, required_headers: set[str], key_headers: tuple[str, ...]) -> list[dict[str, Any]]:
    if sheet_name not in workbook.sheetnames:
        raise TemplateImportError(f"模板缺少工作表：{sheet_name}")
    sheet = workbook[sheet_name]
    iterator = sheet.iter_rows()
    try:
        headers = [text(cell.value) for cell in next(iterator)]
    except StopIteration as exc:
        raise TemplateImportError(f"工作表为空：{sheet_name}") from exc
    if sheet_name == SKU_SHEET:
        headers = [VENDOR_HEADER if header in VENDOR_HEADERS else header for header in headers]
        if headers.count(VENDOR_HEADER) > 1:
            raise TemplateImportError("SKU明细有多个商家SKU列，无法确定编码来源")
    missing = sorted(required_headers - set(headers))
    if missing:
        raise TemplateImportError(f"{sheet_name}缺少表头：{missing}")
    rows: list[dict[str, Any]] = []
    for row_number, cells in enumerate(iterator, start=2):
        record = {header: cell.value for header, cell in zip(headers, cells) if header}
        if sheet_name == SKU_SHEET and VENDOR_HEADER in record:
            cell = cells[headers.index(VENDOR_HEADER)]
            code = cell.value
            if cell.data_type == "f":
                raise TemplateImportError(f"SKU明细第{row_number}行商家SKU是公式，请粘贴实际编码值")
            if code is not None and not isinstance(code, str):
                digits = text(code)
                format_code = cell.number_format or "General"
                if not re.fullmatch(r"[0-9]{1,15}", digits) or not (
                    format_code in {"General", "@"} or re.fullmatch("0+", format_code)
                ):
                    raise TemplateImportError(f"SKU明细第{row_number}行商家SKU格式无法还原，请按显示值填写文本")
                record[VENDOR_HEADER] = digits.zfill(len(format_code)) if format_code.startswith("0") else digits
        if not any(text(record.get(header)) for header in key_headers):
            continue
        record["_row"] = row_number
        rows.append(record)
    return rows


def positive_price(value: Any, row_number: int) -> str:
    try:
        price = Decimal(text(value))
    except InvalidOperation as exc:
        raise TemplateImportError(f"SKU明细第{row_number}行来源当前有效价不是有效数字") from exc
    if not price.is_finite() or price <= 0:
        raise TemplateImportError(f"SKU明细第{row_number}行来源当前有效价必须大于0")
    cents = price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(cents) if price == cents else format(price, "f")


def non_negative_stock(value: Any, row_number: int) -> int:
    try:
        number = Decimal(text(value))
    except InvalidOperation as exc:
        raise TemplateImportError(f"SKU明细第{row_number}行库存不是有效整数") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise TemplateImportError(f"SKU明细第{row_number}行库存必须为非负整数")
    return int(number)


def enabled_value(value: Any, row_number: int) -> bool:
    rendered = text(value).lower()
    if rendered in {"是", "启用", "true", "1", "yes"}:
        return True
    if rendered in {"否", "禁用", "false", "0", "no"}:
        return False
    raise TemplateImportError(f"SKU明细第{row_number}行是否启用只能填写是或否")


def source_attributes(value: Any, row_number: int) -> OrderedDict[str, str]:
    rendered = text(value)
    if not rendered:
        raise TemplateImportError(f"SKU明细第{row_number}行缺少完整源销售属性；无销售维度的商品，{PHOTO_LISTING}")
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        result = OrderedDict((text(key), text(item)) for key, item in parsed.items())
    else:
        result = OrderedDict()
        for part in re.split(r"[|；;\n]+", rendered):
            part = part.strip()
            if not part:
                continue
            match = re.match(r"^([^=:：]+)\s*[=:：]\s*(.+)$", part)
            if not match:
                raise TemplateImportError(
                    f"SKU明细第{row_number}行完整源销售属性格式错误；请用JSON或 属性=值|属性=值"
                )
            result[text(match.group(1))] = text(match.group(2))
    if not result or any(not key or not item for key, item in result.items()):
        raise TemplateImportError(f"SKU明细第{row_number}行完整源销售属性存在空名称或空值")
    return result


def resolve_path(workbook_path: Path, value: Any, label: str, *, directory: bool) -> Path:
    rendered = text(value)
    if not rendered:
        raise TemplateImportError(f"缺少{label}")
    candidate = Path(rendered)
    if not candidate.is_absolute():
        candidate = workbook_path.parent / candidate
    candidate = candidate.resolve()
    valid = candidate.is_dir() if directory else candidate.is_file()
    if not valid:
        kind = "文件夹" if directory else "文件"
        raise TemplateImportError(f"{label}{kind}不存在：{candidate}")
    return candidate


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def image_files(folder: Path, label: str) -> list[Path]:
    files = sorted(
        (path.resolve() for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
        key=natural_key,
    )
    if not files:
        raise TemplateImportError(f"{label}中没有支持的图片：{folder}")
    return files


def attribute_values(all_attributes: list[OrderedDict[str, str]]) -> dict[str, list[str]]:
    names = list(all_attributes[0])
    for attributes in all_attributes[1:]:
        if set(attributes) != set(names):
            raise TemplateImportError("完整源销售属性的属性名称不一致，无法可靠判断销售维度")
    return {name: list(dict.fromkeys(attributes[name] for attributes in all_attributes)) for name in names}


def parse_template(workbook_path: Path) -> list[dict[str, Any]]:
    workbook_path = workbook_path.resolve()
    if not workbook_path.is_file():
        raise TemplateImportError(f"模板文件不存在：{workbook_path}")
    workbook = load_workbook(workbook_path, data_only=False, read_only=True)
    try:
        products = table_rows(
            workbook, PRODUCT_SHEET, PRODUCT_HEADERS,
            ("批次编号", "来源平台", "来源商品链接", "来源商品ID", "商品标题", "来源店铺名称", "主图文件夹", "详情图文件夹", "视频文件"),
        )
        sku_rows = table_rows(
            workbook, SKU_SHEET, SKU_HEADERS,
            ("来源商品ID", "来源SKU ID", VENDOR_HEADER, "款式名称", "尺寸或规格", "完整源销售属性", "SKU图片路径", "来源当前有效价"),
        )
    finally:
        workbook.close()
    if not products:
        raise TemplateImportError("商品信息没有已填写的商品行")
    if not sku_rows:
        raise TemplateImportError("SKU明细没有真实SKU行")

    product_ids: set[str] = set()
    source_skus: set[tuple[str, str]] = set()
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in sku_rows:
        row_number = int(row["_row"])
        product_id = text(row.get("来源商品ID"))
        source_sku = text(row.get("来源SKU ID"))
        raw_vendor_sku = row.get(VENDOR_HEADER)
        if not product_id or not source_sku:
            raise TemplateImportError(f"SKU明细第{row_number}行缺少来源商品ID或来源SKU ID")
        if (product_id, source_sku) in source_skus:
            raise TemplateImportError(f"商品{product_id}内来源SKU ID重复：{source_sku}")
        source_skus.add((product_id, source_sku))
        product_ids.add(product_id)
        row["_sourceSku"] = source_sku
        row["_vendorSku"] = raw_vendor_sku or ""
        row["_sourcePrice"] = positive_price(row.get("来源当前有效价"), row_number)
        if text(row.get("库存")):
            row["_stock"] = non_negative_stock(row["库存"], row_number)
        row["_enabled"] = enabled_value(row.get("是否启用"), row_number)
        row["_attributes"] = source_attributes(row.get("完整源销售属性"), row_number)
        row["_skuImage"] = resolve_path(workbook_path, row.get("SKU图片路径"), f"SKU明细第{row_number}行SKU图片", directory=False)
        grouped_rows.setdefault(product_id, []).append(row)

    parsed_products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for product in products:
        row_number = int(product["_row"])
        product_id = text(product.get("来源商品ID"))
        if not product_id:
            raise TemplateImportError(f"商品信息第{row_number}行缺少来源商品ID")
        if product_id in seen_products:
            raise TemplateImportError(f"商品信息来源商品ID重复：{product_id}")
        seen_products.add(product_id)
        rows = grouped_rows.get(product_id) or []
        if not rows:
            raise TemplateImportError(f"商品{product_id}没有对应的SKU明细")
        platform = text(product.get("来源平台"))
        source_url = text(product.get("来源商品链接"))
        title = text(product.get("商品标题"))
        if platform not in PLATFORM_PREFIX or not source_url or not title:
            raise TemplateImportError(f"商品信息第{row_number}行来源平台、来源链接和标题均为必填")
        category_id = int(text(product.get("目标类目ID")) or 0)
        category_name = text(product.get("目标类目"))
        main_mode = text(product.get("主图模式"))
        if category_id <= 0:
            raise TemplateImportError(f"商品信息第{row_number}行缺少有效目标类目ID")
        main_folder = resolve_path(workbook_path, product.get("主图文件夹"), f"商品{product_id}主图", directory=True)
        detail_folder = resolve_path(workbook_path, product.get("详情图文件夹"), f"商品{product_id}详情图", directory=True)
        main_paths = image_files(main_folder, f"商品{product_id}主图文件夹")
        detail_paths = image_files(detail_folder, f"商品{product_id}详情图文件夹")
        video_value = text(product.get("视频文件"))
        video_path = resolve_path(workbook_path, video_value, f"商品{product_id}视频", directory=False) if video_value else None

        variants = []
        for row in rows:
            variants.append({
                "sourceSku": row["_sourceSku"],
                "sourcePrice": row["_sourcePrice"],
                "sourceFullAttributes": dict(row["_attributes"]),
                "sourceStyleLabel": text(row.get("款式名称")),
                "sourceSizeLabel": text(row.get("尺寸或规格")),
                "vendorSku": row["_vendorSku"],
                **({"stock": row["_stock"]} if "_stock" in row else {}),
                "enabled": row["_enabled"],
                "skuImage": str(row["_skuImage"]),
            })
        source = {
            "schemaVersion": "merchant-template/v1",
            "sourcePlatform": platform.lower() if platform.isascii() else {"京东": "jd", "淘宝": "taobao", "天猫": "tmall"}[platform],
            "productKeyPrefix": PLATFORM_PREFIX[platform],
            "collectedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sourceUrl": source_url,
            "sourceInputUrl": source_url,
            "sourceSku": variants[0]["sourceSku"],
            "sourceSpu": product_id,
            "sourceShopName": text(product.get("来源店铺名称")),
            "targetCategoryId": category_id,
            "targetCategoryName": category_name,
            "title": title,
            "fullTitle": title,
            "sourceBrandId": "",
            "sourceBrandName": "",
            "mainImages": [str(path) for path in main_paths],
            "detailImages": [str(path) for path in detail_paths],
            "video": ({"localPath": str(video_path)} if video_path else None),
            "variants": variants,
            "templateImport": {
                "workbook": str(workbook_path),
                "productSheetRow": row_number,
                "mainImageMode": main_mode,
                "batchId": text(product.get("批次编号")),
                "note": text(product.get("备注")),
                "inference": {},
            },
        }
        if text(product.get("来源类目ID")):
            source_id = int(text(product["来源类目ID"]))
            if source_id <= 0:
                raise TemplateImportError(f"商品信息第{row_number}行来源类目ID无效")
            source["sourceCategoryIds"] = [source_id]
            source["categoryIds"] = [source_id]
        parsed_products.append({"source": source})
    extra_product_ids = product_ids - seen_products
    if extra_product_ids:
        raise TemplateImportError(f"SKU明细存在商品信息中未定义的来源商品ID：{sorted(extra_product_ids)}")
    return parsed_products


def copy_materials(source: dict[str, Any], folder: Path) -> dict[str, Any]:
    result = deepcopy(source)
    for key, target_name in (("mainImages", "主图"), ("detailImages", "详情图")):
        copied: list[str] = []
        for index, raw_path in enumerate(source[key], start=1):
            path = Path(raw_path)
            target = folder / target_name / f"{index:03d}{path.suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(target.relative_to(folder).as_posix())
        result[key] = copied
    sku_copies: dict[str, str] = {}
    for variant in result["variants"]:
        original = str(Path(variant["skuImage"]).resolve())
        if original not in sku_copies:
            path = Path(original)
            target = folder / "SKU图" / f"{len(sku_copies) + 1:03d}{path.suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            sku_copies[original] = target.relative_to(folder).as_posix()
        variant["skuImage"] = sku_copies[original]
    video = result.get("video") or {}
    if video.get("localPath"):
        source_video = Path(video["localPath"])
        target = folder / "视频" / source_video.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_video, target)
        video["localPath"] = target.relative_to(folder).as_posix()
    return result


def bind_sale_dimensions(source: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, Any]]:
    variants = source["variants"]
    values = attribute_values([row["sourceFullAttributes"] for row in variants])
    components = [
        item for item in reference.get("componentCatalog") or []
        if item.get("path") == "root/SKUS/VenderCategoryValue"
        and str(item.get("componentCode") or "").startswith("sale-prop-")
    ]
    raw = {c["componentCode"]: c for c in walk_components(reference.get("schema") or {})}
    selected = []
    matched = set()
    for component in components:
        code, title = component["componentCode"], component.get("title")
        names = [name for name in values if name in (code, title)]
        # Old painting sheets used source names such as 颜色分类. Their separate
        # style/size columns evidence the mapping only when every SKU agrees.
        if not names and source["targetCategoryId"] == 35381:
            field = {"颜色": "sourceStyleLabel", "款式": "sourceStyleLabel",
                     "尺寸": "sourceSizeLabel", "尺码": "sourceSizeLabel"}.get(title)
            if field:
                names = [name for name in values if all(s[field] == s["sourceFullAttributes"][name] for s in variants)]
        if len(names) > 1 or (names and names[0] in matched):
            raise TemplateImportError(f"工作簿销售属性无法唯一对应组件 {code}：{names}；{PHOTO_LISTING}")
        if not names:
            if component.get("required"):
                raise TemplateImportError(f"缺少当前类目要求的销售维度 {title} ({code})；{PHOTO_LISTING}")
            continue
        name = names[0]
        extra = (raw.get(code) or {}).get("extra") or {}
        if str(extra.get("isStructure", "")).lower() in {"true", "1"}:
            raise TemplateImportError(f"销售维度 {title} 要求结构化输入；{PHOTO_LISTING}")
        matched.add(name)
        selected.append({"componentCode": code, "attrName": title or code, "sourceName": name,
                         "dimension": int(extra.get("dim") or len(selected) + 1)})

    unmatched = [name for name in values if name not in matched and len(values[name]) > 1]
    if unmatched or not 1 <= len(selected) <= 2:
        raise TemplateImportError(f"工作簿草稿不能无损表达销售属性 {list(values)}，已匹配 {[s['sourceName'] for s in selected]}；{PHOTO_LISTING}")
    selected.sort(key=lambda selection: selection["dimension"])
    if [s["dimension"] for s in selected] != list(range(1, len(selected) + 1)):
        raise TemplateImportError(f"工作簿草稿不能表达当前销售维度的组件顺序；{PHOTO_LISTING}")
    source["saleProperties"] = {s["componentCode"]: s["sourceName"] for s in selected}
    source["sourceFixedSkuProperties"] = {name: options for name, options in values.items() if name not in matched}
    for variant in variants:
        variant["sourceAttributes"] = {name: variant["sourceFullAttributes"][name] for name in source["saleProperties"].values()}
    source["templateImport"]["inference"].update({
        "salesDimensionCount": len(selected), "salesDimensionNames": list(source["saleProperties"].values()),
        "basis": "工作簿完整源销售属性与目标类目组件", "saleDimensionMapping": selected,
    })
    return selected


def pricing_verification(listing: dict[str, Any]) -> dict[str, Any]:
    pricing = listing["source"]["pricing"]
    if pricing.get("mode") == "source-price":
        rows = [{
            "sourceSku": sku["sourceSku"], "vendorSku": sku["vendorSku"], "sourcePrice": str(sku["sourcePrice"]),
            "jdPrice": str(sku["jdPrice"]), "ok": Decimal(str(sku["sourcePrice"])) == Decimal(str(sku["jdPrice"])),
        } for sku in listing["skus"]]
        return {"mode": "source-price", "ok": all(row["ok"] for row in rows), "rows": rows}
    below = Decimal(str(pricing["belowCompetitor"]))
    national = Decimal("1") - Decimal(str(pricing["nationalSubsidyRate"]))
    activity = Decimal("1") - Decimal(str(pricing["activityDiscountRate"]))
    coupon = Decimal(str(pricing["coupon"]))
    rows = []
    for sku in listing["skus"]:
        source_price = Decimal(str(sku["sourcePrice"]))
        jd_price = Decimal(str(sku["jdPrice"]))
        if component_mode(pricing):
            audit = component_source_audit(source_price, jd_price, pricing)
            arrival = Decimal(audit["arrivalPrice"])
            target = Decimal(audit["expectedArrivalPrice"])
        else:
            multiplier = Decimal(str(pricing.get("targetArrivalMultiplier", 1)))
            arrival = (jd_price * national * activity - coupon).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            target = (source_price * multiplier - below).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append({
            "sourceSku": sku["sourceSku"], "vendorSku": sku["vendorSku"],
            "sourcePrice": str(source_price), "jdPrice": str(jd_price),
            "expectedArrivalPrice": str(arrival), "targetArrivalPrice": str(target),
            "ok": arrival == target,
        })
    return {"ok": all(row["ok"] for row in rows), "rows": rows}


def safe_folder_name(value: str) -> str:
    rendered = re.sub(r'[<>:"/\\|?*]', "", value).strip()
    return rendered[:60] or "template-product"


def finalize_validated_audit(path: Path, variants: list[dict[str, Any]], names: list[str]) -> None:
    workbook = load_workbook(path)
    sheet = workbook["SKU明细"]
    for column, name in ((3, names[0]), (4, names[1] if len(names) == 2 else "")):
        sheet.cell(2, column).value = name
        sheet.cell(2, column).data_type = "s"
    for row_number, variant in enumerate(variants, start=3):
        for column, name in ((3, names[0]), (4, names[1] if len(names) == 2 else None)):
            cell = sheet.cell(row_number, column)
            cell.value = variant["sourceAttributes"][name] if name else None
            cell.data_type = "s"
        sheet.cell(row_number, 5).number_format = "@"
        sheet.cell(row_number, 17).number_format = "@"
        sheet.cell(row_number, 18, "通过")
    workbook.save(path)
    workbook.close()


def create_local_drafts(
    workbook_path: Path, output_root: Path, rules_path: Path | None, reference_path: Path | None,
) -> list[dict[str, Any]]:
    parsed = parse_template(workbook_path)
    if rules_path is None or reference_path is None:
        if any(item["source"]["targetCategoryId"] != 35381 for item in parsed):
            raise TemplateImportError("请提供该目标类目的 --rules 和 --reference")
        legacy_config = Path(os.environ.get("HEIDENG_MERCHANT_HOME", str(Path.home() / ".heideng-merchant"))) / "mature" / "listing" / "config"
        rules_path = rules_path or legacy_config / "modern-decorative-painting.rules.json"
        reference_path = reference_path or legacy_config / "modern-decorative-painting.reference.json"
    rules = mover.read_json(rules_path)
    reference = mover.read_json(reference_path)
    defaults = rules.setdefault("productDefaults", {})
    rules.setdefault("categoryAttributes", [])
    for field in ("brandName", "sevenDayReturnCode", "sevenDayReturnLabel", "freightTemplateId", "freightTemplateLabel"):
        defaults.setdefault(field, "")
    for item in parsed:
        source = item["source"]
        target = source["targetCategoryId"]
        if any(int((data.get("category") or {}).get("id") or 0) != target for data in (rules, reference)):
            raise TemplateImportError(f"商品{source['sourceSpu']}工作簿目标类目{target}与 --rules 或 --reference 不一致")
        target_name = source["targetCategoryName"]
        if target_name and any(data["category"].get("name") not in (None, "", target_name) for data in (rules, reference)):
            raise TemplateImportError(f"工作簿目标类目名称{target_name}与类目配置不一致")
        if not rules["category"].get("name"):
            rules["category"]["name"] = reference["category"].get("name") or target_name
        source_rule = rules["category"].get("sourceId")
        if source_rule and source.get("sourceCategoryIds") and source["sourceCategoryIds"][-1] != int(source_rule):
            raise TemplateImportError(f"商品{source['sourceSpu']}工作簿来源类目与规则的来源类目{source_rule}不一致")
        source["templateImport"].update({"rules": str(rules_path.resolve()), "reference": str(reference_path.resolve())})
        mode = source["templateImport"]["mainImageMode"]
        explicit_mode = {"多套主图": "multi_set", "单套主图": "single_set"}.get(mode, mode)
        expected_mode = defaults.get("mainImageMode")
        if explicit_mode and expected_mode and explicit_mode != expected_mode:
            raise TemplateImportError(f"工作簿主图模式{mode}与当前设置{expected_mode}不一致")
        item["mainImageMode"] = explicit_mode or expected_mode
        if item["mainImageMode"] not in {"multi_set", "single_set"}:
            raise TemplateImportError(f"工作簿草稿缺少受支持的主图模式，当前值为 {item['mainImageMode']}；{PHOTO_LISTING}")
        missing_stock = [v["sourceSku"] for v in source["variants"] if "stock" not in v]
        if missing_stock:
            stock = defaults.get("stock")
            if stock is None or text(stock) == "":
                raise TemplateImportError(f"SKU {missing_stock} 缺少库存，当前规则也没有默认库存")
            defaults["stock"] = non_negative_stock(stock, int(source["templateImport"]["productSheetRow"]))
        item["dimensions"] = bind_sale_dimensions(source, reference)
    pricing = rules.get("pricing") or {}
    if pricing.get("mode") != "source-price":
        missing_pricing = [key for key in ("belowCompetitor", "nationalSubsidyRate", "activityDiscountRate", "coupon")
                           if pricing.get(key) is None]
        if missing_pricing:
            raise TemplateImportError(f"请提供本次定价方案。沿用来源价可设 pricing.mode=source-price；按活动反推缺少：{missing_pricing}")
    # Every workbook SKU carries its original code, including an explicit blank.
    rules["vendorSku"] = {"defaultPrefix": ""}
    defaults.setdefault("stock", None)
    output_root = output_root.resolve()
    destinations = [output_root / safe_folder_name(f"{item['source']['sourceSpu']}_{item['source']['title']}") for item in parsed]
    existing = [str(path) for path in destinations if path.exists()]
    if existing:
        raise TemplateImportError(f"输出目录已存在，禁止覆盖：{existing}")

    if len(set(destinations)) != len(destinations):
        raise TemplateImportError("商品编号和标题生成了相同的输出目录")
    results = []
    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_root) as staging:
        for item, destination in zip(parsed, destinations):
            folder = Path(staging) / destination.name
            folder.mkdir()
            results.append(write_draft(item, folder, destination, rules, reference))
        for destination in destinations:
            (Path(staging) / destination.name).rename(destination)
    return results


def write_draft(
    item: dict[str, Any], folder: Path, destination: Path, rules: dict[str, Any], reference: dict[str, Any],
) -> dict[str, Any]:
    source = copy_materials(item["source"], folder)
    product_rules = {**rules, "productDefaults": {**rules["productDefaults"], "mainImageMode": item["mainImageMode"]}}
    listing = mover.build_listing(source, folder, product_rules, reference, 0)
    category_codes = {c["componentCode"] for c in reference.get("componentCatalog") or []
                      if c.get("path") == "root/CategoryGroupList"}
    unknown_codes = [a.get("componentCode") for a in listing["categoryAttributes"] if a.get("componentCode") not in category_codes]
    if unknown_codes:
        raise TemplateImportError(f"规则中类目属性未出现在当前目标类目参考中：{unknown_codes}")
    dimensions = item["dimensions"]
    definitions = {}
    for slot, dimension in zip(("style", "size"), dimensions):
        options = (rules.get("saleAttributes") or {}).get(slot) or {}
        if options.get("componentCode", dimension["componentCode"]) != dimension["componentCode"]:
            raise TemplateImportError(f"当前规则的 {slot} 组件与工作簿销售维度不一致；{PHOTO_LISTING}")
        definitions[slot] = {**options, "componentCode": dimension["componentCode"], "attrName": dimension["attrName"]}
    listing["product"]["saleAttributeComponents"] = definitions
    listing["product"].pop("vendorStyleStart", None)
    variants_by_sku = {variant["sourceSku"]: variant for variant in source["variants"]}
    for sku in listing["skus"]:
        if source["targetCategoryId"] != 35381:
            for legacy_field in ("mountingValueId", "mountingLabel", "subjectValueId", "subjectLabel"):
                sku.pop(legacy_field, None)
        variant = variants_by_sku[sku["sourceSku"]]
        aliases = jingmai.expected_sale_aliases(listing["product"], sku)
        if aliases != list(variant["sourceAttributes"].values()):
            raise TemplateImportError(f"草稿销售维度与来源 SKU {sku['sourceSku']} 的原始属性值不一致；{PHOTO_LISTING}")
    listing["product"]["inferredSalesDimensionCount"] = len(dimensions)
    listing_path = folder / "listing.json"
    errors, warnings = jingmai.validate_manifest(listing_path, listing, reference)
    validation = {"ok": not errors, "errors": errors, "warnings": warnings}
    if errors:
        raise TemplateImportError("本地草稿预检失败：" + "；".join(errors))
    pricing = pricing_verification(listing)
    if not pricing["ok"]:
        raise TemplateImportError("逐SKU价格复算失败")
    mover.write_json(folder / "manifest.json", source)
    mover.write_json(listing_path, listing)
    mover.write_json(folder / "pricing-verification.json", pricing)
    mover.write_json(folder / "local-validation.json", validation)
    audit_path = folder / "模板导入审核.xlsx"
    mover.build_audit_workbook(source, listing, audit_path)
    finalize_validated_audit(audit_path, source["variants"], list(source["saleProperties"].values()))
    state = {
        "stage": "LOCAL_DRAFT",
        "sourcePlatform": source["sourcePlatform"],
        "sourceSku": source["sourceSku"],
        "sourceSpu": source["sourceSpu"],
        "productId": None,
        "publishAllowed": False,
        "requires": ["PUBLISH_TO_JD"],
        "templateImport": source["templateImport"],
    }
    mover.write_json(folder / "state.json", state)
    return {
        "folder": str(destination),
        "manifest": str(destination / "manifest.json"),
        "listing": str(destination / "listing.json"),
        "auditWorkbook": str(destination / audit_path.name),
        "state": str(destination / "state.json"),
        "skuCount": len(listing["skus"]),
        "validation": validation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按工作簿和当前目标类目的规则、参考生成本地商品草稿")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--rules", type=Path, help="当前目标类目的商家规则 JSON")
    parser.add_argument("--reference", type=Path, help="当前店铺目标类目的参考 JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        results = create_local_drafts(args.input, args.output_root, args.rules, args.reference)
    except (OSError, ValueError, KeyError, ArithmeticError, TemplateImportError, mover.MoverError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "published": False, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
