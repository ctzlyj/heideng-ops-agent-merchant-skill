"""Read-only worker liveness and bounded public diagnostics; never kill by PID."""
from __future__ import annotations
import os,re,time
from pathlib import Path
from .safety import SafetyError,atomic_json,read_json,safe_join
from .state import FileLock

EVENTS={'worker-start','worker-failed','worker-finished','flow-stage','worker-reconciled'}
STAGES={'starting_worker','initializing_worker','created','waiting_login','waiting_shop_confirmation','waiting_callback_server','waiting_oauth','verifying_cli','ready','identity_mismatch','oauth_failed','auth_outcome_unknown','cancelled','timed_out','browser_failed'}

def process_state(pid):
 if type(pid)!=int or not 0<pid<=0xffffffff:return 'unknown'
 if os.name!='nt':
  try:os.kill(pid,0)
  except ProcessLookupError:return 'exited'
  except (PermissionError,OSError):return 'unknown'
  return 'alive'
 import ctypes
 from ctypes import wintypes
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
 kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
 handle=kernel.OpenProcess(0x00100000,False,pid) # SYNCHRONIZE only, no termination permission
 if not handle:return 'exited' if ctypes.get_last_error()==87 else 'unknown'
 try:
  result=kernel.WaitForSingleObject(handle,0)
  return 'exited' if result==0 else 'alive' if result==258 else 'unknown'
 finally:kernel.CloseHandle(handle)

def record_event(state,job,event,data):
 if not isinstance(job,str) or not re.fullmatch('[a-f0-9]{24}',job) or event not in EVENTS:raise SafetyError('auth-diagnostic-event-required')
 path=safe_join(Path(state),'auth/events/'+job+'.json')
 item={'time':time.time(),'taskId':job,'event':event}
 if data.get('stage') in STAGES:item['stage']=data['stage']
 if data.get('status') in {'running','failed','unknown','completed','cancelled'}:item['status']=data['status']
 item['authorizationStarted']=data.get('authorizationStarted') is True
 try:
  with FileLock(path.with_suffix('.lock'),timeout=.1):
   previous=read_json(path,[])
   if not isinstance(previous,list):previous=[]
   atomic_json(path,(previous+[item])[-64:])
 except (OSError,SafetyError):pass # Diagnostic I/O must never alter authorization outcome.
