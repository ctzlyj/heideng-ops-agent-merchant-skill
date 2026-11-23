"""Local CLI-card integration probe. jdo-cli owns the browser URL, callback and tokens."""
import argparse
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


class CardError(Exception):
    """Public fixed diagnostics only; never relay a credential or CLI log."""

WORKER_FAILURES = frozenset({
    'callback-busy','cannot-confirm-callback-stopped','identity-mismatch',
    'official-command-failed','official-identity-unavailable','official-init-failed',
    'official-login-ended-before-url','official-login-incomplete','official-login-receipt-mismatch',
    'official-profile-mismatch','official-profile-not-active','official-receipt-unavailable',
    'official-shop-not-active','unable-to-check-callback-owner','worker-operation-timed-out',
    'worker-permission-denied','needs-reconciliation',
})


def _windows_process_parents():
    """Read native PID metadata without starting a Windows PowerShell session."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
                    ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
                    ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),
                    ('name',wintypes.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD,wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (wintypes.HANDLE,ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateToolhelp32Snapshot(2,0)
    if handle == wintypes.HANDLE(-1).value:
        raise CardError('unable-to-check-callback-owner')
    parents = {}
    try:
        item = Entry()
        item.size = ctypes.sizeof(item)
        more = kernel.Process32FirstW(handle,ctypes.byref(item))
        while more:
            parents[item.pid] = item.parent
            more = kernel.Process32NextW(handle,ctypes.byref(item))
    finally:
        kernel.CloseHandle(handle)
    return parents


def authorization_url(line):
    # Match a complete URL token from native stdout, never a URL embedded
    # inside a different URI or query parameter.
    urls = re.findall(r"""https?://[^\s"'<>]+""", line)
    if len(urls) != 1:
        return None
    url = urls[0]
    parts = urlsplit(url)
    if ((parts.scheme, parts.netloc, parts.path) != ('https', 'open-oauth.jd.com', '/oauth2/to_login')
            or not parts.query or parts.fragment or len(url) > 16384
            or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        return None
    return url


class Card:
    def __init__(self, state, core, *, native_command=None, worker_command=None, callback_port=9001):
        self.state = Path(state).resolve()
        self.core = Path(core).resolve()
        sys.path[:0] = [str(self.core), str(self.core/'mature/connection/app')]
        import shoplib
        from heideng_merchant.safety import safe_join
        self.shoplib = shoplib
        self.folder = safe_join(self.state, 'jd-card')
        self.receipt = safe_join(self.state, 'jd-card/current.json')
        self.home = safe_join(self.state, 'cli-home/.jdo-cli')
        self.config = safe_join(self.home,'config.json')
        self.profiles = safe_join(self.home,'profiles')
        self.native_command = native_command
        self.worker_command = worker_command or [sys.executable, '-I', '-B', str(Path(__file__).resolve())]
        self.callback_port = callback_port
        self._env = None
        self._callback_handles = {}

    def lock(self, name='state', timeout=2):
        from heideng_merchant.state import FileLock
        return FileLock(self.folder/(name+'.lock'), timeout=timeout)

    def current(self):
        from heideng_merchant.safety import read_json
        record = read_json(self.receipt, {})
        if not isinstance(record, dict):
            raise CardError('invalid-card-receipt')
        if record and (not re.fullmatch('[0-9a-f]{24}',str(record.get('attempt') or '')) or
                       record.get('profile') != 'wb-jd-'+record['attempt']):
            raise CardError('invalid-card-receipt')
        return record

    def write(self, record):
        from heideng_merchant.safety import atomic_json
        # Windows readers temporarily deny rename/delete. Keep publishing a whole
        # receipt atomically; a momentary status read must not abort an OAuth worker.
        deadline = time.monotonic() + .6
        while True:
            try:
                atomic_json(self.receipt, record)
                return
            except PermissionError as error:
                if getattr(error,'winerror',None) not in (5,32,33) or time.monotonic() >= deadline:
                    raise
                time.sleep(.02)

    def environment(self):
        from heideng_merchant.mature_runtime import child_environment
        if self._env is None:
            self._env = child_environment(self.state)
            self._env['PYTHONUNBUFFERED'] = '1'
            for key in ('HEIDENG_MERCHANT_LTS4AI_API_KEY','HEIDENG_MERCHANT_WEBCLI_BIN',
                        'HEIDENG_MERCHANT_BROWSER_CONFIG','HEIDENG_WEBCLI_COMMAND_JSON','SHOP_CDP'):
                self._env.pop(key, None)
        return self._env

    def command(self):
        if self.native_command is not None:
            return self.native_command
        from heideng_merchant.official import OfficialClient
        self.native_command = [str(OfficialClient(self.state).executable())]
        return self.native_command

    def native(self, args, timeout):
        result = subprocess.run([*self.command(), *args], env=self.environment(), stdin=subprocess.DEVNULL,
                                capture_output=True, encoding='utf-8', errors='replace', timeout=timeout)
        if result.returncode:
            raise CardError('official-command-failed')
        data = self.shoplib.extract_json(result.stdout)
        if not data:
            raise CardError('official-receipt-unavailable')
        return data

    def metadata(self, profile, *, timeout=5, require_active=True):
        """Inspect only the official CLI's public, non-secret proof fields."""
        from server import owned_credential_slot
        data = self.native(['status'], timeout)
        target = data.get('profile') or {}
        inputs = data.get('credentialInputs') or {}
        store = data.get('credentialStore') or {}
        account = owned_credential_slot(store.get('tokenCredentialAccount'), profile)
        if (data.get('ok') is not True or data.get('defaultProfile') != profile
                or not data.get('home') or Path(data['home']).resolve() != self.home
                or target.get('exists') is not True or not target.get('path')
                or Path(target['path']).resolve() != self.home/'profiles'/(profile+'.json')
                or inputs.get('accessTokenFromEnv') is True or inputs.get('appSecretFromEnv') is True):
            raise CardError('official-profile-mismatch')
        expires = inputs.get('oauthExpiresAtMs')
        if require_active and (not account or inputs.get('oauthTokenStored') is not True
                or inputs.get('oauthTokenMocked') is not False or store.get('appSecretStored') is not True
                or type(expires) not in (int,float) or not math.isfinite(expires)
                or expires <= time.time()*1000):
            raise CardError('official-profile-not-active')
        return account, {**inputs, 'appSecretStored':store.get('appSecretStored')}

    def live_shop(self, profile):
        from heideng_merchant.official import identity_from_response
        data = self.native(['invoke','--skill-id','jdo-seller-info','--url','/rest/sp-seller/v0/venderinfo',
                            '--method','GET','--params','{"scopeSet":"baseInfo"}','--request-identity','vender',
                            '--profile='+profile], 8)
        if data.get('success') is not True:
            raise CardError('official-identity-unavailable')
        ident = identity_from_response(data)
        payload = data['data']
        if 'shopBaseInfo' not in payload:
            payload = payload.get('data') or {}
        if str(payload['shopBaseInfo'].get('status')) != '1':
            raise CardError('official-shop-not-active')
        return {key:ident[key] for key in ('shopId','venderId','shopName')}

    def credential_state(self, record):
        account, flags = self.metadata(record['profile'],require_active=False)
        if account and sha256(account[0].encode()).hexdigest() != record['slotDigest']:
            raise CardError('official-profile-mismatch')
        stored = flags.get('oauthTokenStored')
        if flags.get('appSecretStored') is True and stored is False:
            return 'token-cleared'
        expires = flags.get('oauthExpiresAtMs')
        if (not account or stored is not True or flags.get('oauthTokenMocked') is not False
                or flags.get('appSecretStored') is not True or type(expires) not in (int,float)
                or not math.isfinite(expires) or expires <= 0):
            raise CardError('official-profile-not-active')
        return 'token-expired' if expires <= time.time()*1000 else 'active'

    def status(self, live=False):
        record = self.current()
        if record.get('status') != 'ready':
            return {'status':record.get('status','not-connected'), 'matched':False}
        profile = record['profile']
        credential = self.credential_state(record)
        if credential != 'active':
            return {'status':'not-connected','reason':credential,'matched':False}
        identity = record['identity']
        if live and self.live_shop(profile) != identity:
            raise CardError('identity-mismatch')
        if self.current() != record:
            raise CardError('connection-changed')
        return {'status':'ready','profile':profile, **identity, 'matched':True,'readOnly':True,
                'evidence':'live-venderinfo' if live else 'current-cli-status-and-previous-live-identity'}

    def _new_record(self, previous, expected):
        profiles = {p.stem for p in self.profiles.glob('*.json')}
        if profiles and (not previous or profiles - set(previous.get('ownedProfiles',[]))):
            raise CardError('dedicated-cli-home-required')
        from heideng_merchant.safety import read_json
        default = read_json(self.config,{}).get('default_profile')
        if default and default not in previous.get('ownedProfiles',[]):
            raise CardError('dedicated-cli-home-required')
        attempt = secrets.token_hex(12)
        profile = 'wb-jd-'+attempt
        return {'attempt':attempt, 'profile':profile, 'status':'pending', 'expectedVenderId':expected,
                'ownedProfiles':[*previous.get('ownedProfiles',[]),profile]}

    def _init_native(self, record):
        extra = ['--vender-id',record['expectedVenderId']] if record['expectedVenderId'] else []
        args = ['--endpoint',self.shoplib.DEFAULT_ENDPOINT,'init','--profile',record['profile'],
                '--shop-name',record['profile'],'--skip-network',*extra]
        if self.native(args, 30).get('ok') is not True:
            raise CardError('official-init-failed')

    def prepare(self, expected=''):
        if expected and not re.fullmatch('[0-9]+',expected):
            raise CardError('invalid-expected-vender-id')
        with self.lock():
            record = self.current()
            if record and record['status'] != 'disconnected':
                if (record.get('initialized') and record['expectedVenderId']==expected
                        and record.get('status') in ('prepared','ready','pending')):
                    return {'status':'prepared','profile':record['profile']}
                raise CardError('existing-card-attempt-check-status-or-disconnect')
            record = self._new_record(record, expected)
            if self.native_command is None:
                from heideng_merchant.official import OfficialClient
                client = OfficialClient(self.state)
                if not client.receipt_path.exists():
                    client.install()
                # Recheck integrity even when prepare finds an existing installation.
                self.native_command = [str(client.executable())]
            self.write(dict(record,status='preparing',nativeInitStarted=True))
            self._init_native(record)
            self.write(dict(record,status='prepared',initialized=True))
            return {'status':'prepared','profile':record['profile']}

    def auth(self, expected=''):
        if expected and not re.fullmatch('[0-9]+',expected):
            raise CardError('invalid-expected-vender-id')
        began = time.monotonic()
        with self.lock():
            previous = self.current()
            stage = previous.get('status','disconnected')
            renewal = stage == 'ready'
            if renewal:
                if expected and expected != previous['identity']['venderId']:
                    raise CardError('different-card-attempt')
                if self.credential_state(previous) == 'active':
                    raise CardError('already-connected')
                stage = 'prepared'
            elif stage == 'callback-busy' and previous.get('nativeLoginStarted') is False:
                # A foreign listener stopped preflight, before the native login
                # launched. Reuse the same profile when the merchant tries again.
                stage = 'prepared'
                renewal = previous.get('renewal',False)
            if stage not in ('disconnected','prepared','pending'):
                raise CardError('existing-card-attempt-check-status-or-disconnect')
            record = previous if stage != 'disconnected' else self._new_record(previous, expected)
            if stage == 'prepared' and not renewal and expected and not record['expectedVenderId']:
                record = dict(record, expectedVenderId=expected)
            permitted_target = record.get('identity',{}).get('venderId') or record['expectedVenderId']
            if expected and expected != permitted_target:
                raise CardError('different-card-attempt')
            attempt = record['attempt']
            if stage != 'pending':
                self.command()
                self.write(dict(record,status='pending',renewal=renewal,nativeLoginStarted=False,nativeLoginFinished=False))
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
                try:
                    subprocess.Popen([*self.worker_command,'--state',str(self.state),'--core',str(self.core),
                                      '_wait-for-jd',attempt], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name!='nt')
                except OSError:
                    self.write(record if stage=='prepared' else dict(record,status='disconnected'))
                    raise CardError('worker-start-failed') from None
        # The local service serves only this already-issued URL; retries can reattach
        # to the original attempt without ever submitting a second authorization.
        while time.monotonic()-began < 8.5:
            current = self.current()
            if current.get('attempt') != attempt:
                raise CardError('official-authorization-unavailable')
            if current.get('status') != 'pending':
                status = current.get('status')
                raise CardError(status if isinstance(status,str) and status in WORKER_FAILURES
                                else 'official-authorization-unavailable')
            if current.get('handoffPort'):
                response = queue.Queue(maxsize=1)
                def receive():
                    from multiprocessing.connection import Client
                    from multiprocessing import AuthenticationError
                    try:
                        with Client(('127.0.0.1',current['handoffPort']),authkey=bytes.fromhex(current['handoffKey'])) as client:
                            response.put(client.recv_bytes(16384).decode())
                    except (AuthenticationError,EOFError,OSError,ValueError):
                        response.put(None)
                threading.Thread(target=receive,daemon=True).start()
                try:value = response.get(timeout=max(.01,8.5-time.monotonic()+began))
                except queue.Empty:raise CardError('original-url-handoff-unavailable') from None
                if not value or authorization_url(value) != value or not self._active(attempt):
                    raise CardError('invalid-official-url')
                return value
            time.sleep(.08)
        raise CardError('initial-url-not-ready-check-original-attempt')

    def _active(self, attempt):
        current = self.current()
        return current.get('attempt') == attempt and current.get('status') == 'pending'

    def _finish(self, attempt, **changes):
        with self.lock():
            if not self._active(attempt):
                return False
            record = dict(self.current(), **changes)
            if record['status'] != 'pending':
                record.pop('handoffPort',None)
                record.pop('handoffKey',None)
            self.write(record)
            return True

    def _open_handoff(self, attempt, url, proc):
        from multiprocessing.connection import Listener
        key = secrets.token_bytes(32)
        listener = Listener(('127.0.0.1',0),authkey=key)
        def serve():
            while self._active(attempt):
                try:
                    with listener.accept() as connection:
                        # Callback and card must still belong to exactly this attempt
                        # each time a restarted frontend retrieves the original URL.
                        owners = self._owners()
                        allowed = (proc.poll() is None and self._active(attempt) and owners
                                   and all(self._belongs_to(pid,proc.pid) for pid in owners))
                        connection.send_bytes(url.encode() if allowed else b'')
                except (EOFError,OSError):
                    return
                except Exception:
                    continue
        threading.Thread(target=serve,daemon=True).start()
        self._finish(attempt,handoffPort=listener.address[1],handoffKey=key.hex())
        return listener

    def _owners(self):
        if os.name != 'nt':
            # macOS has system lsof even when launched with a minimal GUI PATH.
            exe = '/usr/sbin/lsof' if sys.platform == 'darwin' else 'lsof'
            result = subprocess.run([exe,'-nP','-iTCP:'+str(self.callback_port),'-sTCP:LISTEN','-t'],
                                    capture_output=True,timeout=2)
            if result.returncode not in (0,1) or result.stderr:
                raise CardError('unable-to-check-callback-owner')
            return {int(pid) for pid in result.stdout.split()}
        exe = Path(os.environ['SystemRoot'])/'System32/netstat.exe'
        result = subprocess.run([str(exe),'-ano','-p','tcp'],capture_output=True,timeout=2,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise CardError('unable-to-check-callback-owner')
        owners = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if (len(parts) >= 5 and parts[0] == b'TCP' and parts[1].endswith(f':{self.callback_port}'.encode())
                    and parts[3].upper() == b'LISTENING'):
                owners.add(int(parts[4]))
        return owners

    def _belongs_to(self, pid, root_pid):
        if os.name != 'nt':
            # Native login is the leader of its own session. A different session
            # cannot join its process group, including after the parent exits.
            try:
                return os.getsid(pid) == root_pid and os.getpgid(pid) == root_pid
            except ProcessLookupError:
                return False
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE,wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        if pid in self._callback_handles:
            return kernel.WaitForSingleObject(self._callback_handles[pid],0) == 258
        # Keep an object handle to the verified listener. Unlike a numeric PID
        # this still identifies it if a frozen executable's outer shell exits.
        handle = kernel.OpenProcess(0x00100001,False,pid)  # SYNCHRONIZE | PROCESS_TERMINATE
        if not handle:
            return False
        try:
            parents = _windows_process_parents()
            ancestor = pid
            visited = set()
            while ancestor and ancestor not in visited:
                if ancestor == root_pid and kernel.WaitForSingleObject(handle,0) == 258:
                    self._callback_handles[pid] = handle
                    return True
                visited.add(ancestor)
                ancestor = parents.get(ancestor)
            return False
        finally:
            if pid not in self._callback_handles:
                kernel.CloseHandle(handle)

    def _stop_native(self,proc):
        # Frozen official CLI versions can run the callback in a child of their loader.
        if os.name != 'nt':
            try:
                os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)
            return
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE,wintypes.DWORD)
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE,wintypes.UINT)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        for handle in self._callback_handles.values():
            try:
                if kernel.WaitForSingleObject(handle,0) == 258:
                    kernel.TerminateProcess(handle,1)
                    if kernel.WaitForSingleObject(handle,2000) != 0:
                        raise CardError('cannot-confirm-callback-stopped')
            finally:
                kernel.CloseHandle(handle)
        self._callback_handles.clear()
        if proc.poll() is None:
            program = Path(os.environ['SystemRoot'])/'System32/taskkill.exe'
            subprocess.run([str(program),'/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=4,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            proc.wait(timeout=2)

    def worker(self, attempt):
        from server import owned_credential_slot
        with self.lock('worker'):
            if not self._active(attempt):
                return 2
            record = self.current()
            profile, expected = record['profile'], record['expectedVenderId']
            extra = ['--vender-id',expected] if expected else []
            try:
                if self._owners():
                    raise CardError('callback-busy')
                if not record.get('initialized'):
                    if not self._finish(attempt,nativeInitStarted=True):
                        return 2
                    self._init_native(record)
                    self._finish(attempt,initialized=True)
                if not self._active(attempt):
                    return 2
                cmd = [*self.command(),'login','--profile',profile,'--no-browser','--timeout','300',*extra]
                if record.get('renewal'):
                    cmd.append('--force')
                if not self._finish(attempt,nativeLoginStarted=True,nativeLoginFinished=False):
                    return 2
                proc = None
                try:
                    proc = subprocess.Popen(cmd,env=self.environment(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',bufsize=1,
                                            start_new_session=os.name!='nt',
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    login = self._wait_login(proc, attempt)
                finally:
                    if proc is not None:
                        try:
                            self._stop_native(proc)
                        finally:
                            proc.stdout.close()
                    with self.lock():
                        latest = self.current()
                        if latest.get('attempt') == attempt:
                            self.write(dict(latest,nativeLoginFinished=True))
                account, _ = self.metadata(profile)
                if (login.get('ok') is not True or login.get('command') != 'login' or login.get('profile') != profile
                        or not login.get('home') or Path(login['home']).resolve() != self.home
                        or login.get('loginCompleted') is not True or login.get('tokenStored') is not True
                        or login.get('tokenMocked') is not False
                        or owned_credential_slot(login.get('tokenCredentialAccount'),profile) != account):
                    raise CardError('official-login-receipt-mismatch')
                identity = self.live_shop(profile)
                if ((expected and expected != identity['venderId']) or account[1] not in ('default',identity['venderId'])):
                    raise CardError('identity-mismatch')
                if record.get('renewal') and (any(identity[k] != record['identity'][k] for k in ('shopId','venderId'))
                        or sha256(account[0].encode()).hexdigest() != record['slotDigest']):
                    raise CardError('identity-mismatch')
                self._finish(attempt,status='ready',identity=identity,slotDigest=sha256(account[0].encode()).hexdigest())
            except (CardError,OSError,ValueError,subprocess.SubprocessError,RuntimeError) as error:
                if isinstance(error,CardError):
                    reason = str(error)
                elif isinstance(error,subprocess.TimeoutExpired):
                    reason = 'worker-operation-timed-out'
                elif isinstance(error,PermissionError):
                    reason = 'worker-permission-denied'
                else:
                    reason = 'needs-reconciliation'
                self._finish(attempt,status=reason)
                return 2
        return 0

    def _wait_login(self, proc, attempt):
        """Use only the native authorization URL, and only while the native listener is owned."""
        lines = queue.Queue()
        def pump():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()
        transcript = ''
        url, handoff = None, None
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            if not self._active(attempt):
                raise CardError('disconnected')
            if url and not handoff:
                owners = self._owners()
                if owners:
                    if proc.poll() is not None or not all(self._belongs_to(pid,proc.pid) for pid in owners):
                        raise CardError('callback-busy')
                    handoff = self._open_handoff(attempt,url,proc)
            try:line = lines.get(timeout=.12)
            except queue.Empty:continue
            if line is None:
                break
            transcript = (transcript + line)[-262144:]
            if not url:
                url = authorization_url(self.shoplib.strip_ansi(line))
        if handoff:handoff.close()
        code = proc.wait(timeout=2)
        if not url:
            raise CardError('official-login-ended-before-url')
        if not handoff or code != 0:
            raise CardError('official-login-incomplete')
        return self.shoplib.extract_json(transcript) or {}

    def disconnect(self):
        with self.lock():
            record = self.current()
            if not record or record['status'] == 'disconnected':
                return {'status':'disconnected','remoteRevocation':'unverified'}
            record.pop('handoffKey',None)
            record.pop('handoffPort',None)
            self.write(dict(record,status='disconnecting'))
        with self.lock('worker', timeout=12), self.lock():
            current = self.current()
            if current.get('attempt') != record['attempt']:
                raise CardError('connection-changed')
            if current.get('status') == 'disconnected':
                return {'status':'disconnected','localAccess':False,'remoteRevocation':'unverified'}
            profile = current['profile']
            if current.get('nativeLoginStarted') and not current.get('nativeLoginFinished'):
                raise CardError('cannot-confirm-callback-stopped')
            from heideng_merchant.safety import safe_join
            config_exists = safe_join(self.home,'profiles/'+profile+'.json').exists()
            if not config_exists and (current.get('initialized') or current.get('nativeInitStarted')
                                      or current.get('nativeLoginStarted')):
                raise CardError('cannot-prove-local-logout-scope')
            if config_exists:
                account, flags = self.metadata(profile,require_active=False)
                if flags.get('oauthTokenStored') is True and not account:
                    raise CardError('cannot-prove-local-logout-scope')
                if (account and current.get('slotDigest') and
                        sha256(account[0].encode()).hexdigest() != current['slotDigest']):
                    raise CardError('cannot-prove-local-logout-scope')
                # Read official status even before first consent: CLI init can store app credentials.
                if flags.get('oauthTokenStored') is not False or flags.get('appSecretStored') is not False or current.get('initialized'):
                    result = self.native(['auth','logout','--profile',profile], 7)
                    if result.get('ok') is not True or result.get('profile') != profile:
                        raise CardError('official-local-logout-unverified')
                    # 0.3.7 clears default_profile during logout, so a subsequent bare
                    # status would describe a different profile. Use the scoped native
                    # deletion receipt instead, requiring positive evidence for each
                    # credential that the CLI reported as present before logout.
                    from server import owned_credential_slot
                    deleted = result.get('deletedCredentials') or []
                    if flags.get('oauthTokenStored') is True and not any(
                        row.get('type')=='token' and row.get('deleted') is True and
                        owned_credential_slot(row.get('account'),profile)==account for row in deleted
                    ):
                        raise CardError('official-local-logout-unverified')
                    if flags.get('appSecretStored') is True and not any(
                        row.get('type')=='appSecret' and row.get('deleted') is True and
                        str(row.get('account','')).removeprefix('jdo-cli:').split(':')[:2]==['appsecret',profile]
                        for row in deleted
                    ):
                        raise CardError('official-local-logout-unverified')
            self.write(dict(current,status='disconnected'))
            return {'status':'disconnected','localAccess':False,'remoteRevocation':'unverified'}


def main(argv=None, *, native_command=None, worker_command=None, callback_port=9001):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,default=Path.home()/'.heideng-wb-jd-card')
    parser.add_argument('--core',type=Path,default=Path(os.environ.get('HEIDENG_MERCHANT_PACKAGE') or Path(__file__).resolve().parents[1]))
    commands = parser.add_subparsers(dest='command',required=True)
    auth = commands.add_parser('auth')
    auth.add_argument('--expect-vender-id',default='')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--expect-vender-id',default='')
    for name in ('status','identity','unAuth'):commands.add_parser(name)
    commands.add_parser('_wait-for-jd').add_argument('attempt')
    args = parser.parse_args(argv)
    try:
        card = Card(args.state,args.core,native_command=native_command,worker_command=worker_command,callback_port=callback_port)
        if args.command == 'auth':
            print(card.auth(args.expect_vender_id),flush=True)
            return 0
        if args.command == '_wait-for-jd':
            return card.worker(args.attempt)
        if args.command == 'prepare':
            print(json.dumps(card.prepare(args.expect_vender_id)))
            return 0
        value = card.disconnect() if args.command == 'unAuth' else card.status(live=args.command=='identity')
        print(json.dumps(value,ensure_ascii=False))
        return 0 if value['status'] in ('ready','disconnected') and (args.command=='unAuth' or value['status']=='ready') else 2
    except (CardError,ValueError,ImportError,OSError,RuntimeError,subprocess.SubprocessError) as error:
        print(json.dumps({'status':str(error) if isinstance(error,CardError) else 'card-operation-unavailable','matched':False}))
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
