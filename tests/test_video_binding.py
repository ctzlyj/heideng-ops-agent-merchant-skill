import importlib.util,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
from tests import test_video_delivery as delivery_tests
from tests.video_binding_fixtures import Client
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from heideng_merchant.operations import digest
class VideoBindingTests(unittest.TestCase):
 def make(self,d,count=3):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.video_binding'),'native type42 binding is missing')
  from heideng_merchant.video_binding import VideoBindingService
  helper=delivery_tests.VideoDeliveryTests();root,manifest,old,delivery=helper.make(d);client=Client(count);delivery.client=client;delivery.ops.client=client;delivery.transfer=client.transfer
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=helper.probe):
   upload=delivery.prepare('merchant-test',manifest,'video-owned');delivery.approve(upload['sessionId'],upload['fingerprint'],confirmed=True);delivery.execute(upload['sessionId'])
  service=VideoBindingService(root/'state',client)
  return root,manifest,client,service,upload['sessionId']
 def ready(self,s,session):
  helper=delivery_tests.VideoDeliveryTests()
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=helper.probe):
   context=s.preview('merchant-test',9,session)
   review={**context['identityReviewScope'],'passed':True}
   return s.prepare('merchant-test',9,session,review=review)
 def run_plan(self,s,plan):
  s.approve(plan['planId'],plan['fingerprint'],confirmed=True)
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):return s.execute(plan['planId'])
 def test_plan_is_read_only_and_exact_parent_approval_required(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session)
   self.assertFalse(c.posts);self.assertEqual(plan['skuCount'],3)
   with self.assertRaises(SafetyError):s.execute(plan['planId'])
   with self.assertRaises(SafetyError):s.approve(plan['planId'],'0'*64,confirmed=True)
   self.assertFalse(c.posts)
 def test_53_skus_use_50_plus_3_and_preserve_every_existing_order(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d,53)
   for sku in c.materials:
    c.materials[sku].append({'skuId':int(sku),'materialType':42,'order':2,'status':4,'videoMaterial':{'videoFrom':1,'videoId':800,'jdVideoId':801,'indexImage':'jfs/synthetic/old.png','title':'old','duration':1,'tagId':18,'tagOrder':3,'tagName':'other','retainedExtension':'keep'}})
   before=copy.deepcopy(c.materials);plan=self.ready(s,session);result=self.run_plan(s,plan)
   self.assertEqual([len(p['skuMaterials']) for p in c.posts],[50,3]);self.assertTrue(result['materialFieldsVerified']);self.assertTrue(result['relationsVerified']);self.assertFalse(result['auditApproved']);self.assertFalse(result['scoreRecalculated'])
   for sku,rows in before.items():
    for row in rows:self.assertIn(row,c.materials[sku])
   self.assertIn(2,c.relation_pages)
   for rows in c.materials.values():
    target=next(m for m in rows if m['materialType']==42 and m['order']==1);self.assertEqual(target['videoMaterial']['videoId'],700);self.assertEqual(target['videoMaterial']['jdVideoId'],900);self.assertEqual(target['videoMaterial']['tagId'],17)
 def test_unknown_matching_readback_never_unlocks_or_reposts(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d,53);plan=self.ready(s,session);c.binding_fault='timeout';result=self.run_plan(s,plan);self.assertTrue(result['originalOutcomeUnknown']);self.assertEqual(len(c.posts),1)
   c.binding_fault=None;result=s.status(plan['planId'],refresh=True);self.assertTrue(result['originalOutcomeUnknown']);self.assertFalse(result['materialFieldsVerified']);s.execute(plan['planId']);self.assertEqual(len(c.posts),1)
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':'/rest/sp-product/v0/products','method':'POST','body':{'synthetic':True}})
 def test_source_and_product_identity_review_cannot_be_substituted(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):
    context=s.preview('merchant-test',9,session);review={**context['identityReviewScope'],'passed':True,'videoSha256':'0'*64}
    with self.assertRaises(SafetyError):s.prepare('merchant-test',9,session,review=review)
    c.fault='readback-id'
    with self.assertRaises(SafetyError):s.preview('merchant-test',9,session)
   self.assertFalse(c.posts)

