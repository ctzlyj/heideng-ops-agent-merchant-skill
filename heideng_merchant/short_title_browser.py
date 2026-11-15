"""Task-owned short-title source browser. Read-only; no upload or import execution."""
from __future__ import annotations
import os,re,time,uuid,urllib.parse,math
from pathlib import Path
from . import VERSION
from .safety import SafetyError,safe_join,read_json,atomic_json,clean_environment,file_sha,is_linked,redact
from .state import FileLock
from .operations import digest
from .video_delivery import _once
from .short_titles import ShortTitlePlans
from .shop_material_execution_contract import current_catalog
from .short_title_browser_contract import source_url,response_bytes,identity_observation,task_page,shop_checked,sha_bytes

WARE_LIST_URL='https://wares-jdm.jd.com/ware/wareList?activeTab=OnsaleWare&businessModel=0'

def _id(value):
 if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{24}',value):raise SafetyError('short-title-browser-source-id-required')
 return value

def _owner(state,session_id,plan):
 relative='browser/short-title/'+_id(session_id)
 return {'sessionId':session_id,'planId':plan['planId'],'planFingerprint':plan['fingerprint'],'shop':shop_checked(plan['scope']['shop']),'profilePath':relative+'/context-data'}

def _source_record(state,client,source_id):
 state=Path(state).absolute();_id(source_id);p=read_json(safe_join(state,'short-title-browser-sources/'+source_id+'.json'))
 if not isinstance(p,dict) or set(p)!={'sourceId','fingerprint','scope'} or p['sourceId']!=source_id or p['fingerprint']!=digest(p['scope']):raise SafetyError('original-short-title-browser-source-changed')
 scope=p['scope'];observation=read_json(safe_join(state,'short-title-browser-observations/'+source_id+'.json'))
 if observation!={'sourceId':source_id,'fingerprint':p['fingerprint'],'scope':scope}:raise SafetyError('independent-original-browser-observation-required')
 expected={'kind','runtimeVersion','sessionId','planId','planFingerprint','shop','capturedAt','identity','taskPage','template'}
 if not isinstance(scope,dict) or set(scope)!=expected or scope['kind']!='native-short-title-browser-source' or scope['sessionId']!=source_id:raise SafetyError('complete-original-browser-source-required')
 if type(scope['capturedAt']) not in (int,float) or not math.isfinite(scope['capturedAt']) or scope['capturedAt']<=0:raise SafetyError('original-browser-capture-time-required')
 plan=ShortTitlePlans(state,client).plan(scope['planId']);owner=_owner(state,source_id,plan)
 if scope['planFingerprint']!=plan['fingerprint'] or scope['shop']!=owner['shop'] or read_json(safe_join(state,'browser/short-title/'+source_id+'/owner.json'))!=owner:raise SafetyError('original-short-title-browser-owner-changed')
 if not safe_join(state,owner['profilePath']).is_dir():raise SafetyError('original-owned-browser-profile-required')
 identity=scope['identity'];page=scope['taskPage'];template=scope['template']
 if not isinstance(identity,dict) or set(identity)!={'responseSha256','sourceSha256','shop','sameObject','captureEpoch'} or identity['shop']!=scope['shop'] or identity['sameObject'] is not True or type(identity['captureEpoch']) is not int or identity['captureEpoch']<1:raise SafetyError('original-same-object-browser-identity-required')
 if not isinstance(page,dict) or set(page)!={'responseSha256','sourceSha256','rows','complete'} or page['complete'] is not False or not isinstance(page['rows'],list) or len(page['rows'])>500:raise SafetyError('original-observed-browser-task-page-required')
 ids=[]
 for row in page['rows']:
  if not isinstance(row,dict) or set(row)!={'instanceId','uploadedObjectSha256'}:raise SafetyError('original-observed-task-row-required')
  if row['instanceId'] is not None:
   if not isinstance(row['instanceId'],str) or not re.fullmatch('[1-9][0-9]{5,18}',row['instanceId']):raise SafetyError('original-task-instance-required')
   ids.append(row['instanceId'])
  if row['uploadedObjectSha256'] is not None and not re.fullmatch('[a-f0-9]{64}',str(row['uploadedObjectSha256'])):raise SafetyError('original-task-object-hash-required')
 if len(ids)!=len(set(ids)):raise SafetyError('unique-original-task-instance-required')
 if not isinstance(template,dict) or set(template)!={'sha256','sourceSha256','localPath','byteCount','parsedForPlan'} or template['localPath']!='short-title-browser-templates/'+source_id+'.xlsx' or template['parsedForPlan'] is not True or type(template['byteCount']) is not int or not 0<template['byteCount']<=5*1024*1024:raise SafetyError('original-browser-template-required')
 for value in (identity['responseSha256'],identity['sourceSha256'],page['responseSha256'],page['sourceSha256'],template['sha256'],template['sourceSha256']):
  if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise SafetyError('original-browser-source-hash-required')
 path=safe_join(state,template['localPath'])
 if not path.is_file() or path.stat().st_size!=template['byteCount'] or file_sha(path)!=template['sha256'] or redact(p)!=p:raise SafetyError('original-browser-template-or-source-changed')
 return p

