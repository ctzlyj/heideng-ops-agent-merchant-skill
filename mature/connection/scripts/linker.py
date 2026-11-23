#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京麦 CLI 店铺连接器客户端。

核心入口：`ensure-shop --shop 店名|venderId`。写入类任务前先调用它，
拿返回的 profile 和 venderId 再执行。所有命令输出 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
APP_DIR = SKILL_DIR / "app"
sys.path.insert(0, str(APP_DIR))
import shoplib as sl  # noqa: E402
from redaction import safe_text

SERVER_PY = APP_DIR / "server.py"
DEFAULT_PORT = int(os.environ.get('JINGMAI_LINKER_PORT') or 8765)
BASE = f"http://127.0.0.1:{DEFAULT_PORT}"
_LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_EMBEDDED_HTTPD = None
_EMBEDDED_THREAD = None


def http_json(path: str, payload=None, token=None, timeout: int = 30):
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Session-Token"] = token
    request = urllib.request.Request(BASE + path, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
    try:
        with _LOCAL_HTTP.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"error": body or str(exc)}
    except Exception as exc:
        return 0, {"error": str(exc)}


def expected_version() -> str:
    m = re.search(r'^SERVER_VERSION\s*=\s*"([^"]+)"', SERVER_PY.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def server_info(timeout: int = 2):
    status, data = http_json("/api/health", timeout=timeout)
    return data if status == 200 and data.get("ok") is True else None


def server_health(timeout: int = 2) -> bool:
    return server_info(timeout) is not None


def stop_stale_server() -> None:
    """Ask an identified inactive connector to stop; never kill by executable name."""
    info = server_info()
    if not info or Path(info.get('appDir') or '').resolve() != APP_DIR.resolve():
        raise RuntimeError('本机端口由其它目录的服务占用，未结束任何进程。')
    status, result = http_json('/api/shutdown', {}, token=get_token())
    if status != 200 or not result.get('ok'):
        raise RuntimeError('旧连接器未安全退出（可能有在途任务），请结束原任务后重试。')
    deadline = time.time() + 5
    while time.time() < deadline and sl.port_owner(DEFAULT_PORT)[0]:
        time.sleep(0.3)


def ensure_embedded_server() -> bool:
    """Own the connector lifetime in the current foreground command, not the host's child reaper."""
    global _EMBEDDED_HTTPD, _EMBEDDED_THREAD
    if _EMBEDDED_HTTPD is not None:
        return False
    info = server_info()
    if info:
        status, current = http_json('/api/job', token=get_token())
        job = current.get('job') if status == 200 else None
        if job and job.get('status') in ('starting', 'waiting', 'verifying'):
            return False  # Resume the exact live task; never replace its service.
        stop_stale_server()
    import server
    httpd = server.create_httpd(DEFAULT_PORT)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name='merchant-embedded-connector')
    _EMBEDDED_HTTPD, _EMBEDDED_THREAD = httpd, thread
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        if server_info():
            return True
        time.sleep(0.1)
    close_embedded_server()
    raise RuntimeError('前台连接服务启动超时，未发起授权。')


def close_embedded_server() -> None:
    global _EMBEDDED_HTTPD, _EMBEDDED_THREAD
    httpd, thread = _EMBEDDED_HTTPD, _EMBEDDED_THREAD
    snapshot=None
    if httpd is not None:
        job=httpd.RequestHandlerClass.manager.current()
        if job is not None:
            cleanup=job.shutdown()
            worker=getattr(job,'_worker_thread',None)
            if not cleanup and (job.status!='success' or worker is None or worker.is_alive()):
                raise RuntimeError('本任务资源收尾未完成；不能声明已退出或重新授权。')
            snapshot={**job.to_dict(),'cleanupComplete':cleanup}
        httpd.shutdown();httpd.server_close()
    _EMBEDDED_HTTPD = _EMBEDDED_THREAD = None
    if thread is not None:
        thread.join(timeout=5)
    return snapshot


