"""One-time compatibility check against the verified *installed* old implementation.
No legacy business implementation is copied into the new package or executed as a task.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
from .safety import SafetyError, clean_environment

def check_legacy_update(target, state, version):
    from .distribution import version_key
    if version_key(version) >= (0, 2, 0):
        return
    target = Path(target).resolve()
    if not (target/'heideng_merchant/update_gate.py').is_file():
        # Only old bare installation fixtures with NO business/runtime paths are admissible.
        managed={'install.lock','install-history.json','install-journal.json'}
        if any(path.name not in managed for path in Path(state).iterdir()):
            raise SafetyError('legacy-operation-state-needs-original-package-review')
        return
    # Caller already verified every old installed byte against its original receipt.
    code = "import sys;sys.path.insert(0,sys.argv[1]);from heideng_merchant.update_gate import busy;print('busy' if busy(sys.argv[2]) else 'idle')"
    try:
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(target), str(Path(state).resolve())], env=clean_environment(Path(state)/'upgrade-probe-home'), capture_output=True, text=True, encoding='utf-8', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise SafetyError('legacy-operation-state-review-unavailable') from None
    if result.returncode or result.stdout.strip() not in {'idle', 'busy'}:
        raise SafetyError('legacy-operation-state-review-unavailable')
    if result.stdout.strip() == 'busy':
        raise SafetyError('active-task-update-deferred')


def quiesce_mature_connector(target, state):
    """Use the verified installed connector's own idle-only shutdown, not new auth gates."""
    target = Path(target).resolve()
    entry = target/'mature/connection/scripts/linker.py'
    if not entry.is_file():
        return
    from .mature_runtime import child_environment
    from .runtime_dependencies import runtime_python
    environment = child_environment(Path(state))
    environment['HEIDENG_MERCHANT_PACKAGE'] = str(target)
    # The installed files are verified by the caller before this compatibility probe.
    # Session transport stays in subprocess memory and never reaches logs/argv/receipts.
    code = ("import sys,runpy;sys.path.insert(0,sys.argv[1]);"
            "from heideng_merchant.mature_runtime import install_network_guard;install_network_guard();"
            "m=runpy.run_path(sys.argv[2]);"
            "m['stop_stale_server']() if m['server_info']() else None")
    try:
        result = subprocess.run([str(runtime_python(state)), '-I', '-B', '-c', code,
                                 str(target), str(entry)], env=environment,
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise SafetyError('mature-connector-update-review-unavailable') from None
    if result.returncode:
        raise SafetyError('mature-connector-active-or-unidentified-update-deferred')
