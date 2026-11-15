"""Parent material-plan membership and authorization, separate from child approvals."""
import math,re,time
from .safety import SafetyError,read_json,safe_join
from .sku_material_contract import hash_value,changes_checked,positive,identifiers,BATCH

def checked_plan(ops,plan):
 if not isinstance(plan,dict) or not isinstance(plan.get('scope'),dict):raise SafetyError('material-parent-plan-required')
 scope=plan['scope'];fingerprint=hash_value(scope)
 if set(scope)!={'shop','productId','changes','tasks','runtimeVersion','intentHash'} or plan.get('fingerprint')!=fingerprint or plan.get('planId')!=fingerprint[:24] or hash_value(plan.get('tasks'))!=hash_value(scope['tasks']):raise SafetyError('material-parent-plan-fingerprint-mismatch')
 changes=changes_checked(scope['changes']);product=positive(scope['productId']);intent={'shop':scope['shop'],'productId':product,'changes':changes}
 if hash_value(changes)!=hash_value(scope['changes']) or scope['intentHash']!=hash_value(intent):raise SafetyError('material-parent-plan-intent-mismatch')
 skus=identifiers(sorted({r['skuId'] for r in changes},key=int));groups=[skus[i:i+BATCH] for i in range(0,len(skus),BATCH)];refs=scope['tasks']
 if not isinstance(refs,list) or len(refs)!=len(groups):raise SafetyError('material-plan-complete-chunks-required')
 used=set();siblings=None
 for index,item in enumerate(refs):
  if not isinstance(item,dict) or set(item)!={'taskId','fingerprint'} or item['taskId'] in used:raise SafetyError('material-plan-unique-chunk-reference-required')
  used.add(item['taskId']);task=ops.task(item['taskId']);proof=task['scope'].get('skuMaterialInput',{})
  if task['taskId']!=item['taskId'] or task['fingerprint']!=item['fingerprint'] or item['fingerprint'][:24]!=item['taskId'] or task['scope']['shop']!=scope['shop'] or task['scope']['runtimeVersion']!=scope['runtimeVersion']:raise SafetyError('material-plan-task-modified')
  expected_changes=[row for row in changes if row['skuId'] in groups[index]]
  if proof.get('productId')!=product or proof.get('intentHash')!=scope['intentHash'] or proof.get('skuIds')!=groups[index] or hash_value(proof.get('changes'))!=hash_value(expected_changes):raise SafetyError('material-plan-description-does-not-match-executable-chunks')
  current_siblings=identifiers(proof.get('siblingSkuIds'))
  if current_siblings!=proof['siblingSkuIds'] or not set(groups[index])<=set(current_siblings) or (siblings is not None and siblings!=current_siblings):raise SafetyError('material-plan-sibling-census-inconsistent')
  siblings=current_siblings
 return plan

def parent_deadline(ops,task):
 proof=task['scope'].get('skuMaterialInput')
 if proof is None:return None
 intent=proof.get('intentHash')
 if not isinstance(intent,str) or not re.fullmatch('[a-f0-9]{64}',intent):raise SafetyError('material-parent-authorization-intent-required')
 index=read_json(safe_join(ops.state,'sku-material-intents/'+intent+'.json'),{});plan_id=index.get('planId')
 if not isinstance(plan_id,str) or not re.fullmatch('[a-f0-9]{24}',plan_id):raise SafetyError('material-parent-plan-not-registered')
 plan=checked_plan(ops,read_json(safe_join(ops.state,'sku-material-plans/'+plan_id+'.json')))
 if plan['scope']['intentHash']!=intent or {'taskId':task['taskId'],'fingerprint':task['fingerprint']} not in plan['scope']['tasks']:raise SafetyError('material-task-not-member-of-approved-parent')
 approval=plan.get('approval',{});deadline=approval.get('expiresAt')
 if approval.get('confirmed') is not True or approval.get('fingerprint')!=plan['fingerprint'] or isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not math.isfinite(deadline) or deadline<=time.time():raise SafetyError('current-exact-parent-material-plan-approval-required')
 return deadline
