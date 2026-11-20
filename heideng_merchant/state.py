"""Cross-process locks and an independent state namespace."""
import os,time,threading
from pathlib import Path
from .safety import is_linked,SafetyError

class FileLock:
 def __init__(self,path:Path,timeout=5,*,shared=False):self.path=Path(path);self.timeout=timeout;self.shared=shared;self.stream=None;self.acquired=False;self.owner_thread=None
 def _windows_lock(self,unlock=False):
  import ctypes,msvcrt
  from ctypes import wintypes
  if not unlock:
   class Overlapped(ctypes.Structure):
    _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
   self.overlapped=Overlapped();self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
   self.kernel.LockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
   self.kernel.LockFileEx.restype=wintypes.BOOL
   self.kernel.UnlockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
   self.kernel.UnlockFileEx.restype=wintypes.BOOL
  handle=msvcrt.get_osfhandle(self.stream.fileno())
  success=self.kernel.UnlockFileEx(handle,0,1,0,ctypes.byref(self.overlapped)) if unlock else self.kernel.LockFileEx(handle,1|(0 if self.shared else 2),0,1,0,ctypes.byref(self.overlapped))
  if not success:raise ctypes.WinError(ctypes.get_last_error())
 def require_owned(self,path):
  if not self.acquired or self.stream is None or self.stream.closed or self.path.resolve()!=Path(path).resolve() or self.owner_thread!=threading.get_ident():raise SafetyError('existing-same-owner-install-guard-required')
 def __enter__(self):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  if is_linked(self.path):raise SafetyError('linked-lock')
  self.stream=self.path.open('a+b')
  if self.path.stat().st_size==0:self.stream.write(b'0');self.stream.flush()
  deadline=time.monotonic()+self.timeout
  while True:
   try:
    self.stream.seek(0)
    if os.name=='nt':
     self._windows_lock()
    else:
     import fcntl
     fcntl.flock(self.stream.fileno(),(fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX)|fcntl.LOCK_NB)
    self.acquired=True;self.owner_thread=threading.get_ident();return self
   except OSError:
    if time.monotonic()>=deadline:self.stream.close();raise SafetyError('resource-busy') from None
    time.sleep(.025)
 def __exit__(self,*args):
  self.stream.seek(0)
  if os.name=='nt':
   self._windows_lock(unlock=True)
  else:
   import fcntl
   fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
  self.stream.close();self.acquired=False;self.owner_thread=None

def merchant_home(home=None):
 if home:return Path(home).resolve()/'.heideng-merchant'
 return Path(os.environ.get('HEIDENG_MERCHANT_HOME',Path.home()/'.heideng-merchant')).resolve()


def installed_state(package, default=None):
    from .safety import read_json

    if os.environ.get('HEIDENG_MERCHANT_HOME') and default is None:
        return merchant_home()
    recorded = read_json(Path(package) / '.merchant-install.json', {}).get('stateRoot')
    if recorded and Path(recorded).is_absolute():
        return Path(recorded).resolve()
    return default or merchant_home()


def install_state(target, home=None, explicit=None):
    from hashlib import sha256
    from .safety import atomic_json, read_json

    specified = explicit or (not home and os.environ.get('HEIDENG_MERCHANT_HOME'))
    root = Path(specified).resolve() if specified else installed_state(target, merchant_home(home))
    target = str(Path(target).resolve())

    def owner(path):
        return (read_json(path / 'updates/settings.json', {}).get('target')
                or read_json(path / 'installation-target.json', {}).get('target'))

    with FileLock(root / 'installation-target.lock'):
        bound = owner(root)
        if bound and bound != target:
            if specified:
                raise SafetyError('update-target-changed-use-explicit-isolated-state-or-maintenance-migration')
            suffix = sha256(os.path.normcase(target).encode()).hexdigest()[:16]
            alternate = root.with_name(f'{root.name}-{suffix}')
            with FileLock(alternate / 'installation-target.lock'):
                if owner(alternate) not in (None, target):
                    raise SafetyError('isolated-state-target-mismatch')
                atomic_json(alternate / 'installation-target.json', {'target': target})
            return alternate
        atomic_json(root / 'installation-target.json', {'target': target})
    return root


def process_alive(pid):
 """Conservative process liveness; never signals/terminates another process."""
 if type(pid) is not int or pid <= 0:return None
 if pid == os.getpid():return True
 if os.name == 'nt':
  import ctypes
  from ctypes import wintypes
  kernel=ctypes.WinDLL('kernel32',use_last_error=True)
  kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
  kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
  kernel.CloseHandle.argtypes=[wintypes.HANDLE]
  handle=kernel.OpenProcess(0x1000,False,pid)
  if not handle:return False if ctypes.get_last_error()==87 else None
  try:
   code=wintypes.DWORD()
   return code.value==259 if kernel.GetExitCodeProcess(handle,ctypes.byref(code)) else None
  finally:kernel.CloseHandle(handle)
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
 except (PermissionError,OSError):return None
