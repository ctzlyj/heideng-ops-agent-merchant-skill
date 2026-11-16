"""Agent-facing single-launch authentication; unknown delivery never starts another login."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from . import VERSION
from .auth_broker import public_status, OBSERVATION_FIELDS
from .auth_lifecycle import process_state, record_event
from .auth_runtime import BrowserRuntime
from .official import OfficialClient
from .operations import Operations
from .safety import SafetyError, atomic_json, clean_environment, read_json, redact, safe_join
from .state import FileLock


def broker_request(port, path, task_id=None, payload=None):
    if not isinstance(task_id, str) or not re.fullmatch("[a-f0-9]{24}", task_id):
        return None
    if not isinstance(port, int) or not 1024 <= port <= 65535 or path not in {"/status", "/observe", "/cancel", "/confirm-shop"}:
        return None
    method = "POST" if path in {"/cancel","/confirm-shop"} else "GET"
    body=json.dumps(payload,ensure_ascii=False).encode() if path=="/confirm-shop" else b"" if method=="POST" else None
    request = urllib.request.Request("http://127.0.0.1:" + str(port) + path,
                                     data=body, method=method,
                                     headers={"X-Heideng-Local": "1", "X-Heideng-Task": task_id, **({"Content-Type":"application/json"} if path=="/confirm-shop" else {})})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
            raw = response.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def validate_target(shop_name, vender_id=None):
    if not isinstance(shop_name, str) or not shop_name.strip() or len(shop_name) > 128 or any(ord(c) < 32 for c in shop_name):
        raise SafetyError("explicit-shop-name-required")
    if redact(shop_name) != shop_name:
        raise SafetyError("credentials-not-allowed-in-shop-name")
    if vender_id is not None and not re.fullmatch("[1-9][0-9]{0,19}", str(vender_id)):
        raise SafetyError("actual-vender-id-required")
    return shop_name.strip(), str(vender_id) if vender_id is not None else None


class AuthManager:
    def __init__(self, state, *, client=None, runtime=None, starter=None, request=None, startup_wait=10, process_probe=None, sleep=None):
        self.state = Path(state).resolve()
        self.client = client or OfficialClient(self.state)
        self.runtime = runtime or BrowserRuntime(self.state)
        self.starter = starter or subprocess.Popen
        self.request = request or broker_request
        self.startup_wait = startup_wait
        self.process_probe = process_probe or process_state
        self.sleep = sleep or time.sleep

    def _path(self, job):
        if not isinstance(job, str) or not re.fullmatch("[a-f0-9]{24}", job):
            raise SafetyError("invalid-auth-job-id")
        return safe_join(self.state, "tasks/" + job + ".json")

    def _record(self, job):
        data = read_json(self._path(job))
        if not isinstance(data, dict) or data.get("kind") != "shop-auth" or data.get("taskId") != job:
            raise SafetyError("auth-task-not-found")
        return data

    def _handle(self, job):
        self._record(job)
        return read_json(safe_join(self.state, "auth/handles/" + job + ".json"), {})

    def status(self, job):
        data = self._record(job)
        handle = self._handle(job)
        reply = self.request(handle.get("port"), "/status", job) if not handle.get("brokerStopped") else None
        if reply and reply.get("taskId") == job:
            return {**public_status(reply), "workerReachable": True}
        result = public_status(data)
        if result.get("status") == "running":
            result["ready"] = False
        return {**result, "workerReachable": False}

    def observe(self, job):
        handle = self._handle(job)
        reply = self.request(handle.get("port"), "/observe", job) if not handle.get("brokerStopped") else None
        if reply and reply.get("taskId") == job:
            return {**public_status(reply), "observation": {k: v for k, v in reply.get("observation", {}).items() if k in OBSERVATION_FIELDS}, "workerReachable": True}
        return self.status(job)

    def confirm_shop(self,job,shop_name,vender_id,fingerprint,*,confirmed=False):
        self._record(job)
        shop_name,vender_id=validate_target(shop_name,vender_id)
        if not confirmed or vender_id is None or not isinstance(fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',fingerprint):
            raise SafetyError('explicit-observed-shop-confirmation-required')
        handle=self._handle(job)
        payload={'shopName':shop_name,'venderId':vender_id,'fingerprint':fingerprint}
        reply=self.request(handle.get('port'),'/confirm-shop',job,payload) if not handle.get('brokerStopped') else None
        accepted=bool(reply and reply.get('taskId')==job and reply.get('confirmationRequested') is True)
        return {**self.status(job),'confirmationRequested':accepted,'oauthReplayed':False}

    def start(self, shop_name, *, vender_id=None, foreground=False, wait=False, wait_timeout=960, progress=None, _retry_job=None):
        if wait and (type(wait_timeout) not in (int, float) or not 0 <= wait_timeout <= 1800):
            raise SafetyError('auth-wait-timeout-must-be-0-to-1800-seconds')
        result = self._start(shop_name, vender_id=vender_id, foreground=foreground, _retry_job=_retry_job)
        # Do not keep start/install locks while a merchant is logging in.
        return self.wait(result['taskId'], timeout=wait_timeout, progress=progress) if wait else result

    def _start(self, shop_name, *, vender_id=None, foreground=False, _retry_job=None):
        shop_name, vender_id = validate_target(shop_name, vender_id)
        if not foreground:
            raise SafetyError("foreground-merchant-login-required-no-background-auth")
        capability = getattr(self.client, 'shop_capability', None)
        if capability is not None:
            admission = capability()
            if not admission.get('authAvailable'):
                raise SafetyError(admission.get('reason') or 'official-auth-platform-not-admitted')
        slot = hashlib.sha256(json.dumps([shop_name, vender_id], ensure_ascii=False).encode()).hexdigest()[:24]
        with FileLock(self.state / "auth" / "start.lock"):
            index_path = safe_join(self.state, "auth/targets.json")
            index = read_json(index_path, {})
            if slot in index:
                prior = self._record(index[slot])
                if _retry_job is None or prior.get("restartOf") == _retry_job:
                    return self.status(index[slot])
                if prior["taskId"] != _retry_job or prior.get("status") not in {"failed", "cancelled"} or prior.get("authorizationStarted") or prior.get("authorizationOutcomeUnknown"):
                    raise SafetyError("original-auth-not-confirmed-safe-to-restart")
                del index[slot]
            for other_job in index.values():
                prior = self._record(other_job)
                same_target = (shop_name in {prior.get('shopName'),prior.get('requestedShopName')}
                               or (vender_id is not None and vender_id in {prior.get('venderId'),prior.get('requestedVenderId')}))
                if same_target and prior.get("status") in {"running", "unknown"}:
                    raise SafetyError("active-auth-target-conflict-observe-original-task")
            self.runtime.ensure()
            if not self.client.ready():
                self.client.install()
            job = uuid.uuid4().hex[:24]
            profile = "merchant-" + job
            data = {"kind": "shop-auth", "taskId": job, "profile": profile, "shopName": shop_name, "requestedShopName": shop_name, "requestedVenderId": vender_id or "",
                    "venderId": vender_id or "", "status": "running", "stage": "starting_worker",
                    "ready": False, "runtimeVersion": VERSION, "createdAt": time.time()}
            if _retry_job is not None:
                data["restartOf"] = _retry_job
            with FileLock(self.state / "install.lock"):
                atomic_json(self._path(job), data)
                index[slot] = job
                atomic_json(index_path, index)
            home = safe_join(self.state, "auth/homes/" + job)
            home.mkdir(parents=True, exist_ok=True)
            script = Path(__file__).resolve().parents[1] / "scripts" / "auth_worker.py"
            args = [str(self.runtime.python()), "-I", str(script), "--state", str(self.state), "--job", job]
            options = {"cwd": str(home), "env": clean_environment(home), "stdin": subprocess.DEVNULL,
                       "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                options["creationflags"] = 0x08000000
            try:
                process = self.starter(args, **options)
                atomic_json(safe_join(self.state, "auth/launches/" + job + ".json"),
                            {"taskId": job, "workerPid": process.pid, "startedAt": time.time()})
            except Exception:
                data.update(status="unknown", stage="auth_outcome_unknown", reason="worker-launch-outcome-unknown-no-replay")
                atomic_json(self._path(job), data)
            deadline = time.monotonic() + self.startup_wait
            while time.monotonic() < deadline:
                if self._handle(job).get("port") or self._record(job).get("status") != "running":
                    break
                time.sleep(.1)
            return self.status(job)

    def reconcile(self, job):
        data = self._record(job)
        status = self.status(job)
        if data.get('status') != 'running' or status.get('workerReachable'):
            return {**status, 'oauthReplayed': False}
        launch_path = safe_join(self.state, 'auth/launches/' + job + '.json')
        launch = read_json(launch_path, {})
        handle = self._handle(job)
        pid = launch.get('workerPid')
        def exited():
            try: return self.process_probe(pid) == 'exited'
            except Exception: return False
        def exact_owner():
            current_launch = read_json(launch_path, {})
            current_handle = self._handle(job)
            return (current_launch == launch and launch.get('taskId') == job and type(pid) == int and 0 < pid <= 0xffffffff
                    and (not current_handle or (current_handle.get('taskId') == job and current_handle.get('workerPid') == pid)))
        if not exact_owner() or not exited():
            return {**status, 'reconciliation': 'worker-exit-not-proven', 'oauthReplayed': False}
        try:
            with FileLock(safe_join(self.state, 'auth/worker-' + job + '.lock'), timeout=.1):
                with FileLock(safe_join(self.state, 'auth/' + job + '.lock'), timeout=.1):
                    current = self._record(job)
                    # Recheck both PID and receipt after taking the worker's full-lifetime lock.
                    if current != data or not exact_owner() or not exited():
                        return {**self.status(job), 'reconciliation': 'owner-or-receipt-changed', 'oauthReplayed': False}
                    before_oauth = (current.get('stage') in {'starting_worker','initializing_worker','created','waiting_login','waiting_shop_confirmation'}
                                    and not current.get('authorizationStarted') and not current.get('authorizationOutcomeUnknown')
                                    and not current.get('cleanupIncomplete'))
                    current.update(status='failed' if before_oauth else 'unknown', ready=False,
                                   stage='browser_failed' if before_oauth else 'auth_outcome_unknown',
                                   reason='worker-exited-before-oauth-safe-to-restart' if before_oauth else 'worker-exited-auth-outcome-unknown-no-replay',
                                   workerExitVerified=True, safeToRestart=before_oauth, updatedAt=time.time())
                    if not before_oauth: current['authorizationOutcomeUnknown'] = True
                    current['workerExitPreviousStage'] = data.get('stage')
                    atomic_json(self._path(job), current)
                    record_event(self.state, job, 'worker-reconciled', current)
                    return {**public_status(current), 'workerReachable': False, 'oauthReplayed': False}
        except SafetyError as error:
            if str(error) != 'resource-busy': raise
            return {**self.status(job), 'reconciliation': 'original-worker-or-task-lock-busy', 'oauthReplayed': False}

    def wait(self, job, *, timeout=960, progress=None):
        self._record(job)
        if type(timeout) not in (int, float) or not 0 <= timeout <= 1800:
            raise SafetyError('auth-wait-timeout-must-be-0-to-1800-seconds')
        deadline = time.monotonic() + timeout
        previous = None
        try:
            while True:
                result = self.status(job)
                if result.get('status') == 'running' and not result.get('workerReachable'):
                    result = self.reconcile(job)
                marker = (result.get('stage'), result.get('status'), result.get('workerReachable'), result.get('identityDiagnostic'), result.get('confirmationRejected'), result.get('reason'), json.dumps(result.get('identityCandidates',[]),sort_keys=True))
                if progress and marker != previous: progress({**result, 'event': 'auth-progress'})
                previous = marker
                if result.get('status') != 'running': return result
                if time.monotonic() >= deadline:
                    return {**result, 'waitTimedOut': True, 'oauthReplayed': False}
                self.sleep(.5)
        except KeyboardInterrupt:
            return {**self.status(job), 'waitInterrupted': True, 'oauthReplayed': False}

    def cancel(self, job):
        handle = self._handle(job)
        if self._record(job).get("status") != "running":
            return self.status(job)
        reply = self.request(handle.get("port"), "/cancel", job) if not handle.get("brokerStopped") else None
        return {**self.status(job), "cancelRequested": bool(reply and reply.get("taskId") == job and reply.get("cancelRequested")),
                "note": "only-owned-worker-may-stop-auth-no-pid-kill"}

    def restart(self, job, *, foreground=False, wait=False, wait_timeout=960, progress=None):
        original = self._record(job)
        if original.get("status") not in {"failed", "cancelled"} or original.get("authorizationStarted") or original.get("authorizationOutcomeUnknown"):
            raise SafetyError("original-auth-not-confirmed-safe-to-restart")
        return self.start(original["shopName"], vender_id=original.get("venderId") or None,
                          foreground=foreground, wait=wait, wait_timeout=wait_timeout, progress=progress, _retry_job=job)

    def recover(self, job):
        self._record(job)
        with FileLock(safe_join(self.state, "auth/" + job + ".lock")):
            data = self._record(job)
            if data.get("status") == "running":
                raise SafetyError("auth-worker-outcome-unresolved-query-status-first")
            if not data.get("venderId"):
                raise SafetyError("auth-target-identity-not-observed")
            identity = Operations(self.state, self.client).connect(data["profile"], data["shopName"], data["venderId"])
            data.update(targetStateVerified=True, updatedAt=time.time())
            # Realtime access proves the profile's current shop, not the original login receipt.
            atomic_json(self._path(job), data)
            return {**public_status(data), "recoveredShopIdentity": {k: identity[k] for k in
                    ("profile", "shopName", "shopId", "venderId", "shopType")}, "oauthReplayed": False}

    def ensure_shop(self, shop_name, *, vender_id=None, foreground=False, wait=False, wait_timeout=960, progress=None):
        shop_name, vender_id = validate_target(shop_name, vender_id)
        shops = read_json(self.state / "shops.json", {})
        matches = [(profile, shop) for profile, shop in shops.items() if shop.get("shopName") == shop_name and
                   (vender_id is None or shop.get("venderId") == vender_id)]
        if not matches:
            index=read_json(self.state/'auth/targets.json',{})
            for job in set(index.values()):
                record=self._record(job)
                if record.get('status')!='completed' or record.get('ready') is not True or record.get('identityConfirmed') is not True or record.get('requestedShopName')!=shop_name:continue
                profile=record.get('profile');shop=shops.get(profile)
                if shop and shop.get('shopName')==record.get('shopName') and shop.get('venderId')==record.get('venderId') and (vender_id is None or vender_id==shop.get('venderId')):
                    matches.append((profile,shop))
            matches=list({profile:(profile,shop) for profile,shop in matches}.values())
        if len(matches) > 1:
            raise SafetyError("multiple-authorized-shop-profiles-select-exact-target")
        if matches:
            profile, shop = matches[0]
            actual = Operations(self.state, self.client).connect(profile, shop["shopName"], shop["venderId"])
            return {"ready": True, "status": "connected", "source": "realtime-official-identity", **actual}
        return self.start(shop_name, vender_id=vender_id, foreground=foreground, wait=wait, wait_timeout=wait_timeout, progress=progress)