def ensure_server() -> bool:
    if _EMBEDDED_HTTPD is not None:
        return False
    info = server_info()
    if info and info.get("version") == expected_version() and (
            not info.get('appDir') or Path(info['appDir']).resolve() == APP_DIR.resolve()):
        return False
    if info:  # 有服务但版本不符（升级后遗留的旧进程），先停掉
        stop_stale_server()
    if not SERVER_PY.exists():
        raise RuntimeError(f"找不到 app/server.py：{SERVER_PY}")
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(os.environ["HEIDENG_MERCHANT_PACKAGE"])/"scripts/mature_entry.py"),
         str(SERVER_PY), "--port", str(DEFAULT_PORT), "--no-clipboard"],
        cwd=str(APP_DIR), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | (0x00000008 if os.name == "nt" else 0),
        start_new_session=(os.name != "nt"),
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        info = server_info()
        if info and info.get("version") == expected_version():
            return True
        if process.poll() is not None:
            raise RuntimeError(f"本机连接服务在就绪前退出（退出码 {process.returncode}）。请核对当前解释器和连接器运行环境。")
        time.sleep(0.5)
    raise RuntimeError("本机连接器启动超时，请手动运行 python app/server.py 查看错误。")

def get_token() -> str:
    with _LOCAL_HTTP.open(BASE + "/", timeout=10) as response:
        html = response.read().decode("utf-8")
    match = re.search(r'const TOKEN = "([^"]+)"', html)
    if not match:
        raise RuntimeError("无法从页面读取会话令牌。")
    return match.group(1)


def api(path: str, payload=None, timeout: int = 30):
    ensure_server()
    return http_json(path, payload=payload, token=get_token(), timeout=timeout)


def _unwrap(status, data):
    return data if status == 200 else {"ok": False, "error": data.get("error")}


# ---------------------------------------------------------------- 基础命令

def cmd_ensure(_a):
    return {"ok": True, "url": BASE + "/", "started": ensure_server()}


def cmd_state(_a):
    return _unwrap(*api("/api/state"))


def cmd_job(_a):
    info = server_info()
    if info and Path(info.get('appDir') or '').resolve() != APP_DIR.resolve():
        return {'ok': False, 'status': 'blocked', 'errorKind': 'other_connector',
                'error': '当前运行的连接服务不属于这份安装。'}
    result = _unwrap(*http_json("/api/job", token=get_token())) if info else {'ok': True}
    if result.get('ok') and not result.get('job'):
        return {'ok': False, 'status': 'job_lost', 'errorKind': 'job_lost',
                'error': '连接服务中的原任务已丢失；请用同店 ensure-shop 恢复，不要手工重发 OAuth。'}
    return result


def cmd_cancel(_a):
    return _unwrap(*api("/api/cancel", {}))


def cmd_login_completed(a):
    current = cmd_job(a)
    if not current.get('ok'):
        return current
    if (current.get('job') or {}).get('id') != a.job_id:
        return {'ok': False, 'errorKind': 'task_changed', 'error': '原任务已改变，未操作其他店铺页面。'}
    return _unwrap(*http_json('/api/login-completed', {'jobId': a.job_id}, token=get_token()))


def cmd_verify(a):
    return _unwrap(*api("/api/verify", {"profile": a.profile}))


def cmd_shortcut(a):
    return sl.create_verified_desktop_shortcut(a.profile, a.shop)


def cmd_connect(a):
    payload = {"shopName": a.shop or "", "profile": a.profile or "", "venderId": a.vender_id or ""}
    if a.no_open:
        payload['browserConfig'] = {'provider': 'host'}
    elif 'browserConfig' not in payload:
        payload['browserConfig']={'provider':'builtin','shopIdentity':{'shopName':a.shop or '','venderId':a.vender_id or ''}}
    data = _unwrap(*api("/api/connect", payload))
    if data.get('jobId'):
        sl.save_pending({'jobId': data['jobId'], 'profile': data['profile'], 'query': a.shop,
                         'shopName': a.shop or '', 'venderId': a.vender_id or ''})
    return data


