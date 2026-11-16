"""Loopback status broker. No OAuth URL, raw stream, screenshot or browser action API."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUBLIC_FIELDS = {"kind", "taskId", "profile", "shopName", "venderId", "status", "stage", "ready",
                 "runtimeVersion", "createdAt", "updatedAt", "finishedAt", "reason", "cleanupIncomplete",
                 "authorizationOutcomeUnknown", "authorizationStarted", "sameContextNavigation", "targetStateVerified",
                 "workerExitVerified", "safeToRestart", "workerExitPreviousStage"}


def public_status(data):
    result = {key: value for key, value in data.items() if key in PUBLIC_FIELDS}
    if result.get('stage') == 'waiting_login' and result.get('status') == 'running':
        result['userAction'] = '请在本次任务窗口内完成登录；如显示京麦首页，先点击“登录”，再用京麦App扫码，等待返回目标店工作台。'
    elif result.get('stage') == 'waiting_oauth' and result.get('status') == 'running':
        result['userAction'] = '请在同一任务窗口完成平台授权确认，不关闭窗口；确认后等待官方回执及目标店身份核对。'
    return result


def allowed_request(method, path, headers, port, *, task_id=None):
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    if not task_id or headers.get("x-heideng-task") != task_id:
        return False
    if headers.get("host") != "127.0.0.1:" + str(port):
        return False
    if headers.get("x-heideng-local") != "1" or "origin" in headers or "referer" in headers:
        return False
    if headers.get("sec-fetch-site", "none") != "none":
        return False
    return (method == "GET" and path in {"/status", "/observe"}) or (method == "POST" and path == "/cancel")


class BrokerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self._status = {"stage": "created", "ready": False}
        self._observation = {}

    def update(self, status, observation=None):
        with self.lock:
            self._status = public_status(status)
            if observation is not None:
                self._observation = {k: v for k, v in observation.items()
                                     if k in {"browserStage", "observedIdentityResponses", "matchingIdentityCount",
                                              "ambiguous", "privatePageContent", "taskOwnedContext"}}

    def status(self):
        with self.lock:
            return dict(self._status)

    def observe(self):
        with self.lock:
            return {**self._status, "observation": dict(self._observation)}

    def cancel(self, task_id=None):
        with self.lock:
            if task_id is not None and task_id != self._status.get("taskId"):
                return False
            self.cancelled.set()
            return True


def make_server(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _serve(self):
            self.connection.settimeout(2)
            if not allowed_request(self.command, self.path, self.headers, self.server.server_port, task_id=state.status().get("taskId")):
                self.send_error(403)
                return
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
                self.send_error(400)
                return
            if self.path == "/cancel":
                task_id = self.headers.get("X-Heideng-Task")
                accepted = state.cancel(task_id)
                result = {"taskId": task_id, "cancelRequested": accepted, "ready": False}
            else:
                result = state.observe() if self.path == "/observe" else state.status()
            raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (OSError, TimeoutError):
                pass

        do_GET = do_POST = _serve

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server
