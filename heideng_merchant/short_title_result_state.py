"""Independent append-only result observations/receipts and fail-closed head evidence."""
import re
from pathlib import Path

from .operations import digest
from .safety import SafetyError, read_json, redact, atomic_json, safe_join
from .short_title_import_state import path, valid_time, HASH
from .short_title_result_transport import MAX_BYTES, MIMES
from .video_delivery import _once

FOLDERS = ("short-title-result-observations", "short-title-result-receipts")
MAX_OBSERVATIONS = 10000
REASONS = {"original-task-not-in-observed-page", "original-task-object-or-time-mismatch", "unique-original-task-dom-row-not-verified", "terminal-original-task-counts-not-verified", "original-task-result-source-not-verified", "original-result-file-not-verified"}


def _hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _error():
    raise SafetyError("original-native-title-result-evidence-required")


def _parsed(result, expected, counts):
    keys = {"complete", "rows", "verifiedFailureSkuIds", "resultFileSha256", "expectedSkuIdsSha256", "successRowCount", "failedRowCount", "unknownRowCount", "originalTaskVerified", "actualTitlesVerified", "healthVerified", "retryAuthorized"}
    if not isinstance(result, dict) or set(result) != keys or redact(result) != result or not _hash(result["resultFileSha256"]) or result["expectedSkuIdsSha256"] != digest(expected) or not isinstance(result["rows"], list) or len(result["rows"]) != len(expected):
        _error()
    if any(result[key] is not False for key in ("originalTaskVerified", "actualTitlesVerified", "healthVerified", "retryAuthorized")):
        _error()
    successes = failures = unknowns = 0
    failed = []
    for sku, row in zip(expected, result["rows"]):
        if not isinstance(row, dict) or set(row) != {"skuId", "outcome", "reason"} or row["skuId"] != sku or row["outcome"] not in ("success", "failed", "unknown") or not isinstance(row["reason"], str) or len(row["reason"]) > 2048 or re.search(r"https?://|www\.", row["reason"], re.I):
            _error()
        if row["outcome"] == "success":
            if row["reason"]:
                _error()
            successes += 1
        elif row["outcome"] == "failed":
            failures += 1
            failed.append(sku)
        else:
            unknowns += 1
    actual = {"successRowCount": successes, "failedRowCount": failures, "unknownRowCount": unknowns}
    if any(type(result[key]) is not int or result[key] != value for key, value in actual.items()) or result["complete"] is not (unknowns == 0) or result["verifiedFailureSkuIds"] != (failed if not unknowns else []) or successes > counts["success"] or failures > counts["failed"]:
        _error()
    if not unknowns and (successes != counts["success"] or failures != counts["failed"]):
        _error()


