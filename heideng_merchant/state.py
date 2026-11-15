"""Cross-process locks and an independent state namespace."""
import os,time,threading
from pathlib import Path
from .safety import is_linked,SafetyError

class FileLock:
 def __init__(self,path:Path,timeout=5):self.path=Path(path);self.timeout=timeout;self.stream=None;self.acquired=False;self.owner_thread=None
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
     import msvcrt
     msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
    else:
     import fcntl
     fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    self.acquired=True;self.owner_thread=threading.get_ident();return self
   except OSError:
    if time.monotonic()>=deadline:self.stream.close();raise SafetyError('resource-busy') from None
    time.sleep(.025)
 def __exit__(self,*args):
  self.stream.seek(0)
  if os.name=='nt':
   import msvcrt
   msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
  else:
   import fcntl
   fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
  self.stream.close();self.acquired=False;self.owner_thread=None

def merchant_home(home=None):
 if home:return Path(home).resolve()/'.heideng-merchant'
 return Path(os.environ.get('HEIDENG_MERCHANT_HOME',Path.home()/'.heideng-merchant')).resolve()