def _job_matches(job, job_id='', profile='', vender_id='', shop_name=''):
    if job_id and job.get('id') != job_id or profile and job.get('profile') != profile:
        return False
    if job.get('status') == 'success':
        identity = job.get('identity') or {}
        if vender_id and str(identity.get('venderId') or '') != str(vender_id):
            return False
        if shop_name and not sl.name_matches(shop_name, [identity.get('shopName', '')]):
            return False
    return True


def wait_job(timeout: int, interval: float = 2.0, *, job_id='', profile='', vender_id='', shop_name=''):
    deadline = time.monotonic() + timeout
    last = None
    emitted=None
    while True:
        status, data = api("/api/job")
        if status != 200:
            return {"ok": False, "error": data.get("error")}
        job = data.get("job")
        if not job:
            return {'ok': False, 'status': 'job_lost', 'errorKind': 'job_lost',
                    'error': '连接服务中的原任务已丢失；请用同店 ensure-shop 恢复原任务，不要新建其它店铺会话。'}
        if job:
            if not _job_matches(job, job_id, profile, vender_id, shop_name):
                return {'ok': False, 'status': 'error', 'errorKind': 'task_changed',
                        'error': '当前任务或店铺身份已改变，未组合、登记或使用其它店铺结果。'}
            last = job
            event_key=(job.get('status'),job.get('stage'),job.get('errorKind'),job.get('message'))
            if event_key != emitted:
                emitted=event_key
                descriptions={'waiting_browser':'正在打开商家专用京麦页；尚未证明窗口可见。',
                              'waiting_login':'请在京麦页自行登录；当前命令仍在等待。',
                              'checking_browser_identity':'正在核对网页登录的店铺。',
                              'waiting_oauth':'正在衔接本次官方授权，不需要复制链接。',
                              'waiting_oauth_confirmation':'请在当前京东授权页完成页面提示，连接仍在等待原授权回执。',
                              'verifying_cli':'正在核验原Profile的官方店铺身份。',
                              'ready':'官方核店已通过。'}
                event={'event':'connection-progress','jobId':job.get('id'),'profile':job.get('profile'),
                       'stage':job.get('stage'),'status':job.get('status'),
                       'message':descriptions.get(job.get('stage'),'请按原任务状态继续；不重发未知授权。'),
                       'remainingSeconds':job.get('budgetRemainingSeconds'),'browserChannel':job.get('browserChannel')}
                print(json.dumps(event,ensure_ascii=False),flush=True)
            if job.get("status") in ("success", "failed", "cancelled", "mismatch"):
                return {"ok": job.get("status") == "success", "job": job,
                        'status': 'ready' if job.get('status') == 'success' else job.get('status'),
                        'stage': job.get('stage', '')}
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)
    return {'ok': True, 'status': 'awaiting_auth', 'stage': (last or {}).get('stage', 'waiting_login'), 'job': last}


def cmd_wait(a):
    pending = sl.load_pending()
    res = wait_job(a.timeout, a.interval, job_id=getattr(a, 'job_id', '') or pending.get('jobId', ''),
                   profile=pending.get('profile', ''), vender_id=pending.get('venderId', ''),
                   shop_name=pending.get('shopName', ''))
    job = res.get("job") or {}
    same_job = pending.get('jobId') == job.get('id') if pending.get('jobId') else False
    if res.get("ok") and job.get('status') == 'success' and pending and same_job and pending.get("profile") == job.get("profile"):
        ident = job.get("identity") or {}
        remember_shop(pending["profile"], pending.get("query", ""), pending.get("shopName", ""), ident,
                      pending.get("shortcutPath", ""))
        entry = sl.load_registry()["profiles"].get(pending["profile"], {})
        res.update({"status": "ready", **sl._public(pending["profile"], ident, entry)})
        if job.get('desktopShortcut'):
            res['desktopShortcut'] = job['desktopShortcut']
    if same_job and job.get("status") in ("success", "cancelled", "mismatch"):
        sl.clear_pending(pending.get('jobId'))
    return res


# ---------------------------------------------------------------- 新命令

