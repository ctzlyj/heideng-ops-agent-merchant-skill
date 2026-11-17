#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京麦 CLI 店铺连接器（本机服务）。

设计边界：
- 只监听 127.0.0.1；授权回调由官方 `jdo-cli login` 自己监听 127.0.0.1:9001。
- 不读取、不返回、不记录任何 token / appSecret / cookie；授权应用使用官方 jdo-cli 内置的，
  不再从别的 Profile 读取 appKey、不复制任何凭据。
- 一次只跑一个授权。授权成功后必须通过 venderinfo 核验店铺身份；与目标不一致则不登记并回滚。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shoplib as sl  # noqa: E402
from redaction import safe_text, safe_value

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "static"
else:
    APP_DIR = Path(__file__).resolve().parent
    STATIC_DIR = APP_DIR / "static"

SERVER_VERSION = "2.1.0-merchant-0.2.8"  # 1.0.2 browser-first authorization protocol
CALLBACK_PORT = sl.CALLBACK_PORT
LOGIN_TIMEOUT = 600
DEFAULT_PORT = 8765
CREATE_NO_WINDOW = sl.CREATE_NO_WINDOW
PROFILE_RE = sl.PROFILE_RE
URL_RE = re.compile(r"https://open-oauth\.jd\.com/oauth2/to_login\?[^\s\"']+")


class CredentialIsolationError(RuntimeError):
    kind = 'credential_isolation'


class CallbackPortBusy(RuntimeError):
    kind = 'port_busy'
    hint = '本机回调端口被占用，未结束其它进程；请先核对任务归属。'

# 兼容旧名
read_json = sl.read_json
write_json = sl.write_json
extract_json = sl.extract_json
strip_ansi = sl.strip_ansi
verify_profile = sl.verify_profile
update_registry = sl.update_registry


def jdo_exe() -> Path:
    exe = sl.find_jdo()
    if not exe:
        raise RuntimeError("未找到 jdo-cli。运行 python scripts/linker.py doctor 查看安装办法。")
    return exe


def ensure_callback_port_free() -> None:
    pid, name = sl.port_owner(CALLBACK_PORT)
    if not pid:
        return
    raise CallbackPortBusy(
        f"本机 {CALLBACK_PORT} 端口被 {name or '未知进程'}(PID {pid}) 占用。"
        "请先关闭该程序或取消上一次授权后重试。"
    )


# ---------------------------------------------------------------- Windows 凭据迁移
class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_longlong),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


def copy_credential(old_target: str, new_target: str, delete_old: bool = False) -> bool:
    """把 Windows 凭据管理器中的 token 复制到新 target，并删除旧 target。

    jdo-cli 在 Profile 还没有 venderId 时把 token 存在 ':default' 下；
    写入 venderId 后会改查 ':<venderId>'，因此需要同步迁移。
    """
    if os.name != "nt":
        return False
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.CredReadW.restype = ctypes.c_bool
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), ctypes.c_uint32]
    advapi32.CredWriteW.restype = ctypes.c_bool
    advapi32.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    advapi32.CredDeleteW.restype = ctypes.c_bool
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    ptr = ctypes.c_void_p()
    if not advapi32.CredReadW(old_target, 1, 0, ctypes.byref(ptr)):
        return False
    try:
        cred = ctypes.cast(ptr, ctypes.POINTER(_CREDENTIAL)).contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        buffer = ctypes.create_string_buffer(blob, len(blob))
        new_cred = _CREDENTIAL()
        new_cred.Flags = 0
        new_cred.Type = 1
        new_cred.TargetName = new_target
        new_cred.Comment = cred.Comment
        new_cred.LastWritten = cred.LastWritten
        new_cred.CredentialBlobSize = len(blob)
        new_cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        new_cred.Persist = 2
        new_cred.AttributeCount = 0
        new_cred.Attributes = None
        new_cred.TargetAlias = None
        new_cred.UserName = (
            new_target[len("jdo-cli:"):]
            if new_target.startswith("jdo-cli:")
            else new_target
        )
        if not advapi32.CredWriteW(ctypes.byref(new_cred), 0):
            return False
    finally:
        advapi32.CredFree(ptr)
    if delete_old:
        advapi32.CredDeleteW(old_target, 1, 0)
    return True


def rename_credential(old_target: str, new_target: str) -> bool:
    return copy_credential(old_target, new_target, delete_old=True)


