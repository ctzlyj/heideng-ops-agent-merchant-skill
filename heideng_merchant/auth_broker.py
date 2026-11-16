"""Loopback status broker. No OAuth URL, raw stream, screenshot or browser action API."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .safety import redact

PUBLIC_FIELDS = {"kind", "taskId", "profile", "shopName", "venderId", "status", "stage", "ready",
                 "runtimeVersion", "createdAt", "updatedAt", "finishedAt", "reason", "cleanupIncomplete",
                 "authorizationOutcomeUnknown", "authorizationStarted", "sameContextNavigation", "targetStateVerified",
                 "workerExitVerified", "workerOwnershipEvidence", "safeToRestart", "workerExitPreviousStage",
                 "requestedShopName", "identityConfirmed", "identityDiagnostic", "confirmationRejected", "browserProvider"}


def public_candidates(candidates):
    result=[]
    if isinstance(candidates,list):
        for candidate in candidates[:20]:
            if not isinstance(candidate,dict):continue
            name=candidate.get('shopName');vid=candidate.get('venderId');fingerprint=candidate.get('fingerprint')
            if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(c)<32 for c in name) or redact(name)!=name:continue
            if not isinstance(vid,str) or re.fullmatch('[1-9][0-9]{0,19}',vid) is None:continue
            if not isinstance(fingerprint,str) or re.fullmatch('[a-f0-9]{64}',fingerprint) is None:continue
            result.append({'shopName':name,'venderId':vid,'fingerprint':fingerprint})
    return result


def public_status(data):
    result = {key: value for key, value in data.items() if key in PUBLIC_FIELDS}
    if result.get('stage') == 'waiting_login' and result.get('status') == 'running':
        result['userAction'] = '请在本次任务窗口内完成登录；如显示京麦首页，先点击“登录”，再用京麦App扫码，等待返回目标店工作台。'
        if result.get('browserProvider')=='original-linker-host-controller':
            result['userAction']='Agent正在通过现有浏览器核对真实店铺；如需登录或本人验证，请在本次窗口完成，已登录时不重复扫码。'
    elif result.get('stage') == 'waiting_shop_confirmation' and result.get('status') == 'running':
        result['userAction'] = '已读取实际店铺，请确认候选中的完整店名及venderId；保持本次窗口和长命令，不取消重扫。'
    elif result.get('stage') == 'waiting_oauth' and result.get('status') == 'running':
        result['userAction'] = '请在同一任务窗口完成平台授权确认，不关闭窗口；确认后等待官方回执及目标店身份核对。'
    if 'identityCandidates' in data:
        result['identityCandidates']=public_candidates(data['identityCandidates'])
    return result


OBSERVATION_FIELDS={'browserStage','observedIdentityResponses','matchingIdentityCount','ambiguous','privatePageContent','taskOwnedContext','identityCandidateCount','candidateOverflow','taskPageCount','observedResponseCount','untrustedResponseCount','nonJsonResponseCount','identityDiagnostic','browserProvider'}

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
    return (method == "GET" and path in {"/status", "/observe"}) or (method == "POST" and path in {"/cancel", "/confirm-shop"})


class BrokerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self._status = {"stage": "created", "ready": False}
        self._observation = {}
        self._confirmation = None

    def update(self, status, observation=None):
        with self.lock:
            self._status = public_status(status)
            if observation is not None:
                self._observation = {k: v for k, v in observation.items()
                                     if k in OBSERVATION_FIELDS}

    def status(self):
        with self.lock:
            return dict(self._status)

    def observe(self):
        with self.lock:
            return {**self._status, "observation": dict(self._observation)}

    def confirm_shop(self,task_id,payload):
        with self.lock:
            if self.cancelled.is_set() or task_id!=self._status.get('taskId') or self._status.get('stage')!='waiting_shop_confirmation' or self._status.get('status')!='running':return False
            if not isinstance(payload,dict) or set(payload)!={'shopName','venderId','fingerprint'}:return False
            if payload not in self._status.get('identityCandidates',[]):return False
            if self._confirmation is not None and self._confirmation!=payload:return False
            self._confirmation=dict(payload);return True

    def take_confirmation(self):
        with self.lock:
            value=self._confirmation;self._confirmation=None;return value

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
            if self.headers.get("Transfer-Encoding") or (self.path!="/confirm-shop" and self.headers.get("Content-Length", "0") != "0"):
                self.send_error(400)
                return
            if self.path=='/confirm-shop':
                length=self.headers.get('Content-Length','0')
                if not length.isdigit() or not 0<int(length)<=4096 or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    self.send_error(400);return
                try:payload=json.loads(self.rfile.read(int(length)))
                except (ValueError,OSError,TimeoutError):self.send_error(400);return
                task_id=self.headers.get('X-Heideng-Task')
                accepted=state.confirm_shop(task_id,payload)
                result={'taskId':task_id,'confirmationRequested':accepted,'ready':False}
            elif self.path == "/cancel":
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
