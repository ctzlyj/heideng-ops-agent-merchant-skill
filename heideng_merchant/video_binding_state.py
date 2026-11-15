"""Independent parent approvals and one-shot native video binding receipts."""
import math,re,time,uuid
from pathlib import Path
from .safety import SafetyError,read_json,safe_join,redact
from .operations import digest
from .video_delivery import _once
from .video_contract import native_id
from .official import validate_profile
from .sku_material_contract import identifiers,BATCH

def path(state,folder,ident):
 if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):raise SafetyError('native-video-binding-id-required')
 return safe_join(state,folder+'/'+ident+'.json')

def raw_plan(ops,task):
 proof=task['scope']['videoMaterialInput'];index=read_json(path(ops.state,'video-binding-intents',proof['intentHash'][:24]))
 if not isinstance(index,dict) or index.get('intentHash')!=proof['intentHash']:raise SafetyError('native-video-binding-parent-registration-required')
 plan=read_json(path(ops.state,'video-binding-plans',index.get('planId')))
 if not isinstance(plan,dict) or digest(plan.get('scope'))!=plan.get('fingerprint') or plan.get('planId')!=plan['fingerprint'][:24]:raise SafetyError('original-native-video-binding-parent-required')
 return plan

def approval(state,plan):
 aid=plan.get('approvalId')
 if not isinstance(aid,str) or not re.fullmatch('[a-f0-9]{32}',aid):raise SafetyError('independent-native-video-binding-parent-approval-required')
 expected={'planId':plan['planId'],'fingerprint':plan['fingerprint'],'approvalId':aid,'approval':plan.get('approval'),'shop':plan['scope']['context']['shop']}
 record=read_json(safe_join(state,'video-binding-approvals/'+plan['planId']+'/'+aid+'.json'))
 if record!=expected or digest(record)!=plan.get('approvalSha256'):raise SafetyError('original-native-video-binding-parent-approval-changed')
 return plan['approvalSha256']

def checked_task(ops,task):
 if 'videoMaterialInput' not in task['scope']:return task
 ident=task['taskId'];marker=read_json(path(ops.state,'video-binding-attempts',ident));record=read_json(path(ops.state,'video-binding-receipts',ident));anchor=read_json(path(ops.state,'video-binding-anchors',ident));shop=task['scope']['shop']
 if marker is None:
  if record is not None or anchor is not None or 'resultReceiptSha256' in task or task['status']!='prepared':raise SafetyError('native-video-binding-original-attempt-required-no-replay')
  return task
 plan=raw_plan(ops,task);sha=approval(ops.state,plan)
 if not isinstance(marker,dict) or set(marker)!={'taskId','fingerprint','shop','approvalSha256','startedAt'} or marker['taskId']!=ident or marker['fingerprint']!=task['fingerprint'] or marker['shop']!=shop or marker['approvalSha256']!=sha:raise SafetyError('native-video-binding-attempt-changed')
 if record is None and anchor is None:
  if 'resultReceiptSha256' in task:raise SafetyError('native-video-binding-original-receipt-missing')
  task['status']='unknown';return task
 if not isinstance(record,dict) or set(record)!={'taskId','fingerprint','shop','receipt'} or record['taskId']!=ident or record['fingerprint']!=task['fingerprint'] or record['shop']!=shop or redact(record)!=record or anchor!={'taskId':ident,'fingerprint':task['fingerprint'],'shop':shop,'originalReceiptSha256':digest(record)}:raise SafetyError('native-video-binding-independent-receipt-changed')
 business_ack(record['receipt'])
 if task.get('resultReceiptSha256')!=digest(record['receipt']) or task.get('result')!=record['receipt']:raise SafetyError('native-video-binding-journal-original-ack-changed')
 if task['status']=='prepared':raise SafetyError('native-video-binding-acknowledged-stage-no-replay')
 return task

def business_ack(result):
 from .verification import business_payload
 payload=business_payload(result)
 if not isinstance(result,dict) or result.get('success') is not True or not isinstance(payload,(dict,list)) or not payload:raise SafetyError('native-video-binding-positive-original-ack-required')

