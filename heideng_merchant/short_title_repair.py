"""Original-parent repair planning/intent, never a permission to replay a shop write."""
import json,unicodedata,uuid
from pathlib import Path
from . import VERSION
from .operations import digest
from .safety import SafetyError,safe_join,redact
from .state import FileLock
from .short_title_import_state import ident,path,evidence,valid_time
from .short_title_contract import source_context,changes_checked
from .short_title_effect_state import read_log as effects,_read
from .short_title_result_state import read_log as results,summary as result_summary
from .video_delivery import _once

FOLDERS=('short-title-repair-plans','short-title-repair-intents','short-title-repair-approvals','short-title-repair-approval-receipts')
MAX_BYTES=16*1024*1024
MAX_FILES=10000

def _error():raise SafetyError('original-confirmed-failure-repair-proof-required')
def _file(state,folder,parent,identifier):return safe_join(Path(state).absolute(),folder+'/'+ident(parent)+'/'+identifier+'.json')
def _read_file(file):
 if not file.is_file() or not 0<file.stat().st_size<=MAX_BYTES:_error()
 return _read(file)
def _entries(state,folder,parent):
 directory=safe_join(Path(state).absolute(),folder+'/'+ident(parent))
 if not directory.exists():return []
 if not directory.is_dir():_error()
 out=[]
 for item in directory.iterdir():
  file=safe_join(Path(state).absolute(),folder+'/'+parent+'/'+item.name)
  if not file.is_file() or file.suffix!='.json' or len(out)>=MAX_FILES:_error()
  out.append(file)
 return out

def _semantic(value):
 keys=('productId','skuId','originalOnSale','target','actualShortTitle','actualFieldObserved','processingOutcome','healthTitleIssue','healthRowObserved')
 return digest({'identitySha256':value['identitySha256'],'rows':[{k:row[k] for k in keys} for row in value['rows']]})

def _snapshot(manager,parent,sequence):
 anchors=evidence(manager.state,parent)[3];_,count,_=effects(manager.state,parent,anchors);latest,n,_=results(manager.state,parent,anchors)
 if type(sequence) is not int or not 1<=sequence<=count:_error()
 item=_read_file(path(manager.state,'short-title-effect-observations',parent['importId'],suffix=f'/{sequence:06d}.json'));value=item['observation']
 receipt=_read_file(path(manager.state,'short-title-effect-receipts',parent['importId'],suffix=f'/{sequence:06d}.json'))
 prefix={}
 for i in range(1,value['originalResultSequence']+1):
  row=_read_file(path(manager.state,'short-title-result-observations',parent['importId'],suffix=f'/{i:06d}.json'));prefix[row['batch']]=row
 if not result_summary(parent,prefix)['rowResultsVerified']:_error()
 if value.get('effectEvidenceVersion')!=2 or value.get('nativeHealthSourcesVerified') is not True or any(value[k] is not True for k in ('currentIdentityVerified','sourceDetailsStable','currentOriginalScopeComplete')) or any(row['actualFieldObserved'] is not True for row in value['rows']):_error()
 proof={'effectObservationSequence':sequence,'effectReceiptSha256':digest(receipt),'resultSequence':value['originalResultSequence'],'resultReceiptSha256':value['originalResultReceiptSha256'],'currentNeedSemanticSha256':_semantic(value)}
 return value,proof

def _checked_changes(manager,parent,value,changes):
 plan=manager.plans.plan(parent['scope']['planId']);_,coverage=source_context(manager.state,plan['scope']['auditId'],plan['scope']['auditFingerprint']);ready=changes_checked(coverage,changes)
 if not ready:_error()
 current={row['skuId']:row for row in value['rows']};old={row['skuId'] for row in parent['scope']['changes']};selected={row['skuId'] for row in ready}
 def key(title):return unicodedata.normalize('NFKC',title).casefold()
 unchanged={key(row['actualShortTitle']) for row in value['rows'] if row['skuId'] not in selected}
 for row in ready:
  native=current[row['skuId']]
  if row['skuId'] not in old or native['processingOutcome']!='failed' or native['originalOnSale'] is not True or native['healthRowObserved'] is not True or native['healthTitleIssue'] is not True or key(row['shortTitle'])==key(native['actualShortTitle']) or key(row['shortTitle']) in unchanged:_error()
 return ready

def _raw(changes):return [{k:row[k] for k in ('productId','skuId','shortTitle','review')} for row in changes]
def _intent(parent,ready):return digest({'kind':'original-short-title-failure-repair-intent','parentFingerprint':parent['fingerprint'],'changes':ready})

