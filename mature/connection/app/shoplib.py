# -*- coding: utf-8 -*-
"""店铺解析、登记、体检与环境检查（纯本机，无网络写入）。

约束：不读取、不返回、不记录 token / appSecret / cookie。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from redaction import safe_text
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CALLBACK_PORT = 9001
DEFAULT_ENDPOINT = "https://mcp-open.jd.com"
OFFICIAL_BASE = "https://mcp-open.jd.com/"
VERSION_POLICY_URL = OFFICIAL_BASE + "cli/version-policy.json"
MAX_ZIP_BYTES = 64 * 1024 * 1024  # 官方包约 8MB；超出视为异常
REGISTRY_VERSION = 2


# ---------------------------------------------------------------- 路径

def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def jdo_home() -> Path:
    return Path(os.environ.get("JDO_HOME") or (user_home() / ".jdo-cli"))


def profiles_dir() -> Path:
    return jdo_home() / "profiles"


def config_path() -> Path:
    return jdo_home() / "config.json"


def linker_home() -> Path:
    return Path(os.environ.get("JINGMAI_LINKER_HOME") or (user_home() / ".jingmai-cli-linker"))


def registry_path() -> Path:
    return linker_home() / "shops.json"


def find_jdo():
    """自动探测 jdo-cli：环境变量 > PATH > ~/.jdo-cli/bin。找不到返回 None。"""
    env = os.environ.get("JDO_CLI_PATH")
    if env and Path(env).exists():
        return Path(env)
    found = shutil.which("jdo-cli")
    if found:
        return Path(found)
    exe = jdo_home() / "bin" / ("jdo-cli.exe" if os.name == "nt" else "jdo-cli")
    return exe if exe.exists() else None


def default_jdo_path() -> Path:
    return jdo_home() / "bin" / ("jdo-cli.exe" if os.name == "nt" else "jdo-cli")


# ---------------------------------------------------------------- 基础 IO

def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def decode_bytes(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def read_json(path: Path, default=None):
    from heideng_merchant import require_local
    require_local(path, parents=True)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    """UTF-8 无 BOM、原子写入（jdo-cli 读不了带 BOM 的 JSON）。"""
    from heideng_merchant import require_local
    require_local(path, parents=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def extract_json(text: str):
    text = strip_ansi(text or "")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
        except Exception:
            continue
        if isinstance(obj, dict) and (
            "success" in obj or "ok" in obj or "data" in obj or "error" in obj
        ):
            return obj
    return None


def run_jdo(args, timeout: int = 60):
    exe = find_jdo()
    if not exe:
        raise RuntimeError("未找到 jdo-cli")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        timeout=timeout,
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )
    text = decode_bytes(proc.stdout or b"")
    if proc.returncode:
        text += '\n' + decode_bytes(proc.stderr or b"")
    text = strip_ansi(text)
    return proc.returncode, text


def is_port_open(port: int) -> bool:
    """仅用于非授权期的检查。授权进行中不要调用：对 9001 的空连接会让 jdo-cli 回调失败。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_owner(port: int):
    """返回 (pid, 进程名)；无占用返回 (None, '')。"""
    if os.name != "nt":
        try:
            result = subprocess.run(["lsof", "-nP", "-iTCP:" + str(int(port)), "-sTCP:LISTEN", "-t"],
                                    capture_output=True, timeout=5)
            ids = decode_bytes(result.stdout).strip().splitlines()
            return (int(ids[0]), "") if ids else (None, "")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("无法只读核对回调端口占用；请安装/检查 lsof，未发起授权。") from exc
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        out = decode_bytes(out)
    except Exception:
        return None, ""
    pid = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            try:
                pid = int(parts[4])
            except ValueError:
                pid = None
            break
    if not pid:
        return None, ""
    try:
        out = decode_bytes(subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, creationflags=CREATE_NO_WINDOW,
        ).stdout)
        line = out.strip().splitlines()[0] if out.strip() else ""
        name = "" if (not line or "INFO:" in line) else line.split(",")[0].strip('"')
    except Exception:
        name = ""
    return pid, name


def process_is_owned(candidate_pid, root_pid):
    """Prove parentage using numeric OS process metadata, never executable names."""
    if not isinstance(candidate_pid, int) or not isinstance(root_pid, int):
        return False
    seen = set()
    while candidate_pid and candidate_pid not in seen and len(seen) < 32:
        if candidate_pid == root_pid:
            return True
        seen.add(candidate_pid)
        try:
            if os.name == 'nt':
                script = ('Get-CimInstance Win32_Process -Filter "ProcessId = ' + str(candidate_pid) +
                          '" | Select-Object -ExpandProperty ParentProcessId')
                result = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                        capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)
                candidate_pid = int(decode_bytes(result.stdout).strip())
            else:
                result = subprocess.run(['ps', '-o', 'ppid=', '-p', str(candidate_pid)],
                                        capture_output=True, timeout=5)
                candidate_pid = int(decode_bytes(result.stdout).strip())
        except Exception:
            return False
    return False


# ---------------------------------------------------------------- 进行中授权的上下文（--no-wait 后由 wait 补登记）

def pending_path() -> Path:
    return linker_home() / "pending-auth.json"


def save_pending(data: dict) -> None:
    write_json(pending_path(), data)


def load_pending() -> dict:
    return read_json(pending_path(), {}) or {}


def clear_pending(job_id=None) -> None:
    if job_id and load_pending().get('jobId') != job_id:
        return
    try:
        pending_path().unlink()
    except OSError:
        pass


