"""Full-product approved missing-main-video binding with exact native readback."""
import copy,time,uuid
from pathlib import Path
from . import VERSION
from .operations import Operations,digest
from .safety import SafetyError,read_json,atomic_json,safe_join
from .state import FileLock
from .video_delivery import VideoDelivery,_once
from .video_binding_contract import context,identity_scope,snapshot,target_material,body_from_proof,contract,relations,WRITE,SKILL,BATCH
from .video_binding_state import path,checked_plan,approval

class VideoBindingService:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def plan(self,plan_id):return checked_plan(self.ops,read_json(path(self.state,'video-binding-plans',plan_id)))
 def _context(self,profile,product_id,session_id,media=False,write_ready=True):
  shop={k:self.ops.shop(profile)[k] for k in ('profile','venderId','shopId','shopName')};return context(self.ops,shop,product_id,session_id,media=media,write_ready=write_ready)
 def preview(self,profile,product_id,session_id):
  ctx=self._context(profile,product_id,session_id,True);self.ops._assert_resolved(ctx['shop'])
  return {'identityReviewScope':identity_scope(ctx),'product':ctx['product'],'source':ctx['source'],'tag':ctx['tag'],'complete':True,'writesPerformed':False,'generationCalls':0}
 def prepare(self,profile,product_id,session_id,*,review=None):
  with FileLock(self.state/'video-binding-plan.lock'):
   ctx=self._context(profile,product_id,session_id,True);self.ops._assert_resolved(ctx['shop'])
   if not isinstance(review,dict) or review.get('passed') is not True or review!={**identity_scope(ctx),'passed':True}:raise SafetyError('exact-video-product-host-identity-review-required')
   ctx['review']=review;intent=digest({'shop':ctx['shop'],'productId':ctx['product']['productId'],'sessionId':session_id});index=path(self.state,'video-binding-intents',intent[:24]);previous=read_json(index)
   if previous:
    if previous.get('intentHash')!=intent:raise SafetyError('native-video-binding-intent-collision')
    return self.status(previous['planId'])
   baseline=snapshot(self.ops,ctx['shop'],ctx['product']['skuIds'],ctx['cards']['GET']);skus=[]
   for sku,slots in baseline['contents'].items():
    current=slots.get('42:1')
    if current is not None and current!=target_material(ctx,sku):raise SafetyError('existing-other-main-video-cannot-be-overwritten')
    if current is None:skus.append(sku)
   skus.sort(key=int);proofs=[]
   for start in range(0,len(skus),BATCH):
    group=skus[start:start+BATCH];proof={'version':1,'intentHash':intent,'context':ctx,'skuIds':group,'baseline':{s:baseline['contents'][s] for s in group},'baselineAudit':{s:baseline['audit'][s] for s in group}};body,_=body_from_proof(self.ops,ctx['shop'],proof,live=True);proofs.append((proof,body))
   tasks=[]
   for proof,body in proofs:
    task=self.ops.prepare(profile,{'url':WRITE,'method':'POST','params':{},'body':body,'skillId':SKILL},video_material_input=proof);tasks.append({'taskId':task['taskId'],'fingerprint':task['fingerprint']})
   scope={'context':ctx,'baseline':baseline['contents'],'baselineAudit':baseline['audit'],'skuIds':skus,'tasks':tasks,'intentHash':intent,'runtimeVersion':VERSION};fingerprint=digest(scope);plan={'planId':fingerprint[:24],'fingerprint':fingerprint,'scope':scope,'createdAt':time.time()}
   _once(path(self.state,'video-binding-plans',plan['planId']),plan);_once(index,{'planId':plan['planId'],'intentHash':intent});return self.status(plan['planId'])
 def approve(self,plan_id,fingerprint,*,confirmed=False,ttl_seconds=900):
  with FileLock(self.state/'video-binding-run.lock'):
   plan=self.plan(plan_id)
   if confirmed is not True or fingerprint!=plan['fingerprint'] or type(ttl_seconds) is not int or not 30<=ttl_seconds<=3600 or any(self.ops.task(t['taskId'])['status']!='prepared' for t in plan['scope']['tasks']):raise SafetyError('exact-unstarted-native-video-binding-parent-approval-required')
   plan['approvalId']=uuid.uuid4().hex;plan['approval']={'confirmed':True,'fingerprint':fingerprint,'expiresAt':time.time()+ttl_seconds};record={'planId':plan_id,'fingerprint':fingerprint,'approvalId':plan['approvalId'],'approval':plan['approval'],'shop':plan['scope']['context']['shop']}
   _once(safe_join(self.state,'video-binding-approvals/'+plan_id+'/'+plan['approvalId']+'.json'),record);plan['approvalSha256']=digest(record);atomic_json(path(self.state,'video-binding-plans',plan_id),plan)
   for t in plan['scope']['tasks']:self.ops.approve(t['taskId'],t['fingerprint'],confirmed=True,ttl_seconds=ttl_seconds)
   return self.status(plan_id)
 def execute(self,plan_id):
  with FileLock(self.state/'video-binding-run.lock'):
   plan=self.plan(plan_id)
   if 'approval' not in plan:raise SafetyError('native-video-binding-parent-approval-required')
   for item in plan['scope']['tasks']:
    task=self.ops.task(item['taskId'])
    if task['status']=='prepared':task=self.ops.execute(item['taskId'])
    if task['status']=='unknown':break
    if task['status'] in ('submitted','verified'):task=self.verify(item['taskId'])
    if task['status']!='verified' or not task.get('videoBindingFieldsVerified') or not task.get('videoBindingRelationsVerified'):break
   return self.status(plan_id,refresh=True)
 def verify(self,task_id):
  with FileLock(self.state/'install.lock'),FileLock(self.state/'tasks.lock'):
   task=self.ops.task(task_id)
   if task['status'] not in ('submitted','verified','unknown') or 'videoMaterialInput' not in task['scope']:raise SafetyError('submitted-native-video-binding-task-required')
   expected=contract(self.ops,task['scope']);proof=task['scope']['videoMaterialInput'];ctx=proof['context'];actual=snapshot(self.ops,ctx['shop'],proof['skuIds'],ctx['cards']['GET']);related=relations(self.ops,ctx);found={r['skuId']:r['status'] for r in related['rows']};matched=digest(actual['contents'])==digest(expected)
   preserved=all(actual['audit'][s].get(k)==v for s,slots in proof['baselineAudit'].items() for k,v in slots.items());visible=all(s in found for s in proof['skuIds']);known=task['status']!='unknown'
   task['videoBindingReadback']={'at':time.time(),'fieldsMatch':matched,'preservedAudit':preserved,'relationsVisible':visible,'sourceHashes':actual['sourceHashes']+related['sourceHashes'],'relationStatuses':{s:found.get(s) for s in proof['skuIds']}}
   task['targetStateVerified']=matched and visible;task['videoBindingFieldsVerified']=matched and known;task['videoBindingRelationsVerified']=visible and known
   if task['targetStateVerified'] and known:task['status']='verified'
   elif task['status']=='verified':task['status']='submitted'
   atomic_json(self.ops._path(task_id),task);return task
 def status(self,plan_id,*,refresh=False):
  plan=self.plan(plan_id);scope=plan['scope'];ctx=scope['context']
  if refresh:
   for item in scope['tasks']:
    task=self.ops.task(item['taskId'])
    if task['status'] in ('submitted','verified','unknown'):self.verify(item['taskId'])
   current=self._context(ctx['shop']['profile'],ctx['product']['productId'],ctx['source']['sessionId'],write_ready=False)
   if digest(current)!=digest({k:v for k,v in ctx.items() if k!='review'}):raise SafetyError('native-video-binding-parent-readback-context-changed')
   actual=snapshot(self.ops,ctx['shop'],ctx['product']['skuIds'],ctx['cards']['GET']);related=relations(self.ops,ctx);expected=copy.deepcopy(scope['baseline'])
   for sku in scope['skuIds']:expected[sku]['42:1']=target_material(ctx,sku)
   found={r['skuId']:r['status'] for r in related['rows']};fields=digest(actual['contents'])==digest(expected);preserved=all(actual['audit'][s].get(k)==v for s,slots in scope['baselineAudit'].items() for k,v in slots.items());visible=set(found)==set(ctx['product']['skuIds']);statuses=[found.get(s) for s in ctx['product']['skuIds']];material_statuses=[actual['audit'][s].get('42:1',{}).get('status') for s in ctx['product']['skuIds']];video=VideoDelivery(self.state,self.client).status(ctx['source']['sessionId'],refresh=True)
   plan['readback']={'at':time.time(),'fieldsMatch':fields,'preservedAudit':preserved,'relationsVisible':visible,'relationStatuses':statuses,'materialStatuses':material_statuses,'videoAuditApproved':video['auditApproved'],'videoAuditStatus':video.get('auditStatus'),'sourceHashes':actual['sourceHashes']+related['sourceHashes']};atomic_json(path(self.state,'video-binding-plans',plan_id),plan)
  chunks=[self.ops.task(t['taskId']) for t in scope['tasks']];unknown=any(t['status'] in ('unknown','submitting') for t in chunks);verified=all(t['status']=='verified' and t.get('videoBindingFieldsVerified') and t.get('videoBindingRelationsVerified') for t in chunks);r=plan.get('readback',{});matched=r.get('fieldsMatch') is True;visible=r.get('relationsVisible') is True;statuses=r.get('relationStatuses',[])+r.get('materialStatuses',[]);approved=matched and visible and len(statuses)==2*len(ctx['product']['skuIds']) and all(v==4 for v in statuses) and r.get('videoAuditApproved') is True
  return {'planId':plan_id,'fingerprint':plan['fingerprint'],'skuCount':len(ctx['product']['skuIds']),'missingMainVideoCount':len(scope['skuIds']),'chunkCount':len(chunks),'verifiedChunkCount':sum(t['status']=='verified' for t in chunks),'productId':ctx['product']['productId'],'videoId':str(ctx['source']['metadata']['videoId']),'jdVideoId':str(ctx['source']['metadata']['jdVideoId']),'skuIds':ctx['product']['skuIds'],'originalOutcomeUnknown':unknown,'targetStateVerified':bool(refresh and matched and visible),'materialFieldsVerified':bool(refresh and matched and verified and not unknown),'relationsVerified':bool(refresh and visible and verified and not unknown),'auditApproved':bool(refresh and approved and verified and not unknown),'auditState':'unknown' if unknown or not refresh or any(v not in (3,4,5) for v in statuses) else 'rejected' if 5 in statuses or r.get('videoAuditStatus')==5 else 'approved' if approved and verified else 'pending','videoAuditStatus':r.get('videoAuditStatus') if refresh else None,'materialAuditStatuses':dict(zip(ctx['product']['skuIds'],r.get('materialStatuses',[]))) if refresh else {},'relationAuditStatuses':dict(zip(ctx['product']['skuIds'],r.get('relationStatuses',[]))) if refresh else {},'nonTargetAuditChanged':bool(refresh and r and r.get('preservedAudit') is False),'freshReadback':refresh,'readbackAt':r.get('at'),'historicalFieldsMatch':matched,'scoreRecalculated':False,'generationCalls':0,'chunks':[{'taskId':t['taskId'],'status':t['status']} for t in chunks]}
