"""Worker originals and command receipts; never inferred launch/dispatch absence."""
import json,re,time,uuid
from pathlib import Path
from . import VERSION
from .operations import digest
from .safety import SafetyError,safe_join,read_json,redact,file_sha
from .short_titles import ShortTitlePlans
from .short_title_imports import ShortTitleImports
from .video_delivery import _once

ID=re.compile('[a-f0-9]{24}');REQ=re.compile('[a-f0-9]{32}');HASH=re.compile('[a-f0-9]{64}')
ACTIONS={'approve','execute','recover','results','effects','stop'}
COMMAND_FOLDERS=('short-title-worker-commands','short-title-worker-dispatches','short-title-worker-results')
NATIVE_FOLDERS=('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors','short-title-import-approvals','short-title-result-observations','short-title-result-receipts','short-title-effect-observations','short-title-effect-receipts')
PUBLIC={'status','reason','importId','fingerprint','submittedBatchCount','unknownBatchCount','rowResultsVerified','actualTitlesVerified','formalAuditVerified','portalVerified','healthVerified','imported','retryAuthorized','effectObservationSequence','currentEffectSourceVerified','currentTaskAnchorMatched','currentResultSourceVerified','runtimeVersion','approvalCurrentlyValid','batchCount','proposedRowCount','approvedRowCount','effectEvidenceVersion','nativeHealthSourcesVerified','targetHealthRequirementsSatisfied','currentNativeHealthSourceVerified'}

def _error():raise SafetyError('original-short-title-worker-evidence-required')
def _id(value,pattern=ID):
 if not isinstance(value,str) or pattern.fullmatch(value) is None:_error()
 return value

def file(state,folder,worker_id,name=None):
 relative=folder+'/'+_id(worker_id)+(('.json') if name is None else '/'+name+'.json')
 return safe_join(Path(state).absolute(),relative)

def _read(path):
 if not path.exists():return None
 if not path.is_file() or not 0<path.stat().st_size<=16*1024*1024:_error()
 def unique(pairs):
  out={}
  for key,value in pairs:
   if key in out:_error()
   out[key]=value
  return out
 try:return json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique,parse_constant=lambda value:_error())
 except (ValueError,OSError,RecursionError):_error()

def _runtime(value):
 if not isinstance(value,dict) or set(value)!={'version','archiveSha256','filesSha256'} or not isinstance(value['version'],str) or re.fullmatch(r'\d+\.\d+\.\d+',value['version']) is None or any(not isinstance(value[k],str) or HASH.fullmatch(value[k]) is None for k in ('archiveSha256','filesSha256')):_error()

def runtime_binding(target=None):
 from .distribution import verify_install
 check=verify_install(Path(__file__).resolve().parents[1] if target is None else target)
 if check.get('valid') is not True or check.get('version')!=VERSION:raise SafetyError('verified-current-managed-worker-install-required')
 receipt=check['receipt'];out={'version':receipt['version'],'archiveSha256':receipt['archiveSha256'],'filesSha256':digest(receipt['files'])};_runtime(out);return out

def create_job(state,plan_id,client,binding,*,source_id=None,foreground=True):
 _runtime(binding)
 if foreground is not True:raise SafetyError('foreground-owned-merchant-browser-required')
 p=ShortTitlePlans(state,client).plan(plan_id)
 if not p['scope']['changes']:_error()
 scope={'kind':'native-short-title-worker','planId':plan_id,'planFingerprint':p['fingerprint'],'shop':p['scope']['shop'],'sourceId':_id(source_id or uuid.uuid4().hex[:24]),'runtime':binding,'foreground':True}
 fp=digest(scope);job={'workerId':fp[:24],'fingerprint':fp,'scope':scope};_once(file(state,'short-title-workers',job['workerId']),job);return job

def read_job(state,worker_id):
 value=_read(file(state,'short-title-workers',worker_id))
 if not isinstance(value,dict) or set(value)!={'workerId','fingerprint','scope'} or value['workerId']!=worker_id or not isinstance(value['scope'],dict) or value['fingerprint']!=digest(value['scope']) or value['fingerprint'][:24]!=worker_id or redact(value)!=value:_error()
 s=value['scope'];keys={'kind','planId','planFingerprint','shop','sourceId','runtime','foreground'}
 if set(s)!=keys or s['kind']!='native-short-title-worker' or s['foreground'] is not True:_error()
 _id(s['sourceId']);_runtime(s['runtime']);p=ShortTitlePlans(state,None).plan(s['planId'])
 if p['fingerprint']!=s['planFingerprint'] or p['scope']['shop']!=s['shop']:_error()
 return value