def cmd_resolve(a):
    return sl.resolve(a.shop)


def _env_blockers():
    if not sl.find_jdo():
        return {"ok": False, "status": "error", "errorKind": "no_cli",
                "error": "这台电脑还没有安装京麦 CLI。",
                "nextActions": ["运行 python scripts/linker.py doctor --install-jdo，装好后会自动初始化，然后重新执行 ensure-shop"]}
    return None


def remember_shop(profile, query, shop_name, ident, shortcut_path=""):
    """授权成功后写登记：把用户当初用的叫法记为别名，并记住专用浏览器，下次 resolve 直接命中。"""
    reg = sl.load_registry()
    entry = reg["profiles"].setdefault(profile, {})
    if shortcut_path:
        entry["browserShortcut"] = shortcut_path
    q = (query or "").strip()
    alias = q if q and not q.isdigit() else shop_name
    if alias and alias != ident.get("shopName", ""):
        entry["aliases"] = sorted(set(entry.get("aliases") or []) | {alias})
    sl.save_registry(reg)


def _cmd_ensure_shop(a, wait_timeout=None):
    blocker = _env_blockers()
    if blocker:
        return blocker
    res = sl.resolve(a.shop)
    if res["status"] != "needs_auth":
        return res
    if a.no_auth:
        res["note"] = "未授权，且指定了 --no-auth，不发起授权。"
        return res
    if os.environ.get('HEIDENG_BACKGROUND') == '1' or os.environ.get('JINGMAI_LINKER_BACKGROUND') == '1':
        return {'ok': False, 'status': 'deferred', 'stage': 'deferred', 'message': '后台不发起扫码或授权。'}
    # 发起授权
    q = a.shop.strip()
    existing = res.get("profile") or ""
    profile = a.profile or existing or res.get("suggestedProfile") or sl.suggest_profile_name(q, sl.list_disk_profiles())
    shop_name = res.get("shopName") or ("" if q.isdigit() else q)
    vender_id = res.get("venderId") or (q if q.isdigit() else "")
    if not shop_name and not vender_id:
        return {"ok": False, "status": "error", "error": "无法确定店铺名称或 venderId"}
    pending=sl.load_pending()
    confirmed_name = (getattr(a, 'confirmed_shop_name', '') or '').strip()
    browser_identity = {'shopName': shop_name, 'venderId': vender_id}
    same_query = bool(pending.get('query')) and sl.norm(pending['query']) == sl.norm(q)
    if confirmed_name:
        if (not getattr(a, 'resume', False) or not same_query or pending.get('processRunning') is not False
                or pending.get('outcome') not in ('login_timeout', 'mismatch', 'oauth_not_opened')
                or not pending.get('shopName') or getattr(a, 'browser_config', None)
                or getattr(a, 'fresh', False) or a.no_open or a.no_wait
                or not 1 < len(confirmed_name) <= 80 or any(ord(char) < 32 for char in confirmed_name)):
            return {'ok': False, 'status': 'blocked', 'errorKind': 'confirmed_shop_resume_unavailable',
                    'error': '确认店名仅用于恢复已结束、且没有待核对授权的原店铺连接。'}
        original_vender_id = pending.get('venderId') or ''
        if original_vender_id and vender_id and original_vender_id != vender_id:
            return {'ok': False, 'status': 'mismatch', 'errorKind': 'mismatch',
                    'error': '原任务的店铺 ID 与当前目标不一致。'}
        vender_id = vender_id or original_vender_id
        browser_identity = pending.get('browserShopIdentity') or {
            'shopName': pending['shopName'], 'venderId': pending.get('venderId', '')}
        shop_name = confirmed_name
    elif same_query and pending.get('confirmedShopName'):
        shop_name = pending['confirmedShopName']
        browser_identity = pending['browserShopIdentity']
    same_target=(bool(shop_name) and pending.get('shopName')==shop_name) or (bool(vender_id) and pending.get('venderId')==vender_id)
    same_pending=bool(same_target and (not a.profile or a.profile==pending.get('profile')))
    if same_pending and pending.get('processRunning') is False and pending.get('outcome')=='callback_unknown':
        original=pending.get('profile')
        try:
            try:sl.require_auth_slot(original,required=True)
            except sl.VerifyError:
                from server import recover_owned_auth_slot
                recover_owned_auth_slot(original,pending.get('jobId'))
                sl.require_auth_slot(original,required=True)
            identity=sl.verify_profile(original)
            sl.assert_profile_proof(original,identity)
            expected_exact = pending.get('confirmedShopName')
            if (vender_id and identity.get('venderId')!=vender_id) or (shop_name and not sl.name_matches(shop_name,[identity.get('shopName','')])) or (expected_exact and identity.get('shopName') != expected_exact):
                return {'ok':False,'status':'mismatch','profile':original,'message':'原Profile核店与目标不符，未重发授权。'}
            sl.update_registry(original,identity)
            if pending.get('confirmedShopName'):
                remember_shop(original,q,shop_name,identity)
            sl.clear_pending(pending.get('jobId'))
            return {'ok':True,'status':'ready','profile':original,'identity':identity,'reconciledOriginal':True}
        except sl.VerifyError as exc:
            return {'ok':False,'status':'paused','errorKind':'callback_unknown','profile':original,
                    'message':'原授权回执尚未核实，已保留原Profile；未重复发起OAuth。','retryAllowed':False}
    if wait_timeout is not None:ensure_embedded_server()
    resume=bool(getattr(a,'resume',False)) or (same_pending and not getattr(a,'fresh',False))
    payload = {"shopName": shop_name, "profile": profile, "venderId": vender_id,
               'resume': resume}
    if wait_timeout is not None:payload['timeoutSeconds']=wait_timeout
    config_file = getattr(a, 'browser_config', '')
    if config_file:
        payload['browserConfig'] = sl.read_json(Path(config_file), {})
    if a.no_open:
        payload['browserConfig'] = {'provider': 'host'}
    elif 'browserConfig' not in payload:
        payload['browserConfig']={'provider':'builtin','shopIdentity':browser_identity}
        if confirmed_name or (same_query and pending.get('confirmedShopName')):
            payload['browserConfig']['confirmedShopName'] = shop_name
    started = _unwrap(*api("/api/connect", payload))
    if started.get('status') == 'ready':
        return started
    if not started.get("ok"):
        err = str(started.get("error") or "")
        out = {"ok": False, "status": "error", "errorKind": "auth_busy" if "已有授权" in err else "other",
               "error": err}
        if "9001" in err:
            out["errorKind"] = "port_busy"
            out["nextActions"] = ["先运行 python scripts/linker.py cancel，仍被占用则关闭占用 9001 的程序后重试"]
        return out
    profile = started.get('profile') or profile
    out_base = {'profile': profile, 'jobId': started.get('jobId'), 'stage': started.get('stage', 'waiting_login')}
    started_job = started.get('job') or {}
    for key in ('browserChannel', 'browserSelectionReason'):
        if started_job.get(key):
            out_base[key] = started_job[key]
    pending_data = {'jobId': started.get('jobId'), 'profile': profile, 'query': q, 'shopName': shop_name,
                    'venderId': vender_id}
    if (payload.get('browserConfig') or {}).get('confirmedShopName'):
        pending_data.update(confirmedShopName=shop_name,browserShopIdentity=browser_identity)
    sl.save_pending(pending_data)
    if a.no_wait:
        return {'ok': True, 'status': 'awaiting_auth', 'message': (started.get('job') or {}).get('message', ''), **out_base}
    waited = wait_job(wait_timeout if wait_timeout is not None else min(a.timeout, 3), interval=0.5, job_id=started.get('jobId', ''), profile=profile,
                       vender_id=vender_id, shop_name=shop_name)
    job = waited.get("job") or {}
    st = job.get("status")
    if st == "success":
        if not _job_matches(job, started.get('jobId', ''), profile, vender_id, shop_name):
            return {'ok': False, 'status': 'error', 'errorKind': 'task_changed',
                    'error': '等待结果不属于原任务或目标店铺，未登记。'}
        ident = job.get("identity") or {}
        entry = sl.load_registry()["profiles"].get(profile, {})
        remember_shop(profile, q, shop_name, ident)
        entry = sl.load_registry()["profiles"].get(profile, {})
        sl.clear_pending(started.get('jobId'))
        result = {"ok": True, "status": "ready", "reauthorized": True, **sl._public(profile, ident, entry), **out_base, 'stage': 'ready'}
        if job.get('desktopShortcut'):
            result['desktopShortcut'] = job['desktopShortcut']
        return result
    if st == "mismatch":
        return {"ok": False, "status": "mismatch", "profile": profile, "message": job.get("message"),
                'expectedShopName':shop_name,'needsMerchantAction':True,
                'nextAction':'请确认口述店名与当前官方店名是否为同店；未确认不登记，不复制Profile或修改授权证明。',
                "actual": {"shopName": (job.get("identity") or {}).get("shopName", ""),
                           "venderId": (job.get("identity") or {}).get("venderId", "")}, **out_base}
    if waited.get('status') == 'awaiting_auth':
        return {'ok': True, 'status': 'awaiting_auth', **out_base, 'stage': job.get('stage', out_base['stage']),
                'message': job.get('message', '')}
    hint = sl.permission_hint() if job.get("errorKind") == "permission" else ""
    return {"ok": False, "status": "error", "errorKind": waited.get('errorKind') or job.get("errorKind") or "timeout",
            "error": job.get("message") or waited.get("error"), "hint": hint, **out_base}


