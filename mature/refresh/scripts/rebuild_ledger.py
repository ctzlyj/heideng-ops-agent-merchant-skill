"""Rebuild the generation ledger from the files already on disk.

usage: python rebuild_ledger.py <run_dir> [--dry-run]

Needed when a run died while saving internal-generation.json: the images exist
but the ledger thinks they are missing, so generate would redo (and re-bill)
every one of them. Each planned key with a valid PNG is marked succeeded.
"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: rebuild_ledger.py <run_dir> [--dry-run]")
    run = Path(argv[1]).resolve()
    dry = "--dry-run" in argv
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json")
    ledger_path = run / "internal-generation.json"
    ledger = common.load_json(ledger_path) or {}

    recovered, broken = [], []
    for key in plan.get("tasks") or {}:
        record = ledger.get(key) or {}
        if record.get("status") in ("succeeded", "rejected"):
            continue
        path = run / "generated" / (key + ".png")
        if not path.exists():
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception:  # noqa: BLE001
            broken.append(key)
            path.unlink(missing_ok=True)
            continue
        recovered.append(key)
        ledger[key] = {"status": "succeeded", "recovered": True, "bytes": path.stat().st_size}

    if not dry:
        common.save_json(ledger_path, ledger)
    ok = sum(1 for value in ledger.values() if value.get("status") == "succeeded")
    rejected = sum(1 for value in ledger.values() if value.get("status") == "rejected")
    pending = len(plan.get("tasks") or {}) - ok - rejected
    print("recovered=%d broken_removed=%d | ledger succeeded=%d rejected=%d pending=%d"
          % (len(recovered), len(broken), ok, rejected, pending))
    if dry:
        print("dry run: ledger not written")


if __name__ == "__main__":
    main(sys.argv)