def read_source(state,client,source_id):
 p=_source_record(state,client,source_id);scope=p['scope']
 return {'sourceId':source_id,'fingerprint':p['fingerprint'],'planId':scope['planId'],'runtimeVersion':scope['runtimeVersion'],'status':'source-captured','capturedAt':scope['capturedAt'],'browserIdentityVerified':True,'templateOriginCaptured':True,'templateSha256':scope['template']['sha256'],'observedTaskRowCount':len(scope['taskPage']['rows']),'observedInstanceIds':[r['instanceId'] for r in scope['taskPage']['rows'] if r['instanceId'] is not None],'taskListComplete':False,'historicalCapture':True,'currentIdentityVerified':False,'platformCurrentRulesVerified':False,'writeExecutionAvailable':False,'imported':False,'approvalReady':False}

class ShortTitleSourceBrowser:
 def __init__(self,state,client,plan_id,*,session_id=None,factory=None,clock=None,channel=None,headless=False):
  self.state=Path(state).absolute();safe_join(self.state,'browser');self.plans=ShortTitlePlans(self.state,client);self.plan=self.plans.plan(plan_id);self.session_id=_id(session_id or uuid.uuid4().hex[:24]);self.binding=_owner(self.state,self.session_id,self.plan)
  if not self.plan['scope']['changes']:raise SafetyError('reviewed-short-title-rows-required-before-browser-source')
  if channel not in (None,'chrome','msedge'):raise SafetyError('system-browser-channel-required')
  self.factory=factory;self.clock=clock or time.time;self.channel=channel or ('msedge' if os.name=='nt' else 'chrome');self.headless=headless;self.controller=self.context=self.page=self.lock=self.install_lock=None;self.owns_lifecycle=False;self.requests={};self.phase=None;self.capture_started=0;self.launch_unknown=False;self.epoch=0;self.proof=None;self.foreign=False;self.stage='not-opened';self.root=safe_join(self.state,'browser/short-title/'+self.session_id);self.owner_path=safe_join(self.state,'browser/short-title/'+self.session_id+'/owner.json');self.lifecycle_path=safe_join(self.state,'browser/short-title/'+self.session_id+'/lifecycle.json')
 def _lifecycle(self,status):atomic_json(self.lifecycle_path,{'sessionId':self.session_id,'status':status})
 def _validate_owner(self):
  if read_json(self.owner_path)!=self.binding:raise SafetyError('task-owned-short-title-browser-owner-changed')
 def open(self):
  if self.controller is not None:raise SafetyError('task-owned-short-title-browser-already-open')
  if self.root.exists() and not self.owner_path.exists():raise SafetyError('unowned-browser-profile-not-adopted')
  if self.owner_path.exists():
   self._validate_owner()
   if read_json(self.lifecycle_path,{}).get('status')!='closed':raise SafetyError('owned-browser-not-confirmed-closed-no-reopen')
  if safe_join(self.state,'short-title-browser-sources/'+self.session_id+'.json').exists():raise SafetyError('browser-source-capture-already-completed')
  try:
   interlock=FileLock(safe_join(self.state,'install.lock'),timeout=0);interlock.__enter__();self.install_lock=interlock
   lock=FileLock(safe_join(self.state,'browser/short-title/'+self.session_id+'/owner.lock'));lock.__enter__();self.lock=lock
   if self.owner_path.exists():
    self._validate_owner()
    if read_json(self.lifecycle_path,{}).get('status')!='closed':raise SafetyError('owned-browser-not-confirmed-closed-no-reopen')
   else:
    if safe_join(self.state,self.binding['profilePath']).exists():raise SafetyError('unowned-browser-profile-not-adopted')
    _once(self.owner_path,self.binding)
   self.owns_lifecycle=True;profile=safe_join(self.state,self.binding['profilePath']);profile.mkdir(parents=True,exist_ok=True);self._lifecycle('opening')
   if self.factory is None:
    from playwright.sync_api import sync_playwright
    factory=sync_playwright
   else:factory=self.factory
   self.controller=factory().start();self.launch_unknown=True;self.context=self.controller.chromium.launch_persistent_context(str(profile),channel=self.channel,headless=self.headless,accept_downloads=True,service_workers='block',env=clean_environment(self.root));self.launch_unknown=False;self.page=self.context.new_page();self.page.on('request',self._request);self.page.on('response',self._response);self.stage='login';self._lifecycle('open');self.page.goto('https://jingmai.jd.com/',wait_until='domcontentloaded',timeout=30000)
  except Exception:
   try:self.close()
   except SafetyError:raise SafetyError('owned-browser-cleanup-unknown-no-reopen') from None
   raise SafetyError('task-owned-browser-open-failed') from None
 def _request(self,request):
  if self.stage!='capturing':return
  try:
   if request.frame is not self.page.main_frame or request.frame.page is not self.page or request.resource_type not in ('xhr','fetch') or not source_url(request.url):return
   stamp=request.timing['startTime']
   if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<self.capture_started:return
   if len(self.requests)>=1000:self.foreign=True;return
   self.requests[id(request)]={'request':request,'epoch':self.epoch,'phase':self.phase}
  except Exception:return
 def _fresh(self,response,phase=None):
  try:
   request=response.request;record=self.requests.get(id(request))
   return bool(record and record['request'] is request and record['epoch']==self.epoch and (phase is None or record['phase']==phase) and request.frame is self.page.main_frame and request.frame.page is self.page and source_url(request.frame.url))
  except Exception:return False
 def _response(self,response):
  if self.stage!='capturing':return
  try:
   if not source_url(response.url) or not self._fresh(response):return
   raw,data=response_bytes(response,self.page);found,foreign=identity_observation(data,self.binding['shop']);self.foreign=self.foreign or foreign
   if found:self.proof={'responseSha256':sha_bytes(raw),'sourceSha256':sha_bytes(response.url.encode()),'shop':self.binding['shop'],'sameObject':True,'captureEpoch':self.epoch}
  except Exception:self.foreign=True
 def poll(self):
  if self.page is None or self.page.is_closed():raise SafetyError('task-owned-browser-closed')
  self.page.wait_for_timeout(50)
 def _identity(self):
  if self.proof is None or self.foreign or self.proof['captureEpoch']!=self.epoch:raise SafetyError('current-same-object-pop-shop-identity-required')
  return dict(self.proof)
 def capture(self):
  from .short_title_workbook import compile_template,_parts,MAX_BYTES
  if self.page is None or self.page.is_closed():raise SafetyError('task-owned-browser-closed')
  self._validate_owner()
  if safe_join(self.state,'short-title-browser-sources/'+self.session_id+'.json').exists():raise SafetyError('browser-source-capture-already-completed')
  self.plan=self.plans.plan(self.plan['planId']);self._catalog()
  self.epoch+=1;self.proof=None;self.foreign=False;self.requests={};self.capture_started=self.clock()*1000;self.phase='navigation';self.stage='capturing'
  try:
   self.page.goto(WARE_LIST_URL,wait_until='domcontentloaded',timeout=30000)
   for _ in range(100):
    if self.proof is not None or self.foreign:break
    self.poll()
   self._identity();self.page.locator('.batch-dropdown-link').hover()
   self.phase='drawer'
   with self.page.expect_response(lambda r:self._fresh(r,'drawer') and source_url(r.url,service='batchJobService.queryByPage'),timeout=20000) as loaded:self.page.get_by_text('批量设置短标题',exact=True).filter(visible=True).click()
   raw,data=response_bytes(loaded.value,self.page,service='batchJobService.queryByPage');rows=task_page(data);self._identity();drawer=self.page.locator('[class*=drawer]').filter(has_text='创建导入任务').filter(visible=True)
   if drawer.count()!=1:raise SafetyError('unique-short-title-import-drawer-required')
   drawer.wait_for(state='visible',timeout=15000);link=drawer.get_by_role('link').filter(has_text=re.compile(r'下载.*模板|模板.*下载')).filter(visible=True)
   if link.count()!=1:raise SafetyError('unique-current-drawer-template-link-required')
   href=link.get_attribute('href');href=urllib.parse.urljoin(WARE_LIST_URL,href) if isinstance(href,str) else None
   if not source_url(href,template=True):raise SafetyError('public-platform-template-link-required')
   self._identity()
   with self.page.expect_download(timeout=30000) as downloaded:link.click()
   download=downloaded.value
   if download.url!=href or not source_url(download.url,template=True) or download.failure() is not None:raise SafetyError('exact-current-template-download-required')
   self._identity();path=Path(download.path())
   if is_linked(path) or not path.is_file() or not 0<path.stat().st_size<=MAX_BYTES:raise SafetyError('bounded-current-template-download-required')
   template=path.read_bytes();_,parts=_parts(template)
   if any(redact(body.decode('utf-8-sig'))!=body.decode('utf-8-sig') for body in parts.values()):raise SafetyError('nonsecret-template-source-required')
   compile_template(template,[{k:r[k] for k in ('skuId','shortTitle')} for r in self.plan['scope']['chunks'][0]])
   self._catalog();self._identity();relative='short-title-browser-templates/'+self.session_id+'.xlsx';output=safe_join(self.state,relative);output.parent.mkdir(parents=True,exist_ok=True)
   with output.open('xb') as stream:stream.write(template);stream.flush();os.fsync(stream.fileno())
   if file_sha(output)!=sha_bytes(template):raise SafetyError('current-template-source-changed')
   scope={'kind':'native-short-title-browser-source','runtimeVersion':VERSION,'sessionId':self.session_id,'planId':self.plan['planId'],'planFingerprint':self.plan['fingerprint'],'shop':self.binding['shop'],'capturedAt':self.clock(),'identity':self._identity(),'taskPage':{'responseSha256':sha_bytes(raw),'sourceSha256':sha_bytes(loaded.value.url.encode()),'rows':rows,'complete':False},'template':{'sha256':sha_bytes(template),'sourceSha256':sha_bytes(href.encode()),'localPath':relative,'byteCount':len(template),'parsedForPlan':True}}
   record={'sourceId':self.session_id,'fingerprint':digest(scope),'scope':scope};_once(safe_join(self.state,'short-title-browser-observations/'+self.session_id+'.json'),record);_once(safe_join(self.state,'short-title-browser-sources/'+self.session_id+'.json'),record);return read_source(self.state,self.plans.client,self.session_id)
  except SafetyError:raise
  except Exception:raise SafetyError('short-title-browser-source-incomplete-no-import') from None
  finally:self.stage='login'
 def _catalog(self):
  from .short_title_contract import source_context
  record,_=source_context(self.state,self.plan['scope']['auditId'],self.plan['scope']['auditFingerprint']);current_catalog(self.plans.ops,record,all_siblings=True)
 def status(self):return read_source(self.state,self.plans.client,self.session_id)
 def close(self):
  try:
   if self.context is not None:self.context.close();self.context=None;self.page=None
   if self.controller is not None:self.controller.stop();self.controller=None
  except Exception:
   if self.owns_lifecycle:self._lifecycle('close-unknown')
   raise SafetyError('owned-browser-cleanup-unknown-no-reopen') from None
  if self.owns_lifecycle:
   self._validate_owner();self._lifecycle('close-unknown' if self.launch_unknown else 'closed');self.owns_lifecycle=False
  if self.lock is not None:self.lock.__exit__(None,None,None);self.lock=None
  if self.install_lock is not None:self.install_lock.__exit__(None,None,None);self.install_lock=None
  self.stage='closed'
  if self.launch_unknown:raise SafetyError('owned-browser-launch-cleanup-unconfirmed-no-reopen')
