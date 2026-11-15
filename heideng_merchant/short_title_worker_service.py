"""Agent-facing merchant worker IPC and hidden process launch; no credential argv."""
import json
import os
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from .auth_runtime import BrowserRuntime
from .official import OfficialClient
from .operations import Operations, digest
from .safety import SafetyError, clean_environment, safe_join, redact
from .state import FileLock
from .video_delivery import _once
from .short_titles import ShortTitlePlans
from .short_title_imports import ShortTitleImports
from .short_title_worker_gate import claim_record, unresolved, ENDPOINTS, LAUNCHES
from . import short_title_worker_state as original


def broker_request(state, job, run, method, path, command=None):
    ep = original._read(original.file(state, ENDPOINTS, job["workerId"], run["runId"]))
    if not isinstance(ep, dict) or ep != {"workerId": job["workerId"], "runId": run["runId"], "workerFingerprint": job["fingerprint"], "port": ep.get("port"), "claimSha256": digest(claim_record(job, run))} or type(ep["port"]) is not int or not 1024 <= ep["port"] <= 65535:
        raise SafetyError("original-owned-worker-endpoint-required")
    from .short_title_worker_broker import allowed_request
    headers = {"Host": "127.0.0.1:" + str(ep["port"]), "X-Heideng-Local": "1", "X-Heideng-Worker": job["workerId"], "X-Heideng-Fingerprint": job["fingerprint"]}
    if not allowed_request(method, path, headers, ep["port"], job["workerId"], job["fingerprint"]):
        raise SafetyError("owned-worker-ipc-route-required")
    raw = None
    if command is not None:
        original._check_command(state, job, run, command)
        raw = json.dumps(command, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request("http://127.0.0.1:" + str(ep["port"]) + path, data=raw, method=method, headers=headers)
    # Never follow a redirect to a remote origin or consult ambient proxy settings.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=5) as response:
        length = response.headers.get("Content-Length", "")
        if not length.isdigit() or not 0 < int(length) <= 64 * 1024 or response.headers.get_content_type() != "application/json":
            raise SafetyError("bounded-worker-ipc-response-required")
        raw = response.read(64 * 1024 + 1)
        if len(raw) != int(length):
            raise SafetyError("complete-worker-ipc-response-required")
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise SafetyError("unique-worker-ipc-response-required")
            out[k] = v
        return out
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=lambda v: (_ for _ in ()).throw(SafetyError("finite-worker-response-required")))
    if not isinstance(value, dict) or redact(value) != value:
        raise SafetyError("public-worker-ipc-response-required")
    if path == "/status" and (value.get("workerId") != job["workerId"] or value.get("workerFingerprint") != job["fingerprint"] or value.get("runId") != run["runId"]):
        raise SafetyError("exact-original-worker-response-required")
    if method == "POST" and value.get("requestId") != command["requestId"]:
        raise SafetyError("exact-original-worker-command-response-required")
    return value


