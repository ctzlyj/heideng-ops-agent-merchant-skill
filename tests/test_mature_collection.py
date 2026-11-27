"""Offline contracts for the bounded, tracked MIT collector migration."""
import ast
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "mature" / "collection"
SCRIPTS = COLLECTION / "scripts"
COMMIT = "90ef8dfd8455848d539d22560ae26ba8bac52e2a"
PURE = ("collector_guard.py", "package_contract.py", "workbook_writer.py",
        "checkpoint_status.py", "media_evidence.py", "media_guard.py", "jpeg_cache.py",
        "resume_policy.py", "request_policy.mjs", "browser_worker.mjs", "native_page.mjs",
        "runner_lock.mjs", "variant_queue.py", "batch_driver/checkpoint_io.py")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def state_for(home, root):
    return home / "mature" / "collection" / "batches" / digest(str(root.resolve()).encode())


@contextlib.contextmanager
def modules(home, output):
    names = [p.stem for p in SCRIPTS.glob("*.py")]
    saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    old_path = sys.path[:]
    env = {"HEIDENG_MERCHANT_HOME": str(home), "HEIDENG_COLLECTION_ROOT": str(output),
           "JD_COLLECTOR_ROOT": str(home / "poison-root"),
           "JD_COLLECTOR_STATE_DIR": str(home / "poison-state")}
    try:
        sys.path.insert(0, str(SCRIPTS))
        with patch.dict(os.environ, env), patch.object(sys, "argv", ["offline-test"]):
            yield importlib.import_module
    finally:
        sys.path[:] = old_path
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def main_data(price="8"):
    return {"ok": True, "login": True, "responseSku": "10000000000001",
            "title": "Synthetic product", "p": "20", "pp": price,
            "priceSource": "warePriceGatherVO.finalPrice", "realSpuId": "20000000000001",
            "carousel": [{"u": "jfs/synthetic-main.jpg", "v": []}], "crumbs": [], "attrs": [],
            "colorSize": [{"dim": 1, "buttons": [
                {"no": "2", "text": "B", "skuId": "10000000000002", "skuList": ["10000000000002"]},
                {"no": "1", "text": "A", "skuId": "10000000000001", "skuList": ["10000000000001"]}]}]}


class MatureCollectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((SCRIPTS / "collector_guard.py").is_file(), "tracked mature collector not migrated")

    def node(self, code, env=None):
        if not shutil.which("node"):
            self.skipTest("Node is required for browser-boundary contracts")
        child = dict(os.environ)
        for key in list(child):
            if key.startswith(("JD_COLLECTOR_", "HEIDENG_COLLECTION_")):
                child.pop(key)
        child.update(env or {})
        result = subprocess.run(["node", "--input-type=module", "-e", code],
                                capture_output=True, text=True, encoding="utf-8", env=child,
                                cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def fixture(self, load, home, output):
        from PIL import Image
        g = load("collector_guard"); p = load("package_live")
        stage = state_for(home, output); stage.mkdir(parents=True, exist_ok=True)
        data = main_data()
        for sku, price in [("10000000000001", "8"), ("10000000000002", "9")]:
            row = copy.deepcopy(data); row.update(responseSku=sku, pp=price)
            g.atomic_json(stage / "data" / (sku + ".json"), {"source": "live_signed_page", "data": row})
        g.atomic_json(stage / "keyword_tasks.json", {"synthetic": [{"pid": data["responseSku"], "row": 2}]})
        g.atomic_json(stage / "details_ordered" / (data["realSpuId"] + ".json"), [])
        image = io.BytesIO(); Image.new("RGB", (4, 4), "red").save(image, "JPEG")
        cache = stage / "asset_cache" / (digest(p.image_url(data["carousel"][0]["u"]).encode()) + ".jpg")
        cache.parent.mkdir(parents=True); cache.write_bytes(image.getvalue())
        return g, p, stage

    def package(self, load, home, output):
        g, p, stage = self.fixture(load, home, output)
        with patch("requests.get", side_effect=AssertionError("network forbidden")):
            plan = p.plan_product("synthetic", {"pid": "10000000000001", "row": 2}, {})
            self.assertEqual(plan["state"], "AWAITING_WORKBOOK")
            p.write_workbook(plan["spec"])
            receipt = p.finalize(plan)
        return g, p, stage, receipt

    def test_original_functions_match_pinned_upstream_ast(self):
        # Development-time hashes from the pinned Git blobs; no upstream lookup at runtime.
        expected = {'scripts/package_live.py::live_data': '267369c319f8f8d58ddeb0d5f1a7b33b71d85eea807665e240beadbe321ef3c4',
 # Merchant download adapter plus the adopted per-SKU priceSource receipt.
 'scripts/package_live.py::plan_product': 'bb94d3c5c0929e05beebcc356d41d02e2a04bd3872b2d5b28a88d8d87a1ce241',
 'scripts/package_live.py::finalize': 'deda0d20cfa6e19987c2b635a771917984ebc555919fadcd369a500e54a6366d',
 'scripts/package_live.py::verify_table': 'b0e8427a090121c7bb417042dbd077d0ecb7519db2779d85a85fb6361f6d4583',
 'scripts/package_live.py::_detail_jobs': 'cccc119294811db5f99e6662c46d4a693101917bbda1e03319201cb574a1fa2e',
 'scripts/package_live.py::details': '703b1814f90a4220d711ff7ee8d5d63ba4ba49206e64eb9bb11eb56a26af0e56',
 # Verification entry as adopted with the shared collection price fallback.
 'scripts/verify_batch.py::run': '51802b25647323a05b7b7908ed2c0210210852cb78ac5f91e7a22dbdb037f9d9',
 'scripts/prepare_batch.py::parse_batch': '59ab1406dd43a53c81b6c17a2552fe1fe36671bb3682ad940205e5353c5fde10',
 'scripts/prepare_batch.py::parse_rows_flat': '829e74ffc37ce916e772778c54aeb85be27e251dc8308823a8e2c947abbed52b',
 'scripts/prepare_batch.py::parse_rows_listing': '2490a05a8065b14723d3b99a95fe37bec9510207f21fa22a55e8e0e403393ead',
 'scripts/prepare_batch.py::parse_rows_alternate': 'b7de9ed83d60565554811cdeb9ba4a2ce0abce2861a11dba829a8bbf682b58d9',
 'scripts/prepare_batch.py::parse_rows_standard': '72d9155f2cc38bbe5260558007dd801090400937a0e2c3a09c4c9be79f202bff',
 'scripts/deliver_batch.py::verified_items': '35f97233b8f0cf5c9e22a8c5b10a59dd21414b70bf924457f012c31d6446b106',
 'scripts/deliver_batch.py::delivered_keys': 'ba7a0dbbdd7519e5ea38cf442ca8fb67541b108597f9d98e63066dcfb6124481',
 'scripts/deliver_batch.py::incremental_items': 'f8e5f9d046c86f79bc57bcd659237337d951a43b2f81f4d4084403210070710f',
 'scripts/deliver_batch.py::write_manifest': '85db00a8270fe5615897bd06b88d9e4a1eaa9dcd09bd4739903339101cd9fe81',
 'scripts/deliver_batch.py::write_zip': 'ea79778bde1617c482d364e8bf7636471300e2409335036bf5bb969409bc9459',
 'scripts/deliver_batch.py::keyword_bins': '446986b30833b356be319b8edbd24eacd9ccde101635322957f0d065e59a7042',
 'scripts/asset_paths.py::safe_name': '743b6cb6b7d2d189b2877b17cdad5775d4b3991a9bb9fe11057ef72423e04960',
 'scripts/asset_paths.py::image_url': '9c6af2f4f4b09645442ace3a8991cfe626812c9c236c561c0b84d264709ecc24',
 'scripts/asset_paths.py::get_public': '39d77095b2d5b94d0ab0f16fcd544ee6ff6504beda9fece945a24280f23fd167',
 'scripts/asset_paths.py::save_jpeg': 'd11b548d18bdce89fc6c6c42a1271373b6e8986b67e771a54600bd5a27d89cee',
 'scripts/asset_paths.py::final_state': '52488eea3a51009a327682890b2fa7b528fc5d40e3cf3cf139c31fe59ca072eb'}
        for key, wanted in expected.items():
            path, name = key.split("::")
            tree = ast.parse((COLLECTION / path).read_text(encoding="utf-8-sig"))
            node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
            # The pinned hashes use Python 3.12's representation. A 3.11 definition
            # has the same semantics but predates the empty type_params field.
            for definition in ast.walk(node):
                if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and 'type_params' not in definition._fields:
                    definition._fields = (*definition._fields, 'type_params')
                    definition.type_params = []
            self.assertEqual(digest(ast.dump(node, include_attributes=False).encode()), wanted, key)

    def test_parent_provenance_and_complete_inventory(self):
        manifest = json.loads((COLLECTION / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["repository"], "ctzlyj/jd-hot-link-collector")
        self.assertEqual(manifest["upstreamCommit"], COMMIT)
        self.assertEqual(manifest["upstreamVersion"], "1.0.4")
        self.assertEqual(manifest["license"], "MIT")
        actual = {p.relative_to(COLLECTION).as_posix() for p in COLLECTION.rglob("*")
                  if p.is_file() and p.name != "provenance.json" and "__pycache__" not in p.parts}
        self.assertEqual(set(manifest["files"]), actual)
        for relative, record in manifest["files"].items():
            if record.get("upstreamSha256") is not None:
                self.assertRegex(record["upstreamSha256"], r"^[0-9a-f]{64}$")
            else:
                self.assertTrue(record.get("reason"))
            self.assertEqual(record["sha256"], digest((COLLECTION / relative).read_bytes()))
            self.assertEqual(record["adapted"], bool(record.get("upstreamSha256")) and record["sha256"] != record["upstreamSha256"])
        for relative in ["LICENSE", "requirements.txt"] + ["scripts/" + p for p in PURE]:
            self.assertFalse(manifest["files"][relative]["adapted"], relative)
        required={"scripts/prepare_batch.py", "scripts/collect_signed.mjs", "scripts/package_live.py",
                  "scripts/verify_batch.py", "scripts/deliver_batch.py", "scripts/click_collector.mjs",
                  "scripts/batch_driver/start_new_batch.py", "scripts/batch_driver/batch_driver.py"}
        self.assertTrue(required <= set(manifest["entrypoints"]))
        self.assertTrue(set(manifest["entrypoints"]) <= set(manifest["files"]))

    def test_runtime_has_no_o2_or_personal_skill_discovery(self):
        for p in SCRIPTS.rglob("*"):
            if p.suffix not in {".py", ".mjs"}: continue
            text = p.read_text(encoding="utf-8")
            for bad in ("@jd/webcli", ".joycode", ".agents", ".codex/skills", "Path.home()", "npx", "o2 "):
                self.assertNotIn(bad, text, str(p))
        self.assertNotIn("context.wcli", (SCRIPTS / "collect_signed.mjs").read_text(encoding="utf-8"))

    def test_original_projection_price_and_identity(self):
        with tempfile.TemporaryDirectory() as t, modules(Path(t), Path(t)/"output") as load:
            g = load("collector_guard")
            raw = {"isLogin": True, "pageConfigVO": {"skuid": "10000000000001"},
                   "skuHeadVO": {"skuTitle": "Synthetic product"}, "price": {"p": "20"},
                   "wareInfoReadMap": {"realSpuId": "20000000000001"},
                   "mainImageVO": {"carouselArea": [{"imageUrl": "jfs/main.jpg"}]},
                   "bestPromotion": {"purchasePrice": "10"}, "warePriceGatherVO": {"priceItemList": [
                       {"priceType": "finalPrice", "hitLine": True, "price": "19"},
                       {"priceType": "finalPrice", "hitLine": False, "price": "8"}]}}
            data = g.signed_response_projection(raw)
            self.assertEqual(data["pp"], "8"); self.assertEqual(data["priceSource"], "warePriceGatherVO.finalPrice")
            self.assertIs(g.validate_main("10000000000001", data), data)
            raw.pop("warePriceGatherVO")
            self.assertEqual(g.signed_response_projection(raw)["pp"], "10")
            for patch_data, reason in [({"pp": None}, "ARRIVAL_PRICE_MISSING"),
                                       ({"responseSku": "other"}, "SKU_ID_MISMATCH"),
                                       ({"login": False}, "LOGIN_REQUIRED")]:
                with self.assertRaisesRegex(g.CollectionError, reason):
                    g.validate_main("10000000000001", dict(data, **patch_data))

    def test_original_order_real_intersection_and_missing_order(self):
        with tempfile.TemporaryDirectory() as t, modules(Path(t), Path(t)/"output") as load:
            g = load("collector_guard")
            dims = [{"dim": 1, "buttons": [{"no": "2", "text": "blue", "skuList": ["c"]},
                    {"no": "1", "text": "red", "skuList": ["a", "b"]}]},
                    {"dim": 2, "buttons": [{"no": "2", "text": "small", "skuList": ["a"]},
                    {"no": "1", "text": "large", "skuList": ["b", "c"]}]}]
            self.assertEqual([(r["sku"], r["spec1"], r["spec2"]) for r in g.ordered_variants("a", dims)],
                             [("b", "red", "large"), ("a", "red", "small"), ("c", "blue", "large")])
            dims[0]["buttons"][0].pop("no")
            with self.assertRaisesRegex(g.CollectionError, "FRONTEND_ORDER_MISSING"):
                g.ordered_variants("a", dims)

    def test_original_checkpoint_reuses_valid_only_and_halt(self):
        with tempfile.TemporaryDirectory() as t, modules(Path(t), Path(t)/"output") as load:
            g = load("collector_guard"); c = g.Checkpoint(state_for(Path(t), Path(t)/"output"))
            self.assertFalse(c.has("10000000000001")); c.put("10000000000001", main_data())
            self.assertTrue(c.has("10000000000001")); self.assertEqual(c.read("10000000000001")["pp"], "8")
            c.halt("VERIFICATION_REQUIRED"); self.assertEqual(c.load_state()["state"], "HALTED")
            bad = main_data(None); g.atomic_json(c.data_root / "10000000000001.json", {"source": "live_signed_page", "data": bad})
            self.assertFalse(c.has("10000000000001"))

    def test_all_state_is_home_namespaced_not_root_or_legacy(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)/"home"; output = Path(t)/"output"
            with modules(home, output) as load:
                a = load("asset_paths")
                self.assertEqual(a.ROOT, output.resolve()); self.assertEqual(a.STAGE, state_for(home, output))
                self.assertEqual(a.resolve_stage(output, str(a.STAGE / "explicit")), a.STAGE / "explicit")
                with self.assertRaisesRegex(ValueError, "COLLECTION_STATE_OUTSIDE_HOME"):
                    a.resolve_stage(output, str(output / ".collector_state"))
            self.assertFalse((output / ".collector_state").exists())
            self.assertFalse((home / "poison-state").exists())

    def test_original_missing_sku_price_never_packages_or_guesses(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)/"home"; output = Path(t)/"output"; output.mkdir()
            with modules(home, output) as load:
                g, p, stage = self.fixture(load, home, output)
                (stage / "data" / "10000000000002.json").unlink()
                partial = main_data(None); partial["responseSku"] = "10000000000002"
                g.atomic_json(stage / "partial_data" / "10000000000002.json", {"source": "live_signed_page_arrival_pending", "data": partial})
                self.assertIsNone(p.live_data("10000000000002"))
                plan = p.plan_product("synthetic", {"pid": "10000000000001"}, {})
                self.assertEqual(plan["state"], "SKU_PRICES_PENDING"); self.assertEqual(plan["missingSku"], ["10000000000002"])
                pending = load("checkpoint_status").pending_checkpoint_status(stage, "10000000000001")
                self.assertEqual(pending["state"], "PRICE_PENDING")
                self.assertEqual(pending["missingPriceSkus"], ["10000000000002"])
                self.assertFalse((output / "synthetic").exists())

    def test_original_package_and_independent_media_workbook_verification(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            with modules(home, output) as load:
                g,p,stage,r = self.package(load, home, output)
                folder=Path(r["folder"])
                for name in ["主图", "详情图", "SKU图", "主图视频"]: self.assertTrue((folder/name).is_dir())
                from openpyxl import load_workbook
                wb=load_workbook(folder/"商品信息.xlsx"); rows=list(wb.active.values); wb.close()
                self.assertEqual(len(rows[0]),22); self.assertEqual([r[5] for r in rows[1:]],["A","B"])
                self.assertEqual([r[7] for r in rows[1:]],[8,9]); self.assertIsNone(rows[2][0])
                with patch("requests.get", side_effect=AssertionError("offline verification")):
                    report=load("verify_batch").run()
                self.assertEqual(report["counts"], {"VERIFIED":1})
                self.assertEqual(report["results"][0]["sourceMediaHashesVerified"], 3)
                before=(stage/"receipts"/"10000000000001.json").read_bytes()
                self.assertEqual(p.plan_product("synthetic", {"pid":"10000000000001"}, {})["state"],"COMPLETE")
                self.assertEqual(before,(stage/"receipts"/"10000000000001.json").read_bytes())

    def test_independent_verifier_recomputes_prices_not_mutated_metadata(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            with modules(home, output) as load:
                g,p,stage,r=self.package(load,home,output)
                meta_path=stage/"packages"/"10000000000001"/"package_metadata.json"
                meta=json.loads(meta_path.read_text(encoding="utf-8")); meta["arrivalPrices"]["10000000000001"]="88"
                g.atomic_json(meta_path,meta)
                from openpyxl import load_workbook
                path=Path(r["folder"])/"商品信息.xlsx"; wb=load_workbook(path); wb.active.cell(2,8).value=88; wb.save(path); wb.close()
                p.verify_table(path,meta)
                report=load("verify_batch").run()
                self.assertEqual(report["results"][0]["error"],"FULL_ROW_CONTENT_MISMATCH")
                self.assertFalse(report["complete"])

    def test_independent_verifier_rejects_valid_jpeg_with_wrong_source_hash(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            with modules(home,output) as load:
                g,p,stage,r=self.package(load,home,output)
                from PIL import Image
                Image.new("RGB",(4,4),"blue").save(Path(r["folder"])/"主图"/"主图_1.jpg","JPEG")
                report=load("verify_batch").run()
                self.assertEqual(report["results"][0]["error"],"SOURCE_CONTENT_MISMATCH")

    def test_delivery_only_accepts_independently_verified_packages(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            with modules(home,output) as load:
                g,p,stage,r=self.package(load,home,output)
                report=load("verify_batch").run(); delivery=load("deliver_batch")
                self.assertEqual(len(delivery.verified_items(report,stage,output)),1)
                report["results"][0].update(state="VALIDATION_ERROR",complete=False)
                g.atomic_json(stage/"independent_validation.json",report)
                self.assertEqual(delivery.verified_items(report,stage,output),[])

    def test_node_projection_order_scheduling_and_capture_are_original(self):
        rp=(SCRIPTS/"request_policy.mjs").as_uri(); cp=(SCRIPTS/"collection_policy.mjs").as_uri(); np=(SCRIPTS/"native_page.mjs").as_uri()
        self.node(f"""import assert from 'node:assert/strict';
          import {{project,validate}} from {json.dumps(rp)};
          import {{shouldRequest,partialRecheckEvidence,waitUntilNext,PRICE_RECHECK_VERSION}} from {json.dumps(cp)};
          import {{capturedBusiness}} from {json.dumps(np)};
          const raw={{isLogin:true,pageConfigVO:{{skuid:'10000000000001'}},skuHeadVO:{{skuTitle:'Synthetic'}},price:{{p:'20'}},bestPromotion:{{purchasePrice:'9'}},warePriceGatherVO:{{priceItemList:[{{priceType:'finalPrice',hitLine:true,price:'19'}},{{priceType:'finalPrice',price:'8'}}]}},wareInfoReadMap:{{realSpuId:'20000000000001'}},mainImageVO:{{carouselArea:[{{imageUrl:'jfs/a.jpg'}}]}}}};
          assert.equal(project(raw).pp,'8'); validate('10000000000001',project(raw));
          assert.throws(()=>validate('10000000000001',{{...project(raw),pp:null}}),/ARRIVAL_PRICE_MISSING/);
          assert.equal(shouldRequest({{validCache:true,recheckPrices:true}}),false);
          const previous=partialRecheckEvidence(true,null,'synthetic-time');
          assert.equal(previous.priceRecheckVersion,PRICE_RECHECK_VERSION);
          assert.equal(shouldRequest({{partialCache:previous,recheckPrices:true}}),false);
          assert.equal(waitUntilNext(100,95,20),15);
          assert.equal(capturedBusiness([{{responseStatus:403}}],'10000000000001').reason,'HTTP_403_REFUSED');
          assert.equal(capturedBusiness([{{responseStatus:429}}],'10000000000001').reason,'HTTP_429_RATE_LIMIT');
          assert.equal(capturedBusiness([{{responseStatus:200,responseBody:JSON.stringify(raw)}}],'other').reason,'SKU_ID_MISMATCH');
        """)

    def test_externally_supplied_transport_never_discovers_private_webcli(self):
        tc=(SCRIPTS/"task_context.mjs").as_uri()
        with tempfile.TemporaryDirectory() as t:
            module=Path(t)/"transport.mjs"
            module.write_text("export class Page {setActivePage(){} startNetworkCapture(){} readNetworkCapture(){} evaluate(){} newTab(){} listTabs(){} closeTab(){}}; export async function sendCommandFull(){};",encoding="utf-8")
            self.node(f"""import assert from 'node:assert/strict'; import {{loadBrowserTransport}} from {json.dumps(tc)};
              delete process.env.HEIDENG_COLLECTION_BROWSER_TRANSPORT;
              await assert.rejects(loadBrowserTransport(),/COLLECTION_OWNED_BROWSER_REQUIRED/);
              process.env.HEIDENG_COLLECTION_BROWSER_TRANSPORT='relative.mjs';
              await assert.rejects(loadBrowserTransport(),/COLLECTION_BROWSER_TRANSPORT_ABSOLUTE_REQUIRED/);
              process.env.HEIDENG_COLLECTION_BROWSER_TRANSPORT={json.dumps(str(module))};
              const t=await loadBrowserTransport(); assert.equal(typeof t.Page,'function'); assert.equal(typeof t.sendCommandFull,'function');
            """)

    def test_python_and_node_resolve_the_same_namespaced_state(self):
        tc=(SCRIPTS/"task_context.mjs").as_uri()
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            out=self.node(f"""import assert from 'node:assert/strict'; import {{resolveStage}} from {json.dumps(tc)};
              const root={json.dumps(str(output.resolve()))}; console.log(resolveStage(root));
              assert.throws(()=>resolveStage(root,root),/COLLECTION_STATE_OUTSIDE_HOME/);
            """,{"HEIDENG_MERCHANT_HOME":str(home)})
            self.assertEqual(Path(out.strip()),state_for(home,output))

    def test_original_checkpoint_replace_retry_is_bounded_and_local(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "checkpoint.json"
            spec = importlib.util.spec_from_file_location("mature_checkpoint_io", SCRIPTS / "batch_driver" / "checkpoint_io.py")
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            original = Path.replace; attempts=[]; sleeps=[]
            def replace(pending, target):
                attempts.append(str(pending))
                if len(attempts) <= 2: raise PermissionError("synthetic sharing violation")
                return original(pending, target)
            with patch.object(Path, "replace", replace):
                module.atomic_state(path, {"state":"RUNNING"}, sleep=sleeps.append)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state":"RUNNING"})
            self.assertEqual(sleeps, [0.025,0.05]); self.assertEqual(len(attempts),3)
            attempts.clear(); sleeps.clear()
            with patch.object(Path, "replace", side_effect=PermissionError("synthetic permanent violation")) as replace:
                with self.assertRaises(PermissionError):
                    module.atomic_state(path, {"state":"HALTED"}, sleep=sleeps.append)
            self.assertEqual(replace.call_count,8); self.assertEqual(len(sleeps),7)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state":"RUNNING"})

    def test_original_collection_driver_reuses_success_without_browser_reads(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            with modules(home,output) as load:
                g,p,stage=self.fixture(load,home,output)
                work=home/"state"/"work"/"collection"; work.mkdir(parents=True)
                g.atomic_json(stage/"browser_context.json", {"session":"synthetic", "tab":"A"*32,
                    "windowMode":"background", "idleTimeout":7200,"probeSku":"10000000000001"})
                transport=home/"transport.mjs"
                transport.write_text("export class Page {setActivePage(){} startNetworkCapture(){throw Error('unexpected browser request')} readNetworkCapture(){throw Error('unexpected capture')} evaluate(){throw Error('unexpected evaluation')} newTab(){throw Error('unexpected navigation')} async listTabs(){return []} closeTab(){}}; export async function sendCommandFull(){throw Error('unexpected command')};",encoding="utf-8")
                env=dict(os.environ); env["HEIDENG_COLLECTION_BROWSER_TRANSPORT"]=str(transport)
                before={f.name:f.read_bytes() for f in (stage/"data").glob("*.json")}
                result=subprocess.run(["node",str(SCRIPTS/"collect_signed.mjs"),"--root",str(output),"--run"],
                    capture_output=True,text=True,encoding="utf-8",env=env,cwd=work,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                state=json.loads((stage/"runner_state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["state"],"DATA_COMPLETE"); self.assertEqual(state["requests"],0)
                self.assertEqual(state["navigations"],0)
                self.assertEqual(before,{f.name:f.read_bytes() for f in (stage/"data").glob("*.json")})
                self.assertFalse((stage/"runner.lock").exists())

    def test_prepare_and_delivery_cli_use_owned_state_and_crc_package(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/"home"; output=Path(t)/"output"; output.mkdir()
            from openpyxl import Workbook
            source=Path(t)/"source.xlsx"; wb=Workbook(); wb.active.append(["synthetic"]); wb.active.append([None,"Synthetic product","10000000000001"]+[None]*9+["https://item.jd.com/10000000000001.html"]); wb.save(source); wb.close()
            work=home/"state"/"work"/"collection"; work.mkdir(parents=True)
            with modules(home,output) as load:
                env=dict(os.environ); env["PYTHONDONTWRITEBYTECODE"]="1"; env["PYTHONUTF8"]="1"
                result=subprocess.run([sys.executable,"-B",str(SCRIPTS/"prepare_batch.py"),"--input",str(source),"--root",str(output)],capture_output=True,text=True,encoding="utf-8",env=env,cwd=work,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                stage=state_for(home,output)
                audit=json.loads((stage/"input_audit.json").read_text(encoding="utf-8"))
                self.assertEqual(audit["sha256"],digest(source.read_bytes())); self.assertEqual(audit["sourceProducts"],1)
                # Seed synthetic official snapshots and cached media; never query the source site.
                # fixture creates its cache directory, which prepare does not create.
                g,p,stage,receipt=self.package(load,home,output)
                load("verify_batch").run()
                result=subprocess.run([sys.executable,"-B",str(SCRIPTS/"deliver_batch.py"),"--root",str(output),"--name","synthetic"],capture_output=True,text=True,encoding="utf-8",env=env,cwd=work,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                import zipfile
                archives=list(output.glob("*.zip")); self.assertEqual(len(archives),1)
                with zipfile.ZipFile(archives[0]) as z:
                    self.assertIsNone(z.testzip()); self.assertTrue(any(n.endswith("商品信息.xlsx") for n in z.namelist()))
                self.assertFalse((output/".collector_state").exists())

    def test_runnable_entrypoint_help_without_home_browser_or_state(self):
        env=dict(os.environ)
        for key in list(env):
            if key.startswith(("HEIDENG_", "JD_COLLECTOR_")): env.pop(key)
        for entry in ["prepare_batch.py","package_live.py","verify_batch.py","deliver_batch.py","collect_signed.mjs"]:
            program="node" if entry.endswith(".mjs") else sys.executable
            result=subprocess.run([program,str(SCRIPTS/entry),"--help"],capture_output=True,text=True,encoding="utf-8",env=env,timeout=30)
            self.assertEqual(result.returncode,0,entry+result.stderr)
            self.assertIn("--root",result.stdout,entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
