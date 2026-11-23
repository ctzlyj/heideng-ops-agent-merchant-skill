"""WorkBuddy expert entry. The invite key is checked before every merchant command."""
from __future__ import annotations

import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


SKILL = Path(__file__).resolve().parents[1]
USAGE_URL = 'https://api.lts4ai.com/api/usage/token/'
MODELS_URL = 'https://api.lts4ai.com/v1/models'


class EligibilityError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_gateway(key, url):
    # Fixed first-party endpoint; authorization is never forwarded to a redirect.
    if url not in (USAGE_URL, MODELS_URL):
        raise EligibilityError('内测资格服务地址不匹配。')
    limit = 1024*1024 if url == MODELS_URL else 32768
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
            content = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise EligibilityError('中转站未确认内测 Key 当前可用，请运营方核对资格、到期时间和额度。') from None
        raise EligibilityError('中转站暂时无法验证内测资格，请稍后继续原任务。') from None
    except (OSError, HTTPException):
        raise EligibilityError('中转站暂时无法验证内测资格，请稍后继续原任务。') from None
    try:
        if len(content) > limit:
            raise ValueError()
        return json.loads(content)
    except (ValueError, UnicodeError):
        raise EligibilityError('中转站返回的资格信息无法核实。') from None


def token_usage(key):
    return read_gateway(key, USAGE_URL)


def active_models(key):
    return read_gateway(key, MODELS_URL)


def qualify(key, digests, *, lookup=token_usage, active=active_models, now=time.time):
    if not digests:
        raise EligibilityError('此包为开发预览，尚未配置受邀商家。')
    if (not isinstance(key, str) or not re.fullmatch(r'[!-~]{24,8192}', key)
            or hashlib.sha256(key.encode()).hexdigest() not in digests):
        raise EligibilityError('此 Key 未获本批内测资格。')
    response = lookup(key)
    info = response.get('data') if isinstance(response, dict) and response.get('code') is True else None
    if not isinstance(info, dict) or info.get('object') != 'token_usage':
        raise EligibilityError('中转站未确认该内测 Key。')
    expiry = info.get('expires_at')
    unlimited = info.get('unlimited_quota')
    balance = info.get('total_available')
    if type(expiry) is not int or expiry < 0 or type(unlimited) is not bool or type(balance) is not int:
        raise EligibilityError('中转站资格信息不完整，请联系内测运营方核对。')
    if expiry and expiry <= now():
        raise EligibilityError('内测 Key 已到期。')
    # The usage endpoint is also available for some inactive token states. Require
    # positive confirmation from the gateway's full TokenAuth path before any work.
    models = active(key)
    if (not isinstance(models, dict) or models.get('object') != 'list'
            or not isinstance(models.get('data'), list) or 'error' in models):
        raise EligibilityError('中转站未确认内测 Key 当前可用。')
    # Quota is an upstream ledger unit. Only zero/negative is comparable without conversion.
    if unlimited:
        return 'unbounded-key'
    return 'quota-exhausted' if balance <= 0 else None


def ask_key():
    from heideng_merchant.merchant_key_ui import _prompt_local_page, _prompt_native_window
    try:
        import tkinter as tk
    except ImportError:
        return _prompt_local_page(beta=True)[0]
    try:
        return _prompt_native_window(beta=True)[0]
    except tk.TclError:
        return _prompt_local_page(beta=True)[0]


def checked_core(skill):
    config = json.loads((skill/'expert-distribution.json').read_bytes())
    archive = skill/'resources/merchant.zip'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != config['coreSha256']:
        raise EligibilityError('专家内置程序未通过发布哈希核验。')
    return archive


def invoke(argv, *, skill=SKILL, home=None, lookup=token_usage, active=active_models, ask=ask_key, run=subprocess.run):
    from heideng_merchant.cli import build_parser
    from heideng_merchant.distribution import validate_archive, verify_install
    from heideng_merchant.merchant_key_store import forget_key, read_key, store_key
    from heideng_merchant.safety import clean_environment

    config = json.loads((skill/'expert-distribution.json').read_bytes())
    if not config['inviteDigests']:
        raise EligibilityError('此包为开发预览，尚未配置受邀商家。')
    state = (Path(home or Path.home())/'.heideng-wb-beta').resolve()
    vault = state/'membership'
    if argv == ['forget-key']:
        forget_key(vault)
        return {'status':'forgotten', 'businessExecuted':False}
    if not argv:
        argv = ['status']
    if argv[0].startswith('-') or argv[0] == 'key' or (argv[0] == 'update' and argv[1:2] != ['usage']):
        raise EligibilityError('请通过专家维护本机内测凭证和版本。')
    if argv != ['activate']:
        parsed = build_parser().parse_args(argv)
        if parsed.state is not None:
            raise EligibilityError('内测任务使用专家自己的商家状态。')
    saved = read_key(vault) if argv != ['activate'] else None
    key = saved or ask()
    if not key:
        raise EligibilityError('内测资格录入已取消。')
    blocked = qualify(key, config['inviteDigests'], lookup=lookup, active=active)
    if not saved:
        store_key(vault, key)
    if argv == ['activate']:
        return {'status':'eligible', 'newImagesAvailable':blocked is None, 'businessExecuted':False}
    env = clean_environment(state/'runtime-home')
    env['HEIDENG_MERCHANT_HOME'] = str(state)
    target = state/'program'/'heideng-ops-agent-merchant'
    installed = verify_install(target)
    if not installed.get('valid') or installed['receipt']['archiveSha256'] != config['coreSha256']:
        archive = checked_core(skill)
        _, files = validate_archive(archive)
        with tempfile.TemporaryDirectory(prefix='heideng-expert-install-') as tmp:
            source = Path(tmp)
            for name, content in files.items():
                path = source/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(content)
            result = run([sys.executable,'-I','-B',str(source/'install.py'),'--archive',str(archive),
                          '--sha256',config['coreSha256'],'--host','workbuddy','--skills-dir',str(target.parent),
                          '--state',str(state),'--with-runtime','--with-official','--no-auto-update'],env=env)
        if result.returncode:
            raise EligibilityError('专家初始化未完成；请核对安装回执后继续。')
        installed = verify_install(target)
        if not installed.get('valid') or installed['receipt']['archiveSha256'] != config['coreSha256']:
            raise EligibilityError('内测程序与专家发布清单不一致。')
    # Transient process-only injection; never use the host's personal/provider key.
    image_capabilities = {'materials','listing','photo-listing','matrix-listing','link-replica','images','image-refresh'}
    if parsed.command == 'run' and parsed.capability in image_capabilities:
        env['HEIDENG_MERCHANT_LTS4AI_API_KEY'] = key
    if blocked:
        env['HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED'] = blocked
    proc = run([sys.executable,'-I','-B',str(target/'scripts/merchant.py'),'--state',str(state),*argv],env=env)
    return proc.returncode


def main():
    try:
        archive = checked_core(SKILL)
    except (EligibilityError, ValueError, KeyError, OSError):
        print(json.dumps({'status':'blocked','message':'内测专家文件不完整，请重新取得本次专家副本。'},ensure_ascii=False))
        return 2
    sys.path.insert(0, str(archive))
    from heideng_merchant.safety import SafetyError
    try:
        result = invoke(sys.argv[1:])
        if isinstance(result, int):
            return result
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (EligibilityError, SafetyError) as error:
        print(json.dumps({'status':'blocked','message':str(error),'businessExecuted':False},ensure_ascii=False))
        return 2


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='backslashreplace')
    raise SystemExit(main())