def delete_credential(target: str) -> bool:
    if os.name != "nt":
        return False
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    advapi32.CredDeleteW.restype = ctypes.c_bool
    return bool(advapi32.CredDeleteW(target, 1, 0))


# ---------------------------------------------------------------- 授权任务

class LoginJob:
    """调用官方 `jdo-cli login --no-browser`，由它监听 9001 并换取令牌。"""

    def __init__(self, profile: str, shop_name: str, expect_vender_id: str = "", force: bool = True,
                 defer_registry: bool = False, timeout: int = LOGIN_TIMEOUT):
        self.id = secrets.token_hex(8)
        self.profile = profile
        self.shop_name = shop_name
        self.expect_vender_id = str(expect_vender_id or "")
        self.force = force
        self.defer_registry = defer_registry
        self.timeout = timeout
        self.created_profile = False
        self.status = "starting"
        self.message = "正在启动京东授权…"
        self.url = ""
        self.identity = None
        self.error = ""
        self.error_kind = ""
        self.log = []
        self.proc = None
        self.started_at = time.time()
        self.finished_at = None
        self._lock = threading.Lock()
        self._url_event = threading.Event()
        self._done = threading.Event()
        self._default_before = None
        self._default_existed = False
        self._raw_output = []  # only in memory; never part of to_dict or disk logs
        self._config_path = sl.config_path()
        self._profiles_path = sl.profiles_dir()

    def to_dict(self):
        return safe_value({
            "id": self.id, "profile": self.profile, "shopName": self.shop_name,
            "expectVenderId": self.expect_vender_id,
            "status": self.status, "message": self.message,
            "identity": self.identity, "error": self.error, "errorKind": self.error_kind,
            "startedAt": int(self.started_at * 1000),
            "finishedAt": int(self.finished_at * 1000) if self.finished_at else None,
        })

    def _restore_default(self):
        cfg = sl.read_json(self._config_path, {}) or {}
        if self._default_before is not None and cfg.get("default_profile") != self._default_before:
            if self._default_existed:
                cfg["default_profile"] = self._default_before
            else:
                cfg.pop("default_profile", None)
            sl.write_json(self._config_path, cfg)

    def _init_profile(self):
        args = ["--endpoint", sl.DEFAULT_ENDPOINT, "init", "--profile", self.profile,
                "--shop-name", self.shop_name or self.profile, "--skip-network"]
        if self.expect_vender_id:
            args += ["--vender-id", self.expect_vender_id]
        code, out = sl.run_jdo(args, timeout=60)
        if code != 0:
            raise RuntimeError("官方 CLI 未创建本任务 Profile，请核对环境与权限。")
        self.created_profile = True

    def start(self):
        exe = jdo_exe()
        cfg = sl.read_json(self._config_path, {}) or {}
        self._default_before = cfg.get("default_profile", "")
        self._default_existed = "default_profile" in cfg
        ensure_callback_port_free()
        if not (self._profiles_path / f"{self.profile}.json").exists():
            try:
                self._init_profile()
            finally:
                self._restore_default()
        cmd = [str(exe), "login", "--profile", self.profile, "--no-browser",
               "--timeout", str(self.timeout)]
        if self.force:
            cmd.append("--force")
        if self.expect_vender_id:
            cmd += ["--vender-id", self.expect_vender_id]
        if self.shop_name:
            cmd += ["--shop-name", self.shop_name]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1, env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        threading.Thread(target=self._monitor, daemon=True).start()
        if not self._url_event.wait(25):
            self._fail("未获取到京东授权地址，请查看日志。", "other")
            return
        deadline = time.time() + 15
        # 注意：不能用 connect 探测 9001，官方回调服务会把空连接当成失败回调而退出；用 netstat 只读判断。
        owned_listener = False
        while time.time() < deadline:
            if self.status in ('failed', 'cancelled', 'success', 'mismatch'):
                return
            owner, _ = sl.port_owner(CALLBACK_PORT)
            if owner:
                if self.proc.poll() is not None or not sl.process_is_owned(owner, self.proc.pid):
                    self._fail('回调监听不属于本任务，未打开授权地址、未结束其它监听者。', 'port_busy')
                    try:
                        self.proc.terminate()
                        self.proc.wait(timeout=2)
                    except Exception:
                        pass
                    return
                owned_listener = True
                break
            time.sleep(0.3)
        if not owned_listener:
            self._fail('本任务的回调监听尚未就绪，未导航授权地址。', 'port_busy')
            if self.proc.poll() is None:
                self.proc.terminate()
            return
        if self.status in ("failed", "cancelled", "success", "mismatch"):
            return
        self.status = "waiting"
        self.message = "请在授权页确认；浏览器已登录目标店铺时，通常只需点一次确认。"

    def _reader(self):
        try:
            for raw in self.proc.stdout:
                line = sl.strip_ansi(raw.rstrip("\r\n"))
                with self._lock:
                    self._raw_output.append(line)
                    self._raw_output = self._raw_output[-500:]
                    self.log.append(safe_text(line))
                    self.log = self.log[-500:]
                if not self.url:
                    match = URL_RE.search(line)
                    if match:
                        self.url = match.group(0)
                        self._url_event.set()
        except Exception as exc:  # pragma: no cover
            with self._lock:
                self.log.append("[reader] output unavailable")

    def _monitor(self):
        code = self.proc.wait()
        self._url_event.set()  # start must not wait 25s for a failed process
        reader = getattr(self, '_reader_thread', None)
        if reader:
            reader.join(timeout=2)
        self._restore_default()
        with self._lock:
            text = "\n".join(self._raw_output)
            self._raw_output.clear()
        if self.status in ("cancelled", "failed"):
            return
        data = sl.extract_json(text)
        if code != 0 or not isinstance(data, dict) or not data.get("ok"):
            msg = self._error_message(text, data, code)
            self._fail(msg, "timeout" if "timed out" in msg.lower() else "auth_failed")
            return
        # Persist only a boolean plus target identity, before network verification.
        # Neither the credential account nor tokens are stored in our proof file.
        if self.expect_vender_id:
            account = str(data.get('tokenCredentialAccount') or '')
            if not account.endswith(':' + self.expect_vender_id):
                sl.mark_auth_rejected(self.profile)
                self._fail('官方凭据槽未证明属于本任务，未登记。', 'credential_isolation')
                return
            try:
                sl.mark_auth_slot(self.profile, self.expect_vender_id)
            except sl.VerifyError as exc:
                self._fail(exc.message, exc.kind)
                return
        if self.status in ("cancelled", "failed"):
            return
        self.status = "verifying"
        self.message = "授权成功，正在核验店铺身份…"
        try:
            identity = sl.verify_profile(self.profile)
        except sl.VerifyError as exc:
            self._fail(f"授权已拿到，但店铺核验失败：{exc.message}", exc.kind)
            if exc.kind == "permission":
                self.message = self.error = self.error + " " + sl.permission_hint()
            return
        except Exception as exc:
            self._fail(f"授权已拿到，但店铺核验失败：{exc}", "other")
            return
        problem = self.check_expected(identity)
        if problem:
            sl.mark_auth_rejected(self.profile)
            self._rollback()
            self.identity = identity
            self.status = "mismatch"
            self.error_kind = "mismatch"
            self.error = self.message = problem
            self.finished_at = time.time()
            self._done.set()
            return
        try:
            self._apply_identity(identity, data)
        except Exception as exc:
            self._fail(f"登记店铺失败：{exc}", getattr(exc, 'kind', 'other'))
            return
        if self.status in ("cancelled", "failed"):
            return
        self.identity = identity
        self.status = "success"
        self.message = f"已连接：{identity['shopName']}（{identity['venderId']}）"
        self.finished_at = time.time()
        self._done.set()

    def check_expected(self, identity: dict) -> str:
        """目标店铺与实际授权店铺不一致时返回说明，否则返回空串。"""
        got_v, got_n = str(identity.get("venderId") or ""), identity.get("shopName") or ""
        if self.expect_vender_id and got_v and got_v != self.expect_vender_id:
            return (f"授权到的店铺（{got_n}，{got_v}）与目标 venderId {self.expect_vender_id} 不一致。"
                    "很可能在别的店铺浏览器里授权了；请切换到目标店铺的京麦账号后重试。")
        if self.shop_name and not self.expect_vender_id:
            if not sl.name_matches(self.shop_name, [got_n]):
                return (f"授权到的店铺是「{got_n}」（{got_v}），与目标「{self.shop_name}」不一致。"
                        "请切换到目标店铺的京麦账号后重试。")
        return ""

    def _rollback(self):
        """身份不符：不留下指向错误店铺的授权。"""
        # Profile names are not token isolation. Never logout a shared credential slot.
        # Only files created by this task are ours to remove; OS credentials stay CLI-managed.
        path = self._profiles_path / f"{self.profile}.json"
        if self.created_profile and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        reg = sl.load_registry()
        if self.profile in reg["profiles"] and self.created_profile:
            reg["profiles"].pop(self.profile, None)
            sl.save_registry(reg)

    def _apply_identity(self, identity: dict, login_data: dict):
        path = self._profiles_path / f"{self.profile}.json"
        data = sl.read_json(path, {}) or {}
        vender_id = str(identity.get("venderId") or "")
        account = str(login_data.get("tokenCredentialAccount") or "")
        if not vender_id or not account.endswith(":" + vender_id):
            sl.mark_auth_rejected(self.profile)
            raise CredentialIsolationError("官方凭据槽未证明属于目标 venderId，未迁移、未登记；请保留当前结果供核验。")
        data["vender_id"] = vender_id
        data["shop_name"] = identity.get("shopName") or data.get("shop_name") or self.shop_name
        data["updated_at"] = int(time.time() * 1000)
        sl.write_json(path, data)
        # 迁移后再核验一次，确保凭据真的可用
        verified = sl.verify_profile(self.profile)
        if self.check_expected(verified):
            raise RuntimeError("凭据定位后店铺身份发生变化，未登记。")
        if not self.defer_registry:
            sl.update_registry(self.profile, verified)

    @staticmethod
    def _error_message(text: str, data, code: int) -> str:
        # Even an unlabelled provider error may contain a code/token. Classify in
        # memory and emit a fixed explanation instead of trusting raw strings.
        kind = sl.classify_error(text)
        if 'timed out' in text.lower() or 'timeout' in text.lower():
            return '授权回调 timed out，请先核验本任务结果。'
        if kind == 'permission':
            return '官方授权权限不足，请核对本店开白。'
        if kind == 'network':
            return '官方授权网络暂不可用，请按当前阶段继续。'
        return f'官方授权尚未完成（退出码 {code}），请先核验本任务结果。'

    def _fail(self, message: str, kind: str = "other"):
        if self.status == "cancelled":
            return
        self.status = "failed"
        self.error = self.message = safe_text(message)
        self.error_kind = kind
        self.finished_at = time.time()
        self._done.set()

    def cancel(self):
        self.status = "cancelled"  # commit cancellation before monitor can report success
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        self._restore_default()
        self.message = "已取消授权。"
        self.finished_at = time.time()
        self._done.set()


