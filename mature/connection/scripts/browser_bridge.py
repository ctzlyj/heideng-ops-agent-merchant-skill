"""Agent-only, private HostBrowser transport; never drives a browser itself.

The Agent supplies a task-local controller as a JSON argv array. The controller
reads {jobId, action} ONLY from stdin and emits one JSON observation to stdout.
Its stdout/stderr and every private API response stay in memory. dispatch() and
the CLI expose only fixed statuses/errors plus job/action identifiers and kind.
linker.api owns service discovery, its runtime BASE and session authentication.

Before executing a controller, durably save {jobId, actionId, phase} under
sl.linker_home(), outside the Skill/package. A process lock prevents concurrent
dispatchers; OS locks release on exit/crash. A dispatched receipt blocks replay
across --once invocations. An uncertain report is checked, never resubmitted.
"consumed" means the action is no longer pending, NOT proof of browser success
or accepted reporting. The Agent must reconcile uncertain browser outcomes.
once=False drains available actions until idle, a rejection or uncertainty.
No controller result, navigation address, credential or identity is persisted.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import linker

_KINDS = {"open_login", "observe", "open_oauth", "confirm", "close"}
_PHASES = {"dispatched", "accepted", "consumed"}
_TERMINAL = {"success", "failed", "cancelled", "mismatch"}
_SHELLS = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
           "sh", "bash", "zsh", "dash", "csh", "fish", "wscript.exe", "cscript.exe"}
_CHALLENGES = {"", "captcha", "sms", "qr", "login", "device", "verification", "unknown", "account-risk-blocked", "confirmation-pending"}


class _Invalid(Exception):
    """Internal control flow only; never print exception messages."""


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def _public(status, action=None, job_id=None, error=None):
    result = {"ok": status in {"accepted", "idle"}, "status": status}
    if _identifier(job_id):
        result["jobId"] = job_id
    if isinstance(action, dict) and _identifier(action.get("id")):
        result["actionId"] = action["id"]
        if action.get("kind") in _KINDS:
            result["actionKind"] = action["kind"]
    if error:
        result["error"] = error  # callers pass only fixed literals
    return result


def _controller_valid(controller):
    if not isinstance(controller, list) or not controller or not controller[0]:
        return False
    if any(not isinstance(arg, str) or re.search(r"[\x00\r\n]", arg) for arg in controller):
        return False
    executable = Path(controller[0]).name.lower()
    return executable not in _SHELLS and not executable.endswith((".cmd", ".bat"))


def _api(path, payload=None, timeout=20):
    try:
        status, data = linker.api(path, payload=payload, timeout=timeout)
        return status, data if isinstance(data, dict) else {}
    except Exception:
        return 0, {}


def _action(timeout):
    status, data = _api("/api/browser-action", timeout=timeout)
    if status != 200 or data.get("ok") is not True or "action" not in data:
        raise _Invalid
    action = data["action"]
    if action is not None:
        if (not _identifier(data.get("jobId")) or not isinstance(action, dict)
                or not _identifier(action.get("id")) or action.get("kind") not in _KINDS):
            raise _Invalid
    return data


def _job(timeout):
    status, data = _api("/api/job", timeout=timeout)
    if status != 200 or data.get("ok") is not True or "job" not in data:
        raise _Invalid
    job = data["job"]
    if job is not None and (not isinstance(job, dict) or not _identifier(job.get("id"))):
        raise _Invalid
    return job


@contextlib.contextmanager
def _lock(home):
    home.mkdir(parents=True, exist_ok=True)
    with (home / "browser-bridge.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_receipt(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (not isinstance(value, dict) or set(value) != {"jobId", "actionId", "phase"}
            or not _identifier(value.get("jobId")) or not _identifier(value.get("actionId"))
            or value.get("phase") not in _PHASES):
        raise _Invalid
    return value


def _save_receipt(path, job_id, action_id, phase):
    value = {"jobId": job_id, "actionId": action_id, "phase": phase}
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".browser-bridge-", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _report(stdout):
    value = json.loads(stdout)
    if not isinstance(value, dict) or value.get("ok") is False or value.get("error"):
        raise _Invalid
    context = value.get("contextId")
    if not isinstance(context, str) or not context or len(context) > 200 or type(value.get("owned")) is not bool:
        raise _Invalid
    result = {"contextId": context, "owned": value["owned"]}
    for key in ("isolated", "verifiedReuse", "loggedIn"):
        if key in value:
            if type(value[key]) is not bool:
                raise _Invalid
            result[key] = value[key]
    if "identity" in value:
        if not isinstance(value["identity"], dict):
            raise _Invalid
        identity = {}
        for key in ("shopName", "venderId", "shopId"):
            if key in value["identity"]:
                item = value["identity"][key]
                if not isinstance(item, str) and not (key != "shopName" and type(item) is int):
                    raise _Invalid
                identity[key] = item
        result["identity"] = identity
    if "profileDir" in value:
        from heideng_merchant.mature_runtime import merchant_profile_directory
        directory=merchant_profile_directory(value.get("profileDir"))
        if directory is None:raise _Invalid
        result["profileDir"]=str(directory)
    if value.get("browserChannel") in ("chrome","msedge","chromium"):result["browserChannel"]=value["browserChannel"]
    if value.get("requiresUserAction") in ("请在京东商城 App 完成账号安全验证，再回到当前页面继续。",):result["requiresUserAction"]=value["requiresUserAction"]
    if "challenge" in value:
        challenge = value["challenge"]
        if not isinstance(challenge, str):
            raise _Invalid
        result["challenge"] = challenge if challenge in _CHALLENGES else "verification"
    return result


def _reconcile(path, job_id, action, timeout, error):
    # Always check both endpoints, even if one failed. No writes or child retry.
    snapshot, job = None, None
    try:
        snapshot = _action(timeout)
    except Exception:
        pass
    try:
        job = _job(timeout)
    except Exception:
        pass
    status = "needs_reconciliation"
    if snapshot is not None and job is not None:
        if snapshot.get("jobId") != job_id or job.get("id") != job_id:
            status = "stale_action"
        elif snapshot["action"] is None or snapshot["action"]["id"] != action["id"]:
            status = "consumed"
    if status in {"consumed", "stale_action"}:
        try:
            _save_receipt(path, job_id, action["id"], "consumed")
        except Exception:
            return _public("needs_reconciliation", action, job_id, "receipt_unavailable")
    return _public(status, action, job_id, error)


def _dispatch_locked(controller, once, timeout, receipt_path):
    try:
        receipt = _load_receipt(receipt_path)
    except Exception:
        return _public("needs_reconciliation", error="receipt_unavailable")
    last = None
    while True:
        try:
            snapshot = _action(timeout)
        except KeyError as error:
            if error.args == ("HEIDENG_MERCHANT_PACKAGE",):return _public("error",error="missing-package-env")
            return _public("error",error="connection-environment-unavailable")
        except Exception:
            return _public("error", error="action_unavailable")
        action, job_id = snapshot["action"], snapshot.get("jobId")
        job = None
        if action is not None or receipt is not None and receipt["phase"] == "dispatched":
            try:
                job = _job(timeout)
            except Exception:
                return _public("needs_reconciliation", action, job_id, "job_unavailable")
        if (receipt is not None and action is not None and receipt["jobId"] == job_id
                and receipt["actionId"] == action["id"]):
            return _public("needs_reconciliation", action, job_id, "result_unknown")
        if action is None:
            return last or _public("idle")
        if (job is None or job.get("id") != job_id
                or job.get("status") in _TERMINAL and action["kind"] != "close"):
            return _public("stale_action", action, job_id, "action_expired")
        try:
            _save_receipt(receipt_path, job_id, action["id"], "dispatched")
        except Exception:
            return _public("needs_reconciliation", action, job_id, "receipt_unavailable")
        try:
            process = subprocess.run(controller, input=json.dumps({"jobId": job_id, "action": action}, ensure_ascii=False),
                                     capture_output=True, text=True, timeout=timeout,
                                     creationflags=linker.CREATE_NO_WINDOW, shell=False,
                                     encoding="utf-8", errors="strict")
        except subprocess.TimeoutExpired:
            return _reconcile(receipt_path, job_id, action, timeout, "controller_timeout")
        except Exception:
            return _reconcile(receipt_path, job_id, action, timeout, "controller_failed")
        if process.returncode != 0:
            return _reconcile(receipt_path, job_id, action, timeout, "controller_failed")
        try:
            report = _report(process.stdout)
        except Exception:
            return _reconcile(receipt_path, job_id, action, timeout, "invalid_controller_output")
        status, data = _api("/api/browser-report", {"jobId": job_id, "actionId": action["id"], "result": report}, timeout)
        if status != 200 or data.get("ok") is not True:
            return _reconcile(receipt_path, job_id, action, timeout,
                              "report_not_accepted" if status else "report_unknown")
        try:
            _save_receipt(receipt_path, job_id, action["id"], "accepted")
        except Exception:
            return _public("needs_reconciliation", action, job_id, "receipt_unavailable")
        last = _public("accepted", action, job_id)
        if once:
            return last
        receipt = {"jobId": job_id, "actionId": action["id"], "phase": "accepted"}


def dispatch(controller: list[str], once=True, timeout=20):
    """Return a public status. Never retry a controller action or unknown report."""
    if not _controller_valid(controller):
        return _public("error", error="invalid_controller")
    if (type(once) is not bool or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        return _public("error", error="invalid_options")
    try:
        home = linker.sl.linker_home()
        with _lock(home):
            return _dispatch_locked(list(controller), once, timeout, home / "browser-bridge-receipt.json")
    except KeyError as error:
        if error.args == ("HEIDENG_MERCHANT_PACKAGE",):return _public("error",error="missing-package-env")
        return _public("error",error="connection-environment-unavailable")
    except Exception:
        return _public("needs_reconciliation", error="receipt_unavailable")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Invalid  # argparse's default includes raw argv in stderr


def main(argv=None):
    """Single-action Agent entry point; --once remains a compatible option."""
    parser = _Parser(description="Agent private browser transport")
    parser.add_argument("--controller", required=True)
    parser.add_argument("--once", action="store_true", default=True,
                        help="Dispatch one action and return (the default).")
    parser.add_argument("--timeout", default="20")
    try:
        args = parser.parse_args(argv)
        try:
            controller = json.loads(args.controller)
        except Exception:
            result = _public("error", error="invalid_controller")
        else:
            try:
                timeout = float(args.timeout)
            except Exception:
                result = _public("error", error="invalid_options")
            else:
                result = dispatch(controller, once=args.once, timeout=timeout)
    except Exception:
        result = _public("error", error="invalid_options")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
