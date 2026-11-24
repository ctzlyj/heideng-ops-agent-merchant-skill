"""Task-owned browser adapters; no WebCLI, credential export or identity endpoint.

create_browser(config=None) defaults to HostBrowser. Methods are synchronous:
open_login(target), open_oauth(url), confirm() -> {"status": "ok"}; close() ->
{"status": "closed"}; observe() -> {loggedIn: bool, identity: {venderId, shopId,
shopName}, challenge: str}. BrowserError exposes fixed kind/hint and to_dict().

HostBrowser.next_action() returns a COPY of the current in-memory action or None.
Only that trusted host bridge may receive its URL. report(id, result) returns
{"status": "accepted"} or {"status": "rejected", "kind": ...}. The first report
needs contextId, owned=True and isolated=True or verifiedReuse=True. Every later
report needs the SAME contextId and owned=True. Successful observe reports include
the observation fields at the top level. ok=False or a nonempty error completes
the action with a sanitized BrowserError; invalid/stale reports do not consume it.
The host owns real page/interface discovery, identity verification, challenges
and closing ONLY pages opened for this task. tabId alone never proves isolation.
timeout/poll are positive finite seconds (defaults 120/.05). A worker calls the
blocking methods while JoyCode or another host polls/reports; no particular host
tool is required. Polling repeats the same ID until accepted, without re-execution.
cancel_wait() -> {"status": "cancelled"} invalidates only the pending ID, wakes
its worker with kind='cancelled', and keeps the owned session available for retry.
Repeated open_login(target) must reuse that target's existing task-owned pages
and context in the host. If that page has moved to OAuth/callback, navigate it
back to the known login page in the same context before observing real identity.
If it is still the login page, preserve it for continued QR observation. It never
authorizes a new context or closing user tabs; compare navigation URLs in memory.

Playwright is optional and starts lazily on the calling worker thread. Config:
provider='playwright', identityScript=<observed, verified JavaScript returning
the observation shape>, identityScriptVerified=True, loginUrl (default
https://jingmai.jd.com/), confirmSelector (explicit only), headless (default True).
HTTP is accepted ONLY for loopback fixtures; production navigation requires HTTPS.
No real Jingmai identity endpoint/schema has been verified here; none is guessed.
userDataDir requires owner=<task owner> and reuseIdentity={verified: True,
venderId, shopId, shopName}; the script must also verify that identity LIVE before
OAuth. This is an explicit task-owned directory, never an automatically located
working profile. No cookies/storage state are read, copied or exported by this
adapter. All Playwright operations, including close, run on the initial worker
thread. Only task-created pages (including action popups) are closed. If unowned
pages remain, their context/driver stays alive for their owner to clean up.
Login retries reuse the context; only a failed task-owned page is replaced after
a navigation error. Repeat calls preserve the page only while it is still at the
configured or observed login URL; OAuth/callback recovery navigates that same
page back to loginUrl. All such URL comparisons and observed addresses stay in
memory. Login redirects are recorded so QR waiting does not restart navigation.
OAuth confirmation may lack merchant DOM: it uses the same verified session,
requires an explicit selector, rejects challenges and any reported identity change.
"""

from __future__ import annotations

import math
import re
import threading
import time
import uuid
from urllib.parse import urlsplit


