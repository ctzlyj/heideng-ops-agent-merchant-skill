import copy,importlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from tests import test_short_titles as plan_fixtures
from tests.short_title_fixtures import template

IDENTITY='https://jingmai.jd.com/api/identity?token=synthetic-only-private'
TASKS='https://api.m.jd.com/api?method=batchJobService.queryByPage&token=synthetic-only-private'
HREF='https://storage.jd.com/synthetic/template.xlsx?token=synthetic-only-private'

class Response:
 def __init__(self,page,url,payload):self.url=url;self.status=200;self.request=SimpleNamespace(resource_type='fetch',frame=getattr(page,'main_frame',SimpleNamespace(page=page)),url=url,timing={'startTime':1000000},started=False);self.payload=payload
 def body(self):return json.dumps(self.payload,ensure_ascii=False).encode()
 def header_value(self,name):return 'application/json' if name=='content-type' else str(len(self.body()))

class Pending:
 def __init__(self,page,kind,predicate=None):self.page=page;self.kind=kind;self.predicate=predicate;self.value=None
 def __enter__(self):self.page.pending=self;return self
 def __exit__(self,*args):
  self.page.pending=None
  if not args[0] and self.value is None:raise RuntimeError('synthetic pending response absent')

class Download:
 def __init__(self,page):self.page=page;self.url=page.href;self.suggested_filename='../synthetic-untrusted-name.xlsx'
 def failure(self):return None
 def path(self):
  p=self.page.temp/'synthetic-download';p.write_bytes(self.page.template);return str(p)

class Locator:
 def __init__(self,page,kind='page'):self.page=page;self.kind=kind
 def filter(self,**kw):return self
 def count(self):return self.page.link_count if self.kind=='link' else self.page.drawer_count if self.kind=='drawer' else 1
 def locator(self,selector):return Locator(self.page,'drawer' if 'drawer' in selector else 'element')
 def get_by_role(self,role,**kw):return Locator(self.page,'link' if role=='link' else 'button')
 def get_by_text(self,*args,**kw):return Locator(self.page,'open')
 def wait_for(self,**kw):pass
 def hover(self):pass
 def get_attribute(self,name):
  if self.page.on_template:self.page.on_template()
  return self.page.href
 def click(self,**kw):
  self.page.clicks.append(self.kind)
  if self.kind=='open':self.page.emit(self.page.stale_tasks or Response(self.page,self.page.task_url,self.page.tasks))
  if self.kind=='link':
   if self.page.identity_during_download is not None:self.page.emit(Response(self.page,IDENTITY,self.page.identity_during_download))
   self.page.pending.value=self.page.download or Download(self.page)

class Page(Locator):
 def __init__(self,temp):
  super().__init__(self);self.main_frame=SimpleNamespace(page=self,url='https://jingmai.jd.com/',parent_frame=None);self.temp=Path(temp);self.href=HREF;self.template=template();self.handlers={};self.pending=None;self.clicks=[];self.urls=[];self.closed=False;self.drawer_count=1;self.link_count=1;self.task_url=TASKS;self.stale_tasks=None;self.download=None;self.identity_during_download=None;self.on_template=None
  self.identities=[{'data':{'shopName':'synthetic-store','venderId':'1','shopId':'3','shopType':'POP','cookie':'synthetic-only-private'}}]
  self.tasks={'code':200,'data':{'batchJobRecordDtoList':[{'taskInstanceId':'123456','jobId':'987654','jobExecFileSrc':'https://storage.jd.com/synthetic/upload.xlsx?token=synthetic-only-private','jobExecTimeStart':1000},{'jobId':'876543'}]}}
 def on(self,event,handler):self.handlers[event]=handler
 def emit(self,response):
  if not response.request.started:
   response.request.started=True
   if self.handlers.get('request'):self.handlers['request'](response.request)
  if self.handlers.get('response'):self.handlers['response'](response)
  if self.pending and self.pending.kind=='response' and self.pending.predicate(response):self.pending.value=response
 def goto(self,url,**kw):
  self.urls.append(url);self.main_frame.url=url
  for value in self.identities:self.emit(Response(self,IDENTITY,value))
 def wait_for_timeout(self,n):pass
 def is_closed(self):return self.closed
 def expect_response(self,predicate,**kw):return Pending(self,'response',predicate)
 def expect_download(self,**kw):return Pending(self,'download')

class Context:
 def __init__(self,temp):self.pages=[];self.temp=temp;self.closed=False;self.fail_close=False
 def new_page(self):self.page=Page(self.temp);self.pages.append(self.page);return self.page
 def close(self):
  if self.fail_close:raise RuntimeError('synthetic-only-private close failure')
  self.closed=True