@contextmanager
def _proof_lock():
    """Serialize this tool's non-secret proof file across client/service processes."""
    home = linker_home()
    home.mkdir(parents=True, exist_ok=True)
    with (home / 'authorization-proof.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise VerifyError('credential_isolation', '授权证明状态正在由其它任务更新，请稍后核对。')
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _proof_data():
    path = linker_home() / 'authorization-proof.json'
    if not path.exists():
        return {'version': 1, 'profiles': {}}
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
        raise VerifyError('credential_isolation', '授权证明状态不可读取，不推断凭据已经隔离。')
    return data


def mark_auth_pending(profile, job_id, vender_id='', shop_name='', *, exact_shop_name=False):
    with _proof_lock():
        data = _proof_data()
        old = data['profiles'].get(profile)
        if old and old.get('jobId') == job_id:
            return
        data['profiles'][profile] = {'jobId': job_id, 'venderId': str(vender_id or ''),
                                     'shopName': shop_name or '', 'status': 'pending', 'slotVerified': False}
        if exact_shop_name:
            data['profiles'][profile]['exactShopName'] = True
        write_json(linker_home() / 'authorization-proof.json', data)


def mark_auth_native_completed(profile, job_id, native_job_id, *, default_slot_namespace='', default_slot_scope='', reused_login=False):
    with _proof_lock():
        data=_proof_data();proof=data['profiles'].get(profile)
        if not proof or proof.get('jobId')!=job_id or proof.get('status')=='rejected':
            raise VerifyError('credential_isolation','官方完成回执不属于当前连接任务，未登记。')
        proof.update(nativeCompleted=True,nativeJobId=str(native_job_id), originalCliHome=str(jdo_home().resolve()))
        if reused_login:
            proof['nativeReused'] = True
        if default_slot_namespace:
            proof['nativeDefaultSlotNamespace'] = default_slot_namespace
        if default_slot_scope:
            proof['nativeDefaultSlotScope'] = default_slot_scope
        write_json(linker_home()/'authorization-proof.json',data)


def mark_auth_slot(profile, vender_id, *, profile_default_scope='', shop_id='', official_name='', job_id=None):
    with _proof_lock():
        data = _proof_data()
        proof = data['profiles'].get(profile)
        if (not proof or proof.get('status') == 'rejected' or proof.get('venderId') not in ('', str(vender_id))
                or (job_id is not None and proof.get('jobId') != job_id)):
            raise VerifyError('credential_isolation', '凭据槽证明与本任务不符，未登记。')
        if ((profile_default_scope and not re.fullmatch(r'[0-9a-f]{16}', profile_default_scope)) or
                ((shop_id or official_name or profile_default_scope) and
                 (not str(shop_id).isascii() or not str(shop_id).isdigit() or not official_name)) or
                (shop_id and proof.get('shopId') and str(shop_id) != str(proof['shopId'])) or
                (official_name and proof.get('officialShopName') and official_name != proof['officialShopName'])):
            raise VerifyError('credential_isolation', '原 Profile 的店铺 ID 或范围证明不完整。')
        proof.update(venderId=str(vender_id), slotVerified=True)
        if shop_id:
            proof.update(shopId=str(shop_id), officialShopName=official_name)
        if profile_default_scope:
            proof.update(slotKind='profile-default', profileDefaultScope=profile_default_scope,
                         originalCliHome=str(jdo_home().resolve()))
        write_json(linker_home() / 'authorization-proof.json', data)


def mark_auth_rejected(profile):
    with _proof_lock():
        data = _proof_data()
        if profile in data['profiles']:
            data['profiles'][profile].update(status='rejected', slotVerified=False)
            write_json(linker_home() / 'authorization-proof.json', data)


def require_auth_slot(profile, required=False, *, job_id=None):
    proof = _proof_data()['profiles'].get(profile)
    if proof is None and not required:
        return  # Existing legacy authorization is verified live, never forced to re-login.
    if (not proof or proof.get('status') == 'rejected' or proof.get('slotVerified') is not True
            or (job_id is not None and proof.get('jobId') != job_id)):
        raise VerifyError('credential_isolation', '本任务的官方凭据槽尚未证明或已拒绝，先核对回执，不重复授权。')
    _check_profile_default(profile, proof)


def _check_profile_default(profile, proof):
    if proof.get('slotKind') == 'profile-default':
        from server import check_profile_default_scope, NativeReceiptPending
        if proof.get('originalCliHome') != str(jdo_home().resolve()):
            raise VerifyError('credential_isolation', '当前 CLI 目录与原店铺任务不符。')
        try:
            check_profile_default_scope(profile, proof.get('profileDefaultScope'))
        except NativeReceiptPending as exc:
            raise VerifyError('credential_isolation', str(exc)) from None


def assert_registered_identity(profile, identity):
    path = registry_path()
    if not path.exists():
        return
    registry = read_json(path)
    if not isinstance(registry,dict) or not isinstance(registry.get('profiles'),dict):
        raise VerifyError('credential_isolation','原店铺登记不能读取，未覆盖。')
    registered = registry['profiles'].get(profile) or {}
    if not isinstance(registered,dict):
        raise VerifyError('credential_isolation','原 Profile 的店铺登记不能读取，未覆盖。')
    for key in ('shopId','venderId','shopName'):
        if key == 'shopName' and not (registered.get('lastVerifiedAt') or registered.get('shopId')):
            continue  # Initial profiles can carry the merchant's working name.
        if registered.get(key) and str(registered[key]) != str(identity.get(key) or ''):
            raise VerifyError('credential_isolation', '官方核店与原 Profile 的已登记身份不一致。')


def _assert_proof_identity(proof, identity):
    shop_id = str(identity.get('shopId') or '')
    name = identity.get('shopName') or ''
    if (proof.get('status') == 'rejected' or proof.get('slotVerified') is not True or
            not shop_id.isascii() or not shop_id.isdigit() or not name or
            str(identity.get('venderId') or '') != proof.get('venderId') or
            (proof.get('shopId') and shop_id != str(proof['shopId'])) or
            (proof.get('officialShopName') and name != proof['officialShopName']) or
            (proof.get('exactShopName') and name != proof.get('shopName')) or
            (proof.get('shopName') and not name_matches(proof['shopName'], [name]))):
        raise VerifyError('credential_isolation', '当前官方核店的商家 ID、店铺 ID 或店名与原授权证明不符。')


def assert_profile_proof(profile, identity):
    assert_registered_identity(profile, identity)
    proof = _proof_data()['profiles'].get(profile)
    if proof is None:
        return
    _check_profile_default(profile, proof)
    _assert_proof_identity(proof, identity)
    if proof.get('status') == 'verified' and proof.get('shopId') and proof.get('officialShopName'):
        return
    if not proof.get('shopId') and proof.get('nativeCompleted'):
        # A crash can leave just the native receipt and numeric slot on disk.
        # Both confirmations must come from this original profile before completing it.
        repeated = verify_profile(profile)
        if any(str(identity.get(k) or '') != str(repeated.get(k) or '') for k in ('shopId','venderId','shopName')):
            raise VerifyError('credential_isolation', '原 Profile 的两次官方核店身份不一致。')
    with _proof_lock():
        data = _proof_data()
        current = data['profiles'].get(profile)
        if not current or current.get('jobId') != proof.get('jobId'):
            raise VerifyError('credential_isolation', '核验期间原授权任务已变化。')
        _assert_proof_identity(current, identity)
        current.update(status='verified', shopId=str(identity['shopId']), officialShopName=identity['shopName'])
        write_json(linker_home() / 'authorization-proof.json', data)


# ---------------------------------------------------------------- 名称归一

def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\-_·•・/\\()（）【】\[\]'\"“”‘’,，.。]+", "", text)


def name_matches(query: str, names) -> bool:
    nq = norm(query)
    if not nq:
        return False
    for name in names:
        nn = norm(name)
        if not nn:
            continue
        if nq == nn:
            return True
        if len(nq) >= 2 and nq in nn:
            return True
        if len(nn) >= 3 and nn in nq:
            return True
    return False


def suggest_profile_name(query: str, existing=()) -> str:
    q = unicodedata.normalize("NFKC", str(query or "")).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", q).strip("-")
    if q.isdigit():
        base = "pop-" + q
    elif len(slug) >= 3:
        base = "pop-" + slug
    else:
        base = "pop-shop-" + hashlib.sha1(q.encode("utf-8")).hexdigest()[:8]
    namespace = hashlib.sha256(str(linker_home().resolve()).encode("utf-8")).hexdigest()[:8]
    base = ("hm-" + namespace + "-" + base)[:38].rstrip("-")
    existing = set(existing)
    name, i = base, 2
    while name in existing:
        name = f"{base}-{i}"
        i += 1
    return name


# ---------------------------------------------------------------- 错误分类 / venderinfo

class VerifyError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def classify_error(text: str) -> str:
    from heideng_merchant.cli_diagnostics import runtime_failure
    runtime = runtime_failure(text)
    if runtime:
        return runtime
    t = (text or "").lower()
    if "missing sp-api auth config" in t:
        return "auth_missing"
    if "refresh_token" in t or "没有做过授权" in t or "请先授权" in t or "token" in t and "无效" in t:
        return "auth_expired"
    if any(k in t for k in ("权限", "forbidden", "403", "未开通", "未订购", "未开白", "service market", "not subscribed", "无访问")):
        return "permission"
    if any(k in t for k in ("timed out", "timeout", "urlopen", "connection", "getaddrinfo", "超时", "10061", "10060")):
        return "network"
    return "other"


def permission_hint() -> str:
    return ("本店可能尚未开通京麦 CLI/API 权限。请在京麦官方开放平台核对本店授权范围，"
            "或联系京麦官方支持；本安装包不依赖员工开白表或公司账号。")


def profile_arg(profile: str) -> str:
    # 用 --profile=NAME 形式，名称以 - 开头（如 '--------'）也能传参
    return f"--profile={profile}"


def verify_profile(profile: str) -> dict:
    """实时只读调用 venderinfo，返回店铺身份；失败抛 VerifyError。"""
    try:
        code, out = run_jdo(
            [
                "invoke", "--skill-id", "jdo-seller-info",
                "--url", "/rest/sp-seller/v0/venderinfo", "--method", "GET",
                "--params", '{"scopeSet":"baseInfo"}',
                "--request-identity", "vender", profile_arg(profile),
            ],
            timeout=60,
        )
    except RuntimeError as exc:
        raise VerifyError("no_cli", str(exc))
    except subprocess.TimeoutExpired:
        raise VerifyError("network", "调用 venderinfo 超时")
    data = extract_json(out)
    if code != 0 or not isinstance(data, dict) or not data.get("success"):
        detail = out.strip().splitlines()[-1] if out.strip() else f"退出码 {code}"
        if isinstance(data, dict) and data.get("errorList"):
            first = data["errorList"][0] or {}
            detail = f"{first.get('message') or ''} {first.get('details') or ''}".strip() or detail
        kind = classify_error(out + ' ' + detail)
        explanations = {'permission': '店铺调用权限不足，请核对开白。', 'network': '店铺信息网络调用未完成。',
                        'tls-runtime-file-missing': '京麦 CLI 初始化 TLS 时缺少本地文件，请运行 doctor-cli。',
                        'local-execution-permission': '宿主未允许本机运行所需系统操作，请核对本机执行权限。',
                        'auth_missing': '本 Profile 尚无可用授权。', 'auth_expired': '本 Profile 授权需要重新连接。'}
        raise VerifyError(kind, explanations.get(kind, '官方店铺身份核验未成功，请保留当前阶段继续核对。'))
    payload = data.get("data") or {}
    shop = payload.get("shopBaseInfo") or {}
    base = payload.get("venderBaseInfo") or {}
    vender_id = str(payload.get("venderId") or "")
    if not vender_id.isdigit() or not shop.get("shopName"):
        raise VerifyError("identity_unavailable", "venderinfo 缺少明确 venderId 或店名，不能用 shopId 代替。")
    return {
        "shopName": shop.get("shopName") or "",
        "venderId": vender_id,
        "shopId": str(shop.get("shopId") or ""),
        "companyName": base.get("companyName") or "",
        "status": shop.get("status"),
        "venderStatus": base.get("venderStatus"),
    }


# ---------------------------------------------------------------- 店铺登记

def _legacy_paths(extra=()):
    paths = [Path(p) for p in extra]
    skill_app = Path(__file__).resolve().parent / "shops.json"
    paths.append(skill_app)
    paths.append(user_home() / ".joycode" / "skills" / "jingmai-cli-linker" / "app" / "shops.json")
    seen, out = set(), []
    for p in paths:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def load_registry(legacy_extra=()) -> dict:
    path = registry_path()
    reg = read_json(path)
    if isinstance(reg, dict) and isinstance(reg.get("profiles"), dict):
        return reg
    reg = {"version": REGISTRY_VERSION, "profiles": {}}
    migrated = []
    for legacy in _legacy_paths(legacy_extra):
        old = read_json(legacy)
        if not isinstance(old, dict):
            continue
        for name, meta in (old.get("profiles") or {}).items():
            if name not in reg["profiles"] and isinstance(meta, dict):
                reg["profiles"][name] = {
                    k: v for k, v in meta.items()
                    if k in ("shopName", "venderId", "shopId", "companyName", "linkedAt", "lastVerifiedAt")
                }
        migrated.append(str(legacy))
    if migrated:
        reg["migratedFrom"] = migrated
        reg["migratedAt"] = int(time.time() * 1000)
        write_json(path, reg)
    return reg


def save_registry(reg: dict) -> None:
    reg["version"] = REGISTRY_VERSION
    write_json(registry_path(), reg)


def update_registry(profile: str, identity: dict, *, status: str = "ok", extra=None) -> None:
    assert_profile_proof(profile, identity)
    reg = load_registry()
    entry = reg["profiles"].setdefault(profile, {})
    entry["shopName"] = identity.get("shopName") or entry.get("shopName", "")
    entry["venderId"] = str(identity.get("venderId") or entry.get("venderId", ""))
    entry["shopId"] = str(identity.get("shopId") or entry.get("shopId", ""))
    entry["companyName"] = identity.get("companyName") or entry.get("companyName", "")
    entry["lastVerifiedAt"] = int(time.time() * 1000)
    entry.setdefault("linkedAt", entry["lastVerifiedAt"])
    entry["status"] = status
    entry.pop("errorKind", None)
    if extra:
        entry.update(extra)
    save_registry(reg)


def list_disk_profiles():
    from heideng_merchant import require_local
    d = require_local(profiles_dir(), parents=True)
    return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []


def build_view(reg=None) -> dict:
    """登记 + 本地 Profile 文件提示的合并视图。key=profile 名。"""
    reg = reg if reg is not None else load_registry()
    disk = set(list_disk_profiles())
    view = {}
    proofs=_proof_data().get('profiles',{})
    for name, meta in (reg.get("profiles") or {}).items():
        e = dict(meta)
        e["hasProfile"] = name in disk
        e["source"] = "registry"
        view[name] = e
    for name in disk:
        local = read_json(profiles_dir() / f"{name}.json", {}) or {}
        e = view.setdefault(name, {"hasProfile": True, "source": "local"})
        e["hasProfile"] = True
        if not e.get("shopName") and local.get("shop_name"):
            e["shopName"] = local["shop_name"]
        if not e.get("venderId") and local.get("vender_id"):
            e["venderId"] = str(local["vender_id"])
    aliases = read_json(linker_home() / 'confirmed-shop-aliases.json', {}) or {}
    for name, e in view.items():
        e['authRejected'] = proofs.get(name, {}).get('status') == 'rejected'
        key = (str(e.get('shopId') or ''), str(e.get('venderId') or ''))
        confirmed = [alias for alias, identity in aliases.items()
                     if key == (identity['shopId'], identity['venderId'])]
        e['aliases'] = sorted(set(e.get('aliases') or []) | set(confirmed))
    return view


def remember_confirmed_alias(shop, alias):
    """Record the merchant's nickname after resolving the official target live."""
    from heideng_merchant.safety import atomic_json, read_json as read_state
    from heideng_merchant.state import FileLock

    alias = alias.strip()
    if not norm(alias) or alias.isdecimal() or len(alias) > 80 or any(ord(c) < 32 for c in alias):
        raise ValueError('需要有效的店铺简称')
    result = resolve(shop)
    if result['status'] != 'ready':
        return result
    identity = {key: str(result.get(key) or '') for key in ('shopId', 'venderId')}
    if not all(value.isdecimal() for value in identity.values()) or shop not in (result['shopName'], identity['venderId']):
        raise ValueError('记录简称需要商家已确认的官方店名或 venderId')
    path = linker_home() / 'confirmed-shop-aliases.json'
    with FileLock(path.with_suffix('.lock')):
        for entry in build_view().values():
            if norm(alias) in {norm(name) for name in _entry_names(entry) if name} and (
                    str(entry.get('venderId') or '') != identity['venderId'] or
                    entry.get('shopId') and str(entry['shopId']) != identity['shopId']):
                return _result('ambiguous', query=alias, message='此简称与另一家已登记店铺同名，请选能区分两店的叫法。')
        aliases = read_state(path, {})
        for known, target in aliases.items():
            if norm(known) == norm(alias) and target != identity:
                return _result('ambiguous', query=alias, message='此简称已绑定其他店，请选能区分两店的叫法。')
        aliases[alias] = identity
        atomic_json(path, aliases)
    return {**result, 'merchantAlias': alias}


def _group_key(name: str, e: dict) -> str:
    if e.get("aliasOf"):
        return "alias:" + str(e["aliasOf"])
    if e.get("venderId"):
        return "v:" + str(e["venderId"])
    if e.get("shopName"):
        return "n:" + norm(e["shopName"])
    return "p:" + name


def _entry_names(e: dict):
    return [e.get("shopName", "")] + list(e.get("aliases") or [])


def match_groups(view: dict, query: str):
    """返回匹配到的店铺分组列表；每组 = {'key','profiles':[...],'entry'}。"""
    q = (query or "").strip()
    hits = {}
    is_id = q.isdigit()
    exact = {}
    loose = {}
    for name, e in view.items():
        if e.get('authRejected'):continue
        if is_id:
            if q in (str(e.get("venderId") or ""), str(e.get("shopId") or "")):
                exact[name] = e
            continue
        nq = norm(q)
        names = [norm(n) for n in _entry_names(e) if n]
        if nq and nq in names:
            exact[name] = e
        elif name_matches(q, _entry_names(e)):
            loose[name] = e
    chosen = exact or loose
    # 把 aliasOf 的 Profile 并入主 Profile 所在分组
    groups = {}
    for name, e in chosen.items():
        target = e.get("aliasOf") if e.get("aliasOf") in view else name
        base = view.get(target, e)
        key = _group_key(target, base)
        g = groups.setdefault(key, {"key": key, "profiles": [], "entry": base})
        if name not in g["profiles"]:
            g["profiles"].append(name)
    # 把同店铺的其他 Profile（同 venderId）也并入分组，便于备选
    for g in groups.values():
        for name, e in view.items():
            if e.get('authRejected'):continue
            if name not in g["profiles"] and _group_key(name, e) == g["key"]:
                g["profiles"].append(name)
            elif e.get("aliasOf") in g["profiles"] and name not in g["profiles"]:
                g["profiles"].append(name)
    return list(groups.values())


def order_profiles(view: dict, names):
    def rank(n):
        e = view.get(n, {})
        return (
            0 if e.get("primary") else 1,
            1 if e.get("aliasOf") else 0,
            0 if e.get("hasProfile") else 1,
            0 if PROFILE_RE.match(n) else 1,
            -int(e.get("lastVerifiedAt") or 0),
            -len(n),  # 平局时取名称更完整（更具体）的 Profile
            n,
        )
    return sorted(names, key=rank)


def _result(status, **kw):
    base = {"ok": status == "ready", "status": status}
    base.update(kw)
    return base


def _public(profile, identity, entry=None):
    entry = entry or {}
    return {
        "profile": profile,
        "venderId": str(identity.get("venderId") or entry.get("venderId") or ""),
        "shopId": str(identity.get("shopId") or entry.get("shopId") or ""),
        "shopName": identity.get("shopName") or entry.get("shopName") or "",
        "companyName": identity.get("companyName") or entry.get("companyName") or "",
        "lastVerifiedAt": int(entry.get("lastVerifiedAt") or 0),
        "browserProfileDir": entry.get("browserProfileDir") or "",
    }


def scan_profiles(profiles, verify=verify_profile, workers: int = 6):
    """并行实时只读校验；返回 {profile: {'identity':..} | {'error':kind,'message':..}}。"""
    results = {}

    def one(name):
        try:
            identity = verify(name)
            assert_profile_proof(name, identity)
            return name, {"identity": identity}
        except VerifyError as exc:
            return name, {"error": exc.kind, "message": exc.message}
        except Exception as exc:  # pragma: no cover - 防御
            return name, {"error": "other", "message": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for name, res in pool.map(one, list(profiles)):
            results[name] = res
    return results


def record_scan(results: dict) -> None:
    reg = load_registry()
    now = int(time.time() * 1000)
    for name, res in results.items():
        entry = reg["profiles"].setdefault(name, {})
        if "identity" in res:
            ident = res["identity"]
            entry["shopName"] = ident.get("shopName") or entry.get("shopName", "")
            entry["venderId"] = str(ident.get("venderId") or entry.get("venderId", ""))
            entry["shopId"] = str(ident.get("shopId") or entry.get("shopId", ""))
            entry["companyName"] = ident.get("companyName") or entry.get("companyName", "")
            entry["lastVerifiedAt"] = now
            entry["status"] = "ok"
            entry.pop("errorKind", None)
        else:
            entry["status"] = "error"
            entry["errorKind"] = res.get("error", "other")
    save_registry(reg)


def _only_unconnected_attempts(group, view, query, pending, proofs, verify):
    for name in group['profiles']:
        e = view[name]
        if (not PROFILE_RE.fullmatch(name) or name == 'default' or not e.get('hasProfile') or
                e.get('venderId') or e.get('shopId') or e.get('lastVerifiedAt') or
                norm(e.get('shopName', '')) != norm(query)):
            return False
        proof = proofs.get(name, {})
        ended_before_oauth = (pending.get('profile') == name and pending.get('processRunning') is False
                              and pending.get('outcome') in ('login_timeout', 'oauth_not_opened')
                              and (not proof or proof.get('jobId') == pending.get('jobId')))
        if (proof.get('nativeCompleted') or proof.get('slotVerified') or
                ((pending.get('profile') == name or proof) and not ended_before_oauth)):
            return False
        try:
            verify(name)
        except VerifyError as exc:
            if exc.kind == 'auth_missing':
                continue
        return False
    return True


def resolve(query: str, verify=verify_profile, live_scan: bool = True) -> dict:
    q = (query or "").strip()
    if not q:
        return _result("error", error="缺少店名或店铺 ID", query=q)
    view = build_view()
    groups = match_groups(view, q)
    if not groups and live_scan:
        names = [n for n in view if view[n].get("hasProfile") and not view[n].get("aliasOf") and not view[n].get('authRejected')]
        record_scan(scan_profiles(names, verify))
        view = build_view()
        groups = match_groups(view, q)
    if not groups:
        return _result(
            "needs_auth", query=q, reason="no_profile",
            suggestedProfile=suggest_profile_name(q, view.keys()),
            venderId=q if q.isdigit() else "",
            message="本机没有这家店的授权记录，需要先授权。",
        )
    inactive = []
    if len(groups) > 1 and live_scan and not q.isdigit():
        # A failed first connection may leave an empty profile alongside a registered
        # shop of the exact same name. Only discount it on fresh, definitive evidence.
        registered = [g for g in groups if g['entry'].get('venderId') and g['entry'].get('shopId')
                      and norm(g['entry'].get('shopName', '')) == norm(q)]
        if len(registered) == 1:
            pending = load_pending()
            proofs = _proof_data()['profiles']
            remaining = []
            for g in groups:
                if g is registered[0] or not _only_unconnected_attempts(g, view, q, pending, proofs, verify):
                    remaining.append(g)
                else:
                    inactive.extend(g['profiles'])
            groups = remaining
    if len(groups) > 1:
        cands = []
        for g in groups:
            names = order_profiles(view, g["profiles"])
            e = view.get(names[0], {})
            cands.append({
                "profile": names[0], "shopName": e.get("shopName", ""),
                "venderId": str(e.get("venderId") or ""),
                "identityState": "registered" if e.get("shopId") and e.get("venderId") else "unverified",
            })
        has_attempts = any(item['identityState'] == 'unverified' for item in cands)
        return _result("ambiguous", query=q, candidates=cands,
                       message=("存在同名待核对记录，请先查原连接任务，或按已确认的 venderId 定位店铺。"
                                if has_attempts else "匹配到多家店铺，请给出更完整的店名或 venderId。"))
    group = groups[0]
    names = order_profiles(view, group["profiles"])
    last_err = None
    for name in names:
        e = view.get(name, {})
        if not e.get("hasProfile") or not PROFILE_RE.match(name) or name == 'default':
            continue
        try:
            ident = verify(name)
            assert_profile_proof(name, ident)
        except VerifyError as exc:
            last_err = (name, exc)
            continue
        known_names = [ident.get("shopName", "")] + _entry_names(e) + _entry_names(group["entry"])
        known_vid = str(e.get("venderId") or "")
        if q.isdigit():
            ok = q in (ident.get("venderId", ""), ident.get("shopId", ""))
        else:
            ok = name_matches(q, known_names)
        if known_vid and ident.get("venderId") and known_vid != ident["venderId"]:
            ok = False
        if e.get("shopId") and str(e['shopId']) != str(ident.get('shopId') or ''):
            ok = False
        if not ok:
            return _result(
                "mismatch", query=q, profile=name,
                expected={"shopName": e.get("shopName", ""), "venderId": known_vid},
                actual={"shopName": ident.get("shopName", ""), "venderId": ident.get("venderId", "")},
                message="Profile 对应的实际店铺与要找的店铺不一致，不能使用。",
            )
        update_registry(name, ident)
        entry = load_registry()["profiles"].get(name, {})
        out = _result("ready", **_public(name, ident, entry))
        out["browserShortcut"] = entry.get("browserShortcut", "")
        if inactive:
            out["unconnectedAttempts"] = inactive
        return out
    if last_err:
        name, exc = last_err
        if exc.kind == "permission":
            return _result("error", query=q, profile=name, errorKind="permission",
                           error=exc.message, hint=permission_hint())
        if exc.kind not in ('auth_missing', 'auth_expired'):
            return _result("error", query=q, profile=name, errorKind=exc.kind, error=exc.message)
        e = view.get(name, {})
        return _result(
            "needs_auth", query=q, reason=exc.kind, profile=name,
            venderId=str(e.get("venderId") or (q if q.isdigit() else "")),
            shopName=e.get("shopName", ""), message=f"授权不可用（{exc.kind}），需要重新授权。",
        )
    # 有记录但没有可用的 Profile 文件
    e = view.get(names[0], {})
    return _result(
        "needs_auth", query=q, reason="profile_missing",
        suggestedProfile=suggest_profile_name(e.get("shopName") or q, view.keys()),
        shopName=e.get("shopName", ""), venderId=str(e.get("venderId") or ""),
        message="登记里有这家店，但本机没有可用的 Profile，需要重新授权。",
    )


# ---------------------------------------------------------------- audit

def audit(verify=verify_profile, apply_aliases: bool = True) -> dict:
    names = list_disk_profiles()
    results = scan_profiles(names, verify)
    record_scan(results)
    reg = load_registry()
    items, by_vender = [], {}
    for name in names:
        res = results[name]
        legal = bool(PROFILE_RE.match(name)) and name != "default"
        item = {"profile": name, "legalName": legal, "usable": "identity" in res}
        if "identity" in res:
            ident = res["identity"]
            item.update({k: ident.get(k, "") for k in ("shopName", "venderId", "shopId", "companyName")})
            by_vender.setdefault(item["venderId"], []).append(name)
        else:
            item.update({"errorKind": res["error"], "error": res["message"]})
            e = reg["profiles"].get(name, {})
            item["shopName"] = e.get("shopName", "")
            item["venderId"] = str(e.get("venderId") or "")
        items.append(item)
    duplicates, suggestions = [], []
    view = build_view(reg)
    for vid, profs in by_vender.items():
        if len(profs) < 2:
            continue
        ordered = order_profiles(
            {n: dict(view.get(n, {}), hasProfile=True) for n in profs}, profs)
        legal_first = sorted(ordered, key=lambda n: (0 if PROFILE_RE.match(n) else 1))
        primary = next((n for n in ordered if view.get(n, {}).get("primary")), legal_first[0])
        others = [n for n in profs if n != primary]
        duplicates.append({
            "venderId": vid, "shopName": next((i["shopName"] for i in items if i["profile"] == primary), ""),
            "profiles": profs, "suggestedPrimary": primary, "suggestedAliases": others,
        })
        suggestions.append(f"重复店铺 {vid}：主 Profile 用 {primary}，{', '.join(others)} 记为别名（待你确认后再决定是否删除）。")
        if apply_aliases:
            for n in others:
                reg["profiles"].setdefault(n, {})["aliasOf"] = primary
            reg["profiles"].setdefault(primary, {})["primary"] = True
    if apply_aliases:
        save_registry(reg)
    for it in items:
        if not it["legalName"]:
            suggestions.append(f"Profile「{it['profile']}」名称不合法，命令行难以传参：建议为该店重新授权成新 Profile，旧的待确认后删除。")
        if not it["usable"]:
            kind = it.get("errorKind")
            tip = {
                "auth_missing": "缺少授权配置，需重新授权",
                "auth_expired": "授权已失效，需重新授权",
                "permission": "权限不足，请核对是否已开白",
                "network": "网络异常，稍后重试",
            }.get(kind, "调用失败，需排查")
            suggestions.append(f"Profile「{it['profile']}」不可用：{tip}。")
    usable = sum(1 for i in items if i["usable"])
    return {
        "ok": True, "total": len(items), "usable": usable, "unusable": len(items) - usable,
        "profiles": items, "duplicates": duplicates, "suggestions": suggestions,
        "note": "audit 只读平台，只更新本机登记表；未删除任何 Profile 或凭据。",
    }


# ---------------------------------------------------------------- 专用浏览器

def desktop_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return user_home() / "Desktop"


def _desktop_browser(channel):
    """Locate the recorded browser channel without choosing another profile."""
    if channel not in ('chrome', 'msedge', 'chromium'):
        return None
    if channel == 'chromium':
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
        return executable if executable.is_file() else None
    if sys.platform == 'darwin':
        import pwd
        name = {'chrome': 'Google Chrome', 'msedge': 'Microsoft Edge'}[channel]
        local_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        roots = [Path('/Applications'), local_home / 'Applications']
        candidates = [root / f'{name}.app' / 'Contents' / 'MacOS' / name for root in roots]
    elif os.name == 'nt':
        import winreg
        filename, relative = {
            'chrome': ('chrome.exe', 'Google/Chrome/Application/chrome.exe'),
            'msedge': ('msedge.exe', 'Microsoft/Edge/Application/msedge.exe'),
        }[channel]
        candidates = []
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key_path = rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{filename}'
                with winreg.OpenKey(hive, key_path) as key:
                    candidates.append(Path(str(winreg.QueryValueEx(key, '')[0]).strip('"')))
            except OSError:
                continue
        roots = [os.environ.get(key) for key in ('ProgramFiles', 'ProgramFiles(x86)', 'HEIDENG_HOST_LOCAL_APPDATA')]
        candidates.extend(Path(root) / relative for root in roots if root)
    else:
        return None
    return next((path for path in candidates if path.is_absolute() and path.is_file()), None)


def _merchant_desktop():
    if os.name == 'nt':
        host_folder = os.environ.get('HEIDENG_HOST_DESKTOP')
        if host_folder:
            return Path(host_folder)
        from heideng_merchant.mature_runtime import windows_known_folder
        return windows_known_folder(0x0010)
    if sys.platform == 'darwin':
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir) / 'Desktop'
    return None


def _write_browser_shortcut(path, command, marker):
    """Publish a link without replacing a file that Black Lamp did not create."""
    from heideng_merchant.safety import is_linked
    if is_linked(path) or path.exists() and not path.is_file():
        raise FileExistsError(path)
    if os.name == 'nt':
        from heideng_merchant.windows_shortcut import prepare_link
        existing = path.stat() if path.exists() else None
        with tempfile.TemporaryDirectory(dir=path.parent, prefix='.heideng-shortcut-') as directory:
            stage = Path(directory) / 'stage.lnk'
            changed = prepare_link(path if existing else None, stage, command[0],
                                   subprocess.list2cmdline(command[1:]), marker)
            if existing:
                current = path.stat()
                if is_linked(path) or not os.path.samestat(existing, current) or (
                        current.st_mtime_ns, current.st_size) != (existing.st_mtime_ns, existing.st_size):
                    raise FileExistsError(path)
            if not changed:
                return 'existing'
            if existing:
                stage.replace(path)
            else:
                # On Windows rename refuses to replace a file created concurrently.
                stage.rename(path)
        return 'created'

    script = f'#!/bin/sh\n# {marker}\nexec {shlex.join(command)}\n'.encode('utf-8')
    exists = path.exists()
    if exists:
        with path.open('rb') as old:
            if old.readline(100) != b'#!/bin/sh\n' or old.readline(100).rstrip() != f'# {marker}'.encode():
                raise FileExistsError(path)
            if old.read(len(script) + 1) == script.split(b'\n', 2)[2]:
                return 'existing'
    with tempfile.TemporaryDirectory(dir=path.parent, prefix='.heideng-shortcut-') as directory:
        staged = Path(directory) / 'stage.command'
        staged.write_bytes(script)
        staged.chmod(0o700)
        if exists:
            staged.replace(path)
        else:
            os.link(staged, path)
    return 'created'


def ensure_desktop_shortcut(profile, identity):
    """Create or refresh the shortcut for a live-verified merchant identity."""
    from heideng_merchant.host_connection_controller import WORKSPACE_URL
    from heideng_merchant.mature_runtime import merchant_profile_directory
    from heideng_merchant.safety import SafetyError
    from heideng_merchant.state import FileLock, merchant_home
    entry = load_registry()['profiles'].get(profile, {})
    vender_id = str(identity.get('venderId') or '')
    shop_id = str(identity.get('shopId') or '')
    shop_name = identity.get('shopName')
    if (not vender_id.isascii() or not vender_id.isdigit() or not isinstance(shop_name, str) or not shop_name
            or str(entry.get('venderId') or '') != vender_id or entry.get('shopName') != shop_name
            or str(entry.get('shopId') or '') != shop_id):
        return {'status': 'unavailable', 'reason': 'shop-identity-unverified'}
    try:
        desktop = _merchant_desktop()
        if desktop is None:
            reason = 'desktop-directory-unavailable' if os.name == 'nt' else 'desktop-platform-unsupported'
            return {'status': 'unavailable', 'reason': reason}
        directory = merchant_profile_directory(entry.get('browserProfileDir'))
        if not directory:
            return {'status': 'unavailable', 'reason': 'shop-browser-profile-unavailable'}
        executable = _desktop_browser(entry.get('browserChannel'))
        if not executable:
            return {'status': 'unavailable', 'reason': 'shop-browser-unavailable'}
        if not desktop.is_absolute() or not desktop.is_dir() or desktop.resolve().is_relative_to(merchant_home()):
            return {'status': 'unavailable', 'reason': 'desktop-directory-unavailable'}
        label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', shop_name)[:70].strip(' .') or '店铺'
        key = hashlib.sha256(f'{merchant_home()}\n{vender_id}\n{shop_id}'.encode()).hexdigest()[:16]
        marker = f'Heideng shop {key}'
        suffix = '.lnk' if os.name == 'nt' else '.command'
        command = [str(executable), f'--user-data-dir={directory}', '--profile-directory=Default',
                   '--no-first-run', '--new-window', WORKSPACE_URL]
        with FileLock(linker_home() / 'desktop-shortcuts.lock'):
            for name in (f'黑灯-{label}', f'黑灯-{label}-{key[:8]}'):
                path = desktop / (name + suffix)
                try:
                    status = _write_browser_shortcut(path, command, marker)
                except FileExistsError:
                    continue
                if not path.is_file() or not path.stat().st_size:
                    return {'status': 'unavailable', 'reason': 'desktop-shortcut-not-found'}
                if os.name == 'nt':
                    # The link was staged then renamed. Notify Explorer of its final path.
                    import ctypes
                    event = 0x00000002 if status == 'created' else 0x00002000  # SHCNE_CREATE / SHCNE_UPDATEITEM
                    ctypes.windll.shell32.SHChangeNotify(event, 0x0005, ctypes.c_wchar_p(str(path)), None)
                return {'status': status, 'path': str(path)}
        return {'status': 'unavailable', 'reason': 'desktop-shortcut-name-in-use'}
    except (OSError, RuntimeError, ValueError, ImportError, SafetyError, subprocess.TimeoutExpired) as exc:
        failure = {'status': 'unavailable', 'reason': 'desktop-shortcut-write-failed'}
        if hasattr(exc, 'hresult') and hasattr(exc, 'operation'):
            failure.update(operation=exc.operation, hresult=exc.hresult)
        return failure


def create_verified_desktop_shortcut(profile, shop_name):
    if profile == 'default' or not PROFILE_RE.fullmatch(profile):
        return {'ok': False, 'error': '需要已授权的店铺 Profile。'}
    entry = load_registry()['profiles'].get(profile, {})
    try:
        require_auth_slot(profile)
        identity = verify_profile(profile)
        assert_profile_proof(profile, identity)
    except VerifyError as exc:
        return {'ok': False, 'errorKind': exc.kind, 'error': exc.message}
    if shop_name != identity.get('shopName') and shop_name not in (entry.get('aliases') or []):
        return {'ok': False, 'error': '已授权店铺与请求店铺不一致。'}
    shortcut = ensure_desktop_shortcut(profile, identity)
    if shortcut.get('path'):
        return {'ok': True, **shortcut}
    return {'ok': False, **shortcut, 'error': '没有创建桌面快捷方式，请查看具体状态。'}


def shortcut_dirs():
    dirs = []
    extra = os.environ.get("JINGMAI_BROWSER_DIRS")
    if extra:
        dirs.extend(Path(p) for p in extra.split(os.pathsep) if p)
    d = desktop_dir()
    dirs += [d / "京麦店铺浏览器", d]
    if os.environ.get("PUBLIC"):
        dirs.append(Path(os.environ["PUBLIC"]) / "Desktop")
    return [x for x in dirs if x.exists()]


def find_shop_shortcut(names, registry_hint: str = ""):
    """按店名/别名找 京麦-店铺名.lnk（排除 京麦CLI-*）。返回 Path 或 None。"""
    if registry_hint and Path(registry_hint).exists():
        return Path(registry_hint)
    cands = []
    for d in shortcut_dirs():
        for p in d.glob("京麦-*.lnk"):
            cands.append(p)
    wanted = [n for n in names if n]
    for n in wanted:
        for p in cands:
            if p.stem == f"京麦-{n}":
                return p
    hits = []
    for p in cands:
        label = p.stem[len("京麦-"):]
        if any(norm(label) == norm(n) or (len(norm(n)) >= 2 and norm(n) in norm(label)) or
               (len(norm(label)) >= 3 and norm(label) in norm(n)) for n in wanted):
            hits.append(p)
    return hits[0] if len(hits) == 1 else None


def read_shortcut(path: Path) -> dict:
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            lnk = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
            return {"TargetPath": lnk.TargetPath, "Arguments": lnk.Arguments,
                    "WorkingDirectory": lnk.WorkingDirectory, "IconLocation": lnk.IconLocation}
        finally:
            pythoncom.CoUninitialize()
    except ImportError:
        pass
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$l=(New-Object -ComObject WScript.Shell).CreateShortcut($env:JM_LNK);"
        "@{TargetPath=$l.TargetPath;Arguments=$l.Arguments;WorkingDirectory=$l.WorkingDirectory;"
        "IconLocation=$l.IconLocation}|ConvertTo-Json -Compress"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, env=dict(os.environ, JM_LNK=str(path)),
        creationflags=CREATE_NO_WINDOW, timeout=30,
    ).stdout
    return json.loads(decode_bytes(out).strip() or "{}")