_HINTS = {
    "browser_error": "浏览器操作未完成，请由宿主核对当前页面状态。",
    "browser_timeout": "等待浏览器报告超时，请核对状态后再继续。",
    "configuration": "浏览器配置无效。",
    "identity_unverified": "需要显式配置经验证的身份读取脚本。",
    "session_unverified": "需要任务归属和独立或已验证复用的浏览器上下文。",
    "context_mismatch": "浏览器上下文与本任务已验证的上下文不一致。",
    "identity_mismatch": "当前页面身份与已验证的复用身份不一致。",
    "invalid_observation": "身份报告格式无效，不能推断店铺身份。",
    "stale_action": "动作已过期、已完成或不属于本任务。",
    "action_pending": "浏览器动作仍在处理，请继续观察原任务，不要重复操作。",
    "busy": "本任务已有浏览器动作等待报告。",
    "cancelled": "本任务的浏览器动作已取消。",
    "closed": "本任务的浏览器已关闭。",
    "challenge": "页面需要人工处理验证，请由宿主观察后继续。",
    "login_required": "请先完成页面登录并核验真实店铺身份。",
    "confirmation_unconfigured": "未配置明确的授权确认元素。",
    "wrong_thread": "请在创建浏览器会话的工作线程内操作。",
    "provider_unavailable": "可选 Playwright 运行环境不可用。",
}
_CHALLENGES = {"", "captcha", "sms", "qr", "login", "device", "verification", "unknown", "account-risk-blocked", "confirmation-pending"}
_IDENTITY_KEYS = ("venderId", "shopId", "shopName")
_PLAYWRIGHT_RUNTIME = threading.local()


class BrowserError(Exception):
    """Only fixed public kind/hint; never use a provider's exception message."""

    def __init__(self, kind="browser_error"):
        self.kind = kind if isinstance(kind, str) and kind in _HINTS else "browser_error"
        self.hint = _HINTS[self.kind]
        super().__init__(self.hint)

    def to_dict(self):
        return {"status": "error", "kind": self.kind, "hint": self.hint}


def _config(config):
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise BrowserError("configuration")
    config = dict(config)
    for key, default in (("timeout", 120.0), ("poll", 0.05)):
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise BrowserError("configuration")
        config[key] = float(value)
    return config


def _identity(value, required):
    if not isinstance(value, dict):
        raise BrowserError("invalid_observation")
    result = {}
    for key in _IDENTITY_KEYS:
        item = value.get(key, "")
        if key != "shopName" and isinstance(item, int) and not isinstance(item, bool):
            item = str(item)
        if not isinstance(item, str) or (required and not item):
            raise BrowserError("invalid_observation")
        if key != "shopName":
            if item and not re.fullmatch(r"[0-9]{1,64}", item):
                raise BrowserError("invalid_observation")
        elif len(item) > 200 or re.search(r"[\x00-\x1f\x7f]|https?://|(?:token|cookie|secret|authorization)\s*[:=]", item, re.I):
            raise BrowserError("invalid_observation")
        result[key] = item
    return result


def _observation(result):
    if not isinstance(result, dict) or type(result.get("loggedIn")) is not bool:
        raise BrowserError("invalid_observation")
    logged_in = result["loggedIn"]
    identity = _identity(result.get("identity", {}), False)
    if logged_in and not identity["shopName"].strip():
        raise BrowserError("invalid_observation")
    challenge = result.get("challenge", "")
    if not isinstance(challenge, str):
        raise BrowserError("invalid_observation")
    return {"loggedIn": logged_in, "identity": identity,
            "challenge": challenge if challenge in _CHALLENGES else "verification"}


def _target(target):
    if not isinstance(target, str) or not target.strip() or len(target) > 200:
        raise BrowserError("configuration")
    return target


def _url(url):
    valid = False
    if isinstance(url, str) and not re.search(r"[\x00-\x20\x7f]", url):
        try:
            parsed = urlsplit(url)
            valid = (bool(parsed.hostname) and not parsed.username and not parsed.password
                     and (parsed.scheme == "https" or
                          parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}))
        except Exception:
            pass
    if not valid:
        raise BrowserError("configuration")
    return url


def create_browser(config=None):
    config = _config(config)
    provider = config.get("provider", "host")
    if provider == "host":
        return HostBrowser(config)
    if provider == 'builtin':
        identity=config.get('shopIdentity') or {}
        return _BUILTIN_FACTORY(identity)
    if provider == "playwright":
        return PlaywrightBrowser(config)
    raise BrowserError("configuration")