ACTIVE = ("starting", "waiting", "verifying")


class Manager:
    def __init__(self):
        self._lock = threading.Lock()
        self.job = None

    def start(self, profile, shop_name, expect_vender_id="", force=True) -> LoginJob:
        with self._lock:
            if self.job and self.job.status in ACTIVE:
                raise RuntimeError(
                    f"已有授权正在进行（{self.job.shop_name or self.job.profile}），请先完成或 cancel。")
            job = LoginJob(profile, shop_name, expect_vender_id, force)
            self.job = job
            try:
                job.start()
            except Exception:
                job.status = "failed"
                raise
            return job

    def current(self):
        with self._lock:
            return self.job

    def start_flow(self, profile, shop_name, expect_vender_id='', browser_config=None, resume=False):
        from browser_auth import BrowserAuthJob
        with self._lock:
            if self.job and hasattr(self.job, 'requested_profile'):
                same_identity = (bool(expect_vender_id) and self.job.expect_vender_id == expect_vender_id)
                same_name = bool(shop_name) and sl.norm(self.job.shop_name) == sl.norm(shop_name)
                same = (same_identity or same_name) and (not expect_vender_id or not self.job.expect_vender_id or same_identity)
                if same and (self.job.status not in ('cancelled', 'failed', 'mismatch') or resume):
                    if resume:
                        self.job.resume()
                    return self.job
            if self.job and self.job.status in ACTIVE:
                raise RuntimeError('已有授权正在进行，请先完成或取消本任务。')
            job = BrowserAuthJob(profile, shop_name, expect_vender_id, browser_config=browser_config)
            self.job = job
            job.start()
            return job

    def cancel(self, job_id=''):
        with self._lock:
            if job_id and self.job and self.job.id != job_id:
                raise ValueError('任务归属不符，未取消其它任务。')
            if self.job and self.job.status not in ('success', 'cancelled'):
                self.job.cancel()


