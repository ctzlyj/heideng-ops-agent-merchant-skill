"""Reusable merchant-owned browser controller for the mature HostBrowser actions.

Only page/session operations live here; shop identity, OAuth and authorization remain
in the mature connector. No cookie/storage/history/credential is read or exported.
"""
from __future__ import annotations
import json, os, re, sys, uuid
from pathlib import Path
from urllib.parse import urlsplit
from .state import FileLock

LOGIN_URL='https://passport.shop.jd.com/login/index.action'
WORKSPACE_URL='https://shop.jd.com/jdm/home'
CHANNELS=('chrome','msedge','chromium')

BROWSER_START_HINTS = {
    'browser_python_dependency': '当前连接进程无法加载 Playwright 或其本机依赖。请用商家隔离运行环境恢复连接。',
    'browser_driver_failed': 'Playwright Python 已加载，驱动进程未能启动。请核对当前 Python 架构与隔离环境中的 Playwright driver。',
    'browser_channel_missing': '所选浏览器通道未安装或其程序文件不可用。请核对该通道的本机安装位置。',
    'browser_host_permission': '当前宿主没有启动此浏览器所需的本机权限。请在允许启动浏览器的本机宿主复测 browser-check；保留原店铺资料。',
    'browser_profile_busy': '原商家专用浏览器资料正被其他进程占用。请回到持有该资料的原窗口或连接任务。',
    'browser_isolated_home_unavailable': '无法准备商家隔离环境的 AppData 目录，请核对本机商家状态目录的写入权限。',
    'browser_channel_launch_failed': '驱动可用，浏览器通道未能启动。请用 browser-check 在临时商家资料中复测所选通道。',
    'browser_cleanup_failed': '本机浏览器或驱动未能确认退出，请核对这次任务的临时窗口。',
}


class BrowserStartError(Exception):
    def __init__(self, kind):
        self.kind = kind
        self.hint = BROWSER_START_HINTS[kind]
        super().__init__(self.hint)


def prepare_isolated_browser_home():
    """Chrome on Windows needs the declared Local AppData folder before its driver can attach."""
    if sys.platform != 'win32':
        return
    from .safety import SafetyError, safe_join
    state = Path(os.environ.get('HEIDENG_MERCHANT_HOME') or '')
    home = state / 'runtime-home'
    if not state.is_absolute() or any(Path(os.environ.get(key) or '') != home for key in ('HOME', 'USERPROFILE')):
        return
    for key, relative in (('LOCALAPPDATA','runtime-home/AppData/Local'), ('APPDATA','runtime-home/AppData/Roaming')):
        # A host-supplied personal AppData or redirected path belongs to the host.
        if Path(os.environ.get(key) or '') != state / relative:
            continue
        try:
            safe_join(state, relative).mkdir(parents=True, exist_ok=True)
        except (OSError, SafetyError):
            raise BrowserStartError('browser_isolated_home_unavailable') from None


def startup_kind(exc, phase):
    # Provider output can contain command lines and profile paths. Only emit fixed diagnoses.
    message = str(exc).casefold()
    if (isinstance(exc, PermissionError) or 'operation not permitted' in message or 'permission denied' in message
            or 'access is denied' in message or ('bootstrap_check_in' in message and '1100' in message)
            or ('sandbox' in message and 'mach-' in message and ('deny' in message or 'denied' in message))):
        return 'browser_host_permission'
    if phase == 'driver':
        return 'browser_driver_failed'
    if any(text in message for text in ('singletonlock', 'processsingleton', 'user data directory is already in use')):
        return 'browser_profile_busy'
    if (isinstance(exc, FileNotFoundError) or any(text in message for text in
            ("executable doesn't exist", 'executable does not exist', 'executable not found'))
            or ('distribution' in message and 'not found' in message)):
        return 'browser_channel_missing'
    return 'browser_channel_launch_failed'