def check_observation(root, anchors, batch, value):
    anchor = anchors.get((batch, "create"))
    keys = {"anchorSha256", "identitySha256", "taskPageSha256", "resultSourceSha256", "taskRowSha256", "source", "state", "reason", "counts", "download", "result"}
    if anchor is None or not isinstance(value, dict) or set(value) != keys or redact(value) != value or value["anchorSha256"] != digest(anchor) or not all(_hash(value[key]) for key in ("identitySha256", "taskPageSha256")) or value["state"] not in ("unavailable", "pending", "unknown-result", "complete") or value["reason"] is not None and (not isinstance(value["reason"], str) or value["reason"] not in REASONS) or any(value[key] is not None and not _hash(value[key]) for key in ("resultSourceSha256", "taskRowSha256")):
        _error()
    source = value["source"]
    wanted = {"instanceId": anchor["instanceId"], "uploadedObjectSha256": anchor["objectSha256"], "startedAt": anchor["startedAt"]}
    if source is not None:
        if not isinstance(source, dict) or set(source) != set(wanted) or source["instanceId"] != wanted["instanceId"] or source["uploadedObjectSha256"] is not None and not _hash(source["uploadedObjectSha256"]) or source["startedAt"] is not None and not valid_time(source["startedAt"]):
            _error()
    if source != wanted:
        if value["resultSourceSha256"] is not None or value["taskRowSha256"] is not None or value["state"] != "unavailable" or value["counts"] is not None or value["download"] is not None or value["result"] is not None or value["reason"] != ("original-task-not-in-observed-page" if source is None else "original-task-object-or-time-mismatch"):
            _error()
        return
    expected = [row["skuId"] for row in root["scope"]["chunks"][batch - 1]]
    counts = value["counts"]
    if counts is not None and (not isinstance(counts, dict) or set(counts) != {"success", "failed"} or any(type(count) is not int or count < 0 for count in counts.values()) or sum(counts.values()) != len(expected)):
        _error()
    if value["state"] in ("unknown-result", "complete") and (counts is None or not _hash(value["taskRowSha256"]) or not _hash(value["resultSourceSha256"])):
        _error()
    if value["state"] == "pending" and counts is not None:
        _error()
    if value["result"] is None:
        if value["download"] is not None or value["state"] == "complete" or value["reason"] is None:
            _error()
        return
    if counts is None or value["state"] not in ("unknown-result", "complete"):
        _error()
    download = value["download"]
    if not isinstance(download, dict) or set(download) != {"resultObjectSha256", "resultFileSha256", "byteCount", "contentType"} or download["resultObjectSha256"] != value["resultSourceSha256"] or not _hash(download["resultFileSha256"]) or type(download["byteCount"]) is not int or not 0 < download["byteCount"] <= MAX_BYTES or download["contentType"] not in MIMES:
        _error()
    _parsed(value["result"], expected, counts)
    if value["result"]["resultFileSha256"] != download["resultFileSha256"] or (value["state"] == "complete") != value["result"]["complete"] or value["reason"] != (None if value["state"] == "complete" else "original-result-file-not-verified"):
        _error()


def _files(state, folder, root):
    directory = path(state, folder, root["importId"], suffix="")
    if not directory.exists():
        return {}
    if not directory.is_dir():
        _error()
    values = {}
    for item in directory.iterdir():
        file = safe_join(Path(state).absolute(), folder + "/" + root["importId"] + "/" + item.name)
        if not file.is_file() or not re.fullmatch(r"[0-9]{6}\.json", file.name) or not 1 <= int(file.stem) <= MAX_OBSERVATIONS or len(values) >= MAX_OBSERVATIONS:
            _error()
        values[int(file.stem)] = read_json(file)
    return values