# ---------------------------------------------------------------- HTTP

def create_shop_shortcut(shop_name: str, profile: str, port: int, names=()):
    from urllib.parse import urlencode
    entry = sl.load_registry()["profiles"].get(profile, {})
    source = sl.find_shop_shortcut([shop_name, *names], entry.get("browserShortcut", ""))
    if not source:
        raise RuntimeError(f"没有找到 京麦-{shop_name}.lnk（店铺专用浏览器快捷方式）。")
    info = sl.read_shortcut(source)
    url = f"http://127.0.0.1:{port}/?" + urlencode({"shop": shop_name, "profile": profile})
    cmd = sl.browser_command(info, url)
    if not cmd:
        raise RuntimeError("源快捷方式没有目标程序。")
    out_path = source.parent / f"京麦CLI-{shop_name}.lnk"
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("缺少 pywin32，无法创建快捷方式（pip install pywin32）。") from exc
    pythoncom.CoInitialize()
    try:
        lnk = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(out_path))
        lnk.TargetPath = cmd[0]
        lnk.Arguments = sl.quote_args(cmd[1:])
        lnk.WorkingDirectory = str(info.get("WorkingDirectory") or "")
        lnk.IconLocation = str(info.get("IconLocation") or "")
        lnk.Save()
    finally:
        pythoncom.CoUninitialize()
    reg = sl.load_registry()
    reg["profiles"].setdefault(profile, {})["browserShortcut"] = str(source)
    sl.save_registry(reg)
    return out_path


