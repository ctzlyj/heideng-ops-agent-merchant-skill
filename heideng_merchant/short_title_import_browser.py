"""Native UI import transport; manager-owned attempts and original upload binding only."""
import re,math,urllib.parse
from pathlib import Path
from . import VERSION
from .safety import SafetyError,safe_join,file_sha
from .video_delivery import _once
from .operations import digest
from .short_title_browser import ShortTitleSourceBrowser,WARE_LIST_URL,_source_record
from .short_title_browser_contract import source_url,response_bytes,sha_bytes
from .short_title_import_contract import project,observed_tasks
from .short_title_import_state import evidence,event_path

class ShortTitleImportBrowser(ShortTitleSourceBrowser):
 def __init__(self,manager,import_id,*,factory=None,headless=False,channel=None,result_transport=None):
  root=manager.record(import_id);self.manager=manager;self.import_id=import_id;self.root_fingerprint=root['fingerprint'];self.root_scope=root['scope'];self.memo=None;self.stop_requested=lambda:False;self.current_proof=None;self.preflight_at=0;self.pending_attempt=None
  from .short_title_result_transport import ResultTransport
  self.result_transport=result_transport or ResultTransport(clock=lambda:manager.clock());self._last_result_sources=[]
  super().__init__(manager.state,manager.client,root['scope']['planId'],session_id=root['scope']['sourceId'],factory=factory,clock=lambda:manager.clock(),headless=headless,channel=channel)
 def open(self,*,install_guard=None):
  super().open(install_guard=install_guard);self.manager.live_browser=self
 def close(self):
  super().close()
  if self.manager.live_browser is self:self.manager.live_browser=None
 def _open_allowed(self):
  p=self.manager.record(self.import_id);evidence(self.state,p);_source_record(self.state,self.manager.client,self.session_id)
  if p['fingerprint']!=self.root_fingerprint or p['scope']['runtimeVersion']!=VERSION or (Path(__file__).resolve().parents[1]/'VERSION').read_text().strip()!=VERSION:raise SafetyError('current-original-native-import-runtime-required')
 def capture(self):raise SafetyError('native-import-browser-cannot-replace-source-capture')
 def status(self):return self.manager.status(self.import_id)
 def _timeout(self,deadline):
  remaining=deadline-self.clock()
  if not math.isfinite(remaining) or remaining<=0:raise SafetyError('native-import-attempt-deadline-expired')
  return max(1,min(25000,int(remaining*1000)))
 def _drawer(self):
  drawer=self.page.locator('[class*=drawer]').filter(has_text='创建导入任务').filter(visible=True)
  if drawer.count()!=1:raise SafetyError('unique-original-native-import-drawer-required')
  drawer.wait_for(state='visible',timeout=15000);return drawer
 def _observe(self):
  self._last_result_sources=[]
  self._open_allowed();self.manager._current(self.manager.record(self.import_id),readonly=True);self.epoch+=1;self.proof=None;self.foreign=False;self.requests={};self.capture_started=self.clock()*1000;self.phase='navigation';self.stage='capturing';self.memo=None
  self.page.goto(WARE_LIST_URL,wait_until='domcontentloaded',timeout=30000)
  for _ in range(100):
   if self.proof is not None or self.foreign:break
   self.poll()
  self._identity();self.page.locator('.batch-dropdown-link').hover();self.phase='drawer'
  with self.page.expect_response(lambda r:self._fresh(r,'drawer') and source_url(r.url,service='batchJobService.queryByPage'),timeout=20000) as loaded:self.page.get_by_text('批量设置短标题',exact=True).filter(visible=True).click()
  raw,data=response_bytes(loaded.value,self.page,service='batchJobService.queryByPage');rows=observed_tasks(data);from .short_title_result_browser import result_sources;self._last_result_sources=result_sources(data);self._identity();drawer=self._drawer();link=drawer.get_by_role('link').filter(has_text=re.compile(r'下载.*模板|模板.*下载')).filter(visible=True)
  if link.count()!=1:raise SafetyError('unique-current-native-import-template-required')
  href=link.get_attribute('href');href=urllib.parse.urljoin(WARE_LIST_URL,href) if isinstance(href,str) else None
  if not source_url(href,template=True):raise SafetyError('public-current-native-template-link-required')
  with self.page.expect_download(timeout=30000) as downloaded:link.click()
  download=downloaded.value
  if download.url!=href or download.failure() is not None:raise SafetyError('exact-current-native-template-download-required')
  template=_source_record(self.state,self.manager.client,self.session_id)['scope']['template'];file=Path(download.path())
  if not file.is_file() or file.stat().st_size!=template['byteCount'] or file_sha(file)!=template['sha256']:raise SafetyError('approved-native-template-content-changed')
  self._identity();self.preflight_at=self.clock();self.current_proof={'identitySha256':self._identity()['responseSha256'],'taskPageSha256':sha_bytes(raw),'captureEpoch':self.epoch,'beforeInstanceIds':[r['instanceId'] for r in rows if r['instanceId'] is not None],'templateSha256':template['sha256']}
  return {'rows':rows,'taskPageSha256':sha_bytes(raw),'identitySha256':self._identity()['responseSha256']}
 def preflight(self):self._observe();return dict(self.current_proof)
 def observe(self):return self._observe()
 def _dispatch(self,artifact,phase,attempt):
  p=self.manager.record(self.import_id);ev=evidence(self.state,p);key=(artifact['batch'],phase)
  if self.pending_attempt!=attempt['context']['attemptId'] or key not in ev[1] or ev[1][key]!=attempt or key in ev[2] or artifact!=p['scope']['artifacts'][artifact['batch']-1] or attempt['context']['fingerprint']!=p['fingerprint'] or self.manager._approval(p)['approvalId']!=attempt['approvalId']:raise SafetyError('new-manager-owned-native-import-attempt-required')
  self.pending_attempt=None;self._timeout(attempt['deadline']);self._identity();self.manager._current(p)
  if self.stop_requested():raise SafetyError('worker-stop-requested-no-next-native-action')
  _once(event_path(self.state,'short-title-import-dispatches',self.import_id,artifact['batch'],phase),{'context':attempt['context'],'attemptSha256':digest(attempt)});self.manager._worker_checkpoint()
  if self.stop_requested():raise SafetyError('worker-stop-requested-no-next-native-action')
 def grant(self,attempt):
  p=self.manager.record(self.import_id);ev=evidence(self.state,p);key=(attempt['context']['batch'],attempt['context']['phase'])
  if key not in ev[1] or ev[1][key]!=attempt or key in ev[2] or key in ev[4]:raise SafetyError('unused-original-native-import-attempt-required')
  self.pending_attempt=attempt['context']['attemptId']
 def upload(self,artifact,attempt):
  drawer=self._drawer();input=drawer.locator('input[type=file]')
  if input.count()!=1:raise SafetyError('unique-native-title-import-file-input-required')
  self.phase='upload';self._dispatch(artifact,'upload',attempt)
  with self.page.expect_response(lambda r:self._fresh(r,'upload') and source_url(r.url,service='file.upload'),timeout=self._timeout(attempt['deadline'])) as loaded:input.set_input_files(str(safe_join(self.state,artifact['localPath'])),timeout=self._timeout(attempt['deadline']))
  raw,data=response_bytes(loaded.value,self.page,service='file.upload');result=project(raw,data,'upload');self._identity()
  if result['outcome']=='accepted':
   drawer.get_by_text(artifact['filename'],exact=True).wait_for(state='visible',timeout=self._timeout(attempt['deadline']));self.memo=(artifact['sha256'],artifact['filename'],result['uploadedObjectSha256'])
  return result
 def can_create(self,artifact,object_hash):
  if self.memo!=(artifact['sha256'],artifact['filename'],object_hash) or not 0<=self.clock()-self.preflight_at<=30:return False
  try:self._identity();self._drawer().get_by_text(artifact['filename'],exact=True).wait_for(state='visible',timeout=1000);return True
  except Exception:return False
 def create(self,artifact,attempt):
  if not self.can_create(artifact,self.memo[2] if self.memo else None):raise SafetyError('original-live-native-upload-binding-required')
  button=self._drawer().get_by_role('button',name='确定导入',exact=True)
  if button.count()!=1:raise SafetyError('unique-native-title-import-create-button-required')
  self.phase='create';self._dispatch(artifact,'create',attempt)
  with self.page.expect_response(lambda r:self._fresh(r,'create') and source_url(r.url,service='batchJobService.createImportJob'),timeout=self._timeout(attempt['deadline'])) as loaded:button.click(timeout=self._timeout(attempt['deadline']))
  raw,data=response_bytes(loaded.value,self.page,service='batchJobService.createImportJob');result=project(raw,data,'create');self._identity();return result
