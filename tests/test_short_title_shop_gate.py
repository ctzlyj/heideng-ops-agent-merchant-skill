"""Unknown native imports must quarantine same-shop writes across plans/tools."""
import tempfile
import unittest
from heideng_merchant.safety import SafetyError
from tests import test_short_title_imports as native


class ShortTitleShopGateTests(unittest.TestCase):
    def prepare(self, directory):
        client, _, _, _, manager, root = native.ShortTitleImportsTests().make(directory)
        manager.approve(root["importId"], root["fingerprint"], confirmed=True)
        return client, manager, root

    def unknown(self, directory, manager, root):
        factory, browser = native.ShortTitleImportsTests().browser(directory, manager, root)
        factory.driver.context.page.fault = "create-timeout"
        result = manager.execute(root["importId"], browser)
        self.assertEqual(result["status"], "unknown")
        return factory, browser

    def test_new_prepared_scope_cannot_bypass_other_original_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            _, first, one = self.prepare(directory)
            _, second, two = self.prepare(directory)
            self.assertNotEqual(one["importId"], two["importId"])
            old_factory, old_browser = self.unknown(directory, first, one)
            old_browser.close()
            new_factory, new_browser = native.ShortTitleImportsTests().browser(directory, second, two)
            try:
                with self.assertRaises(SafetyError):
                    second.execute(two["importId"], new_browser)
                self.assertEqual((new_factory.driver.context.page.uploads, new_factory.driver.context.page.creates), (0, 0))
                self.assertEqual((old_factory.driver.context.page.uploads, old_factory.driver.context.page.creates), (1, 1))
            finally:
                new_browser.close()

    def test_native_unknown_blocks_other_same_shop_write_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root = self.prepare(directory)
            _, browser = self.unknown(directory, manager, root)
            try:
                shop = manager.record(root["importId"])["scope"]["shop"]
                with self.assertRaises(SafetyError):
                    manager.plans.ops._assert_resolved(shop)
                alias = {**shop, "profile": "merchant-secondary"}
                with self.assertRaises(SafetyError):
                    manager.plans.ops._assert_resolved(alias)
                other = {**shop,"profile":"merchant-other","venderId":"2","shopId":"33","shopName":"other-synthetic"}
                manager.plans.ops._assert_resolved(other)
            finally:
                browser.close()

    def test_known_prepared_root_orphan_c2_records_block_same_shop_writes(self):
        from pathlib import Path
        from heideng_merchant.safety import atomic_json
        for folder in ("short-title-result-observations","short-title-result-receipts","short-title-result-heads"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as directory:
                _, first, one = self.prepare(directory)
                _, second, two = self.prepare(directory)
                file = Path(directory) / folder / (one["importId"] + ".json") if folder.endswith("heads") else Path(directory) / folder / one["importId"] / "000001.json"
                atomic_json(file, {})
                with self.assertRaises(SafetyError):
                    first.plans.ops._assert_resolved(first.record(one["importId"])["scope"]["shop"])
                factory, browser = native.ShortTitleImportsTests().browser(directory, second, two)
                try:
                    with self.assertRaises(SafetyError):
                        second.execute(two["importId"], browser)
                    self.assertEqual((factory.driver.context.page.uploads,factory.driver.context.page.creates),(0,0))
                finally:
                    browser.close()

    def test_surviving_c2_originals_stop_own_replay_after_b2_history_loss(self):
        import importlib
        import shutil
        from pathlib import Path
        from tests.short_title_result_fixtures import ResultFactory, TransportFactory
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root = self.prepare(directory)
            factory = ResultFactory(directory)
            wire = TransportFactory()
            transport = importlib.import_module("heideng_merchant.short_title_result_transport").ResultTransport(resolver=wire.resolver,connection_factory=wire,clock=lambda:1000)
            browser = importlib.import_module("heideng_merchant.short_title_import_browser").ShortTitleImportBrowser(manager,root["importId"],factory=lambda:factory,headless=True,result_transport=transport)
            browser.open()
            page = factory.driver.context.page
            try:
                manager.execute(root["importId"],browser)
                raw = page.complete()
                wire.response.body = raw
                wire.response.headers[1] = ("Content-Length",str(len(raw)))
                self.assertTrue(manager.collect_results(root["importId"],browser)["rowResultsVerified"])
                originals = {str(file.relative_to(Path(directory))):file.read_bytes() for folder in ("short-title-result-observations","short-title-result-receipts","short-title-result-heads") for file in (Path(directory)/folder).rglob("*.json")}
                for folder in ("short-title-import-attempts","short-title-import-dispatches","short-title-import-acks","short-title-import-observations","short-title-import-anchors"):
                    target = (Path(directory)/folder/root["importId"]).resolve()
                    self.assertTrue(target.is_relative_to(Path(directory).resolve()))
                    self.assertEqual(target.name,root["importId"])
                    shutil.rmtree(target)
                with self.assertRaises(SafetyError):
                    manager.execute(root["importId"],browser)
                self.assertEqual((page.uploads,page.creates),(1,1))
                self.assertTrue(all((Path(directory)/name).read_bytes()==raw for name,raw in originals.items()))
            finally:
                browser.close()

    def test_own_original_read_only_recovery_is_not_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manager, root = self.prepare(directory)
            factory, browser = self.unknown(directory, manager, root)
            try:
                result = manager.recover(root["importId"], browser)
                self.assertEqual(result["submittedBatchCount"], 1)
                self.assertFalse(result["actualTitlesVerified"])
                self.assertEqual((factory.driver.context.page.uploads, factory.driver.context.page.creates), (1,1))
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