class VideoBindingSafetyTests(unittest.TestCase):
 make=VideoBindingTests.make
 ready=VideoBindingTests.ready
 run_plan=VideoBindingTests.run_plan
 def test_product_review_requires_literal_boolean_true(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):
    preview=s.preview('merchant-test',9,session);review={**preview['identityReviewScope'],'passed':1}
    with self.assertRaises(SafetyError):s.prepare('merchant-test',9,session,review=review)
   self.assertFalse(c.posts)
 def test_missing_audit_status_is_unknown_not_pending_or_approved(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);self.run_plan(s,plan)
   for values in c.materials.values():
    for row in values:
     if row['materialType']==42 and row['order']==1:row['status']=None
   c.relation_status_override={sku:3 for sku in c.materials}
   result=s.status(plan['planId'],refresh=True);self.assertEqual(result['auditState'],'unknown');self.assertFalse(result['auditApproved']);self.assertFalse(result['originalOutcomeUnknown'])
 def test_expiry_during_submitting_journal_does_not_dispatch_native_binding(self):
  import time
  from heideng_merchant import operations
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);s.approve(plan['planId'],plan['fingerprint'],confirmed=True);clock=[time.time()];original=operations.atomic_json
   def save(p,value):
    original(p,value)
    if value.get('status')=='submitting' and 'videoMaterialInput' in value.get('scope',{}):clock[0]+=10000
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe),patch('heideng_merchant.operations.atomic_json',side_effect=save),patch('heideng_merchant.operations.time.time',side_effect=lambda:clock[0]):
    try:s.execute(plan['planId'])
    except SafetyError:pass
   self.assertEqual(c.posts,[],'no native POST may start after persisted approval expires')
 def test_complete_material_and_relation_audit_requires_video_audit_too(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);self.run_plan(s,plan)
   for values in c.materials.values():
    for row in values:
     if row['materialType']==42 and row['order']==1:row['status']=4
   self.assertFalse(s.status(plan['planId'],refresh=True)['auditApproved']);c.video['status']=4;result=s.status(plan['planId'],refresh=True);self.assertTrue(result['auditApproved']);self.assertEqual(result['auditState'],'approved');self.assertFalse(s.status(plan['planId'])['auditApproved'])
 def test_lost_original_attempt_and_rewound_journal_never_reposts(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);self.run_plan(s,plan);task_id=plan['chunks'][0]['taskId'];journal=s.ops._path(task_id);data=read_json(journal);data['status']='prepared';atomic_json(journal,data);(root/'state/video-binding-attempts'/(task_id+'.json')).unlink()
   with self.assertRaises(SafetyError):s.ops.execute(task_id)
   self.assertEqual(len(c.posts),1)
 def test_missing_task_journal_with_original_evidence_blocks_same_shop_write(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);c.binding_fault='timeout';self.run_plan(s,plan);task_id=plan['chunks'][0]['taskId'];s.ops._path(task_id).unlink()
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':'/rest/sp-product/v0/products','method':'POST','body':{'synthetic':True}})
 def test_bad_relation_pagination_does_not_submit_next_chunk_and_can_read_then_continue(self):
  for fault in ('relation-duplicate','relation-total','relation-missing'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    root,m,c,s,session=self.make(d,53);plan=self.ready(s,session);c.binding_fault=fault
    with self.assertRaises(SafetyError):self.run_plan(s,plan)
    self.assertEqual(len(c.posts),1);c.binding_fault=None
    with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):result=s.execute(plan['planId'])
    self.assertEqual(len(c.posts),2);self.assertTrue(result['materialFieldsVerified'])
 def test_actual_tag_unavailable_or_duplicate_refuses_before_write(self):
  for tags in ([],[{'tagId':17,'sort':2,'tagName':'other'}],[{'tagId':17,'sort':2,'tagName':'产品展示'},{'tagId':18,'sort':3,'tagName':'产品展示'}]):
   with self.subTest(tags=tags),tempfile.TemporaryDirectory() as d:
    root,m,c,s,session=self.make(d);c.tags=tags
    with self.assertRaises(SafetyError):self.ready(s,session)
    self.assertFalse(c.posts)

