"""Filesystem, environment and output boundaries; standard library only."""
from __future__ import annotations
import json, os, re, stat, tempfile
from pathlib import Path

class SafetyError(RuntimeError): pass

def is_linked(path):
 try:metadata=Path(path).lstat()
 except FileNotFoundError:return False
 return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))

RESERVED={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}

def safe_join(root: Path, relative: str) -> Path:
 root=Path(root).absolute()
 if not isinstance(relative,str) or not relative or relative.startswith('/') or any(c in relative for c in ('\\',':','%','\x00')):raise SafetyError('unsafe-relative-path')
 parts=relative.split('/')
 if any(p in ('','.', '..') or p!=p.rstrip(' .') or any(ord(c)<32 for c in p) or p.split('.')[0].upper() in RESERVED for p in parts):raise SafetyError('unsafe-relative-path')
 if is_linked(root):raise SafetyError('linked-root')
 current=root
 for part in parts:
  current=current/part
  if is_linked(current):raise SafetyError('linked-path')
 try:current.resolve().relative_to(root.resolve())
 except ValueError:raise SafetyError('path-escape') from None
 return current

def clean_environment(home:Path, inherited:dict|None=None) -> dict:
 source=os.environ if inherited is None else inherited
 allowed=('SystemRoot','SystemDrive','WINDIR','ProgramFiles','ProgramFiles(x86)','PATH','PATHEXT','TEMP','TMP','LANG')
 # Windows host dictionaries commonly uppercase keys. Keep only the same safe OS allowlist.
 lookup={str(k).casefold():v for k,v in source.items()} if os.name=='nt' else source
 result={key:lookup[key.casefold() if os.name=='nt' else key] for key in allowed if (key.casefold() if os.name=='nt' else key) in lookup}
 if os.name=='nt':
  for key in ('SystemRoot','WINDIR'):
   if not result.get(key) and os.environ.get(key):result[key]=os.environ[key]
 home=Path(home).resolve()
 result.update(HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData'/'Roaming'),LOCALAPPDATA=str(home/'AppData'/'Local'),PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
 return result

_SENSITIVE_GENERAL = r'authorization|cookie|token|secret|password|api[_-]?key|credential|pt[_-]?(?:key|pin)'
_SENSITIVE_ALIASES = r'thor|eid|fp|sso_ticket|tgt|device_id|deviceId|signature'
_SENSITIVE = _SENSITIVE_GENERAL+r'|(?:^|_)(?:'+_SENSITIVE_ALIASES+r')(?:_|$)'
_STRING_SENSITIVE = _SENSITIVE_GENERAL+r'|(?<![A-Za-z0-9])(?:'+_SENSITIVE_ALIASES+r')(?:_[A-Za-z0-9_]*)?'

_PUBLIC_BOOLEAN_FIELDS={'authorizationOutcomeUnknown','authorizationStarted','credentialExecutionAvailable'}

def redact(value,secrets=()):
 if isinstance(value,dict):
  return {(redact(k,secrets) if isinstance(k,str) else k):('[REDACTED]' if re.search(_SENSITIVE,str(k),re.I) and not (k in _PUBLIC_BOOLEAN_FIELDS and type(v) is bool) else redact(v,secrets)) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [redact(v,secrets) for v in value]
 if not isinstance(value,str):return value
 # JSON in scalar business fields must use the same key rules as dictionaries,
 # including escaped keys and nested JSON. Preserve ordinary text byte-for-byte.
 if value.lstrip().startswith(('{','[')):
  try:
   decoded=json.loads(value)
   cleaned=redact(decoded,secrets)
   if cleaned!=decoded:return json.dumps(cleaned,ensure_ascii=False,separators=(',',':'))
  except (ValueError,TypeError):pass
  except RecursionError:return '[REDACTED]'
 for secret in secrets:
  if secret:value=value.replace(secret,'[REDACTED]')
 value=re.sub(r'(?i)Bearer\s+[^\s,;\"\x27]+','Bearer [REDACTED]',value)
 value=re.sub(r'(?i)('+_STRING_SENSITIVE+r')[\"\']?\s*[:=]\s*[^\n;]+',lambda m:m.group(1)+'=[REDACTED]',value)
 return value

def atomic_json(destination:Path,value):
 destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
 raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
 descriptor,name=tempfile.mkstemp(prefix='.'+destination.name+'.',suffix='.tmp',dir=destination.parent)
 try:
  with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(name,destination)
 finally:
  try:Path(name).unlink()
  except FileNotFoundError:pass

def read_json(path:Path,default=None):
 if not Path(path).is_file():return default
 try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
 except (ValueError,OSError):raise SafetyError('invalid-state-json') from None

def file_sha(path:Path):
 import hashlib
 digest=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
 return digest.hexdigest()