class BuiltinBrowser:
    """Mature auth drives the packaged controller itself; no Agent polling loop."""
    def __init__(self,shop_identity=None):
        from heideng_merchant.host_connection_controller import HostConnectionController
        self.controller=HostConnectionController(shop_identity=shop_identity)
        self.profile_directory=None;self.profile_channel=None;self.profile_channel_reason=None;self._context_id=None;self._closed=False;self._oauth_confirm_handled=False
    def prepare_launch(self):
        try:
            self.controller._launch()
        finally:
            self.profile_channel = self.controller.channel
            self.profile_channel_reason = self.controller.channel_reason
    def _call(self,kind,**payload):
        if self._closed and kind!='close':raise BrowserError('closed')
        result=self.controller.dispatch({'action':{'kind':kind,**payload}})
        if not isinstance(result,dict):raise BrowserError('browser_error')
        if kind=='close':
            if result.get('ok') is True and not result.get('error'):return result
            raise BrowserError('browser_error')
        if result.get('profileDir'):
            from heideng_merchant.mature_runtime import merchant_profile_directory
            self.profile_directory=merchant_profile_directory(result['profileDir'])
        self.profile_channel=result.get('browserChannel');self.profile_channel_reason=result.get('browserSelectionReason')
        context=result.get('contextId')
        if not context or result.get('owned') is not True or (self._context_id and context!=self._context_id):raise BrowserError('context_mismatch')
        if self._context_id is None and result.get('isolated') is not True and result.get('verifiedReuse') is not True:raise BrowserError('session_unverified')
        self._context_id=context
        if result.get('ok') is False or result.get('error'):
            kind_name=result.get('error')
            if kind_name=='login_required':raise BrowserError('login_required')
            if kind_name=='confirmation_scope_changed':raise BrowserError('challenge')
            raise BrowserError('browser_error')
        return result
    def open_login(self,target):self._call('open_login',target=_target(target));return {'status':'ok'}
    def observe(self):
        value=self._call('observe')
        return {'loggedIn':bool(value.get('loggedIn')),'identity':value.get('identity') or {},'challenge':value.get('challenge','')}
    def check_workspace_after_login(self):
        self.controller.check_workspace_after_login()
    def open_oauth(self,url):self._call('open_oauth',url=_url(url));self._oauth_confirm_handled=False;return {'status':'ok'}
    def confirm(self):
        if self._oauth_confirm_handled:raise BrowserError('action_pending')
        self._oauth_confirm_handled=True
        result=self._call('confirm')
        return {'challenge':result['challenge']} if result.get('challenge') else {'status':'ok'}
    def close(self):self._call('close');self._closed=True;return {'status':'closed'}


def _BUILTIN_FACTORY(shop_identity):return BuiltinBrowser(shop_identity)