class VideoBindingCliTests(unittest.TestCase):
 make=VideoBindingTests.make
 def test_agent_cli_completes_preview_review_parent_approval_and_binding_without_provider(self):
  import io,contextlib
  from heideng_merchant import cli
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d)
   def command(*args):
    with contextlib.redirect_stderr(io.StringIO()):
     try:parsed=cli.parser().parse_args(list(map(str,args)))
     except SystemExit:self.fail('Agent native video-binding CLI route is missing')
    return cli.run(parsed)
   with patch('heideng_merchant.cli.merchant_home',return_value=root/'state'),patch('heideng_merchant.cli.OfficialClient',return_value=c),patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):
    preview=command('video-binding-preview','--profile','merchant-test','--product-id',9,'--session-id',session);review=root/'identity-review.json';atomic_json(review,{**preview['identityReviewScope'],'passed':True})
    plan=command('video-binding-plan','--profile','merchant-test','--product-id',9,'--session-id',session,'--review',review)
    with self.assertRaises(SafetyError):command('video-binding-execute','--plan-id',plan['planId'])
    command('video-binding-approve','--plan-id',plan['planId'],'--fingerprint',plan['fingerprint'],'--confirm');result=command('video-binding-execute','--plan-id',plan['planId']);self.assertTrue(result['materialFieldsVerified']);self.assertFalse(result['auditApproved']);self.assertEqual(len(c.posts),1)
    self.assertFalse(command('video-binding-status','--plan-id',plan['planId'])['materialFieldsVerified']);self.assertTrue(command('video-binding-status','--plan-id',plan['planId'],'--refresh')['relationsVerified'])

class VideoBindingReviewRegressions(unittest.TestCase):
 make=VideoBindingTests.make
 ready=VideoBindingTests.ready
 run_plan=VideoBindingTests.run_plan
 def test_missing_original_upload_approval_cannot_authorize_binding(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);journal=root/'state/video-sessions'/(session+'.json');data=read_json(journal);aid=data['approvalId'];data.pop('approval');atomic_json(journal,data);(root/'state/video-session-approvals'/session/(aid+'.json')).unlink()
   with self.assertRaises(SafetyError):self.ready(s,session)
   self.assertFalse(c.posts)
 def test_missing_relation_status_blocks_promotion_and_next_chunk(self):
  from tests.video_binding_fixtures import RELS
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d,53);plan=self.ready(s,session);original=c.invoke
   def invoke(p,url,**kw):
    result=original(p,url,**kw)
    if url==RELS:
     for row in result['data']:row.pop('relationStatus',None)
    return result
   with patch.object(c,'invoke',side_effect=invoke),self.assertRaises(SafetyError):self.run_plan(s,plan)
   self.assertEqual(len(c.posts),1);self.assertEqual(s.ops.task(plan['chunks'][0]['taskId'])['status'],'submitted')
 def test_non_target_audit_progress_does_not_revoke_content_verification(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d)
   for values in c.materials.values():values[0]['status']=3
   plan=self.ready(s,session);self.run_plan(s,plan)
   for values in c.materials.values():values[0]['status']=4
   result=s.status(plan['planId'],refresh=True);self.assertTrue(result['materialFieldsVerified']);self.assertEqual(result['verifiedChunkCount'],1)
 def test_read_only_rejection_is_reported_but_new_binding_cannot_start(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d);plan=self.ready(s,session);self.run_plan(s,plan);c.video['status']=5
   result=s.status(plan['planId'],refresh=True);self.assertEqual(result['auditState'],'rejected');self.assertFalse(result['auditApproved']);self.assertEqual(len(c.posts),1)
   with self.assertRaises(SafetyError):self.ready(s,session)

class VideoBindingAuditReportTests(unittest.TestCase):
 make=VideoBindingTests.make
 ready=VideoBindingTests.ready
 run_plan=VideoBindingTests.run_plan
 def test_separate_audit_domains_and_non_target_progress_are_reported(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,session=self.make(d)
   for values in c.materials.values():values[0]['status']=3
   plan=self.ready(s,session);result=self.run_plan(s,plan);self.assertEqual(result['videoAuditStatus'],2);self.assertEqual(set(result['materialAuditStatuses'].values()),{3});self.assertEqual(set(result['relationAuditStatuses'].values()),{3});self.assertFalse(result['nonTargetAuditChanged'])
   for values in c.materials.values():
    for row in values:row['status']=4
   result=s.status(plan['planId'],refresh=True);self.assertTrue(result['materialFieldsVerified']);self.assertTrue(result['nonTargetAuditChanged']);self.assertEqual(set(result['materialAuditStatuses'].values()),{4});self.assertEqual(set(result['relationAuditStatuses'].values()),{4});self.assertEqual(result['videoAuditStatus'],2);self.assertFalse(result['auditApproved'])
