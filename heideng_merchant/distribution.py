"""Verified standalone installs, immutable receipts and recoverable switches."""
from __future__ import annotations
import hashlib,json,os,re,shutil,stat,tempfile,time,uuid,zipfile
from pathlib import Path
from . import SKILL_NAME
from .safety import is_linked,SafetyError,safe_join,file_sha,atomic_json,read_json
from .state import FileLock

MAX_BYTES=64*1024*1024
MANIFEST='package-manifest.json'
RECEIPT='.merchant-install.json'

def admissible_file(name):
 if name in {'SKILL.md','VERSION','README.md','NOTICE.md','registry.json','install.py','package-files.json',MANIFEST}:return True
 if re.fullmatch(r'(?:heideng_merchant|scripts)/[a-zA-Z0-9_-]+\.py|references/[a-zA-Z0-9_-]+\.md',name):return True
 parts=name.split('/')
 if len(parts)<3 or parts[0]!='mature' or parts[1] not in {'connection','materials','listing','collection','comparison','diagnosis','refresh','video'}:return False
 # Path safety remains safe_join's responsibility; binary templates need their original Unicode names.
 return Path(name).name=='LICENSE' or Path(name).suffix.lower() in {'.py','.md','.json','.mjs','.js','.txt','.xlsx','.csv','.ps1','.sh','.svg','.html','.cjs'}

def version_key(value):
 if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):raise SafetyError('invalid-version')
 return tuple(map(int,value.split('.')))

def source_files(source):
 source=Path(source).resolve();files={}
 declaration=read_json(source/'package-files.json')
 if declaration is not None:
  if declaration.get('schemaVersion')!=1 or not isinstance(declaration.get('files'),list):raise SafetyError('invalid-package-declaration')
  candidates=[*declaration['files'],'package-files.json']
  mature=source/'mature'
  if mature.exists():
   for component in sorted(mature.iterdir()):
    if not component.is_dir() or is_linked(component):raise SafetyError('linked-mature-source')
    metadata=read_json(component/'provenance.json')
    if not isinstance(metadata,dict) or metadata.get('license') not in {'MIT','owner-authorized-distribution'}:raise SafetyError('mature-distribution-permission-required')
    if metadata.get('license')=='owner-authorized-distribution':
     permission=metadata.get('permissionRecord')
     if not permission or permission not in metadata.get('files',{}):raise SafetyError('mature-distribution-permission-record-required')
    for rel,record in metadata.get('files',{}).items():
     path=safe_join(component,rel)
     if is_linked(path) or not path.is_file() or file_sha(path)!=record.get('sha256'):raise SafetyError('mature-source-modified')
     candidates.append(path.relative_to(source).as_posix())
    candidates.append((component/'provenance.json').relative_to(source).as_posix())
  for name in sorted(set(candidates)):
   path=safe_join(source,name)
   if is_linked(path) or not path.is_file() or not admissible_file(name):raise SafetyError('unapproved-distribution-file')
   data=path.read_bytes()
   files[name]=data if name.startswith("mature/") else data.replace(b"\r\n",b"\n")
  if not {'SKILL.md','VERSION'}<=files.keys():raise SafetyError('missing-package-entry')
  return files
 candidates=['SKILL.md','VERSION','README.md','NOTICE.md','registry.json','install.py']
 for folder in ('heideng_merchant','scripts','references'):
  parent=source/folder
  if is_linked(parent):raise SafetyError('linked-source')
  if parent.is_dir():candidates.extend(p.relative_to(source).as_posix() for p in parent.rglob('*') if p.suffix in ('.py','.md','.json') and '__pycache__' not in p.parts)
 for name in sorted(set(candidates)):
  p=safe_join(source,name)
  if p.is_file() and admissible_file(name):files[name]=p.read_bytes().replace(b'\r\n',b'\n')
 if not {'SKILL.md','VERSION'}<=files.keys():raise SafetyError('missing-package-entry')
 if not re.search(r'^name:\s*'+re.escape(SKILL_NAME)+r'\s*$',files['SKILL.md'].decode('utf-8-sig'),re.M):raise SafetyError('wrong-skill-identity')
 return files

def build_bundle(source,output,version):
 version_key(version);files=source_files(source)
 if files['VERSION'].decode('utf-8-sig').strip()!=version:raise SafetyError('package-version-mismatch')
 manifest={'schemaVersion':1,'skill':SKILL_NAME,'version':version,'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}}
 files[MANIFEST]=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for name,raw in sorted(files.items()):
   info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,raw)
 return output

