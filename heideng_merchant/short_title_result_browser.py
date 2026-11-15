"""Read-only native original-instance result observation; confidential URLs stay here."""
import re

from .operations import digest
from .safety import SafetyError
from .short_title_browser_contract import source_url, sha_bytes
from .short_title_import_contract import observed_tasks, object_sha
from .short_title_import_state import evidence
from .short_title_results import parse_result_workbook


def result_sources(data):
    """Browser-private projection only; not a persistence/CLI return contract."""
    rows = observed_tasks(data)
    return [{**row, "resultUrl": raw.get("jobExecFileRst")} for row, raw in zip(rows, data["data"]["batchJobRecordDtoList"])]


def task_counts(text, instance, expected):
    if not isinstance(text, str) or len(text) > 16384:
        return None
    token = re.compile(r"(?<![A-Za-z0-9])" + re.escape(instance) + r"(?![A-Za-z0-9])")
    if len(token.findall(text)) != 1:
        return None
    terminal = re.findall(r"(?:^|[\s|，,;；])(?:已完成|已结束)(?=$|[\s|，,;；])", text)
    if len(terminal) != 1 or any(word in text for word in ("处理中", "未完成", "未结束", "进行中", "待处理")):
        return None
    def count(label):
        labels = list(re.finditer(r"(?<![A-Za-z\u4e00-\u9fff])" + label, text))
        if len(labels) != 1:
            return None
        tail = text[labels[0].end():]
        found = re.match(r"\s*[：:]?\s*(0|[1-9][0-9]{0,4})(?=$|[\s|;；]|[,，](?=\s*(?:成功|失败|已完成|已结束)))", tail)
        return int(found[1]) if found else None
    success, failed = count("成功"), count("失败")
    if success is None or failed is None or success + failed != expected:
        return None
    return {"success": success, "failed": failed}


def observe_result(browser, batch):
    manager = browser.manager
    root = manager.record(browser.import_id)
    anchors = evidence(manager.state, root)[3]
    anchor = anchors.get((batch, "create"))
    if anchor is None:
        raise SafetyError("original-native-result-anchor-required")
    page = browser._observe()
    observation = {"anchorSha256": digest(anchor), "identitySha256": page["identitySha256"], "taskPageSha256": page["taskPageSha256"], "resultSourceSha256": None, "taskRowSha256": None, "source": None, "state": "unavailable", "reason": "original-task-not-in-observed-page", "counts": None, "download": None, "result": None}
    wanted = [row for row in browser._last_result_sources if row["instanceId"] == anchor["instanceId"]]
    if len(wanted) != 1:
        return observation
    row = wanted[0]
    source = {key: row[key] for key in ("instanceId", "uploadedObjectSha256", "startedAt")}
    observation["source"] = source
    if source != {"instanceId": anchor["instanceId"], "uploadedObjectSha256": anchor["objectSha256"], "startedAt": anchor["startedAt"]}:
        observation["reason"] = "original-task-object-or-time-mismatch"
        return observation
    observation["resultSourceSha256"] = object_sha(row["resultUrl"])
    token = re.compile(r"(?<![A-Za-z0-9])" + re.escape(anchor["instanceId"]) + r"(?![A-Za-z0-9])")
    rows = browser._drawer().locator("tbody tr").filter(has_text=token)
    if rows.count() != 1:
        observation["reason"] = "unique-original-task-dom-row-not-verified"
        return observation
    text = rows.inner_text(timeout=10000)
    if isinstance(text, str) and len(text) <= 16384:
        observation["taskRowSha256"] = sha_bytes(text.encode("utf-8"))
    counts = task_counts(text, anchor["instanceId"], len(root["scope"]["chunks"][batch - 1]))
    if counts is None:
        observation.update(state="pending", reason="terminal-original-task-counts-not-verified")
        return observation
    observation["counts"] = counts
    if not source_url(row["resultUrl"], template=True):
        observation["reason"] = "original-task-result-source-not-verified"
        return observation
    observation.update(state="unknown-result", reason="original-result-file-not-verified")
    try:
        raw, proof = browser.result_transport.fetch(row["resultUrl"], deadline=manager.clock() + 60)
        if proof["resultObjectSha256"] != object_sha(row["resultUrl"]):
            raise SafetyError("exact-observed-result-source-required")
        browser._identity()
        manager._current(root, readonly=True)
        parsed = parse_result_workbook(raw, [entry["skuId"] for entry in root["scope"]["chunks"][batch - 1]], success_rows=counts["success"], failed_rows=counts["failed"])
        if parsed["resultFileSha256"] != proof["resultFileSha256"]:
            raise SafetyError("original-result-download-bytes-required")
        observation.update(download=proof, result=parsed)
        if parsed["complete"]:
            observation.update(state="complete", reason=None)
    except Exception:
        # Neither an error echo nor a signed URL is returned to the manager.
        observation.update(state="unknown-result", reason="original-result-file-not-verified", download=None, result=None)
    return observation
