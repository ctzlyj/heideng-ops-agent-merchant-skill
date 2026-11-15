"""Immutable native title import scope and independent evidence reconstruction."""
import re,math
from pathlib import Path
from . import VERSION
from .safety import SafetyError,safe_join,read_json,file_sha,redact
from .operations import digest
from .short_titles import ShortTitlePlans
from .short_title_browser import _source_record

ID=re.compile('[a-f0-9]{24}');HASH=re.compile('[a-f0-9]{64}');PHASES=('upload','create')

def ident(value):
 if not isinstance(value,str) or not ID.fullmatch(value):raise SafetyError('native-short-title-import-id-required')
 return value

def path(state,folder,import_id,suffix='.json'):return safe_join(Path(state).absolute(),folder+'/'+ident(import_id)+suffix)
def event_path(state,folder,import_id,batch,phase):
 if type(batch) is not int or not 1<=batch<=999999 or phase not in PHASES:raise SafetyError('native-short-title-import-event-required')
 return safe_join(Path(state).absolute(),folder+'/'+ident(import_id)+'/'+f'{batch:06d}-{phase}.json')
def valid_time(value):return type(value) in (int,float) and math.isfinite(value) and value>0

def intent(plan):return digest({'kind':'native-short-title-import-intent','planFingerprint':plan['fingerprint'],'shop':plan['scope']['shop']})
def filename(source_id,batch,sha):return 'short-title-'+ident(source_id)+'-'+f'{batch:06d}'+'-'+sha[:12]+'.xlsx'