def check_local_browser(channel=None):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='heideng-browser-check-') as directory:
        controller = HostConnectionController(state=directory)
        failure = None
        try:
            controller._launch(channel, local_only=True)
            controller.page.goto('about:blank', wait_until='domcontentloaded')
            ready = controller.page.url == 'about:blank' and controller.page.evaluate('() => 2 + 2') == 4
            if not ready:
                raise BrowserStartError('browser_channel_launch_failed')
        except BrowserStartError as error:
            failure = error.kind
        except Exception as error:
            failure = startup_kind(error, 'channel')
        finally:
            try:
                controller._close()
            except Exception:
                failure = failure or 'browser_cleanup_failed'
        result = {'ok': failure is None, 'browserChannel': controller.channel or channel,
                  'merchantLoginStarted': False, 'businessExecuted': False}
        if failure:
            return {**result, 'status': 'blocked', 'stage': 'checking_browser_runtime',
                    'errorKind': failure, 'error': BROWSER_START_HINTS[failure]}
        return {**result, 'status':'browser-ready', 'page':'about:blank'}

def _public(value):
    return {'actions':['open_login','observe','open_oauth','confirm','close'],'loginUrl':LOGIN_URL,
            'merchantChoosesLoginMethod':True,'challenges':['login','qr','sms','captcha','account-risk-blocked','verification'],
            'oauthConfirmation':'Only current authorized scope; extra scope/cost/challenge requires merchant action',
            'profileRule':'merchant-owned state/browser-profiles only; no work browser or cookie export'}


def _page_text(page):
    return page.locator('body').inner_text(timeout=5000)[:12000]


def _trusted_shop_page(url):
    parsed=urlsplit(url)
    return parsed.scheme=='https' and parsed.hostname and (parsed.hostname=='shop.jd.com' or parsed.hostname.endswith('.shop.jd.com') or parsed.hostname=='jingmai.jd.com' or parsed.hostname.endswith('.jingmai.jd.com') or parsed.hostname=='passport.shop.jd.com')


def _identity(page):
    """Read only public identity DOM, never cookies or authorization codes."""
    for script in (
        """() => {
            const selectors = ['.shop-menu-accountV1__right-account-top-name', '#shop-base-name', '[data-shop-name]'];
            return selectors.flatMap(selector => Array.from(document.querySelectorAll(selector))
                .filter(element => element.getClientRects().length && getComputedStyle(element).visibility === 'visible')
                .map(element => element.innerText));
        }""",
        r"""() => {let t=document.body.innerText;let m=t.match(/(?:店铺名称|当前店铺)[:：]\s*([^\n]{2,80})/);return m&&m[1]}"""):
        try:
            result = page.evaluate(script)
        except Exception:
            continue
        for value in result if isinstance(result, list) else [result]:
            if not isinstance(value, str):
                continue
            name = value.strip()
            if (1 < len(name) < 80 and name not in ('京东-欢迎登录','京麦工作台-京东商家一站式工作台','客服','店铺','首页','消息','全部')
                    and not any(text in name for text in ('密码登录','短信登录','立即登录','开店'))):
                return {'shopName': name}
    return {}


def page_identity(page):
    """Only return visible official workspace identity and its explicitly named identifiers."""
    if page.is_closed() or not _trusted_shop_page(page.url) or urlsplit(page.url).hostname == 'passport.shop.jd.com':
        return {}
    url = page.url
    identity = _identity(page)
    if not identity:
        return {}
    try:
        ids = page.evaluate(r"""(name) => {
          const elems = [...document.querySelectorAll('.shop-menu-accountV1__right-account-top-name,#shop-base-name,[data-shop-name]')]
            .filter(el => el.getClientRects().length && getComputedStyle(el).visibility === 'visible'
                && el.innerText.trim() === name);
          if (!elems.length) return {};
          const text = document.body.innerText;
          const fields = {};
          for (const [key, attr, label] of [
            ['shopId','data-shop-id',/当前店铺(?:ID|编号)\s*[:：]\s*(\d+)\b/gi],
            ['venderId','data-vender-id',/当前(?:商家|商户)(?:ID|编号)\s*[:：]\s*(\d+)\b/gi]]) {
            const values = new Set(elems.map(el=>el.getAttribute(attr)).filter(v=>/^\d+$/.test(v)));
            for (const match of text.matchAll(label)) values.add(match[1]);
            if (values.size > 1) return {ambiguous:true};
            if (values.size === 1) fields[key] = [...values][0];
          }
          return fields;
        }""",identity['shopName'])
    except Exception:
        ids = {}
    if page.url != url or isinstance(ids,dict) and ids.get('ambiguous'):
        return {}
    if not isinstance(ids,dict):
        return identity
    return {**identity, **{k:v for k,v in ids.items() if k in ('shopId','venderId') and isinstance(v,str) and re.fullmatch('[0-9]+',v)}}