def checked_plan(ops,plan):
 if not isinstance(plan,dict) or not isinstance(plan.get('scope'),dict):raise SafetyError('original-native-video-binding-plan-required')
 scope=plan['scope'];fingerprint=digest(scope)
 if set(scope)!={'context','baseline','baselineAudit','skuIds','tasks','intentHash','runtimeVersion'} or plan.get('fingerprint')!=fingerprint or plan.get('planId')!=fingerprint[:24]:raise SafetyError('native-video-binding-parent-scope-changed')
 ctx=scope['context'];all_skus=identifiers(ctx['product']['skuIds']);skus=identifiers(scope['skuIds']) if scope['skuIds'] else []
 if set(scope['baseline'])!=set(all_skus) or set(scope['baselineAudit'])!=set(all_skus) or skus!=[s for s in all_skus if '42:1' not in scope['baseline'][s]]:raise SafetyError('native-video-binding-parent-complete-baseline-required')
 expected_intent=digest({'shop':ctx['shop'],'productId':ctx['product']['productId'],'sessionId':ctx['source']['sessionId']})
 if scope['intentHash']!=expected_intent:raise SafetyError('native-video-binding-original-intent-changed')
 from .video_binding_contract import target_material,identity_scope
 if not isinstance(ctx.get('review'),dict) or ctx['review'].get('passed') is not True or ctx['review']!={**identity_scope(ctx),'passed':True}:raise SafetyError('exact-native-video-product-review-required')
 for s in all_skus:
  if s not in skus and scope['baseline'][s]['42:1']!=target_material(ctx,s):raise SafetyError('other-existing-main-video-not-reusable')
 groups=[skus[i:i+BATCH] for i in range(0,len(skus),BATCH)];refs=scope['tasks'];seen=set()
 if not isinstance(refs,list) or len(refs)!=len(groups):raise SafetyError('complete-native-video-binding-chunks-required')
 for group,item in zip(groups,refs):
  if not isinstance(item,dict) or set(item)!={'taskId','fingerprint'} or item['taskId'] in seen:raise SafetyError('unique-native-video-binding-child-required')
  seen.add(item['taskId']);task=ops.task(item['taskId']);proof=task['scope'].get('videoMaterialInput')
  expected={'version':1,'intentHash':scope['intentHash'],'context':ctx,'skuIds':group,'baseline':{s:scope['baseline'][s] for s in group},'baselineAudit':{s:scope['baselineAudit'][s] for s in group}}
  if task['fingerprint']!=item['fingerprint'] or task['taskId']!=item['taskId'] or task['scope']['shop']!=ctx['shop'] or task['scope']['runtimeVersion']!=scope['runtimeVersion'] or proof!=expected:raise SafetyError('native-video-binding-child-not-exact-parent-member')
 if 'approval' in plan:approval(ops.state,plan)
 return plan

def parent_deadline(ops,task):
 if 'videoMaterialInput' not in task['scope']:return None
 plan=checked_plan(ops,raw_plan(ops,task));approval(ops.state,plan);value=plan.get('approval',{});deadline=value.get('expiresAt')
 if value.get('confirmed') is not True or value.get('fingerprint')!=plan['fingerprint'] or isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not math.isfinite(deadline) or deadline<=time.time():raise SafetyError('current-exact-native-video-binding-parent-approval-required')
 return deadline

def start_attempt(ops,task):
 if 'videoMaterialInput' not in task['scope']:return
 ident=task['taskId']
 if any(path(ops.state,f,ident).exists() for f in ('video-binding-attempts','video-binding-receipts','video-binding-anchors')) or 'resultReceiptSha256' in task:raise SafetyError('native-video-binding-original-attempt-no-replay')
 plan=raw_plan(ops,task);parent_deadline(ops,task)
 _once(path(ops.state,'video-binding-attempts',ident),{'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'approvalSha256':approval(ops.state,plan),'startedAt':time.time()})

def preserve_receipt(ops,task,result):
 if 'videoMaterialInput' not in task['scope']:return
 business_ack(result);ident=task['taskId'];record={'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'receipt':result}
 if redact(record)!=record or not path(ops.state,'video-binding-attempts',ident).is_file():raise SafetyError('native-video-binding-original-attempt-before-receipt-required')
 _once(path(ops.state,'video-binding-receipts',ident),record);_once(path(ops.state,'video-binding-anchors',ident),{'taskId':ident,'fingerprint':task['fingerprint'],'shop':task['scope']['shop'],'originalReceiptSha256':digest(record)})

def owner(record):
 value=record.get('shop') if isinstance(record,dict) else None
 if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k].strip() for k in ('profile','venderId','shopId','shopName')):raise SafetyError('every-native-video-binding-evidence-owner-required')
 validate_profile(value['profile']);native_id(value['venderId']);native_id(value['shopId']);return value

def assert_resolved(ops,shop,exclude=None):
 evidence={}
 for folder in ('video-binding-attempts','video-binding-receipts','video-binding-anchors'):
  for p in (ops.state/folder).glob('*.json'):
   record=read_json(path(ops.state,folder,p.stem));evidence.setdefault(p.stem,[]).append(owner(record))
 for ident,owners in evidence.items():
  if any(o!=owners[0] for o in owners):raise SafetyError('contradictory-native-video-binding-evidence-owner')
  same=owners[0]['profile']==shop['profile'] or all(owners[0][k]==shop[k] for k in ('venderId','shopId'))
  if not same:continue
  value=read_json(ops._path(ident))
  if not isinstance(value,dict) or value.get('scope',{}).get('shop')!=owners[0] or 'videoMaterialInput' not in value.get('scope',{}) or digest(value['scope'])!=value.get('fingerprint'):raise SafetyError('orphaned-native-video-binding-outcome-unresolved')
  value=checked_task(ops,value)
  if ident!=exclude and value['status'] in ('unknown','submitting','submitted'):raise SafetyError('same-shop-native-video-binding-outcome-unresolved')
 for directory in (ops.state/'video-binding-approvals').glob('*'):
  if not directory.is_dir():raise SafetyError('native-video-binding-approval-layout-unprovable')
  records=[read_json(safe_join(ops.state,'video-binding-approvals/'+directory.name+'/'+p.name)) for p in directory.glob('*.json')];owners=[owner(r) for r in records]
  if not owners or any(o!=owners[0] for o in owners):raise SafetyError('native-video-binding-approval-owner-unprovable')
  if not path(ops.state,'video-binding-plans',directory.name).exists() and (owners[0]['profile']==shop['profile'] or all(owners[0][k]==shop[k] for k in ('venderId','shopId'))):raise SafetyError('orphaned-native-video-binding-parent-unresolved')
