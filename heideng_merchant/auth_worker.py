"""One task owns the browser, OAuth process and a public-status-only loopback broker."""
from __future__ import annotations

import argparse
import os
import re
import threading
import time
from pathlib import Path

from . import VERSION
from .auth_browser import PlaywrightBrowser
from .auth_broker import BrokerState, make_server, public_status
from .auth_flow import AuthFlow
from .official import OfficialClient
from .operations import Operations
from .safety import SafetyError, atomic_json, read_json, safe_join
from .state import FileLock


def drive_flow(flow, broker, operations, *, sleep=time.sleep):
    flow.registrar = operations
    try:
        while flow.data["stage"] not in flow.TERMINAL:
            if broker.cancelled.is_set():
                flow.cancel()
            else:
                flow.tick()
            broker.update(flow.status(), flow.browser.public_observation())
            if flow.data["stage"] not in flow.TERMINAL:
                sleep(.1)
    except (Exception, KeyboardInterrupt):
        flow.data.update(ready=False, status="unknown" if flow.process is not None else "failed",
                         stage="auth_outcome_unknown" if flow.process is not None else "browser_failed",
                         reason="auth-worker-interrupted-no-replay")
        flow._close()
    broker.update(flow.status())
    return public_status(flow.status())


def run_worker(state, job):
    if not re.fullmatch("[a-f0-9]{24}", job):
        raise SafetyError("invalid-auth-job-id")
    state = Path(state).resolve()
    path = safe_join(state, "tasks/" + job + ".json")
    data = read_json(path, {})
    if data.get("kind") != "shop-auth" or data.get("taskId") != job or data.get("stage") != "starting_worker" or data.get("runtimeVersion") != VERSION:
        raise SafetyError("auth-start-receipt-required-no-replay")
    with FileLock(safe_join(state, "auth/worker-" + job + ".lock"), timeout=.1):
        # Re-read under the ownership lock: a duplicate worker never opens another login.
        current = read_json(path, {})
        if current.get("stage") != "starting_worker":
            raise SafetyError("auth-already-started-no-replay")
        current["stage"] = "initializing_worker"
        atomic_json(path, current)
        try:
            return _run_owned(state, job, data)
        except (Exception, KeyboardInterrupt):
            current = read_json(path, {})
            if current.get("status") == "running":
                unknown = bool(current.get("authorizationStarted"))
                current.update(status="unknown" if unknown else "failed", ready=False,
                               stage="auth_outcome_unknown" if unknown else "browser_failed",
                               reason="worker-start-or-cleanup-incomplete-no-replay")
                atomic_json(path, current)
            return public_status(current)


def _run_owned(state, job, data):
    broker = BrokerState()
    broker.update(data)
    server = make_server(broker)
    handle_path = safe_join(state, "auth/handles/" + job + ".json")
    handle = {"taskId": job, "workerPid": os.getpid(), "port": server.server_port,
              "brokerStopped": False, "startedAt": time.time()}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    atomic_json(handle_path, handle)
    try:
        client = OfficialClient(state)
        browser = PlaywrightBrowser(data["shopName"], data.get("venderId") or None)
        flow = AuthFlow(state, job, data["profile"], data["shopName"], client, browser,
                        expected_vender_id=data.get("venderId") or None)
        result = drive_flow(flow, broker, Operations(state, client))
        # Completed state remains on disk; brief linger permits a final live observation.
        broker.cancelled.wait(2)
        return result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        handle["brokerStopped"] = True
        atomic_json(handle_path, handle)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    try:
        run_worker(args.state, args.job)
        return 0
    except (Exception, KeyboardInterrupt):
        # Never print raw browser, SDK or OAuth errors. Existing receipt forbids replay.
        return 2
