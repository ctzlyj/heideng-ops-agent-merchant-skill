"""Synthetic Windows venv redirector smoke: no SDK, browser, auth, or network.

Run with python -B -m tests.smoke_auth_redirector. The only runtime files are an
unpipped temporary venv and synthetic auth receipts/diagnostics/locks. Production
AuthManager.reconcile is exercised without auth/client/runtime calls. A stdin release plus a
child self-exit watchdog bounds cleanup; no PID killing is used. Retain our own
native handle to the actual worker until assertions finish to prevent PID reuse.
"""
import ctypes
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import venv
from ctypes import wintypes
from pathlib import Path

from heideng_merchant.auth_lifecycle import probe_owned_worker, process_identity, process_state
from heideng_merchant.auth_manager import AuthManager
from heideng_merchant.safety import atomic_json, read_json
from heideng_merchant.state import FileLock


JOB = "a" * 24
CHILD = """
import json, os, sys, threading, time
watchdog = threading.Timer(15, lambda: os._exit(73))
watchdog.daemon = True
watchdog.start()
print(json.dumps({'taskId': 'a' * 24, 'workerPid': os.getpid(), 'parentPid': os.getppid(), 'startedAt': time.time()}), flush=True)
release = sys.stdin.readline()
watchdog.cancel()
raise SystemExit(0 if release.strip() == 'release' else 74)
"""


class ForbiddenAuthCalls:
    def __getattr__(self, name):
        raise AssertionError("auth/client/runtime calls forbidden in redirector smoke")

