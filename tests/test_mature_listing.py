"""Offline contract tests for bounded mature listing reuse (no live services)."""
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "mature" / "listing"
SCRIPTS = BUNDLE / "scripts"


def module(name):
    sys.path.insert(0, str(SCRIPTS))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS))


def jpeg(size=(1024, 1024)):
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "JPEG")
    return out.getvalue()


def manifest():
    return {"category": {"id": 1}, "product": {
        "productKey": "TEST", "title": "测试收纳架", "brandId": -1,
        "sevenDayReturnCode": "1", "freightTemplateId": "12",
        "includeSizeSaleAttribute": False,
        "saleAttributeComponents": {"style": {"componentCode": "sale-prop-2", "attrName": "规格"}},
    }, "skus": [
        {"skuKey": "one", "jdPrice": "10.50", "stock": 12, "vendorSku": "A-1",
         "styleAlias": "白色", "sizeAlias": "小", "styleMappingId": "color-a", "sizeMappingId": "size-a",
         "styleOrder": 1, "sizeOrder": 1, "enabled": True, "skuAttributes": []},
        {"skuKey": "two", "jdPrice": "20.75", "stock": 8, "vendorSku": "A-2",
         "styleAlias": "黑色", "sizeAlias": "大", "styleMappingId": "color-b", "sizeMappingId": "size-b",
         "styleOrder": 2, "sizeOrder": 2, "enabled": True, "skuAttributes": []}],
        "images": [
            {"role": "spu_main", "order": 1, "upload": {"imgUrl": "jfs/main.jpg"}},
            {"role": "sku_main", "skuKey": "one", "order": 1, "upload": {"imgUrl": "jfs/a.jpg"}},
            {"role": "sku_main", "skuKey": "two", "order": 1, "upload": {"imgUrl": "jfs/b.jpg"}},
            {"role": "detail", "order": 1, "upload": {"imgUrl": "jfs/detail.jpg"}}],
        "categoryAttributes": []}


def detail():
    return {"productInfo": {"productId": 123, "categoryDetail": {"lastCategoryId": 1}},
        "material": {"mainImages": [
            {"uuid": "color-a", "imageInfoList": [{"imgUrl": "jfs/a.jpg", "orderSort": 1}]},
            {"uuid": "color-b", "imageInfoList": [{"imgUrl": "jfs/b.jpg", "orderSort": 1}]}]},
        "skuList": [{"skuId": 1, "priceInfo": {"jdPrice": 10.50}},
                    {"skuId": 2, "priceInfo": {"jdPrice": 20.75}}]}


def sanitized_env(home):
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT", "TEMP", "TMP"}}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return env


