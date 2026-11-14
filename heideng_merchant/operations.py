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
 if not re.fullmatch('[a-z0-9-]+',str(result['skillId'])):raise SafetyError('invalid-skill-id')
 digest(result)
 return result

def _verification(value):
 if not isinstance(value,dict) or set(value)!={'query','expected'}:raise SafetyError('complete-readback-scope-required')
 query=_operation(value['query']);validate_expected(value['expected'])
 if query['method']!='GET' or redact(value)!=value:raise SafetyError('readonly-nonsecret-readback-required')
 if len(json.dumps(value,ensure_ascii=False,allow_nan=False))>65536:raise SafetyError('verification-scope-too-large')
 return {'query':query,'expected':value['expected']}

def _same_identity(actual,expected):
 return actual.get('shopType')=='POP' and all(str(actual.get(k))==str(expected[k]) for k in ('venderId','shopId','shopName'))

def _match_count(result,expected):
 data=business_payload(result);rows=data if isinstance(data,list) else [data]
 return sum(isinstance(row,dict) and matches_fields(row,expected) for row in rows)

class Operations:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client
 def connect(self,profile,shop_name,vender_id):
  validate_profile(profile)
  if not str(vender_id).isdigit() or not shop_name:raise SafetyError('explicit-shop-identity-required')
  actual=self.client.identity(profile)
  if actual.get('shopType')!='POP' or actual.get('shopName')!=shop_name or actual.get('venderId')!=str(vender_id):raise SafetyError('shop-identity-mismatch')
  actual={**actual,'profile':profile,'verifiedAt':time.time()}
  with FileLock(self.state/'shops.lock'):
   shops=read_json(self.state/'shops.json',{});previous=shops.get(profile)
   if previous and (previous['venderId']!=actual['venderId'] or previous['shopName']!=actual['shopName']):raise SafetyError('profile-already-bound-to-another-shop')
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
  return value
 def prepare(self,profile,operation,verification=None,*,precondition=None,online_verification=None):
  shop=self.shop(profile);operation=_operation(operation)
  scope={'shop':{k:shop[k] for k in ('profile','venderId','shopName','shopId')},'operation':operation,'runtimeVersion':VERSION}
  if callable(getattr(self.client,'plan_execution',None)):
   scope['officialExecution']=self.client.plan_execution(operation,profile=profile)
   if redact(scope['officialExecution'])!=scope['officialExecution']:raise SafetyError('credentials-not-allowed-in-execution-contract')
  for key,value in (('verification',verification),('precondition',precondition),('onlineVerification',online_verification)):
   if value is not None:scope[key]=_verification(value)
  contract=price_contract(scope)
  fingerprint=digest(scope);ident=fingerprint[:24];path=self._path(ident)
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    existing=read_json(path)
    if existing:return self.task(ident)
    if operation['method']!='GET':
     self._assert_resolved(shop)
    planning=None
    if contract:
     if not _same_identity(self.client.identity(profile),shop):raise SafetyError('native-price-planning-shop-mismatch')
     check=scope['precondition'];query=check['query'];response=self.client.invoke(profile,query['url'],method='GET',params=query['params'],skill_id=query['skillId'])
     validate_native_price_response(contract,response,stage='before')
     if _match_count(response,check['expected'])!=1:raise SafetyError('native-price-planning-values-not-current')
     planning={'query':query,'responseSha256':digest(response),'checkedAt':time.time()}
    task={'taskId':ident,'fingerprint':fingerprint,'scope':scope,'status':'prepared','createdAt':time.time(),'requiresWriteApproval':operation['method']!='GET'}
    if planning is not None:task['planningEvidence']=planning
    atomic_json(path,task);return task
 def _assert_resolved(self,shop,exclude=None):
  for entry in (self.state/'tasks').glob('*.json'):
   old=read_json(safe_join(self.state,'tasks/'+entry.name),{});subject=old.get('scope',{}).get('shop',{})
   same=subject.get('profile')==shop['profile'] or all(str(subject.get(k,''))==str(shop[k]) for k in ('venderId','shopId'))
   if old.get('taskId')!=exclude and old.get('status') in ('unknown','submitting','submitted') and same:raise SafetyError('shop-has-unresolved-write-check-before-new-write')
 def approve(self,task_id,fingerprint,*,confirmed=False,ttl_seconds=900):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
    if not confirmed or fingerprint!=task['fingerprint'] or task['status']!='prepared':raise SafetyError('exact-user-approval-required')
    if not 1<=ttl_seconds<=3600:raise SafetyError('invalid-approval-lifetime')
    task['approval']={'fingerprint':fingerprint,'expiresAt':time.time()+ttl_seconds,'confirmed':True}
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
    expected=task['scope']['shop'];actual=self.client.identity(expected['profile'])
    if any(str(actual.get(k))!=str(expected[k]) for k in ('shopName','venderId','shopId')) or actual.get('shopType')!='POP':raise SafetyError('shop-changed-stop-before-write')
    if task['requiresWriteApproval']:self._assert_resolved(expected,exclude=task_id)
    contract=price_contract(task['scope'])
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
    task.update(status='submitting',startedAt=time.time());atomic_json(self._path(task_id),task)
    try:
     result=self.client.invoke(expected['profile'],op['url'],method=op['method'],params=op['params'],body=op.get('body'),skill_id=op['skillId'],write_authorized=task['requiresWriteApproval'],**transport_options)
     payload=business_payload(result)
     if task['requiresWriteApproval'] and (not isinstance(payload,(dict,list)) or not payload):raise SafetyError('business-acknowledgement-missing')
    except Exception as error:
     task.update(status='unknown',error={'kind':type(error).__name__,'message':'提交结果待核对；不会自动重提，也不会因换工具重新提交'})
    else:task.update(status='submitted' if task['requiresWriteApproval'] else 'completed',result=redact(result),finishedAt=time.time())
    atomic_json(self._path(task_id),task);return task
 def readback(self,task_id,query,expected):
  query=_operation(query)
  if query['method']!='GET' or not isinstance(expected,dict) or not expected:raise SafetyError('readback-query-and-expected-fields-required')
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
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
     if task['status']!='unknown':task['status']='verified'
     task['verificationMeaning']='目标状态由本店官方读取证明；unknown原提交仍未证明终态，继续阻断重提/新写入'
    atomic_json(self._path(task_id),task);return task

 def verify_online(self,task_id):
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    task=self.task(task_id)
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