class HostBrowser:
    """An independent, thread-safe, in-memory request/report channel per task."""

    def __init__(self, config=None):
        config = _config(config)
        self._timeout = config["timeout"]
        self._poll = config["poll"]
        self._condition = threading.Condition()
        self._pending = None
        self._context_id = None
        self.profile_directory = None
        self.profile_channel = None
        self._closing = False
        self._closed = False

    def next_action(self):
        with self._condition:
            pending = self._pending
            if pending is None:
                return None
            if time.monotonic() >= pending["deadline"]:
                # An idle human-facing action is still alive; only its consumer is late.
                self._condition.notify_all()
                return None if pending["action"]["kind"]=="observe" else dict(pending["action"])
            return dict(pending["action"])

    def report(self, action_id, result):
        with self._condition:
            pending = self._pending
            if pending is None or not isinstance(action_id, str) or pending["action"]["id"] != action_id:
                return {"status": "rejected", "kind": "stale_action"}
            if time.monotonic() >= pending["deadline"] and pending["action"]["kind"] in ("open_login", "open_oauth", "confirm"):
                pending["deadline"] = time.monotonic() + self._timeout
            context = result.get("contextId") if isinstance(result, dict) else None
            if not isinstance(context, str) or not context or len(context) > 200 or result.get("owned") is not True:
                return {"status": "rejected", "kind": "session_unverified"}
            if self._context_id is None:
                if result.get("isolated") is not True and result.get("verifiedReuse") is not True:
                    return {"status": "rejected", "kind": "session_unverified"}
            elif context != self._context_id:
                return {"status": "rejected", "kind": "context_mismatch"}
            if result.get("ok") is False or result.get("error"):
                pending["failure"] = "browser_error"
            elif pending["action"]["kind"] == "observe":
                try:
                    pending["result"] = _observation(result)
                except BrowserError:
                    return {"status": "rejected", "kind": "invalid_observation"}
            else:
                pending["result"] = {"status": "closed" if pending["action"]["kind"] == "close" else "ok"}
                if pending['action']['kind'] != 'close' and result.get('challenge'):
                    challenge = result['challenge']
                    pending['result']['challenge'] = challenge if challenge in _CHALLENGES else 'verification'
            if result.get('profileDir') and not pending.get('failure'):
                from heideng_merchant.mature_runtime import merchant_profile_directory
                directory=merchant_profile_directory(result['profileDir'])
                if directory is None:return {"status":"rejected","kind":"session_unverified"}
                if self.profile_directory is not None and self.profile_directory!=directory:
                    return {"status":"rejected","kind":"context_mismatch"}
                channel=result.get('browserChannel')
                if channel is not None and channel not in ('chrome','msedge','chromium'):return {'status':'rejected','kind':'configuration'}
                if self.profile_channel is not None and channel is not None and self.profile_channel!=channel:return {'status':'rejected','kind':'context_mismatch'}
                self.profile_directory=directory
                if channel:self.profile_channel=channel
            self._context_id = context
            pending["done"] = True
            self._pending = None
            self._condition.notify_all()
            return {"status": "accepted"}

    def _request(self, kind, **payload):
        with self._condition:
            if self._closed:raise BrowserError("closed")
            if self._closing:raise BrowserError("busy")
            if kind == "close":
                self._closing = True
                if self._pending is not None:
                    self._pending["failure"] = "cancelled";self._pending = None;self._condition.notify_all()
            elif self._pending is not None:raise BrowserError("busy")
            # UI operations can be pending; a read must not kill a human login.
            deadline = time.monotonic() + self._timeout if kind in ("open_login", "open_oauth", "confirm") else float("inf")
            pending = {"action": {"id": uuid.uuid4().hex, "kind": kind, **payload}, "deadline": deadline, "done": False}
            self._pending = pending;self._condition.notify_all()
            try:
                while not pending["done"]:
                    if "failure" in pending:
                        if pending["failure"]=="browser_timeout":raise BrowserError("action_pending")
                        raise BrowserError(pending["failure"])
                    if kind in ("open_login", "open_oauth", "confirm") and time.monotonic() >= pending["deadline"]:
                        # Reconcile the exact action before replay; never infer not-submitted.
                        raise BrowserError("action_pending")
                    remaining = pending["deadline"] - time.monotonic()
                    self._condition.wait(max(0.001, min(remaining, self._poll)))
            finally:
                if kind == "close":self._closed = True;self._closing = False

    def open_login(self, target):
        return self._request("open_login", target=_target(target))

    def observe(self):
        return self._request("observe")

    def open_oauth(self, url):
        return self._request("open_oauth", url=_url(url))

    def confirm(self):
        return self._request("confirm")

    def cancel_wait(self):
        with self._condition:
            if self._pending is not None:
                self._pending["failure"] = "cancelled"
                self._pending = None
                self._condition.notify_all()
        return {"status": "cancelled"}

    def close(self):
        with self._condition:
            if self._closed:
                return {"status": "closed"}
        return self._request("close")


