"""Worker quarantine and exact owning-thread witness, independent of PID/heartbeat."""
from pathlib import Path
import threading
from contextlib import nullcontext
from .safety import SafetyError, safe_join, atomic_json, file_sha
from .state import FileLock
from . import short_title_worker_state as original
from .operations import digest

CLAIMS = "short-title-worker-claims"
ENDPOINTS = "short-title-worker-endpoints"
LAUNCHES = "short-title-worker-launches"
FOLDERS = ("short-title-worker-runs", "short-title-worker-closed", "short-title-worker-close-receipts", "short-title-worker-roots", *original.COMMAND_FOLDERS, CLAIMS, ENDPOINTS, LAUNCHES, "short-title-worker-prefixes", "short-title-worker-prefix-receipts")


def claim_record(job, run):
    return {"workerId": job["workerId"], "runId": run["runId"], "workerFingerprint": job["fingerprint"], "runSha256": digest(run)}


class WorkerWitness:
    def __init__(self, state, job, run, owner_guard, install_guard, verifier):
        self.state = Path(state).absolute()
        self.job, self.run = job, run
        self.owner_guard, self.install_guard, self.verifier = owner_guard, install_guard, verifier
        self.admission_lock=threading.RLock()
        self.native_prefix=None

    def validate(self, state):
        with self.admission_lock:
            return self._validate(state)

    def _validate(self, state, *, cleanup=False):
        if Path(state).absolute() != self.state or not isinstance(self.owner_guard, FileLock) or not isinstance(self.install_guard, FileLock):
            raise SafetyError("exact-owned-worker-witness-required")
        self.owner_guard.require_owned(self.state / "short-title-worker-owner.lock")
        self.install_guard.require_owned(self.state / "install.lock")
        job = original.read_job(self.state, self.job["workerId"])
        runs = original.read_runs(self.state, job)
        if job != self.job or runs.get(self.run["runId"]) != self.run or original.file(self.state, "short-title-worker-closed", job["workerId"], self.run["runId"]).exists():
            raise SafetyError("original-active-worker-witness-required")
        if original._read(original.file(self.state, CLAIMS, job["workerId"], self.run["runId"])) != claim_record(job, self.run):
            raise SafetyError("original-worker-actor-claim-required")
        if not cleanup and self.verifier() != job["scope"]["runtime"]:
            raise SafetyError("original-worker-runtime-changed-no-action")
        self._check_prefix()
        return job["workerId"], self.run["runId"]

    def _prefix_paths(self):
        return [original.file(self.state,folder,self.job["workerId"],self.run["runId"]) for folder in ("short-title-worker-prefixes","short-title-worker-prefix-receipts")]

    def _prefix_record(self, footprints):
        return {"workerId":self.job["workerId"],"runId":self.run["runId"],"claimSha256":digest(claim_record(self.job,self.run)),"footprints":footprints}

    def _check_prefix(self):
        path,receipt=self._prefix_paths();stored=original._read(path);ack=original._read(receipt)
        if self.native_prefix is None:
            if stored is not None or ack is not None:raise SafetyError("original-active-worker-prefix-not-adopted")
            return
        expected=self._prefix_record(self.native_prefix)
        if stored!=expected or ack!={"workerId":self.job["workerId"],"runId":self.run["runId"],"prefixSha256":digest(expected)}:
            raise SafetyError("original-active-worker-prefix-lost-or-changed")
        for relative,sha in self.native_prefix.items():
            path=safe_join(self.state,relative)
            if not path.is_file() or file_sha(path)!=sha:raise SafetyError("original-active-native-prefix-lost-or-changed-no-replay")

    def checkpoint(self):
        return self._checkpoint()

    def checkpoint_for_cleanup(self):
        # Cleanup remains permitted after runtime drift; no new native action.
        return self._checkpoint(cleanup=True)

    def _checkpoint(self, *, cleanup=False):
        with self.admission_lock:
            self._validate(self.state,cleanup=cleanup)
            current=original.native_footprints(self.state,self.job)
            prior=self.native_prefix or {}
            if any(current.get(k)!=v for k,v in prior.items()):raise SafetyError("original-active-native-prefix-lost-or-changed-no-replay")
            if self.native_prefix is not None and current==prior:return
            record=self._prefix_record(current)
            # Never publish a record that our bounded reader cannot read.
            import json
            if len(json.dumps(record).encode("utf-8"))>16*1024*1024:raise SafetyError("bounded-native-prefix-required-no-truncation")
            path,receipt=self._prefix_paths();atomic_json(path,record);atomic_json(receipt,{"workerId":self.job["workerId"],"runId":self.run["runId"],"prefixSha256":digest(record)})
            self.native_prefix=current


def _entries(state, folder):
    root = safe_join(Path(state).absolute(), folder)
    if not root.exists():
        return []
    if not root.is_dir():
        raise SafetyError("unreviewed-worker-state-layout")
    return [safe_join(Path(state).absolute(), folder + "/" + p.name) for p in root.iterdir()]


def unresolved(state, witness=None):
    with witness.admission_lock if isinstance(witness,WorkerWitness) else nullcontext():
        return _unresolved(state,witness)

def _unresolved(state, witness=None):
    owned = witness.validate(state) if isinstance(witness, WorkerWitness) else None
    jobs, active = {}, []
    for p in _entries(state, "short-title-workers"):
        if not p.is_file() or p.suffix != ".json" or original.ID.fullmatch(p.stem) is None:
            raise SafetyError("unreviewed-worker-state-layout")
        job = original.read_job(state, p.stem)
        runs = original.read_runs(state, job)
        jobs[p.stem] = (job, runs)
        launches = original._entries(state, LAUNCHES, job, original.ID)
        if set(launches)-set(runs) or any(value != claim_record(job, runs[rid]) for rid,value in launches.items()):
            raise SafetyError("orphan-worker-launch-intent")
        claims = original._entries(state, CLAIMS, job, original.ID)
        endpoints = original._entries(state, ENDPOINTS, job, original.ID)
        if set(claims) - set(runs) or set(endpoints) - set(claims):
            raise SafetyError("orphan-worker-actor-evidence")
        for rid, claim in claims.items():
            if claim != claim_record(job, runs[rid]):
                raise SafetyError("original-worker-actor-claim-required")
        for rid, ep in endpoints.items():
            if not isinstance(ep, dict) or ep != {"workerId": job["workerId"], "runId": rid, "workerFingerprint": job["fingerprint"], "port": ep.get("port"), "claimSha256": digest(claims[rid])} or type(ep["port"]) is not int or not 1024 <= ep["port"] <= 65535:
                raise SafetyError("original-owned-worker-endpoint-required")
        if any(not original.file(state, "short-title-worker-closed", job["workerId"], rid).exists() and (job["workerId"], rid) != owned for rid in runs):
            active.append(job)
    for folder in FOLDERS:
        for p in _entries(state, folder):
            valid = p.is_file() and p.suffix == ".json" if folder == "short-title-worker-roots" else p.is_dir()
            if not valid or p.stem not in jobs:
                raise SafetyError("orphan-worker-evidence-before-action")
    return active


def assert_resolved(ops, shop):
    # One worker per merchant home. An active other-shop actor also blocks writes:
    # the install witness is home-scoped, not permission to bypass another actor.
    if unresolved(ops.state, getattr(ops, "worker_witness", None)):
        raise SafetyError("original-worker-not-confirmed-closed-before-new-write")


def busy(state):
    return bool(unresolved(state))
