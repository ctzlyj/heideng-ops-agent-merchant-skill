"""Exact-scope approvals and durable non-replaying merchant operations."""
from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
from . import VERSION
from .safety import SafetyError,atomic_json,read_json,redact,safe_join
from .state import FileLock
from .official import validate_profile,validate_route

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
 def prepare(self,profile,operation,verification=None):
  shop=self.shop(profile);operation=_operation(operation)
  scope={'shop':{k:shop[k] for k in ('profile','venderId','shopName','shopId')},'operation':operation,'runtimeVersion':VERSION}
  if verification is not None:
   if not isinstance(verification,dict) or set(verification)!={'query','expected'} or not isinstance(verification['expected'],dict) or not verification['expected']:raise SafetyError('complete-readback-scope-required')
   query=_operation(verification['query'])
   if query['method']!='GET' or redact(verification)!=verification:raise SafetyError('readonly-nonsecret-readback-required')
   scope['verification']={'query':query,'expected':verification['expected']}
  fingerprint=digest(scope);ident=fingerprint[:24];path=self._path(ident)
  with FileLock(self.state/'install.lock'):
   with FileLock(self.state/'tasks.lock'):
    existing=read_json(path)
    if existing:return self.task(ident)
    if operation['method']!='GET':
     for p in (self.state/'tasks').glob('*.json'):
      old=read_json(p,{})
      if old.get('status') in ('unknown','submitting','submitted') and old.get('scope',{}).get('shop',{}).get('profile')==profile:raise SafetyError('shop-has-unresolved-write-check-before-new-write')
    task={'taskId':ident,'fingerprint':fingerprint,'scope':scope,'status':'prepared','createdAt':time.time(),'requiresWriteApproval':operation['method']!='GET'}
    atomic_json(path,task);return task
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
    if task['scope']['runtimeVersion']!=VERSION:raise SafetyError('runtime-changed-prepare-new-scope-and-approval')
    if task['status']!='prepared':raise SafetyError('task-already-started-query-outcome-do-not-replay')
    if task['requiresWriteApproval']:
     approval=task.get('approval',{})
     if not approval.get('confirmed') or approval.get('fingerprint')!=task['fingerprint'] or approval.get('expiresAt',0)<time.time():raise SafetyError('current-exact-write-approval-required')
    expected=task['scope']['shop'];actual=self.client.identity(expected['profile'])
    if any(str(actual.get(k))!=str(expected[k]) for k in ('shopName','venderId','shopId')) or actual.get('shopType')!='POP':raise SafetyError('shop-changed-stop-before-write')
    op=task['scope']['operation'];task.update(status='submitting',startedAt=time.time());atomic_json(self._path(task_id),task)
    try:
     result=self.client.invoke(expected['profile'],op['url'],method=op['method'],params=op['params'],body=op.get('body'),skill_id=op['skillId'],write_authorized=task['requiresWriteApproval'])
     if isinstance(result,dict) and (result.get('success') is False or result.get('status') in ('error','FAILED')):raise SafetyError('business-outcome-not-confirmed')
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
    if task['status'] not in ('submitted','unknown'):raise SafetyError('readback-only-for-unresolved-write')
    verification=task['scope'].get('verification')
    if not verification or digest(verification)!=digest({'query':query,'expected':expected}):raise SafetyError('readback-must-match-original-approved-verification-scope')
    shop=task['scope']['shop'];actual=self.client.identity(shop['profile'])
    if any(str(actual.get(k))!=str(shop[k]) for k in ('venderId','shopId','shopName')):raise SafetyError('readback-shop-mismatch')
    result=self.client.invoke(shop['profile'],query['url'],params=query['params'],skill_id=query['skillId'])
    data=result.get('data',{}) if isinstance(result,dict) else {};rows=data if isinstance(data,list) else [data]
    matched=[row for row in rows if isinstance(row,dict) and all(str(row.get(k))==str(v) for k,v in expected.items())]
    task['readback']={'query':query,'expected':expected,'matchCount':len(matched),'at':time.time(),'result':redact(result)}
    # Exact API evidence of the desired state, not an assertion about authorship of an unknown submission.
    if len(matched)==1:
     task['targetStateVerified']=True
     if task['status']!='unknown':task['status']='verified'
     task['verificationMeaning']='目标状态由本店官方读取证明；unknown原提交仍未证明终态，继续阻断重提/新写入' 
    atomic_json(self._path(task_id),task);return task
