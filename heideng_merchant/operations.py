"""Exact-scope approvals and durable non-replaying merchant operations."""
from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
from . import VERSION
from .safety import SafetyError,atomic_json,read_json,redact,safe_join
from .state import FileLock
from .official import validate_profile,validate_route
from .verification import business_payload,matches_fields,validate_expected
from .price_contract import price_contract,validate_native_price_response
from .result_verification import validate_result_verification,resolve_result_verification
from .image_probe import probe_image
from .publication_contract import check_scope as check_publication_scope,checked_validation,VALIDATION_TTL,VALIDATE,PUBLISH,validation_verdict,receipt as publication_receipt
from .material_contract import describe_upload,check_image_evidence,verify_upload_context,validate_image_receipt

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _operation(value):
 if not isinstance(value,dict):raise SafetyError('operation-object-required')
 allowed={'url','method','params','body','skillId'}
 if set(value)-allowed:raise SafetyError('unreviewed-operation-fields')
 if redact(value)!=value:raise SafetyError('credentials-not-allowed-in-business-payload')
 method=str(value.get('method','GET')).upper()
 if method not in ('GET','POST','PUT','PATCH','DELETE'):raise SafetyError('invalid-operation-method')
 params=value.get('params',{})
 if not isinstance(params,dict):raise SafetyError('params-object-required')
 result={'url':validate_route(value.get('url')),'method':method,'params':params,'skillId':value.get('skillId','jdo-seller-info')}
 if 'body' in value:
  if method=='GET' or not isinstance(value['body'],(dict,list)):raise SafetyError('invalid-operation-body')
  result['body']=value['body']
 from .video_contract import guarded_video_route
 if guarded_video_route(result['url'],method):raise SafetyError('native-video-allocation-or-save-requires-approved-confidential-session')
 if not re.fullmatch('[a-z0-9-]+',str(result['skillId'])):raise SafetyError('invalid-skill-id')
 digest(result)
 return result

def _verification(value):
 if not isinstance(value,dict) or set(value)!={'query','expected'}:raise SafetyError('complete-readback-scope-required')
 query=_operation(value['query']);validate_expected(value['expected'])
 if query['method']!='GET' or redact(value)!=value:raise SafetyError('readonly-nonsecret-readback-required')
 if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))>256*1024:raise SafetyError('verification-scope-too-large')
 return {'query':query,'expected':value['expected']}

def _same_identity(actual,expected):
 return actual.get('shopType')=='POP' and all(str(actual.get(k))==str(expected[k]) for k in ('venderId','shopId','shopName'))

def _match_count(result,expected):
 data=business_payload(result);rows=data if isinstance(data,list) else [data]
 return sum(isinstance(row,dict) and matches_fields(row,expected) for row in rows)

