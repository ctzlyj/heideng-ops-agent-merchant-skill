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
 result={key:source[key] for key in ('SystemRoot','WINDIR','ProgramFiles','ProgramFiles(x86)','PATH','PATHEXT','TEMP','TMP','LANG') if key in source}
 home=Path(home).resolve()
 result.update(HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData'/'Roaming'),LOCALAPPDATA=str(home/'AppData'/'Local'),PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
 return result

def redact(value,secrets=()):
 if isinstance(value,dict):return {k:('[REDACTED]' if re.search(r'authorization|cookie|token|secret|password|api[_-]?key|credential',str(k),re.I) else redact(v,secrets)) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [redact(v,secrets) for v in value]
 if not isinstance(value,str):return value
 for secret in secrets:
  if secret:value=value.replace(secret,'[REDACTED]')
 value=re.sub(r'(?i)Bearer\s+[^\s,;\"\x27]+','Bearer [REDACTED]',value)
 value=re.sub(r'(?i)(authorization|cookie|token|api[_-]?key|secret|password)\s*[:=]\s*[^\n;]+',lambda m:m.group(1)+'=[REDACTED]',value)
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