def browser_command(info: dict, url: str):
    """由 lnk 信息拼出『专用浏览器打开 url』的命令行（沿用其 user-data-dir）。"""
    target = str(info.get("TargetPath") or "")
    args = str(info.get("Arguments") or "")
    if not target:
        return None
    udd = re.search(r'--user-data-dir=(?:"([^"]+)"|(\S+))', args)
    pd = re.search(r'--profile-directory=(?:"([^"]+)"|(\S+))', args)
    cmd = [target]
    if udd:
        cmd.append("--user-data-dir=" + (udd.group(1) or udd.group(2)))
    cmd.append("--profile-directory=" + ((pd.group(1) or pd.group(2)) if pd else "Default"))
    cmd += ["--no-first-run", "--new-window", url]
    return cmd


def quote_args(args) -> str:
    """把参数列表拼成 lnk 的 Arguments：--k=v 的值含空格时整体加引号，URL 加引号。"""
    out = []
    for a in args:
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            out.append(f'{k}="{v}"' if (" " in v or not v) else a)
        elif a.startswith("--"):
            out.append(a)
        else:
            out.append(f'"{a}"')
    return " ".join(out)

def open_auth_url(url: str, names, registry_hint: str = "",
                  spawn=subprocess.Popen, opener=None, no_open: bool = False) -> dict:
    """优先用店铺专用浏览器打开；找不到则用系统默认浏览器新窗口。不读写 Cookie。"""
    if no_open:
        return {"method": "none", "url": url}
    lnk = None
    try:
        lnk = find_shop_shortcut(names, registry_hint)
    except Exception:
        lnk = None
    if lnk:
        try:
            cmd = browser_command(read_shortcut(lnk), url)
            if cmd:
                spawn(cmd, close_fds=True)
                return {"method": "shop_browser", "shortcut": lnk.name, "shortcutPath": str(lnk)}
        except Exception as exc:
            note = f"专用浏览器启动失败：{exc}"
        else:
            note = ""
    else:
        note = "没有找到该店专用浏览器快捷方式"
    if opener is None:
        import webbrowser
        opener = lambda u: webbrowser.open(u, new=1)
    try:
        opened = bool(opener(url))
    except Exception:
        opened = False
    return {"method": "default_browser" if opened else "manual", "note": note, "url": url,
            "hint": "已用系统默认浏览器打开授权页。请确认浏览器里登录的就是目标店铺的京麦账号；登录了别的店会被身份核验拦下。"}


