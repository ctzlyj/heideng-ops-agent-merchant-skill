"""Reusable merchant-owned browser controller for the mature HostBrowser actions.

Only page/session operations live here; shop identity, OAuth and authorization remain
in the mature connector. No cookie/storage/history/credential is read or exported.
"""
from __future__ import annotations
import json, os, secrets, sys, uuid
from pathlib import Path
from urllib.parse import urlsplit
from .mature_runtime import merchant_profile_directory
from .state import FileLock

LOGIN_URL='https://passport.shop.jd.com/login/index.action'
CHANNELS=('chrome','msedge','chromium')

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
        """() => {let e=document.querySelector('[data-shop-name]');return e&&e.innerText}""",
        r"""() => {let t=document.body.innerText;let m=t.match(/(?:店铺名称|当前店铺|店铺)[:：\s]*([^\n]{2,80})/);return m&&m[1]}"""):
        try:
            name=page.evaluate(script)
            if isinstance(name,str) and 1<len(name.strip())<80:return {'shopName':name.strip()}
        except Exception:pass
    return {}


class HostConnectionController:
    def __init__(self,state=None):
        home=Path(state or os.environ['HEIDENG_MERCHANT_HOME']).resolve()
        self.home=home;self.root=home/'browser-controller'
        self.root.mkdir(parents=True,exist_ok=True)
        self._state_path=self.root/'session.json'
        self._state=None
        self._playwright=None;self.context=None;self.page=None;self.context_id=None;self.channel=None;self.profile=None
        self.owned_pages=[];self.oauth_identity=None

    def describe_contract(self):return _public(None)

    def _load(self):
        if self._state is not None:return self._state
        from .safety import read_json
        self._state=read_json(self._state_path,{})
        if self._state and set(self._state)!={'contextId','profileDir','browserChannel'}:self._state=None
        return self._state

    def _launch(self,channel='chrome'):
        if self.context is not None:return
        from playwright.sync_api import sync_playwright
        state=self._load()
        if state:
            self.context_id=state['contextId'];self.channel=state['browserChannel'];self.profile=Path(state['profileDir'])
        else:
            self.context_id='merchant-connection-'+uuid.uuid4().hex
            self.profile=self.home/'browser-profiles'/('connection-'+uuid.uuid4().hex[:12])
            self.channel=channel
        directory=merchant_profile_directory(self.profile)
        if directory is None:raise RuntimeError('merchant-owned-profile-required')
        directory.mkdir(parents=True,exist_ok=True)
        self._playwright=sync_playwright().start()
        self.context=self._playwright.chromium.launch_persistent_context(str(directory),channel=None if self.channel=='chromium' else self.channel,headless=False,accept_downloads=False,args=['--no-first-run','--no-default-browser-check'])
        self.context.set_default_timeout(15000)
        pages=list(self.context.pages)
        self.page=next((p for p in pages if not p.is_closed()),None) or self.context.new_page()
        self.owned_pages=[p for p in pages if p.url=='about:blank']
        if self.page not in self.owned_pages:self.owned_pages.append(self.page)
        self._save()

    def _save(self):
        from .safety import atomic_json
        atomic_json(self._state_path,{'contextId':self.context_id,'profileDir':str(self.profile.resolve()),'browserChannel':self.channel})

    def _result(self,extra=None):
        result={'ok':True,'contextId':self.context_id,'owned':True,'isolated':True,'verifiedReuse':True,'profileDir':str(self.profile.resolve()),'browserChannel':self.channel}
        if extra:result.update(extra)
        return result

    def _open_login(self,action):
        self._launch(action.get('browserChannel') or 'chrome')
        url=self.page.url
        if url=='about:blank' or not _trusted_shop_page(url):self.page.goto(LOGIN_URL,wait_until='domcontentloaded')
        # Do not select QR/password/SMS on the merchant's behalf.
        return self._result()

    def _observe(self):
        if self.context is None:
            state=self._load()
            if not state:return {'ok':False,'error':'context-not-opened'}
            self._launch()
        url=self.page.url;host=(urlsplit(url).hostname or '').lower()
        if host=='aq.jd.com' and urlsplit(url).path.startswith('/certified'):
            return self._result({'loggedIn':False,'identity':{},'challenge':'account-risk-blocked','requiresUserAction':'请在京东商城 App 完成账号安全验证，再回到当前页面继续。'})
        identity=_identity(self.page) if _trusted_shop_page(url) else {}
        return self._result({'loggedIn':bool(identity),'identity':identity,'challenge':''})

    def _open_oauth(self,action):
        self._launch()
        url=action.get('url','');parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in {'passport.jd.com','open-oauth.jd.com'}:raise ValueError('official-oauth-page-required')
        observation=self._observe()
        if observation.get('challenge'):return self._result({'challenge':observation['challenge']})
        if not observation.get('loggedIn'):return {'ok':False,'error':'login_required'}
        self.oauth_identity=observation['identity']
        self.page.goto(url,wait_until='domcontentloaded')
        return self._result()

    def _confirm(self):
        self._launch()
        observation=self._observe()
        if observation.get('challenge'):return self._result({'challenge':observation['challenge']})
        # Normal current-scope OAuth confirmation only. No hidden scope/cost approval.
        text=_page_text(self.page)
        if any(word in text for word in ('新增权限','额外付费','购买服务','开通付费')):return {'ok':False,'error':'confirmation_scope_changed'}
        page_url=self.page.url
        if urlsplit(page_url).hostname!='passport.jd.com' or not page_url.startswith('https://passport.jd.com/oauth/'):
            return {'ok':False,'error':'oauth_confirmation_page_required'}
        for selector in ('input[type=checkbox]','input[name*=agree]'):
            box=self.page.locator(selector)
            if box.count() and not box.first.is_checked():box.first.check()
        button=self.page.get_by_role('button',name='登录',exact=True)
        if not button.count():button=self.page.get_by_text('登录',exact=True)
        if not button.count():return {'ok':False,'error':'confirmation_button_unavailable'}
        button.first.click(timeout=15000)
        return self._result()

    def _close(self):
        if self.context is None:return {'ok':True}
        for page in self.owned_pages:
            if not page.is_closed():page.close()
        self.context=None;self._playwright.stop();self._playwright=None
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
    controller=HostConnectionController()
    if argv==['--describe-contract']:
        print(json.dumps(controller.describe_contract(),ensure_ascii=False));return 0
    with FileLock(controller.root/'action.lock'):
        try:
            raw=sys.stdin.read()
            if len(raw)>65536:raise ValueError('request-too-large')
            request=json.loads(raw)
            result=controller.dispatch(request)
        except Exception as error:
            # Never echo URLs, page bodies, browser responses or credentials.
            result={'ok':False,'error':'connection-controller-'+type(error).__name__}
    print(json.dumps(result,ensure_ascii=True));return 0

if __name__=='__main__':raise SystemExit(main())
