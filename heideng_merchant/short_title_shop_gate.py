"""Quarantine same-shop native title writes across new plans and other tools."""
import re
from pathlib import Path

from .safety import SafetyError, safe_join
from .short_title_import_state import record, evidence, ID

EVENTS = ("short-title-import-attempts", "short-title-import-dispatches", "short-title-import-acks", "short-title-import-observations", "short-title-import-anchors", "short-title-import-approvals", "short-title-result-observations", "short-title-result-receipts")


def _entries(state, folder):
    directory = safe_join(state, folder)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise SafetyError("unresolved-native-title-state-layout")
    return [safe_join(state, folder + "/" + item.name) for item in directory.iterdir()]


def assert_resolved(ops, shop, exclude_import_id=None):
    state = Path(ops.state).absolute()
    if exclude_import_id is not None and (not isinstance(exclude_import_id, str) or ID.fullmatch(exclude_import_id) is None):
        raise SafetyError("exact-own-native-import-exclusion-required")
    roots = set()
    for file in _entries(state, "short-title-imports"):
        if file.is_file() and file.suffix == ".lock" and ID.fullmatch(file.stem):
            continue
        if not file.is_file() or file.suffix != ".json" or ID.fullmatch(file.stem) is None:
            raise SafetyError("unresolved-native-title-state-layout")
        roots.add(file.stem)
        if file.stem == exclude_import_id:
            # Native coordinator has independently read/validated this exact root.
            # Its existing one-shot attempt rules still forbid self replay.
            continue
        original = record(state, ops.client, file.stem)
        history = evidence(state, original)
        from .short_title_result_state import read_log
        read_log(state, original, history[3])
        owner = original["scope"]["shop"]
        same = owner["profile"] == shop["profile"] or all(str(owner[key]) == str(shop[key]) for key in ("venderId", "shopId"))
        if same and any(history[index] for index in (1, 2, 3, 4, 5)):
            # Processing results are not C3 title/audit/health completion.
            raise SafetyError("shop-has-unresolved-native-title-import-recover-original-before-new-write")
    for folder in EVENTS:
        for directory in _entries(state, folder):
            if not directory.is_dir() or directory.name not in roots:
                raise SafetyError("orphan-native-title-evidence-before-new-write")
    for file in _entries(state, "short-title-result-heads"):
        if not file.is_file() or file.suffix != ".json" or file.stem not in roots:
            raise SafetyError("orphan-native-title-evidence-before-new-write")
