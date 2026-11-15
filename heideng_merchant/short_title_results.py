"""Bounded result-file parsing only; neither original-task proof nor retry permission."""
import hashlib
import re
import xml.etree.ElementTree as ET

from .operations import digest
from .products import identifier
from .safety import SafetyError, redact
from .short_title_workbook import NS, _parts

HEADERS = {"SKUID", "执行结果", "失败原因"}
TAG = "{" + NS + "}"


def _text_container(container):
    if container is None:
        raise SafetyError("native-title-result-text-required")
    texts = []
    for child in container:
        if child.tag == TAG + "t" and not len(child):
            texts.append(child.text or "")
        elif child.tag == TAG + "r":
            run = [item for item in child if item.tag == TAG + "t"]
            if len(run) != 1 or len(run[0]) or any(item.tag not in (TAG + "t", TAG + "rPr") for item in child):
                raise SafetyError("native-title-result-text-required")
            texts.append(run[0].text or "")
        else:
            raise SafetyError("native-title-result-text-required")
    if not texts:
        raise SafetyError("native-title-result-text-required")
    value = "".join(texts)
    if len(value) > 2048 or redact(value) != value or re.search(r"https?://|www\.", value, re.I):
        raise SafetyError("bounded-nonprivate-title-result-text-required")
    return value


def _cell_text(cell, strings):
    kind = cell.attrib.get("t")
    if kind == "inlineStr" and len(cell) == 1 and cell[0].tag == TAG + "is":
        return _text_container(cell[0])
    if kind == "s" and len(cell) == 1 and cell[0].tag == TAG + "v":
        value = cell[0].text
        if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,5}", value) or int(value) >= len(strings):
            raise SafetyError("valid-title-result-shared-string-required")
        return strings[int(value)]
    raise SafetyError("exact-text-title-result-cells-required")


def parse_result_workbook(raw, expected_sku_ids, *, success_rows, failed_rows):
    """Parse one complete <=5000-row original batch's *supplied* result bytes.

    The caller must independently prove the original task/download binding. An
    unknown status never becomes a failed row, and this function authorizes no
    write or retry. All private/raw file contents stay in the calling process.
    """
    if type(expected_sku_ids) not in (list, tuple) or not 1 <= len(expected_sku_ids) <= 5000:
        raise SafetyError("complete-original-title-result-sku-scope-required")
    if any(type(sku) is not str for sku in expected_sku_ids):
        raise SafetyError("exact-text-title-result-sku-scope-required")
    expected = [identifier(sku) for sku in expected_sku_ids]
    if len(set(expected)) != len(expected):
        raise SafetyError("unique-original-title-result-sku-scope-required")
    if any(type(count) is not int or count < 0 for count in (success_rows, failed_rows)) or success_rows + failed_rows != len(expected):
        raise SafetyError("exact-original-title-result-counts-required")
    _, parts = _parts(raw)
    strings = []
    if "xl/sharedStrings.xml" in parts:
        shared = ET.fromstring(parts["xl/sharedStrings.xml"])
        if shared.tag != TAG + "sst" or any(child.tag != TAG + "si" for child in shared):
            raise SafetyError("valid-title-result-shared-strings-required")
        strings = [_text_container(item) for item in shared]
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    tables = sheet.findall(TAG + "sheetData")
    if sheet.tag != TAG + "worksheet" or len(tables) != 1 or len(tables[0]) != len(expected) + 1:
        raise SafetyError("complete-original-title-result-rows-required")
    records = []
    for number, row in enumerate(tables[0], 1):
        if row.tag != TAG + "row" or row.attrib.get("r") != str(number) or len(row) != 3:
            raise SafetyError("unique-ordered-title-result-sheet-rows-required")
        cells = {}
        for cell in row:
            coordinate = cell.attrib.get("r")
            if cell.tag != TAG + "c" or coordinate not in ("A" + str(number), "B" + str(number), "C" + str(number)) or coordinate in cells:
                raise SafetyError("unique-exact-title-result-cell-coordinates-required")
            cells[coordinate] = _cell_text(cell, strings)
        records.append([cells[column + str(number)] for column in "ABC"])
    headers = records.pop(0)
    if len(set(headers)) != 3 or set(headers) != HEADERS:
        raise SafetyError("reviewed-native-title-result-headers-required")
    seen = {}
    for values in records:
        entry = dict(zip(headers, values))
        sku = identifier(entry["SKUID"])
        if sku not in expected or sku in seen:
            raise SafetyError("exact-original-title-result-sku-rows-required")
        status, reason = entry["执行结果"], entry["失败原因"]
        outcome = "success" if status == "成功" else "failed" if status == "失败" else "unknown"
        if outcome == "success" and reason:
            raise SafetyError("consistent-native-title-result-row-required")
        seen[sku] = {"skuId": sku, "outcome": outcome, "reason": reason}
    rows = [seen[sku] for sku in expected]
    successful = sum(row["outcome"] == "success" for row in rows)
    failed = sum(row["outcome"] == "failed" for row in rows)
    unknown = len(rows) - successful - failed
    if successful > success_rows or failed > failed_rows or (not unknown and (successful != success_rows or failed != failed_rows)):
        raise SafetyError("task-counts-and-title-result-rows-must-agree")
    return {
        "complete": not unknown,
        "rows": rows,
        "verifiedFailureSkuIds": [row["skuId"] for row in rows if row["outcome"] == "failed"] if not unknown else [],
        "resultFileSha256": hashlib.sha256(raw).hexdigest(),
        "expectedSkuIdsSha256": digest(expected),
        "successRowCount": successful,
        "failedRowCount": failed,
        "unknownRowCount": unknown,
        "originalTaskVerified": False,
        "actualTitlesVerified": False,
        "healthVerified": False,
        "retryAuthorized": False,
    }