class MatureListingTests(unittest.TestCase):
    def test_real_builder_preserves_optional_logistics_without_inventing(self):
        cli = module("jdo_listing_mvp")
        m = manifest(); before = copy.deepcopy(m)
        m["product"].update(packageLengthMm=240, packageWidthMm=180, packageHeightMm=60, weightKg="0.400")
        rows = {r["componentCode"]: r.get("value") for r in cli.build_publish_schema(m)}
        self.assertEqual([rows[c] for c in ("WareLength", "WareWide", "WareHeight", "WareWeight")],
                         ["240", "180", "60", "0.400"])
        m = before; m["product"].pop("freightTemplateId")
        codes = {r["componentCode"] for r in cli.build_publish_schema(m)}
        self.assertFalse(codes & {"WareLength", "WareWide", "WareHeight", "WareWeight", "WareTransport"})

    def test_real_multi_sku_builder_keeps_prices_stock_codes_and_color_bindings(self):
        cli = module("jdo_listing_mvp"); m = manifest(); original = copy.deepcopy(m)
        rows = {r["componentCode"]: r.get("value") for r in cli.build_publish_schema(m)}
        skus = [{r["componentCode"]: r.get("value") for r in sku["value"]} for sku in rows["SKUS"]]
        self.assertEqual([(s["SkuJdprice"], s["SkuStockNum"], s["SkuVendorSku"]) for s in skus],
                         [("10.50", 12, "A-1"), ("20.75", 8, "A-2")])
        props = [{p["key"]: p["value"] for p in s["SkuMainImage"][0]["properties"]} for s in skus]
        self.assertEqual([(p["imgUrl"], p["colorId"]) for p in props],
                         [("jfs/a.jpg", "color-a"), ("jfs/b.jpg", "color-b")])
        self.assertEqual(m, original)
        editor = [{p["key"]: p["value"] for p in r["properties"]} for r in rows["WareEditor"]]
        self.assertEqual([e["userAgent"] for e in editor], ["pc", "mobile"])
        self.assertTrue(all("detail.jpg" in e["desc"] for e in editor))

    def test_image_patch_preserves_other_groups_and_verifies_price_safety(self):
        p = module("image_patch_update"); before = detail(); original = copy.deepcopy(before)
        body, summary = p.build_image_patch_payload(before, {"jfs/a.jpg": "jfs/new-a.jpg"})
        self.assertEqual(body["opType"], 3); self.assertEqual(summary["replaced"], 1)
        self.assertEqual(before, original)
        groups = [json.loads(r["value"]) for r in body["patchOperationList"]]
        props = [{p["key"]: p["value"] for p in g["value"][0]["properties"]} for g in groups]
        self.assertEqual([(p["imgUrl"], p["colorId"]) for p in props],
                         [("jfs/new-a.jpg", "color-a"), ("jfs/b.jpg", "color-b")])
        after = copy.deepcopy(before); after["material"]["mainImages"][0]["imageInfoList"][0]["imgUrl"] = "jfs/new-a.jpg"
        self.assertEqual(p.verify_patch(before, after, {"jfs/a.jpg": "jfs/new-a.jpg"}), [])
        after["skuList"][1]["priceInfo"]["jdPrice"] = 99
        self.assertTrue(any("price changed" in e for e in p.verify_patch(before, after, {})))

    def test_default_missing_profile_and_cross_profile_are_rejected(self):
        cli = module("jdo_listing_mvp")
        for profile in ("", "default", "bad profile"):
            with self.subTest(profile=profile), self.assertRaises(cli.JdoError): cli.configure_jdo_profile(profile)
        cli.configure_jdo_profile("pop-test")
        self.assertEqual(cli.profile_bound_arguments(["invoke"]), ["invoke", "--profile", "pop-test"])
        with self.assertRaises(cli.JdoError): cli.profile_bound_arguments(["invoke", "--profile", "pop-other"])
        with self.assertRaises(cli.JdoError): cli.require_verified_jdo_store()
        cli.mark_jdo_store_verified("pop-test", 42, "测试")
        cli.configure_jdo_profile("pop-other")
        with self.assertRaises(cli.JdoError): cli.require_verified_jdo_store()

    def test_write_store_drift_is_detected_before_process_execution(self):
        cli = module("jdo_listing_mvp"); cli.configure_jdo_profile("pop-test")
        cli.mark_jdo_store_verified("pop-test", 42, "测试")
        with patch.object(cli, "get", return_value={"data": {"venderId": 43, "shopBaseInfo": {"shopName": "另一店"}}}), \
                patch.object(cli.subprocess, "run", side_effect=AssertionError("write must not run")):
            with self.assertRaises(cli.JdoError): cli.run_jdo(["invoke", "--method", "POST"])

    def test_store_and_package_contract_reject_default_escape_and_unknown_replay(self):
        pc = module("photo_contract")
        with self.assertRaises(ValueError): pc.check_store({"profile": "default", "venderId": 42, "shopName": "测试"})
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError): pc.package_path(Path(t), "../private")
        for status in ("SUBMITTING", "UNKNOWN", "SUCCEEDED"):
            with self.subTest(status=status), self.assertRaises(pc.ReconcileRequired): pc.can_submit({"status": status})

    def test_dependency_discovery_is_sibling_only_and_missing_linker_is_explicit(self):
        paths = module("skill_paths")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); listing = root / "package" / "mature" / "listing"; listing.mkdir(parents=True)
            private = root / "home" / ".agents" / "skills" / "jingmai-cli-linker"; private.mkdir(parents=True)
            self.assertIsNone(paths.installed_skill_dir("jingmai-cli-linker", skill_root=listing, home=root / "home"))
            sibling = listing.parent / "jingmai-cli-linker"; sibling.mkdir()
            self.assertEqual(paths.installed_skill_dir("jingmai-cli-linker", skill_root=listing), sibling)
            for bad in ("../private", "/outside"):
                with self.assertRaises(ValueError): paths.installed_skill_dir(bad, skill_root=listing)
        pl = module("photo_listing")
        with patch.object(pl, "installed_skill_dir", return_value=None):
            with self.assertRaisesRegex(ValueError, "jingmai-cli-linker.*mature"): pl.ensure_shop("42")

    def test_existing_explicit_store_verification_does_not_require_linker(self):
        pl = module("photo_listing"); store = {"profile": "pop-test", "venderId": 42, "shopName": "测试"}
        with patch.object(pl, "ensure_shop", side_effect=AssertionError("no auth helper")), \
                patch.object(pl.cli, "get", return_value={"data": {"venderId": 42, "shopBaseInfo": {"shopName": "测试", "type": 0, "status": 1}}}):
            self.assertEqual(pl.verify_store(store), store)
            self.assertEqual(pl.cli.require_verified_jdo_store(), store)

    def test_merchant_adapter_uses_real_references_and_no_old_key_fallback(self):
        pg = module("photo_generation"); company = module("company_jpeg_edits")
        class Boundary:
            def __init__(self, key=None): self.key = key
            def edit(self, *, prompt, images, size="1024x1024"):
                if prompt != "merchant prompt" or (len(images) != 1 or not isinstance(images[0], Path) or images[0].read_bytes() != jpeg()) or size != "1024x1024":
                    raise AssertionError("wrong merchant boundary")
                return jpeg()
        boundary = types.ModuleType("heideng_merchant.mature_image")
        boundary.MerchantImageClient = Boundary
        boundary.merchant_key = lambda: os.environ.get("HEIDENG_MERCHANT_LTS4AI_API_KEY", "")
        with tempfile.TemporaryDirectory() as t, patch.dict(sys.modules, {boundary.__name__: boundary}), \
                patch.dict(os.environ, {"JD_LLM_API_KEY": "ignored", "GPT_IMAGE2_API_KEY": "ignored"}, clear=True):
            src = Path(t) / "photo.jpg"; src.write_bytes(jpeg())
            with self.assertRaises(ValueError): pg.key_from_environment()
            self.assertEqual(company.resolve_api_key(), "")
            with patch.dict(os.environ, {"HEIDENG_MERCHANT_LTS4AI_API_KEY": "offline-sentinel"}):
                self.assertEqual(pg.key_from_environment(), "offline-sentinel")
                self.assertEqual(pg.CompanyPhotoClient("offline-sentinel").edit(model="gpt-image-2.5", prompt="merchant prompt", photos=[src], size="1024x1024"), jpeg())
                raw, meta = company.CompanyClient("offline-sentinel").edit(model="gpt-image-2.5", prompt="merchant prompt", source=src)
                self.assertEqual(raw, jpeg()); self.assertEqual(meta["provider"], "lts4ai")
            with self.assertRaises(ValueError): pg.CompanyPhotoClient("offline-sentinel").edit(model="old-model", prompt="x", photos=[src], size="1024x1024")

    def test_photo_receipt_caches_success_and_never_retries_unknown_or_redo(self):
        pg = module("photo_generation")
        class LocalClient:
            capacity = 1
            def __init__(self, fail=False): self.calls = 0; self.fail = fail
            def edit(self, **kw):
                self.calls += 1
                if self.fail: raise TimeoutError("private provider output must not enter receipt")
                if kw["model"] != "gpt-image-2.5": raise AssertionError("alternate provider")
                return jpeg()
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = root / "photo.jpg"; src.write_bytes(jpeg())
            tasks = [{"id": "main", "prompt": "x", "photos": [str(src)], "size": "1024x1024", "role": "main"}]
            client = LocalClient(); self.assertEqual(pg.generate_tasks(tasks, root / "ok", client=client)["successCount"], 1)
            pg.generate_tasks(tasks, root / "ok", client=client); self.assertEqual(client.calls, 1)
            failed = LocalClient(True); result = pg.generate_tasks(tasks, root / "unknown", client=failed)
            self.assertEqual(result["unknownCount"], 1)
            for redo in (None, ["main"]):
                with self.assertRaises(pg.GenerationUnknown): pg.generate_tasks(tasks, root / "unknown", client=failed, redo=redo)
            self.assertEqual(failed.calls, 1)
            self.assertNotIn("private provider", (root / "unknown" / "generation.json").read_text())

    def test_company_receipt_never_replays_attempted_generation(self):
        c = module("company_jpeg_edits")
        class Broken:
            def edit(self, **kwargs): raise c.SafeGenerationError("TimeoutError")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = root / "photo.jpg"; src.write_bytes(jpeg()); sha = hashlib.sha256(src.read_bytes()).hexdigest()
            plan = {"prompt": "x", "sources": [{"source": str(src), "sha": sha, "model": "gpt-image-2.5"}]}
            with self.assertRaises(RuntimeError): c.generate_plan(plan, root, client=Broken())
            with self.assertRaisesRegex(RuntimeError, "reconcile"): c.generate_plan(plan, root, client=Broken())
            self.assertEqual(json.loads((root / "generation.json").read_text())[sha]["attempts"], 1)

    def test_legacy_video_producer_is_blocked_not_searched_or_called(self):
        v = module("video_handoff")
        with patch.object(v.subprocess, "run", side_effect=AssertionError("no producer")):
            self.assertIsNone(v.find_video_skill(env={"JD_MAIN_VIDEO_BATCH_SKILL": "private"}))
            with tempfile.TemporaryDirectory() as t:
                p = Path(t) / "manifest.json"; p.write_text(json.dumps({"video": {"localPath": "video.mp4"}}))
                with self.assertRaisesRegex(v.HandoffError, "external.video.*protocol"): v.check_handoff(p)
        pipe = module("jd_product_pipeline")
        with self.assertRaisesRegex(pipe.PipelineError, "external.video.*protocol"):
            pipe.automate_main_video(state_path=Path("unused"), state={}, folder=Path("unused"), source={"video": {"localPath": "video.mp4"}}, product_id=1, transcode_attempts=1, review_attempts=1, interval=0)

    def test_video_upload_binding_builders_are_independently_reusable(self):
        p = module("jd_product_pipeline")
        self.assertEqual(p.video_upload_url_params(Path("video.mp4"), 123, 7),
                         {"fileName": "video.mp4", "fileSize": 123, "videoType": 1, "jdVideoId": 7, "breakPointFlag": True})
        body = p.build_video_binding_body(product_id=12, sku_id=34, video={"indexImage": "cover", "videoId": 56, "jdVideoId": 78, "videoName": "v", "duration": 10}, tag={"sort": 1, "tagId": 2, "tagName": "产品展示"})
        self.assertEqual(body["skuMaterials"][0]["skuId"], 34)
        self.assertTrue(p.video_relation_audit([{"skuId": 34, "videoId": 56, "relationStatus": 4}], [34], 56)["allApproved"])
        self.assertFalse(p.video_relation_audit([], [34], 56)["allApproved"])

    def test_runtime_defaults_imports_and_entrypoint_help_are_offline(self):
        provenance = json.loads((BUNDLE / "provenance.json").read_text())
        with tempfile.TemporaryDirectory() as t:
            env = sanitized_env(Path(t))
            code = """
import sys, pathlib, socket, importlib
sys.path[:0] = [sys.argv[1], sys.argv[2]]
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('no network'))
for path in pathlib.Path(sys.argv[1]).glob('*.py'): importlib.import_module(path.stem)
import jdo_listing_mvp as cli, jd_product_pipeline as pipe
for path in (cli.REFERENCE, cli.STORE_CONFIG, cli.JDO_RUNTIME, pipe.OUTPUT_ROOT, pipe.RULES):
 assert str(path).startswith(str(pathlib.Path.home() / '.heideng-merchant')), path
assert not any('image_generation' in n for n in sys.modules)
print('offline imports and merchant defaults OK')
"""
            run = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS), str(ROOT)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            for entry in provenance["entrypoints"]:
                with self.subTest(entry=entry):
                    run = subprocess.run([sys.executable, "-B", str(BUNDLE / entry), "--help"], cwd=t, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn("usage:", run.stdout)
            self.assertEqual(list(Path(t).iterdir()), [])

    def test_photo_builder_uses_verified_facts_and_all_skus_with_real_detail_gate(self):
        pl = module("photo_listing"); pc = module("photo_contract"); pg = module("photo_generation"); dp = module("detail_pages")
        reference = {"category": {"id": 1}, "brands": [{"brandId": -1}],
            "schema": {"componentList": [{"componentCode": "SKUS", "childrenComponents": [
                {"componentCode": "VenderCategoryValue", "childrenComponents": [
                    {"componentCode": "sale-prop-2", "componentTitle": "spec", "extra": {"dim": 1}}]}]}]},
            "componentCatalog": [], "media": {"defaultCategoryId": 1, "zoneId": "z", "categories": [{"categoryId": 1}]}}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for n in ("photo.jpg", "main.jpg", "sku-a.jpg", "sku-b.jpg"): (root / n).write_bytes(jpeg((800, 800)))
            m = pc.initial_manifest({"profile": "pop-test", "venderId": 42, "shopName": "test"}, ["photo.jpg"], "Test rack")
            m["facts"] = {"confirmed": True, "title": "Test rack", "categoryId": 1, "brandId": -1,
                "sellingPoints": ["verified real product"], "packageLengthMm": 100, "packageWidthMm": 80,
                "packageHeightMm": 30, "weightKg": "0.100", "freightTemplateId": 1, "sevenDayReturnCode": "1",
                "categoryAttributes": [], "skus": [{"key": "one", "spec": "white", "jdPrice": "10.50", "stock": 12, "skuAttributes": []},
                    {"key": "two", "spec": "black", "jdPrice": "20.75", "stock": 8, "skuAttributes": []}]}
            m["mainImages"] = [{"localPath": "main.jpg", "role": "white"}]
            m["variants"] = [{"key": "one", "skuImage": {"localPath": "sku-a.jpg"}}, {"key": "two", "skuImage": {"localPath": "sku-b.jpg"}}]
            plan = dp.build_detail_plan(m, root, identity_rules="real product only", style="clean")
            pg.atomic_json(root / "detail-plan.json", plan)
            m["detailImages"] = []
            for i, mod in enumerate(plan["modules"]):
                rnd = random.Random(100 + i); small = Image.new("RGB", (9, 8))
                small.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(72)])
                p = root / mod["outputFile"]; p.parent.mkdir(parents=True, exist_ok=True)
                small.resize((790, 1185), Image.Resampling.NEAREST).save(p, "JPEG", quality=90)
                m["detailImages"].append({"id": mod["id"], "module": mod["kind"], "localPath": mod["outputFile"], "sha256": pg.sha(p), "skuKeys": mod["skuKeys"], "onlineUrl": ""})
            original = copy.deepcopy(m); listing = pl.build_listing(m, root, reference)
            self.assertEqual([(s["skuKey"], s["jdPrice"], s["stock"]) for s in listing["skus"]], [("one", "10.50", 12), ("two", "20.75", 8)])
            self.assertEqual([i["localPath"] for i in listing["images"] if i["role"] == "sku_main"], ["sku-a.jpg", "sku-b.jpg"])
            self.assertEqual(listing["product"]["weightKg"], "0.100"); self.assertEqual(m, original)
            m["facts"]["confirmed"] = False
            with self.assertRaisesRegex(ValueError, "Missing verified facts"): pl.build_listing(m, root, reference)

    def test_matrix_unknown_request_cannot_replay_even_with_explicit_redo(self):
        mx = module("matrix_listing"); company = module("company_jpeg_edits")
        class Broken:
            calls = 0
            def __init__(self, key): pass
            def edit(self, **kwargs):
                Broken.calls += 1
                raise company.SafeGenerationError("TimeoutError")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); (root / "source-main").mkdir(); (root / "source-main" / "photo.jpg").write_bytes(jpeg())
            (root / "source-apply.json").write_text(json.dumps({"productInfo": {"productName": "Test rack"}}))
            (root / "variants.json").write_text(json.dumps({"variants": {"a": {"suffix": "clean"}}}))
            (root / "source-main-manifest.json").write_text(json.dumps([{"stem": "photo", "file": "photo.jpg"}]))
            args = types.SimpleNamespace(run=str(root), variants=None, variant="a", only=None, redo=False)
            with patch.object(mx, "resolve_api_key", return_value="offline-sentinel"), patch.object(company, "CompanyClient", Broken):
                self.assertEqual(mx.command_generate(args), 2)
                with self.assertRaisesRegex(mx.MatrixError, "unknown.*reconcile"): mx.command_generate(args)
                args.only = ["photo"]; args.redo = True
                with self.assertRaisesRegex(mx.MatrixError, "unknown.*reconcile"): mx.command_generate(args)
            self.assertEqual(Broken.calls, 1)
            record = json.loads((root / "generated" / "a" / "ledger.json").read_text())["photo"]
            self.assertEqual(record["status"], "UNKNOWN")

    def test_real_parent_image_contract_is_compatible_without_live_generation(self):
        pg = module("photo_generation"); company = module("company_jpeg_edits")
        from heideng_merchant import mature_image
        class LocalCore:
            def __init__(self, key, **options):
                if options != {"base_url": "https://api.lts4ai.com/v1", "model": "gpt-image-2.5", "retries": 0}:
                    raise AssertionError("unexpected provider configuration")
            def edit(self, prompt, references, size, directory):
                if len(references) != 1 or not Path(references[0].path).is_file(): raise AssertionError("invalid real reference")
                p = Path(directory) / "result.jpg"; p.write_bytes(jpeg())
                return types.SimpleNamespace(path=p)
        with tempfile.TemporaryDirectory() as t, patch.object(mature_image.lts4ai_client, "SfImage2Client", LocalCore):
            src = Path(t) / "photo.jpg"; src.write_bytes(jpeg())
            raw = pg.CompanyPhotoClient("offline-sentinel").edit(model="gpt-image-2.5", prompt="x", photos=[src], size="1024x1024")
            with Image.open(io.BytesIO(raw)) as im: self.assertEqual(im.format, "JPEG")
            raw, _ = company.CompanyClient("offline-sentinel").edit(model="gpt-image-2.5", prompt="x", source=src)
            with Image.open(io.BytesIO(raw)) as im: self.assertEqual(im.size, (1024, 1024))

    def test_image_patch_cli_verifies_explicit_store_before_updates(self):
        p = module("image_patch_update"); cli = p.cli
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); config = root / "store.json"; urls = root / "urls.json"
            store = {"profile": "pop-test", "venderId": 42, "shopName": "test"}
            config.write_text(json.dumps({"store": store})); urls.write_text(json.dumps({"jfs/a.jpg": "jfs/new-a.jpg"}))
            args = ["image_patch_update.py", "--profile", "pop-test", "--store-config", str(config), "--url-map", str(urls), "--product-ids", "123", "--confirm", "PATCH_PRODUCT_IMAGES"]
            def offline_update(*args):
                self.assertEqual(cli.require_verified_jdo_store(), store)
                return {"ok": True, "productId": 123}
            data = {"data": {"venderId": 42, "shopBaseInfo": {"shopName": "test", "type": 0, "status": 1}}}
            with patch.object(sys, "argv", args), patch.object(cli, "get", return_value=data), patch.object(p, "patch_product", offline_update):
                self.assertEqual(p.main(), 0)
            store["profile"] = "pop-other"; config.write_text(json.dumps({"store": store}))
            with patch.object(sys, "argv", args), patch.object(cli, "get", return_value=data), patch.object(p, "patch_product", side_effect=AssertionError("no wrong-store update")):
                with self.assertRaises(cli.JdoError): p.main()

    def test_image_patch_default_body_uses_merchant_namespace(self):
        p = module("image_patch_update"); before = detail(); after = copy.deepcopy(before)
        after["material"]["mainImages"][0]["imageInfoList"][0]["imgUrl"] = "jfs/new-a.jpg"
        with tempfile.TemporaryDirectory() as t:
            state = Path(t) / "mature" / "listing"
            def offline_transfer(**kwargs):
                body_path = kwargs["body_path"]
                self.assertTrue(body_path.is_relative_to(state))
                body = json.loads(body_path.read_text())
                self.assertEqual(body["applyId"], "123"); self.assertEqual(body["opType"], 3)
                return {"data": {"applyId": 123}}
            with patch.object(p.cli, "STATE_ROOT", state), patch.object(p, "apply_detail", side_effect=[before, after]), \
                    patch.object(p.cli, "run_jdo_large", offline_transfer), patch.object(p.time, "sleep"):
                result = p.patch_product(123, {"jfs/a.jpg": "jfs/new-a.jpg"}, "PATCH_PRODUCT_IMAGES")
            self.assertTrue(result["ok"])
            self.assertEqual(len(list(state.rglob("patch_123.json"))), 1)

    def test_brand_submit_unknown_transport_outcome_is_not_retried(self):
        b = module("set_product_brand"); attempts = []
        def lost_response():
            attempts.append(1)
            raise b.cli.JdoError("SSL EOF")
        with patch.object(b.time, "sleep"):
            with self.assertRaises(b.cli.JdoError): b.with_retries(lost_response, 4, 10, "submit 123")
        self.assertEqual(len(attempts), 1)

    def test_existing_sku_full_edit_preserves_bindings_ids_and_omits_stock(self):
        b = module("set_product_brand"); source = detail()
        for i, sku in enumerate(source["skuList"]):
            sku.update(outerId="code-" + str(i), stockNum=10, skuEnableStatus=1, saleAttrs=[
                {"attrId": "1001", "attrName": "color", "attrValueAlias": "white" if i == 0 else "black",
                 "attrValues": "color-a" if i == 0 else "color-b", "mappingId": "", "attrValuesSeqNo": i + 1}])
        original = copy.deepcopy(source); body = b.build_edit_body(source, 17)
        rows = {r["componentCode"]: r.get("value") for r in json.loads(body["schema"])}
        skus = [{r["componentCode"]: r.get("value", r.get("properties")) for r in s["value"]} for s in rows["SKUS"]]
        self.assertEqual([(s["SkuUUid"], s["SkuId"], s["SkuJdprice"], s["SkuVendorSku"]) for s in skus],
                         [("1", 1, "10.5", "code-0"), ("2", 2, "20.75", "code-1")])
        self.assertTrue(all("SkuStockNum" not in s for s in skus))
        props = [{p["key"]: p["value"] for p in s["VenderCategoryValue"][0]["properties"]} for s in skus]
        self.assertEqual([p["mappingId"] for p in props], ["color-a", "color-b"])
        self.assertEqual(source, original)

    def test_photo_store_verification_rejects_inactive_or_non_pop_store(self):
        pl = module("photo_listing"); store = {"profile": "pop-test", "venderId": 42, "shopName": "test"}
        for shop_type, status in ((1, 1), (0, 2)):
            data = {"data": {"venderId": 42, "shopBaseInfo": {"shopName": "test", "type": shop_type, "status": status}}}
            with self.subTest(type=shop_type, status=status), patch.object(pl.cli, "get", return_value=data):
                with self.assertRaises(ValueError): pl.verify_store(store)
                with self.assertRaises(pl.cli.JdoError): pl.cli.require_verified_jdo_store()

    def test_legacy_company_boundary_retains_original_start_pacing(self):
        company = module("company_jpeg_edits")
        class LocalImage:
            def __init__(self, key): pass
            def edit(self, **kwargs): return jpeg()
        boundary = types.ModuleType("heideng_merchant.mature_image"); boundary.MerchantImageClient = LocalImage
        clock = [0.0]; delays = []
        def sleep(seconds): delays.append(seconds); clock[0] += seconds
        with tempfile.TemporaryDirectory() as t, patch.dict(sys.modules, {boundary.__name__: boundary}):
            src = Path(t) / "photo.jpg"; src.write_bytes(jpeg())
            client = company.CompanyClient("offline-sentinel", clock=lambda: clock[0], sleep=sleep)
            for _ in range(2): self.assertEqual(client.edit(model="gpt-image-2.5", prompt="x", source=src)[0], jpeg())
        self.assertEqual(delays, [1.0])

    def test_standard_provenance_covers_every_bundled_file_and_hash(self):
        p = json.loads((BUNDLE / "provenance.json").read_text())
        self.assertEqual(p["schemaVersion"], 1); self.assertEqual(p["license"], "MIT")
        self.assertEqual(p["repository"], "ctzlyj/jingmai-hot-product-mover-skill")
        self.assertEqual(p["upstreamCommit"], "3ee08af2f3970f88d39756f1906040efe75117dc")
        self.assertEqual(p["upstreamVersion"], "1.2.6")
        self.assertIn("LICENSE", p["files"])
        actual = {str(f.relative_to(BUNDLE)).replace("\\", "/") for f in BUNDLE.rglob("*") if f.is_file() and f.name != "provenance.json" and "__pycache__" not in f.parts}
        self.assertEqual(actual, set(p["files"]))
        for relative, info in p["files"].items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((BUNDLE / relative).read_bytes()).hexdigest(), info["sha256"])
                self.assertEqual(len(info["upstreamSha256"]), 64)
                self.assertEqual(info["adapted"], info["sha256"] != info["upstreamSha256"])
                self.assertFalse(relative.startswith(("config/", "outputs/", "tests/")))


if __name__ == "__main__":
    unittest.main()
