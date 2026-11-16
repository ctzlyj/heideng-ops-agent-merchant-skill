"""Offline ownership tests; the guarded caller below is not OAuth integration."""
import copy
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from heideng_merchant import auth_lifecycle as lifecycle
from heideng_merchant.safety import SafetyError, atomic_json, read_json
from heideng_merchant.state import FileLock


JOB = "a" * 24


def receipts(launch_pid=3632, worker_pid=19688):
    return ({"taskId": JOB, "workerPid": launch_pid, "startedAt": 1.0},
            {"taskId": JOB, "workerPid": worker_pid, "startedAt": 2.0})


def proven_receipts():
    launch, handle = receipts()
    launch["processProof"] = {"pid": 3632, "creationTime": 100}
    handle["processProof"] = {"pid": 19688, "creationTime": 200,
                              "parentPid": 3632, "parentCreationTime": 100}
    return launch, handle


class ProbeMixin:
    def probe(self, launch, handle, probe=lambda pid: "exited", job=JOB):
        helper = getattr(lifecycle, "probe_owned_worker", None)
        self.assertTrue(callable(helper), "task-bound multi-PID exit helper is missing")
        return helper(launch, handle, job, probe)


class RedirectorTests(ProbeMixin, unittest.TestCase):
    def test_legacy_redirector_and_actual_worker_both_exited(self):
        launch, handle = receipts()
        before = copy.deepcopy((launch, handle))
        calls = []
        result = self.probe(launch, handle, lambda pid: calls.append(pid) or "exited")
        self.assertEqual(result.state, "exited")
        self.assertEqual(result.worker_pid, 19688)
        self.assertEqual(result.pids, (3632, 19688))
        self.assertEqual(result.ownership, "legacy-task-bound")
        self.assertEqual(calls, [3632, 19688])
        self.assertEqual((launch, handle), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.state = "alive"

    def test_distinct_legacy_requires_both_started_at_before_os_probe(self):
        for side in (0, 1):
            for value in (None, True, False, 0, -1, "1", [], {},
                          float("nan"), float("inf"), float("-inf"), 2**2048):
                with self.subTest(side=side, value=value):
                    pair = list(receipts())
                    pair[side]["startedAt"] = value
                    probe = Mock(return_value="exited")
                    self.assertEqual(self.probe(*pair, probe=probe).state, "unknown")
                    probe.assert_not_called()
            pair = list(receipts())
            del pair[side]["startedAt"]
            probe = Mock(return_value="exited")
            self.assertEqual(self.probe(*pair, probe=probe).state, "unknown")
            probe.assert_not_called()

    def test_distinct_legacy_requires_absolute_30_second_start_window(self):
        for launch_time, handle_time, expected in ((1, 31, "exited"), (31, 1, "exited"),
                                                   (1.0, 31.001, "unknown"),
                                                   (31.001, 1.0, "unknown")):
            with self.subTest(launch=launch_time, handle=handle_time):
                launch, handle = receipts()
                launch["startedAt"], handle["startedAt"] = launch_time, handle_time
                probe = Mock(return_value="exited")
                self.assertEqual(self.probe(launch, handle, probe=probe).state, expected)
                self.assertEqual(probe.call_count, 2 if expected == "exited" else 0)

    def test_same_pid_and_empty_handle_do_not_require_legacy_timestamps(self):
        launch, handle = receipts(3632, 3632)
        del launch["startedAt"]
        del handle["startedAt"]
        self.assertEqual(self.probe(launch, handle).state, "exited")
        self.assertEqual(self.probe(launch, {}).state, "exited")

    def test_native_ancestry_proof_is_not_legacy_started_at(self):
        launch, handle = proven_receipts()
        del launch["startedAt"]
        del handle["startedAt"]
        result = self.probe(launch, handle)
        self.assertEqual(result.state, "exited")
        self.assertEqual(result.ownership, "recorded-ancestry")

    def test_same_pid_is_probed_once(self):
        calls = []
        result = self.probe(*receipts(3632, 3632),
                            probe=lambda pid: calls.append(pid) or "exited")
        self.assertEqual(result.state, "exited")
        self.assertEqual(result.pids, (3632,))
        self.assertEqual(result.worker_pid, 3632)
        self.assertEqual(calls, [3632])

    def test_launch_only_preserves_pre_handle_startup(self):
        launch, _ = receipts()
        result = self.probe(launch, {})
        self.assertEqual((result.state, result.worker_pid, result.pids, result.ownership),
                         ("exited", 3632, (3632,), "launch-only"))

    def test_either_alive_unknown_or_reused_refuses_and_checks_both(self):
        for blocked_pid in (3632, 19688):
            for state in ("alive", "unknown", "pid-reused", None, True, {}, []):
                with self.subTest(pid=blocked_pid, state=state):
                    calls = []
                    def probe(pid):
                        calls.append(pid)
                        return state if pid == blocked_pid else "exited"
                    result = self.probe(*receipts(), probe=probe)
                    self.assertNotEqual(result.state, "exited")
                    self.assertEqual(calls, [3632, 19688])

    def test_probe_exception_is_unknown_without_short_circuit(self):
        for failed_pid in (3632, 19688):
            calls = []
            def probe(pid):
                calls.append(pid)
                if pid == failed_pid:
                    raise OSError("synthetic inaccessible process")
                return "exited"
            self.assertEqual(self.probe(*receipts(), probe=probe).state, "unknown")
            self.assertEqual(calls, [3632, 19688])

    def test_wrong_task_or_malformed_records_refuse_before_os_probe(self):
        for side in (0, 1):
            for field, values in (("taskId", ("b" * 24, None, True, "../unsafe")),
                                  ("workerPid", (None, True, False, 0, -1, 2**32,
                                                 "3632", 3632.0, [], {}))):
                for value in values:
                    with self.subTest(side=side, field=field, value=value):
                        launch, handle = receipts()
                        (launch, handle)[side][field] = value
                        with patch.object(lifecycle, "process_state") as probe:
                            self.assertEqual(self.probe(launch, handle, probe).state, "unknown")
                            probe.assert_not_called()
        for launch, handle in (({}, {}), (None, {}), ([], {}), (receipts()[0], None),
                               (receipts()[0], []), (receipts()[0], {"workerPid": 19688})):
            self.assertEqual(self.probe(launch, handle).state, "unknown")
        for job in (None, True, "", "../unsafe", "A" * 24, "a" * 23):
            self.assertEqual(self.probe(*receipts(), job=job).state, "unknown")

    def test_recorded_ancestry_is_distinct_from_legacy(self):
        result = self.probe(*proven_receipts())
        self.assertEqual(result.state, "exited")
        self.assertEqual(result.ownership, "recorded-ancestry")

    def test_partial_invalid_or_unrelated_proof_never_downgrades_to_legacy(self):
        cases = []
        for side in (0, 1):
            for value in (None, {}, True, "legacy", [], {"pid": 3632},
                          {"pid": 3632, "creationTime": 100, "extra": "invented"}):
                pair = list(proven_receipts())
                pair[side]["processProof"] = value
                cases.append(pair)
            pair = list(proven_receipts())
            del pair[side]["processProof"]
            cases.append(pair)
        for field in ("pid", "creationTime", "parentPid", "parentCreationTime"):
            for value in (None, True, 0, -1, "100", 100.0, float("nan"),
                          float("inf"), 2**64):
                pair = list(proven_receipts())
                pair[1]["processProof"][field] = value
                cases.append(pair)
        for field, value in (("pid", 3632), ("parentPid", 777),
                             ("parentCreationTime", 99), ("creationTime", 99)):
            pair = list(proven_receipts())
            pair[1]["processProof"][field] = value
            cases.append(pair)
        for pair in cases:
            with self.subTest(pair=pair):
                self.assertEqual(self.probe(*pair).state, "unknown")

    def test_same_pid_creation_times_must_agree(self):
        launch, handle = receipts(3632, 3632)
        launch["processProof"] = {"pid": 3632, "creationTime": 100}
        handle["processProof"] = {"pid": 3632, "creationTime": 100}
        self.assertEqual(self.probe(launch, handle).state, "exited")
        handle["processProof"]["creationTime"] = 101
        self.assertEqual(self.probe(launch, handle).state, "unknown")

    def test_reused_pid_creation_time_refuses_even_if_probe_says_exited(self):
        for reused_pid in (3632, 19688):
            def probe(pid):
                return {"state": "exited", "pid": pid,
                        "creationTime": 999 if pid == reused_pid else (100 if pid == 3632 else 200)}
            self.assertEqual(self.probe(*proven_receipts(), probe=probe).state, "unknown")

    def test_existing_default_process_state_is_upgraded_to_identity_probe(self):
        def observation(pid):
            return {"pid": pid, "state": "exited", "creationTime": 999}
        with patch.object(lifecycle, "process_state", return_value="exited") as old_probe:
            with patch.object(lifecycle, "process_identity", side_effect=observation) as native:
                self.assertEqual(self.probe(*proven_receipts(), probe=old_probe).state, "unknown")
                old_probe.assert_not_called()
                self.assertEqual([call.args[0] for call in native.call_args_list], [3632, 19688])
    def test_rich_probe_missing_process_and_matching_identity(self):
        for creation_times in ((None, None), (100, 200)):
            def probe(pid):
                return {"state": "exited", "pid": pid,
                        "creationTime": creation_times[pid == 19688]}
            self.assertEqual(self.probe(*proven_receipts(), probe=probe).state, "exited")
        for bad in ({"state": "exited", "pid": 777},
                    {"state": "exited", "creationTime": True},
                    {"state": "exited", "creationTime": "100"}):
            self.assertEqual(self.probe(*receipts(), probe=lambda pid: bad).state, "unknown")

    def test_helper_does_not_decide_oauth_replay_or_mutate_task_receipt(self):
        for flags in ({"stage": "created"},
                      {"stage": "waiting_oauth", "authorizationStarted": True},
                      {"stage": "waiting_login", "authorizationOutcomeUnknown": True}):
            task = {"taskId": JOB, "status": "running", **flags}
            before = copy.deepcopy(task)
            result = self.probe(*receipts())
            self.assertEqual(result.state, "exited")
            self.assertFalse(hasattr(result, "safeToRestart"))
            self.assertFalse(hasattr(result, "oauthReplayed"))
            self.assertEqual(task, before)
            # Existing caller policy, NOT the liveness helper, retains this boundary.
            before_oauth = (task["stage"] == "created"
                            and not task.get("authorizationStarted")
                            and not task.get("authorizationOutcomeUnknown"))
            self.assertEqual(before_oauth, flags == {"stage": "created"})


class CallerGuardTests(ProbeMixin, unittest.TestCase):
    """Demonstrate the mandatory immutable re-read + dual-lock caller contract."""

    def guarded(self, root, probe, before_lock=lambda: None):
        paths = [root / name for name in ("launch.json", "handle.json", "task.json")]
        initial = tuple(read_json(path) for path in paths)
        result = self.probe(*initial[:2], probe=probe)
        if result.state != "exited":
            return False
        before_lock()
        try:
            with FileLock(root / ("worker-" + JOB + ".lock"), timeout=.01):
                with FileLock(root / (JOB + ".lock"), timeout=.01):
                    current = tuple(read_json(path) for path in paths)
                    return (current == initial
                            and self.probe(*current[:2], probe=probe).state == "exited")
        except SafetyError as error:
            if str(error) != "resource-busy":
                raise
            return False

    def setup_receipts(self, root):
        launch, handle = receipts()
        for name, data in (("launch.json", launch), ("handle.json", handle),
                           ("task.json", {"taskId": JOB, "stage": "created"})):
            atomic_json(root / name, data)

    def test_legacy_recovery_requires_both_exclusive_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_receipts(root)
            self.assertTrue(self.guarded(root, lambda pid: "exited"))
            for name in ("worker-" + JOB + ".lock", JOB + ".lock"):
                with FileLock(root / name, timeout=.01):
                    self.assertFalse(self.guarded(root, lambda pid: "exited"))

    def test_caller_detects_changed_launch_handle_and_task(self):
        for name in ("launch.json", "handle.json", "task.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.setup_receipts(root)
                def change():
                    data = read_json(root / name)
                    data["updatedAt"] = 99
                    atomic_json(root / name, data)
                self.assertFalse(self.guarded(root, lambda pid: "exited", change))
                self.assertEqual(read_json(root / name)["updatedAt"], 99)

    def test_caller_detects_change_during_first_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_receipts(root)
            def probe(pid):
                data = read_json(root / "task.json")
                data["authorizationStarted"] = True
                atomic_json(root / "task.json", data)
                return "exited"
            self.assertFalse(self.guarded(root, probe))

    def test_caller_rechecks_both_pids_under_locks(self):
        for blocked_pid in (3632, 19688):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.setup_receipts(root)
                calls = []
                def probe(pid):
                    calls.append(pid)
                    return "alive" if len(calls) > 2 and pid == blocked_pid else "exited"
                self.assertFalse(self.guarded(root, probe))
                self.assertEqual(calls, [3632, 19688, 3632, 19688])


class NativeIdentityTests(unittest.TestCase):
    def kernel(self, wait=258, times_ok=True):
        kernel = Mock()
        kernel.OpenProcess.return_value = 12345
        kernel.WaitForSingleObject.return_value = wait
        def times(handle, created, ended, kernel_time, user_time):
            created._obj.dwHighDateTime = 1
            created._obj.dwLowDateTime = 234
            return times_ok
        kernel.GetProcessTimes.side_effect = times
        return kernel

    def native(self, kernel, pid=3632, error=0):
        import ctypes
        with patch.object(lifecycle.os, "name", "nt"):
            with patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
                with patch.object(ctypes, "get_last_error", return_value=error, create=True):
                    return lifecycle.process_identity(pid)

    def test_native_state_and_creation_time_share_non_terminating_handle(self):
        for wait, state in ((258, "alive"), (0, "exited"), (0xffffffff, "unknown")):
            with self.subTest(wait=wait):
                kernel = self.kernel(wait)
                result = self.native(kernel)
                self.assertEqual(result, {"pid": 3632, "state": state, "creationTime": 2**32 + 234})
                kernel.OpenProcess.assert_called_once_with(0x00101000, False, 3632)
                kernel.WaitForSingleObject.assert_called_once_with(12345, 0)
                self.assertEqual(kernel.GetProcessTimes.call_args.args[0], 12345)
                kernel.CloseHandle.assert_called_once_with(12345)
                self.assertNotIn("TerminateProcess", [call[0] for call in kernel.mock_calls])

    def test_access_denied_is_unknown_and_absent_pid_is_exited(self):
        for error, state in ((5, "unknown"), (87, "exited"), (0, "unknown")):
            kernel = self.kernel()
            kernel.OpenProcess.return_value = 0
            self.assertEqual(self.native(kernel, error=error)["state"], state)
            kernel.GetProcessTimes.assert_not_called()
            kernel.WaitForSingleObject.assert_not_called()
            kernel.CloseHandle.assert_not_called()

    def test_query_failure_closes_handle_and_does_not_claim_exit(self):
        kernel = self.kernel(wait=0, times_ok=False)
        self.assertEqual(self.native(kernel)["state"], "unknown")
        kernel.WaitForSingleObject.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(12345)

    def test_invalid_pid_never_reaches_os_and_preserves_state_api(self):
        for pid in (None, True, 0, -1, "3632", 3632.0, 2**32, [], {}):
            kernel = self.kernel()
            self.assertEqual(self.native(kernel, pid=pid)["state"], "unknown")
            kernel.OpenProcess.assert_not_called()
            self.assertEqual(lifecycle.process_state(pid), "unknown")

if __name__ == "__main__":
    unittest.main()