class Driver:
 def __init__(self,temp):self.chromium=self;self.context=Context(temp);self.launches=[];self.stopped=False
 def launch_persistent_context(self,path,**kw):self.launches.append((path,kw));return self.context
 def stop(self):self.stopped=True
class Factory:
 def __init__(self,temp):self.driver=Driver(temp)
 def start(self):return self.driver

class ShortTitleBrowserTests(unittest.TestCase):
 def make(self,d,**kw):
  c,s,a=plan_fixtures.ShortTitlePlansTests().make(d);p=s.prepare(a['auditId'],[plan_fixtures.ShortTitlePlansTests().row()]);f=Factory(d);cls=importlib.import_module('heideng_merchant.short_title_browser').ShortTitleSourceBrowser;b=cls(d,c,p['planId'],factory=lambda:f,clock=lambda:1000,headless=True,**kw);return c,s,p,f,b
 def test_owned_context_captures_template_and_page_without_import(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();r=b.capture();self.assertEqual(r['status'],'source-captured');self.assertTrue(r['browserIdentityVerified']);self.assertTrue(r['templateOriginCaptured']);self.assertFalse(r['imported']);self.assertFalse(r['writeExecutionAvailable']);self.assertFalse(r['taskListComplete']);self.assertEqual(r['observedTaskRowCount'],2);self.assertEqual(r['observedInstanceIds'],['123456']);self.assertFalse(c.posts)
   path,opts=f.driver.launches[0];self.assertTrue(Path(path).is_relative_to(Path(d)));self.assertNotIn('profile-directory',' '.join(opts.get('args',[])));self.assertEqual(opts['service_workers'],'block');self.assertNotIn('JD_LLM_API_KEY',opts['env']);b.close();self.assertTrue(f.driver.context.closed);self.assertTrue(f.driver.stopped)
 def test_identity_requires_same_object_all_three_fields_and_pop(self):
  values=[{'data':[{'shopName':'synthetic-store'},{'venderId':'1','shopId':'1','shopType':'POP'}]}, {'data':{'shopName':'synthetic-store','venderId':'1','shopId':'2','shopType':'POP'}}, {'data':{'shopName':'synthetic-store','venderId':'2','shopId':'1','shopType':'POP'}}, {'data':{'shopName':'synthetic-store','venderId':'1','shopId':'1'}}, {'data':{'shopName':'synthetic-store','venderId':'1','shopId':'1','shopType':'1'}}]
  for value in values:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();f.driver.context.page.identities=[value]
    with self.assertRaises(SafetyError):b.capture()
    self.assertFalse(f.driver.context.page.clicks);b.close()
 def test_previous_login_proof_is_not_reused_after_navigation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();f.driver.context.page.identities=[]
   with self.assertRaises(SafetyError):b.capture()
   b.close()
 def test_foreign_identity_seen_after_target_revokes_source(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;page.identities.append({'data':{'shopName':'other-synthetic','venderId':'2','shopId':'2','shopType':'POP'}})
   with self.assertRaises(SafetyError):b.capture()
   self.assertFalse(page.clicks);b.close()
 def test_unowned_page_response_cannot_prove_identity(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;page.identities=[];old=page.goto
   def goto(url,**kw):old(url,**kw);page.emit(Response(object(),IDENTITY,{'data':{'shopName':'synthetic-store','venderId':'1','shopId':'3','shopType':'POP'}}))
   page.goto=goto
   with self.assertRaises(SafetyError):b.capture()
   b.close()
 def test_identity_drift_during_template_download_revokes_source(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();f.driver.context.page.identity_during_download={'data':{'shopName':'other-synthetic','venderId':'2','shopId':'2','shopType':'POP'}}
   with self.assertRaises(SafetyError):b.capture()
   self.assertFalse(list(Path(d).glob('short-title-browser-sources/*.json')));b.close()
 def test_unique_drawer_and_unique_template_link_required(self):
  for key in ('drawer_count','link_count'):
   for number in (0,2):
    with self.subTest(key=key,number=number),tempfile.TemporaryDirectory() as d:
     c,s,p,f,b=self.make(d);b.open();setattr(f.driver.context.page,key,number)
     with self.assertRaises(SafetyError):b.capture()
     b.close()
 def test_task_service_is_exact_not_substring_or_foreign_origin(self):
  for url in ('https://example.com/api?method=batchJobService.queryByPage','https://api.m.jd.com/api?method=fakebatchJobService.queryByPage','https://api.m.jd.com/api?method=batchJobService.queryByPage&method=another','https://api.m.jd.com/api?token=batchJobService.queryByPage'):
   with self.subTest(url=url),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();f.driver.context.page.task_url=url
    with self.assertRaises(SafetyError):b.capture()
    b.close()
 def test_task_source_code_shape_duplicate_instances_and_limits_fail_closed(self):
  values=[{'code':500,'data':{'batchJobRecordDtoList':[]}}, {'code':200,'data':{}}, {'code':200,'data':{'batchJobRecordDtoList':[{'taskInstanceId':'123456'},{'taskInstanceId':'123456'}]}}, {'code':200,'data':{'batchJobRecordDtoList':[{'taskId':'123456','taskInstanceId':'234567'}]}}, {'code':200,'data':{'batchJobRecordDtoList':[{}]*501}}]
  for value in values:
   with self.subTest(value=str(value)[:80]),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();f.driver.context.page.tasks=value
    with self.assertRaises(SafetyError):b.capture()
    b.close()
 def test_external_template_url_or_event_substitution_refused(self):
  for href in ('https://example.com/template.xlsx','http://storage.jd.com/template.xlsx','file:///synthetic.xlsx','https://storage.jd.com:8443/template.xlsx'):
   with self.subTest(href=href),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();f.driver.context.page.href=href
    with self.assertRaises(SafetyError):b.capture()
    self.assertNotIn('link',f.driver.context.page.clicks);b.close()
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;page.download=Download(page);page.download.url='https://storage.jd.com/synthetic/other.xlsx'
   with self.assertRaises(SafetyError):b.capture()
   b.close()
 def test_unsafe_and_oversized_downloads_not_persisted_as_sources(self):
  for raw in (b'not-xlsx',b'x'*(5*1024*1024+1)):
   with self.subTest(size=len(raw)),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();f.driver.context.page.template=raw
    with self.assertRaises(SafetyError):b.capture()
    self.assertFalse(list(Path(d).glob('short-title-browser-sources/*.json')));b.close()
 def test_source_and_summary_do_not_contain_raw_response_or_signed_url(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();r=b.capture();raw='\n'.join(x.read_text() for x in Path(d).rglob('*.json'));self.assertNotIn('synthetic-only-private',raw);self.assertNotIn('?token=',raw);self.assertNotIn('cookie',json.dumps(r));b.close()
 def test_original_census_drift_blocks_source_freeze(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page
   def mutate():c.products[0]['productName']='changed-synthetic'
   page.on_template=mutate
   with self.assertRaises(SafetyError):b.capture()
   self.assertFalse(list(Path(d).glob('short-title-browser-sources/*.json')));b.close()
 def test_source_or_template_tamper_detected_and_capture_not_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();r=b.capture()
   with self.assertRaises(SafetyError):b.capture()
   reader=importlib.import_module('heideng_merchant.short_title_browser').read_source;self.assertEqual(reader(d,c,r['sourceId'])['status'],'source-captured');src=read_json(Path(d)/('short-title-browser-sources/'+r['sourceId']+'.json'));(Path(d)/src['scope']['template']['localPath']).write_bytes(b'changed')
   with self.assertRaises(SafetyError):reader(d,c,r['sourceId'])
   b.close()
 def test_session_owner_and_cleanup_failure_cannot_reopen_profile(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();session=b.session_id;f.driver.context.fail_close=True
   with self.assertRaises(SafetyError):b.close()
   cls=importlib.import_module('heideng_merchant.short_title_browser').ShortTitleSourceBrowser;other=cls(d,c,p['planId'],session_id=session,factory=lambda:Factory(d),headless=True,clock=lambda:1000)
   with self.assertRaises(SafetyError):other.open()
   f.driver.context.fail_close=False;b.close()
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();session=b.session_id;b.close();owner=Path(d)/('browser/short-title/'+session+'/owner.json');x=read_json(owner);x['shop']['shopId']='2';atomic_json(owner,x);other=importlib.import_module('heideng_merchant.short_title_browser').ShortTitleSourceBrowser(d,c,p['planId'],session_id=session,factory=lambda:Factory(d))
   with self.assertRaises(SafetyError):other.open()
 def test_source_requested_id_and_source_scope_not_substitutable(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();r=b.capture();b.close();src=Path(d)/('short-title-browser-sources/'+r['sourceId']+'.json');other='a'*24;(src.parent/(other+'.json')).write_bytes(src.read_bytes());reader=importlib.import_module('heideng_merchant.short_title_browser').read_source
   with self.assertRaises(SafetyError):reader(d,c,other)

 def test_rehashed_identity_or_template_source_cannot_replace_original_observation(self):
  from heideng_merchant.operations import digest
  reader=importlib.import_module('heideng_merchant.short_title_browser').read_source
  for section in ('identity','template','taskPage'):
   with self.subTest(section=section),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();r=b.capture();b.close();path=Path(d)/('short-title-browser-sources/'+r['sourceId']+'.json');src=read_json(path);src['scope'][section]['sourceSha256']='a'*64;src['fingerprint']=digest(src['scope']);atomic_json(path,src)
    with self.assertRaises(SafetyError):reader(d,c,r['sourceId'])
 def test_existing_unowned_profile_is_never_adopted(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);profile=Path(d)/b.binding['profilePath'];profile.mkdir(parents=True);(profile/'synthetic-copied-profile-marker').write_text('synthetic only')
   with self.assertRaises(SafetyError):b.open()
   self.assertFalse(f.driver.launches)
 def test_launch_exception_quarantines_profile_even_when_controller_stops(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d)
   def launch(*args,**kw):raise RuntimeError('synthetic-only-private launch result unknown')
   f.driver.launch_persistent_context=launch
   with self.assertRaises(SafetyError):b.open()
   self.assertTrue(f.driver.stopped);self.assertEqual(read_json(b.lifecycle_path)['status'],'close-unknown');other=importlib.import_module('heideng_merchant.short_title_browser').ShortTitleSourceBrowser(d,c,p['planId'],session_id=b.session_id,factory=lambda:Factory(d))
   with self.assertRaises(SafetyError):other.open()

 def test_unopened_close_cannot_clear_unknown_launch_quarantine(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d)
   def fail(*args,**kw):raise RuntimeError('synthetic unknown launch')
   f.driver.launch_persistent_context=fail
   with self.assertRaises(SafetyError):b.open()
   before=b.lifecycle_path.read_bytes();other=importlib.import_module('heideng_merchant.short_title_browser').ShortTitleSourceBrowser(d,c,p['planId'],session_id=b.session_id,factory=lambda:Factory(d));other.close();self.assertEqual(b.lifecycle_path.read_bytes(),before)
   with self.assertRaises(SafetyError):other.open()
 def test_pre_capture_request_and_child_frame_cannot_prove_current_identity(self):
  for mode in ('old-request','child-frame'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;stale=Response(page,IDENTITY,page.identities[0]);page.identities=[]
    if mode=='old-request':stale.request.timing={'startTime':0}
    else:page.main_frame=SimpleNamespace(page=page);stale.request.frame=SimpleNamespace(page=page,parent_frame=page.main_frame)
    old=page.goto
    def goto(url,**kw):old(url,**kw);page.emit(stale)
    page.goto=goto
    try:
     with self.assertRaises(SafetyError):b.capture()
    finally:b.close()
 def test_duplicate_json_cannot_erase_foreign_identity(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;page.identities=[];resp=Response(page,IDENTITY,{});raw=b'{"data":{"shopName":"foreign-synthetic","venderId":"2","shopId":"4","shopType":"POP"},"data":{"shopName":"synthetic-store","venderId":"1","shopId":"3","shopType":"POP"}}';resp.body=lambda:raw;old=page.goto
   def goto(url,**kw):old(url,**kw);page.emit(resp)
   page.goto=goto
   try:
    with self.assertRaises(SafetyError):b.capture()
   finally:b.close()
 def test_depth_abort_latches_unknown_or_foreign_identity(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;deep={}
   for _ in range(31):deep={'child':deep}
   page.tasks={'code':200,'data':{'batchJobRecordDtoList':[]},'foreign':{'shopName':'foreign-synthetic','venderId':'2','shopId':'4','shopType':'POP'},'metadata':deep}
   try:
    with self.assertRaises(SafetyError):b.capture()
   finally:b.close()
 def test_literal_vender_id_is_required_and_alias_only_can_not_replace_it(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();f.driver.context.page.identities=[{'data':{'shopName':'synthetic-store','vendorId':'1','shopId':'3','shopType':'POP'}}]
   try:
    with self.assertRaises(SafetyError):b.capture()
   finally:b.close()

 def test_old_task_request_is_not_current_drawer_snapshot(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open();page=f.driver.context.page;page.stale_tasks=Response(page,TASKS,{'code':200,'data':{'batchJobRecordDtoList':[{'taskInstanceId':'999999'}]}});page.stale_tasks.request.timing={'startTime':0}
   try:
    with self.assertRaises(SafetyError):b.capture()
   finally:b.close()

if __name__=='__main__':unittest.main()