class PlaywrightBrowser:
    """Lazy optional Chromium; verified observation script, own context/pages."""

    def __init__(self, config=None):
        config = _config(config)
        script = config.get("identityScript")
        if not isinstance(script, str) or not script.strip() or config.get("identityScriptVerified") is not True:
            raise BrowserError("identity_unverified")
        self._reuse_identity = None
        self._user_data_dir = config.get("userDataDir")
        from heideng_merchant.mature_runtime import merchant_profile_directory
        self.profile_directory = merchant_profile_directory(self._user_data_dir)
        self.profile_channel=config.get('channel') or 'chromium'
        if self.profile_channel not in ('chrome','msedge','chromium'):raise BrowserError('configuration')
        if self._user_data_dir is not None:
            reuse = config.get("reuseIdentity")
            if (not isinstance(self._user_data_dir, str) or not self._user_data_dir.strip()
                    or not isinstance(config.get("owner"), str) or not config["owner"].strip()
                    or not isinstance(reuse, dict) or reuse.get("verified") is not True):
                raise BrowserError("session_unverified")
            self._reuse_identity = _identity(reuse, True)
        self._login_url = _url(config.get("loginUrl", "https://passport.shop.jd.com/login/index.action"))
        self._identity_script = script
        self._confirm_selector = config.get("confirmSelector")
        if self._confirm_selector is not None and (not isinstance(self._confirm_selector, str) or not self._confirm_selector.strip()):
            raise BrowserError("configuration")
        self._headless = config.get("headless", True)
        if type(self._headless) is not bool:
            raise BrowserError("configuration")
        self._timeout = config["timeout"]
        self._playwright = None
        self._engine = None
        self._context = None
        self._page = None
        self._owned_pages = []
        self._in_action = False
        self._thread_id = None
        self._closed = False
        self._runtime_held = False
        self._login_opened = False
        self._login_page_url = None
        self._login_failed = False
        self._oauth_identity = None

    def _check(self, page=True):
        if self._closed:
            raise BrowserError("closed")
        if self._thread_id is not None and self._thread_id != threading.get_ident():
            raise BrowserError("wrong_thread")
        if page and self._page is None:
            raise BrowserError("login_required")

    def _perform(self, call, kind="browser_error"):
        # Raise OUTSIDE except: no provider exception attached as __context__.
        try:
            return call()
        except BrowserError:
            raise
        except Exception:
            pass
        raise BrowserError(kind) from None

    def _start(self):
        self._check(page=False)
        if self._context is not None:
            return
        from heideng_merchant.host_connection_controller import BrowserStartError, startup_kind
        sync_playwright = None
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            pass
        if sync_playwright is None:
            raise BrowserStartError("browser_python_dependency")
        self._thread_id = threading.get_ident()

        def launch():
            runtime = getattr(_PLAYWRIGHT_RUNTIME, "value", None)
            if runtime is None:
                runtime = {"driver": sync_playwright().start(), "refs": 0}
                _PLAYWRIGHT_RUNTIME.value = runtime
            self._playwright = runtime["driver"]
            runtime["refs"] += 1
            self._runtime_held = True
            if self._user_data_dir is None:
                self._engine = self._playwright.chromium.launch(headless=self._headless,chromium_sandbox=True,channel=None if self.profile_channel=='chromium' else self.profile_channel)
                self._context = self._engine.new_context()
            else:
                self._context = self._playwright.chromium.launch_persistent_context(self._user_data_dir, headless=self._headless,chromium_sandbox=True,channel=None if self.profile_channel=='chromium' else self.profile_channel)
                # The launcher-created blank page belongs to this task. Restored
                # nonblank pages are not ours and must survive adapter.close().
                self._owned_pages.extend(page for page in self._context.pages if page.url == "about:blank")
            self._context.set_default_timeout(self._timeout * 1000)
            self._context.set_default_navigation_timeout(self._timeout * 1000)
            self._context.on("page", self._track_page)
            self._page = self._context.new_page()
            self._owned_pages.append(self._page)

        try:
            launch()
            return
        except Exception as exc:
            kind = startup_kind(exc, 'driver' if self._playwright is None else 'channel')
        self._release_runtime()
        raise BrowserStartError(kind) from None

    def prepare_launch(self):
        self._start()

    def _release_runtime(self):
        if not self._runtime_held:
            return
        runtime = _PLAYWRIGHT_RUNTIME.value
        runtime["refs"] -= 1
        self._runtime_held = False
        if runtime["refs"] == 0:
            _PLAYWRIGHT_RUNTIME.value = None
            self._perform(runtime["driver"].stop)

    def _track_page(self, page):
        if self._in_action and page not in self._owned_pages:
            self._owned_pages.append(page)

    def _navigate(self, url):
        self._in_action = True
        try:
            self._perform(lambda: self._page.goto(url, wait_until="domcontentloaded"))
        finally:
            self._in_action = False
        return {"status": "ok"}

    def open_login(self, target):
        _target(target)
        if self._page is not None and self._login_opened:
            self._check()
            current_url = self._perform(lambda: self._page.url)
            if not self._login_failed and current_url in (self._login_url, self._login_page_url):
                if self._reuse_identity is not None:
                    self.observe()
                return {"status": "ok"}
        self._start()
        if self._login_failed:
            # Failed Chromium navigation can queue an internal error document
            # that interrupts another goto. Replace only this owned page,
            # preserving its context, implicit session and all other pages.
            def replace_failed_page():
                if not self._page.is_closed():
                    self._page.close()
                self._page = self._context.new_page()
                self._owned_pages.append(self._page)
            self._perform(replace_failed_page)
        try:
            result = self._navigate(self._login_url)
        except BrowserError:
            self._login_failed = True
            raise
        self._login_failed = False
        self._login_opened = True
        self._login_page_url = self._perform(lambda: self._page.url)
        if self._reuse_identity is not None:
            self.observe()
        return result

    def observe(self):
        self._check()
        observation = _observation(self._perform(lambda: self._page.evaluate(self._identity_script)))
        if self._reuse_identity is not None and observation["loggedIn"]:
            current = observation["identity"]
            if any(value and value != self._reuse_identity[key] for key, value in current.items()):
                raise BrowserError("identity_mismatch")
            if not all(current.values()):
                # A previously verified profile must still match the full live identity.
                # Wait for the page to finish rendering without replacing this session.
                return {"loggedIn": False, "identity": {}, "challenge": observation["challenge"]}
        return observation

    def _allow_authorization(self):
        observation = self.observe()
        if observation["challenge"]:
            raise BrowserError("challenge")
        if not observation["loggedIn"]:
            raise BrowserError("login_required")
        return observation

    def open_oauth(self, url):
        url = _url(url)
        observation = self._allow_authorization()
        result = self._navigate(url)
        self._oauth_identity = observation["identity"]
        return result

    def confirm(self):
        self._check()
        if self._confirm_selector is None:
            raise BrowserError("confirmation_unconfigured")
        observation = self.observe()
        if observation["challenge"]:
            raise BrowserError("challenge")
        if observation["loggedIn"]:
            if self._oauth_identity is not None and observation["identity"] != self._oauth_identity:
                raise BrowserError("identity_mismatch")
        elif self._oauth_identity is None:
            raise BrowserError("login_required")
        self._in_action = True
        try:
            self._perform(lambda: self._page.locator(self._confirm_selector).click())
        finally:
            self._in_action = False
        return {"status": "ok"}

    def close(self):
        if self._closed and not self._runtime_held:
            return {"status": "closed"}
        if self._thread_id is not None and self._thread_id != threading.get_ident():
            raise BrowserError("wrong_thread")

        def cleanup():
            for page in self._owned_pages:
                if not page.is_closed():
                    page.close()
            if self._context is not None and not self._context.pages:
                self._context.close()
                if self._engine is not None:
                    self._engine.close()
                self._release_runtime()
            elif self._context is None and self._playwright is not None:
                self._release_runtime()

        try:
            self._perform(cleanup)
        finally:
            self._closed = True
        return {"status": "closed"}
