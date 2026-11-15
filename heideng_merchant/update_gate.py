"""Read-only fail-closed eligibility for installation/recovery/version switching."""
import re
from pathlib import Path
from .safety import SafetyError,read_json,safe_join
ACTIVE={'submitting','unknown','submitted','running'}
ID=re.compile('[a-f0-9]{24}')

def _entries(state,folder):
 root=safe_join(state,folder)
 if not root.exists():return []
 if not root.is_dir():raise SafetyError('unreviewed-update-state-layout')
 return [safe_join(state,folder+'/'+p.name) for p in root.iterdir()]

def _object(p):
 value=read_json(p)
 if not isinstance(value,dict):raise SafetyError('unprovable-update-state-record')
 return value

def _native_busy(state):
 from . import VERSION
 from .operations import Operations
 from .video_delivery import _load,_valid_time,ACTIVE as VIDEO_ACTIVE
 from .video_binding_state import checked_plan,raw_plan
 ops=Operations(state,None);tasks={};bindings=set();shop_materials=set()
 for p in _entries(state,'tasks'):
  if not p.is_file() or p.suffix!='.json':raise SafetyError('unreviewed-operation-state-file')
  value=_object(p);status=value.get('status')
  if not isinstance(status,str):raise SafetyError('unprovable-operation-state-status')
  if status in ACTIVE:return True
  tasks[p.stem]=value
  if 'shopMaterialInput' in value.get('scope',{}):
   if not ID.fullmatch(p.stem) or value.get('taskId')!=p.stem or value.get('fingerprint','')[:24]!=p.stem:raise SafetyError('unprovable-shop-material-task-identity')
   checked=ops.task(p.stem)
   if checked['status'] not in ('prepared','verified'):return True
   shop_materials.add(p.stem)
  if 'videoMaterialInput' in value.get('scope',{}):
   if not ID.fullmatch(p.stem) or value.get('taskId')!=p.stem or value.get('fingerprint','')[:24]!=p.stem:raise SafetyError('unprovable-binding-task-identity')
   checked=ops.task(p.stem)
   if checked['status'] not in ('prepared','verified'):return True
   bindings.add(p.stem)
 sessions={}
 for p in _entries(state,'video-sessions'):
  if p.is_file() and p.suffix=='.lock' and ID.fullmatch(p.stem):continue
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):raise SafetyError('unreviewed-video-session-file')
  value=_load(state,p.stem);sessions[p.stem]=value
  if value['status'] in VIDEO_ACTIVE:return True
  if value['status']=='prepared' and value['scope'].get('runtimeVersion')!=VERSION:return True
  if value['receipts'] and (not isinstance(value.get('approval'),dict) or value['approval'].get('confirmed') is not True):return True
 for folder in ('video-session-attempts','video-session-receipts','video-session-anchors','video-session-approvals'):
  for directory in _entries(state,folder):
   if not directory.is_dir() or directory.name not in sessions:return True
   files=_entries(state,folder+'/'+directory.name)
   if not files:return True
   for p in files:
    valid=(re.fullmatch('[a-f0-9]{32}',p.stem) if folder.endswith('approvals') else p.stem in ('allocate','renew','transfer','save'))
    if not p.is_file() or p.suffix!='.json' or not valid:return True
    r=_object(p);owner=sessions[directory.name]['scope']['shop']
    if r.get('sessionId')!=directory.name or r.get('fingerprint')!=sessions[directory.name]['fingerprint'] or r.get('shop')!=owner:return True
 for p in _entries(state,'video-session-cancellations'):
  if not p.is_file() or p.suffix!='.json' or p.stem not in sessions or sessions[p.stem]['status']!='cancelled':return True
 plans={}
 for p in _entries(state,'video-binding-plans'):
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):return True
  value=checked_plan(ops,_object(p))
  if value['planId']!=p.stem:return True
  plans[p.stem]=value
 for folder in ('video-binding-attempts','video-binding-receipts','video-binding-anchors'):
  for p in _entries(state,folder):
   if not p.is_file() or p.suffix!='.json' or p.stem not in bindings:return True
 for directory in _entries(state,'video-binding-approvals'):
  if not directory.is_dir() or directory.name not in plans:return True
  files=_entries(state,'video-binding-approvals/'+directory.name)
  if not files:return True
  for p in files:
   if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{32}',p.stem):return True
   r=_object(p);plan=plans[directory.name]
   if set(r)!={'planId','fingerprint','shop','approvalId','approval'} or r.get('approvalId')!=p.stem or r.get('planId')!=directory.name or r.get('fingerprint')!=plan['fingerprint'] or r.get('shop')!=plan['scope']['context']['shop']:return True
   approval=r['approval']
   if not isinstance(approval,dict) or set(approval)!={'confirmed','fingerprint','expiresAt'} or approval['confirmed'] is not True or approval['fingerprint']!=plan['fingerprint'] or not _valid_time(approval['expiresAt']):return True
 for p in _entries(state,'video-binding-intents'):
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):return True
  index=_object(p)
  if set(index)!={'planId','intentHash'} or not isinstance(index['intentHash'],str) or not re.fullmatch('[a-f0-9]{64}',index['intentHash']) or index['intentHash'][:24]!=p.stem or index.get('planId') not in plans or plans[index['planId']]['scope']['intentHash']!=index['intentHash']:return True
 for plan in plans.values():
  intent=plan['scope']['intentHash'];index=_object(safe_join(state,'video-binding-intents/'+intent[:24]+'.json'))
  if index!={'planId':plan['planId'],'intentHash':intent}:return True
 for ident in bindings:
  parent=checked_plan(ops,raw_plan(ops,tasks[ident]))
  if parent['planId'] not in plans or not any(ref['taskId']==ident and ref['fingerprint']==tasks[ident]['fingerprint'] for ref in parent['scope']['tasks']):return True
 return _shop_material_busy(ops,shop_materials,tasks)

def _shop_material_busy(ops,children,tasks):
 from .shop_material_execution_state import checked_plan,raw_plan,approval_record
 state=ops.state;plans={}
 for p in _entries(state,'shop-material-plans'):
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):return True
  value=checked_plan(ops,_object(p))
  if value['planId']!=p.stem:return True
  plans[p.stem]=value
 for folder in ('shop-material-attempts','shop-material-receipts','shop-material-anchors'):
  for p in _entries(state,folder):
   if not p.is_file() or p.suffix!='.json' or p.stem not in children:return True
 for directory in _entries(state,'shop-material-approvals'):
  if not directory.is_dir() or directory.name not in plans:return True
  files=_entries(state,'shop-material-approvals/'+directory.name)
  if not files:return True
  for p in files:
   if not p.is_file() or p.suffix!='.json' or not re.fullmatch('[a-f0-9]{32}',p.stem):return True
   approval_record(ops,plans[directory.name],p.stem)
 for p in _entries(state,'shop-material-intents'):
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):return True
  index=_object(p)
  if set(index)!={'planId','intentHash'} or not isinstance(index['intentHash'],str) or not re.fullmatch('[a-f0-9]{64}',index['intentHash']) or index['intentHash'][:24]!=p.stem or index['planId'] not in plans or plans[index['planId']]['scope']['intentHash']!=index['intentHash']:return True
 for ident in children:
  parent=raw_plan(ops,tasks[ident])
  if parent['planId'] not in plans:return True
 return False

def busy(state):
 try:return _native_busy(Path(state).absolute())
 except (SafetyError,OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):return True