def record(state,client,import_id):
 p=read_json(path(state,'short-title-imports',import_id))
 if not isinstance(p,dict) or set(p)!={'importId','fingerprint','scope'} or p['importId']!=import_id or p['fingerprint']!=digest(p['scope']) or p['fingerprint'][:24]!=import_id or redact(p)!=p:raise SafetyError('original-native-short-title-import-changed')
 s=p['scope'];keys={'kind','runtimeVersion','planId','planFingerprint','sourceId','sourceFingerprint','shop','intentHash','changes','chunks','artifacts'}
 if not isinstance(s,dict) or set(s)!=keys or s['kind']!='native-short-title-browser-import' or not isinstance(s['runtimeVersion'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',s['runtimeVersion']):raise SafetyError('complete-native-short-title-import-scope-required')
 plan=ShortTitlePlans(state,client).plan(s['planId']);source=_source_record(state,client,s['sourceId'])
 if s['planFingerprint']!=plan['fingerprint'] or s['sourceFingerprint']!=source['fingerprint'] or source['scope']['planId']!=plan['planId'] or source['scope']['planFingerprint']!=plan['fingerprint'] or s['shop']!=plan['scope']['shop'] or s['shop']!=source['scope']['shop'] or s['intentHash']!=intent(plan) or s['changes']!=plan['scope']['changes'] or s['chunks']!=plan['scope']['chunks'] or not s['changes'] or not isinstance(s['artifacts'],list) or len(s['artifacts'])!=len(s['chunks']):raise SafetyError('original-native-short-title-import-source-scope-required')
 index=read_json(path(state,'short-title-import-intents',s['intentHash'][:24]))
 if index!={'importId':import_id,'intentHash':s['intentHash']}:raise SafetyError('original-native-short-title-import-intent-required')
 for i,(artifact,rows) in enumerate(zip(s['artifacts'],s['chunks']),1):
  if not isinstance(artifact,dict) or set(artifact)!={'batch','rowCount','rowsSha256','localPath','sha256','byteCount','filename'} or artifact['batch']!=i or artifact['rowCount']!=len(rows) or not 1<=len(rows)<=5000 or artifact['rowsSha256']!=digest(rows) or not isinstance(artifact['sha256'],str) or not HASH.fullmatch(artifact['sha256']) or artifact['filename']!=filename(s['sourceId'],i,artifact['sha256']) or artifact['localPath']!='short-title-import-workbooks/'+s['sourceId']+'/'+artifact['filename'] or type(artifact['byteCount']) is not int or not 0<artifact['byteCount']<=5*1024*1024:raise SafetyError('original-native-short-title-import-artifact-required')
  f=safe_join(Path(state).absolute(),artifact['localPath'])
  if not f.is_file() or f.stat().st_size!=artifact['byteCount'] or file_sha(f)!=artifact['sha256']:raise SafetyError('complete-original-native-short-title-import-files-required')
 return p

def approvals(state,p):
 folder=path(state,'short-title-import-approvals',p['importId'],suffix='');out={}
 if not folder.exists():return out
 if not folder.is_dir():raise SafetyError('native-import-approval-directory-required')
 for file in folder.iterdir():
  f=safe_join(Path(state).absolute(),'short-title-import-approvals/'+p['importId']+'/'+file.name);value=read_json(f)
  if not f.is_file() or f.suffix!='.json' or not re.fullmatch('[a-f0-9]{32}',f.stem) or not isinstance(value,dict) or set(value)!={'importId','fingerprint','shop','approvalId','confirmed','approvedAt','expiresAt'} or value['importId']!=p['importId'] or value['fingerprint']!=p['fingerprint'] or value['shop']!=p['scope']['shop'] or value['approvalId']!=f.stem or value['confirmed'] is not True or not valid_time(value['approvedAt']) or not valid_time(value['expiresAt']) or not 30<=value['expiresAt']-value['approvedAt']<=3600 or redact(value)!=value:raise SafetyError('original-exact-native-import-approval-required')
  out[f.stem]=value
 return out

def _events(state,folder,p):
 directory=path(state,folder,p['importId'],suffix='');out={}
 if not directory.exists():return out
 if not directory.is_dir():raise SafetyError('native-import-event-directory-required')
 for file in directory.iterdir():
  match=re.fullmatch(r'([0-9]{6})-(upload|create)\.json',file.name)
  if not file.is_file() or not match:raise SafetyError('original-native-import-event-layout-required')
  batch=int(match[1]);phase=match[2]
  if not 1<=batch<=len(p['scope']['artifacts']):raise SafetyError('original-native-import-event-batch-required')
  f=event_path(state,folder,p['importId'],batch,phase);value=read_json(f)
  if not isinstance(value,dict) or redact(value)!=value:raise SafetyError('original-native-import-event-object-required')
  out[(batch,phase)]=value
 return out

def check_result(r,phase):
 if not isinstance(r,dict) or set(r)!={'outcome','responseSha256','uploadedObjectSha256','instanceId','instanceEvidence'} or r['outcome'] not in ('accepted','non-success','unknown') or not isinstance(r['responseSha256'],str) or not HASH.fullmatch(r['responseSha256']) or (r['uploadedObjectSha256'] is not None and (not isinstance(r['uploadedObjectSha256'],str) or not HASH.fullmatch(r['uploadedObjectSha256']))) or (r['instanceId'] is not None and (not isinstance(r['instanceId'],str) or not re.fullmatch('[1-9][0-9]{5,18}',r['instanceId']) or int(r['instanceId'])>9223372036854775807)) or (phase=='create' and (r['instanceEvidence'] not in ('absent','exact','contradictory') or (r['instanceEvidence']=='exact')!=(r['instanceId'] is not None))) or (phase=='upload' and (r['instanceEvidence']!='not-applicable')) or (phase=='upload' and (r['instanceId'] is not None or r['outcome']=='accepted' and r['uploadedObjectSha256'] is None)) or (phase=='create' and r['uploadedObjectSha256'] is not None):raise SafetyError('bounded-original-native-import-business-ack-required')

def check_preflight(proof,template_sha):
 if not isinstance(proof,dict) or set(proof)!={'identitySha256','taskPageSha256','captureEpoch','beforeInstanceIds','templateSha256','healthAuditId','healthAuditFingerprint'} or type(proof['captureEpoch']) is not int or proof['captureEpoch']<1 or not isinstance(proof['beforeInstanceIds'],list) or len(proof['beforeInstanceIds'])>500 or any(not isinstance(x,str) or not re.fullmatch('[1-9][0-9]{5,18}',x) or int(x)>9223372036854775807 for x in proof['beforeInstanceIds']) or len(proof['beforeInstanceIds'])!=len(set(proof['beforeInstanceIds'])) or not isinstance(proof['healthAuditId'],str) or not ID.fullmatch(proof['healthAuditId']) or not isinstance(proof['healthAuditFingerprint'],str) or not HASH.fullmatch(proof['healthAuditFingerprint']) or proof['templateSha256']!=template_sha or any(not isinstance(proof[k],str) or not HASH.fullmatch(proof[k]) for k in ('identitySha256','taskPageSha256','templateSha256')):raise SafetyError('original-native-import-preflight-required')

def check_observation(value):
 if not isinstance(value,dict) or set(value)!={'rows','taskPageSha256','identitySha256'} or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ('taskPageSha256','identitySha256')) or not isinstance(value['rows'],list) or len(value['rows'])>500:raise SafetyError('bounded-native-task-page-observation-required')
 ids=set()
 for row in value['rows']:
  if not isinstance(row,dict) or set(row)!={'instanceId','uploadedObjectSha256','startedAt'} or (row['instanceId'] is not None and (not isinstance(row['instanceId'],str) or not re.fullmatch('[1-9][0-9]{5,18}',row['instanceId']) or int(row['instanceId'])>9223372036854775807 or row['instanceId'] in ids)) or (row['uploadedObjectSha256'] is not None and (not isinstance(row['uploadedObjectSha256'],str) or not HASH.fullmatch(row['uploadedObjectSha256']))) or (row['startedAt'] is not None and not valid_time(row['startedAt'])):raise SafetyError('original-native-task-page-row-required')
  if row['instanceId']:ids.add(row['instanceId'])

def evidence(state,p):
 ap=approvals(state,p);attempts=_events(state,'short-title-import-attempts',p);acks=_events(state,'short-title-import-acks',p);anchors=_events(state,'short-title-import-anchors',p);dispatches=_events(state,'short-title-import-dispatches',p);observations=_events(state,'short-title-import-observations',p);template_sha=_source_record(state,None,p['scope']['sourceId'])['scope']['template']['sha256']
 for key,a in attempts.items():
  n,phase=key;artifact=p['scope']['artifacts'][n-1];context=a.get('context')
  if set(a)!={'context','approvalId','startedAt','deadline','preflight'} or not isinstance(context,dict) or set(context)!={'importId','fingerprint','shop','batch','phase','artifactSha256','rowsSha256','attemptId'} or context['importId']!=p['importId'] or context['fingerprint']!=p['fingerprint'] or context['shop']!=p['scope']['shop'] or context['batch']!=n or context['phase']!=phase or context['artifactSha256']!=artifact['sha256'] or context['rowsSha256']!=artifact['rowsSha256'] or not isinstance(context['attemptId'],str) or not re.fullmatch('[a-f0-9]{32}',context['attemptId']) or a['approvalId'] not in ap or not valid_time(a['startedAt']) or not valid_time(a['deadline']) or not ap[a['approvalId']]['approvedAt']<=a['startedAt']<a['deadline']<=ap[a['approvalId']]['expiresAt']:raise SafetyError('original-approved-native-import-attempt-required')
  check_preflight(a['preflight'],template_sha)
  from .short_title_contract import source_context
  healthy,coverage=source_context(state,a['preflight']['healthAuditId'],a['preflight']['healthAuditFingerprint']);by_sku={row['skuId']:row for row in coverage}
  if healthy['scope']['shop']!=p['scope']['shop'] or any(row['skuId'] not in by_sku or by_sku[row['skuId']]['onSale'] is not True or by_sku[row['skuId']]['nativeTitleIssue'] is not True or by_sku[row['skuId']]['productId']!=row['productId'] for row in p['scope']['chunks'][n-1]):raise SafetyError('original-current-title-health-eligibility-required')
  if phase=='create' and ((n,'upload') not in acks or acks[n,'upload']['result']['outcome']!='accepted'):raise SafetyError('original-native-upload-acceptance-required')
 for key,ack in acks.items():
  if key not in attempts or key not in dispatches or set(ack)!={'context','attemptSha256','result'} or ack['context']!=attempts[key]['context'] or ack['attemptSha256']!=digest(attempts[key]):raise SafetyError('original-native-import-ack-attempt-required')
  check_result(ack['result'],key[1])
 for key,value in dispatches.items():
  if key not in attempts or set(value)!={'context','attemptSha256'} or value['context']!=attempts[key]['context'] or value['attemptSha256']!=digest(attempts[key]):raise SafetyError('original-native-import-single-dispatch-required')
 for key,value in observations.items():
  n,phase=key
  if phase!='create' or key not in attempts or key not in dispatches or (n,'upload') not in acks or set(value)!={'context','attemptSha256','uploadAckSha256','observedAt','observed'} or value['context']!=attempts[key]['context'] or value['attemptSha256']!=digest(attempts[key]) or value['uploadAckSha256']!=digest(acks[n,'upload']) or not valid_time(value['observedAt']):raise SafetyError('independent-original-native-task-observation-required')
  check_observation(value['observed'])
 instances=set()
 for key,anchor in anchors.items():
  n,phase=key
  if phase!='create' or key not in attempts or key not in dispatches or key not in observations or (n,'upload') not in acks or acks[n,'upload']['result']['outcome']!='accepted' or set(anchor)!={'context','attemptSha256','uploadAckSha256','instanceId','objectSha256','startedAt','observedAt','taskPageSha256','identitySha256','observationSha256'} or anchor['context']!=attempts[key]['context'] or anchor['attemptSha256']!=digest(attempts[key]) or anchor['uploadAckSha256']!=digest(acks[n,'upload']) or anchor['objectSha256']!=acks[n,'upload']['result']['uploadedObjectSha256'] or not isinstance(anchor['instanceId'],str) or not re.fullmatch('[1-9][0-9]{5,18}',anchor['instanceId']) or anchor['instanceId'] in attempts[n,'upload']['preflight']['beforeInstanceIds'] or not valid_time(anchor['startedAt']) or not attempts[key]['startedAt']-5<=anchor['startedAt']<=attempts[key]['deadline']+5 or not valid_time(anchor['observedAt']) or any(not isinstance(anchor[k],str) or not HASH.fullmatch(anchor[k]) for k in ('taskPageSha256','identitySha256')):raise SafetyError('original-native-import-instance-source-anchor-required')
  obs=observations[key]
  if anchor['observationSha256']!=digest(obs) or anchor['observedAt']!=obs['observedAt'] or anchor['taskPageSha256']!=obs['observed']['taskPageSha256'] or anchor['identitySha256']!=obs['observed']['identitySha256'] or {'instanceId':anchor['instanceId'],'uploadedObjectSha256':anchor['objectSha256'],'startedAt':anchor['startedAt']} not in obs['observed']['rows']:raise SafetyError('original-native-instance-observation-anchor-changed')
  if anchor['instanceId'] in instances:raise SafetyError('unique-root-wide-native-import-instance-required')
  instances.add(anchor['instanceId'])
  ack=acks.get(key)
  if ack and (ack['result']['instanceEvidence']=='contradictory' or ack['result']['instanceId'] is not None and ack['result']['instanceId']!=anchor['instanceId']):raise SafetyError('original-native-instance-ack-anchor-conflict')
 for n,phase in attempts:
  if any((previous,'create') not in anchors for previous in range(1,n)):raise SafetyError('complete-original-native-import-prefix-required')
 return ap,attempts,acks,anchors,dispatches,observations

def batch_rows(p,ev):
 ap,at,ack,anchors,dispatches,observations=ev;out=[]
 for artifact in p['scope']['artifacts']:
  n=artifact['batch'];u=(n,'upload');c=(n,'create');state='not-started';instance=None
  if u in at:
   if u not in ack or ack[u]['result']['outcome']=='unknown':state='unknown-upload'
   elif ack[u]['result']['outcome']=='non-success':state='upload-non-success'
   elif c not in at:state='uploaded-awaiting-create'
   elif c in anchors:state='submitted';instance=anchors[c]['instanceId']
   elif c in ack and ack[c]['result']['outcome']=='non-success':state='create-non-success'
   else:state='unknown-create'
  out.append({'batch':n,'rowCount':artifact['rowCount'],'state':state,'instanceId':instance})
 return out
