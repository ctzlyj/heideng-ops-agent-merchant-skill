"""Exact-root native import API; reconstructs outcomes, never replays an attempt."""
import uuid,time
from pathlib import Path
from . import VERSION
from .operations import digest
from .state import FileLock
from .safety import SafetyError,safe_join,read_json,file_sha
from .video_delivery import _once
from .short_titles import ShortTitlePlans
from .short_title_browser import _source_record
from .short_title_workbook import compile_template
from .short_title_import_state import record,evidence,batch_rows,approvals,intent,filename,path,event_path,valid_time,check_result,check_preflight,check_observation

class ShortTitleImports:
 def __init__(self,state,client,*,clock=None):self.state=Path(state).absolute();self.client=client;self.plans=ShortTitlePlans(self.state,client);self.clock=clock or time.time;self.live_browser=None
 def record(self,import_id):return record(self.state,self.client,import_id)
 def _current(self,p,*,readonly=False,health=False,batch=None,install_guard=None):
  from .short_title_contract import source_context
  from .shop_material_execution_contract import current_catalog
  from .operations import _same_identity
  if not _same_identity(self.client.identity(p['scope']['shop']['profile']),p['scope']['shop']):raise SafetyError('native-import-current-shop-identity-mismatch')
  if readonly:return
  from .short_title_result_state import read_log
  anchors=evidence(self.state,p)[3];read_log(self.state,p,anchors)
  from .short_title_effect_state import read_log as effect_log
  effect_log(self.state,p,anchors)
  self.plans.ops._assert_resolved(p['scope']['shop'],exclude_native_import=p['importId'])
  audit,_=source_context(self.state,self.plans.plan(p['scope']['planId'])['scope']['auditId']);current_catalog(self.plans.ops,audit,all_siblings=True)
  if health:
   from .shop_material_audit import ShopMaterialAudit
   fresh=ShopMaterialAudit(self.state,self.client).audit(p['scope']['shop']['profile'],install_guard=install_guard);current,rows=source_context(self.state,fresh['auditId']);known={r['skuId']:r for r in rows};selected=p['scope']['chunks'][batch-1] if batch else p['scope']['changes']
   if current['scope']['shop']!=p['scope']['shop'] or any(r['skuId'] not in known or known[r['skuId']]['onSale'] is not True or known[r['skuId']]['nativeTitleIssue'] is not True or known[r['skuId']]['productId']!=r['productId'] for r in selected):raise SafetyError('current-title-issue-no-longer-proven-no-overwrite')
   return {'healthAuditId':fresh['auditId'],'healthAuditFingerprint':fresh['fingerprint']}
 def prepare(self,plan_id,source_id):
  with FileLock(safe_join(self.state,'short-title-imports.lock')):
   plan=self.plans.plan(plan_id);source=_source_record(self.state,self.client,source_id);ih=intent(plan);index=read_json(path(self.state,'short-title-import-intents',ih[:24]))
   if index:
    p=self.record(index['importId'])
    if p['scope']['sourceId']!=source_id:raise SafetyError('existing-import-intent-requires-original-source-recovery')
    return self.status(p['importId'])
   if source['scope']['planFingerprint']!=plan['fingerprint'] or source['scope']['runtimeVersion']!=VERSION or not plan['scope']['changes']:raise SafetyError('current-original-browser-source-and-reviewed-copy-required')
   template=safe_join(self.state,source['scope']['template']['localPath']).read_bytes();artifacts=[]
   for n,chunk in enumerate(plan['scope']['chunks'],1):
    raw=compile_template(template,[{k:r[k] for k in ('skuId','shortTitle')} for r in chunk]);from .short_title_browser_contract import sha_bytes
    sha=sha_bytes(raw);name=filename(source_id,n,sha);relative='short-title-import-workbooks/'+source_id+'/'+name;f=safe_join(self.state,relative);f.parent.mkdir(parents=True,exist_ok=True)
    if not f.exists():
     with f.open('xb') as stream:stream.write(raw);stream.flush();__import__('os').fsync(stream.fileno())
    if file_sha(f)!=sha:raise SafetyError('original-import-workbook-conflict')
    artifacts.append({'batch':n,'rowCount':len(chunk),'rowsSha256':digest(chunk),'localPath':relative,'sha256':sha,'byteCount':len(raw),'filename':name})
   scope={'kind':'native-short-title-browser-import','runtimeVersion':VERSION,'planId':plan_id,'planFingerprint':plan['fingerprint'],'sourceId':source_id,'sourceFingerprint':source['fingerprint'],'shop':plan['scope']['shop'],'intentHash':ih,'changes':plan['scope']['changes'],'chunks':plan['scope']['chunks'],'artifacts':artifacts};fp=digest(scope);p={'importId':fp[:24],'fingerprint':fp,'scope':scope};self._current(p);root=path(self.state,'short-title-imports',p['importId'])
   if root.exists():raise SafetyError('original-import-intent-index-missing-review-required')
   _once(root,p);_once(path(self.state,'short-title-import-intents',ih[:24]),{'importId':p['importId'],'intentHash':ih});return self.status(p['importId'])
 def approve(self,import_id,fingerprint,*,confirmed=False,ttl=900):
  if confirmed is not True or type(ttl) is not int or not 30<=ttl<=3600:raise SafetyError('explicit-exact-native-title-import-approval-required')
  with FileLock(path(self.state,'short-title-imports',import_id,suffix='.lock')):
   p=self.record(import_id);evidence(self.state,p)
   if p['fingerprint']!=fingerprint or p['scope']['runtimeVersion']!=VERSION:raise SafetyError('current-exact-import-root-fingerprint-required')
   guard=None
   if self.live_browser is not None and self.live_browser.import_id==import_id:
    self._browser(p,self.live_browser);self.live_browser.install_lock.require_owned(self.state/'install.lock');guard=self.live_browser.install_lock
   self._current(p,health=True,install_guard=guard);now=self.clock();existing=approvals(self.state,p)
   if not valid_time(now):raise SafetyError('native-import-approval-time-required')
   if not any(a['approvedAt']<=now<a['expiresAt'] for a in existing.values()):
    aid=uuid.uuid4().hex;_once(safe_join(self.state,'short-title-import-approvals/'+import_id+'/'+aid+'.json'),{'importId':import_id,'fingerprint':p['fingerprint'],'shop':p['scope']['shop'],'approvalId':aid,'confirmed':True,'approvedAt':now,'expiresAt':now+ttl})
   return self.status(import_id)
 def status(self,import_id):
  p=self.record(import_id);ev=evidence(self.state,p);rows=batch_rows(p,ev);now=self.clock();active=any(a['approvedAt']<=now<a['expiresAt'] for a in ev[0].values());states={r['state'] for r in rows};submitted=sum(r['state']=='submitted' for r in rows)
  status='unknown' if any(x.startswith('unknown') for x in states) else 'non-success-unverified' if any(x.endswith('non-success') for x in states) else 'submitted-awaiting-verification' if submitted==len(rows) else 'uploaded-awaiting-create' if 'uploaded-awaiting-create' in states else 'partial-submitted' if submitted else 'approved' if active else 'prepared'
  result={'importId':import_id,'fingerprint':p['fingerprint'],'status':status,'proposedRowCount':len(p['scope']['changes']),'approvedRowCount':len(p['scope']['changes']) if ev[0] else 0,'batchCount':len(rows),'submittedBatchCount':submitted,'unknownBatchCount':sum(r['state'].startswith('unknown') for r in rows),'approvalCurrentlyValid':active,'executionApiAvailable':True,'CLIWorkerIntegrated':True,'imported':False,'actualTitlesVerified':False,'healthVerified':False,'rowResultsVerified':False,'taskListComplete':False,'runtimeVersion':p['scope']['runtimeVersion']}
  from .short_title_result_state import read_log,summary
  result.update(summary(p,read_log(self.state,p,ev[3])[0]))
  if result['rowResultsVerified']:result['status']='processing-completed-awaiting-title-verification'
  from .short_title_effect_state import read_log as effect_log,summary as effect_summary
  latest_effect,count,_=effect_log(self.state,p,ev[3]);result.update(effect_summary(latest_effect,count))
  if result['actualTitlesVerified']:result['status']='actual-titles-observed-awaiting-audit-health-portal'
  return result
 def rows(self,import_id,*,page=1,page_size=50,view='batches'):
  if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or not 1<=page_size<=200 or view not in ('batches','changes','results','effects'):raise SafetyError('bounded-native-import-page-required')
  p=self.record(import_id);ev=evidence(self.state,p);from .short_title_result_state import read_log,result_rows;latest=read_log(self.state,p,ev[3])[0];rows=result_rows(p,ev[3],latest) if view=='results' else batch_rows(p,ev) if view=='batches' else p['scope']['changes'];
  if view=='effects':
   from .short_title_effect_state import read_log as effect_log,effect_rows
   rows=effect_rows(self.state,p,effect_log(self.state,p,ev[3])[0])
  start=(page-1)*page_size;items=rows[start:start+page_size]
  return {'importId':import_id,'view':view,'items':items,'total':len(rows),'nextPage':page+1 if start+len(items)<len(rows) else None,'pageIsWholeScope':page==1 and len(items)==len(rows),'imported':False}
 def collect_results(self,import_id,browser,*,batch=None):
  from .short_title_result_state import read_log,append_observation
  from .short_title_result_browser import observe_result
  with FileLock(path(self.state,'short-title-imports',import_id,suffix='.lock')):
   p=self.record(import_id);self._browser(p,browser);browser.install_lock.require_owned(self.state/'install.lock');self._current(p,readonly=True);ev=evidence(self.state,p)
   if batch is not None and (type(batch) is not int or not 1<=batch<=len(p['scope']['chunks'])):raise SafetyError('exact-original-result-batch-required')
   read_log(self.state,p,ev[3],repair=True)
   if any(key[1]=='upload' and ack['result']['outcome']=='accepted' and (key[0],'create') not in ev[1] for key,ack in ev[2].items()):
    out=self.status(import_id);out.update(currentResultSourceVerified=False,currentTaskAnchorMatched=False,stoppedReason='uncreated-original-upload-binding-preserved');return out
   targets=[batch] if batch is not None and (batch,'create') in ev[3] else sorted(key[0] for key in ev[3]) if batch is None else []
   if not targets:
    out=self.status(import_id);out.update(currentResultSourceVerified=False,currentTaskAnchorMatched=False,stoppedReason='original-task-anchor-required-before-result-observation');return out
   matched=True;result_verified=True
   for number in targets:
    try:observation=observe_result(browser,number)
    except Exception:
     out=self.status(import_id);out.update(currentResultSourceVerified=False,currentTaskAnchorMatched=False,stoppedReason='original-task-result-source-not-verified');return out
    append_observation(self.state,p,ev[3],number,observation,self.clock());anchor=ev[3][number,'create'];task_matched=observation['source']=={'instanceId':anchor['instanceId'],'uploadedObjectSha256':anchor['objectSha256'],'startedAt':anchor['startedAt']};matched=matched and task_matched;result_verified=result_verified and task_matched and observation['download'] is not None and observation['result'] is not None and observation['download']['resultObjectSha256']==observation['resultSourceSha256']
   out=self.status(import_id);out.update(currentTaskAnchorMatched=matched,currentResultSourceVerified=result_verified,currentResultReadBatches=targets);return out
 def collect_effects(self,import_id,browser,*,max_pages=1000):
  from .short_title_verification import observe_original_effects
  from .short_title_result_state import read_log as result_log
  from .short_title_effect_state import read_log as effect_log,append_observation
  with FileLock(path(self.state,'short-title-imports',import_id,suffix='.lock')):
   p=self.record(import_id);self._browser(p,browser);browser.install_lock.require_owned(self.state/'install.lock');self._current(p,readonly=True);anchors=evidence(self.state,p)[3]
   result_log(self.state,p,anchors,repair=True);effect_log(self.state,p,anchors,repair=True)
   observed=observe_original_effects(self,import_id,browser,max_pages=max_pages)
   self._current(p,readonly=True);self._browser(p,browser);browser.install_lock.require_owned(self.state/'install.lock')
   sequence=append_observation(self.state,p,anchors,observed,self.clock())
   self._browser(p,browser);browser.install_lock.require_owned(self.state/'install.lock')
   observed.update(C3ReceiptPersisted=True,effectObservationSequence=sequence,currentEffectSourceVerified=observed['sourceDetailsStable'] and observed['currentOriginalScopeComplete'],currentNativeHealthSourceVerified=observed.get('nativeHealthSourcesVerified',False))
   return observed
 def prepare_repair(self,import_id,browser,changes):
  from .short_title_repair import ShortTitleRepairPlans
  return ShortTitleRepairPlans(self).prepare(import_id,browser,changes)
 def repair_record(self,import_id,repair_id):
  from .short_title_repair import ShortTitleRepairPlans
  return ShortTitleRepairPlans(self).record(import_id,repair_id)
 def repair_status(self,import_id,repair_id):
  from .short_title_repair import ShortTitleRepairPlans
  return ShortTitleRepairPlans(self).status(import_id,repair_id)
 def repair_rows(self,import_id,repair_id,**kwargs):
  from .short_title_repair import ShortTitleRepairPlans
  return ShortTitleRepairPlans(self).rows(import_id,repair_id,**kwargs)
 def approve_repair(self,import_id,repair_id,fingerprint,browser,**kwargs):
  from .short_title_repair import ShortTitleRepairPlans
  return ShortTitleRepairPlans(self).approve(import_id,repair_id,fingerprint,browser,**kwargs)
 def _browser(self,p,browser):
  from .short_title_import_browser import ShortTitleImportBrowser
  if not isinstance(browser,ShortTitleImportBrowser) or browser.manager.state!=self.state or browser.import_id!=p['importId'] or browser.root_fingerprint!=p['fingerprint'] or browser.session_id!=p['scope']['sourceId'] or browser.page is None or browser.context is None or browser.install_lock is None or not browser.owns_lifecycle or read_json(browser.lifecycle_path,{}).get('status')!='open':raise SafetyError('original-owned-native-import-browser-required')
 def _approval(self,p):
  now=self.clock();values=[a for a in approvals(self.state,p).values() if a['approvedAt']<=now<a['expiresAt']]
  if not values or p['scope']['runtimeVersion']!=VERSION:raise SafetyError('valid-current-native-import-approval-required')
  return max(values,key=lambda a:a['approvedAt'])
 def _worker_checkpoint(self):
  witness=getattr(self.plans.ops,'worker_witness',None)
  if witness is not None:witness.checkpoint()
 def _attempt(self,p,batch,phase,proof,*,install_guard=None):
  approval=self._approval(p);health=self._current(p,health=True,batch=batch,install_guard=install_guard);proof={**proof,**health};p=self.record(p['importId']);evidence(self.state,p);artifact=p['scope']['artifacts'][batch-1];now=self.clock();check_preflight(proof,_source_record(self.state,None,p['scope']['sourceId'])['scope']['template']['sha256']);a={'context':{'importId':p['importId'],'fingerprint':p['fingerprint'],'shop':p['scope']['shop'],'batch':batch,'phase':phase,'artifactSha256':artifact['sha256'],'rowsSha256':artifact['rowsSha256'],'attemptId':uuid.uuid4().hex},'approvalId':approval['approvalId'],'startedAt':now,'deadline':min(now+30,approval['expiresAt']),'preflight':proof};_once(event_path(self.state,'short-title-import-attempts',p['importId'],batch,phase),a);self._worker_checkpoint();return a
 def _ack(self,p,batch,phase,a,result):check_result(result,phase);_once(event_path(self.state,'short-title-import-acks',p['importId'],batch,phase),{'context':a['context'],'attemptSha256':digest(a),'result':result});self._worker_checkpoint()
 def _anchor(self,p,batch,browser):
  ev=evidence(self.state,p);key=(batch,'create');at=ev[1].get(key);upload=ev[2].get((batch,'upload'));ack=ev[2].get(key)
  if not at or not upload or upload['result']['outcome']!='accepted' or key in ev[3] or ack and ack['result']['instanceEvidence']=='contradictory':return False
  used={anchor['instanceId'] for anchor in ev[3].values()};stored=ev[5].get(key);observed=stored['observed'] if stored else browser.observe();check_observation(observed);wanted=ack['result']['instanceId'] if ack else None;sha=upload['result']['uploadedObjectSha256'];before=ev[1][batch,'upload']['preflight']['beforeInstanceIds'];candidates=[row for row in observed['rows'] if row['instanceId'] is not None and row['instanceId'] not in used and row['instanceId'] not in before and row['uploadedObjectSha256']==sha and valid_time(row['startedAt']) and at['startedAt']-5<=row['startedAt']<=at['deadline']+5]
  if len(candidates)!=1 or wanted is not None and candidates[0]['instanceId']!=wanted:return False
  if stored is None:
   stored={'context':at['context'],'attemptSha256':digest(at),'uploadAckSha256':digest(upload),'observedAt':self.clock(),'observed':observed};_once(event_path(self.state,'short-title-import-observations',p['importId'],batch,'create'),stored)
  row=candidates[0];anchor={'context':at['context'],'attemptSha256':digest(at),'uploadAckSha256':digest(upload),'instanceId':row['instanceId'],'objectSha256':sha,'startedAt':row['startedAt'],'observedAt':stored['observedAt'],'taskPageSha256':observed['taskPageSha256'],'identitySha256':observed['identitySha256'],'observationSha256':digest(stored)};_once(event_path(self.state,'short-title-import-anchors',p['importId'],batch,'create'),anchor);self._worker_checkpoint();return True
 def recover(self,import_id,browser):
  with FileLock(path(self.state,'short-title-imports',import_id,suffix='.lock')):
   p=self.record(import_id);self._browser(p,browser);self._current(p,readonly=True);rows=batch_rows(p,evidence(self.state,p))
   for row in rows:
    if row['state'] in ('unknown-create','create-non-success'):
     try:self._anchor(p,row['batch'],browser)
     except Exception:pass
     break
    if row['state'] not in ('submitted','not-started'):break
   return self.status(import_id)
 def execute(self,import_id,browser,*,stop_requested=None):
  browser.stop_requested=stop_requested or (lambda:False)
  with FileLock(path(self.state,'short-title-imports',import_id,suffix='.lock')):
   p=self.record(import_id);self._browser(p,browser);self._approval(p);self._current(p);reason=None;stage='preflight'
   for row in batch_rows(p,evidence(self.state,p)):
    if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
    batch=row['batch'];state=row['state'];artifact=p['scope']['artifacts'][batch-1]
    if state=='submitted':continue
    if state.startswith('unknown'):reason='original-unknown-attempt-recovery-only';break
    if state.endswith('non-success'):reason='native-non-success-response-needs-reconciliation';break
    try:
     if state=='not-started':
      stage='preflight';proof=browser.preflight()
      if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
      a=self._attempt(p,batch,'upload',proof,install_guard=browser.install_lock);stage='upload'
      if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
      browser.grant(a);result=browser.upload(artifact,a);self._ack(p,batch,'upload',a,result)
      if result['outcome']!='accepted':reason='upload-outcome-needs-original-reconciliation';break
     if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
     ev=evidence(self.state,p);upload=ev[2][batch,'upload'];proof=ev[1][batch,'upload']['preflight']
     if not browser.can_create(artifact,upload['result']['uploadedObjectSha256']):reason='original-live-upload-binding-not-restored';break
     stage='create';a=self._attempt(p,batch,'create',proof,install_guard=browser.install_lock)
     if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
     browser.grant(a);result=browser.create(artifact,a);self._ack(p,batch,'create',a,result)
     if result['outcome']!='accepted':reason='native-non-success-response-needs-reconciliation';break
     stage='anchor'
     if not self._anchor(p,batch,browser):reason='original-task-source-anchor-not-verified';break
    except Exception:
     if stop_requested is not None and stop_requested():reason='worker-stop-requested-no-next-native-action';break
     reason={'preflight':'current-browser-source-or-template-not-verified','upload':'upload-outcome-unknown-inspect-original-attempt','create':'creation-outcome-unknown-query-original-task','anchor':'original-task-source-anchor-not-verified'}[stage];break
   result=self.status(import_id)
   if reason:result['stoppedReason']=reason
   return result
