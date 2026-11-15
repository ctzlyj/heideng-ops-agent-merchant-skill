"""Approved ready materials across the whole shop, with explicit remaining gaps."""
import copy,time,uuid
from pathlib import Path
from . import VERSION
from .operations import Operations,digest
from .safety import SafetyError,atomic_json,read_json,safe_join,redact
from .state import FileLock
from .shop_material_execution_contract import source_context,slots_checked,changes_for_audit,intent,groups,current_catalog,live_product
from .shop_material_execution_state import path,checked_plan,approval_record
from .sku_material_contract import SLOTS,identifiers,census,read_materials,capabilities,upload_source,body_from_proof,WRITE,SKILL
from .video_delivery import _once

class ShopMaterialExecution:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def plan(self,plan_id):return checked_plan(self.ops,read_json(path(self.state,'shop-material-plans',plan_id)))
 def prepare(self,audit_id,changes,*,target_slots=None):
  with FileLock(self.state/'shop-material-plan.lock'):
   record=source_context(self.ops,audit_id);slots=slots_checked(target_slots);changes=changes_for_audit(record,changes,slots);i=intent(record,changes,slots);ih=digest(i);index=path(self.state,'shop-material-intents',ih[:24]);prior=read_json(index)
   if prior:
    if prior.get('intentHash')!=ih:raise SafetyError('shop-material-intent-registration-conflict')
    return self.status(prior['planId'])
   current_catalog(self.ops,record);shop=i['shop'];self.ops._assert_resolved(shop,resolved_uploads=sorted({r['uploadTaskId'] for r in changes if 'uploadTaskId' in r}));caps=capabilities(self.client,shop) if changes else {};drafts=[]
   if changes and caps['GET']!=record['scope']['sources']['materialCapability']:raise SafetyError('original-shop-material-capability-changed')
   sources={tid:upload_source(self.ops,shop,tid) for tid in sorted({r['uploadTaskId'] for r in changes if 'uploadTaskId' in r})}
   outer={'version':1,'intentHash':ih,'auditId':audit_id,'auditFingerprint':record['fingerprint']}
   for pid,skus,rows in groups(changes):
    siblings,_=census(self.ops,shop['profile'],pid);baseline={sku:record['scope']['sources']['materials']['contents'][sku] for sku in skus};observed=read_materials(self.client,shop,skus,caps['GET']['inputSchema'])
    if observed['contents']!=baseline:raise SafetyError('original-shop-material-slots-changed-during-plan')
    proof={'version':1,'intentHash':ih,'capabilities':caps,'productId':pid,'siblingSkuIds':siblings,'skuIds':skus,'baseline':baseline,'changes':rows,'sources':{tid:sources[tid] for tid in sorted({r['uploadTaskId'] for r in rows if 'uploadTaskId' in r})}}
    from .sku_material_repair import repair_fields,check_live_audit
    proof.update(repair_fields(self.ops,baseline,{sku:record['scope']['sources']['materials']['audit'][sku] for sku in skus},rows));check_live_audit(proof,observed)
    live_product(self.ops,{'skuMaterialInput':proof,'shop':shop},record);body,_=body_from_proof(self.ops,shop,proof);drafts.append((proof,body))
   from .sku_material_repair import finalize_proofs
   drafts=finalize_proofs(self.ops,shop,[proof for proof,body in drafts]);tasks=[]
   from .shop_material_execution_state import root_preparation
   with root_preparation(self.ops,ih,shop) as preparing:
    for proof,body in drafts:
     task=self.ops.prepare(shop['profile'],{'url':WRITE,'method':'POST','params':{},'body':body,'skillId':SKILL},sku_material_input=proof,shop_material_input=outer);tasks.append({'taskId':task['taskId'],'fingerprint':task['fingerprint']});preparing.children.add(task['taskId'])
   scope={'intent':i,'intentHash':ih,'capabilities':caps,'tasks':tasks,'runtimeVersion':VERSION};fp=digest(scope);plan={'planId':fp[:24],'fingerprint':fp,'scope':scope,'createdAt':time.time()};_once(path(self.state,'shop-material-plans',plan['planId']),plan);_once(index,{'planId':plan['planId'],'intentHash':ih});return self.status(plan['planId'])
 def approve(self,plan_id,fingerprint,*,confirmed=False,ttl_seconds=900):
  with FileLock(self.state/'shop-material-run.lock'):
   plan=self.plan(plan_id);tasks=[self.ops.task(r['taskId']) for r in plan['scope']['tasks']]
   if confirmed is not True or fingerprint!=plan['fingerprint'] or type(ttl_seconds) is not int or not 30<=ttl_seconds<=3600 or not any(t['status']=='prepared' for t in tasks) or any(t['status'] not in ('prepared','verified') for t in tasks):raise SafetyError('exact-known-shop-material-root-or-tail-approval-required')
   self.ops._assert_resolved(plan['scope']['intent']['shop'],resolved_uploads=sorted({r['uploadTaskId'] for r in plan['scope']['intent']['changes'] if 'uploadTaskId' in r}))
   aid=uuid.uuid4().hex;grant={'confirmed':True,'fingerprint':fingerprint,'expiresAt':time.time()+ttl_seconds,'approvedAt':time.time()};record={'planId':plan_id,'fingerprint':fingerprint,'approvalId':aid,'approval':grant,'shop':plan['scope']['intent']['shop']}
   _once(safe_join(self.state,'shop-material-approvals/'+plan_id+'/'+aid+'.json'),record);plan.update(approvalId=aid,approval=grant,approvalSha256=digest(record));atomic_json(path(self.state,'shop-material-plans',plan_id),plan)
   for t in tasks:
    if t['status']=='prepared':self.ops.approve(t['taskId'],t['fingerprint'],confirmed=True,ttl_seconds=ttl_seconds)
   return self.status(plan_id)
 def execute(self,plan_id):
  with FileLock(self.state/'shop-material-run.lock'):
   plan=self.plan(plan_id);states=[self.ops.task(r['taskId'])['status'] for r in plan['scope']['tasks']]
   if any(s in ('unknown','submitting') for s in states):return self.status(plan_id)
   if any(s=='prepared' for s in states):
    original=approval_record(self.ops,plan)
    if original['approval']['expiresAt']<=time.time():raise SafetyError('current-whole-shop-approval-required-before-execution')
   if any(s=='prepared' for s in states):
    from .shop_material_execution_state import root_dispatch
    with root_dispatch(self.ops,plan):self._run_chunks(plan)
   else:self._run_chunks(plan)
   ready=all(self.ops.task(r['taskId'])['status']=='verified' and self.ops.task(r['taskId']).get('materialFieldsVerified') is True for r in plan['scope']['tasks'])
   fresh=False
   if ready:
    try:current_catalog(self.ops,source_context(self.ops,plan['scope']['intent']['auditId'],plan['scope']['intent']['auditFingerprint']),all_siblings=True);fresh=True
    except SafetyError:pass
    plan['catalogObservation']={'at':time.time(),'matched':fresh,'reason':'matched' if fresh else 'changed-or-unavailable'};atomic_json(path(self.state,'shop-material-plans',plan_id),plan)
   result=self.status(plan_id);result['currentCatalogScopeVerified']=fresh;return result
 def _run_chunks(self,plan):
  for ref in plan['scope']['tasks']:
   t=self.ops.task(ref['taskId'])
   if t['status']=='prepared':t=self.ops.execute(t['taskId'])
   if t['status']=='unknown':break
   if t['status'] in ('submitted','verified'):t=self.ops.verify_materials(t['taskId'])
   if t['status']!='verified' or t.get('materialFieldsVerified') is not True:break
 def coverage(self,plan):
  from .sku_material_repair import is_empty
  i=plan['scope']['intent'];record=source_context(self.ops,i['auditId'],i['auditFingerprint']);ready={(r['skuId'],r['slot']):r.get('action','fill') for r in i['changes']};result=[]
  for row in record['scope']['items']:
   if row['onSale'] is not True:continue
   sku=row['skuId'];contents=record['scope']['sources']['materials']['contents'][sku];audit=record['scope']['sources']['materials']['audit'][sku]
   for slot in i['targetSlots']:
    kind,order=SLOTS[slot];key=f'{kind}:{order}';material=contents.get(key);evidence=audit.get(key,{})
    if material is None:state='ready' if (sku,slot) in ready else 'awaiting-material'
    elif ready.get((sku,slot))=='repair':state='ready-repair'
    else:
     values=material['textMaterial']['contents'] if kind==1002 else material['imageMaterial']['skuImages'];state='existing-content' if values and (kind!=1002 or any(v.strip() for v in values)) else 'existing-empty'
    result.append({'productId':row['productId'],'skuId':sku,'slot':slot,'state':state,'originalAuditStatus':evidence.get('status'),'originalAuditReason':evidence.get('reason'),'originalEmpty':material is not None and is_empty(material),'originalContentSha256':digest(material) if material is not None else None})
  return result
 def status(self,plan_id,*,refresh=False):
  plan=self.plan(plan_id);chunks=[]
  for ref in plan['scope']['tasks']:
   t=self.ops.task(ref['taskId'])
   if refresh and t['status'] in ('submitted','verified','unknown'):t=self.ops.verify_materials(t['taskId'])
   chunks.append({'taskId':t['taskId'],'status':t['status'],'materialFieldsVerified':t.get('materialFieldsVerified') is True,'auditApproved':t.get('materialAuditApproved') is True,'productId':t['scope']['skuMaterialInput']['productId'],'skuCount':len(t['scope']['skuMaterialInput']['skuIds'])})
  rows=self.coverage(plan);i=plan['scope']['intent'];audit=source_context(self.ops,i['auditId'],i['auditFingerprint'])['scope'];sale=[r for r in audit['items'] if r['onSale'] is True];all_ready=bool(chunks) and all(r['status']=='verified' and r['materialFieldsVerified'] for r in chunks);awaiting=sum(r['state']=='awaiting-material' for r in rows);empty=sum(r['state']=='existing-empty' or (r['state']=='ready-repair' and r['originalEmpty']) for r in rows)
  issues=sum(r['originalAuditStatus'] not in (None,4) or r['state'].startswith('existing') and r['originalAuditStatus'] is None for r in rows);observation=plan.get('catalogObservation',{})
  return {'planId':plan_id,'fingerprint':plan['fingerprint'],'runtimeVersion':plan['scope']['runtimeVersion'],'auditId':i['auditId'],'auditFingerprint':i['auditFingerprint'],'productCount':len(audit['products']),'onSaleSkuCount':len(sale),'offSaleSiblingCount':len(audit['items'])-len(sale),'targetSlots':i['targetSlots'],'readyChangeCount':len(i['changes']),'readyRepairCount':sum(r.get('action')=='repair' for r in i['changes']),'verifiedRepairCount':sum(sum(row.get('action')=='repair' for row in self.ops.task(ref['taskId'])['scope']['skuMaterialInput']['changes']) for ref in plan['scope']['tasks'] if self.ops.task(ref['taskId'])['status']=='verified' and self.ops.task(ref['taskId']).get('materialFieldsVerified') is True),'awaitingMaterialCount':awaiting,'existingEmptySlotCount':empty,'existingRejectedSlotCount':sum(r['originalAuditStatus']==5 for r in rows),'existingPendingSlotCount':sum(r['originalAuditStatus']==3 for r in rows),'chunkCount':len(chunks),'verifiedChunkCount':sum(r['status']=='verified' and r['materialFieldsVerified'] for r in chunks),'allReadyChangesVerified':all_ready,'allTargetSlotsHaveContent':not awaiting and not any(r['state']=='existing-empty' for r in rows) and (all_ready or not chunks),'noWorkInTargetScope':not i['changes'] and not awaiting and not empty and not issues,'existingUnknownAuditSlotCount':sum(r['state'].startswith('existing') and r['originalAuditStatus'] not in (3,4,5) for r in rows),'currentCatalogScopeVerified':False,'catalogHistoricallyMatched':observation.get('matched') is True,'catalogObservationReason':observation.get('reason'),'catalogObservedAt':observation.get('at'),'originalOutcomeUnknown':any(r['status'] in ('unknown','submitting') for r in chunks),'auditApprovedForWrittenChanges':all_ready and all(r['auditApproved'] for r in chunks),'approvalExpiresAt':plan.get('approval',{}).get('expiresAt'),'historicalAuditCapture':True,'transactionSnapshot':False,'scoreRecalculated':False,'generationCalls':0,'summaryOnly':True,'rowsCommand':'shop-material-rows'}
 def rows(self,plan_id,*,page=1,page_size=50,view='coverage'):
  if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or not 1<=page_size<=200 or view not in ('coverage','chunks'):raise SafetyError('bounded-shop-material-row-page-required')
  plan=self.plan(plan_id)
  if view=='coverage':rows=self.coverage(plan)
  else:
   rows=[]
   for ref in plan['scope']['tasks']:
    t=self.ops.task(ref['taskId']);rows.append({'taskId':t['taskId'],'status':t['status'],'productId':t['scope']['skuMaterialInput']['productId'],'skuIds':t['scope']['skuMaterialInput']['skuIds']})
  start=(page-1)*page_size;selected=rows[start:start+page_size];return {'planId':plan_id,'view':view,'total':len(rows),'items':selected,'page':page,'pageSize':page_size,'nextPage':page+1 if start+len(selected)<len(rows) else None,'pageIsWholeScope':page==1 and len(selected)==len(rows)}
