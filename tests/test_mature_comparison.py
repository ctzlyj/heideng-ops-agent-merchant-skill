"""Offline regressions for the pinned mature comparison source (no live calls)."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "mature" / "comparison"
SCRIPTS = BUNDLE / "scripts"

def module(name):
    if not (SCRIPTS / (name + ".py")).is_file():
        raise AssertionError("Missing migrated mature source: " + name)
    sys.path.insert(0, str(SCRIPTS))
    try:
        result = importlib.import_module(name)
        if Path(result.__file__).parent.resolve() != SCRIPTS.resolve():
            raise AssertionError("Imported a non-vendored implementation: " + name)
        return result
    finally:
        sys.path.pop(0)


def market_input():
    candidates, verified = [], {}
    for i in range(12):
        sku, selected = str(90000000000011 + i), str(90000000001011 + i)
        url = "https://item.jd.com/" + sku + ".html"
        spu = "sample-spu-" + str(i)
        candidates.append({
            "sku_id": sku, "spu_id": spu, "title": "Same print " + str(i),
            "shop_name": "Other shop", "product_url": url,
            "source_channels": ["jd_title_search"],
            "observations": [{"sku_id": sku, "product_url": url,
                "sales_lower_bound": 12000 - i * 100, "sales_text": "已售" + str(12000 - i * 100) + "+",
                "display_price": "0.01", "sales_evidence": {"source": "jd_visible_product_card",
                    "sku_id": sku, "product_url": url, "captured_at": "2026-11-16T10:00:00+08:00"}}],
            "ai_review": {"decision": "same", "confidence": "high",
                "evidence_rules": ["composition matches", "pattern matches"], "verification_ref": "review-" + sku}})
        verified[spu] = {"status": "verified", "entry_sku_ids": [sku], "selected_sku_id": selected,
            "raw_spec": "宽80厘米-高40厘米", "normalized_spec": "80x40cm",
            "final_price": format(10 + i, ".2f"), "match_method": "exact_size_single_price",
            "price_evidence": {"source": "jd_detail_network", "captured_at": "2026-11-16T10:01:00+08:00",
                "product_url": "https://item.jd.com/" + selected + ".html"}}
    return {"source": {"sku_id": "90000000000001", "spu_id": "own-spu", "normalized_spec": "80x40cm"},
        "own_shop_filter": {"configured": True, "shop_names": ["Own shop"]},
        "source_spu_evidence": {"proven": True}, "eligible_candidates": candidates,
        "rejected_candidates": []}, verified


class OfflineOfficialClient:
    """Local fixture only: mature API guards/readback run without any network."""
    def __init__(self):
        self.profile, self.writes, self.uncertain = "fixture", [], False
        self.shop = {"shop_id": "10001", "vender_id": "20001", "shop_name": "Fixture shop", "type": "pop"}
        self.detail = {"productInfo": {"productId": 70001, "productName": "Fixture", "categoryDetail": {"lastCategoryId": 123}, "productStatus": 103},
            "material": {}, "skuList": [{"skuId": 80001, "productId": 70001, "skuName": "Fixture A 60x120cm", "outerId": "0", "skuEnableStatus": 1,
                "valid": 1, "skuStatus": {"onOffShelfStatus": 1}, "priceInfo": {"jdPrice": "20.00"},
                "saleAttrs": [{"attrName": "颜色", "attrValueAlias": "A"}, {"attrName": "尺寸", "attrValueAlias": "60x120cm"}]}]}
    def identity(self):
        return copy.deepcopy(self.shop)
    def get(self, name, params):
        if name in ("detail", "application"):
            return {"success": True, "data": copy.deepcopy(self.detail)}
        if name == "price_stars":
            return {"success": True, "data": None, "paginationData": {"currentPage": 1, "pageSize": 200, "totalItems": 0}}
        if name == "products":
            return {"success": True, "data": [{"productId": 70001, "modified": 1}], "paginationData": {"currentPage": 1, "pageSize": 50, "totalItems": 1}}
        raise AssertionError("Unexpected fixture read: " + name)
    def patch(self, product_id, body):
        self.writes.append(copy.deepcopy(body))
        for operation in body["patchOperationList"]:
            self.detail["skuList"][0]["priceInfo"]["jdPrice"] = json.loads(operation["value"])["value"]
        if self.uncertain:
            raise module("jingmai_api").ApiError("WRITE_OUTCOME_UNKNOWN")
        return {"success": True, "data": {"id": str(product_id)}}


def offline_price_source(now):
    return {"shop_id": "10001", "mode": "repricing", "captured_at": now.isoformat(),
        "preflight": {"status": "READY", "purpose": "price", "checked_at": now.isoformat()},
        "price_context": "ordinary_single_item", "expected_competitor_sku_ids": ["90001"],
        "competitor_skus": [{"sku_id": "90001", "size": "60x120", "design": "A", "price": "12.34", "url": "https://item.jd.com/90001.html"}],
        "own_skus": [{"sku_id": "80001", "size": "60x120", "design": "A", "current_final_price": "99.00"}],
        "activity": {"model": "legacy_direct_subsidy_v1", "direct_rate": "0.15", "subsidy_rate": "0.15",
            "starts_at": (now-timedelta(days=1)).isoformat(), "ends_at": (now+timedelta(days=1)).isoformat(),
            "confirmed_at": now.isoformat(), "sku_ids": ["80001"]}}


class MatureAlgorithmTests(unittest.TestCase):
    def test_exact_dimensions_and_cent_inversion_are_upstream_algorithms(self):
        m = module("jd_price_adjustment")
        self.assertEqual(m.canonical_spec("宽80厘米-高40厘米"), "80x40")
        dimensions = module("jd_detail_evidence")
        self.assertNotEqual(dimensions.normalize_dimensions("80x40x2cm"), dimensions.normalize_dimensions("80x40cm"))
        plan = m.create_price_plan(Decimal("12.34"), Decimal("0.15"), Decimal("0.15"))
        self.assertEqual(plan.final_price, Decimal("12.24"))
        self.assertEqual(plan.final_difference, Decimal("-0.10"))
        self.assertEqual(m.calculate_final_price(plan.jd_price, Decimal("0.15"), Decimal("0.15")).final_price, plan.final_price)

    def test_multi_price_exact_spec_requires_explicit_override(self):
        m = module("jd_price_adjustment")
        own = [{"sku_id": "80001", "size": "80x40", "design": "A", "current_final_price": "20.00"}]
        competitors = [{"sku_id": str(90001+i), "size": "80x40", "design": design, "price": price,
            "url": "https://item.jd.com/" + str(90001+i) + ".html"} for i, (design, price) in enumerate([("A", "10.00"), ("B", "11.00")])]
        with self.assertRaises(m.MatchReviewRequiredError):
            m.plan_catalog(own, competitors, Decimal("0"), Decimal("0"), {})
        rows = m.plan_catalog(own, competitors, Decimal("0"), Decimal("0"), {"80001": "90002"})
        self.assertEqual(rows[0]["competitor_sku"], "90002")
        self.assertEqual(rows[0]["recommended_jd_price"], "10.90")
        with self.assertRaises(m.CatalogValidationError):
            m.validate_competitor_catalog(["90001", "90002", "90003"], competitors)

    def test_top10_uses_verified_price_not_search_display_price(self):
        m = module("same_product_market")
        discovery, verified = market_input()
        report = m.build_market_report(discovery, verified)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(len(report["top_same_spec"]), 10)
        self.assertEqual(report["statistics"]["minimum_final_price"], "10.00")
        self.assertEqual(report["statistics"]["average_final_price"], "14.50")
        self.assertEqual(m.build_market_report(discovery, verified, top_limit=20)["statistics"]["sample_count"], 12)

    def test_uncertain_high_rank_and_unproven_source_clear_statistics(self):
        m = module("same_product_market")
        for change in ("uncertain", "source", "filter"):
            discovery, verified = market_input()
            if change == "uncertain":
                discovery["eligible_candidates"][0]["ai_review"]["confidence"] = "low"
            elif change == "source":
                discovery["source_spu_evidence"]["proven"] = False
            else:
                discovery["own_shop_filter"]["configured"] = False
            report = m.build_market_report(discovery, verified)
            self.assertNotEqual(report["status"], "READY")
            self.assertEqual(report["top_same_spec"], [])
            self.assertIsNone(report["statistics"]["minimum_final_price"])
            self.assertIsNone(report["statistics"]["average_final_price"])

    def test_market_workbook_is_real_three_sheet_output(self):
        market = module("same_product_market")
        builder = module("build_market_workbook")
        from openpyxl import load_workbook
        discovery, verified = market_input()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "market.xlsx"
            builder.build_market_workbook(market.build_market_report(discovery, verified), output)
            workbook = load_workbook(output, data_only=True)
            try:
                self.assertEqual(workbook.sheetnames, ["同品列表", "同规格TOP10", "统计摘要"])
                self.assertEqual(workbook["同规格TOP10"].max_row, 11)
            finally:
                workbook.close()

    def test_local_image_similarity_runs_on_actual_images(self):
        m = module("image_similarity")
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary)/"a.png", Path(temporary)/"b.png"
            Image.new("RGB", (32, 32), (210, 80, 30)).save(a)
            Image.new("RGB", (32, 32), (10, 180, 230)).save(b)
            self.assertEqual(m.compare_images(a, a)["combined_similarity"], 1.0)
            self.assertLess(m.compare_images(a, b)["combined_similarity"], 1.0)

    def test_confirmation_rejected_before_any_official_client_access(self):
        m = module("jingmai_api")
        # Real upstream validation: an unconfirmed/malformed plan never reaches identity or writes.
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(m.ApiError):
                m.execute(object(), object(), {}, "unconfirmed", Path(temporary))


    def test_mature_confirmation_readback_and_unknown_write_do_not_replay(self):
        api, pricing = module("jingmai_api"), module("store_pricing")
        now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as temporary:
                previous = os.environ.get("HEIDENG_MERCHANT_HOME")
                os.environ["HEIDENG_MERCHANT_HOME"] = temporary
                try:
                    client = OfflineOfficialClient()
                    store = pricing.PolicyStore()
                    proposed = store.prepare(client.identity(), pricing.legacy_config())
                    policy = store.commit(client.identity(), proposed["config"], proposed["confirm_token"])
                    plan = api.prepare_plan(client, policy, offline_price_source(now), product_ids=["70001"], now=now)
                    root = Path(temporary)/"comparison/api-runs"
                    with self.assertRaisesRegex(api.ApiError, "CONFIRMATION_MISMATCH"):
                        api.execute(client, store, plan, "wrong-token", root, now=now, poll_count=1, poll_interval=0)
                    self.assertEqual(client.writes, [])
                    client.uncertain = uncertain
                    state = api.execute(client, store, plan, plan["confirm_token"], root, now=now, poll_count=1, poll_interval=0)
                    self.assertEqual(state["status"], "WRITE_OUTCOME_UNKNOWN" if uncertain else "VERIFIED")
                    readback = api.execute(client, store, plan, plan["confirm_token"], root, now=now, poll_count=1, poll_interval=0, read_only=True)
                    self.assertEqual(readback["status"], "VERIFIED")
                    self.assertEqual(readback["verified_skus"], 1)
                    self.assertEqual(len(client.writes), 1)
                    self.assertEqual(client.writes[0]["patchOperationList"][0]["path"], "skus[skuId==80001]")
                finally:
                    if previous is None: os.environ.pop("HEIDENG_MERCHANT_HOME", None)
                    else: os.environ["HEIDENG_MERCHANT_HOME"] = previous


class MatureBoundaryTests(unittest.TestCase):
    def subprocess_environment(self, home):
        keep = {"SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "TEMP", "TMP", "PATHEXT"}
        env = {key: value for key, value in os.environ.items() if key.upper() in keep}
        env.update(HEIDENG_MERCHANT_HOME=str(home), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        return env

    def test_all_real_entrypoints_help_and_import_without_authentication(self):
        manifest = json.loads((BUNDLE / "provenance.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            env = self.subprocess_environment(Path(temporary))
            for name in manifest["entrypoints"]:
                with self.subTest(entrypoint=name):
                    help_result = subprocess.run([sys.executable, "-B", str(BUNDLE/name), "--help"], env=env,
                        cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(help_result.returncode, 0, help_result.stderr)
                    self.assertIn("usage:", help_result.stdout)
                    code = "import sys;sys.path.insert(0, " + repr(str(SCRIPTS)) + ");import " + Path(name).stem
                    imported = subprocess.run([sys.executable, "-B", "-c", code], env=env, cwd=temporary,
                        capture_output=True, text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_original_market_cli_build_and_workbook_entry_emit_real_files(self):
        discovery, verified = market_input()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            env = self.subprocess_environment(home)
            discovery_path, verification_path, report_path = home/"discovery.json", home/"verified.json", home/"report.json"
            discovery_path.write_text(json.dumps(discovery), encoding="utf-8")
            verification_path.write_text(json.dumps(verified), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS/"same_product_market.py"), "build",
                "--discovery", str(discovery_path), "--verifications", str(verification_path), "--output", str(report_path)],
                env=env, cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "READY")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["statistics"]["average_final_price"], "14.50")
            workbook_path = home/"market.xlsx"
            built = subprocess.run([sys.executable, "-B", str(SCRIPTS/"build_market_workbook.py"),
                "--report", str(report_path), "--output", str(workbook_path)], env=env, cwd=temporary,
                capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(built.returncode, 0, built.stderr)
            from openpyxl import load_workbook
            workbook = load_workbook(workbook_path, read_only=True, data_only=True)
            try:
                self.assertEqual(workbook.sheetnames, ["同品列表", "同规格TOP10", "统计摘要"])
            finally:
                workbook.close()

    def test_original_price_cli_plan_keeps_real_subcommand_and_cent_gap(self):
        source = {"expected_competitor_sku_ids": ["90001"],
            "own_skus": [{"sku_id": "80001", "size": "60x120", "design": "A", "current_final_price": "20.00"}],
            "competitor_skus": [{"sku_id": "90001", "size": "60x120", "design": "A", "price": "12.34", "url": "https://item.jd.com/90001.html"}]}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            input_path, output = home/"catalog.json", home/"result"
            input_path.write_text(json.dumps(source), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS/"jd_price_adjustment.py"), "plan",
                "--input", str(input_path), "--direct-rate", "0.15", "--subsidy-rate", "0.15", "--output-dir", str(output)],
                env=self.subprocess_environment(home), cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads((output/"comparison_rows.json").read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["calculated_final_price"], "12.24")
            self.assertEqual(rows[0]["final_difference"], "-0.10")
            self.assertEqual(json.loads((output/"upload_rows.json").read_text(encoding="utf-8"))[0]["SKUID"], "80001")

    def test_manifest_hashes_cover_bundle_and_keep_original_algorithm_bytes(self):
        manifest = json.loads((BUNDLE / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["repository"], "ctzlyj/jd-competitor-price-adjustment-skill")
        self.assertEqual(manifest["upstreamCommit"], "43bdf6790fe3c8a5b89c217edcaefabf670cbc2c")
        self.assertEqual(manifest["upstreamVersion"], "1.0.0")
        self.assertEqual(manifest["license"], "MIT")
        actual = {p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob("*") if p.is_file()
            and "__pycache__" not in p.parts and p.name != "provenance.json"}
        self.assertEqual(set(manifest["files"]), actual)
        for name, record in manifest["files"].items():
            self.assertEqual(record["sha256"], hashlib.sha256((BUNDLE/name).read_bytes()).hexdigest(), name)
            if not record["adapted"]:
                self.assertEqual(record["sha256"], record["upstreamSha256"], name)
        for name in ("jd_price_adjustment", "same_product_market", "competitor_discovery", "jd_detail_evidence", "image_similarity", "hot_spu_comparison"):
            self.assertFalse(manifest["files"]["scripts/"+name+".py"]["adapted"])

    def test_policy_defaults_are_merchant_scoped_not_personal(self):
        m = module("store_pricing")
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("HEIDENG_MERCHANT_HOME")
            os.environ["HEIDENG_MERCHANT_HOME"] = temporary
            try:
                self.assertEqual(m.PolicyStore().root, (Path(temporary)/"comparison/stores").resolve())
                with self.assertRaises(m.PolicyError):
                    m.PolicyStore(Path(temporary).parent/"outside-comparison-test")
            finally:
                if previous is None: os.environ.pop("HEIDENG_MERCHANT_HOME", None)
                else: os.environ["HEIDENG_MERCHANT_HOME"] = previous

    def test_missing_merchant_home_fails_closed_without_personal_fallback(self):
        m = module("merchant_runtime")
        previous = os.environ.pop("HEIDENG_MERCHANT_HOME", None)
        try:
            with self.assertRaisesRegex(m.RuntimeConfigurationError, "HEIDENG_MERCHANT_HOME_REQUIRED"):
                m.merchant_home()
        finally:
            if previous is not None: os.environ["HEIDENG_MERCHANT_HOME"] = previous

    def test_external_webcli_subprocess_preserves_arguments_stdin_and_namespace(self):
        m = module("browser_runtime")
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)/"merchant"
            home.mkdir()
            script = Path(temporary)/"installed_transport.py"
            script.write_text("import json,os,sys\nprint(json.dumps({'arguments':sys.argv[1:],'input':sys.stdin.read(),'cwd':os.getcwd(),'home':os.environ.get('HEIDENG_MERCHANT_HOME'),'node_options':os.environ.get('NODE_OPTIONS')}))\n", encoding="utf-8")
            env = self.subprocess_environment(home)
            env["HEIDENG_WEBCLI_COMMAND_JSON"] = json.dumps([sys.executable, str(script)])
            env["NODE_OPTIONS"] = "--dangerous-parent-option"
            runner = m.WebCliRunner(environment=env)
            arguments = ["--json", "exec", "print('中文 & | < >')"]
            result = json.loads(runner.run(arguments, input_text="payload中文"))
            self.assertEqual(result["arguments"], arguments)
            self.assertEqual(result["input"], "payload中文")
            self.assertEqual(Path(result["cwd"]), home/"comparison/browser-runtime")
            self.assertEqual(result["home"], str(home))
            self.assertIsNone(result["node_options"])

    def test_browser_transport_rejects_employee_aliases_without_launch(self):
        m = module("browser_runtime")
        with tempfile.TemporaryDirectory() as temporary:
            env = self.subprocess_environment(Path(temporary))
            env["HEIDENG_WEBCLI_COMMAND_JSON"] = '["o2", "launch", "webcli"]'
            with self.assertRaisesRegex(m.BrowserRuntimeError, "EXTERNAL_WEBCLI_COMMAND_REQUIRED"):
                m.WebCliRunner(environment=env).run(["--help"])

    def test_direct_detail_entrypoint_rejects_checkpoint_escape_before_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)/"merchant"
            home.mkdir()
            env = self.subprocess_environment(home)
            env["HEIDENG_WEBCLI_COMMAND_JSON"] = json.dumps([sys.executable, "-c", "raise SystemExit('TRANSPORT_MUST_NOT_RUN')"])
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS/"webcli_jd_detail_capture.py"),
                "--profile", "fixture", "--entry-sku", "90001", "--checkpoint", str(Path(temporary)/"escape.json"),
                "--output", str(home/"catalog.json")], env=env, cwd=temporary,
                capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertIn("STATE_MUST_BE_INSIDE_MERCHANT_HOME", result.stderr)
            self.assertEqual(list(home.iterdir()), [])

    def test_optional_authorized_image_search_is_unconfigured_without_network(self):
        m = module("authorized_image_search")
        previous = os.environ.pop("HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN", None)
        try:
            with self.assertRaisesRegex(m.AuthorizedSearchError, "AUTHORIZED_IMAGE_SEARCH_UNCONFIGURED"):
                m._request_json("/health")
        finally:
            if previous is not None: os.environ["HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN"] = previous

    def test_official_boundary_requires_merchant_jdo_namespace(self):
        m = module("merchant_runtime")
        previous = {key: os.environ.get(key) for key in ("HEIDENG_MERCHANT_HOME", "JDO_HOME")}
        with tempfile.TemporaryDirectory() as temporary:
            os.environ["HEIDENG_MERCHANT_HOME"] = temporary
            os.environ.pop("JDO_HOME", None)
            try:
                with self.assertRaisesRegex(m.RuntimeConfigurationError, "MERCHANT_JDO_HOME_REQUIRED"):
                    m.official_executable(sys.executable)
                os.environ["JDO_HOME"] = str(Path(temporary).parent/"outside-jdo")
                with self.assertRaisesRegex(m.RuntimeConfigurationError, "STATE_MUST_BE_INSIDE_MERCHANT_HOME"):
                    m.official_executable(sys.executable)
                os.environ["JDO_HOME"] = str(Path(temporary)/"jdo")
                self.assertEqual(m.official_executable(sys.executable), str(Path(sys.executable).resolve()))
            finally:
                for key, value in previous.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value

    def test_no_employee_model_keys_personal_roots_or_installer_in_python(self):
        self.assertTrue(SCRIPTS.is_dir())
        for path in SCRIPTS.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in (".agents", ".codex", "Path.home()", "llm-gw", "JOY_BUILDER_API_KEY", "OXYGEN_API_KEY", "webcli-business-local", "o2_command", "O2Runner", "npm install", "pip install"):
                self.assertNotIn(forbidden, text, path.name)


if __name__ == "__main__":
    unittest.main()