def link_root(state,job,import_id,client=None):
 root=ShortTitleImports(state,client).record(import_id)
 if root['scope']['sourceId']!=job['scope']['sourceId'] or root['scope']['planId']!=job['scope']['planId'] or root['scope']['shop']!=job['scope']['shop']:_error()
 link={'workerId':job['workerId'],'workerFingerprint':job['fingerprint'],'importId':import_id,'fingerprint':root['fingerprint']}
 p=file(state,'short-title-worker-roots',job['workerId']);old=_read(p)
 if old is not None:
  if old!=link:_error()
 else:_once(p,link)
 return link

def read_link(state,job,client=None):
 value=_read(file(state,'short-title-worker-roots',job['workerId']))
 if value is None:return None
 if not isinstance(value,dict) or set(value)!={'workerId','workerFingerprint','importId','fingerprint'} or value['workerId']!=job['workerId'] or value['workerFingerprint']!=job['fingerprint']:_error()
 root=ShortTitleImports(state,client).record(value['importId'])
 if root['fingerprint']!=value['fingerprint'] or root['scope']['sourceId']!=job['scope']['sourceId'] or root['scope']['planId']!=job['scope']['planId'] or root['scope']['shop']!=job['scope']['shop']:_error()
 return value

def _entries(state,folder,job,pattern):
 directory=file(state,folder,job['workerId'],'placeholder').parent
 if not directory.exists():return {}
 if not directory.is_dir():_error()
 out={}
 for p in directory.iterdir():
  if not p.is_file() or p.suffix!='.json' or pattern.fullmatch(p.stem) is None or len(out)>=10000:_error()
  checked=file(state,folder,job['workerId'],p.stem);out[p.stem]=_read(checked)
 return out

def _footprints(state,job):
 result={}
 for folder in ('short-title-worker-claims','short-title-worker-endpoints','short-title-worker-launches','short-title-worker-prefixes','short-title-worker-prefix-receipts'):
  for name in _entries(state,folder,job,ID):
   p=file(state,folder,job['workerId'],name);result[p.relative_to(Path(state).absolute()).as_posix()]=file_sha(p)
 for folder in COMMAND_FOLDERS:
  for name in _entries(state,folder,job,REQ):
   p=file(state,folder,job['workerId'],name);result[p.relative_to(Path(state).absolute()).as_posix()]=file_sha(p)
 result.update(native_footprints(state,job));return result

def native_footprints(state,job):
 result={}
 link=file(state,'short-title-worker-roots',job['workerId'])
 if link.exists():
  result[link.relative_to(Path(state).absolute()).as_posix()]=file_sha(link)
  bound=read_link(state,job);root=file(state,'short-title-imports',bound['importId']);result[root.relative_to(Path(state).absolute()).as_posix()]=file_sha(root)
  for folder in NATIVE_FOLDERS:
   directory=file(state,folder,bound['importId'],'placeholder').parent
   if directory.exists():
    if not directory.is_dir():_error()
    for item in directory.iterdir():
     p=safe_join(Path(state).absolute(),folder+'/'+bound['importId']+'/'+item.name)
     if not p.is_file():_error()
     result[p.relative_to(Path(state).absolute()).as_posix()]=file_sha(p)
 return result

