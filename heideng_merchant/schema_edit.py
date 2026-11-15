"""Complete source-backed existing-product image/detail edits, not new products."""
import copy,json,re,time,uuid
from pathlib import Path
from . import VERSION
from .operations import Operations,digest,_same_identity
from .safety import SafetyError,atomic_json,read_json,safe_join
from .product_schema import ProductSchemaService,_validate_logical_properties
from .products import _sku_source,identifier,_product_identity,APPLY_DETAIL
from .publication_contract import VALIDATE,PUBLISH,checked_validation,receipt,DetailHTML
from .edit_contract import KIND,validate_baseline,assets,upload_ids,changed_schema,matches_source,container_codes
from .verification import business_payload
from .state import FileLock

class EditService:
 def __init__(self,state,client):
  self.state=Path(state).resolve();self.client=client;self.ops=Operations(state,client);self.schemas=ProductSchemaService(state,client)
 def _path(self,ident):
  if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):raise SafetyError('safe-edit-baseline-id-required')
  return safe_join(self.state,'product-schemas/baselines/'+ident+'.json')
 def _load(self,ident):
  record=read_json(self._path(ident))
  if not isinstance(record,dict) or digest(record.get('scope'))!=record.get('fingerprint') or record['scope'].get('runtimeVersion')!=VERSION:raise SafetyError('original-edit-baseline-missing-modified-or-old-runtime')
  return record
 def _fresh(self,cap):
  scope=cap['scope'];profile=scope['shop']['profile'];actual=self.schemas.detail(profile,scope['productId']);schema,_,_=self.schemas._template(profile,scope['productId'],scope['lastCategoryId'])
  if digest(actual)!=scope['productDetailHash'] or digest(schema)!=digest(scope['rawSchema'] if 'schemaCompiler' in scope else scope['schema']):raise SafetyError('edit-source-or-template-changed-capture-again')
  census=self.schemas.list_skus(profile,scope['productId'],page_size=50)
  if not census['complete'] or census['reportedTotal'] is None or set(identifier(r.get('skuId')) for r in census['items'])!=set(scope['skuIds']):raise SafetyError('complete-current-edit-sku-census-required')
  if not _same_identity(self.client.identity(profile),scope['shop']):raise SafetyError('edit-shop-changed-during-read')
 def baseline(self,capture_id,schema,bindings,sale_sources,*,_stable_id=None):
  cap=self.schemas._load('captures',capture_id);self._fresh(cap);submitted,ids,_=validate_baseline(cap,schema,bindings,sale_sources);self._fresh(cap);source=cap['scope']
  scope={'captureId':capture_id,'captureFingerprint':cap['fingerprint'],'runtimeVersion':VERSION,'shop':source['shop'],'productId':source['productId'],'lastCategoryId':source['lastCategoryId'],'skuIds':ids,'schema':submitted,'containerCodes':sorted(container_codes(source['schema'])),'bindings':copy.deepcopy(bindings),'saleSources':copy.deepcopy(sale_sources),'createdAt':time.time()}
  record={'baselineId':_stable_id or uuid.uuid4().hex[:24],'scope':scope,'fingerprint':digest(scope)}
  path=self._path(record['baselineId'])
  if _stable_id and path.exists():
   old=self._load(_stable_id)
   if digest({k:v for k,v in old['scope'].items() if k!='createdAt'})!=digest({k:v for k,v in scope.items() if k!='createdAt'}):raise SafetyError('native-automatic-baseline-conflict')
   record=old
  else:atomic_json(path,record)
  return self._baseline_view(record)
 @staticmethod
 def _baseline_view(record):
  scope=record['scope']
  return {**record,'schema':copy.deepcopy(scope['schema']),'skuCount':len(scope['skuIds']),'skuIdentityMappingVerified':True,'allBaselineValuesSourceBound':True,'submissionReady':False,'phase':'full-original-edit-baseline-not-submitted'}
 def prepare_baseline(self,capture_id):
  original=self.schemas._load('captures',capture_id);self._fresh(original)
  compiled=self.schemas.compile_capture(capture_id)
  stable=digest({'compiledCapture':compiled['fingerprint'],'compiler':compiled['scope']['schemaCompiler']})[:24]
  with FileLock(self.state/'native-prepare.lock'):
   return self.baseline(compiled['captureId'],compiled['scope']['schema'],compiled['bindings'],compiled['saleSources'],_stable_id=stable)
 @staticmethod
 def _body(scope,schema):return {'scene':'pop','schema':json.dumps(schema,ensure_ascii=False,separators=(',',':'),allow_nan=False),'productApplyDTO':{'productId':int(scope['productId']),'categoryDTO':{'lastCategoryId':int(scope['lastCategoryId'])}}}
 def plan_validation(self,baseline_id,changes):
  record=self._load(baseline_id);b=record['scope'];cap=self.schemas._load('captures',b['captureId'])
  if cap['fingerprint']!=b['captureFingerprint']:raise SafetyError('baseline-original-capture-fingerprint-changed')
  self._fresh(cap);schema,ids,_=validate_baseline(cap,b['schema'],b['bindings'],b['saleSources']);changes=copy.deepcopy(changes)
  if isinstance(changes,list):
   for c in changes:
    if isinstance(c,dict) and 'html' in c:c['html']=DetailHTML().vetted(c['html'])
  refs=upload_ids(changes);new=changed_schema(schema,changes,assets(self.ops,self.client,b['shop'],refs),b['containerCodes'])
  proof={'kind':KIND,'baselineId':baseline_id,'baselineFingerprint':record['fingerprint'],'editIntentId':baseline_id,'changes':changes,'assetBindings':[{'taskId':i} for i in refs],'intentId':uuid.uuid4().hex}
  task=self.ops.prepare(b['shop']['profile'],{'url':VALIDATE,'method':'POST','params':{},'skillId':'jdo-product-publish','body':self._body(b,new)},listing_input=proof)
  return {'task':task,'skuCount':len(ids),'productId':b['productId'],'phase':'full-edit-validation-awaiting-approval','skuIdentityMappingVerified':True,'allBaselineValuesSourceBound':True,'productBound':False,'onlineEffective':False}
 def plan_edit(self,validation_task_id):
  task=self.ops.task(validation_task_id);scope=task['scope']
  if scope.get('nativeListingInput',{}).get('kind')!=KIND:raise SafetyError('full-existing-edit-validation-required')
  checked_validation(self.ops,validation_task_id,scope['operation']['body'],scope['shop'])
  edit=self.ops.prepare(scope['shop']['profile'],{**scope['operation'],'url':PUBLISH},listing_input=scope['nativeListingInput'],validated_task_id=validation_task_id)
  return {'task':edit,'phase':'full-edit-awaiting-approval' if edit['status']=='prepared' else 'existing-full-edit-request','onlineEffective':False}
 def _known(self,task_id):
  task=self.ops.task(task_id);s=task['scope']
  if s['operation']['url']!=PUBLISH or s.get('nativeListingInput',{}).get('kind')!=KIND:raise SafetyError('existing-product-full-edit-task-required')
  if task['status'] not in ('submitted','verified') or task.get('resultReceiptSha256')!=digest(task.get('result')):raise SafetyError('known-original-full-edit-receipt-required-not-unknown')
  r=receipt(task['result']);product=identifier(s['operation']['body']['productApplyDTO']['productId'])
  if 'applyId' not in r or r.get('productId')!=product:raise SafetyError('original-existing-product-and-apply-id-receipt-required')
  base=self._load(s['nativeListingInput']['baselineId']);cap=self.schemas._load('captures',base['scope']['captureId'])
  if cap['fingerprint']!=base['scope']['captureFingerprint']:raise SafetyError('original-edit-capture-changed')
  validate_baseline(cap,base['scope']['schema'],base['scope']['bindings'],base['scope']['saleSources']);schema=json.loads(s['operation']['body']['schema'])
  return task,r,base['scope'],schema
 def _view(self,task):
  return {'task':task,'phase':'unknown' if task['status']=='unknown' else ('full-edit-receipt-known' if task.get('result') else task['status']),'pendingFieldsVerified':task.get('editPendingFieldsVerified',False),'onlineEffective':task.get('editOnlineFieldsVerified',False),'allSkuOnlineVerified':task.get('editOnlineFieldsVerified',False),'productImagesOnlineVerified':task.get('editOnlineFieldsVerified',False),'remotePixelsVerified':False,'verification':'complete source-bound fields plus original apply/product identity; not pixel inspection'}
 def status(self,task_id,*,refresh=False):
  task=self.ops.task(task_id)
  if task['scope'].get('nativeListingInput',{}).get('kind')!=KIND or task['scope']['operation']['url']!=PUBLISH:raise SafetyError('full-edit-task-required')
  if not refresh or task['status']=='unknown':return self._view(task)
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task,r,b,schema=self._known(task_id);shop=task['scope']['shop']
    if not _same_identity(self.client.identity(shop['profile']),shop):raise SafetyError('full-edit-readback-shop-mismatch')
    reply=self.client.invoke(shop['profile'],APPLY_DETAIL,method='GET',params={'applyId':int(r['applyId']),'scene':'pop'},skill_id='jdo-product-update');data=business_payload(reply)
    _validate_logical_properties(reply)
    from .safety import redact
    if redact(reply)!=reply:raise SafetyError('private-edit-readback-refused')
    matched=isinstance(data,dict) and str(data.get('applyId'))==r['applyId'] and matches_source(data,b,schema)
    if not _same_identity(self.client.identity(shop['profile']),shop):raise SafetyError('full-edit-readback-shop-changed')
    task.update(editPendingFieldsVerified=matched,editPendingReadback={'originalApplyId':r['applyId'],'responseSha256':digest(reply),'checkedAt':time.time(),'allBoundFieldsMatched':matched})
    if matched:task['status']='verified'
    atomic_json(self.ops._path(task_id),task);return self._view(task)
 def verify_online(self,task_id):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task,r,b,schema=self._known(task_id);shop=task['scope']['shop'];data=self.schemas.detail(shop['profile'],b['productId']);census=self.schemas.list_skus(shop['profile'],b['productId'],page_size=50)
    matched=matches_source(data,b,schema) and census['complete'] and census['reportedTotal'] is not None and set(identifier(row.get('skuId')) for row in census['items'])==set(b['skuIds']) and all(row.get('productId') is None or identifier(row['productId'])==b['productId'] for row in census['items'])
    if not _same_identity(self.client.identity(shop['profile']),shop):raise SafetyError('full-edit-online-shop-changed')
    task.update(editOnlineFieldsVerified=matched,editOnlineReadback={'productId':b['productId'],'responseSha256':digest(data),'sourcePageHashes':census['sourcePageHashes'],'checkedAt':time.time(),'allBoundFieldsMatched':matched,'skuCensusComplete':census['complete']})
    atomic_json(self.ops._path(task_id),task);return self._view(task)