def validate_archive(archive):
 archive=Path(archive)
 if not archive.is_file() or archive.stat().st_size>MAX_BYTES:raise SafetyError('invalid-archive-size')
 try:
  with zipfile.ZipFile(archive) as z:
   entries=z.infolist();seen=set();raw={};total=0
   if len(entries)>500:raise SafetyError('too-many-package-files')
   for item in entries:
    safe_join(Path(tempfile.gettempdir()),item.filename)
    if not admissible_file(item.filename):raise SafetyError('unapproved-distribution-file')
    name=item.filename.casefold()
    if name in seen:raise SafetyError('duplicate-package-path')
    seen.add(name);mode=item.external_attr>>16
    if stat.S_ISLNK(mode) or item.is_dir() or item.flag_bits&1:raise SafetyError('invalid-package-member')
    total+=item.file_size
    if item.file_size>16*1024*1024 or total>MAX_BYTES:raise SafetyError('expanded-package-too-large')
    raw[item.filename]=z.read(item)
 except (zipfile.BadZipFile,KeyError,OSError):raise SafetyError('invalid-package-archive') from None
 try:manifest=json.loads(raw[MANIFEST])
 except (KeyError,ValueError):raise SafetyError('missing-package-manifest') from None
 if manifest.get('schemaVersion')!=1 or manifest.get('skill')!=SKILL_NAME:raise SafetyError('wrong-package-identity')
 version_key(manifest.get('version'))
 hashes=manifest.get('files')
 if not isinstance(hashes,dict) or set(hashes)!=set(raw)-{MANIFEST}:raise SafetyError('package-file-set-mismatch')
 if not {'SKILL.md','VERSION'}<=hashes.keys():raise SafetyError('missing-package-entry')
 for name,sha in hashes.items():
  if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha) or hashlib.sha256(raw[name]).hexdigest()!=sha:raise SafetyError('package-file-hash-mismatch')
 if raw['VERSION'].decode('utf-8-sig').strip()!=manifest['version']:raise SafetyError('package-version-mismatch')
 if not re.search(r'^name:\s*'+re.escape(SKILL_NAME)+r'\s*$',raw['SKILL.md'].decode('utf-8-sig'),re.M):raise SafetyError('wrong-skill-identity')
 return manifest,raw

def verify_install(target):
 target=Path(target)
 if target.name!=SKILL_NAME or is_linked(target):return {'valid':False,'reason':'wrong-install-directory'}
 receipt=read_json(target/RECEIPT)
 if not isinstance(receipt,dict) or receipt.get('skill')!=SKILL_NAME:return {'valid':False,'reason':'unmanaged-directory'}
 try:
  expected=receipt['files'];actual=set()
  for p in target.rglob('*'):
   if is_linked(p):raise SafetyError('linked-install')
   if p.is_file() and p.name!=RECEIPT and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'):actual.add(p.relative_to(target).as_posix())
  if set(expected)!=actual:raise SafetyError('local-file-set-changed')
  for name,sha in expected.items():
   if file_sha(safe_join(target,name))!=sha:raise SafetyError('local-file-changed')
 except (KeyError,OSError,SafetyError):return {'valid':False,'reason':'locally-modified'}
 return {'valid':True,'version':receipt['version'],'receipt':receipt}

def _target(target):
 target=Path(target).absolute()
 if target.name!=SKILL_NAME or target.parent==target or is_linked(target):raise SafetyError('wrong-install-directory')
 # Check every existing ancestor; never follow a junction into another namespace.
 for ancestor in (target.parent,*target.parents):
  if is_linked(ancestor):raise SafetyError('linked-install-parent')
 target.parent.mkdir(parents=True,exist_ok=True)
 return target

def _owned(path,target,kind):
 p=Path(path).absolute()
 if p.parent!=target.parent or not p.name.startswith('.'+SKILL_NAME+'.'+kind+'-') or is_linked(p):raise SafetyError('unsafe-recovery-path')
 return p

def _remove_owned(path,target,kind):
 p=_owned(path,target,kind)
 if p.exists():
  for child in p.rglob('*'):
   if is_linked(child):raise SafetyError('linked-recovery-file')
  shutil.rmtree(p)

def busy(state):
 # Mature foreground execution holds this same install.lock for its full lifetime.
 # A connector's own pending job also keeps an update deferred, without a new auth FSM.
 pending=read_json(Path(state)/'linker'/'pending.json')
 return bool(pending and pending.get('status') not in ('ready','completed','cancelled','error'))

def _replace_directory(source,target):
 """Retry only an unchanged local directory switch under transient Windows locks.

 A failed rename is not a business submission. Never overwrite a newly appeared
 destination or retry a replacement source; persistent failures keep the journal.
 """
 source=Path(source);target=Path(target)
 if is_linked(source) or not source.is_dir():raise SafetyError('directory-switch-source-changed')
 original=source.stat();identity=(original.st_dev,original.st_ino)
 delays=(.05,.1,.2,.4,.8)
 for attempt in range(len(delays)+1):
  if target.exists() or is_linked(target):raise SafetyError('directory-switch-target-changed')
  if is_linked(source) or not source.is_dir():raise SafetyError('directory-switch-source-changed')
  current=source.stat()
  if (current.st_dev,current.st_ino)!=identity:raise SafetyError('directory-switch-source-changed')
  try:
   os.replace(source,target);return
  except OSError as exc:
   if getattr(exc,'winerror',None) not in (5,32,33) or attempt==len(delays):raise
   time.sleep(delays[attempt])

