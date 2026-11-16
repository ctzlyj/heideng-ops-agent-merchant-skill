"""Read-only worker liveness and bounded public diagnostics; never kill by PID."""
from __future__ import annotations
import math,os,re,time
from dataclasses import dataclass
from pathlib import Path
from .safety import SafetyError,atomic_json,read_json,safe_join
from .state import FileLock

EVENTS={'cleanup-verified','worker-start','worker-failed','worker-finished','flow-stage','worker-reconciled'}
STAGES={'starting_worker','initializing_worker','created','waiting_login','waiting_shop_confirmation','waiting_callback_server','waiting_oauth','verifying_cli','ready','identity_mismatch','oauth_failed','auth_outcome_unknown','cancelled','timed_out','browser_failed'}


def _valid_pid(pid):
    return type(pid) == int and 0 < pid <= 0xffffffff


def _valid_creation_time(value):
    # Native Windows FILETIME ticks, not wall-clock startedAt or a rounded float.
    return type(value) == int and 0 < value < 2**64


def process_state(pid):
 if not _valid_pid(pid):return 'unknown'
 if os.name!='nt':
  try:os.kill(pid,0)
  except ProcessLookupError:return 'exited'
  except (PermissionError,OSError):return 'unknown'
  return 'alive'
 import ctypes
 from ctypes import wintypes
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
 kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
 handle=kernel.OpenProcess(0x00100000,False,pid) # SYNCHRONIZE only, no termination permission
 if not handle:return 'exited' if ctypes.get_last_error()==87 else 'unknown'
 try:
  result=kernel.WaitForSingleObject(handle,0)
  return 'exited' if result==0 else 'alive' if result==258 else 'unknown'
 finally:kernel.CloseHandle(handle)