# ---------------------------------------------------------------- 环境体检

def doctor(policy=None) -> dict:
    checks, actions = [], []

    def add(name, ok, detail="", action=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok and action:
            actions.append(action)

    add("python", sys.version_info >= (3, 8), sys.version.split()[0], "安装 Python 3.8+")
    if os.name == 'nt':
        try:
            import win32com.client  # noqa: F401
            add("pywin32", True, "可读取旧版 Windows 快捷方式")
        except ImportError:
            add("pywin32", False, "可选组件；本版店铺入口使用系统 Shell Link")
    exe = find_jdo()
    if not exe:
        add("jdo-cli", False, "未找到",
            "运行 python scripts/linker.py doctor --install-jdo 从京麦官方通道安装 jdo-cli；"
            "或使用商家状态内已校验的官方 CLI")
    else:
        ver = ""
        try:
            code, out = run_jdo(["status"], timeout=30)
            payload = extract_json(out) or {}
            if code == 0 and payload.get('ok') is True:
                ver = payload.get("cliVersion", "")
        except Exception:
            pass
        info = cli_version_info(ver, policy)
        add("jdo-cli", True, f"{exe} {ver}".strip())
        checks[-1].update({"version": ver, **info})
        add("官方 CLI 状态回执", bool(ver), "已读取版本" if ver else "未取得可核对的状态回执",
            "使用商家入口 doctor-cli 单独检查本机启动与京东公开 HTTPS")
        if info.get("needsUpdate"):
            add("jdo-cli 版本", False, info["note"], info["action"])
        add("jdo-cli 已初始化", config_path().exists(), str(config_path()),
            "运行 python scripts/linker.py doctor --init 完成初始化")
    pid, name = port_owner(CALLBACK_PORT)
    add("回调端口 9001", pid is None,
        "空闲" if pid is None else f"被 {name or '未知进程'}(PID {pid}) 占用",
        "9001 被占用：先 python scripts/linker.py cancel；仍占用则关闭该进程后重试")
    try:
        linker_home().mkdir(parents=True, exist_ok=True)
        add("登记目录可写", True, str(linker_home()))
    except Exception as exc:
        add("登记目录可写", False, str(exc), "检查用户目录写权限，或设置 JINGMAI_LINKER_HOME")
    return {"ok": all(c["ok"] for c in checks if c["name"] != "pywin32"), "checks": checks, "nextActions": actions}


def init_jdo() -> dict:
    """首次初始化 jdo-cli 目录与配置，不创建 default Profile，并显式使用线上 endpoint。"""
    if config_path().exists():
        return {"ok": True, "message": "jdo-cli 已初始化"}
    for sub in ("profiles", "cache", "logs", "credentials", "skills"):
        (jdo_home() / sub).mkdir(parents=True, exist_ok=True)
    code, out = run_jdo(["--endpoint", DEFAULT_ENDPOINT, "init", "--skip-network"], timeout=60)
    # 官方 init 无 --profile 会生成 default Profile；本 Skill 禁止使用，立即清理空壳并清空默认值
    stub = profiles_dir() / "default.json"
    data = read_json(stub, None)
    if isinstance(data, dict) and not data.get("vender_id") and not data.get("xid"):
        try:
            stub.unlink()
        except OSError:
            pass
    cfg = read_json(config_path(), {}) or {}
    if cfg.get("default_profile") == "default":
        cfg["default_profile"] = ""
        write_json(config_path(), cfg)
    return {"ok": code == 0 and config_path().exists(),
            "message": "已初始化" if code == 0 else out.strip()[-200:]}

# ---------------------------------------------------------------- 官方 CLI 版本与安装

def parse_version(text: str):
    """'0.3.7' -> (0,3,7)；无法解析返回 None。"""
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def fetch_policy(timeout: int = 20, opener=None) -> dict:
    """匿名读取京麦官方版本策略。失败抛 InstallError。"""
    import urllib.request
    opener = opener or (lambda u, t: urllib.request.urlopen(u, timeout=t).read())
    try:
        data = json.loads(opener(VERSION_POLICY_URL, timeout).decode("utf-8"))
    except Exception as exc:
        raise InstallError("policy_unreachable", str(exc)[:200])
    if not isinstance(data, dict):
        raise InstallError("policy_invalid", "官方版本信息格式异常")
    return data


def policy_artifact(policy: dict):
    entry = ((policy.get("artifacts") or {}).get("binaries") or {}).get("windows-x64")
    if not isinstance(entry, dict) or not entry.get("path") or not entry.get("sha256"):
        raise InstallError("no_artifact", "官方版本信息里没有 Windows 安装包")
    return entry


def cli_version_info(current: str, policy=None) -> dict:
    """比较当前版本与官方最新/下限。只有低于下限才 needsUpdate；高于下限但非最新只是信息。"""
    info = {"current": current, "latest": "", "minSupported": "", "needsUpdate": False, "behindLatest": False}
    if policy is None:
        try:
            policy = fetch_policy(timeout=6)
        except InstallError:
            info["note"] = "无法连接京麦官方通道，未能核对最新版本（不影响使用）"
            return info
    latest = policy.get("latestVersion") or policy.get("stableVersion") or ""
    minimum = policy.get("minSupportedVersion") or ""
    info.update({"latest": latest, "minSupported": minimum})
    cur, low, top = parse_version(current), parse_version(minimum), parse_version(latest)
    if cur and low and cur < low:
        info["needsUpdate"] = True
        info["note"] = f"当前 jdo-cli {current} 低于官方要求的最低版本 {minimum}"
        info["action"] = "运行 jdo-cli update self 升级（不会影响已有授权和 Profile）"
    elif cur and top and cur < top:
        info["behindLatest"] = True
        info["note"] = f"官方最新是 {latest}，当前 {current}，可正常使用，无需操作"
    elif cur:
        info["note"] = "已是官方最新版本"
    return info


class InstallError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


HUMAN = {
    "unsupported_platform": ("这台电脑不是 Windows 64 位，本工具暂不支持自动安装京麦 CLI。",
                             "目前无法使用京麦授权功能。",
                             "请换一台 Windows 电脑，或联系负责人帮你安装。"),
    "policy_unreachable": ("没能连上京麦官方下载通道。",
                           "京麦 CLI 暂时没装上，还不能授权店铺。",
                           "请确认已连上公司网络（内网/VPN）后重新运行；仍不行就联系负责人。"),
    "policy_invalid": ("京麦官方下载通道返回的内容不对。",
                       "京麦 CLI 暂时没装上，还不能授权店铺。",
                       "稍后重试；仍不行请联系负责人。"),
    "no_artifact": ("京麦官方通道里没有找到适合这台电脑的安装包。",
                    "京麦 CLI 暂时没装上，还不能授权店铺。",
                    "请联系负责人确认官方是否已发布 Windows 版本。"),
    "download_failed": ("京麦 CLI 的安装包没有下载完整。",
                        "京麦 CLI 暂时没装上，还不能授权店铺。",
                        "请检查网络后重新运行；如果杀毒软件弹出拦截提示，请选择允许后再试。"),
    "verify_failed": ("下载到的安装包和官方信息对不上，为了安全已经停止，没有安装任何东西。",
                      "你的电脑没有被改动，京麦 CLI 还没装上。",
                      "请重新运行一次；多次都这样，说明网络被中途改动过，请联系负责人并换个网络再试。"),
    "extract_failed": ("安装包解压或写入失败，可能被杀毒软件拦截了。",
                       "已有的文件保持原样没有被破坏，但京麦 CLI 还没装上。",
                       "请把杀毒软件对 .jdo-cli 文件夹的拦截设为允许后重新运行，或联系负责人。"),
    "init_failed": ("京麦 CLI 已装好，但初始化没有完成。",
                    "还不能授权店铺。",
                    "请重新运行 doctor --init；仍不行请联系负责人。"),
}


def human_message(kind: str) -> dict:
    what, impact, nxt = HUMAN.get(kind, ("安装过程出了问题。", "京麦 CLI 暂时没装上。", "请重新运行；仍不行请联系负责人。"))
    return {"问题": what, "影响": impact, "下一步": nxt}


def _download(url: str, timeout: int, opener=None) -> bytes:
    import urllib.request
    opener = opener or (lambda u, t: urllib.request.urlopen(u, timeout=t).read())
    return opener(url, timeout)


def install_jdo(policy_opener=None, download_opener=None, platform_ok=None, home=None) -> dict:
    """Merchant-only verified official installation; mature init/auth is unchanged."""
    existing = find_jdo()
    if existing:
        return {"ok": True, "installed": False, "path": str(existing),
                "message": "已有京麦 CLI，未覆盖或降级。"}
    from heideng_merchant.official import OfficialClient
    from heideng_merchant.safety import SafetyError
    merchant = os.environ.get("HEIDENG_MERCHANT_HOME")
    if not merchant:
        return _install_fail("merchant_home_required")
    try:
        client = OfficialClient(Path(merchant))
        result = client.install()
        executable = client.executable()
        os.environ["JDO_CLI_PATH"] = str(executable)
        return {"ok": True, "installed": result.get("status") == "installed",
                "path": str(executable), "version": result.get("version", ""),
                "source": "京麦官方校验下载", "binaryVerified": True}
    except SafetyError as exc:
        return _install_fail(str(exc))


def _install_fail(kind: str, detail: str = "") -> dict:
    return {"ok": False, "status": "error", "errorKind": "install_" + kind, "message": human_message(kind),
            "detail": detail, "installed": False}