def read_runs(state,job):
 runs=_entries(state,'short-title-worker-runs',job,ID);closed=_entries(state,'short-title-worker-closed',job,ID);acks=_entries(state,'short-title-worker-close-receipts',job,ID)
 if set(closed)-set(runs) or set(acks)!=set(closed):_error()
 prefixes=_entries(state,'short-title-worker-prefixes',job,ID);prefix_receipts=_entries(state,'short-title-worker-prefix-receipts',job,ID)
 if set(prefixes)-set(runs) or set(prefix_receipts)!=set(prefixes):_error()
 native=native_footprints(state,job) if prefixes else {}
 for rid,prefix in prefixes.items():
  if not isinstance(prefix,dict) or set(prefix)!={'workerId','runId','claimSha256','footprints'} or prefix['workerId']!=job['workerId'] or prefix['runId']!=rid or prefix['claimSha256']!=digest({'workerId':job['workerId'],'runId':rid,'workerFingerprint':job['fingerprint'],'runSha256':digest(runs[rid])}) or not isinstance(prefix['footprints'],dict):_error()
  if prefix_receipts[rid]!={'workerId':job['workerId'],'runId':rid,'prefixSha256':digest(prefix)}:_error()
  if any(native.get(relative)!=sha for relative,sha in prefix['footprints'].items()):_error()
 accepted=_entries(state,COMMAND_FOLDERS[0],job,REQ);dispatched=_entries(state,COMMAND_FOLDERS[1],job,REQ);results=_entries(state,COMMAND_FOLDERS[2],job,REQ)
 if set(dispatched)-set(accepted) or set(results)-set(dispatched):_error()
 for name,run in runs.items():
  if not isinstance(run,dict) or set(run)!={'workerId','workerFingerprint','runId','runtime','resumeReadOnly'} or run['workerId']!=job['workerId'] or run['workerFingerprint']!=job['fingerprint'] or run['runId']!=name or run['runtime']!=job['scope']['runtime'] or type(run['resumeReadOnly']) is not bool:_error()
  if name in closed:
   end=closed[name]
   if not isinstance(end,dict) or set(end)!={'workerId','runId','runSha256','brokerStopped','browserClosed','guardOwnedAtClose','nativeImportId','footprints'} or end['workerId']!=job['workerId'] or end['runId']!=name or end['runSha256']!=digest(run) or any(end[k] is not True for k in ('brokerStopped','browserClosed','guardOwnedAtClose')) or not isinstance(end['footprints'],dict):_error()
   ack=acks[name]
   if ack!={'workerId':job['workerId'],'runId':name,'closedSha256':digest(end)}:_error()
   native_id=end['nativeImportId']
   if native_id is not None:_id(native_id)
   for relative,sha in end['footprints'].items():
    allowed=any(relative.startswith(folder+'/'+job['workerId']+'/') and REQ.fullmatch(Path(relative).stem) for folder in COMMAND_FOLDERS) or relative=='short-title-worker-roots/'+job['workerId']+'.json'
    allowed=allowed or any(relative.startswith(folder+'/'+job['workerId']+'/') and ID.fullmatch(Path(relative).stem) for folder in ('short-title-worker-claims','short-title-worker-endpoints','short-title-worker-launches','short-title-worker-prefixes','short-title-worker-prefix-receipts'))
    if native_id is not None:allowed=allowed or relative=='short-title-imports/'+native_id+'.json' or any(relative.startswith(folder+'/'+native_id+'/') for folder in NATIVE_FOLDERS)
    if not allowed:_error()
    p=safe_join(Path(state).absolute(),relative)
    if not isinstance(sha,str) or HASH.fullmatch(sha) is None or not p.is_file() or file_sha(p)!=sha:_error()
 return runs

def begin_run(state,job,*,resume=False):
 runs=read_runs(state,job)
 if any(not file(state,'short-title-worker-closed',job['workerId'],name).exists() for name in runs):raise SafetyError('original-worker-run-not-confirmed-closed-no-restart')
 if resume is not bool(runs):_error()
 run={'workerId':job['workerId'],'workerFingerprint':job['fingerprint'],'runId':uuid.uuid4().hex[:24],'runtime':job['scope']['runtime'],'resumeReadOnly':resume}
 _once(file(state,'short-title-worker-runs',job['workerId'],run['runId']),run);return run

def _check_command(state,job,run,value):
 keys={'requestId','action','importId','fingerprint','confirmed','ttl'}
 if not isinstance(value,dict) or set(value)!=keys or redact(value)!=value or not isinstance(value['action'],str) or value['action'] not in ACTIONS or type(value['confirmed']) is not bool or type(value['ttl']) is not int or not 30<=value['ttl']<=3600:_error()
 _id(value['requestId'],REQ)
 if value['action']=='approve':
  if value['confirmed'] is not True:_error()
 elif value['confirmed'] is not False:_error()
 if run['resumeReadOnly'] and value['action'] in ('approve','execute'):raise SafetyError('original-worker-resume-is-readonly-no-replay')
 if value['action']=='stop' and value['importId'] is None and value['fingerprint'] is None:return
 link=read_link(state,job)
 if link is None or value['importId']!=link['importId'] or value['fingerprint']!=link['fingerprint']:_error()

def accept_command(state,job,run,command):
 read_job(state,job['workerId']);runs=read_runs(state,job)
 if runs.get(run['runId'])!=run or file(state,'short-title-worker-closed',job['workerId'],run['runId']).exists():_error()
 _check_command(state,job,run,command)
 value={'workerId':job['workerId'],'workerFingerprint':job['fingerprint'],'runId':run['runId'],'command':command,'commandSha256':digest(command)}
 p=file(state,COMMAND_FOLDERS[0],job['workerId'],command['requestId']);old=_read(p)
 if old is not None:
  if old!=value:_error()
  return old
 if file(state,COMMAND_FOLDERS[1],job['workerId'],command['requestId']).exists() or file(state,COMMAND_FOLDERS[2],job['workerId'],command['requestId']).exists():_error()
 _once(p,value);return value

