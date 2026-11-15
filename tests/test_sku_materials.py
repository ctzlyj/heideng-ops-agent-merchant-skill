"""Synthetic native material boundary. No real profiles, auth or HTTP."""
import copy, importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from tests.material_fixtures import Client as ImageClient, png, probe
from heideng_merchant.operations import Operations, digest
from heideng_merchant.safety import SafetyError, atomic_json

READ='/rest/sp-product/v0/sku-materials'
WRITE=READ+'/batch'

def material(sku, kind=32, order=2, value='jfs/t1/preserved.png', status=4):
 row={'skuId':int(sku),'materialType':kind,'order':order,'status':status}
 if kind==1002:row['textMaterial']={'contents':[value]}
 else:row['imageMaterial']={'imgType':1,'skuImages':[{'index':1,'imgUrl':value}]}
 return row

class Client(ImageClient):
 def __init__(self,count=3):
  super().__init__();self.skus=[{'skuId':i+101,'productId':9,'status':103} for i in range(count)];self.materials={str(s['skuId']):[material(s['skuId'])] for s in self.skus};self.posts=[];self.fault=None;self.mutate=None;self.reads=0;self.card_fault=None
 def invoke(self,p,url,**kw):
  if url=='/rest/open-metadata/v0/apis/{apiname}':
   api=kw['params']['apiname'];method='POST' if api.startswith('POST.') else 'GET';path=WRITE if method=='POST' else READ
   properties={'skuMaterials':{'type':'array','minItems':1,'maxItems':50,'items':{'type':'object'}}} if method=='POST' else {k:{'type':'array','items':{'type':'integer'}} for k in ('skuIds','materialTypes','scopeSet')}
   schema={'type':'object','required':list(properties),'properties':properties,'additionalProperties':False}
   if self.card_fault=='schema' and method=='POST':schema['properties']['skuMaterials']['maxItems']=0
   if self.card_fault=='unknown':schema['$ref']='#/unknown'
   return {'success':True,'data':{'apiName':api,'method':'DELETE' if self.card_fault=='method' else method,'path':'/wrong' if self.card_fault=='path' else path,'inputSchema':schema}}
  if url in (READ,WRITE):
   self.calls.append((url,copy.deepcopy(kw)))
   if url==WRITE:
    self.posts.append(copy.deepcopy(kw['body']))
    for row in kw['body']['skuMaterials']:
     sid=str(row['skuId']);values={(m['materialType'],m['order']):m for m in self.materials[sid]}
     for m in row['materials']:values[(m['materialType'],m['order'])]={**copy.deepcopy(m),'status':3}
     self.materials[sid]=list(values.values())
    if self.fault=='timeout':raise TimeoutError('synthetic secret-looking token must not be echoed')
    if self.fault=='partial':return {'success':True,'data':{'receipt':'synthetic'},'errorList':[{'message':'partial'}]}
    return {'success':True,'data':{'receipt':'synthetic-'+str(len(self.posts))}}
   self.reads+=1;params=kw['params'];ids=params['skuIds'];types=params['materialTypes']
   rows=[{'skuId':sid,'materials':[copy.deepcopy(m) for m in self.materials[str(sid)] if m['materialType'] in types]} for sid in reversed(ids)]
   if self.fault=='omitted':rows=rows[:-1]
   elif self.fault=='duplicate' and rows:rows.append(copy.deepcopy(rows[0]))
   elif self.fault=='foreign':rows[0]['skuId']=999
   if self.mutate:self.mutate(self,rows)
   return {'success':True,'data':rows}
  if url.endswith('/products/{productId}'):
   self.calls.append((url,copy.deepcopy(kw)));return {'data':{'productId':9,'skuList':copy.deepcopy(self.skus)}}
  if url.endswith('/skus'):
   self.calls.append((url,copy.deepcopy(kw)));q=kw['params'];rows=self.skus[(q['page']-1)*q['pageSize']:q['page']*q['pageSize']];return {'data':copy.deepcopy(rows),'paginationData':{'totalItems':len(self.skus)}}
  if url.endswith('/health-infos'):
   self.calls.append((url,copy.deepcopy(kw)));return {'data':[{'skuId':101,'healthScore':50,'improvementList':[]}],'paginationData':{'totalItems':1}}
  return super().invoke(p,url,**kw)