class Handler(BaseHTTPRequestHandler):
    server_version = "JingmaiCliLinker/" + SERVER_VERSION
    session_token = ""
    manager = None
    port = DEFAULT_PORT

    def log_message(self, fmt, *args):
        return

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get("X-Session-Token") != self.session_token:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}:
            return False
        return True

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

    def _serve_index(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        body = html.replace("__SESSION_TOKEN__", self.session_token).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _state(self) -> dict:
        cfg = sl.read_json(sl.config_path(), {}) or {}
        job = self.manager.current()
        exe = sl.find_jdo()
        view = sl.build_view()
        profiles = []
        for name, e in sorted(view.items(), key=lambda kv: (kv[1].get("shopName") or kv[0]).lower()):
            profiles.append({
                "profile": name, "shopName": e.get("shopName", ""), "venderId": str(e.get("venderId") or ""),
                "shopId": str(e.get("shopId") or ""), "companyName": e.get("companyName", ""),
                "lastVerifiedAt": e.get("lastVerifiedAt") or 0, "status": e.get("status", ""),
                "aliasOf": e.get("aliasOf", ""), "hasProfile": e.get("hasProfile", False),
            })
        return {
            "ok": True,
            "cli": {"path": str(exe or ""), "exists": bool(exe), "version": cfg.get("cli_version") or ""},
            "defaultProfile": cfg.get("default_profile") or "",
            "port": self.port, "registry": str(sl.registry_path()),
            "profiles": profiles, "job": job.to_dict() if job else None,
        }

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._serve_index()
        if path == "/api/health":
            return self._send_json(200, {"ok": True, "version": SERVER_VERSION, "appDir": str(APP_DIR)})
        if not self._authorized():
            return self._send_json(403, {"error": "unauthorized"})
        if path == "/api/state":
            return self._send_json(200, self._state())
        if path == "/api/job":
            job = self.manager.current()
            return self._send_json(200, {"ok": True, "job": job.to_dict() if job else None})
        if path == '/api/browser-action':
            job = self.manager.current()
            # Private transport for a controller: not a public job/log response.
            return self._send_json(200, {'ok': True, 'jobId': job.id if job else '',
                                         'action': job.browser_action() if hasattr(job, 'browser_action') else None})
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return self._send_json(403, {"error": "unauthorized"})
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
            if path == "/api/connect":
                return self._connect(body)
            if path == "/api/cancel":
                self.manager.cancel(str(body.get('jobId') or ''))
                return self._send_json(200, {"ok": True})
            if path == '/api/browser-report':
                job = self.manager.current()
                if not job or body.get('jobId') != job.id:
                    raise ValueError('浏览器报告不属于当前任务。')
                report = job.browser_report(body.get('actionId'), body.get('result') or {})
                if report.get('status') != 'accepted':
                    return self._send_json(409, {'ok': False, 'errorKind': report.get('kind', 'stale_action'),
                                                 'error': '报告未被接受，当前任务与浏览器动作未改变。'})
                return self._send_json(200, {'ok': True})
            if path == '/api/shutdown':
                job = self.manager.current()
                if job and job.status in ACTIVE:
                    return self._send_json(409, {'ok': False, 'error': '授权正在进行，不能替换服务。'})
                self._send_json(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/verify":
                return self._verify(body)
            if path == "/api/shortcut":
                return self._shortcut(body)
            self._send_json(404, {"error": "not found"})
        except Exception as exc:
            self._send_json(400, {"error": safe_text(exc)})

    def _connect(self, body: dict):
        shop_name = str(body.get("shopName") or "").strip()
        profile = str(body.get("profile") or "").strip()
        vender_id = str(body.get("venderId") or "").strip()
        if not shop_name and not vender_id:
            raise ValueError("请填写店铺名称或 venderId。")
        if len(shop_name) > 60:
            raise ValueError("店铺名称过长。")
        if vender_id and not vender_id.isdigit():
            raise ValueError("venderId 必须是数字。")
        if not profile:
            profile = sl.suggest_profile_name(shop_name or vender_id, sl.list_disk_profiles())
        if not PROFILE_RE.match(profile) or profile == "default":
            raise ValueError("Profile 名称只能使用小写字母、数字和短横线，长度 2-41，且不能叫 default。")
        if os.environ.get('HEIDENG_BACKGROUND') == '1' or os.environ.get('JINGMAI_LINKER_BACKGROUND') == '1':
            return self._send_json(200, {'ok': False, 'status': 'deferred', 'stage': 'deferred',
                                         'errorKind': 'background', 'message': '后台不发起扫码或授权。'})
        resolved = sl.resolve(vender_id or shop_name)
        if resolved.get('status') in ('ready', 'needs_auth'):
            wrong_id = vender_id and resolved.get('venderId') and str(resolved['venderId']) != vender_id
            wrong_name = shop_name and resolved.get('shopName') and not sl.name_matches(shop_name, [resolved['shopName']])
            if wrong_id or wrong_name:
                return self._send_json(200, {'ok': False, 'status': 'mismatch', 'errorKind': 'mismatch',
                      'message': '明确 venderId 与店名/实际店铺不一致，未连接。',
                      'expected': {'shopName': shop_name, 'venderId': vender_id}})
        if resolved['status'] != 'needs_auth':
            return self._send_json(200, resolved)
        job = self.manager.start_flow(profile, shop_name, vender_id, body.get('browserConfig'), bool(body.get('resume')))
        self._send_json(200, {"ok": True, 'status': 'awaiting_auth', "jobId": job.id,
                              "profile": job.profile, 'stage': job.stage, 'job': job.to_dict()})

    def _verify(self, body: dict):
        profile = str(body.get("profile") or "").strip()
        if profile == 'default' or not PROFILE_RE.match(profile):
            raise ValueError('请指定合法的非 default Profile。')
        if not profile or not (sl.profiles_dir() / f"{profile}.json").exists():
            raise ValueError("Profile 不存在。")
        try:
            identity = sl.verify_profile(profile)
            sl.assert_profile_proof(profile, identity)
        except sl.VerifyError as exc:
            hint = sl.permission_hint() if exc.kind == "permission" else ""
            return self._send_json(200, {"ok": False, "errorKind": exc.kind, "error": exc.message, "hint": hint})
        sl.update_registry(profile, identity)
        self._send_json(200, {"ok": True, "identity": identity})

    def _shortcut(self, body: dict):
        shop_name = str(body.get("shopName") or "").strip()
        profile = str(body.get("profile") or "").strip()
        if not shop_name or not profile:
            raise ValueError("缺少店铺名称或 Profile。")
        path = create_shop_shortcut(shop_name, profile, self.port)
        self._send_json(200, {"ok": True, "path": str(path)})


def main() -> int:
    parser = argparse.ArgumentParser(description="京麦 CLI 店铺连接器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-clipboard", action="store_true")
    args = parser.parse_args()
    if args.host != '127.0.0.1':
        parser.error('服务只允许监听 127.0.0.1')

    Handler.session_token = secrets.token_urlsafe(24)
    Handler.manager = Manager()
    Handler.port = args.port
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_clipboard:
        try:
            subprocess.run(["clip"], input=url, text=True, creationflags=CREATE_NO_WINDOW, timeout=5)
            print("URL copied to clipboard.")
        except Exception:
            pass
    print("=" * 64)
    print("Jingmai CLI shop linker is running.")
    print(f"Open this URL in the shop's Jingmai browser: {url}")
    if not sl.find_jdo():
        print("[WARN] jdo-cli not found. Run: python scripts/linker.py doctor")
    print("Keep this window open. Press Ctrl+C to stop.")
    print("=" * 64)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
