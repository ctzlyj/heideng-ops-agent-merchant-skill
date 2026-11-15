"""Owned native browser worker entry; the Agent launches it with nonsecret IDs."""
import argparse
import json
import signal
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.short_title_worker import ShortTitleWorker
from heideng_merchant.safety import SafetyError


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True)
    p.add_argument("--worker", required=True)
    p.add_argument("--run", required=True)
    args = p.parse_args(argv)
    worker = ShortTitleWorker(args.state, args.worker, args.run)
    def stop(signum, frame):
        if worker.broker is not None:
            worker.broker.stop_requested.set()
        else:
            raise SafetyError("worker-stopped-before-owned-broker")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        print(json.dumps(worker.run(), ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"status": "original-worker-unconfirmed-inspect-original-evidence", "restartAllowed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