class SkuMaterialTests(unittest.TestCase):
 def make(self,d,count=3):
  from heideng_merchant.sku_materials import SkuMaterialService
  c=Client(count);s=SkuMaterialService(Path(d),c);s.ops.connect('merchant-test','synthetic-store','1');return c,s
 def text(self,sku=101):return {'skuId':sku,'slot':'point1','text':'轻巧便携','review':'passed'}
 def prepare(self,s,changes=None):return s.prepare('merchant-test',9,changes or [self.text()])
 def run_plan(self,s,plan):s.approve(plan['planId'],plan['fingerprint'],confirmed=True);return s.execute(plan['planId'])
 def upload(self,s,d):
  from heideng_merchant.materials import MaterialService
  path=Path(d)/'sample.png';path.write_bytes(png());t=MaterialService(d,s.client).prepare_upload('merchant-test',path,'img_test',7)['task'];s.ops.approve(t['taskId'],t['fingerprint'],confirmed=True);s.ops.execute(t['taskId']);s.ops.verify_result(t['taskId']);return t['taskId']
 def test_service_exists(self):self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.sku_materials'),'native SKU material service is missing')
 def test_full_census_gap_and_native_health_metric_without_zero_fill(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);report=s.audit('merchant-test',9,include_health=True);self.assertTrue(report['complete']);self.assertEqual(report['skuCount'],3);self.assertEqual(report['unscoredSkuIds'],['102','103']);self.assertIsNone(report['portalScoreEquivalent']);self.assertEqual(report['metricField'],'healthScore');self.assertFalse(c.posts)
 def test_material_response_must_cover_every_actual_sku(self):
  for fault in ('omitted','duplicate','foreign'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.fault=fault
    with self.assertRaises(SafetyError):self.prepare(s)
    self.assertFalse(c.posts)
 def test_plan_without_approval_never_dispatches(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s)
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)
 def test_known_receipt_and_complete_readback_preserve_other_type_order(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);result=self.run_plan(s,p);self.assertEqual(result['verifiedChunkCount'],1);self.assertEqual(len(c.posts),1);self.assertTrue(result['materialFieldsVerified']);self.assertFalse(result['auditApproved']);self.assertFalse(result['scoreRecalculated']);self.assertEqual(c.materials['101'][0]['order'],2)
 def test_resume_same_plan_and_tasks_without_new_posts(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);self.run_plan(s,p);again=self.prepare(s);self.assertEqual(again['planId'],p['planId']);s.execute(p['planId']);self.assertEqual(len(c.posts),1)
 def test_unknown_target_match_does_not_prove_original_or_allow_replay(self):
  for fault in ('timeout','partial'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);p=self.prepare(s);c.fault=fault;result=self.run_plan(s,p);self.assertTrue(result['originalOutcomeUnknown']);task=s.status(p['planId'],refresh=True)['chunks'][0];self.assertTrue(task['targetStateVerified']);self.assertEqual(task['status'],'unknown');s.execute(p['planId']);self.assertEqual(len(c.posts),1)
    with self.assertRaises(SafetyError):s.prepare('merchant-test',9,[self.text(102)])
 def test_whole_supported_scope_readback_detects_preserved_slot_loss_and_extra_order(self):
  for fault in ('missing','extra','changed'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);p=self.prepare(s);s.approve(p['planId'],p['fingerprint'],confirmed=True);tid=p['tasks'][0]['taskId'];s.ops.execute(tid)
    if fault=='missing':c.materials['101']=[m for m in c.materials['101'] if m['materialType']==1002]
    elif fault=='extra':c.materials['101'].append(material(101,32,1))
    else:c.materials['101'][0]['imageMaterial']['skuImages'][0]['imgUrl']='jfs/t1/changed.png'
    result=s.status(p['planId'],refresh=True);self.assertFalse(result['materialFieldsVerified']);self.assertEqual(result['chunks'][0]['status'],'submitted')
 def test_material_or_census_drift_after_approval_prevents_post(self):
  for fault in ('material','census','shop'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);p=self.prepare(s);s.approve(p['planId'],p['fingerprint'],confirmed=True)
    if fault=='material':c.materials['101'][0]['imageMaterial']['skuImages'][0]['imgUrl']='jfs/t1/changed.png'
    elif fault=='census':c.skus.append({'skuId':104,'productId':9,'status':103});c.materials['104']=[]
    else:c.foreign=True
    with self.assertRaises(SafetyError):s.execute(p['planId'])
    self.assertFalse(c.posts)
 def test_pending_rejected_approved_or_empty_existing_slot_never_overwritten(self):
  for status in (3,4,5,None):
   with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.materials['101'].append(material(101,1002,1,'旧卖点',status))
    with self.assertRaises(SafetyError):self.prepare(s)
    self.assertFalse(c.posts)
 def test_changes_require_valid_ids_unique_absent_slot_and_host_review(self):
  cases=[{'skuId':True,'slot':'point1','text':'轻巧便携','review':'passed'}, {'skuId':999,'slot':'point1','text':'轻巧便携','review':'passed'}, {'skuId':101,'slot':'point1','text':'轻巧便携'}, {'skuId':101,'slot':'point1','text':'123456789','review':'passed'}, {'skuId':101,'slot':'point1','text':'轻巧便携','review':'passed','imgUrl':'jfs/t1/fake.png'}, {'skuId':101,'slot':'video','text':'轻巧便携','review':'passed'}]
  for row in cases:
   with self.subTest(row=row),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d)
    with self.assertRaises(SafetyError):s.prepare('merchant-test',9,[row])
    self.assertFalse(c.posts)
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d)
   with self.assertRaises(SafetyError):s.prepare('merchant-test',9,[self.text(),self.text()])
 def test_image_requires_original_same_shop_upload_and_fresh_readback(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
   c,s=self.make(d);tid=self.upload(s,d);p=s.prepare('merchant-test',9,[{'skuId':101,'slot':'white','uploadTaskId':tid,'review':'passed'}]);self.run_plan(s,p);self.assertEqual(c.posts[0]['skuMaterials'][0]['materials'][0]['imageMaterial']['skuImages'][0]['imgUrl'],'jfs/t1/1/synthetic.png')
 def test_unknown_upload_or_modified_original_image_prevents_binding(self):
  for fault in ('unknown','url'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
    c,s=self.make(d);tid=self.upload(s,d)
    if fault=='url':c.images[0]['imgUrl']='jfs/t1/other.png'
    else:t=s.ops.task(tid);t['status']='unknown';atomic_json(s.ops._path(tid),t)
    with self.assertRaises(SafetyError):s.prepare('merchant-test',9,[{'skuId':101,'slot':'white','uploadTaskId':tid,'review':'passed'}])
    self.assertFalse(c.posts)
 def test_generic_entrypoint_cannot_bypass_source_proof_or_use_destructive_alias(self):
  for url,method in ((WRITE,'POST'),(READ,'DELETE'),(WRITE+'/', 'POST'),('/rest/sp-product/v0//sku-materials/batch','POST')):
   with self.subTest(url=url),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d)
    with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':url,'method':method,'skillId':'jdo-api-830','body':{'skuMaterials':[]}})
    self.assertFalse(c.posts)
 def test_generic_readback_cannot_clear_material_task(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);s.approve(p['planId'],p['fingerprint'],confirmed=True);t=s.ops.execute(p['tasks'][0]['taskId'])
   with self.assertRaises(SafetyError):s.ops.readback(t['taskId'],{'url':READ,'params':{},'skillId':'jdo-api-830'},{'skuId':101})
 def test_approval_expires_at_last_transport_boundary(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);s.approve(p['planId'],p['fingerprint'],confirmed=True,ttl_seconds=1)
   with patch('heideng_merchant.operations.time.time',return_value=10**12):
    with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)
 def test_1000_sku_20_chunks_one_approval_no_omission_or_replay(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d,1000);changes=[self.text(row['skuId']) for row in c.skus];p=s.prepare('merchant-test',9,changes);self.assertEqual(len(p['tasks']),20);r=self.run_plan(s,p);self.assertEqual(r['verifiedChunkCount'],20);self.assertEqual(sum(len(x['skuMaterials']) for x in c.posts),1000);s.execute(p['planId']);self.assertEqual(len(c.posts),20)
 def test_later_chunk_waits_for_first_unresolved_original(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d,51);p=s.prepare('merchant-test',9,[self.text(r['skuId']) for r in c.skus]);c.fault='timeout';r=self.run_plan(s,p);self.assertTrue(r['originalOutcomeUnknown']);self.assertEqual(len(c.posts),1);self.assertEqual(r['chunks'][1]['status'],'prepared')

 def test_plan_top_level_task_list_cannot_replace_approved_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);path=s._path(p['planId']);p['tasks']=[];atomic_json(path,p)
   with self.assertRaises(SafetyError):s.approve(p['planId'],p['fingerprint'],confirmed=True)
   self.assertFalse(c.posts)
 def test_product_census_requires_reported_total_not_inferred_short_page(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);original=c.invoke
   def invoke(p,url,**kw):
    result=original(p,url,**kw)
    if url.endswith('/skus'):result.pop('paginationData',None)
    return result
   c.invoke=invoke
   with self.assertRaises(SafetyError):self.prepare(s)
   self.assertFalse(c.posts)
 def test_small_native_material_write_uses_deadline_enforcing_stdin(self):
  from heideng_merchant.official_transport import transport_for
  op={'url':WRITE,'method':'POST','params':{},'body':{'skuMaterials':[]},'skillId':'jdo-api-830'}
  self.assertEqual(transport_for(Path('synthetic.exe'),'merchant-test',op),'official-source-stdin')
 def test_forged_body_cannot_be_rehashed_into_a_different_material_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);t=s.ops.task(p['tasks'][0]['taskId']);t['scope']['operation']['body']['skuMaterials'][0]['skuId']=102
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',t['scope']['operation'],sku_material_input=t['scope']['skuMaterialInput'])
   self.assertFalse(c.posts)
 def test_unknown_material_shape_or_duplicate_order_fails_before_write(self):
  for fault in ('indices','duplicate-slot','missing-array','text-object'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d)
    if fault=='indices':c.materials['101'][0]['imageMaterial']['skuImages'].append(copy.deepcopy(c.materials['101'][0]['imageMaterial']['skuImages'][0]))
    elif fault=='duplicate-slot':c.materials['101'].append(copy.deepcopy(c.materials['101'][0]))
    elif fault=='text-object':c.materials['101'].append({'skuId':101,'materialType':1002,'order':2,'textMaterial':{'contents':{}}})
    else:
     c.mutate=lambda client,rows:rows[0].pop('materials',None)
    with self.assertRaises(SafetyError):self.prepare(s)
    self.assertFalse(c.posts)

 def test_live_capability_method_path_and_unsupported_schema_fail_closed(self):
  for fault in ('method','path','unknown','schema'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.card_fault=fault
    with self.assertRaises(SafetyError):self.prepare(s)
    self.assertFalse(c.posts)
 def test_capability_schema_change_after_approval_stops_before_post(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);s.approve(p['planId'],p['fingerprint'],confirmed=True);c.card_fault='schema'
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)

 def test_parent_plan_change_description_must_exactly_cover_executable_chunks(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);a=self.prepare(s);b=self.prepare(s,[self.text(102)]);a['tasks']=b['tasks'];a['scope']['tasks']=b['tasks'];a['fingerprint']=digest(a['scope']);a['planId']=a['fingerprint'][:24];atomic_json(s._path(a['planId']),a)
   with self.assertRaises(SafetyError):s.approve(a['planId'],a['fingerprint'],confirmed=True)
   self.assertFalse(c.posts)
 def test_rehashed_upload_receipt_cannot_select_unrelated_image(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
   c,s=self.make(d);tid=self.upload(s,d);other=copy.deepcopy(c.images[0]);other.update(imgId='asset-unrelated',imgUrl='jfs/t1/1/unrelated.png');c.images.append(other);t=s.ops.task(tid);t['result']['data']=copy.deepcopy(other);t['resultReceiptSha256']=digest(t['result']);atomic_json(s.ops._path(tid),t)
   with self.assertRaises(SafetyError):s.prepare('merchant-test',9,[{'skuId':101,'slot':'white','uploadTaskId':tid,'review':'passed'}])
   self.assertFalse(c.posts)
 def test_generic_chunk_approval_cannot_substitute_for_parent_plan_approval(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);p=self.prepare(s);t=s.ops.task(p['tasks'][0]['taskId'])
   with self.assertRaises(SafetyError):s.ops.approve(t['taskId'],t['fingerprint'],confirmed=True)
   t['approval']={'confirmed':True,'fingerprint':t['fingerprint'],'expiresAt':10**12};atomic_json(s.ops._path(t['taskId']),t)
   with self.assertRaises(SafetyError):s.ops.execute(t['taskId'])
   self.assertFalse(c.posts)
 def test_remaining_chunk_approval_cannot_extend_original_plan_deadline(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d,51);p=s.prepare('merchant-test',9,[self.text(r['skuId']) for r in c.skus]);s.approve(p['planId'],p['fingerprint'],confirmed=True,ttl_seconds=60);first=p['tasks'][0]['taskId'];s.ops.execute(first);s.ops.verify_materials(first);last=s.ops.task(p['tasks'][1]['taskId']);deadline=last['approval']['expiresAt']
   with patch('heideng_merchant.operations.time.time',return_value=deadline+1):
    with self.assertRaises(SafetyError):s.ops.approve(last['taskId'],last['fingerprint'],confirmed=True,ttl_seconds=900)
    last['approval']['expiresAt']=deadline+900;atomic_json(s.ops._path(last['taskId']),last)
    with self.assertRaises(SafetyError):s.ops.execute(last['taskId'])
   self.assertEqual(len(c.posts),1)

if __name__=='__main__':unittest.main()