def read_log(state, root, anchors, *, repair=False):
    observations = _files(state, FOLDERS[0], root)
    receipts = _files(state, FOLDERS[1], root)
    head_path = path(state, "short-title-result-heads", root["importId"])
    head_exists = head_path.exists()
    if head_exists and not head_path.is_file():
        _error()
    head = read_json(head_path) if head_exists else None
    if head_exists and (not isinstance(head, dict) or set(head) != {"importId", "fingerprint", "sequence", "receiptSha256"} or head["importId"] != root["importId"] or head["fingerprint"] != root["fingerprint"] or type(head["sequence"]) is not int or not 1 <= head["sequence"] <= MAX_OBSERVATIONS or not _hash(head["receiptSha256"])):
        _error()
    count = len(observations)
    if set(observations) != set(range(1, count + 1)) or set(receipts) - set(observations):
        _error()
    previous = root["fingerprint"]
    hashes = {0: previous}
    missing = []
    latest = {}
    for sequence in range(1, count + 1):
        item = observations[sequence]
        keys = {"importId", "fingerprint", "sequence", "previousReceiptSha256", "batch", "observedAt", "observation"}
        if not isinstance(item, dict) or set(item) != keys or redact(item) != item or item["importId"] != root["importId"] or item["fingerprint"] != root["fingerprint"] or type(item["sequence"]) is not int or item["sequence"] != sequence or item["previousReceiptSha256"] != previous or type(item["batch"]) is not int or not 1 <= item["batch"] <= len(root["scope"]["chunks"]) or not valid_time(item["observedAt"]):
            _error()
        check_observation(root, anchors, item["batch"], item["observation"])
        receipt = {"importId": root["importId"], "fingerprint": root["fingerprint"], "sequence": sequence, "observationSha256": digest(item), "previousReceiptSha256": previous}
        if sequence not in receipts:
            missing.append((sequence, receipt))
        elif not isinstance(receipts[sequence], dict) or set(receipts[sequence]) != set(receipt) or type(receipts[sequence]["sequence"]) is not int or receipts[sequence] != receipt:
            _error()
        previous = digest(receipt)
        hashes[sequence] = previous
        latest[item["batch"]] = item
    expected_head = {"importId": root["importId"], "fingerprint": root["fingerprint"], "sequence": count, "receiptSha256": previous}
    if not count:
        if head is not None or receipts:
            _error()
    elif head != expected_head:
        if not repair:
            _error()
        if not head_exists:
            if count != 1:
                _error()
        elif not isinstance(head, dict) or set(head) != set(expected_head) or head["importId"] != root["importId"] or head["fingerprint"] != root["fingerprint"] or type(head["sequence"]) is not int or head["sequence"] != count - 1 or head["receiptSha256"] != hashes[count - 1]:
            _error()
    if missing and not repair:
        _error()
    # Only reconstruct deterministic receipt/head from intact original observations.
    # A missing/changed observation is never repaired or replaced here.
    if repair:
        for sequence, receipt in missing:
            _once(safe_join(Path(state).absolute(), FOLDERS[1] + "/" + root["importId"] + f"/{sequence:06d}.json"), receipt)
        if count and head != expected_head:
            atomic_json(head_path, expected_head)
    return latest, count, previous


def append_observation(state, root, anchors, batch, observation, observed_at):
    check_observation(root, anchors, batch, observation)
    if not valid_time(observed_at):
        _error()
    latest, count, previous = read_log(state, root, anchors)
    if count >= MAX_OBSERVATIONS:
        raise SafetyError("native-result-observation-limit-reached")
    sequence = count + 1
    item = {"importId": root["importId"], "fingerprint": root["fingerprint"], "sequence": sequence, "previousReceiptSha256": previous, "batch": batch, "observedAt": observed_at, "observation": observation}
    receipt = {"importId": root["importId"], "fingerprint": root["fingerprint"], "sequence": sequence, "observationSha256": digest(item), "previousReceiptSha256": previous}
    for folder, value in zip(FOLDERS, (item, receipt)):
        _once(safe_join(Path(state).absolute(), folder + "/" + root["importId"] + f"/{sequence:06d}.json"), value)
    atomic_json(path(state, "short-title-result-heads", root["importId"]), {"importId": root["importId"], "fingerprint": root["fingerprint"], "sequence": sequence, "receiptSha256": digest(receipt)})


def summary(root, latest):
    complete = [batch for batch, item in latest.items() if item["observation"]["state"] == "complete"]
    return {"rowResultsVerified": len(complete) == len(root["scope"]["chunks"]), "resultObservedBatchCount": len(latest), "resultCompleteBatchCount": len(complete), "resultEvidenceHistorical": True, "retryAuthorized": False}


def result_rows(root, anchors, latest):
    output = []
    for batch, original in enumerate(root["scope"]["chunks"], 1):
        item = latest.get(batch)
        result = item["observation"]["result"] if item else None
        rows = {row["skuId"]: row for row in result["rows"]} if result else {}
        anchor = anchors.get((batch, "create"))
        for change in original:
            row = rows.get(change["skuId"], {"outcome": "unknown", "reason": "original-row-result-not-observed"})
            output.append({"batch": batch, "skuId": change["skuId"], "productId": change["productId"], "proposedShortTitle": change["shortTitle"], "instanceId": anchor["instanceId"] if anchor else None, "outcome": row["outcome"], "reason": row["reason"], "resultObservationSequence": item["sequence"] if item else None, "actualTitleVerified": False})
    return output
