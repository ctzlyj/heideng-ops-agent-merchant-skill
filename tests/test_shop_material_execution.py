import importlib.util,tempfile,unittest,copy,time
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from heideng_merchant import distribution
from tests.shop_material_execution_fixtures import Client,changes
class ShopMaterialExecutionTests(unittest.TestCase):
 def make(self,d,first=53,second=3):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.shop_material_execution'),'whole-shop approved execution missing')
  from heideng_merchant.shop_material_execution import ShopMaterialExecution
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  c=Client(first,second);s=ShopMaterialExecution(d,c);s.ops.connect('merchant-test','synthetic-store','1');a=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False)
  return c,s,a
 def prepare(self,c,s,a,slots=('point1',)):return s.prepare(a['auditId'],changes(c),target_slots=list(slots))
 def run_plan(self,s,p):s.approve(p['planId'],p['fingerprint'],confirmed=True);return s.execute(p['planId'])
 def test_complete_multishop_scope_not_health_subset_and_read_only_prepare(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=self.prepare(c,s,a);self.assertEqual(p['onSaleSkuCount'],56);self.assertEqual(p['offSaleSiblingCount'],2);self.assertEqual(p['productCount'],2);self.assertEqual(p['readyChangeCount'],56);self.assertEqual(p['chunkCount'],3);self.assertFalse(c.posts)
 def test_50_plus3_plus_other_product_are_preserved_with_one_root_approval(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);before=copy.deepcopy(c.materials);p=self.prepare(c,s,a);r=self.run_plan(s,p);self.assertEqual([len(v['skuMaterials']) for v in c.posts],[50,3,3]);self.assertTrue(r['allReadyChangesVerified']);self.assertFalse(r['auditApprovedForWrittenChanges']);self.assertFalse(r['scoreRecalculated'])
   self.assertEqual({row['productId'] for post in c.posts for row in post['skuMaterials']},{9,10});self.assertFalse(any(row['skuId'] in (9001,9002,301) for post in c.posts for row in post['skuMaterials']))
   for sku,original in before.items():
    for m in original:self.assertIn(m,c.materials[sku])
 def test_root_approval_cannot_be_replaced_by_manual_child_confirmation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=self.prepare(c,s,a);child=s.plan(p['planId'])['scope']['tasks'][0]
   with self.assertRaises(SafetyError):s.ops.approve(child['taskId'],child['fingerprint'],confirmed=True)
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)
 def test_default_all_slots_exposes_unready_materials_instead_of_silently_narrowing(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=s.prepare(a['auditId'],changes(c));self.assertGreater(p['awaitingMaterialCount'],0);r=self.run_plan(s,p);self.assertTrue(r['allReadyChangesVerified']);self.assertFalse(r['allTargetSlotsHaveContent']);self.assertGreater(r['awaitingMaterialCount'],0)
 def test_no_ready_materials_and_empty_shop_do_not_manufacture_work(self):
  for empty in (False,True):
   with self.subTest(empty=empty),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1)
    if empty:
     from heideng_merchant.shop_material_audit import ShopMaterialAudit
     for product in c.products:product['productStatus']=104
     a=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False)
    p=s.prepare(a['auditId'],[],target_slots=['point1']);self.assertEqual(p['chunkCount'],0);self.assertEqual(p['readyChangeCount'],0);self.assertEqual(p['noWorkInTargetScope'],empty)
    with self.assertRaises(SafetyError):s.approve(p['planId'],p['fingerprint'],confirmed=True)
    self.assertFalse(c.posts)
 def test_incomplete_inventory_or_material_source_is_not_executable(self):
  for fault in ('missing-total','omitted'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);c.fault=fault
    from heideng_merchant.shop_material_audit import ShopMaterialAudit
    bad=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False)
    with self.assertRaises(SafetyError):s.prepare(bad['auditId'],changes(c),target_slots=['point1'])
    self.assertFalse(c.posts)
 def test_offsale_foreign_product_and_existing_slots_are_rejected(self):
  for row in ({'productId':9,'skuId':9001,'slot':'point1','text':'轻巧便携','review':'passed'},{'productId':9,'skuId':1001,'slot':'point1','text':'轻巧便携','review':'passed'},{'productId':9,'skuId':101,'slot':'white','uploadTaskId':'a'*24,'review':'passed'}):
   with self.subTest(row=row),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[row])
    self.assertFalse(c.posts)
 def test_unknown_second_chunk_stops_tail_and_cannot_replay_from_readback(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);c.write_fault_on=2;r=s.execute(p['planId']);self.assertTrue(r['originalOutcomeUnknown']);self.assertEqual(len(c.posts),2);self.assertEqual(r['verifiedChunkCount'],1)
   c.write_fault_on=None;c.fault=None;r=s.status(p['planId'],refresh=True);self.assertTrue(r['originalOutcomeUnknown']);s.execute(p['planId']);self.assertEqual(len(c.posts),2);self.assertTrue(distribution.busy(Path(d)))
 def test_root_deadline_clips_children_and_cannot_extend_during_child_approval(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True,ttl_seconds=30);root=s.plan(p['planId']);deadline=root['approval']['expiresAt']
   for child in root['scope']['tasks']:
    t=s.ops.approve(child['taskId'],child['fingerprint'],confirmed=True,ttl_seconds=3600);self.assertLessEqual(t['approval']['expiresAt'],deadline)
   self.assertFalse(c.posts)
 def test_catalog_and_selected_sku_drift_stop_before_first_write(self):
  for drift in ('product','sku'):
   with self.subTest(drift=drift),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True)
    if drift=='product':c.products[0]['productStatus']=104
    else:c.skus[0]['status']=104
    with self.assertRaises(SafetyError):s.execute(p['planId'])
    self.assertFalse(c.posts)
 def test_wrong_shop_is_not_a_new_execution_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);c.foreign=True
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts)
 def test_source_audit_and_original_root_approval_cannot_be_lost(self):
  for missing in ('audit','approval'):
   with self.subTest(missing=missing),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);plan=s.plan(p['planId'])
    path=Path(d)/'shop-material-audits'/(a['auditId']+'.json') if missing=='audit' else Path(d)/'shop-material-approvals'/p['planId']/(plan['approvalId']+'.json');path.unlink()
    with self.assertRaises(SafetyError):s.execute(p['planId'])
    self.assertFalse(c.posts);self.assertTrue(distribution.busy(Path(d)))
 def test_known_partial_scope_can_resume_once_after_explicit_tail_renewal(self):
  with tempfile.TemporaryDirectory() as d:
   from tests.test_sku_materials import READ
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);root=s.plan(p['planId']);old=root['approvalId'];invoke=c.invoke
   def interrupted(profile,url,**kw):
    result=invoke(profile,url,**kw)
    if url==READ and len(c.posts)==1:c.products[1]['productStatus']=104
    return result
   c.invoke=interrupted
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertEqual(len(c.posts),1);self.assertEqual(s.status(p['planId'])['verifiedChunkCount'],1);c.products[1]['productStatus']=103;c.invoke=invoke
   s.approve(p['planId'],p['fingerprint'],confirmed=True);self.assertNotEqual(s.plan(p['planId'])['approvalId'],old);r=s.execute(p['planId']);self.assertTrue(r['allReadyChangesVerified']);self.assertEqual(len(c.posts),2);self.assertEqual(len(list((Path(d)/'shop-material-approvals'/p['planId']).glob('*.json'))),2)
 def test_journal_reset_or_receipt_loss_never_unlocks_unknown_or_replays(self):
  for loss in ('reset','receipt'):
   with self.subTest(loss=loss),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);first=s.plan(p['planId'])['scope']['tasks'][0]
    if loss=='reset':c.write_fault_on=1;s.execute(p['planId']);path=s.ops._path(first['taskId']);v=read_json(path);v['status']='prepared';v.pop('result',None);atomic_json(path,v)
    else:s.execute(p['planId']);(Path(d)/'shop-material-receipts'/(first['taskId']+'.json')).unlink()
    self.assertTrue(distribution.busy(Path(d)))
    try:s.execute(p['planId'])
    except SafetyError:pass
    self.assertEqual(len(c.posts),1 if loss=='reset' else 2)

 def test_existing_rejected_pending_or_unknown_content_is_not_no_work(self):
  from tests.test_sku_materials import material
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  for audit_status in (3,5,None):
   with self.subTest(audit_status=audit_status),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,1,1)
    for sku in (101,1001):c.materials[str(sku)].append(material(sku,1002,1,status=audit_status))
    a=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False);p=s.prepare(a['auditId'],[],target_slots=['point1']);self.assertFalse(p['noWorkInTargetScope']);self.assertTrue(p['allTargetSlotsHaveContent']);self.assertFalse(c.posts)
 def test_final_catalog_change_is_reported_without_relabeling_known_writes_unknown(self):
  from tests.test_sku_materials import WRITE
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);original=c.invoke
   def changed(profile,url,**kw):
    result=original(profile,url,**kw)
    if url==WRITE and len(c.posts)==2:c.products.append({'productId':30,'productName':'synthetic-new','productStatus':103})
    return result
   c.invoke=changed;r=s.execute(p['planId']);self.assertTrue(r['allReadyChangesVerified']);self.assertFalse(r['originalOutcomeUnknown']);self.assertFalse(r.get('currentCatalogScopeVerified',True));self.assertEqual(r.get('catalogObservationReason'),'changed-or-unavailable');self.assertEqual(len(c.posts),2)
 def test_additional_malformed_root_approval_cannot_be_ignored_before_writes(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);root=s.plan(p['planId'])
   atomic_json(Path(d)/'shop-material-approvals'/p['planId']/('a'*32+'.json'),{'planId':p['planId'],'fingerprint':p['fingerprint'],'shop':root['scope']['intent']['shop']})
   with self.assertRaises(SafetyError):s.execute(p['planId'])
   self.assertFalse(c.posts);self.assertTrue(distribution.busy(Path(d)))

 def test_agent_cli_runs_one_scope_and_pages_without_printing_every_id(self):
  from heideng_merchant import cli
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);recipe=Path(d)/'ready.json';atomic_json(recipe,changes(c))
   def command(name,*args):
    try:parsed=cli.parser().parse_args([name,*map(str,args)])
    except SystemExit:self.fail('whole-shop execution has no Agent CLI entry point')
    return cli.run(parsed)
   with patch.dict(__import__('os').environ,{'HEIDENG_MERCHANT_HOME':d}),patch('heideng_merchant.cli.OfficialClient',return_value=c):
    p=command('shop-material-plan','--audit-id',a['auditId'],'--changes',recipe,'--target-slots','point1');self.assertNotIn('scope',p);self.assertNotIn('tasks',p)
    with self.assertRaises(SafetyError):command('shop-material-approve','--plan-id',p['planId'],'--fingerprint',p['fingerprint'])
    command('shop-material-approve','--plan-id',p['planId'],'--fingerprint',p['fingerprint'],'--confirm');r=command('shop-material-execute','--plan-id',p['planId']);self.assertTrue(r['allReadyChangesVerified'])
    rows=command('shop-material-rows','--plan-id',p['planId'],'--page-size',2);self.assertEqual(rows['total'],3);self.assertEqual(len(rows['items']),2);self.assertEqual(rows['nextPage'],2)
    status=command('shop-material-status','--plan-id',p['planId']);self.assertTrue(status['summaryOnly']);self.assertFalse(status['currentCatalogScopeVerified'])

 def test_foreign_owner_claim_cannot_hide_a_same_shop_original_attempt(self):
  for owner in ({'profile':'merchant-other','venderId':'not-id','shopId':'22','shopName':'other'},{'profile':'merchant-other','venderId':'2','shopId':'22','shopName':'other'}):
   with self.subTest(owner=owner),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);first=s.plan(p['planId'])['scope']['tasks'][0];c.write_fault_on=1;s.execute(p['planId'])
    journal=s.ops._path(first['taskId']);task=read_json(journal);task['status']='prepared';atomic_json(journal,task);marker=Path(d)/'shop-material-attempts'/(first['taskId']+'.json');record=read_json(marker);record['shop']=owner;atomic_json(marker,record)
    with self.assertRaises(SafetyError):s.ops._assert_resolved(s.ops.shop('merchant-test'))
    self.assertEqual(len(c.posts),1)

 def test_late_added_sku_in_earlier_product_invalidates_current_whole_shop_scope(self):
  from tests.test_sku_materials import WRITE,material
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);original=c.invoke
   def changed(profile,url,**kw):
    result=original(profile,url,**kw)
    if url==WRITE and len(c.posts)==2:c.skus.append({'skuId':7001,'productId':9,'status':103,'skuName':'synthetic-new'});c.materials['7001']=[material(7001)]
    return result
   c.invoke=changed;r=s.execute(p['planId']);self.assertTrue(r['allReadyChangesVerified']);self.assertFalse(r['originalOutcomeUnknown']);self.assertFalse(r['currentCatalogScopeVerified']);self.assertEqual(r['catalogObservationReason'],'changed-or-unavailable');self.assertEqual(len(c.posts),2)

 def test_original_uploaded_image_can_be_reused_across_owned_products(self):
  from tests.test_sku_materials import SkuMaterialTests
  from tests.material_fixtures import probe
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):
   c,s,a=self.make(d,1,1);c.materials['101']=[];c.materials['1001']=[];a=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False)
   upload=SkuMaterialTests().upload(s,d);recipe=[{'productId':pid,'skuId':sku,'slot':'white','uploadTaskId':upload,'review':'passed'} for pid,sku in ((9,101),(10,1001))]
   p=s.prepare(a['auditId'],recipe,target_slots=['white']);r=self.run_plan(s,p);self.assertTrue(r['allReadyChangesVerified']);self.assertEqual(len(c.posts),2)
   self.assertEqual({m['imageMaterial']['skuImages'][0]['imgUrl'] for post in c.posts for row in post['skuMaterials'] for m in row['materials']},{'jfs/t1/1/synthetic.png'})

 def test_retained_attempt_or_root_cannot_lose_its_original_child_binding(self):
  from heideng_merchant.operations import digest
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  for fault in ('proof-removed','child-and-marker-removed'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);first=s.plan(p['planId'])['scope']['tasks'][0];c.write_fault_on=1;s.execute(p['planId']);journal=s.ops._path(first['taskId'])
    if fault=='proof-removed':v=read_json(journal);v['status']='prepared';v['scope'].pop('shopMaterialInput');v['fingerprint']=digest(v['scope']);atomic_json(journal,v)
    else:journal.unlink();(Path(d)/'shop-material-attempts'/(first['taskId']+'.json')).unlink()
    with self.assertRaises(SafetyError):s.ops._assert_resolved(s.ops.shop('merchant-test'))
    c.write_fault_on=None;c.fault=None;fresh=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False);recipe=[{**r,'slot':'point2','text':'柔软舒适'} for r in changes(c)]
    with self.assertRaises(SafetyError):s.prepare(fresh['auditId'],recipe,target_slots=['point2'])
    self.assertEqual(len(c.posts),1)
 def test_a_root_cannot_promise_different_changes_using_another_roots_children(self):
  from heideng_merchant.operations import digest
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);root=copy.deepcopy(s.plan(p['planId']))
   for row in root['scope']['intent']['changes']:row['text']='柔软舒适'
   ih=digest(root['scope']['intent']);root['scope']['intentHash']=ih;fp=digest(root['scope']);root.update(planId=fp[:24],fingerprint=fp)
   atomic_json(Path(d)/'shop-material-plans'/(root['planId']+'.json'),root);atomic_json(Path(d)/'shop-material-intents'/(ih[:24]+'.json'),{'planId':root['planId'],'intentHash':ih})
   with self.assertRaises(SafetyError):s.plan(root['planId'])
   self.assertTrue(distribution.busy(Path(d)));self.assertFalse(c.posts)
 def test_direct_child_dispatch_is_not_an_alternative_to_the_whole_shop_runner(self):
  for changed in (False,True):
   with self.subTest(changed=changed),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);first=s.plan(p['planId'])['scope']['tasks'][0]
    if changed:c.products.append({'productId':30,'productName':'synthetic-new','productStatus':103})
    with self.assertRaises(SafetyError):s.ops.execute(first['taskId'])
    self.assertFalse(c.posts)

 def test_lost_root_with_surviving_approval_intent_and_tail_still_blocks_new_writes(self):
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d,2,1);p=self.prepare(c,s,a);s.approve(p['planId'],p['fingerprint'],confirmed=True);root=s.plan(p['planId']);first=root['scope']['tasks'][0];c.write_fault_on=1;s.execute(p['planId'])
   s.ops._path(first['taskId']).unlink();(Path(d)/'shop-material-attempts'/(first['taskId']+'.json')).unlink();(Path(d)/'shop-material-plans'/(p['planId']+'.json')).unlink()
   self.assertTrue(list((Path(d)/'shop-material-approvals'/p['planId']).glob('*.json')));self.assertTrue(s.ops._path(root['scope']['tasks'][1]['taskId']).exists())
   with self.assertRaises(SafetyError):s.ops._assert_resolved(s.ops.shop('merchant-test'))
   c.write_fault_on=None;c.fault=None;fresh=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False);recipe=[{**r,'slot':'point2','text':'柔软舒适'} for r in changes(c)]
   with self.assertRaises(SafetyError):s.prepare(fresh['auditId'],recipe,target_slots=['point2'])
   self.assertEqual(len(c.posts),1);self.assertTrue(distribution.busy(Path(d)))