def process_identity(pid):
    """Read state and creation time from the SAME native handle, without killing.

    creationTime is a positive integer Windows FILETIME, or None if the PID is
    absent / the platform has no identity probe. Failure to inspect is unknown.
    Startup integration may persist {pid, creationTime} as processProof while
    alive; a worker can additionally record its numeric os.getppid() and that
    parent's creationTime. Never manufacture this evidence after an old exit.
    """
    result = {"pid": pid, "state": "unknown", "creationTime": None}
    if not _valid_pid(pid):
        return result
    if os.name != "nt":
        result["state"] = process_state(pid)
        return result
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, never TERMINATE.
    handle = kernel.OpenProcess(0x00101000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            result["state"] = "exited"
        return result
    try:
        created, ended, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return result
        creation_time = (created.dwHighDateTime << 32) | created.dwLowDateTime
        if not _valid_creation_time(creation_time):
            return result
        result["creationTime"] = creation_time
        wait = kernel.WaitForSingleObject(handle, 0)
        result["state"] = "exited" if wait == 0 else "alive" if wait == 258 else "unknown"
        return result
    finally:
        kernel.CloseHandle(handle)


@dataclass(frozen=True)
class OwnedWorkerState:
    """Liveness evidence only: even state='exited' does NOT authorize replay."""
    state: str
    worker_pid: int | None = None
    pids: tuple[int, ...] = ()
    ownership: str = "unverified"


def _receipt_identity(record, job, *, worker=False):
    if (not isinstance(record, dict) or record.get("taskId") != job
            or not _valid_pid(record.get("workerPid"))):
        raise ValueError("invalid-task-bound-process-receipt")
    if "processProof" not in record:
        return record["workerPid"], None
    proof = record["processProof"]
    required = {"pid", "creationTime"}
    ancestry = {"parentPid", "parentCreationTime"}
    if (not isinstance(proof, dict) or set(proof) not in
            (required, required | ancestry if worker else required)
            or not _valid_pid(proof.get("pid")) or proof["pid"] != record["workerPid"]
            or not _valid_creation_time(proof.get("creationTime"))):
        raise ValueError("invalid-process-proof")
    if ancestry <= set(proof):
        if (not _valid_pid(proof["parentPid"]) or proof["parentPid"] == proof["pid"]
                or not _valid_creation_time(proof["parentCreationTime"])
                or proof["creationTime"] < proof["parentCreationTime"]):
            raise ValueError("invalid-parent-process-proof")
    return record["workerPid"], dict(proof)


def probe_owned_worker(launch, handle, job, process_probe=None):
    """Check EVERY unique launch/worker PID; never infer ownership by equality.

    The taskId-bound handle's workerPid is the authoritative actual worker; the
    launch workerPid may be a Windows venv redirector. An empty {} handle retains
    launch-only startup recovery. Wrong-task/malformed receipts or partial new
    proofs fail closed BEFORE probing. Injected process_probe(pid) may return the
    existing 'alive'/'exited'/'unknown' strings, or process_identity's dictionary.
    Passing the standard process_state probe uses process_identity internally so
    newly recorded creation evidence is checked without changing the old API.
    A mismatched observed creationTime (PID reuse) always refuses reconciliation.

    Optional startup processProof schema (integer native FILETIME ticks):
      launch: {pid, creationTime}
      handle: {pid, creationTime, parentPid, parentCreationTime}
    Distinct PIDs require a matching parent PID/time and ordered creation times.
    This is recorded-ancestry evidence, not retrospective OS ancestry discovery.
    Without either proof, ownership='legacy-task-bound' explicitly means ONLY a
    task-bound worker receipt, not ancestry. Distinct legacy PIDs additionally
    require both positive finite numeric startedAt timestamps within 30 seconds
    (absolute difference: the worker can beat the parent receipt write). These
    timestamps are a bounded receipt sanity check, NOT ancestry/creation proof.
    Both exits AND the caller's original
    exclusive owner/task locks are required for legacy recovery.

    Caller MUST keep immutable snapshots of launch, handle AND task, acquire both
    original full-lifetime locks, re-read all three unchanged, and call this helper
    again under the locks before mutating. It must separately retain the pre-OAuth
    safe-restart boundary; post-OAuth/unknown outcomes NEVER authorize replay.
    This helper acquires no locks, writes no receipts, and decides no auth policy.
    """
    unknown = OwnedWorkerState("unknown")
    if not isinstance(job, str) or not re.fullmatch("[a-f0-9]{24}", job):
        return unknown
    try:
        launch_pid, launch_proof = _receipt_identity(launch, job)
        if not isinstance(handle, dict):
            return unknown
        worker_pid, worker_proof = (_receipt_identity(handle, job, worker=True)
                                    if handle else (launch_pid, launch_proof))
        pids = tuple(dict.fromkeys((launch_pid, worker_pid)))
        if handle and worker_pid != launch_pid and launch_proof is None and worker_proof is None:
            started = (launch.get("startedAt"), handle.get("startedAt"))
            try:
                if (any(type(value) not in (int, float) or value <= 0 or not math.isfinite(value)
                        for value in started) or abs(started[0] - started[1]) > 30):
                    return unknown
            except OverflowError:
                return unknown
        ownership = "legacy-task-bound" if handle else "launch-only"
        if handle and (launch_proof is not None or worker_proof is not None):
            if launch_proof is None or worker_proof is None:
                return unknown
            if worker_pid == launch_pid:
                if launch_proof["creationTime"] != worker_proof["creationTime"]:
                    return unknown
                ownership = "recorded-process"
            else:
                if (worker_proof.get("parentPid") != launch_pid
                        or worker_proof.get("parentCreationTime") != launch_proof["creationTime"]):
                    return unknown
                ownership = "recorded-ancestry"
    except (ValueError, TypeError):
        return unknown
    expected = {launch_pid: launch_proof, worker_pid: worker_proof}
    probe = process_identity if process_probe is None or process_probe is process_state else process_probe
    states = []
    for pid in pids:
        state = "unknown"
        try:
            observation = probe(pid)
            if isinstance(observation, dict):
                observed_pid = observation.get("pid", pid)
                ctime = observation.get("creationTime")
                proof = expected[pid]
                if (_valid_pid(observed_pid) and observed_pid == pid
                        and (ctime is None or _valid_creation_time(ctime))
                        and (proof is None or ctime is None or ctime == proof["creationTime"])):
                    state = observation.get("state")
            else:
                state = observation
            if not isinstance(state, str) or state not in {"alive", "exited", "unknown"}:
                state = "unknown"
        except Exception:
            pass  # Inspection failure never proves exit, and never skips the other PID.
        states.append(state)
    state = "unknown" if "unknown" in states else "alive" if "alive" in states else "exited"
    return OwnedWorkerState(state, worker_pid, pids, ownership)


def record_event(state,job,event,data):
 if not isinstance(job,str) or not re.fullmatch('[a-f0-9]{24}',job) or event not in EVENTS:raise SafetyError('auth-diagnostic-event-required')
 path=safe_join(Path(state),'auth/events/'+job+'.json')
 item={'time':time.time(),'taskId':job,'event':event}
 if data.get('stage') in STAGES:item['stage']=data['stage']
 if data.get('status') in {'running','failed','unknown','completed','cancelled'}:item['status']=data['status']
 item['authorizationStarted']=data.get('authorizationStarted') is True
 try:
  with FileLock(path.with_suffix('.lock'),timeout=.1):
   previous=read_json(path,[])
   if not isinstance(previous,list):previous=[]
   atomic_json(path,(previous+[item])[-64:])
 except (OSError,SafetyError):pass # Diagnostic I/O must never alter authorization outcome.