class HostConnectionController:
    def __init__(self,state=None,shop_identity=None,*,workspace_key=None):
        self.shop_identity=shop_identity or {}
        home=Path(state or os.environ['HEIDENG_MERCHANT_HOME']).resolve()
        import hashlib
        identity_key=workspace_key or str(self.shop_identity.get('venderId') or self.shop_identity.get('shopName') or 'pending-shop')
        self.home=home;self.root=home/'browser-controller'/hashlib.sha256(identity_key.encode()).hexdigest()[:16]
        self.root.mkdir(parents=True,exist_ok=True)
        self._state_path=self.root/'session.json'
        self._state=None
        self._playwright=None;self.context=None;self.page=None;self.context_id=None;self.channel=None;self.profile=None;self.oauth_confirm_handled=False
        self.oauth_identity=None;self.channel_reason=''

    def describe_contract(self):return _public(None)

    def _load(self):
        if self._state is not None:return self._state
        from .safety import read_json
        self._state=read_json(self._state_path,{})
        if self._state and set(self._state)!={'contextId','profileDir','browserChannel','shopIdentity'}:self._state=None
        return self._state

    def _launch(self,channel=None,*,local_only=False):
        if self.context is not None:return
        prepare_isolated_browser_home()
        if channel is not None and channel not in CHANNELS:
            raise ValueError('invalid-browser-channel')
        state=self._load()
        if channel and state and state.get('browserChannel') != channel:
            # Different Chromium products must not open each other's persistent profile.
            self.root=self.root/('channel-'+channel)
            self.root.mkdir(parents=True,exist_ok=True)
            self._state_path=self.root/'session.json'
            self._state=None
            state=self._load()
            if state and state.get('browserChannel') != channel:
                raise RuntimeError('recorded-browser-channel-mismatch')
        if state:
            if state.get('shopIdentity')!=self.shop_identity:raise RuntimeError('connection-profile-belongs-to-another-shop')
            self.context_id=state['contextId'];self.channel=state['browserChannel'];self.profile=Path(state['profileDir']);self.channel_reason='reused-shop-session'
        else:
            self.context_id='merchant-connection-'+uuid.uuid4().hex
            self.profile=self.home/'browser-profiles'/('connection-'+uuid.uuid4().hex[:12])
            self.channel=channel or self._default_channel()
            self.channel_reason='explicit-request' if channel else getattr(self,'_default_reason','system-default-https')
        from .safety import safe_join
        expected=self.home/'browser-profiles'
        if not self.profile.is_absolute() or self.profile == expected or not self.profile.is_relative_to(expected):
            raise RuntimeError('merchant-owned-profile-required')
        directory=safe_join(expected,self.profile.relative_to(expected).as_posix())
        try:
            directory.mkdir(parents=True,exist_ok=True)
        except PermissionError:
            raise BrowserStartError('browser_host_permission') from None
        try:
            from playwright.sync_api import sync_playwright
        except (ImportError, OSError):
            raise BrowserStartError('browser_python_dependency') from None
        try:
            self._playwright=sync_playwright().start()
        except Exception as error:
            raise BrowserStartError(startup_kind(error, 'driver')) from None
        try:
            self.context=self._playwright.chromium.launch_persistent_context(
                str(directory), channel=None if self.channel=='chromium' else self.channel,
                headless=False, accept_downloads=False, timeout=20000,
                offline=local_only, chromium_sandbox=True,
                args=['--no-first-run','--no-default-browser-check'])
        except Exception as error:
            try:
                self._playwright.stop()
            finally:
                self._playwright=None
            raise BrowserStartError(startup_kind(error, 'channel')) from None
        self.context.set_default_timeout(15000)
        pages=[page for page in self.context.pages if not page.is_closed()]
        self.page=next((page for page in pages if _trusted_shop_page(page.url) or
                        urlsplit(page.url).hostname == 'aq.jd.com'), None)
        if self.page is None:
            self.page=next((page for page in pages if page.url == 'about:blank'), None) or self.context.new_page()
        self._save()

    def _default_channel(self):
        if os.name!='nt':
            self._default_reason='supported-browser-default'
            return 'chrome'
        # Ask the shell for the HTTPS handler, including ProgIds registered per installation.
        try:
            import ctypes
            from ctypes import wintypes
            query = ctypes.WinDLL('shlwapi').AssocQueryStringW
            query.argtypes = [wintypes.DWORD,wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,
                              wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
            size = wintypes.DWORD(32768)
            output = ctypes.create_unicode_buffer(size.value)
            if query(0x1000,2,'https','open',output,ctypes.byref(size)) == 0:
                from ntpath import basename
                channel = {'chrome.exe':'chrome','msedge.exe':'msedge'}.get(basename(output.value).casefold())
                if channel:
                    return channel
        except (OSError, AttributeError):
            pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
                handler = str(winreg.QueryValueEx(key,'ProgId')[0]).casefold()
                if 'msedge' in handler or 'microsoftedge' in handler:return 'msedge'
                if 'chrome' in handler:return 'chrome'
        except OSError:pass
        self._default_reason='supported-browser-default'
        return 'chrome'

    def _save(self):
        from .safety import atomic_json
        atomic_json(self._state_path,{'contextId':self.context_id,'profileDir':str(self.profile.resolve()),'browserChannel':self.channel,'shopIdentity':self.shop_identity})

    def _result(self,extra=None):
        result={'ok':True,'contextId':self.context_id,'owned':True,'isolated':True,'verifiedReuse':True,'profileDir':str(self.profile.resolve()),'browserChannel':self.channel,'browserSelectionReason':self.channel_reason}
        if extra:result.update(extra)
        return result

    def _open_login(self,action):
        reused = bool(self._load())
        self._launch(action.get('browserChannel'))
        url=self.page.url
        if reused and url=='about:blank':
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            try:
                self.page.goto(WORKSPACE_URL, wait_until='domcontentloaded', timeout=10000)
            except PlaywrightTimeout:
                pass
            url=self.page.url
        if url=='about:blank' or (not _trusted_shop_page(url) and urlsplit(url).hostname!='aq.jd.com'):
            self.page.goto(LOGIN_URL,wait_until='domcontentloaded')
        # Do not select QR/password/SMS on the merchant's behalf.
        self.page.bring_to_front()
        return self._result()

    def _observe(self):
        if self.context is None:
            state=self._load()
            if not state:return {'ok':False,'error':'context-not-opened'}
            self._launch()
        url=self.page.url;host=(urlsplit(url).hostname or '').lower()
        if host=='aq.jd.com' and urlsplit(url).path.startswith('/certified'):
            return self._result({'loggedIn':False,'identity':{},'challenge':'account-risk-blocked','requiresUserAction':'请在京东商城 App 完成账号安全验证，再回到当前页面继续。'})
        # Do not replace the current pending OAuth page with an unrelated workspace tab.
        if host in {'passport.jd.com','open-oauth.jd.com'} and self.oauth_identity:
            return self._result({'loggedIn':True,'identity':self.oauth_identity,'challenge':''})
        pages=getattr(self.context,'pages',[])
        candidates=[self.page,*(p for p in reversed(pages if isinstance(pages,(list,tuple)) else []) if p is not self.page)]
        for page in candidates:
            if page.is_closed():continue
            parsed=urlsplit(page.url)
            if not _trusted_shop_page(page.url) or parsed.hostname=='passport.shop.jd.com':continue
            identity=page_identity(page)
            if identity:
                self.page=page
                return self._result({'loggedIn':True,'identity':identity,'challenge':''})
        return self._result({'loggedIn':False,'identity':{},'challenge':''})

    def check_workspace_after_login(self):
        """The merchant reported completing login. Reuse the existing page if it did not redirect."""
        if self.page is None or self.page.is_closed():
            return
        if self._observe().get('loggedIn') or urlsplit(self.page.url).hostname != 'passport.shop.jd.com':
            return
        from playwright.sync_api import Error as PlaywrightError
        try:
            self.page.goto(WORKSPACE_URL, wait_until='domcontentloaded', timeout=10000)
        except PlaywrightError:
            # A network change can race the redirect; subsequent polls only read the current pages.
            pass

    def _open_oauth(self,action):
        self._launch()
        url=action.get('url','');parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in {'passport.jd.com','open-oauth.jd.com'}:raise ValueError('official-oauth-page-required')
        observation=self._observe()
        if observation.get('challenge'):return self._result({'challenge':observation['challenge']})
        if not observation.get('loggedIn'):return {'ok':False,'error':'login_required'}
        self.oauth_identity=observation['identity'];self.oauth_confirm_handled=False
        self.page.goto(url,wait_until='domcontentloaded')
        return self._result()

    def _confirm(self):
        self._launch()
        if self.oauth_confirm_handled:return {'ok':False,'error':'confirmation_already_processed'}
        observation=self._observe()
        if observation.get('challenge'):return self._result({'challenge':observation['challenge']})
        self.page.bring_to_front()
        parsed=urlsplit(self.page.url)
        if parsed.hostname in ('127.0.0.1','localhost') and parsed.port == 9001:
            return self._result()
        if parsed.scheme != 'https' or parsed.hostname not in ('passport.jd.com','open-oauth.jd.com'):
            return {'ok':False,'error':'oauth_confirmation_page_required'}
        if parsed.hostname!='passport.jd.com' or not parsed.path.startswith('/oauth/'):
            return self._result({'challenge':'请在当前京东授权页完成页面要求的操作'})
        text=_page_text(self.page)
        if any(word in text for word in ('新增权限','额外付费','购买服务','开通付费')):
            return self._result({'challenge':'请在当前京东授权页核对新增权限或费用'})
        button=self.page.get_by_role('button',name='登录',exact=True)
        if not button.count():button=self.page.get_by_text('登录',exact=True)
        if button.count() != 1 or not button.first.is_visible():
            return self._result({'challenge':'请在当前京东授权页确认授权'})
        for selector in ('input[type=checkbox]','input[name*=agree]'):
            box=self.page.locator(selector)
            if box.count() and not box.first.is_checked():box.first.check()
        if not button.first.is_enabled():
            return self._result({'challenge':'请在当前京东授权页确认授权'})
        button.first.click(timeout=15000);self.oauth_confirm_handled=True
        return self._result()

    def _close(self):
        if self.context is None and self._playwright is None:return {'ok':True}
        # This controller launched its own persistent browser. Graceful context closure
        # lets Chromium flush the merchant's session to its original profile.
        try:
            if self.context is not None:self.context.close()
        finally:
            try:
                if self._playwright is not None:self._playwright.stop()
            finally:
                self.context=None;self._playwright=None
        return {'ok':True}

    def dispatch(self,request):
        action=request.get('action') or {};kind=action.get('kind')
        if kind=='open_login':return self._open_login(action)
        if kind=='observe':return self._observe()
        if kind=='open_oauth':return self._open_oauth(action)
        if kind=='confirm':return self._confirm()
        if kind=='close':return self._close()
        return {'ok':False,'error':'unsupported-action'}


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    if argv==['--describe-contract']:
        print(json.dumps(_public(None),ensure_ascii=False));return 0
    if argv in (['--help'],['-h']):
        print('usage: host_connection_controller.py [--describe-contract]  # JSON action request on stdin');return 0
    controller=HostConnectionController()
    with FileLock(controller.root/'action.lock'):
        try:
            raw=sys.stdin.read()
            if len(raw)>65536:raise ValueError('request-too-large')
            request=json.loads(raw)
            result=controller.dispatch(request)
        except BrowserStartError as error:
            result={'ok':False,'error':error.kind,'hint':error.hint}
        except Exception as error:
            # Never echo URLs, page bodies, browser responses or credentials.
            result={'ok':False,'error':'connection-controller-'+type(error).__name__}
    print(json.dumps(result,ensure_ascii=True));return 0

if __name__=='__main__':raise SystemExit(main())
