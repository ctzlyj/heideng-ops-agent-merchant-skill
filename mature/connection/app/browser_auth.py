"""Browser login precedes official CLI OAuth; only verified identity is registered."""
import os
import secrets
import threading
import time

import shoplib as sl
from redaction import safe_text, safe_value


LOGIN_HINT = '已打开京麦登录页，请自行选择密码、短信或扫码登录；完成后自动衔接授权。'
ACTIVE = ('starting', 'waiting', 'verifying')


class BrowserAuthJob:
    def __init__(self, profile, shop_name, expect_vender_id='', *, browser=None, login_factory=None,
                 login_timeout=600, oauth_timeout=600, poll_interval=0.5, browser_config=None):
        self.id = secrets.token_hex(8)
        self.requested_profile = profile
        # A file owned by this task cannot overwrite any existing profile, even after account mismatch.
        self.profile = profile[:24].rstrip('-') + '-' + self.id[:8]
        self.shop_name = shop_name
        self.expect_vender_id = str(expect_vender_id or '')
        self.browser = browser
        self.browser_config = browser_config
        self.login_factory = login_factory
        self.login_timeout, self.oauth_timeout = login_timeout, oauth_timeout
        self.poll_interval = poll_interval
        self.status, self.stage, self.message = 'starting', 'checking_existing', '正在检查店铺连接。'
        self.identity, self.error, self.error_kind = None, '', ''
        self.login = None
        self.started_at, self.finished_at = time.time(), None
        self._done, self._cancelled = threading.Event(), threading.Event()
        self._commit_lock = threading.RLock()
        self._resume_event = threading.Event()
        self._worker_thread = None

    def to_dict(self):
        return safe_value({'id': self.id, 'profile': self.profile, 'shopName': self.shop_name,
                           'expectVenderId': self.expect_vender_id, 'status': self.status,
                           'stage': self.stage, 'message': self.message, 'identity': self.identity,
                           'error': self.error, 'errorKind': self.error_kind,
                           'startedAt': int(self.started_at * 1000),
                           'finishedAt': int(self.finished_at * 1000) if self.finished_at else None})

    def start(self):
        if self._worker_thread and self._worker_thread.is_alive():
            self._resume_event.set()
            return
        self._worker_thread = threading.Thread(target=self._worker, daemon=True, name='jingmai-browser-login')
        self._worker_thread.start()

    def _worker(self):
        try:
            while not self._cancelled.is_set() and self.status != 'success':
                self.run()
                if self.status == 'success' or self.stage == 'deferred':
                    break
                self._resume_event.wait()
                self._resume_event.clear()
        finally:
            if self.browser and (self.status == 'success' or self._cancelled.is_set()):
                try:
                    self.browser.close()
                except Exception:
                    pass

    def _stage(self, stage, message, status='waiting'):
        self.stage, self.message, self.status = stage, message, status

    def _finish(self, status, stage, message, kind=''):
        with self._commit_lock:
            if self._cancelled.is_set() and status != 'cancelled':
                return
            self.status, self.stage = status, stage
            self.message = safe_text(message)
            self.error = self.message if status in ('failed', 'mismatch') else ''
            self.error_kind = kind
            self.finished_at = time.time()
            self._done.set()

    def _matches(self, identity):
        if not isinstance(identity, dict):
            return False
        vid, name = str(identity.get('venderId') or ''), identity.get('shopName') or ''
        if not vid.isdigit() or not name:
            return False
        if self.expect_vender_id:
            if vid != self.expect_vender_id:
                return False
        return not self.shop_name or sl.name_matches(self.shop_name, [name])

    def _verify_and_commit(self):
        self._stage('verifying_cli', '正在实时核验这家店的 CLI 连接。', 'verifying')
        sl.require_auth_slot(self.profile, required=True)
        identity = sl.verify_profile(self.profile)
        if not self._matches(identity):
            sl.mark_auth_rejected(self.profile)
            self.identity = identity
            self._finish('mismatch', 'mismatch', '授权后店铺身份与目标不一致，未登记。', 'mismatch')
            return
        with self._commit_lock:
            if self._cancelled.is_set():
                return
            from heideng_merchant.mature_runtime import merchant_profile_directory
            directory=merchant_profile_directory(getattr(self.browser,'profile_directory',None))
            metadata={'browserProfileDir':str(directory)} if directory else None
            channel=getattr(self.browser,'profile_channel',None)
            if metadata and channel in ('chrome','msedge','chromium'):metadata['browserChannel']=channel
            sl.update_registry(self.profile, identity, extra=metadata)
            self.identity = identity
            self._finish('success', 'ready', '已连接：' + identity['shopName'])

    def run(self):
        if os.environ.get('HEIDENG_BACKGROUND') == '1' or os.environ.get('JINGMAI_LINKER_BACKGROUND') == '1':
            self._finish('failed', 'deferred', '后台任务不发起扫码或授权。', 'background')
            return
        try:
            sl.mark_auth_pending(self.profile, self.id, self.expect_vender_id, self.shop_name)
            if self.browser is None:
                from browser_adapters import create_browser
                self.browser = create_browser(self.browser_config)
            self._stage('waiting_browser', '正在等待当前 Agent 接管任务浏览器，尚未打开扫码页面。')
            self.browser.open_login(self.shop_name or self.expect_vender_id)
            self._stage('waiting_login', LOGIN_HINT)
            deadline = time.monotonic() + self.login_timeout
            identity = None
            while not self._cancelled.is_set() and time.monotonic() < deadline:
                try:
                    observation = self.browser.observe()
                except Exception as exc:
                    # Login redirects can destroy an evaluation context. Repeat
                    # only the read, bounded by the independent scan deadline.
                    if getattr(exc, 'kind', '') not in ('browser_error','action_pending'):
                        raise
                    self._cancelled.wait(self.poll_interval)
                    continue
                if observation.get('challenge'):
                    self.message = ('请在京东商城 App 完成账号安全验证，再回到本页面继续；不会重复发起授权。' if observation['challenge']=='account-risk-blocked' else '请在京麦页面完成：' + safe_text(observation['challenge']))
                    self._cancelled.wait(self.poll_interval)
                    continue
                if observation.get('loggedIn'):
                    identity = observation.get('identity') or {}
                    self._stage('checking_browser_identity', '正在核对网页登录的店铺。')
                    if not self._matches(identity):
                        sl.mark_auth_rejected(self.profile)
                        self.identity = identity
                        self._finish('mismatch', 'mismatch', '网页登录的店铺与目标不一致，请选择目标店铺。', 'mismatch')
                        return
                    break
                self._cancelled.wait(self.poll_interval)
            if self._cancelled.is_set():
                return
            if not identity:
                self._stage('waiting_login', '登录尚未完成，页面已保留。请继续登录，或由宿主用 --resume 恢复原任务。')
                return
            self.expect_vender_id = str(identity['venderId'])
            self.shop_name = identity['shopName']
            if self.login_factory is None:
                from server import LoginJob
                self.login_factory = LoginJob
            self._stage('waiting_oauth', '网页登录已确认，正在自动连接官方 CLI。')
            self.login = self.login_factory(self.profile, self.shop_name, self.expect_vender_id,
                                            defer_registry=True, timeout=int(self.oauth_timeout))
            self.login.start()
            if self._cancelled.is_set():
                self.login.cancel()
                return
            if self.login.status in ('failed', 'mismatch', 'cancelled'):
                self._finish(self.login.status, self.login.status, self.login.message, self.login.error_kind)
                return
            self.browser.open_oauth(self.login.url)
            self.login.url = ''  # navigation consumed; no persistent URL receipt
            try:
                response = self.browser.confirm() or {}
            except Exception as exc:
                if getattr(exc, 'kind', '') not in ('challenge', 'confirmation_unconfigured'):
                    raise
                response = {'challenge': '平台要求本人确认，请在当前授权页面完成'}
            if response.get('challenge'):
                self.message = '请在授权页面完成：' + safe_text(response['challenge'])
            deadline = time.monotonic() + self.oauth_timeout
            while not self._cancelled.is_set() and time.monotonic() < deadline:
                if self.login._done.wait(self.poll_interval):
                    break
            if self._cancelled.is_set():
                return
            if self.login.status == 'success':
                self._verify_and_commit()
            elif self.login.status == 'mismatch':
                self.identity = self.login.identity
                self._finish('mismatch', 'mismatch', self.login.message, 'mismatch')
            elif self.login.status == 'failed' and self.login.error_kind not in ('timeout', 'auth_failed'):
                self._finish('failed', 'verifying_cli', self.login.message, self.login.error_kind)
            else:
                # A lost callback may already have stored credentials. Reconcile before any retry.
                try:
                    self._verify_and_commit()
                except sl.VerifyError as exc:
                    proc = getattr(self.login, 'proc', None)
                    if proc and proc.poll() is None:
                        self.login.cancel()
                    self._finish('failed', 'waiting_oauth', '授权结果尚未确认，已保留页面；先核验本任务 Profile。', 'callback_unknown')
        except sl.VerifyError as exc:
            self._finish('failed', 'verifying_cli', exc.message, exc.kind)
        except Exception as exc:
            kind = getattr(exc, 'kind', '') or ('port_busy' if '9001' in str(exc) else 'browser_error')
            hint = getattr(exc, 'hint', '') or '本次连接尚未完成，请按当前阶段继续；其它店铺未注销。'
            self._finish('failed', self.stage, hint, kind)

    def cancel(self):
        with self._commit_lock:
            if self.status == 'success':
                return
            self._cancelled.set()
            self._resume_event.set()
            if self.login:
                self.login.cancel()
            interrupt = getattr(self.browser, 'cancel_wait', None)
            if interrupt:
                interrupt()
            self._finish('cancelled', 'cancelled', '已取消本次连接。')

    def resume(self):
        if self.status not in ('failed', 'mismatch'):
            return
        if self.status == 'mismatch' and self.login is None:
            # The previous browser identity was rejected before any CLI action.
            # Keep its quarantined record, give this explicit retry a fresh file.
            self.profile = self.requested_profile[:24].rstrip('-') + '-' + secrets.token_hex(4)
        # Retrying OAuth needs a new LoginJob (official CLI generates a new state).
        if self.login:
            if getattr(self.login, 'error_kind', '') == 'credential_isolation':
                return
            try:
                sl.require_auth_slot(self.profile, required=True)
                self._verify_and_commit()
                self._resume_event.set()  # Let the original worker close only its resources.
                return
            except sl.VerifyError as exc:
                if exc.kind == 'credential_isolation':
                    self._finish('failed', 'verifying_cli', exc.message, exc.kind)
                    return
                proc = getattr(self.login, 'proc', None)
                if proc and proc.poll() is None:
                    self.login.cancel()
        self._done.clear()
        self.finished_at = None
        self.start()

    def browser_action(self):
        method = getattr(self.browser, 'next_action', None)
        return method() if method else None

    def browser_report(self, action_id, result):
        if self._cancelled.is_set():
            current = self.browser_action() or {}
            if current.get('kind') != 'close' or current.get('id') != action_id:
                raise ValueError('This task is cancelled')
        return self.browser.report(action_id, result)
