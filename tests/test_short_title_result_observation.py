import importlib
import json
import tempfile
import unittest
from pathlib import Path
from heideng_merchant.safety import SafetyError, read_json, atomic_json
from tests import test_short_title_imports as import_fixtures
from tests.short_title_result_fixtures import ResultFactory, TransportFactory, workbook


class ShortTitleResultObservationTests(unittest.TestCase):
    def setup(self, directory, *, execute=True):
        client, _, _, _, manager, root = import_fixtures.ShortTitleImportsTests().make(directory)
        manager.approve(root["importId"], root["fingerprint"], confirmed=True)
        factory = ResultFactory(directory)
        wire = TransportFactory()
        transport = importlib.import_module("heideng_merchant.short_title_result_transport").ResultTransport(resolver=wire.resolver, connection_factory=wire, clock=lambda: 1000)
        browser_type = importlib.import_module("heideng_merchant.short_title_import_browser").ShortTitleImportBrowser
        browser = browser_type(manager, root["importId"], factory=lambda: factory, headless=True, result_transport=transport)
        browser.open()
        if execute:
            manager.execute(root["importId"], browser)
        page = factory.driver.context.page
        return client, manager, root, browser, page, wire

    def complete(self, page, wire, **kwargs):
        raw = page.complete(**kwargs)
        wire.response.body = raw
        wire.response.headers[1] = ("Content-Length", str(len(raw)))

    def test_native_original_result_is_read_only_and_not_title_effectiveness(self):
        with tempfile.TemporaryDirectory() as directory:
            client, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                output = manager.collect_results(root["importId"], browser)
                self.assertTrue(output["rowResultsVerified"])
                self.assertFalse(output["actualTitlesVerified"])
                self.assertFalse(output["healthVerified"])
                self.assertFalse(output["imported"])
                self.assertFalse(output["retryAuthorized"])
                rows = manager.rows(root["importId"], view="results")["items"]
                self.assertEqual(rows[0]["skuId"], "101")
                self.assertEqual(rows[0]["outcome"], "success")
                self.assertEqual((page.uploads, page.creates), (1, 1))
                self.assertEqual(len(wire.requests), 1)
                self.assertFalse(client.posts)
                manager.collect_results(root["importId"], browser)
                self.assertEqual((page.uploads, page.creates), (1, 1))
                self.assertEqual(len(wire.requests), 2)
                for path in Path(directory).rglob("*.json"):
                    text = path.read_text(encoding="utf-8-sig")
                    self.assertNotIn("synthetic-only-private", text)
                    self.assertNotIn("jobExecFileRst", text)
            finally:
                browser.close()

    def test_pending_and_missing_original_id_have_no_result_get(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    if missing:
                        page.tasks["data"]["batchJobRecordDtoList"].pop()
                    else:
                        page.result_dom = ["7000000001 处理中 成功：0 失败：0"]
                    out = manager.collect_results(root["importId"], browser)
                    self.assertFalse(out["rowResultsVerified"])
                    self.assertEqual(len(wire.requests), 0)
                    self.assertEqual((page.uploads, page.creates), (1, 1))
                finally:
                    browser.close()

    def test_other_upload_object_or_time_never_downloads(self):
        for field, value in (("jobExecFileSrc", "https://storage.jd.com/synthetic/other.xlsx"), ("jobExecTimeStart", 1001)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    page.tasks["data"]["batchJobRecordDtoList"][-1][field] = value
                    self.assertFalse(manager.collect_results(root["importId"], browser)["rowResultsVerified"])
                    self.assertFalse(wire.requests)
                finally:
                    browser.close()

    def test_ambiguous_dom_counts_and_unknown_terminal_text_never_download(self):
        for text in ("7000000001 已完成 成功：1 成功：1 失败：0", "7000000001 已完成 成功：0 失败：0", "7000000001 未完成 成功：1 失败：0", "7000000001 已完成 处理中 成功：1 失败：0"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    page.result_dom = [text]
                    self.assertFalse(manager.collect_results(root["importId"], browser)["rowResultsVerified"])
                    self.assertFalse(wire.requests)
                finally:
                    browser.close()

    def test_failed_row_is_processing_failure_not_retry_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire, outcome="失败", reason="标题不合规则")
                result = manager.collect_results(root["importId"], browser)
                self.assertTrue(result["rowResultsVerified"])
                self.assertFalse(result["retryAuthorized"])
                self.assertEqual(manager.rows(root["importId"], view="results")["items"][0]["outcome"], "failed")
                manager.execute(root["importId"], browser)
                self.assertEqual((page.uploads, page.creates), (1, 1))
            finally:
                browser.close()

    def test_bad_result_or_download_failure_stays_unknown_without_private_error(self):
        for failure in ("bad-file", "wire-error"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    if failure == "bad-file":
                        wire.response.body = b"synthetic-bad-file"
                        wire.response.headers[1] = ("Content-Length", str(len(wire.response.body)))
                    else:
                        wire.error = True
                    result = manager.collect_results(root["importId"], browser)
                    self.assertFalse(result["rowResultsVerified"])
                    self.assertNotIn("synthetic-only-private", json.dumps(result))
                    self.assertEqual((page.uploads, page.creates), (1, 1))
                finally:
                    browser.close()

    def test_result_reader_refuses_missing_original_observation_or_receipt(self):
        for folder in ("short-title-result-observations", "short-title-result-receipts"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    manager.collect_results(root["importId"], browser)
                    files = list((Path(directory) / folder / root["importId"]).glob("*.json"))
                    self.assertEqual(len(files), 1)
                    files[0].unlink()
                    with self.assertRaises(SafetyError):
                        manager.status(root["importId"])
                    self.assertEqual((page.uploads, page.creates), (1, 1))
                finally:
                    browser.close()

    def test_result_reader_rejects_changed_rows_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                manager.collect_results(root["importId"], browser)
                observation = next((Path(directory) / "short-title-result-observations" / root["importId"]).glob("*.json"))
                data = read_json(observation)
                data["observation"]["result"]["rows"][0]["skuId"] = "102"
                atomic_json(observation, data)
                with self.assertRaises(SafetyError):
                    manager.status(root["importId"])
            finally:
                browser.close()

    def rewrite_last_receipt(self, directory, root, item):
        from heideng_merchant.operations import digest
        receipt_path = next((Path(directory) / "short-title-result-receipts" / root["importId"]).glob("*.json"))
        receipt = read_json(receipt_path)
        receipt["observationSha256"] = digest(item)
        atomic_json(receipt_path, receipt)
        head_path = Path(directory) / "short-title-result-heads" / (root["importId"] + ".json")
        head = read_json(head_path)
        head["receiptSha256"] = digest(receipt)
        atomic_json(head_path, head)

    def test_result_object_must_match_independent_native_source_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                manager.collect_results(root["importId"], browser)
                file = next((Path(directory) / "short-title-result-observations" / root["importId"]).glob("*.json"))
                item = read_json(file)
                item["observation"]["download"]["resultObjectSha256"] = "a" * 64
                atomic_json(file, item)
                self.rewrite_last_receipt(directory, root, item)
                with self.assertRaises(SafetyError):
                    manager.status(root["importId"])
            finally:
                browser.close()

    def test_malformed_reason_is_sanitized_evidence_error(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                manager.collect_results(root["importId"], browser)
                file = next((Path(directory) / "short-title-result-observations" / root["importId"]).glob("*.json"))
                item = read_json(file)
                item["observation"]["reason"] = {}
                atomic_json(file, item)
                self.rewrite_last_receipt(directory, root, item)
                with self.assertRaises(SafetyError):
                    manager.status(root["importId"])
            finally:
                browser.close()

    def test_uncreated_upload_binding_is_not_destroyed_by_result_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory, execute=False)
            try:
                record = manager.record(root["importId"])
                artifact = record["scope"]["artifacts"][0]
                proof = browser.preflight()
                attempt = manager._attempt(record, 1, "upload", proof, install_guard=browser.install_lock)
                browser.grant(attempt)
                response = browser.upload(artifact, attempt)
                manager._ack(record, 1, "upload", attempt, response)
                memo = browser.memo
                before = len(page.urls)
                out = manager.collect_results(root["importId"], browser)
                self.assertEqual(out["stoppedReason"], "uncreated-original-upload-binding-preserved")
                self.assertEqual(browser.memo, memo)
                self.assertEqual(len(page.urls), before)
                self.assertEqual((page.uploads, page.creates), (1, 0))
                self.assertFalse(wire.requests)
            finally:
                browser.close()

    def test_intact_observation_repairs_lost_receipt_or_first_head_without_write_replay(self):
        for folder in ("short-title-result-receipts", "short-title-result-heads"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    manager.collect_results(root["importId"], browser)
                    base = Path(directory) / folder
                    file = next((base / root["importId"]).glob("*.json")) if folder.endswith("receipts") else base / (root["importId"] + ".json")
                    file.unlink()
                    with self.assertRaises(SafetyError):
                        manager.status(root["importId"])
                    output = manager.collect_results(root["importId"], browser)
                    self.assertTrue(output["rowResultsVerified"])
                    self.assertEqual((page.uploads, page.creates), (1, 1))
                finally:
                    browser.close()

    def test_deleted_last_observation_and_receipt_cannot_hide_original_head(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                manager.collect_results(root["importId"], browser)
                manager.collect_results(root["importId"], browser)
                for folder in ("short-title-result-observations", "short-title-result-receipts"):
                    (Path(directory) / folder / root["importId"] / "000002.json").unlink()
                with self.assertRaises(SafetyError):
                    manager.status(root["importId"])
                with self.assertRaises(SafetyError):
                    manager.collect_results(root["importId"], browser)
                self.assertEqual(len(wire.requests), 2)
            finally:
                browser.close()

    def test_wrong_current_shop_blocks_result_get_before_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            client, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                original = client.identity
                client.identity = lambda profile: {**original(profile), "shopName": "other-synthetic-store"}
                before = len(page.urls)
                with self.assertRaises(SafetyError):
                    manager.collect_results(root["importId"], browser)
                self.assertEqual(len(page.urls), before)
                self.assertFalse(wire.requests)
            finally:
                browser.close()

    def test_malformed_complete_count_tokens_and_duplicates_never_prove_rows(self):
        cases = ("1.5", "1e3", "1/100", "1 成功：01", "1,000", "01", "-1")
        for value in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    page.result_dom = [f"7000000001 已完成 成功：{value} 失败：0"]
                    out = manager.collect_results(root["importId"], browser)
                    self.assertFalse(out["rowResultsVerified"])
                    self.assertFalse(wire.requests)
                finally:
                    browser.close()

    def test_invalid_existing_head_is_not_a_missing_head_recovery(self):
        for scenario in ("directory-empty", "null-existing", "directory-existing", "boolean-head", "boolean-receipt"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory, execute=scenario != "directory-empty")
                try:
                    head = Path(directory) / "short-title-result-heads" / (root["importId"] + ".json")
                    head.parent.mkdir(parents=True,exist_ok=True)
                    if scenario != "directory-empty":
                        self.complete(page, wire)
                        manager.collect_results(root["importId"], browser)
                    if scenario.startswith("directory"):
                        if head.exists():
                            head.unlink()
                        head.mkdir()
                    elif scenario == "null-existing":
                        atomic_json(head, None)
                    elif scenario == "boolean-head":
                        data = read_json(head)
                        data["sequence"] = True
                        atomic_json(head, data)
                    else:
                        receipt = next((Path(directory) / "short-title-result-receipts" / root["importId"]).glob("*.json"))
                        data = read_json(receipt)
                        data["sequence"] = True
                        atomic_json(receipt, data)
                    with self.assertRaises(SafetyError):
                        manager.status(root["importId"])
                    with self.assertRaises(SafetyError):
                        manager.collect_results(root["importId"], browser)
                finally:
                    browser.close()

    def test_result_source_flag_is_not_just_task_anchor_matching(self):
        for scenario in ("missing-url", "pending", "get-error"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                _, manager, root, browser, page, wire = self.setup(directory)
                try:
                    self.complete(page, wire)
                    if scenario == "missing-url":
                        page.tasks["data"]["batchJobRecordDtoList"][-1]["jobExecFileRst"] = None
                    elif scenario == "pending":
                        page.result_dom = ["7000000001 处理中 成功：0 失败：0"]
                    else:
                        wire.error = True
                    out = manager.collect_results(root["importId"], browser)
                    self.assertFalse(out["currentResultSourceVerified"])
                    self.assertTrue(out["currentTaskAnchorMatched"])
                    self.assertFalse(out["rowResultsVerified"])
                finally:
                    browser.close()

    def test_complete_rows_still_block_updates_and_orphan_result_is_busy(self):
        gate = importlib.import_module("heideng_merchant.short_title_import_gate")
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root, browser, page, wire = self.setup(directory)
            try:
                self.complete(page, wire)
                manager.collect_results(root["importId"], browser)
            finally:
                browser.close()
            self.assertTrue(gate.busy(Path(directory)))
        with tempfile.TemporaryDirectory() as directory:
            orphan = Path(directory) / "short-title-result-observations" / ("a" * 24) / "000001.json"
            atomic_json(orphan, {})
            self.assertTrue(gate.busy(Path(directory)))


if __name__ == "__main__":
    unittest.main()