def _recover(target,state):
 journal=read_json(Path(state)/'install-journal.json')
 if not journal:return
 if journal.get('target')!=str(target):raise SafetyError('recovery-target-mismatch')
 stage=_owned(journal['stage'],target,'stage');backup=_owned(journal['backup'],target,'backup')
 if target.exists():
  if not verify_install(target)['valid']:raise SafetyError('recovery-local-change')
 elif backup.exists():_replace_directory(backup,target)
 elif stage.exists():raise SafetyError('interrupted-first-install-review-required')
 _remove_owned(stage,target,'stage')
 (Path(state)/'install-journal.json').unlink(missing_ok=True)

def install_archive(archive,target,state,*,expected_sha):
 target=_target(target);state=Path(state);state.mkdir(parents=True,exist_ok=True)
 if not re.fullmatch('[0-9a-f]{64}',str(expected_sha)) or file_sha(archive)!=expected_sha:raise SafetyError('archive-sha256-mismatch')
 manifest,raw=validate_archive(archive)
 with FileLock(state/'install.lock'):
  if busy(state):raise SafetyError('active-task-update-or-recovery-deferred')
  _recover(target,state)
  if target.exists():
   current=verify_install(target)
   if not current['valid']:raise SafetyError(current['reason'])
   from .installation_guard import check_legacy_update,quiesce_mature_connector
   check_legacy_update(target,state,current['version'])
   quiesce_mature_connector(target,state)
   if current['version']==manifest['version']:
    if current['receipt']['archiveSha256']==expected_sha:return {'status':'unchanged','version':manifest['version'],'target':str(target)}
    raise SafetyError('same-version-different-artifact')
   if version_key(manifest['version'])<=version_key(current['version']):raise SafetyError('downgrade-refused')
  if busy(state):raise SafetyError('active-task-update-deferred')
  ident=uuid.uuid4().hex;stage=target.parent/('.'+SKILL_NAME+'.stage-'+ident);backup=target.parent/('.'+SKILL_NAME+'.backup-'+ident)
  stage.mkdir()
  for name,data in raw.items():p=safe_join(stage,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  hashes={name:hashlib.sha256(data).hexdigest() for name,data in raw.items()}
  atomic_json(stage/RECEIPT,{'skill':SKILL_NAME,'version':manifest['version'],'archiveSha256':expected_sha,'files':hashes})
  atomic_json(state/'install-journal.json',{'target':str(target),'stage':str(stage),'backup':str(backup)})
  had_previous=target.exists()
  try:
   if had_previous:_replace_directory(target,backup)
   _replace_directory(stage,target)
  except OSError:
   if not target.exists() and backup.exists():_replace_directory(backup,target)
   raise SafetyError('install-switch-failed-recoverable') from None
  atomic_json(state/'install-history.json',{'target':str(target),'previous':str(backup) if had_previous else None,'version':manifest['version']})
  (state/'install-journal.json').unlink()
  return {'status':'installed','version':manifest['version'],'target':str(target),'previousVersionAvailable':had_previous}

def rollback(target,state):
 target=_target(target);state=Path(state)
 with FileLock(state/'install.lock'):
  if busy(state):raise SafetyError('active-task-rollback-or-recovery-deferred')
  _recover(target,state)
  if busy(state):raise SafetyError('active-task-rollback-deferred')
  info=read_json(state/'install-history.json',{})
  if info.get('target')!=str(target) or not info.get('previous'):raise SafetyError('no-verified-rollback')
  previous=_owned(info['previous'],target,'backup')
  # Backup directory has a different name; verification uses its trusted receipt/file hashes.
  check=read_json(previous/RECEIPT,{})
  if check.get('skill')!=SKILL_NAME:raise SafetyError('invalid-rollback-receipt')
  for name,sha in check.get('files',{}).items():
   if file_sha(safe_join(previous,name))!=sha:raise SafetyError('rollback-files-modified')
  if not verify_install(target)['valid']:raise SafetyError('locally-modified')
  displaced=target.parent/('.'+SKILL_NAME+'.backup-'+uuid.uuid4().hex)
  _replace_directory(target,displaced)
  try:_replace_directory(previous,target)
  except OSError:_replace_directory(displaced,target);raise SafetyError('rollback-switch-failed') from None
  atomic_json(state/'install-history.json',{'target':str(target),'previous':str(displaced),'version':check['version']})
  return {'status':'rolled-back','version':check['version']}
