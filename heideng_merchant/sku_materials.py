"""Native missing-slot audit and durable per-chunk maintenance; no generators."""
from __future__ import annotations
import time
from pathlib import Path
from .operations import Operations, digest
from .safety import SafetyError, atomic_json, read_json, safe_join
from .state import FileLock
from .sku_material_contract import SLOTS, WRITE, SKILL, BATCH, positive, identifiers, census, read_materials, changes_checked, upload_source, capabilities

class SkuMaterialService:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def audit(self,profile,product_id,*,include_health=False):
  sku_ids,skus=census(self.ops,profile,product_id);snapshot=read_materials(self.client,self.ops.shop(profile),sku_ids);missing={};issues={}
  for sku in sku_ids:
   missing[sku]=[name for name,(kind,order) in SLOTS.items() if f'{kind}:{order}' not in snapshot['contents'][sku]]
   issues[sku]={slot:e for slot,e in snapshot['audit'][sku].items() if e['status']!=4}
  scores={};health=None
  if include_health:
   from .products import ProductService
   health=ProductService(self.state,self.client).list_health(profile,page_size=100,max_pages=1000)
   for row in health['items']:
    sku=positive(row['skuId']);value=row.get('healthScore')
    if sku in sku_ids and not isinstance(value,bool) and isinstance(value,(int,float)) and 0<=value<=100:scores[sku]=value
  return {'complete':True,'skuCount':len(sku_ids),'skuIds':sku_ids,'productId':positive(product_id),'profile':profile,'missingSlots':missing,'auditIssues':issues,'snapshot':snapshot,'metricName':'商品信息健康分','metricField':'healthScore','portalScoreEquivalent':None,'scoreSourceComplete':health['complete'] if health else False,'scores':scores,'informationHealth':health,'scoresRequested':include_health,'unscoredSkuIds':[s for s in sku_ids if s not in scores],'lowScoreSkuIds':[s for s,v in scores.items() if v<=89],'onSaleSkuIds':[positive(r['skuId']) for r in skus if str(r.get('status'))=='103'],'writesPerformed':False,'auditApproved':False,'scoreRecalculated':False,'observedAt':time.time()}
 def _path(self,plan_id):
  if not isinstance(plan_id,str) or len(plan_id)!=24 or any(c not in '0123456789abcdef' for c in plan_id):raise SafetyError('invalid-material-plan-id')
  return safe_join(self.state,'sku-material-plans/'+plan_id+'.json')
 def plan(self,plan_id):
  plan=read_json(self._path(plan_id))
  from .sku_material_authorization import checked_plan
  return checked_plan(self.ops,plan)
 def prepare(self,profile,product_id,changes):
  changes=changes_checked(changes);product_id=positive(product_id);shop={k:self.ops.shop(profile)[k] for k in ('profile','venderId','shopName','shopId')};intent={'shop':shop,'productId':product_id,'changes':changes};intent_hash=digest(intent)
  with FileLock(self.state/'sku-material-plan.lock'):
   index_path=safe_join(self.state,'sku-material-intents/'+intent_hash+'.json');prior=read_json(index_path)
   if prior:return self.plan(prior['planId'])
   self.ops._assert_resolved(shop,resolved_uploads=[row['uploadTaskId'] for row in changes if 'uploadTaskId' in row])
   siblings,_=census(self.ops,profile,product_id);sku_ids=identifiers(sorted({r['skuId'] for r in changes},key=int))
   if not set(sku_ids)<=set(siblings):raise SafetyError('material-change-sku-not-in-product')
   cards=capabilities(self.client,shop)
   sources={tid:upload_source(self.ops,shop,tid) for tid in sorted({r['uploadTaskId'] for r in changes if 'uploadTaskId' in r})};snapshot=read_materials(self.client,shop,sku_ids);tasks=[]
   from .sku_material_contract import body_from_proof
   proofs=[]
   for start in range(0,len(sku_ids),BATCH):
    group=sku_ids[start:start+BATCH];proof={'version':1,'intentHash':intent_hash,'capabilities':cards,'productId':product_id,'siblingSkuIds':siblings,'skuIds':group,'baseline':{sku:snapshot['contents'][sku] for sku in group},'changes':[r for r in changes if r['skuId'] in group],'sources':{tid:sources[tid] for tid in sorted({r['uploadTaskId'] for r in changes if r['skuId'] in group and 'uploadTaskId' in r})}}
    from .sku_material_repair import repair_fields
    proof.update(repair_fields(self.ops,proof['baseline'],{sku:snapshot['audit'][sku] for sku in group},proof['changes']))
    body,_=body_from_proof(self.ops,shop,proof);proofs.append((proof,body))
   from .sku_material_repair import finalize_proofs
   proofs=finalize_proofs(self.ops,shop,[proof for proof,body in proofs])
   # Validate every local chunk before persisting any operation task.
   for proof,body in proofs:
    task=self.ops.prepare(profile,{'url':WRITE,'method':'POST','params':{},'body':body,'skillId':SKILL},sku_material_input=proof);tasks.append({'taskId':task['taskId'],'fingerprint':task['fingerprint']})
   scope={**intent,'intentHash':intent_hash,'tasks':tasks,'runtimeVersion':tasks and self.ops.task(tasks[0]['taskId'])['scope']['runtimeVersion']};fingerprint=digest(scope);plan_id=fingerprint[:24];plan={'planId':plan_id,'fingerprint':fingerprint,'scope':scope,'tasks':tasks,'skuCount':len(sku_ids),'changeCount':len(changes),'createdAt':time.time(),'requiresWriteApproval':True}
   atomic_json(self._path(plan_id),plan);atomic_json(index_path,{'planId':plan_id});return plan
 def approve(self,plan_id,fingerprint,*,confirmed=False,ttl_seconds=900):
  plan=self.plan(plan_id)
  if not confirmed or fingerprint!=plan['fingerprint'] or any(self.ops.task(i['taskId'])['status']!='prepared' for i in plan['tasks']):raise SafetyError('exact-unstarted-material-plan-approval-required')
  if isinstance(ttl_seconds,bool) or not isinstance(ttl_seconds,int) or not 1<=ttl_seconds<=3600:raise SafetyError('invalid-material-approval-ttl')
  deadline=time.time()+ttl_seconds
  plan['approval']={'fingerprint':fingerprint,'confirmed':True,'expiresAt':deadline,'approvedAt':time.time()}
  atomic_json(self._path(plan_id),plan)
  for item in plan['tasks']:
   # One user scope, one common deadline, not a renewed TTL for every chunk.
   self.ops.approve(item['taskId'],item['fingerprint'],confirmed=True,ttl_seconds=ttl_seconds)
   with FileLock(self.state/'install.lock'),FileLock(self.state/'tasks.lock'):
    task=self.ops.task(item['taskId']);task['approval']['expiresAt']=min(task['approval']['expiresAt'],deadline);atomic_json(self.ops._path(item['taskId']),task)
  return self.status(plan_id)
 def execute(self,plan_id):
  plan=self.plan(plan_id)
  with FileLock(self.state/'sku-material-run.lock'):
   for item in plan['tasks']:
    task=self.ops.task(item['taskId'])
    if task['status']=='prepared':task=self.ops.execute(item['taskId'])
    if task['status']=='unknown':break
    if task['status'] in ('submitted','verified'):task=self.ops.verify_materials(item['taskId'])
    if task['status']!='verified' or not task.get('materialFieldsVerified'):break
  return self.status(plan_id)
 def status(self,plan_id,*,refresh=False):
  plan=self.plan(plan_id);chunks=[]
  for item in plan['tasks']:
   task=self.ops.task(item['taskId'])
   if refresh and task['status'] in ('unknown','submitted','verified'):task=self.ops.verify_materials(item['taskId'])
   chunks.append({'taskId':task['taskId'],'status':task['status'],'targetStateVerified':bool(task.get('targetStateVerified')),'materialFieldsVerified':bool(task.get('materialFieldsVerified')),'auditApproved':bool(task.get('materialAuditApproved')),'readbackAt':task.get('materialReadback',{}).get('at')})
  return {'planId':plan_id,'fingerprint':plan['fingerprint'],'chunkCount':len(chunks),'verifiedChunkCount':sum(t['status']=='verified' and t['materialFieldsVerified'] for t in chunks),'materialFieldsVerified':bool(chunks) and all(t['materialFieldsVerified'] and t['status']=='verified' for t in chunks),'auditApproved':bool(chunks) and all(t['auditApproved'] and t['status']=='verified' for t in chunks),'scoreRecalculated':False,'originalOutcomeUnknown':any(t['status'] in ('unknown','submitting') for t in chunks),'chunks':chunks,'scope':'queried types 31/32/33/36/1002 and every existing order for target SKUs; not a transaction snapshot'}
