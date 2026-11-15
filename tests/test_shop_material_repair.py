"""Synthetic complete-shop repairs; no merchant auth, HTTP or model calls."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from heideng_merchant.shop_material_audit import ShopMaterialAudit
from heideng_merchant.shop_material_execution import ShopMaterialExecution
from tests.shop_material_execution_fixtures import Client
from tests.test_sku_materials import material
from tests import test_sku_materials as sku_tests
from tests.material_fixtures import probe

class ShopMaterialRepairTests(unittest.TestCase):
 def make(self,d,first=2,second=1):
  c=Client(first,second);s=ShopMaterialExecution(d,c);s.ops.connect('merchant-test','synthetic-store','1');return c,s
 def audit(self,c,s):return ShopMaterialAudit(s.state,c).audit('merchant-test',include_health=False)
 def text(self,sku=101,pid=9,slot='point1',text='柔软舒适'):
  return {'productId':pid,'skuId':sku,'slot':slot,'text':text,'review':'passed','action':'repair'}
 def run_plan(self,s,p):s.approve(p['planId'],p['fingerprint'],confirmed=True);return s.execute(p['planId'])
 def upload(self,s,d):return sku_tests.SkuMaterialTests().upload(s,d)
 def image(self,tid):return {'productId':9,'skuId':101,'slot':'scene2','uploadTaskId':tid,'review':'passed','action':'repair'}
 def test_rejected_text_is_replaced_under_original_root_and_all_fields_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);old=material(101,1002,1,'轻巧便携',5);old['auditDesc']='synthetic inaccurate text';c.materials['101'].append(old);before=copy.deepcopy(c.materials);a=self.audit(c,s)
   p=s.prepare(a['auditId'],[self.text()],target_slots=['point1']);self.assertEqual(p['readyRepairCount'],1);self.assertFalse(p['allReadyChangesVerified']);r=self.run_plan(s,p);self.assertTrue(r['allReadyChangesVerified']);self.assertEqual(r['verifiedRepairCount'],1);self.assertFalse(r['auditApprovedForWrittenChanges']);self.assertFalse(r['scoreRecalculated'])
   self.assertEqual(c.posts[0]['skuMaterials'][0]['materials'][0]['textMaterial']['contents'],['柔软舒适']);self.assertIn(before['101'][0],c.materials['101']);self.assertEqual(before['1001'],c.materials['1001']);self.assertEqual(before['9001'],c.materials['9001'])
   task=s.ops.task(s.plan(p['planId'])['scope']['tasks'][0]['taskId']);self.assertEqual(task['scope']['skuMaterialInput']['version'],2)
 def test_existing_empty_approved_text_is_repaired_and_missing_slot_is_not(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);old=material(101,1002,1,'',4);c.materials['101'].append(old);a=self.audit(c,s);p=s.prepare(a['auditId'],[self.text()],target_slots=['point1']);self.assertEqual(p['existingEmptySlotCount'],1);r=self.run_plan(s,p);self.assertTrue(r['allReadyChangesVerified']);self.assertEqual(r['verifiedRepairCount'],1)
   with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.text(sku=102)],target_slots=['point1'])
 def test_pending_unknown_and_approved_nonempty_slots_cannot_be_repaired(self):
  for status in (3,None,1,2,4):
   with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'轻巧便携',status));a=self.audit(c,s)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.text()],target_slots=['point1'])
    self.assertFalse(c.posts)
 def test_empty_pending_or_unknown_slot_is_not_repair_eligible(self):
  for status in (3,None,0):
   with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'',status));a=self.audit(c,s)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.text()])
 def test_repair_requires_explicit_action_and_changed_text(self):
  for action,text in ((None,'柔软舒适'),('repair','轻巧便携'),('replace','柔软舒适')):
   with self.subTest(action=action,text=text),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'轻巧便携',5));a=self.audit(c,s);row=self.text(text=text)
    if action is None:row.pop('action')
    else:row['action']=action
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[row])
    self.assertFalse(c.posts)
 def test_status_or_reason_drift_blocks_before_first_write(self):
  for drift in ('status','auditDesc'):
   with self.subTest(drift=drift),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'轻巧便携',5));a=self.audit(c,s);p=s.prepare(a['auditId'],[self.text()]);s.approve(p['planId'],p['fingerprint'],confirmed=True);c.materials['101'][-1][drift]=4 if drift=='status' else 'changed rejection'
    with self.assertRaises(SafetyError):s.execute(p['planId'])
    self.assertFalse(c.posts)
 def test_audit_drift_during_preparation_creates_no_tasks(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'轻巧便携',5));a=self.audit(c,s);c.materials['101'][-1]['status']=4
   with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.text()])
   self.assertFalse(list((Path(d)/'tasks').glob('*.json')) if (Path(d)/'tasks').exists() else [])
 def test_new_image_bytes_and_url_are_checked_and_original_cache_survives(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',return_value=b'synthetic-old-original') as fetch:
   c,s=self.make(d);c.materials['101'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d);p=s.prepare(a['auditId'],[self.image(tid)],target_slots=['scene2']);self.assertEqual(p['readyRepairCount'],1);self.assertTrue(fetch.called);r=self.run_plan(s,p);self.assertTrue(r['allReadyChangesVerified']);self.assertEqual(r['verifiedRepairCount'],1);self.assertTrue(list((Path(d)/'sku-material-originals').glob('*.bin')))
 def test_different_url_with_identical_original_bytes_is_refused(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
   c,s=self.make(d);c.materials['101'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d);source=next(Path(d).rglob('sample.png'));original=source.read_bytes()
   with patch('heideng_merchant.workflows._asset_download',return_value=original):
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.image(tid)],target_slots=['scene2'])
   self.assertFalse(c.posts)
 def test_original_cache_missing_or_changed_blocks_write(self):
  for fault in ('missing','changed'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',return_value=b'synthetic-old-original'):
    c,s=self.make(d);c.materials['101'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d);p=s.prepare(a['auditId'],[self.image(tid)]);s.approve(p['planId'],p['fingerprint'],confirmed=True);cache=next((Path(d)/'sku-material-originals').glob('*.bin'))
    if fault=='missing':cache.unlink()
    else:cache.write_bytes(b'changed')
    with self.assertRaises(SafetyError):s.execute(p['planId'])
    self.assertFalse(c.posts)
 def test_remote_original_byte_drift_is_not_written(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',return_value=b'synthetic-old-original') as fetch:
   c,s=self.make(d);c.materials['101'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d);p=s.prepare(a['auditId'],[self.image(tid)]);s.approve(p['planId'],p['fingerprint'],confirmed=True);fetch.return_value=b'changed-original'
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)
 def test_empty_approved_image_does_not_fabricate_original_download(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',side_effect=AssertionError('no old image')):
   c,s=self.make(d);c.materials['101'][0]['imageMaterial']['skuImages']=[];a=self.audit(c,s);tid=self.upload(s,d);p=s.prepare(a['auditId'],[self.image(tid)]);self.assertTrue(self.run_plan(s,p)['allReadyChangesVerified'])
 def test_original_download_failure_preserves_plan_not_started(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',side_effect=SafetyError('synthetic download failed')):
   c,s=self.make(d);c.materials['101'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d)
   with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.image(tid)])
   self.assertFalse(c.posts);self.assertFalse(list((Path(d)/'shop-material-plans').glob('*.json')))
 def test_mixed_multichunk_repairs_unknown_tail_cannot_replay(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d,53,3);rows=[]
   for sku in c.skus:
    if sku['status']==103 and sku['productId']!=20:
     c.materials[str(sku['skuId'])].append(material(sku['skuId'],1002,1,'轻巧便携',5));rows.append(self.text(sku=sku['skuId'],pid=sku['productId']))
   a=self.audit(c,s);p=s.prepare(a['auditId'],rows,target_slots=['point1']);self.assertEqual(p['readyRepairCount'],56);s.approve(p['planId'],p['fingerprint'],confirmed=True);c.write_fault_on=2;r=s.execute(p['planId']);self.assertEqual(r['verifiedRepairCount'],50);self.assertTrue(r['originalOutcomeUnknown']);self.assertEqual(len(c.posts),2);c.write_fault_on=None;c.fault=None;s.status(p['planId'],refresh=True);s.execute(p['planId']);self.assertEqual(len(c.posts),2)

 def test_declared_incomplete_http_original_is_not_a_valid_capture(self):
  import io,http.client,socket
  from tests.material_fixtures import png
  from heideng_merchant.sku_material_repair import _download
  raw=png()
  class MemorySocket:
   def makefile(self,mode):return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(raw)).encode()+b'\r\nContent-Type: image/png\r\n\r\n'+raw[:16])
  class Opener:
   def open(self,*a,**kw):
    response=http.client.HTTPResponse(MemorySocket());response.begin();return response
  with patch('urllib.request.build_opener',return_value=Opener()),patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):
   with self.assertRaises(SafetyError):_download('jfs/t1/original.png')
 def test_new_bytes_matching_other_products_original_are_blocked_before_tasks(self):
  from tests.material_fixtures import png
  from heideng_merchant.materials import MaterialService
  class Distinct(Client):
   def invoke(self,p,url,**kw):
    result=super().invoke(p,url,**kw)
    if url.endswith('/media-zones/{zoneId}/images') and kw.get('method')=='POST':
     self.images[-1]['imgUrl']='jfs/new/'+self.images[-1]['imgId']+'.png';result['data']=copy.deepcopy(self.images[-1])
    return result
  for same_product in (False,True):
   with self.subTest(same_product=same_product),tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
    c=Distinct(2,1);s=ShopMaterialExecution(d,c);s.ops.connect('merchant-test','synthetic-store','1');other=102 if same_product else 1001;pid=9 if same_product else 10
    c.materials['101']=[material(101,32,2,'jfs/old/a.png',5)];c.materials[str(other)]=[material(other,32,2,'jfs/old/b.png',5)];a=self.audit(c,s)
    def upload(raw,name):
     path=Path(d)/name;path.write_bytes(raw);t=MaterialService(d,c).prepare_upload('merchant-test',path,'img_test',7)['task'];s.ops.approve(t['taskId'],t['fingerprint'],confirmed=True);s.ops.execute(t['taskId']);s.ops.verify_result(t['taskId']);return t['taskId']
    tid_a=upload(png(),'reuse-other.png');tid_b=upload(png()+b'synthetic-fresh-bytes','fresh.png')
    def fetch(url,**kw):return b'synthetic-old-a' if url.endswith('a.png') else png()
    with patch('heideng_merchant.workflows._asset_download',side_effect=fetch):
     rows=[self.image(tid_a),{'productId':pid,'skuId':other,'slot':'scene2','uploadTaskId':tid_b,'review':'passed','action':'repair'}]
     with self.assertRaises(SafetyError):s.prepare(a['auditId'],rows,target_slots=['scene2'])
    self.assertFalse(c.posts);self.assertFalse(list((Path(d)/'shop-material-plans').glob('*.json')))


 def test_complete_http_capture_boundaries(self):
  import io,http.client,socket
  from tests.material_fixtures import png
  from heideng_merchant.sku_material_repair import _download
  raw=png()
  for case in ('length','chunked','missing-length','range','gzip','incomplete-chunk','duplicate-length'):
   with self.subTest(case=case):
    status=b'206 Partial Content' if case=='range' else b'200 OK'
    headers=b'Content-Length: '+str(len(raw)).encode()+b'\r\n'
    body=raw
    if case=='missing-length':headers=b'Connection: close\r\n'
    if case=='gzip':headers+=b'Content-Encoding: gzip\r\n'
    if case=='duplicate-length':headers+=b'Content-Length: 16\r\n'
    if case in ('chunked','incomplete-chunk'):
     headers=b'Transfer-Encoding: chunked\r\n';body=hex(len(raw))[2:].encode()+b'\r\n'+(raw if case=='chunked' else raw[:16])+b'\r\n'+(b'0\r\n\r\n' if case=='chunked' else b'')
    wire=b'HTTP/1.1 '+status+b'\r\n'+headers+b'\r\n'+body
    class MemorySocket:
     def makefile(self,mode):return io.BytesIO(wire)
    class Opener:
     def open(self,*a,**kw):
      response=http.client.HTTPResponse(MemorySocket());response.begin();return response
    with patch('urllib.request.build_opener',return_value=Opener()),patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):
     if case in ('length','chunked'):self.assertEqual(_download('jfs/t1/original.png'),raw)
     else:
      with self.assertRaises(SafetyError):_download('jfs/t1/original.png')
 def test_standalone_material_plan_uses_same_v2_global_proof_without_changing_v1_tail(self):
  from heideng_merchant.sku_materials import SkuMaterialService
  with tempfile.TemporaryDirectory() as d:
   helper=sku_tests.SkuMaterialTests();c,s=helper.make(d,53);c.materials['101'].append(material(101,1002,1,'轻巧便携',5));rows=[{'skuId':101,'slot':'point1','text':'柔软舒适','review':'passed','action':'repair'}]+[{'skuId':i,'slot':'point1','text':'轻松收纳','review':'passed'} for i in range(102,154)]
   p=s.prepare('merchant-test',9,rows);self.assertEqual([s.ops.task(t['taskId'])['scope']['skuMaterialInput']['version'] for t in p['tasks']],[2,1]);r=helper.run_plan(s,p);self.assertTrue(r['materialFieldsVerified']);self.assertEqual([len(b['skuMaterials']) for b in c.posts],[50,3])


 def test_root_original_set_rejects_an_incomplete_other_child_image_scope(self):
  from heideng_merchant.sku_material_repair import original_set
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',return_value=b'synthetic-old-original'):
   c,s=self.make(d);c.materials['101'][0]['status']=5;c.materials['1001'][0]['status']=5;a=self.audit(c,s);tid=self.upload(s,d);rows=[self.image(tid),{'productId':10,'skuId':1001,'slot':'scene2','uploadTaskId':tid,'review':'passed','action':'repair'}];p=s.prepare(a['auditId'],rows,target_slots=['scene2'])
   proofs=[copy.deepcopy(s.ops.task(ref['taskId'])['scope']['skuMaterialInput']) for ref in s.plan(p['planId'])['scope']['tasks']];self.assertTrue(original_set(proofs));proofs[1]['repairSources']={}
   with self.assertRaises(SafetyError):original_set(proofs)
   self.assertFalse(c.posts)

if __name__=='__main__':unittest.main()
