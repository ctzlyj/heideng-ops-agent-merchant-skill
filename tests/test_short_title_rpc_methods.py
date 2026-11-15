"""Exact historical RPC aliases; fake native pages only, no broad URL matches."""
import importlib
import tempfile
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from heideng_merchant.short_title_browser_contract import source_url
from tests import test_short_title_browser as source_fixtures
from tests import test_short_title_imports as import_fixtures
from tests.short_title_result_fixtures import ResultPage, ResultContext, ResultFactory, TransportFactory

METHODS = {"file.upload": "dsm.base.service.file.upload", "batchJobService.createImportJob": "dsm.product.manage.view.batchJobService.createImportJob", "batchJobService.queryByPage": "dsm.product.manage.view.batchJobService.queryByPage"}


class QualifiedPage(ResultPage):
    def emit(self, response):
        url = urlsplit(response.url)
        query = parse_qs(url.query, keep_blank_values=True)
        method = query.get("method", [])
        if len(method) == 1 and method[0] in METHODS:
            query["method"] = [METHODS[method[0]]]
            response.url = urlunsplit((url.scheme,url.netloc,url.path,urlencode(query,doseq=True),url.fragment))
            response.request.url = response.url
        return super().emit(response)


class QualifiedContext(ResultContext):
    def new_page(self):
        self.page = QualifiedPage(self.temp)
        self.pages.append(self.page)
        return self.page


class QualifiedFactory(ResultFactory):
    def __init__(self, directory):
        super().__init__(directory)
        self.driver.context = QualifiedContext(directory)


class ShortTitleRpcMethodTests(unittest.TestCase):
    def test_only_exact_audited_short_and_qualified_aliases_match(self):
        for short, full in METHODS.items():
            for method in (short, full):
                with self.subTest(method=method):
                    self.assertTrue(source_url("https://api.m.jd.com/api?" + urlencode({"method":method}), service=short))

    def test_unknown_namespace_substrings_and_duplicate_method_never_match(self):
        for short, full in METHODS.items():
            for method in ("prefix."+full, full+".other", full+" ", full.replace("dsm.","employee.")):
                with self.subTest(method=method):
                    self.assertFalse(source_url("https://api.m.jd.com/api?"+urlencode({"method":method}),service=short))
            for query in ("method="+full+"&method="+short,"method="+full+"&method="+full,"other="+full):
                self.assertFalse(source_url("https://api.m.jd.com/api?"+query,service=short))
            self.assertFalse(source_url("https://api.m.jd.com/not-api?method="+full,service=short))

    def test_native_source_capture_accepts_qualified_task_method(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, factory, browser = source_fixtures.ShortTitleBrowserTests().make(directory)
            browser.open()
            try:
                factory.driver.context.page.task_url = "https://api.m.jd.com/api?method="+METHODS["batchJobService.queryByPage"]
                result = browser.capture()
                self.assertTrue(result["templateOriginCaptured"])
                self.assertFalse(result["imported"])
            finally:
                browser.close()

    def test_native_upload_create_recovery_and_results_use_qualified_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            client, _, _, _, manager, root = import_fixtures.ShortTitleImportsTests().make(directory)
            manager.approve(root["importId"],root["fingerprint"],confirmed=True)
            factory = QualifiedFactory(directory)
            wire = TransportFactory()
            transport = importlib.import_module("heideng_merchant.short_title_result_transport").ResultTransport(resolver=wire.resolver,connection_factory=wire,clock=lambda:1000)
            browser = importlib.import_module("heideng_merchant.short_title_import_browser").ShortTitleImportBrowser(manager,root["importId"],factory=lambda:factory,headless=True,result_transport=transport)
            browser.open()
            page = factory.driver.context.page
            try:
                page.fault = "create-timeout"
                self.assertEqual(manager.execute(root["importId"],browser)["status"],"unknown")
                self.assertEqual(manager.recover(root["importId"],browser)["submittedBatchCount"],1)
                raw = page.complete()
                wire.response.body = raw
                wire.response.headers[1] = ("Content-Length",str(len(raw)))
                result = manager.collect_results(root["importId"],browser)
                self.assertTrue(result["rowResultsVerified"])
                self.assertTrue(result["currentResultSourceVerified"])
                self.assertFalse(result["actualTitlesVerified"])
                self.assertFalse(result["retryAuthorized"])
                self.assertEqual((page.uploads,page.creates),(1,1))
                self.assertFalse(client.posts)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
