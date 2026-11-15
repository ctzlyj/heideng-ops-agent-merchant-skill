import importlib,tempfile,unittest,json,copy,hashlib
from pathlib import Path
from tests import test_short_title_browser as source_fixtures
from tests.short_title_import_fixtures import ImportFactory
from heideng_merchant.safety import SafetyError,read_json,atomic_json

class ShortTitleImportsTests(unittest.TestCase):
 def make(self,d):
  c,s,p,f,b=source_fixtures.ShortTitleBrowserTests().make(d);b.open();source=b.capture();b.close();cls=importlib.import_module('heideng_merchant.short_title_imports').ShortTitleImports;m=cls(d,c,clock=lambda:1000);root=m.prepare(p['planId'],source['sourceId']);return c,s,p,source,m,root
 def browser(self,d,m,root):
  f=ImportFactory(d);cls=importlib.import_module('heideng_merchant.short_title_import_browser').ShortTitleImportBrowser;b=cls(m,root['importId'],factory=lambda:f,headless=True);b.open();return f,b
 def test_exact_root_and_one_approval_are_not_import_or_effectiveness(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);self.assertEqual(r['proposedRowCount'],1);self.assertEqual(r['approvedRowCount'],0);self.assertEqual(r['batchCount'],1);self.assertFalse(r['imported']);self.assertFalse(r['actualTitlesVerified']);self.assertEqual(m.prepare(p['planId'],src['sourceId'])['importId'],r['importId'])
   with self.assertRaises(SafetyError):m.approve(r['importId'],'a'*64,confirmed=True)
   with self.assertRaises(SafetyError):m.approve(r['importId'],r['fingerprint'],confirmed=False)
   a=m.approve(r['importId'],r['fingerprint'],confirmed=True);self.assertEqual(a['status'],'approved');self.assertFalse(a['imported']);self.assertFalse(c.posts)
 def test_native_upload_and_create_are_anchored_but_not_claimed_applied(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r)
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['status'],'submitted-awaiting-verification');self.assertEqual(out['submittedBatchCount'],1);self.assertFalse(out['imported']);self.assertFalse(out['actualTitlesVerified']);self.assertEqual(f.driver.context.page.uploads,1);self.assertEqual(f.driver.context.page.creates,1);again=m.execute(r['importId'],b);self.assertEqual(again['submittedBatchCount'],1);self.assertEqual(f.driver.context.page.uploads,1);self.assertEqual(f.driver.context.page.creates,1)
   finally:b.close()
 def test_unapproved_expired_or_wrong_browser_has_zero_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);f,b=self.browser(d,m,r)
   try:
    with self.assertRaises(SafetyError):m.execute(r['importId'],b)
    self.assertEqual(f.driver.context.page.uploads,0);m.approve(r['importId'],r['fingerprint'],confirmed=True,ttl=30);m.clock=lambda:2000
    with self.assertRaises(SafetyError):m.execute(r['importId'],b)
    self.assertEqual(f.driver.context.page.uploads,0)
   finally:b.close()
 def test_upload_unknown_or_non_success_never_reuploads_or_creates(self):
  for fault in ('upload-timeout','upload-refused'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault=fault
    try:
     out=m.execute(r['importId'],b);self.assertIn(out['status'],('unknown','non-success-unverified'));self.assertEqual(f.driver.context.page.uploads,1);self.assertEqual(f.driver.context.page.creates,0);m.execute(r['importId'],b);self.assertEqual(f.driver.context.page.uploads,1);self.assertEqual(f.driver.context.page.creates,0)
    finally:b.close()
 def test_lost_create_ack_recovers_original_instance_by_read_only_anchor(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault='create-timeout'
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['status'],'unknown');self.assertEqual(f.driver.context.page.creates,1);out=m.recover(r['importId'],b);self.assertEqual(out['status'],'submitted-awaiting-verification');self.assertEqual(f.driver.context.page.creates,1);self.assertEqual(f.driver.context.page.uploads,1);m.execute(r['importId'],b);self.assertEqual(f.driver.context.page.creates,1)
   finally:b.close()
 def test_type_job_id_does_not_become_instance_and_wrong_anchor_stays_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);page=f.driver.context.page;page.fault='type-id-only'
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['submittedBatchCount'],1);row=m.rows(r['importId'],view='batches')['items'][0];self.assertEqual(row['instanceId'],'7000000001');self.assertNotEqual(row['instanceId'],'30034')
   finally:b.close()
 def test_scope_artifact_and_any_independent_original_tamper_prevents_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);root=m.record(r['importId']);path=Path(d)/root['scope']['artifacts'][0]['localPath'];path.write_bytes(b'tampered');f=None;b=None
   with self.assertRaises(SafetyError):m.status(r['importId'])
   self.assertFalse(c.posts)
 def test_original_records_and_replies_never_store_private_response_or_url(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r)
   try:out=m.execute(r['importId'],b)
   finally:b.close()
   text='\n'.join(x.read_text() for x in Path(d).rglob('*.json'));self.assertNotIn('synthetic-only-private',text);self.assertNotIn('?token=',text);self.assertFalse(c.posts)
 def test_no_original_source_and_other_requested_id_are_refused(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d)
   with self.assertRaises(SafetyError):m.prepare(p['planId'],'a'*24)
   root=Path(d)/('short-title-imports/'+r['importId']+'.json');root.parent.joinpath('a'*24+'.json').write_bytes(root.read_bytes())
   with self.assertRaises(SafetyError):m.status('a'*24)

 def large(self,d):
  from tests.test_shop_material_audit import ShopClient
  from heideng_merchant.short_titles import ShortTitlePlans
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  from heideng_merchant.short_title_browser import ShortTitleSourceBrowser
  c=ShopClient(large=5001);c.health=[{'skuId':row['skuId'],'productId':row['productId'],'healthScore':None,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]} for row in c.skus if row['status']==103];c.fault='omitted';s=ShortTitlePlans(d,c);s.ops.connect('merchant-test','synthetic-store','1');audit=ShopMaterialAudit(d,c).audit('merchant-test');changes=[{'productId':row['productId'],'skuId':row['skuId'],'shortTitle':'收纳'+str(row['skuId']),'review':'passed'} for row in c.skus if row['status']==103];p=s.prepare(audit['auditId'],changes);f=source_fixtures.Factory(d);b=ShortTitleSourceBrowser(d,c,p['planId'],factory=lambda:f,clock=lambda:1000,headless=True);b.open();src=b.capture();b.close();m=importlib.import_module('heideng_merchant.short_title_imports').ShortTitleImports(d,c,clock=lambda:1000);r=m.prepare(p['planId'],src['sourceId']);return c,s,p,src,m,r
 def test_all_5001_rows_one_root_approval_two_actual_native_dispatches(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.large(d);self.assertEqual(r['proposedRowCount'],5001);self.assertEqual(r['batchCount'],2);self.assertEqual([x['rowCount'] for x in m.rows(r['importId'])['items']],[5000,1]);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r)
   try:out=m.execute(r['importId'],b);self.assertEqual(out['submittedBatchCount'],2);self.assertFalse(out['imported']);self.assertEqual(f.driver.context.page.uploads,2);self.assertEqual(f.driver.context.page.creates,2)
   finally:b.close()
   self.assertEqual(len(list((Path(d)/'short-title-import-approvals'/r['importId']).glob('*.json'))),1)
 def test_missing_future_file_cannot_allow_earlier_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.large(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);root=m.record(r['importId']);(Path(d)/root['scope']['artifacts'][1]['localPath']).unlink()
   try:
    with self.assertRaises(SafetyError):m.execute(r['importId'],b)
    self.assertEqual(f.driver.context.page.uploads,0);self.assertEqual(f.driver.context.page.creates,0)
   finally:b.close()
 def test_duplicate_uploaded_object_candidates_do_not_hide_behind_known_ack_id(self):
  from tests.short_title_import_fixtures import CREATE
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);page=f.driver.context.page;old=page.emit
   def emit(response):
    old(response)
    if response.url==CREATE:row=copy.deepcopy(page.tasks['data']['batchJobRecordDtoList'][-1]);row['jobExecId']='7000000099';page.tasks['data']['batchJobRecordDtoList'].append(row)
   page.emit=emit
   try:self.assertEqual(m.execute(r['importId'],b)['status'],'unknown');self.assertEqual(page.creates,1)
   finally:b.close()
 def test_later_original_attempts_prove_missing_earlier_prefix_not_unstarted(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.large(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r)
   try:
    self.assertEqual(m.execute(r['importId'],b)['submittedBatchCount'],2)
    for folder in ('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors'):
     for file in (Path(d)/folder/r['importId']).glob('000001-*.json'):file.unlink()
    with self.assertRaises(SafetyError):m.execute(r['importId'],b)
    self.assertEqual(f.driver.context.page.uploads,2);self.assertEqual(f.driver.context.page.creates,2)
   finally:b.close()
 def test_changed_native_template_is_specific_preflight_stop_not_completion(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.template=b'different synthetic template'
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['status'],'approved');self.assertEqual(out['stoppedReason'],'current-browser-source-or-template-not-verified');self.assertEqual(f.driver.context.page.uploads,0)
   finally:b.close()
 def test_malformed_projected_ack_is_never_written_before_validation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);old=b.upload
   def upload(artifact,attempt):old(artifact,attempt);return {'cookie':'synthetic-only-private'}
   b.upload=upload
   try:self.assertEqual(m.execute(r['importId'],b)['status'],'unknown')
   finally:b.close()
   self.assertFalse(list((Path(d)/'short-title-import-acks'/r['importId']).glob('*.json')));self.assertNotIn('synthetic-only-private',''.join(x.read_text() for x in Path(d).rglob('*.json')))
 def test_changed_source_cannot_restart_same_unknown_import_intent(self):
  from heideng_merchant.short_title_browser import ShortTitleSourceBrowser
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault='create-timeout'
   try:self.assertEqual(m.execute(r['importId'],b)['status'],'unknown')
   finally:b.close()
   f2=source_fixtures.Factory(d);other=ShortTitleSourceBrowser(d,c,p['planId'],factory=lambda:f2,clock=lambda:1000,headless=True);other.open();new=other.capture();other.close()
   with self.assertRaises(SafetyError):m.prepare(p['planId'],new['sourceId'])
   self.assertEqual(m.status(r['importId'])['status'],'unknown')
 def test_non_success_create_response_reconciles_only_original_visible_task(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault='create-refused'
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['status'],'non-success-unverified');self.assertEqual(m.recover(r['importId'],b)['submittedBatchCount'],1);self.assertEqual(f.driver.context.page.creates,1)
   finally:b.close()
 def test_transport_cannot_upload_without_original_manager_attempt(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);f,b=self.browser(d,m,r);artifact=m.record(r['importId'])['scope']['artifacts'][0]
   try:
    with self.assertRaises(SafetyError):b.upload(artifact,{'context':{'attemptId':'a'*32}})
    self.assertEqual(f.driver.context.page.uploads,0)
   finally:b.close()

 def test_current_title_problem_removed_prevents_approval_or_later_overwrite(self):
  for stage in ('before-approval','before-upload'):
   with self.subTest(stage=stage),tempfile.TemporaryDirectory() as d:
    c,s,p,src,m,r=self.make(d)
    if stage=='before-upload':m.approve(r['importId'],r['fingerprint'],confirmed=True)
    c.health[0]['improvementList']=[]
    if stage=='before-approval':
     with self.assertRaises(SafetyError):m.approve(r['importId'],r['fingerprint'],confirmed=True)
    else:
     f,b=self.browser(d,m,r)
     try:out=m.execute(r['importId'],b);self.assertEqual(f.driver.context.page.uploads,0);self.assertFalse(out['imported'])
     finally:b.close()
 def test_read_only_recovery_does_not_require_unchanged_sale_or_health_after_write(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault='create-timeout'
   try:
    self.assertEqual(m.execute(r['importId'],b)['status'],'unknown');c.skus[0]['status']=104;c.health[0]['improvementList']=[];self.assertEqual(m.recover(r['importId'],b)['submittedBatchCount'],1);self.assertEqual(f.driver.context.page.creates,1)
   finally:b.close()
 def test_anchor_tamper_cannot_change_instance_when_direct_ack_omitted_id(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);f.driver.context.page.fault='type-id-only'
   try:self.assertEqual(m.execute(r['importId'],b)['submittedBatchCount'],1)
   finally:b.close()
   path=Path(d)/'short-title-import-anchors'/r['importId']/'000001-create.json';value=read_json(path);value['instanceId']='7000000099';atomic_json(path,value)
   with self.assertRaises(SafetyError):m.status(r['importId'])

 def test_conflicting_or_malformed_instance_ack_never_becomes_omitted_id(self):
  from tests.short_title_import_fixtures import CREATE
  for data in ({'taskInstanceId':'7000000001','jobExecId':'7000000099'},{'taskInstanceId':'malformed'}):
   with self.subTest(data=data),tempfile.TemporaryDirectory() as d:
    c,s,p,src,m,r=self.make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);page=f.driver.context.page;old=page.emit
    def emit(response):
     if response.url==CREATE:response.payload={'code':200,'data':data}
     old(response)
    page.emit=emit
    try:
     self.assertEqual(m.execute(r['importId'],b)['status'],'unknown');self.assertEqual(m.recover(r['importId'],b)['status'],'unknown');self.assertEqual(page.creates,1)
    finally:b.close()
 def test_same_actual_instance_cannot_be_reused_across_root_batches(self):
  from tests.short_title_import_fixtures import CREATE
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=self.large(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=self.browser(d,m,r);page=f.driver.context.page;old=page.emit
   def emit(response):
    if response.url==source_fixtures.TASKS and page.creates==1 and page.uploads==1 and (Path(d)/'short-title-import-anchors'/r['importId']/'000001-create.json').exists():page.tasks['data']['batchJobRecordDtoList']=[];response.payload=page.tasks
    if response.url==CREATE and page.creates==2:response.payload={'code':200,'data':{'taskInstanceId':'7000000001'}};page.tasks['data']['batchJobRecordDtoList'][-1]['jobExecId']='7000000001'
    old(response)
   page.emit=emit
   try:
    out=m.execute(r['importId'],b);self.assertEqual(out['status'],'unknown');self.assertEqual(out['submittedBatchCount'],1);self.assertEqual(page.uploads,2);self.assertEqual(page.creates,2)
   finally:b.close()

if __name__=='__main__':unittest.main()
