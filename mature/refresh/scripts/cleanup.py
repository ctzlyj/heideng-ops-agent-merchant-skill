"""Delete the heavy intermediates of a finished run.

usage: python cleanup.py <run_dir> [--force] [--keep generated]

Refuses to run unless final-verification.json is fully green (or --force), so a
half-finished run never loses the images it still needs. Keeps every ledger,
plans, snapshots and the report; removes sources/, generated/, references/ and
patch-bodies/ by default.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

HEAVY = ("sources", "generated", "references", "patch-bodies")


def tree_size(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: cleanup.py <run_dir> [--force] [--keep generated]")
    run = Path(argv[1]).resolve()
    force = "--force" in argv
    keep = set()
    if "--keep" in argv:
        keep = {item.strip() for item in argv[argv.index("--keep") + 1].split(",") if item.strip()}

    report = common.load_json(run / "final-verification.json")
    if not report:
        raise SystemExit("no final-verification.json: run verify.py first")
    failed = [pid for pid, entry in report.items() if not entry.get("ok")]
    if failed and not force:
        raise SystemExit("verification still failing for %d product(s): %s (use --force to clean anyway)"
                         % (len(failed), ", ".join(failed[:5])))

    freed = 0
    for name in HEAVY:
        if name in keep:
            continue
        folder = run / name
        size = tree_size(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        freed += size
        print("removed %s: %.1f MB" % (name, size / 1048576))
    print("freed %.1f MB; kept plan/ledgers/report" % (freed / 1048576))


if __name__ == "__main__":
    main(sys.argv)