def dispatch_command(state,job,run,accepted):
 request_id=_id(accepted['command']['requestId'],REQ)
 if _read(file(state,COMMAND_FOLDERS[0],job['workerId'],request_id))!=accepted or accepted['runId']!=run['runId']:_error()
 _check_command(state,job,run,accepted['command'])
 p=file(state,COMMAND_FOLDERS[1],job['workerId'],request_id)
 if p.exists():raise SafetyError('original-worker-command-already-dispatched-no-replay')
 value={'workerId':job['workerId'],'runId':run['runId'],'requestId':request_id,'acceptanceSha256':digest(accepted)};_once(p,value);return value

def public_result(value):
 if not isinstance(value,dict) or redact(value)!=value:_error()
 out={k:v for k,v in value.items() if k in PUBLIC and (v is None or type(v) in (str,int,float,bool))}
 if redact(out)!=out or any(isinstance(v,str) and (len(v)>2048 or re.search(r'https?://',v,re.I)) for v in out.values()):_error()
 return out

def write_result(state,job,run,accepted,dispatch,result):
 rid=accepted['command']['requestId']
 if _read(file(state,COMMAND_FOLDERS[1],job['workerId'],rid))!=dispatch or dispatch['acceptanceSha256']!=digest(accepted):_error()
 value={'workerId':job['workerId'],'runId':run['runId'],'requestId':rid,'dispatchSha256':digest(dispatch),'result':public_result(result)}
 _once(file(state,COMMAND_FOLDERS[2],job['workerId'],rid),value);return value

def command_status(state,job,request_id):
 _id(request_id,REQ);accepted=_read(file(state,COMMAND_FOLDERS[0],job['workerId'],request_id));dispatch=_read(file(state,COMMAND_FOLDERS[1],job['workerId'],request_id));result=_read(file(state,COMMAND_FOLDERS[2],job['workerId'],request_id))
 if accepted is None:
  if dispatch is not None or result is not None:_error()
  return {'requestId':request_id,'status':'not-found','historicalResult':True}
 run=read_runs(state,job).get(accepted.get('runId'))
 if run is None or set(accepted)!={'workerId','workerFingerprint','runId','command','commandSha256'} or accepted['workerId']!=job['workerId'] or accepted['workerFingerprint']!=job['fingerprint'] or accepted['command'].get('requestId')!=request_id or accepted['commandSha256']!=digest(accepted['command']):_error()
 _check_command(state,job,run,accepted['command'])
 status='accepted-not-dispatched';value=None
 if dispatch is not None:
  expected={'workerId':job['workerId'],'runId':run['runId'],'requestId':request_id,'acceptanceSha256':digest(accepted)}
  if dispatch!=expected:_error()
  status='original-command-outcome-unknown'
 if result is not None:
  if dispatch is None or not isinstance(result,dict) or set(result)!={'workerId','runId','requestId','dispatchSha256','result'} or result['workerId']!=job['workerId'] or result['runId']!=run['runId'] or result['requestId']!=request_id or result['dispatchSha256']!=digest(dispatch) or result['result']!=public_result(result['result']):_error()
  status='completed';value=result['result']
 return {'requestId':request_id,'status':status,'result':value,'historicalResult':True}

def finish_run(state,job,run,*,broker_stopped=False,browser_closed=False,guard_owned=False):
 if broker_stopped is not True or browser_closed is not True or guard_owned is not True:_error()
 read_runs(state,job);life=safe_join(Path(state).absolute(),'browser/short-title/'+job['scope']['sourceId']+'/lifecycle.json')
 if life.exists() and read_json(life,{}).get('status')!='closed':_error()
 for rid in _entries(state,COMMAND_FOLDERS[0],job,REQ):command_status(state,job,rid)
 link=read_link(state,job)
 value={'workerId':job['workerId'],'runId':run['runId'],'runSha256':digest(run),'brokerStopped':True,'browserClosed':True,'guardOwnedAtClose':True,'nativeImportId':link['importId'] if link else None,'footprints':_footprints(state,job)}
 if len(json.dumps(value).encode('utf-8'))>16*1024*1024:raise SafetyError('bounded-worker-closure-required-no-truncation')
 _once(file(state,'short-title-worker-closed',job['workerId'],run['runId']),value)
 _once(file(state,'short-title-worker-close-receipts',job['workerId'],run['runId']),{'workerId':job['workerId'],'runId':run['runId'],'closedSha256':digest(value)})
 return value