def cmd_ensure_shop(a):
    foreground = (not getattr(a, 'no_wait', False) and not getattr(a, 'no_open', False) and not getattr(a, 'browser_config', None)
                  and os.environ.get('HEIDENG_BACKGROUND') != '1' and os.environ.get('JINGMAI_LINKER_BACKGROUND') != '1')
    if not foreground:
        return _cmd_ensure_shop(a)
    result=None
    try:
        result=_cmd_ensure_shop(a, getattr(a, 'timeout', 600))
    except KeyboardInterrupt:
        result={'ok':False,'status':'awaiting_auth','message':'用户结束等待，正在核对并收尾原任务。'}
    finally:
        snapshot=close_embedded_server()
    if snapshot and result:
        result['resourceCleanup']='completed' if snapshot.get('cleanupComplete',True) else 'pending'
    if snapshot and result and result.get('status') not in ('ready','mismatch'):
        if snapshot.get('status')=='success':
            result = {'ok':True,'status':'ready','profile':snapshot['profile'],'identity':snapshot.get('identity'),
                    'processRunning':False,'reconciledOriginal':True,'retryAllowed':False,
                    'resourceCleanup':result['resourceCleanup']}
            if snapshot.get('desktopShortcut'):
                result['desktopShortcut'] = snapshot['desktopShortcut']
        else:
            ended='paused' if snapshot.get('stage')=='paused' else snapshot.get('status','failed')
            result.update(ok=False,status=ended,profile=snapshot.get('profile'),jobId=snapshot.get('id'),stage=snapshot.get('stage'),errorKind=snapshot.get('errorKind'),
                          processRunning=False,canLeave=True,retryAllowed=False,
                          nextAction='原命令已收尾；同店再次ensure-shop先核对原Profile，不手工重发OAuth。')
    if snapshot and result and result.get('status') != 'ready':
        pending=sl.load_pending()
        if pending.get('jobId')==snapshot.get('id'):
            sl.save_pending({**pending,'stage':snapshot.get('stage'),'processRunning':False,'outcome':snapshot.get('errorKind')})
    if (result and result.get('status') == 'ready' and 'desktopShortcut' not in result
            and not getattr(a, 'no_auth', False) and result.get('profile')):
        identity = result.get('identity') or {name: result.get(name) for name in ('shopName', 'shopId', 'venderId')}
        result['desktopShortcut'] = sl.ensure_desktop_shortcut(result['profile'], identity)
    return result


