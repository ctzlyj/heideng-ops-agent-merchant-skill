"""Synthetic original-task DOM and public result transport, never a real browser."""
from tests.short_title_import_fixtures import ImportLocator, ImportPage, ImportContext, ImportFactory
from tests.test_short_title_results import workbook


class ResultLocator(ImportLocator):
    def __init__(self, page, kind="element", selected=None):
        super().__init__(page, kind)
        self.selected = selected

    def locator(self, selector):
        return ResultLocator(self.page, "rows" if selector == "tbody tr" else "file" if selector == "input[type=file]" else "drawer" if "drawer" in selector else "element")

    def get_by_role(self, role, **kwargs):
        return ResultLocator(self.page, "link" if role == "link" else "create" if kwargs.get("name") == "确定导入" else "button")

    def get_by_text(self, text, **kwargs):
        return ResultLocator(self.page, "open" if text == "批量设置短标题" else "label")

    def filter(self, **kwargs):
        if self.kind == "rows" and "has_text" in kwargs:
            pattern = kwargs["has_text"]
            self.selected = [text for text in self.page.result_dom if pattern.search(text)]
        return self

    def count(self):
        if self.kind == "rows":
            return len(self.selected if self.selected is not None else self.page.result_dom)
        return super().count()

    def inner_text(self, **kwargs):
        return self.selected[0]


class ResultPage(ImportPage):
    def __init__(self, temp):
        super().__init__(temp)
        self.result_dom = []

    def locator(self, selector):
        return ResultLocator(self, "drawer" if "drawer" in selector else "element")

    def get_by_text(self, *args, **kwargs):
        return ResultLocator(self, "open")

    def complete(self, *, outcome="成功", reason=""):
        task = self.tasks["data"]["batchJobRecordDtoList"][-1]
        task["jobExecFileRst"] = "https://storage.jd.com/synthetic/result.xlsx?expires=1&token=synthetic-only-private"
        success = int(outcome == "成功")
        failed = int(outcome == "失败")
        self.result_dom = [f"{task['jobExecId']} 已完成 成功：{success} 失败：{failed}"]
        return workbook([("101", outcome, reason)])


class ResultContext(ImportContext):
    def new_page(self):
        self.page = ResultPage(self.temp)
        self.pages.append(self.page)
        return self.page


class ResultFactory(ImportFactory):
    def __init__(self, temp):
        super().__init__(temp)
        self.driver.context = ResultContext(temp)


class Response:
    def __init__(self, body):
        self.body = body
        self.offset = 0
        self.status = 200
        self.headers = [("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("Content-Length", str(len(body)))]
    def getheaders(self):
        return self.headers
    def read(self, size):
        value = self.body[self.offset:self.offset + size]
        self.offset += len(value)
        return value


class Connection:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False
    def set_debuglevel(self, value):
        self.owner.debuglevel = value
    def request(self, method, path, body=None, headers=None):
        self.owner.requests.append((method, path, headers))
        if self.owner.error:
            raise RuntimeError("synthetic-only-private credential echo")
    def getresponse(self):
        return self.owner.response
    def close(self):
        self.closed = True


class TransportFactory:
    def __init__(self, body=b"synthetic-result"):
        self.response = Response(body)
        self.requests = []
        self.error = False
        self.debuglevel = None
        self.ips = ["93.184.216.34"]
        self.connection = None
    def resolver(self, host, port, **kwargs):
        return [(2, 1, 6, "", (ip, port)) for ip in self.ips]
    def __call__(self, host, port, **kwargs):
        self.response.offset = 0
        self.connection = Connection(self)
        return self.connection
