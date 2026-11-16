"""Persistent owning-thread native title coordinator. Starting never grants writes."""
import threading
import time
from pathlib import Path
from .official import OfficialClient
from .safety import SafetyError
from .state import FileLock
from .video_delivery import _once
from .operations import digest
from .short_title_browser import ShortTitleSourceBrowser
from .short_title_import_browser import ShortTitleImportBrowser
from .short_title_imports import ShortTitleImports
from .short_title_worker_broker import CommandBroker, make_server
from .short_title_worker_gate import WorkerWitness, claim_record, unresolved, CLAIMS, ENDPOINTS
from . import short_title_worker_state as original


class ShortTitleWorker:
    def __init__(self, state, worker_id, run_id, *, client=None, source_factory=None, import_factory=None, runtime_verifier=None, clock=None, headless=False):
        self.state = Path(state).absolute()
        self.job = original.read_job(self.state, worker_id)
        self.run_record = original.read_runs(self.state, self.job).get(original._id(run_id))
        if self.run_record is None:
            raise SafetyError("original-worker-run-required")
        self.client = client if client is not None else OfficialClient(self.state)
        self.source_factory, self.import_factory = source_factory, import_factory
        self.runtime_verifier = runtime_verifier or original.runtime_binding
        self.clock = clock or time.time
        self.headless = headless
        self.owner_guard = FileLock(self.state / "short-title-worker-owner.lock", timeout=0)
        self.install_guard = FileLock(self.state / "install.lock", timeout=0)
        self.browser = self.broker = self.server = self.server_thread = self.manager = self.witness = None
        self.claimed = self.closed = False

    def _validate_action(self):
        with self.witness.admission_lock:
            self.witness.validate(self.state)
            if unresolved(self.state, self.witness):
                raise SafetyError("another-original-worker-unresolved-no-action")
            original.read_link(self.state, self.job, self.client)

    def _claim(self):
        if original.file(self.state, "short-title-worker-closed", self.job["workerId"], self.run_record["runId"]).exists():
            raise SafetyError("original-worker-run-already-closed-no-launch")
        if original.read_runs(self.state, self.job).get(self.run_record["runId"]) != self.run_record:
            raise SafetyError("original-worker-run-changed-no-launch")
        if self.runtime_verifier() != self.job["scope"]["runtime"]:
            raise SafetyError("original-worker-runtime-changed-no-launch")
        _once(original.file(self.state, CLAIMS, self.job["workerId"], self.run_record["runId"]), claim_record(self.job, self.run_record))
        self.claimed = True
        self.witness = WorkerWitness(self.state, self.job, self.run_record, self.owner_guard, self.install_guard, lambda: self.runtime_verifier())
        self._validate_action()
        self.witness.checkpoint()

    def _start_broker(self):
        self.broker = CommandBroker(self.state, self.job, self.run_record)
        self.witness.admission_lock=self.broker.lock
        self.server = make_server(self.broker)
        self.server_thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.server_thread.start()
        ep = {"workerId": self.job["workerId"], "runId": self.run_record["runId"], "workerFingerprint": self.job["fingerprint"], "port": self.server.server_port, "claimSha256": digest(claim_record(self.job, self.run_record))}
        _once(original.file(self.state, ENDPOINTS, self.job["workerId"], self.run_record["runId"]), ep)

    def _wait_login(self):
        self.broker.update({}, stage="awaiting-login", ready=False)
        while not self.broker.stop_requested.is_set():
            self._validate_action()
            value = self.browser.authentication_status()
            if value["status"] == "identity-mismatch":
                raise SafetyError("owned-login-shop-identity-mismatch")
            if value["currentIdentityVerified"]:
                return True
            self.browser.poll()
        return False

    def _prepare(self):
        link = original.read_link(self.state, self.job, self.client)
        if not self.run_record["resumeReadOnly"]:
            if link is not None:
                raise SafetyError("original-root-requires-confirmed-readonly-resume")
            self.browser = ShortTitleSourceBrowser(self.state, self.client, self.job["scope"]["planId"], session_id=self.job["scope"]["sourceId"], factory=self.source_factory, clock=self.clock, headless=self.headless)
            self.browser.open(install_guard=self.install_guard)
            if not self._wait_login():
                return
            self._validate_action()
            self.browser.capture()
            self.browser.close()
            self.browser = None
            self._validate_action()
            root = self.manager.prepare(self.job["scope"]["planId"], self.job["scope"]["sourceId"])
            link = original.link_root(self.state, self.job, root["importId"], self.client)
            self.witness.checkpoint()
        if link is not None and not self.broker.stop_requested.is_set():
            self._validate_action()
            self.browser = ShortTitleImportBrowser(self.manager, link["importId"], factory=self.import_factory, headless=self.headless)
            self.browser.open(install_guard=self.install_guard)
            if not self._wait_login():
                return
            self.broker.update(self.manager.status(link["importId"]), stage="readonly-resumed" if self.run_record["resumeReadOnly"] else "awaiting-exact-approval", ready=True)
        else:
            self.broker.update({}, stage="readonly-no-original-root", ready=True)

    def _handle(self, accepted):
        action = accepted["command"]["action"]
        if action != "stop":
            self._validate_action()
        with self.broker.lock:
            dispatch = original.dispatch_command(self.state, self.job, self.run_record, accepted)
        command = accepted["command"]
        if action == "stop":
            self.broker.stop_requested.set()
            result = {"status": "local-stop-requested", "imported": False}
        elif self.broker.stop_requested.is_set():
            result = {"status": "stopped-before-native-action", "imported": False}
        else:
            try:
                ident = command["importId"]
                if action == "approve":
                    result = self.manager.approve(ident, command["fingerprint"], confirmed=command["confirmed"], ttl=command["ttl"])
                elif action == "execute":
                    result = self.manager.execute(ident, self.browser, stop_requested=self.broker.stop_requested.is_set)
                    # Reads remain explicit commands. C2/C3 failure never creates a replacement write.
                elif action == "recover":
                    result = self.manager.recover(ident, self.browser)
                elif action == "results":
                    result = self.manager.collect_results(ident, self.browser)
                elif action == "effects":
                    result = self.manager.collect_effects(ident, self.browser)
                elif action == "repair-plan":
                    self.manager.repair_stop_requested=self.broker.stop_requested.is_set
                    result = self.manager.prepare_repair(ident,self.browser,command["changes"])
                elif action == "repair-approve":
                    self.manager.repair_stop_requested=self.broker.stop_requested.is_set
                    result = self.manager.approve_repair(ident,command["repairPlanId"],command["repairFingerprint"],self.browser,confirmed=command["confirmed"],ttl=command["ttl"],approval_id=command["requestId"])
                else:
                    raise SafetyError("exact-native-worker-action-required")
                if "stoppedReason" in result:
                    result = {**result, "reason": result["stoppedReason"]}
            except Exception:
                # Never expose a raw native body; dispatch remains an original one-shot.
                result = {"status": "native-command-unverified", "reason": "inspect-original-native-and-command-evidence", "imported": False}
        self.witness.checkpoint()
        with self.broker.lock:
            original.write_result(self.state, self.job, self.run_record, accepted, dispatch, result)
        self.broker.update(result, stage="waiting-for-command", ready=not self.broker.stop_requested.is_set())

    def close(self):
        if self.closed:
            return
        if self.broker is not None:
            self.broker.freeze()
        if self.server is not None:
            if self.server_thread is not None and self.server_thread.is_alive():
                self.server.shutdown()
                self.server_thread.join(timeout=5)
                if self.server_thread.is_alive():
                    raise SafetyError("owned-worker-broker-cleanup-unknown")
            self.server.server_close()
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.claimed:
            self.owner_guard.require_owned(self.state / "short-title-worker-owner.lock")
            self.install_guard.require_owned(self.state / "install.lock")
            self.witness.checkpoint_for_cleanup()
            original.finish_run(self.state, self.job, self.run_record, broker_stopped=True, browser_closed=True, guard_owned=True)
        if self.install_guard.acquired:
            self.install_guard.__exit__(None, None, None)
        if self.owner_guard.acquired:
            self.owner_guard.__exit__(None, None, None)
        self.closed = True

    def run(self):
        if self.claimed or self.closed:
            raise SafetyError("original-worker-actor-cannot-relaunch")
        try:
            self.owner_guard.__enter__()
            self.install_guard.__enter__()
            self._claim()
            self.manager = ShortTitleImports(self.state, self.client, clock=self.clock)
            self.manager.plans.ops.worker_witness = self.witness
            self._start_broker()
            self._prepare()
            while not self.broker.stop_requested.is_set():
                self._validate_action()
                accepted = self.broker.take()
                if accepted is not None:
                    self._handle(accepted)
                elif self.browser is not None:
                    self.browser.poll()
                else:
                    time.sleep(0.05)
            # Freeze before draining: accepted commands are accounted for, not replayed.
            self.broker.freeze()
            while (accepted := self.broker.take()) is not None:
                self._handle(accepted)
        except Exception:
            try:
                self.close()
            except Exception:
                # Keep actual guards until actual cleanup; durable run stays quarantined.
                raise SafetyError("owned-worker-cleanup-unknown-no-restart") from None
            raise SafetyError("original-worker-stopped-inspect-existing-evidence-no-restart") from None
        self.close()
        return {"workerId": self.job["workerId"], "runId": self.run_record["runId"], "status": "closed", "localResourcesClosed": True, "nativeImportVerified": False}