def cmd_audit(a):
    blocker = _env_blockers()
    if blocker:
        return blocker
    return sl.audit(apply_aliases=not a.no_write)


def cmd_doctor(a):
    extra = {}
    if a.install_jdo:
        res = sl.install_jdo()
        extra["install"] = res
        if res.get("ok") and res.get("installed"):
            # 装好后直接初始化，让同事不用回头问下一步
            extra["init"] = sl.init_jdo()
            if not extra["init"].get("ok"):
                extra["install"] = sl._install_fail("init_failed", extra["init"].get("message", ""))
    elif a.init and sl.find_jdo():
        extra["init"] = sl.init_jdo()
    result = sl.doctor()
    result.update(extra)
    inst = extra.get("install") or {}
    if inst.get("ok") and result.get("ok"):
        result["nextStep"] = '环境已就绪。告诉 Agent 要连接的店名；需要登录时商家用京麦 App 扫网页二维码，之后自动衔接授权。'
    elif inst and not inst.get("ok"):
        result["ok"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Jingmai CLI shop linker client")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn in (("ensure", cmd_ensure), ("state", cmd_state), ("job", cmd_job), ("cancel", cmd_cancel)):
        sub.add_parser(name).set_defaults(func=fn)

    p = sub.add_parser("resolve", help="店名/简称/venderId → profile（只读）")
    p.add_argument("--shop", required=True)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("remember-alias", help="保存商家已明确确认的店铺简称")
    p.add_argument("--shop", required=True, help="官方店名或 venderId")
    p.add_argument("--alias", required=True)
    p.set_defaults(func=lambda args: sl.remember_confirmed_alias(args.shop, args.alias))

    p = sub.add_parser("ensure-shop", help="解析→可用即返回→否则授权→核验→登记")
    p.add_argument("--shop", required=True, help="店名、简称或明确 venderId；不把 shopId 当 venderId")
    p.add_argument("--profile", help="新店用的 Profile 名（默认自动生成）")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--no-auth", action="store_true", help="只解析，未授权也不发起授权")
    p.add_argument("--no-open", action="store_true", help="暂不打开页面，返回等待浏览器状态")
    p.add_argument("--no-wait", action="store_true", help="立即返回任务与阶段，由 Agent 短轮询")
    p.add_argument('--resume', action='store_true', help='先核验已有结果，再恢复同任务')
    p.add_argument('--confirmed-shop-name', help='用户确认的京麦官方店名；与原查询及 --resume 一起使用')
    p.add_argument('--fresh', action='store_true', help='明确放弃旧会话并新建任务；不用于普通网络中断恢复')
    p.add_argument('--browser-config', help='Agent 提供的非敏感浏览器适配配置文件')
    p.set_defaults(func=cmd_ensure_shop)

    p = sub.add_parser("audit", help="只读体检全部 Profile")
    p.add_argument("--no-write", action="store_true", help="不更新本机登记表（别名/主 Profile 标记）")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("doctor", help="检查/修复运行环境")
    p.add_argument("--install-jdo", action="store_true")
    p.add_argument("--init", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("connect", help="底层：发起授权并（默认）自动打开授权页")
    p.add_argument("--shop", default="")
    p.add_argument("--profile", default="")
    p.add_argument("--vender-id", default="")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("wait")
    p.add_argument('--job-id', default='', help='显式绑定原任务，默认使用本任务pending')
    p.add_argument("--timeout", type=int, default=3)
    p.add_argument("--interval", type=float, default=2.0)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser('login-completed', help='商家已说明扫码登录完成，用原任务的现有页面核对工作台')
    p.add_argument('--job-id', required=True)
    p.set_defaults(func=cmd_login_completed)

    p = sub.add_parser("verify")
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("shortcut")
    p.add_argument("--shop", required=True)
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_shortcut)

    args = parser.parse_args()
    try:
        result = args.func(args)
    except Exception as exc:
        result = {"ok": False, "status": "error", "error": safe_text(exc)}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