class ShortTitleWorkerService:
    def __init__(self, state, *, client=None, runtime=None, starter=None, request=None, runtime_verifier=None, startup_wait=5):
        self.state = Path(state).absolute()
        self.client = client if client is not None else OfficialClient(self.state)
        self.runtime = runtime if runtime is not None else BrowserRuntime(self.state)
        self.starter = starter or subprocess.Popen
        self.request = request or broker_request
        self.runtime_verifier = runtime_verifier or original.runtime_binding
        self.startup_wait = startup_wait

    def _job_run(self, worker_id):
        job = original.read_job(self.state, worker_id)
        runs = original.read_runs(self.state, job)
        if not runs:
            raise SafetyError("original-worker-run-required")
        # UUIDs are not chronology. Only one run can remain unclosed.
        active = [r for rid, r in runs.items() if not original.file(self.state, "short-title-worker-closed", worker_id, rid).exists()]
        if len(active) > 1:
            raise SafetyError("single-original-worker-run-required")
        if active:
            return job, active[0]
        # A closed summary has no current actor and never addresses old loopback ports.
        return job, None

    def status(self, worker_id):
        job, run = self._job_run(worker_id)
        link = original.read_link(self.state, job, self.client)
        out = {"workerId": worker_id, "workerFingerprint": job["fingerprint"], "runId": run["runId"] if run else None, "status": "original-worker-outcome-unconfirmed" if run else "closed", "workerReachable": False, "localResourcesClosed": run is None, "resumeReadOnly": run["resumeReadOnly"] if run else False, "startAuthorizesWrites": False}
        if link:
            out.update(original.public_result(ShortTitleImports(self.state, self.client).status(link["importId"])))
            out["nativeStatus"] = out["status"]
            out["status"] = "original-worker-outcome-unconfirmed" if run else "closed"
        if run is not None:
            try:
                value = self.request(self.state, job, run, "GET", "/status")
                if not isinstance(value, dict) or value.get("workerId") != worker_id or value.get("runId") != run["runId"] or value.get("workerFingerprint") != job["fingerprint"]:
                    raise SafetyError("exact-original-worker-response-required")
                out.update(value)
                out["workerReachable"] = True
            except Exception:
                pass
        return out

    def _spawn(self, job, run):
        home = safe_join(self.state, "short-title-worker-home/" + job["workerId"] + "/" + run["runId"])
        home.mkdir(parents=True, exist_ok=True)
        args = [str(self.runtime.python()), "-I", str(Path(__file__).resolve().parents[1] / "scripts" / "short_title_worker.py"), "--state", str(self.state), "--worker", job["workerId"], "--run", run["runId"]]
        options = {"cwd": str(home), "env": clean_environment(home), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = 0x08000000
        try:
            self.starter(args, **options)
        except Exception:
            return self.status(job["workerId"])
        deadline = time.monotonic() + max(0, self.startup_wait)
        while time.monotonic() < deadline:
            out = self.status(job["workerId"])
            if out["workerReachable"]:
                return out
            time.sleep(0.05)
        return self.status(job["workerId"])

    def _existing_plan_job(self, plan_id):
        ShortTitlePlans(self.state, self.client).plan(plan_id)
        root = safe_join(self.state, "short-title-workers")
        jobs = []
        if root.exists():
            if not root.is_dir():
                raise SafetyError("original-worker-layout-required")
            for path in root.iterdir():
                if not path.is_file() or path.suffix != ".json":
                    raise SafetyError("original-worker-layout-required")
                job = original.read_job(self.state, path.stem)
                if job["scope"]["planId"] == plan_id:
                    jobs.append(job)
        if len(jobs) > 1:
            raise SafetyError("single-original-worker-job-required")
        return jobs[0] if jobs else None

    def start(self, plan_id, *, foreground=False):
        if foreground is not True:
            raise SafetyError("foreground-owned-merchant-browser-required")
        # Reads address the existing actor without taking the actor's own locks.
        existing = self._existing_plan_job(plan_id)
        if existing is not None and original.read_runs(self.state, existing):
            return self.status(existing["workerId"])
        with FileLock(self.state / "short-title-worker-owner.lock", timeout=0), FileLock(self.state / "install.lock", timeout=0):
            plan = ShortTitlePlans(self.state, self.client).plan(plan_id)
            root = safe_join(self.state, "short-title-workers")
            candidates = []
            if root.exists():
                for path in root.iterdir():
                    job = original.read_job(self.state, path.stem)
                    if job["scope"]["planId"] == plan_id:
                        candidates.append(job)
            if len(candidates) > 1:
                raise SafetyError("single-original-worker-job-required")
            if candidates and original.read_runs(self.state, candidates[0]):
                return self.status(candidates[0]["workerId"])
            if unresolved(self.state):
                raise SafetyError("original-worker-unresolved-no-new-launch")
            Operations(self.state, self.client)._assert_resolved(plan["scope"]["shop"])
            binding = self.runtime_verifier()
            self.runtime.ensure()
            job = candidates[0] if candidates else original.create_job(self.state, plan_id, self.client, binding)
            if job["scope"]["runtime"] != binding:
                raise SafetyError("original-worker-runtime-changed-no-launch")
            run = original.begin_run(self.state, job)
            _once(original.file(self.state, LAUNCHES, job["workerId"], run["runId"]), claim_record(job, run))
        # Release parent locks before the child owns them. Launch intent was committed.
        return self._spawn(job, run)

    def resume(self, worker_id):
        with FileLock(self.state / "short-title-worker-owner.lock", timeout=0), FileLock(self.state / "install.lock", timeout=0):
            job, active = self._job_run(worker_id)
            if active is not None or unresolved(self.state):
                raise SafetyError("original-worker-run-not-confirmed-closed-no-restart")
            if self.runtime_verifier() != job["scope"]["runtime"]:
                raise SafetyError("original-worker-runtime-changed-no-resume")
            self.runtime.ensure()
            run = original.begin_run(self.state, job, resume=True)
            _once(original.file(self.state, LAUNCHES, job["workerId"], run["runId"]), claim_record(job, run))
        return self._spawn(job, run)

    def command(self, worker_id, action, *, import_id=None, fingerprint=None, confirmed=False, ttl=900, request_id=None):
        job, run = self._job_run(worker_id)
        if run is None:
            raise SafetyError("original-active-worker-required-readonly-resume-first")
        stable = {"workerId": worker_id, "runId": run["runId"], "action": action, "importId": import_id, "fingerprint": fingerprint, "confirmed": confirmed, "ttl": ttl}
        rid = request_id or (digest(stable)[:32] if action in ("approve", "execute", "stop") else uuid.uuid4().hex)
        command = {"requestId": rid, "action": action, "importId": import_id, "fingerprint": fingerprint, "confirmed": confirmed, "ttl": ttl}
        original._check_command(self.state, job, run, command)
        try:
            result = self.request(self.state, job, run, "POST", "/commands", command)
            if not isinstance(result, dict) or result.get("requestId") != rid:
                raise SafetyError("exact-original-command-result-required")
            return {"workerId": worker_id, "runId": run["runId"], **result}
        except Exception:
            return {"workerId": worker_id, "runId": run["runId"], "requestId": rid, "status": "delivery-unknown-read-original-request", "commandStatusAvailable": True}

    def command_status(self, worker_id, request_id):
        job = original.read_job(self.state, worker_id)
        return original.command_status(self.state, job, request_id)
