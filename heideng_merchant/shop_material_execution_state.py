"""Independent whole-shop approvals and one-shot child attempts/receipts."""
import re,time,math
from .safety import SafetyError,safe_join,read_json,redact
from .operations import digest
from .video_delivery import _once
from .shop_material_execution_contract import source_context,changes_for_audit,slots_checked,groups,intent

def path(state,folder,ident):
 if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):raise SafetyError('native-shop-material-id-required')
 return safe_join(state,folder+'/'+ident+'.json')
def valid_time(value):return type(value) in (int,float) and math.isfinite(value) and value>0

def scope_checked(ops,plan):
 if not isinstance(plan,dict) or not isinstance(plan.get('scope'),dict):raise SafetyError('original-whole-shop-material-plan-required')
 scope=plan['scope'];fp=digest(scope)
 if set(scope)!={'intent','intentHash','capabilities','tasks','runtimeVersion'} or plan.get('fingerprint')!=fp or plan.get('planId')!=fp[:24] or not isinstance(scope['runtimeVersion'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',scope['runtimeVersion']):raise SafetyError('original-shop-material-parent-scope-changed')
 i=scope['intent'];record=source_context(ops,i['auditId'],i['auditFingerprint']);slots=slots_checked(i['targetSlots']);changes=changes_for_audit(record,i['changes'],slots)
 if i!=intent(record,changes,slots) or scope['intentHash']!=digest(i) or not isinstance(scope['tasks'],list):raise SafetyError('shop-material-parent-intent-changed')
 expected=groups(changes);refs=scope['tasks']
 if len(refs)!=len(expected) or len({r.get('taskId') for r in refs if isinstance(r,dict)})!=len(refs) or any(not isinstance(r,dict) or set(r)!={'taskId','fingerprint'} or not isinstance(r['fingerprint'],str) or not re.fullmatch('[a-f0-9]{64}',r['fingerprint']) or r['taskId']!=r['fingerprint'][:24] for r in refs):raise SafetyError('complete-unique-whole-shop-chunks-required')
 if (bool(refs) and (not isinstance(scope['capabilities'],dict) or set(scope['capabilities'])!={'GET','POST'})) or (not refs and scope['capabilities']!={}):raise SafetyError('shop-material-original-capability-scope-required')
 return record,expected

def raw_plan(ops,task):
 proof=task['scope']['shopMaterialInput'];index=read_json(path(ops.state,'shop-material-intents',proof['intentHash'][:24]))
 if not isinstance(index,dict) or set(index)!={'planId','intentHash'} or index['intentHash']!=proof['intentHash']:raise SafetyError('original-shop-material-parent-registration-required')
 plan=read_json(path(ops.state,'shop-material-plans',index['planId']));record,expected=scope_checked(ops,plan)
 if plan['scope']['intentHash']!=index['intentHash']:raise SafetyError('shop-material-intent-registration-changed')
 ref={'taskId':task['taskId'],'fingerprint':task['fingerprint']}
 if ref not in plan['scope']['tasks']:raise SafetyError('shop-material-task-not-in-original-parent')
 _approval_entries(ops,plan)
 position=plan['scope']['tasks'].index(ref);pid,skus,changes=expected[position];p=task['scope']['skuMaterialInput'];i=plan['scope']['intent']
 if task['scope']['shop']!=i['shop'] or task['scope']['runtimeVersion']!=plan['scope']['runtimeVersion'] or proof!={'version':1,'intentHash':plan['scope']['intentHash'],'auditId':i['auditId'],'auditFingerprint':i['auditFingerprint']} or p['productId']!=pid or p['skuIds']!=skus or p['changes']!=changes or p['capabilities']!=plan['scope']['capabilities']:raise SafetyError('shop-material-child-does-not-match-root-description')
 return plan

def approval_record(ops,plan,aid=None):
 aid=plan.get('approvalId') if aid is None else aid
 if not isinstance(aid,str) or not re.fullmatch('[a-f0-9]{32}',aid):raise SafetyError('original-whole-shop-parent-approval-required')
 record=read_json(safe_join(ops.state,'shop-material-approvals/'+plan['planId']+'/'+aid+'.json'));i=plan['scope']['intent']
 if not isinstance(record,dict) or set(record)!={'planId','fingerprint','approvalId','shop','approval'} or record['planId']!=plan['planId'] or record['fingerprint']!=plan['fingerprint'] or record['approvalId']!=aid or record['shop']!=i['shop'] or redact(record)!=record:raise SafetyError('original-shop-material-approval-changed')
 grant=record['approval']
 if not isinstance(grant,dict) or set(grant)!={'confirmed','fingerprint','expiresAt','approvedAt'} or grant['confirmed'] is not True or grant['fingerprint']!=plan['fingerprint'] or not valid_time(grant['expiresAt']) or not valid_time(grant['approvedAt']):raise SafetyError('original-shop-material-approval-format-invalid')
 return record

def _approval_entries(ops,plan):
 folder='shop-material-approvals/'+plan['planId'];root=safe_join(ops.state,folder)
 if not root.exists():return
 if not root.is_dir():raise SafetyError('unreviewed-shop-material-approval-layout')
 for entry in root.iterdir():
  p=safe_join(ops.state,folder+'/'+entry.name)
  if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{32}',p.stem):raise SafetyError('unreviewed-shop-material-approval-entry')
  approval_record(ops,plan,p.stem)

def checked_plan(ops,plan):
 scope_checked(ops,plan);_approval_entries(ops,plan);scope=plan['scope'];i=scope['intent'];index=read_json(path(ops.state,'shop-material-intents',scope['intentHash'][:24]))
 if index!={'planId':plan['planId'],'intentHash':scope['intentHash']}:raise SafetyError('original-shop-material-root-registration-required')
 for ref in scope['tasks']:
  task=ops.task(ref['taskId']);parent=raw_plan(ops,task)
  if task['taskId']!=ref['taskId'] or task['fingerprint']!=ref['fingerprint'] or parent['planId']!=plan['planId'] or parent['fingerprint']!=plan['fingerprint']:raise SafetyError('shop-material-root-child-reciprocal-membership-required')
 if 'approval' in plan:
  original=approval_record(ops,plan)
  if original['approval']!=plan['approval'] or digest(original)!=plan.get('approvalSha256'):raise SafetyError('original-shop-material-selected-approval-changed')
 return plan

def parent_deadline(ops,task):
 plan=raw_plan(ops,task);original=approval_record(ops,plan)
 if original['approval']!=plan.get('approval') or digest(original)!=plan.get('approvalSha256') or original['approval']['expiresAt']<=time.time():raise SafetyError('current-exact-whole-shop-approval-required')
 return original['approval']['expiresAt']

def checked_task(ops,task):
 if 'shopMaterialInput' not in task.get('scope',{}):return task
 ident=task['taskId'];marker=read_json(path(ops.state,'shop-material-attempts',ident));record=read_json(path(ops.state,'shop-material-receipts',ident));anchor=read_json(path(ops.state,'shop-material-anchors',ident));shop=task['scope']['shop']
 if marker is None:
  if record is not None or anchor is not None or 'resultReceiptSha256' in task or task['status']!='prepared':raise SafetyError('original-shop-material-attempt-required-no-replay')
  return task
 plan=raw_plan(ops,task)
 if not isinstance(marker,dict) or set(marker)!={'taskId','fingerprint','shop','planId','approvalId','approvalSha256','startedAt'} or marker['taskId']!=ident or marker['fingerprint']!=task['fingerprint'] or marker['shop']!=shop or marker['planId']!=plan['planId'] or not valid_time(marker['startedAt']):raise SafetyError('original-shop-material-attempt-changed')
 original=approval_record(ops,plan,marker['approvalId'])
 if digest(original)!=marker['approvalSha256']:raise SafetyError('original-shop-material-attempt-approval-changed')
 if record is None and anchor is None:
  if 'resultReceiptSha256' in task:raise SafetyError('original-shop-material-acknowledgement-lost')
  task['status']='unknown';return task
 if not isinstance(record,dict) or set(record)!={'taskId','fingerprint','shop','receipt'} or record['taskId']!=ident or record['fingerprint']!=task['fingerprint'] or record['shop']!=shop or redact(record)!=record or anchor!={'taskId':ident,'fingerprint':task['fingerprint'],'shop':shop,'originalReceiptSha256':digest(record)}:raise SafetyError('original-shop-material-independent-ack-changed')
 from .video_binding_state import business_ack
 business_ack(record['receipt'])
 if task.get('resultReceiptSha256')!=digest(record['receipt']) or task.get('result')!=record['receipt'] or task['status']=='prepared':raise SafetyError('original-shop-material-journal-ack-changed-no-replay')
 if task['status']=='submitting':task['status']='unknown'
 return task

def start_attempt(ops,task):
 if 'shopMaterialInput' not in task['scope']:return
 ident=task['taskId'];plan=raw_plan(ops,task);parent_deadline(ops,task)
 if any(path(ops.state,f,ident).exists() for f in ('shop-material-attempts','shop-material-receipts','shop-material-anchors')):raise SafetyError('shop-material-original-attempt-no-replay')
 _once(path(ops.state,'shop-material-attempts',ident),{'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'planId':plan['planId'],'approvalId':plan['approvalId'],'approvalSha256':digest(approval_record(ops,plan)),'startedAt':time.time()})

def preserve_receipt(ops,task,result):
 if 'shopMaterialInput' not in task['scope']:return
 from .video_binding_state import business_ack
 business_ack(result);ident=task['taskId'];record={'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'receipt':result}
 if redact(record)!=record or not path(ops.state,'shop-material-attempts',ident).is_file():raise SafetyError('shop-material-original-attempt-before-ack-required')
 _once(path(ops.state,'shop-material-receipts',ident),record);_once(path(ops.state,'shop-material-anchors',ident),{'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'originalReceiptSha256':digest(record)})

def assert_resolved(ops,shop,exclude=None):
 from .video_binding_state import owner as checked_owner
 evidence={}
 for folder in ('shop-material-attempts','shop-material-receipts','shop-material-anchors'):
  root=safe_join(ops.state,folder)
  if not root.exists():continue
  if not root.is_dir():raise SafetyError('shop-material-original-evidence-layout-invalid')
  for entry in root.iterdir():
   p=safe_join(ops.state,folder+'/'+entry.name)
   if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{24}',p.stem):raise SafetyError('unreviewed-shop-material-evidence-entry')
   record=read_json(p);owner=checked_owner(record)
   if record.get('taskId')!=p.stem or not isinstance(record.get('fingerprint'),str) or not re.fullmatch('[a-f0-9]{64}',record['fingerprint']) or record['fingerprint'][:24]!=p.stem:raise SafetyError('original-shop-material-evidence-identity-invalid')
   evidence.setdefault(p.stem,[]).append(owner)
 for ident,owners in evidence.items():
  if any(o!=owners[0] for o in owners):raise SafetyError('shop-material-evidence-owners-contradict')
  owner=owners[0];journal=read_json(ops._path(ident))
  if journal is not None and (not isinstance(journal,dict) or journal.get('scope',{}).get('shop')!=owner):raise SafetyError('shop-material-evidence-original-owner-contradicts-journal')
  if journal is not None:
   if journal.get('taskId')!=ident or 'shopMaterialInput' not in journal.get('scope',{}) or journal.get('fingerprint')!=digest(journal.get('scope')):raise SafetyError('shop-material-original-journal-identity-and-proof-required')
   for folder in ('shop-material-attempts','shop-material-receipts','shop-material-anchors'):
    original=read_json(path(ops.state,folder,ident))
    if original is not None and original.get('fingerprint')!=journal['fingerprint']:raise SafetyError('shop-material-original-evidence-journal-fingerprint-mismatch')
   task=ops.task(ident)
  if owner['profile']==shop['profile'] or (owner['venderId']==shop['venderId'] and owner['shopId']==shop['shopId']):
   if ident==exclude:continue
   if journal is None or task['status'] in ('submitting','unknown','submitted') or task['status']=='verified' and task.get('materialFieldsVerified') is not True:raise SafetyError('same-shop-original-material-outcome-unresolved')

 root=safe_join(ops.state,'shop-material-plans')
 if root.exists():
  if not root.is_dir():raise SafetyError('shop-material-original-parent-layout-invalid')
  for entry in root.iterdir():
   p=safe_join(ops.state,'shop-material-plans/'+entry.name)
   if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{24}',p.stem):raise SafetyError('unreviewed-shop-material-parent-entry')
   plan=checked_plan(ops,read_json(p))
   if plan['planId']!=p.stem:raise SafetyError('shop-material-original-parent-file-identity-changed')
   owner=plan['scope']['intent']['shop']
   if owner['profile']==shop['profile'] or (owner['venderId']==shop['venderId'] and owner['shopId']==shop['shopId']):
    for ref in plan['scope']['tasks']:
     if ref['taskId']==exclude:continue
     t=ops.task(ref['taskId'])
     if t['status'] in ('unknown','submitting','submitted') or t['status']=='verified' and t.get('materialFieldsVerified') is not True:raise SafetyError('same-shop-retained-root-has-unresolved-original-children')


 # Reconcile surviving registrations even when the root itself was lost.
 roots=safe_join(ops.state,'shop-material-plans')
 for folder in ('shop-material-intents','shop-material-approvals'):
  base=safe_join(ops.state,folder)
  if not base.exists():continue
  if not base.is_dir():raise SafetyError('shop-material-original-registration-layout-invalid')
  for entry in base.iterdir():
   p=safe_join(ops.state,folder+'/'+entry.name)
   if folder.endswith('intents'):
    if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{24}',p.stem):raise SafetyError('unreviewed-shop-material-intent-entry')
    index=read_json(p)
    if not isinstance(index,dict) or set(index)!={'planId','intentHash'} or not isinstance(index['intentHash'],str) or not re.fullmatch('[a-f0-9]{64}',index['intentHash']) or index['intentHash'][:24]!=p.stem:raise SafetyError('unprovable-original-shop-material-intent')
    parent=checked_plan(ops,read_json(path(ops.state,'shop-material-plans',index['planId'])))
    if parent['scope']['intentHash']!=index['intentHash']:raise SafetyError('original-shop-material-intent-parent-mismatch')
   else:
    if not p.is_dir() or not re.fullmatch('[a-f0-9]{24}',p.name):raise SafetyError('unreviewed-shop-material-approval-directory')
    parent=read_json(path(ops.state,'shop-material-plans',p.name))
    if parent is None:raise SafetyError('orphan-original-shop-material-approval-root-missing')
    checked_plan(ops,parent)
 base=safe_join(ops.state,'tasks')
 if base.exists():
  for entry in base.iterdir():
   p=safe_join(ops.state,'tasks/'+entry.name)
   if not p.is_file() or p.suffix!='.json':continue
   journal=read_json(p)
   if not isinstance(journal,dict) or 'shopMaterialInput' not in journal.get('scope',{}):continue
   owner=checked_owner({'shop':journal['scope'].get('shop')})
   if journal.get('taskId')!=p.stem or journal.get('fingerprint')!=digest(journal.get('scope')) or journal['fingerprint'][:24]!=p.stem:raise SafetyError('shop-material-original-child-journal-identity-invalid')
   if owner['profile']==shop['profile'] or (owner['venderId']==shop['venderId'] and owner['shopId']==shop['shopId']):
    if _new_unattempted_child(ops,journal):continue
    raw_plan(ops,journal)

_PREPARATION_KEY=object()
class _Preparation:
 def __init__(self,intent_hash):self.key=_PREPARATION_KEY;self.intentHash=intent_hash;self.children=set()

def _new_unattempted_child(ops,task):
 context=getattr(ops,'_shop_material_preparation',None);ident=task['taskId'];proof=task['scope']['shopMaterialInput']
 if not isinstance(context,_Preparation) or context.key is not _PREPARATION_KEY or ident not in context.children or proof.get('intentHash')!=context.intentHash or task.get('status')!='prepared':return False
 if any(path(ops.state,f,ident).exists() for f in ('shop-material-attempts','shop-material-receipts','shop-material-anchors')) or path(ops.state,'shop-material-intents',context.intentHash[:24]).exists():return False
 return True

from contextlib import contextmanager
@contextmanager
def root_preparation(ops,intent_hash,shop):
 # Before creating this runtime-only context, all pre-existing orphan proofs block.
 assert_resolved(ops,shop)
 previous=getattr(ops,'_shop_material_preparation',None);context=_Preparation(intent_hash);ops._shop_material_preparation=context
 try:yield context
 finally:
  if previous is None:delattr(ops,'_shop_material_preparation')
  else:ops._shop_material_preparation=previous


# A runtime-only dispatch capability is created after an actual full-catalog read.
# It is never accepted from CLI parameters or persisted as a boolean claim.
_DISPATCH_KEY=object()
class _Dispatch:
 def __init__(self,plan):self.key=_DISPATCH_KEY;self.planId=plan['planId'];self.fingerprint=plan['fingerprint'];self.children=plan['scope']['tasks']

def require_dispatch(ops,scope):
 dispatch=getattr(ops,'_shop_material_dispatch',None)
 if not isinstance(dispatch,_Dispatch) or dispatch.key is not _DISPATCH_KEY:raise SafetyError('whole-shop-child-dispatch-requires-root-runner')
 ident=digest(scope)[:24];task={'taskId':ident,'fingerprint':digest(scope),'scope':scope};plan=raw_plan(ops,task)
 if (dispatch.planId,dispatch.fingerprint)!=(plan['planId'],plan['fingerprint']):raise SafetyError('whole-shop-dispatch-capability-does-not-match-original-root')
 ref={'taskId':ident,'fingerprint':task['fingerprint']}
 if ref not in dispatch.children:raise SafetyError('whole-shop-dispatch-child-not-in-original-root')
 for earlier in dispatch.children[:dispatch.children.index(ref)]:
  t=ops.task(earlier['taskId'])
  if t['status']!='verified' or t.get('materialFieldsVerified') is not True:raise SafetyError('whole-shop-dispatch-predecessor-not-originally-verified')

from contextlib import contextmanager
@contextmanager
def root_dispatch(ops,plan):
 from .shop_material_execution_contract import current_catalog
 plan=checked_plan(ops,plan);grant=approval_record(ops,plan)
 if grant['approval']['expiresAt']<=time.time():raise SafetyError('whole-shop-root-approval-expired-before-managed-dispatch')
 current_catalog(ops,source_context(ops,plan['scope']['intent']['auditId'],plan['scope']['intent']['auditFingerprint']))
 previous=getattr(ops,'_shop_material_dispatch',None);ops._shop_material_dispatch=_Dispatch(plan)
 try:yield
 finally:
  if previous is None:delattr(ops,'_shop_material_dispatch')
  else:ops._shop_material_dispatch=previous
