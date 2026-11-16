"""Run the whole refresh pipeline for one run directory, resumable.

usage: python run_all.py <run_dir> [--steps a,b,c] [--from STEP] [--retries N]
                          [--wait-quota MINUTES] [productId ...]

Every step is ledger-driven, so re-running this after any interruption simply
continues where the previous attempt stopped. A step that dies silently (the
upload worker did this once at 1440/3378 with an empty stderr) is restarted up
to --retries times before the pipeline stops.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

DEFAULT_STEPS = ["build_plan", "download_sources", "generate", "upload", "patch", "verify", "report"]
QUOTA_BLOCKED = 3


def parse_args(argv):
    steps, start_from = list(DEFAULT_STEPS), ""
    retries, wait_minutes, pids = 3, 0.0, []
    index = 2
    while index < len(argv):
        item = argv[index]
        if item == "--steps":
            steps = [part.strip() for part in argv[index + 1].split(",") if part.strip()]
            index += 2
            continue
        if item == "--from":
            start_from = argv[index + 1]
            index += 2
            continue
        if item == "--retries":
            retries = int(argv[index + 1])
            index += 2
            continue
        if item == "--wait-quota":
            wait_minutes = float(argv[index + 1])
            index += 2
            continue
        pids.append(item)
        index += 1
    if start_from:
        steps = steps[steps.index(start_from):]
    return steps, retries, wait_minutes, pids


def run_step(run, step, pids, wait_minutes):
    script = Path(__file__).resolve().parent / (step + ".py")
    if not script.exists():
        raise SystemExit("missing step script: %s" % script)
    command = [sys.executable, "-I", "-B", str(common.skill_root().parents[1]/"scripts/mature_entry.py"), str(script), str(run)] + list(pids)
    if step == "generate" and wait_minutes:
        command += ["--wait-quota", str(wait_minutes)]
    started = time.time()
    process = subprocess.run(command, cwd=str(run), capture_output=True)
    text_out = process.stdout.decode("utf-8", "replace")
    text_err = process.stderr.decode("utf-8", "replace")
    log = run / ("runall-%s.log" % step)
    log.write_text(text_out + ("\n[stderr]\n" + text_err if text_err.strip() else ""),
                   encoding="utf-8")
    tail = [line for line in text_out.strip().splitlines() if line.strip()][-3:]
    for line in tail:
        print("   %s" % line, flush=True)
    return process.returncode, round(time.time() - started, 1), text_err[-400:]


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: run_all.py <run_dir> [--steps ...] [--from STEP] [--retries N]"
                         " [--wait-quota MINUTES] [productId ...]")
    run = Path(argv[1]).resolve()
    steps, retries, wait_minutes, pids = parse_args(argv)
    state_path = run / "run-state.json"
    state = common.load_json(state_path) or {}
    print("run: %s" % run)
    print("steps: %s" % ",".join(steps))

    for step in steps:
        attempts = 0
        while True:
            attempts += 1
            print("[%s] attempt %d" % (step, attempts), flush=True)
            code, elapsed, err = run_step(run, step, pids, wait_minutes)
            state[step] = {"returncode": code, "attempts": attempts, "seconds": elapsed}
            common.save_json(state_path, state)
            if code == 0:
                print("[%s] ok in %.0fs" % (step, elapsed), flush=True)
                break
            if code == QUOTA_BLOCKED:
                print("[%s] 停在额度门槛：%s" % (step, err.strip()[:200] or "见日志"), flush=True)
                print("额度恢复后执行：python scripts/run_all.py <run> --from %s" % step, flush=True)
                return QUOTA_BLOCKED
            if step in {"generate","upload","patch","patch_detail"}:
                print("Preserve original receipts; no automatic replay of paid/write step",flush=True)
                return code or 1
            if attempts > retries:
                print("[%s] failed after %d attempts (see runall-%s.log)" % (step, attempts, step),
                      flush=True)
                print("继续可用：python scripts/run_all.py <run> --from %s" % step, flush=True)
                return code or 1
            print("[%s] non-zero (%d), restarting in 20s" % (step, code), flush=True)
            time.sleep(20)

    print("pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