class ShortTitleRepairPlans:
 def __init__(self,manager):self.manager=manager;self.state=manager.state
 def _owned(self,parent,browser,*,approve=False):
  self.manager._browser(parent,browser);browser.install_lock.require_owned(self.state/'install.lock');self.manager._current(parent,readonly=True);self.manager._worker_checkpoint()
  if getattr(self.manager,'repair_stop_requested',lambda:False)():raise SafetyError('original-repair-command-stopped')
  witness=getattr(self.manager.plans.ops,'worker_witness',None)
  if approve and witness is not None and witness.run.get('resumeReadOnly'):raise SafetyError('original-worker-resume-is-readonly-no-repair-approval')
 def _collect(self,parent,browser):
  from .shop_material_execution_contract import current_catalog
  plan=self.manager.plans.plan(parent['scope']['planId']);audit,_=source_context(self.state,plan['scope']['auditId'],plan['scope']['auditFingerprint'])
  self._owned(parent,browser);current_catalog(self.manager.plans.ops,audit,all_siblings=True);self._owned(parent,browser)
  current=self.manager.collect_results(parent['importId'],browser)
  if any(current.get(key) is not True for key in ('rowResultsVerified','currentResultSourceVerified','currentTaskAnchorMatched')) or current.get('currentResultReadBatches')!=list(range(1,len(parent['scope']['chunks'])+1)):_error()
  self._owned(parent,browser)
  fresh=self.manager.collect_effects(parent['importId'],browser)
  self._owned(parent,browser);current_catalog(self.manager.plans.ops,audit,all_siblings=True);self._owned(parent,browser)
  if fresh.get('currentEffectSourceVerified') is not True or fresh.get('currentNativeHealthSourceVerified') is not True:_error()
  return fresh['effectObservationSequence']
 def _current_snapshot(self,parent,sequence):
  anchors=evidence(self.state,parent)[3];latest,count,_=effects(self.state,parent,anchors);_,result_count,_=results(self.state,parent,anchors)
  if sequence!=count or latest['observation']['originalResultSequence']!=result_count:_error()
  return _snapshot(self.manager,parent,sequence)
 def record(self,parent_id,repair_id):
  parent=self.manager.record(parent_id);ident(repair_id);saved=_read_file(_file(self.state,FOLDERS[0],parent_id,repair_id))
  if not isinstance(saved,dict) or set(saved)!={'repairPlanId','repairFingerprint','scope'} or saved['repairPlanId']!=repair_id or saved['repairFingerprint']!=digest(saved['scope']) or saved['repairFingerprint'][:24]!=repair_id or redact(saved)!=saved:_error()
  scope=saved['scope'];keys={'kind','runtimeVersion','parentImportId','parentFingerprint','shop','originalPlanFingerprint','originalAuditFingerprint','intentHash','sourceProof','changes'}
  if not isinstance(scope,dict) or set(scope)!=keys or scope['kind']!='native-short-title-confirmed-failure-repair-plan' or not isinstance(scope['sourceProof'],dict):_error()
  plan=self.manager.plans.plan(parent['scope']['planId'])
  if scope['runtimeVersion']!=parent['scope']['runtimeVersion'] or scope['parentImportId']!=parent_id or scope['parentFingerprint']!=parent['fingerprint'] or scope['shop']!=parent['scope']['shop'] or scope['originalPlanFingerprint']!=plan['fingerprint'] or scope['originalAuditFingerprint']!=plan['scope']['auditFingerprint']:_error()
  value,proof=_snapshot(self.manager,parent,scope['sourceProof'].get('effectObservationSequence'));ready=_checked_changes(self.manager,parent,value,_raw(scope['changes']))
  if digest(proof)!=digest(scope['sourceProof']) or ready!=scope['changes'] or scope['intentHash']!=_intent(parent,ready):_error()
  index=_read_file(_file(self.state,FOLDERS[1],parent_id,scope['intentHash'][:24]))
  if index!={'parentImportId':parent_id,'intentHash':scope['intentHash'],'repairPlanId':repair_id,'repairFingerprint':saved['repairFingerprint']}:_error()
  return saved
 def _worker_integrity(self,parent_id):
  from . import short_title_worker_state as original
  folder=safe_join(self.state,'short-title-worker-roots')
  if not folder.exists():return
  if not folder.is_dir():_error()
  for item in folder.iterdir():
   file=safe_join(self.state,'short-title-worker-roots/'+item.name)
   if not file.is_file() or file.suffix!='.json':_error()
   value=_read_file(file)
   if not isinstance(value,dict):_error()
   if value.get('importId')==parent_id:
    job=original.read_job(self.state,file.stem);original.read_link(self.state,job);original.read_runs(self.state,job)
 def _family(self,parent_id):
  self.manager.record(parent_id)
  self._worker_integrity(parent_id)
  plans={}
  for file in _entries(self.state,FOLDERS[0],parent_id):plans[ident(file.stem)]=self.record(parent_id,file.stem)
  indexes=_entries(self.state,FOLDERS[1],parent_id)
  if len(indexes)!=len(plans):_error()
  for file in indexes:
   index=_read_file(file);saved=plans.get(index.get('repairPlanId')) if isinstance(index,dict) else None
   if saved is None or file.stem!=saved['scope']['intentHash'][:24]:_error()
  approvals={}
  receipt_files={file.stem:file for file in _entries(self.state,FOLDERS[3],parent_id)}
  for file in _entries(self.state,FOLDERS[2],parent_id):
   value=_read_file(file);keys={'parentImportId','repairPlanId','repairFingerprint','approvalId','confirmed','approvedAt','expiresAt','sourceProof'}
   if not isinstance(value,dict) or set(value)!=keys or len(file.stem)!=32 or any(c not in 'abcdef0123456789' for c in file.stem) or value['approvalId']!=file.stem or value['parentImportId']!=parent_id or value['confirmed'] is not True or not valid_time(value['approvedAt']) or not valid_time(value['expiresAt']) or not 30<=value['expiresAt']-value['approvedAt']<=3600 or not isinstance(value['sourceProof'],dict) or redact(value)!=value:_error()
   receipt=receipt_files.get(file.stem)
   if receipt is None or _read_file(receipt)!={'parentImportId':parent_id,'repairPlanId':value['repairPlanId'],'repairFingerprint':value['repairFingerprint'],'approvalId':file.stem,'approvalSha256':digest(value)}:_error()
   saved=plans.get(value['repairPlanId'])
   if saved is None or value['repairFingerprint']!=saved['repairFingerprint']:_error()
   parent=self.manager.record(parent_id);snap,proof=_snapshot(self.manager,parent,value['sourceProof'].get('effectObservationSequence'))
   if digest(proof)!=digest(value['sourceProof']) or proof['effectObservationSequence']<saved['scope']['sourceProof']['effectObservationSequence'] or proof['currentNeedSemanticSha256']!=saved['scope']['sourceProof']['currentNeedSemanticSha256'] or _checked_changes(self.manager,parent,snap,_raw(saved['scope']['changes']))!=saved['scope']['changes']:_error()
   approvals[file.stem]=value
  if set(receipt_files)!=set(approvals):_error()
  return plans,approvals
 def status(self,parent_id,repair_id):
  plans,approvals=self._family(parent_id);saved=plans.get(repair_id)
  if saved is None:_error()
  now=self.manager.clock();active=[a for a in approvals.values() if a['repairPlanId']==repair_id and a['approvedAt']<=now<a['expiresAt']]
  return {'importId':parent_id,'repairPlanId':repair_id,'repairFingerprint':saved['repairFingerprint'],'repairRowCount':len(saved['scope']['changes']),'approvalCurrentlyValid':bool(active),'newApprovalRecorded':bool(active),'currentRepairNeedVerified':False,'repairEvidenceHistorical':True,'planningOnly':True,'childImportExecutionAvailable':False,'imported':False,'retryAuthorized':False}
 def prepare(self,parent_id,browser,changes):
  parent=self.manager.record(parent_id)
  if parent['scope']['runtimeVersion']!=VERSION:_error()
  with FileLock(safe_join(self.state,'short-title-repair.lock')):
   self._family(parent_id);sequence=self._collect(parent,browser)
   with FileLock(path(self.state,'short-title-imports',parent_id,suffix='.lock')):
    self._owned(parent,browser);value,proof=self._current_snapshot(parent,sequence);ready=_checked_changes(self.manager,parent,value,changes);ih=_intent(parent,ready);indexfile=_file(self.state,FOLDERS[1],parent_id,ih[:24])
    if indexfile.exists():
     old=_read_file(indexfile);saved=self.record(parent_id,old['repairPlanId'])
     if saved['scope']['sourceProof']['currentNeedSemanticSha256']!=proof['currentNeedSemanticSha256']:_error()
    else:
     plan=self.manager.plans.plan(parent['scope']['planId']);scope={'kind':'native-short-title-confirmed-failure-repair-plan','runtimeVersion':VERSION,'parentImportId':parent_id,'parentFingerprint':parent['fingerprint'],'shop':parent['scope']['shop'],'originalPlanFingerprint':plan['fingerprint'],'originalAuditFingerprint':plan['scope']['auditFingerprint'],'intentHash':ih,'sourceProof':proof,'changes':ready};fp=digest(scope);saved={'repairPlanId':fp[:24],'repairFingerprint':fp,'scope':scope}
     self._owned(parent,browser);_once(_file(self.state,FOLDERS[0],parent_id,fp[:24]),saved);_once(indexfile,{'parentImportId':parent_id,'intentHash':ih,'repairPlanId':fp[:24],'repairFingerprint':fp});self.manager._worker_checkpoint()
   out=self.status(parent_id,saved['repairPlanId']);out.update(currentRepairNeedVerified=True,repairEvidenceHistorical=False);return out
 def approve(self,parent_id,repair_id,fingerprint,browser,*,confirmed=False,ttl=900,approval_id=None):
  if confirmed is not True or type(ttl) is not int or not 30<=ttl<=3600 or not valid_time(self.manager.clock()):_error()
  aid=approval_id or uuid.uuid4().hex
  if not isinstance(aid,str) or len(aid)!=32 or any(c not in 'abcdef0123456789' for c in aid):_error()
  with FileLock(safe_join(self.state,'short-title-repair.lock')):
   saved=self.record(parent_id,repair_id);parent=self.manager.record(parent_id)
   if fingerprint!=saved['repairFingerprint'] or saved['scope']['runtimeVersion']!=VERSION:_error()
   self._owned(parent,browser,approve=True);self._family(parent_id)
   file=_file(self.state,FOLDERS[2],parent_id,aid)
   if file.exists():
    old=_read_file(file)
    if old['repairPlanId']!=repair_id or old['repairFingerprint']!=fingerprint:_error()
    return self.status(parent_id,repair_id)
   sequence=self._collect(parent,browser)
   with FileLock(path(self.state,'short-title-imports',parent_id,suffix='.lock')):
    self._owned(parent,browser,approve=True);value,proof=self._current_snapshot(parent,sequence)
    if proof['currentNeedSemanticSha256']!=saved['scope']['sourceProof']['currentNeedSemanticSha256'] or _checked_changes(self.manager,parent,value,_raw(saved['scope']['changes']))!=saved['scope']['changes']:_error()
    now=self.manager.clock();record={'parentImportId':parent_id,'repairPlanId':repair_id,'repairFingerprint':fingerprint,'approvalId':aid,'confirmed':True,'approvedAt':now,'expiresAt':now+ttl,'sourceProof':proof};self._owned(parent,browser,approve=True);_once(file,record);_once(_file(self.state,FOLDERS[3],parent_id,aid),{'parentImportId':parent_id,'repairPlanId':repair_id,'repairFingerprint':fingerprint,'approvalId':aid,'approvalSha256':digest(record)});self.manager._worker_checkpoint()
   out=self.status(parent_id,repair_id);out.update(currentRepairNeedVerified=True,repairEvidenceHistorical=False);return out
 def rows(self,parent_id,repair_id,*,page=1,page_size=50,view='changes'):
  if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or not 1<=page_size<=200 or view not in ('changes','siblings'):_error()
  plans,_=self._family(parent_id);saved=plans.get(repair_id)
  if saved is None:_error()
  rows=saved['scope']['changes'] if view=='changes' else _snapshot(self.manager,self.manager.record(parent_id),saved['scope']['sourceProof']['effectObservationSequence'])[0]['rows'];start=(page-1)*page_size;items=rows[start:start+page_size]
  return {'importId':parent_id,'repairPlanId':repair_id,'view':view,'items':items,'total':len(rows),'page':page,'pageSize':page_size,'nextPage':page+1 if start+len(items)<len(rows) else None,'repairEvidenceHistorical':True,'currentRepairNeedVerified':False,'retryAuthorized':False,'imported':False}

def validate_layout(state,client=None):
 from .short_title_imports import ShortTitleImports
 manager=ShortTitleImports(state,client);parents=set();present=False
 for folder in FOLDERS:
  directory=safe_join(Path(state).absolute(),folder)
  if not directory.exists():continue
  if not directory.is_dir():_error()
  for item in directory.iterdir():
   child=safe_join(Path(state).absolute(),folder+'/'+item.name)
   if not child.is_dir():_error()
   parents.add(ident(item.name));present=True
 for parent in parents:ShortTitleRepairPlans(manager)._family(parent)
 return present
