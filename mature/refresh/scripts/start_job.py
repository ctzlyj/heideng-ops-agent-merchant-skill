"""Start one pipeline step detached and hidden, then print its pid.

usage: python start_job.py <run_dir> <script.py> <log_name> [args...]

A .pid file and matching log/err files land in the run directory so long
steps (download/generate/upload/patch) can be polled instead of blocking a
foreground shell, and no console window is created.
"""

import os
import json
import subprocess
import sys
from pathlib import Path


def main(argv):
    if len(argv) < 4:
        raise SystemExit("usage: start_job.py <run_dir> <script.py> <log_name> [args...]")
    run = Path(argv[1]).resolve()
    script = argv[2]
    log_name = argv[3]
    extra = argv[4:]
    python = sys.executable
    import _common as common
    allowed=json.loads((common.skill_root()/"provenance.json").read_text(encoding="utf-8"))["entrypoints"]
    if "scripts/"+script not in allowed:raise SystemExit("unregistered pipeline step")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    log = open(run / log_name, "ab", buffering=0)
    err = open(run / log_name.replace(".log", "-err.log"), "ab", buffering=0)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    proc = subprocess.Popen(
        [str(python), "-I", "-B", str(common.skill_root().parents[1]/"scripts/mature_entry.py"), str(Path(__file__).resolve().parent / script), str(run), *extra],
        cwd=str(run),
        stdout=log,
        stderr=err,
        env=env,
        startupinfo=startupinfo,
        creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000) if os.name=="nt" else 0,
    )
    pid_path = run / log_name.replace(".log", ".pid")
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    print("started %s pid=%s" % (script, proc.pid))


if __name__ == "__main__":
    main(sys.argv)