@unittest.skipUnless(os.name == "nt", "requires the actual Windows venv redirector")
class WindowsRedirectorSmoke(unittest.TestCase):
    def test_actual_venv_redirector_and_worker_exit_without_replay(self):
        with tempfile.TemporaryDirectory(prefix="hd007-redirector-") as directory:
            root = Path(directory)
            venv.EnvBuilder(with_pip=False).create(root / "venv")
            # Only minimal OS variables: do not forward application credentials.
            env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
            env.update(TEMP=directory, TMP=directory, PYTHONUTF8="1")
            process = subprocess.Popen(
                [str(root / "venv" / "Scripts" / "python.exe"), "-I", "-B", "-u", "-c", CHILD],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env=env, cwd=directory,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            launch_started_at = time.time()
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            worker_handle = None
            try:
                messages = queue.Queue()
                reader = threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True)
                reader.start()
                receipt = json.loads(messages.get(timeout=10))
                reader.join(timeout=1)
                self.assertFalse(reader.is_alive())
                self.assertEqual(receipt["taskId"], JOB)
                actual_pid = receipt["workerPid"]
                self.assertNotEqual(process.pid, actual_pid, "a real redirector pair must be observed")
                self.assertEqual(receipt["parentPid"], process.pid)
                worker_handle = kernel.OpenProcess(0x00101000, False, actual_pid)
                self.assertTrue(worker_handle)
                launch = {"taskId": JOB, "workerPid": process.pid, "startedAt": launch_started_at}
                handle = {"taskId": JOB, "workerPid": actual_pid, "startedAt": receipt["startedAt"]}
                legacy = probe_owned_worker(launch, handle, JOB)
                self.assertEqual(legacy.state, "alive")
                self.assertEqual(legacy.worker_pid, actual_pid)
                self.assertEqual(process_state(process.pid), "alive")
                self.assertEqual(process_state(actual_pid), "alive")
                state = root / "state"
                launch_path = state / "auth" / "launches" / (JOB + ".json")
                handle_path = state / "auth" / "handles" / (JOB + ".json")
                task_path = state / "tasks" / (JOB + ".json")
                task = {"kind": "shop-auth", "taskId": JOB, "profile": "merchant-synthetic-a1",
                        "shopName": "synthetic-shop", "venderId": "1", "status": "running",
                        "stage": "created", "ready": False, "createdAt": launch_started_at,
                        "authorizationStarted": False, "authorizationOutcomeUnknown": False}
                atomic_json(launch_path, launch)
                atomic_json(handle_path, handle)
                atomic_json(task_path, task)
                manager = AuthManager(
                    state, client=ForbiddenAuthCalls(), runtime=ForbiddenAuthCalls(),
                    starter=lambda *args, **kwargs: self.fail("auth startup forbidden"),
                    request=lambda *args, **kwargs: None, process_probe=process_state,
                    startup_wait=0,
                )
                caller_alive = manager.reconcile(JOB)
                self.assertEqual(caller_alive["status"], "running")
                self.assertEqual(caller_alive["reconciliation"], "worker-exit-not-proven")
                self.assertFalse(caller_alive["oauthReplayed"])
                self.assertEqual(read_json(task_path), task)
                launch_identity = process_identity(process.pid)
                worker_identity = process_identity(actual_pid)
                self.assertIs(type(launch_identity["creationTime"]), int)
                self.assertIs(type(worker_identity["creationTime"]), int)
                proven_launch = {**launch, "processProof": {
                    "pid": process.pid, "creationTime": launch_identity["creationTime"]}}
                proven_handle = {**handle, "processProof": {
                    "pid": actual_pid, "creationTime": worker_identity["creationTime"],
                    "parentPid": receipt["parentPid"],
                    "parentCreationTime": launch_identity["creationTime"]}}
                self.assertEqual(probe_owned_worker(proven_launch, proven_handle, JOB).state, "alive")
                _, errors = process.communicate(input="release\n", timeout=10)
                self.assertEqual((process.returncode, errors), (0, ""))
                self.assertEqual(process_state(process.pid), "exited")
                self.assertEqual(process_state(actual_pid), "exited")
                # Synthetic analogue of the existing exclusive caller locks.
                with FileLock(root / ("worker-" + JOB + ".lock"), timeout=.1):
                    with FileLock(root / (JOB + ".lock"), timeout=.1):
                        legacy = probe_owned_worker(launch, handle, JOB)
                        proven = probe_owned_worker(proven_launch, proven_handle, JOB)
                        self.assertEqual(legacy.state, "exited")
                        self.assertEqual(legacy.ownership, "legacy-task-bound")
                        self.assertEqual(proven.state, "exited")
                        self.assertEqual(proven.ownership, "recorded-ancestry")
                caller_exited = manager.reconcile(JOB)
                self.assertEqual(caller_exited["status"], "failed")
                self.assertEqual(caller_exited["stage"], "browser_failed")
                self.assertTrue(caller_exited["safeToRestart"])
                self.assertTrue(caller_exited["workerExitVerified"])
                self.assertEqual(caller_exited["workerOwnershipEvidence"], "legacy-task-bound")
                self.assertFalse(caller_exited["workerReachable"])
                self.assertFalse(caller_exited["oauthReplayed"])
                persisted = read_json(task_path)
                self.assertEqual(persisted["status"], "failed")
                self.assertTrue(persisted["safeToRestart"])
                self.assertEqual(persisted["workerExitPreviousStage"], "created")
                self.assertFalse(persisted["authorizationStarted"])
                self.assertFalse(persisted["authorizationOutcomeUnknown"])
                self.assertEqual(read_json(launch_path), launch)
                self.assertEqual(read_json(handle_path), handle)
                # A terminal re-read is idempotent, not an auth start/restart.
                self.assertEqual(manager.reconcile(JOB)["status"], "failed")
                self.assertEqual(read_json(task_path), persisted)
                print(json.dumps({"status": "passed", "launchPid": process.pid,
                                  "workerPid": actual_pid, "parentPid": receipt["parentPid"],
                                  "whileAlive": "alive", "afterExit": "exited",
                                  "legacyOwnership": legacy.ownership,
                                  "newOwnership": proven.ownership, "exitCode": process.returncode,
                                  "callerWhileAlive": caller_alive["status"],
                                  "callerAfterExit": caller_exited["status"],
                                  "safeToRestart": caller_exited["safeToRestart"],
                                  "oauthReplayed": caller_exited["oauthReplayed"]}))
            finally:
                if process.poll() is None:
                    # EOF is cooperative shutdown; the worker's own watchdog is the bound.
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                    process.wait(timeout=20)
                if worker_handle:
                    kernel.CloseHandle(worker_handle)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream and not stream.closed:
                        stream.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