class Operations:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client
 def connect(self,profile,shop_name,vender_id,*,confirmed_alias=None):
  validate_profile(profile)
  if not str(vender_id).isdigit() or not shop_name:raise SafetyError('explicit-shop-identity-required')
  if confirmed_alias is not None and (not isinstance(confirmed_alias,str) or not confirmed_alias.strip() or len(confirmed_alias)>128 or any(ord(c)<32 for c in confirmed_alias) or redact(confirmed_alias)!=confirmed_alias):raise SafetyError('safe-confirmed-shop-alias-required')
  actual=self.client.identity(profile)
  if actual.get('shopType')!='POP' or actual.get('shopName')!=shop_name or actual.get('venderId')!=str(vender_id):raise SafetyError('shop-identity-mismatch')
  actual={**actual,'profile':profile,'verifiedAt':time.time()}
  with FileLock(self.state/'shops.lock'):
   shops=read_json(self.state/'shops.json',{});previous=shops.get(profile)
   if previous and (previous['venderId']!=actual['venderId'] or previous['shopName']!=actual['shopName']):raise SafetyError('profile-already-bound-to-another-shop')
   aliases=previous.get('aliases',[]) if previous else []
   if not isinstance(aliases,list) or any(not isinstance(alias,str) or not alias.strip() or len(alias)>128 or any(ord(c)<32 for c in alias) or redact(alias)!=alias for alias in aliases):raise SafetyError('registered-shop-aliases-invalid')
   if confirmed_alias and confirmed_alias!=shop_name and confirmed_alias not in aliases:
    if any(other_profile!=profile and (other.get('shopName')==confirmed_alias or confirmed_alias in other.get('aliases',[])) for other_profile,other in shops.items()):raise SafetyError('shop-alias-already-bound-select-exact-profile')
    aliases=list(dict.fromkeys([*aliases,confirmed_alias]))
   if aliases:actual['aliases']=aliases
   shops[profile]=actual;atomic_json(self.state/'shops.json',shops)
  return actual
 def shop(self,profile):
  validate_profile(profile);shop=read_json(self.state/'shops.json',{}).get(profile)
  if not shop:raise SafetyError('shop-not-connected')
  return shop
 def _path(self,task_id):
  if not re.fullmatch('[a-f0-9]{24}',str(task_id)):raise SafetyError('invalid-task-id')
  return safe_join(self.state,'tasks/'+task_id+'.json')
 def task(self,task_id):
  value=read_json(self._path(task_id))
  if not value:raise SafetyError('task-not-found')
  if digest(value['scope'])!=value['fingerprint']:raise SafetyError('task-scope-modified')
  from .video_binding_state import checked_task
  value=checked_task(self,value)
  from .shop_material_execution_state import checked_task as checked_shop_task
  return checked_shop_task(self,value)
 def _existing_publication(self,scope,new_id):
  # Persisted creation intent survives copying/moving a package; the path is
  # retained as a conservative fallback for older local task journals.
  import os
  proof=scope['nativeListingInput'];editing=proof.get('kind')=='schema-edit';source=None if editing else os.path.normcase(str(Path(proof['manifestPath']).resolve()));intent=proof['editIntentId'] if editing else proof['publicationIntentId'];prepared=[]
  for path in sorted((self.state/'tasks').glob('*.json')):
   old=read_json(path,{});old_scope=old.get('scope',{});op=old_scope.get('operation',{});old_proof=old_scope.get('nativeListingInput',{});old_source=old_proof.get('manifestPath')
   if op.get('method')!='POST' or op.get('url')!=PUBLISH or old.get('taskId')==new_id:continue
   if any(str(old_scope.get('shop',{}).get(k))!=str(scope['shop'][k]) for k in ('venderId','shopId')):continue
   if editing!=(old_proof.get('kind')=='schema-edit'):continue
   same_path=not editing and isinstance(old_source,str) and os.path.normcase(str(Path(old_source).resolve()))==source
   if not same_path and old_proof.get('editIntentId' if editing else 'publicationIntentId')!=intent:continue
   old=self.task(old['taskId'])
   if old['status'] in ('submitted','verified','submitting','unknown'):return old
   if old['status']=='prepared':prepared.append(old)
  for old in prepared:
   old.update(status='superseded',supersededBy=new_id);atomic_json(self._path(old['taskId']),old)
  return None
 def prepare(self,profile,operation,verification=None,*,precondition=None,online_verification=None,result_verification=None,listing_input=None,validated_task_id=None,sku_material_input=None,video_material_input=None,shop_material_input=None):
  shop=self.shop(profile);operation=_operation(operation)
  scope={'shop':{k:shop[k] for k in ('profile','venderId','shopName','shopId')},'operation':operation,'runtimeVersion':VERSION}
  if callable(getattr(self.client,'plan_execution',None)):
   scope['officialExecution']=self.client.plan_execution(operation,profile=profile)
   if redact(scope['officialExecution'])!=scope['officialExecution']:raise SafetyError('credentials-not-allowed-in-execution-contract')
  for key,value in (('verification',verification),('precondition',precondition),('onlineVerification',online_verification)):
   if value is not None:scope[key]=_verification(value)
  if result_verification is not None:scope['resultVerification']=validate_result_verification(result_verification,_operation)
  if listing_input is not None:
   if operation['method']!='POST' or operation['url'] not in (VALIDATE,PUBLISH) or redact(listing_input)!=listing_input:raise SafetyError('native-publication-input-only')
   scope['nativeListingInput']=listing_input
  if validated_task_id is not None:scope['publicationValidationTaskId']=validated_task_id
  if sku_material_input is not None:scope['skuMaterialInput']=sku_material_input
  if shop_material_input is not None:scope['shopMaterialInput']=shop_material_input
  if video_material_input is not None:scope['videoMaterialInput']=video_material_input
  from .sku_material_contract import contract as material_contract
  material_expected=material_contract(self,scope,live=True)
  publication_stage=check_publication_scope(self,scope,self.client)
  upload=describe_upload(scope)
  if upload:
   descriptor,raw=upload;image=probe_image(self.state,raw);check_image_evidence(descriptor,image);scope['materialUpload']={'image':image}
  contract=price_contract(scope)
  fingerprint=digest(scope);ident=fingerprint[:24];path=self._path(ident)
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    existing=read_json(path)
    if existing:return self.task(ident)
    if publication_stage=='publication':
     prior=self._existing_publication(scope,ident)
     if prior is not None:return prior
    if operation['method']!='GET':
     self._assert_resolved(shop,resolved_uploads=([b['taskId'] for b in scope.get('nativeListingInput',{}).get('assetBindings',[])] if publication_stage else [])+list(scope.get('skuMaterialInput',{}).get('sources',{})))
    planning=None
    if contract:
     if not _same_identity(self.client.identity(profile),shop):raise SafetyError('native-price-planning-shop-mismatch')
     check=scope['precondition'];query=check['query'];response=self.client.invoke(profile,query['url'],method='GET',params=query['params'],skill_id=query['skillId'])
     validate_native_price_response(contract,response,stage='before')
     if _match_count(response,check['expected'])!=1:raise SafetyError('native-price-planning-values-not-current')
     planning={'query':query,'responseSha256':digest(response),'checkedAt':time.time()}
    material_planning=None
    if upload:
     proof=verify_upload_context(self.client,shop,descriptor);material_planning={'zoneChecked':True,'categoryChecked':True,'zonesSha256':digest(proof['zones']),'categoriesSha256':digest(proof['categories']),'checkedAt':time.time()}
    task={'taskId':ident,'fingerprint':fingerprint,'scope':scope,'status':'prepared','createdAt':time.time(),'requiresWriteApproval':operation['method']!='GET'}
    if planning is not None:task['planningEvidence']=planning
    if material_planning is not None:task['materialPlanningEvidence']=material_planning
    atomic_json(path,task);return task
 def _assert_resolved(self,shop,exclude=None,resolved_uploads=(),exclude_video_session=None,exclude_native_import=None):
  from .short_title_worker_gate import assert_resolved as assert_worker_resolved
  assert_worker_resolved(self,shop)
  from .short_title_shop_gate import assert_resolved as assert_native_title_resolved
  assert_native_title_resolved(self,shop,exclude_native_import)
  from .video_binding_state import assert_resolved as assert_binding_resolved
  assert_binding_resolved(self,shop,exclude)
  from .shop_material_execution_state import assert_resolved as assert_shop_material_resolved
  assert_shop_material_resolved(self,shop,exclude)
  from .video_delivery import assert_video_resolved
  assert_video_resolved(self.state,shop,exclude_video_session)
  for entry in (self.state/'tasks').glob('*.json'):
   old=read_json(safe_join(self.state,'tasks/'+entry.name),{});subject=old.get('scope',{}).get('shop',{})
   same=subject.get('profile')==shop['profile'] or all(str(subject.get(k,''))==str(shop[k]) for k in ('venderId','shopId'))
   if old.get('taskId')!=exclude and (old.get('status') in ('unknown','submitting','submitted') or old.get('status')=='verified' and old.get('scope',{}).get('nativeListingInput',{}).get('kind')=='schema-edit' and old.get('editPendingFieldsVerified') is not True) and same:
    if old.get('status')=='submitted' and old.get('taskId') in resolved_uploads and describe_upload(old['scope']) is not None:continue
    # A valid original publication receipt is known acceptance, not online activation.
    if old.get('status')=='submitted' and old.get('scope',{}).get('operation',{}).get('url')==PUBLISH and old.get('resultReceiptSha256')==digest(old.get('result')) and old.get('scope',{}).get('nativeListingInput',{}).get('kind')!='schema-edit':
     publication_receipt(old['result']);continue
    raise SafetyError('shop-has-unresolved-write-check-before-new-write')
 def approve(self,task_id,fingerprint,*,confirmed=False,ttl_seconds=900):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    if not confirmed or fingerprint!=task['fingerprint'] or task['status']!='prepared':raise SafetyError('exact-user-approval-required')
    if not 1<=ttl_seconds<=3600:raise SafetyError('invalid-approval-lifetime')
    from .sku_material_authorization import parent_deadline
    parent=parent_deadline(self,task)
    task['approval']={'fingerprint':fingerprint,'expiresAt':min(time.time()+ttl_seconds,parent) if parent is not None else time.time()+ttl_seconds,'confirmed':True}
    atomic_json(self._path(task_id),task);return task
 def execute(self,task_id):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    try:live_version=(Path(__file__).resolve().parents[1]/'VERSION').read_text(encoding='utf-8-sig').strip()
    except OSError:raise SafetyError('live-runtime-version-unavailable') from None
    if task['scope']['runtimeVersion']!=VERSION or live_version!=VERSION:raise SafetyError('runtime-changed-prepare-new-scope-and-approval')
    if task['status']!='prepared':raise SafetyError('task-already-started-query-outcome-do-not-replay')
    if task['requiresWriteApproval']:
     approval=task.get('approval',{})
     if not approval.get('confirmed') or approval.get('fingerprint')!=task['fingerprint'] or approval.get('expiresAt',0)<=time.time():raise SafetyError('current-exact-write-approval-required')
    from .sku_material_authorization import parent_deadline
    parent=parent_deadline(self,task)
    if parent is not None:task['approval']['expiresAt']=min(task['approval']['expiresAt'],parent)
    expected=task['scope']['shop'];actual=self.client.identity(expected['profile'])
    if any(str(actual.get(k))!=str(expected[k]) for k in ('shopName','venderId','shopId')) or actual.get('shopType')!='POP':raise SafetyError('shop-changed-stop-before-write')
    publication_stage=check_publication_scope(self,task['scope'],self.client)
    if task['requiresWriteApproval']:self._assert_resolved(expected,exclude=task_id,resolved_uploads=([b['taskId'] for b in task['scope'].get('nativeListingInput',{}).get('assetBindings',[])] if publication_stage else [])+list(task['scope'].get('skuMaterialInput',{}).get('sources',{})))
    from .sku_material_contract import contract as material_contract
    material_expected=material_contract(self,task['scope'],live=True,dispatch=True)
    contract=price_contract(task['scope']);upload=describe_upload(task['scope'])
    if upload:
     descriptor,raw=upload;image=probe_image(self.state,raw);check_image_evidence(descriptor,image)
     if task['scope'].get('materialUpload')!={'image':image}:raise SafetyError('native-image-approved-evidence-changed')
     proof=verify_upload_context(self.client,expected,descriptor);task['materialPreconditionEvidence']={'zonesSha256':digest(proof['zones']),'categoriesSha256':digest(proof['categories']),'checkedAt':time.time()}
    precondition=task['scope'].get('precondition')
    if precondition:
     query=precondition['query'];current=self.client.invoke(expected['profile'],query['url'],method='GET',params=query['params'],skill_id=query['skillId'])
     if contract:validate_native_price_response(contract,current,stage='before')
     if _match_count(current,precondition['expected'])!=1:raise SafetyError('precondition-current-value-changed-prepare-new-approval')
     task['preconditionEvidence']={'checkedAt':time.time(),'matched':True,'result':redact(current)}
    if task['requiresWriteApproval'] and task['approval']['expiresAt']<=time.time():raise SafetyError('approval-expired-during-preflight')
    op=task['scope']['operation'];execution=task['scope'].get('officialExecution');transport_options={}
    if execution is None and callable(getattr(self.client,'plan_execution',None)):raise SafetyError('legacy-task-missing-official-execution-contract-prepare-new-approval')
    if execution is not None:
     if not callable(getattr(self.client,'plan_execution',None)) or self.client.plan_execution(op,profile=expected['profile'])!=execution:raise SafetyError('official-execution-contract-changed-prepare-new-approval')
     transport_options={'expected_execution':execution,'expected_shop':expected,'authorization_expires_at':task.get('approval',{}).get('expiresAt') if task['requiresWriteApproval'] else None}
    if execution is not None and task['requiresWriteApproval'] and not _same_identity(self.client.identity(expected['profile']),expected):raise SafetyError('shop-changed-during-transport-preflight')
    if task['requiresWriteApproval'] and task['approval']['expiresAt']<=time.time():raise SafetyError('approval-expired-during-transport-preflight')
    if publication_stage=='publication':
     validation=checked_validation(self,task['scope']['publicationValidationTaskId'],op['body'],expected)
     deadline=min(task['approval']['expiresAt'],validation['finishedAt']+VALIDATION_TTL)
     if deadline<=time.time():raise SafetyError('validation-or-approval-expired-before-dispatch')
     transport_options['authorization_expires_at']=deadline
    from .video_binding_state import start_attempt
    start_attempt(self,task)
    from .shop_material_execution_state import start_attempt as start_shop_attempt
    start_shop_attempt(self,task)
    task.update(status='submitting',startedAt=time.time());atomic_json(self._path(task_id),task)
    try:
     if task['requiresWriteApproval'] and task['approval']['expiresAt']<=time.time():raise SafetyError('approval-expired-after-attempt-persistence-before-dispatch')
     result=self.client.invoke(expected['profile'],op['url'],method=op['method'],params=op['params'],body=op.get('body'),skill_id=op['skillId'],write_authorized=task['requiresWriteApproval'],**transport_options)
     if publication_stage=='validation':
      verdict=validation_verdict(result,expected_execution=execution)
     else:
      payload=business_payload(result)
      if material_expected is not None and (not isinstance(result,dict) or result.get('success') is not True):raise SafetyError('native-material-positive-business-acknowledgement-required')
      if task['requiresWriteApproval'] and (not isinstance(payload,(dict,list)) or not payload):raise SafetyError('business-acknowledgement-missing')
      if publication_stage=='publication':
       received=publication_receipt(result)
       if task['scope'].get('nativeListingInput',{}).get('kind')=='schema-edit' and ('applyId' not in received or received.get('productId')!=str(op['body']['productApplyDTO']['productId'])):raise SafetyError('original-full-edit-receipt-product-mismatch')
     if 'resultVerification' in task['scope']:resolve_result_verification(task['scope']['resultVerification'],result)
     if upload:
      validate_image_receipt(descriptor,image,result)
      from .material_contract import preserve_upload_receipt
      preserve_upload_receipt(self,task,redact(result))
     from .video_binding_state import preserve_receipt
     preserve_receipt(self,task,redact(result))
     from .shop_material_execution_state import preserve_receipt as preserve_shop_receipt
     preserve_shop_receipt(self,task,redact(result))
    except Exception as error:
     task.update(status='unknown',error={'kind':type(error).__name__,'message':'提交结果待核对；不会自动重提，也不会因换工具重新提交'})
    else:
     task.update(status='completed' if publication_stage=='validation' else ('submitted' if task['requiresWriteApproval'] else 'completed'),result=redact(result),resultReceiptSha256=digest(redact(result)),finishedAt=time.time())
     if publication_stage=='validation':task['validationVerdict']=verdict
    atomic_json(self._path(task_id),task);return task
 def readback(self,task_id,query,expected):
  query=_operation(query)
  if query['method']!='GET' or not isinstance(expected,dict) or not expected:raise SafetyError('readback-query-and-expected-fields-required')
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    if 'skuMaterialInput' in task['scope'] or 'videoMaterialInput' in task['scope']:raise SafetyError('dedicated-native-material-readback-required')
    if task['scope'].get('nativeListingInput',{}).get('kind')=='schema-edit':raise SafetyError('dedicated-full-edit-readback-required')
    if task['status'] not in ('submitted','unknown','verified'):raise SafetyError('readback-only-for-unresolved-write')
    verification=task['scope'].get('verification')
    if not verification or digest(verification)!=digest({'query':query,'expected':expected}):raise SafetyError('readback-must-match-original-approved-verification-scope')
    shop=task['scope']['shop'];actual=self.client.identity(shop['profile'])
    if not _same_identity(actual,shop):raise SafetyError('readback-shop-mismatch')
    result=self.client.invoke(shop['profile'],query['url'],params=query['params'],skill_id=query['skillId'])
    contract=price_contract(task['scope'])
    if contract:validate_native_price_response(contract,result,stage='pending')
    match_count=_match_count(result,expected)
    task['readback']={'query':query,'expected':expected,'matchCount':match_count,'at':time.time(),'result':redact(result)}
    # Exact API evidence of the desired state, not an assertion about authorship of an unknown submission.
    task['targetStateVerified']=match_count==1
    if match_count==1:
     if task['status']!='unknown' and ('resultVerification' not in task['scope'] or task.get('resultStateVerified')):task['status']='verified'
     task['verificationMeaning']='目标状态由本店官方读取证明；unknown原提交仍未证明终态，继续阻断重提/新写入'
    atomic_json(self._path(task_id),task);return task

 def verify_online(self,task_id):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    if 'skuMaterialInput' in task['scope'] or 'videoMaterialInput' in task['scope']:raise SafetyError('dedicated-native-material-readback-required')
    if task['scope'].get('nativeListingInput',{}).get('kind')=='schema-edit':raise SafetyError('dedicated-full-edit-readback-required')
    if task['status'] not in ('submitted','unknown','verified'):raise SafetyError('online-readback-only-after-submission')
    verification=task['scope'].get('onlineVerification')
    if not verification:raise SafetyError('online-verification-must-be-bound-before-approval')
    shop=task['scope']['shop'];actual=self.client.identity(shop['profile'])
    if not _same_identity(actual,shop):raise SafetyError('readback-shop-mismatch')
    query=verification['query'];result=self.client.invoke(shop['profile'],query['url'],method='GET',params=query['params'],skill_id=query['skillId'])
    contract=price_contract(task['scope'])
    if contract:validate_native_price_response(contract,result,stage='online')
    count=_match_count(result,verification['expected'])
    task['onlineReadback']={'query':query,'expected':verification['expected'],'matchCount':count,'at':time.time(),'result':redact(result)}
    task['onlineStateVerified']=count==1
    # A current online value cannot certify authorship or clear an unknown request.
    atomic_json(self._path(task_id),task);return task

 def verify_result(self,task_id):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    if 'skuMaterialInput' in task['scope'] or 'videoMaterialInput' in task['scope']:raise SafetyError('dedicated-native-material-readback-required')
    if task['scope'].get('nativeListingInput',{}).get('kind')=='schema-edit':raise SafetyError('dedicated-full-edit-readback-required')
    verification=task['scope'].get('resultVerification')
    if task['status'] not in ('submitted','verified') or not verification:raise SafetyError('known-original-result-required-never-resolve-unknown-by-target-match')
    result=task.get('result')
    if result is None or digest(result)!=task.get('resultReceiptSha256'):raise SafetyError('original-result-receipt-missing-or-modified')
    resolved=resolve_result_verification(verification,result);shop=task['scope']['shop']
    if not _same_identity(self.client.identity(shop['profile']),shop):raise SafetyError('readback-shop-mismatch')
    query=resolved['query'];response=self.client.invoke(shop['profile'],query['url'],method='GET',params=query['params'],skill_id=query['skillId'])
    upload=describe_upload(task['scope'])
    if upload:
     descriptor,raw=upload;image=task['scope'].get('materialUpload',{}).get('image');check_image_evidence(descriptor,image);validate_image_receipt(descriptor,image,response,original=result)
    count=_match_count(response,resolved['expected'])
    task['resultReadback']={'query':query,'expected':resolved['expected'],'matchCount':count,'at':time.time(),'result':redact(response),'sourceResultSha256':task['resultReceiptSha256']}
    task['resultStateVerified']=count==1
    if count==1 and ('verification' not in task['scope'] or task.get('targetStateVerified')):task['status']='verified'
    atomic_json(self._path(task_id),task);return task

 def verify_materials(self,task_id):
  from .sku_material_contract import contract as material_contract, census, read_materials, SLOTS
  with FileLock(self.state/'install.lock'),FileLock(self.state/'tasks.lock'):
   task=self.task(task_id)
   if task['status'] not in ('submitted','unknown','verified') or 'skuMaterialInput' not in task['scope']:raise SafetyError('submitted-native-material-task-required')
   expected=material_contract(self,task['scope']);proof=task['scope']['skuMaterialInput'];shop=task['scope']['shop']
   if task['status']!='unknown' and task.get('resultReceiptSha256')!=digest(task.get('result')):raise SafetyError('native-material-original-acknowledgement-modified')
   siblings,_=census(self,shop['profile'],proof['productId'])
   if siblings!=proof['siblingSkuIds']:raise SafetyError('native-material-readback-sibling-census-changed')
   current=read_materials(self.client,shop,proof['skuIds']);matched=digest(current['contents'])==digest(expected)
   audit=[]
   for row in proof['changes']:
    kind,order=SLOTS[row['slot']];audit.append(current['audit'][row['skuId']].get(f'{kind}:{order}',{}).get('status'))
   task['materialReadback']={'at':time.time(),'matched':matched,'sourceHashes':current['sourceHashes'],'audit':current['audit']}
   task['targetStateVerified']=matched;task['materialFieldsVerified']=matched and task['status']!='unknown';task['materialAuditApproved']=matched and bool(audit) and all(v==4 for v in audit) and task['status']!='unknown'
   if matched and task['status']!='unknown':task['status']='verified'
   elif task['status']=='verified':task['status']='submitted'
   task['verificationMeaning']='Queried SKU material content and preserved orders only; acknowledgement is not audit approval, score recalculation or authorship of an unknown request.'
   atomic_json(self._path(task_id),task);return task
