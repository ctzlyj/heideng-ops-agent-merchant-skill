import copy,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.publish_support import PublishSupport
from heideng_merchant.publishing import PublishService
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from tests import publish_fixtures as f

class PublishingTests(unittest.TestCase):
 def make(self,d):
  c,ops,manifest,schema,specs,assets=f.setup(d);return c,ops,PublishService(Path(d),c),manifest,schema,specs,assets
 def plan(self,s,manifest,schema,specs,assets):return s.plan_validation(f.PROFILE,manifest,schema,specs,assets)
 def validate(self,ops,s,manifest,schema,specs,assets):
  task=self.plan(s,manifest,schema,specs,assets)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);return task['taskId']
 def test_context_resolves_real_third_level_brand_and_keeps_full_schema(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);ctx=PublishSupport(Path(d),c).context(f.PROFILE,f.CATEGORY,f.BRAND)
   self.assertEqual(ctx['thirdCategoryId'],1348);self.assertEqual(ctx['schema'],c.rules);self.assertEqual(ctx['brand']['brandId'],f.BRAND)
   self.assertFalse(any(url.endswith('/sale-attr-templates') for url,_ in c.calls))
   c.rules[-1]['childrenComponents'][-1]['childrenComponents'][0]['extra']['isStructure']=True
   ctx=PublishSupport(Path(d),c).context(f.PROFILE,f.CATEGORY,f.BRAND);self.assertEqual(ctx['saleAttributeTemplates'][0]['templateType'],'2')
 def test_full_sku_validation_and_submission_use_same_flat_body_with_separate_exact_approvals(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);plan=self.plan(s,m,p,sp,a);v=plan['task'];self.assertEqual(plan['skuCount'],3);self.assertEqual(plan['phase'],'validation-awaiting-approval')
   self.assertEqual(c.validation_posts,0);self.assertEqual(c.publish_posts,0)
   with self.assertRaises(SafetyError):ops.execute(v['taskId'])
   ops.approve(v['taskId'],v['fingerprint'],confirmed=True);done=ops.execute(v['taskId']);self.assertEqual(done['status'],'completed');self.assertEqual(s.validation_status(v['taskId'])['phase'],'validation-passed')
   pub=s.plan_publish(v['taskId'])['task'];self.assertEqual(pub['scope']['operation']['body'],v['scope']['operation']['body'])
   with self.assertRaises(SafetyError):ops.execute(pub['taskId'])
   ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True);ops.execute(pub['taskId']);status=s.status(pub['taskId'])
   self.assertEqual(status['receipt'],{'applyId':'300','productId':'400'});self.assertFalse(status['onlineEffective']);self.assertEqual(c.publish_posts,1)
   with self.assertRaises(SafetyError):ops.execute(pub['taskId'])
 def test_documented_empty_validation_success_is_not_missing_business_ack(self):
  for data in (None,{},[]):
   with self.subTest(data=data),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);c.validation_reply={'success':True,'data':data};vid=self.validate(ops,s,m,p,sp,a)
    self.assertEqual(s.validation_status(vid)['phase'],'validation-passed');self.assertIsNotNone(s.plan_publish(vid)['task'])
 def test_violations_ambiguous_reports_and_unknown_never_allow_publish(self):
  for mode in ('violation','ambiguous','failed','unknown'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d)
    if mode=='violation':c.validation_reply={'success':True,'data':{'wareKeeperDetectResultList':[{'reason':'synthetic rejection'}]}}
    elif mode=='ambiguous':c.validation_reply={'success':True,'data':{'unreviewedReport':['message']}}
    elif mode=='failed':c.validation_reply={'success':False,'data':{}}
    else:c.validation_unknown=True
    vid=self.validate(ops,s,m,p,sp,a)
    with self.assertRaises(SafetyError):s.plan_publish(vid)
    with self.assertRaises(SafetyError):ops.execute(vid)
    self.assertEqual(c.validation_posts,1);self.assertEqual(c.publish_posts,0)
 def test_last_sku_omission_price_stock_or_spec_drift_is_rejected_before_validation(self):
  for mode in ('missing','price','stock','spec','uuid','existing-sku'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);rows=p[-1]['value']
    if mode=='missing':rows.pop()
    elif mode=='price':rows[-1]['value'][2]['value']='31.00'
    elif mode=='stock':rows[-1]['value'][3]['value']=4
    elif mode=='spec':rows[-1]['value'][4]['value'][1]['properties'][0]['value']='wrong size'
    elif mode=='uuid':rows[-1]['value'][0]['value']=rows[0]['value'][0]['value']
    else:rows[-1]['value'].insert(0,{'componentCode':'SkuId','value':'123'})
    with self.assertRaises(SafetyError):self.plan(s,m,p,sp,a)
    self.assertEqual(c.validation_posts,0)
 def test_spec_mapping_must_cover_every_original_dimension(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);sp.pop('sale-prop-101')
   with self.assertRaises(SafetyError):self.plan(s,m,p,sp,a)
 def test_generic_full_post_cannot_bypass_validation_or_use_another_schema(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);v=self.plan(s,m,p,sp,a)['task'];operation={**v['scope']['operation'],'url':'/rest/sp-product/v0/product-applies'}
   with self.assertRaises(SafetyError):ops.prepare(f.PROFILE,operation)
   self.assertEqual(c.publish_posts,0)
 def test_template_brand_photo_and_original_material_changes_block_submit_before_post(self):
  for mode in ('template','brand','photo','material'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);vid=self.validate(ops,s,m,p,sp,a);pub=s.plan_publish(vid)['task'];ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True)
    if mode=='template':c.rules[0]['newRule']=True
    elif mode=='brand':c.brand_revoked=True
    elif mode=='photo':(m.parent/a[0]['localPath']).write_bytes(b'changed')
    else:c.images[0]['imgSize']+=17
    with self.assertRaises(SafetyError):ops.execute(pub['taskId'])
    self.assertEqual(c.publish_posts,0)
 def test_original_validation_receipt_hash_age_and_profile_are_bound(self):
  for mode in ('hash','age','profile'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);vid=self.validate(ops,s,m,p,sp,a);v=ops.task(vid)
    if mode=='hash':v['result']['data']={'changed':True};atomic_json(ops._path(vid),v)
    elif mode=='age':v['finishedAt']=time.time()-601;atomic_json(ops._path(vid),v)
    else:c.foreign=True
    with self.assertRaises(SafetyError):s.plan_publish(vid)
 def test_unknown_publication_is_not_replayed_or_reported_online(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);vid=self.validate(ops,s,m,p,sp,a);pub=s.plan_publish(vid)['task'];ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True);c.publish_unknown=True
   ops.execute(pub['taskId']);status=s.status(pub['taskId']);self.assertEqual(status['phase'],'unknown');self.assertIsNone(status['receipt']);self.assertFalse(status['onlineEffective'])
   with self.assertRaises(SafetyError):ops.execute(pub['taskId'])
   self.assertEqual(c.publish_posts,1)

 def test_known_publication_cannot_be_duplicated_with_a_new_validation_nonce(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);vid=self.validate(ops,s,m,p,sp,a);first=s.plan_publish(vid)['task'];ops.approve(first['taskId'],first['fingerprint'],confirmed=True);ops.execute(first['taskId'])
   newer=self.validate(ops,s,m,p,sp,a);again=s.plan_publish(newer)['task'];self.assertEqual(again['taskId'],first['taskId'])
   with self.assertRaises(SafetyError):ops.execute(again['taskId'])
   self.assertEqual(c.publish_posts,1)
 def test_unstarted_old_publication_is_superseded_by_a_new_validated_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);v1=self.validate(ops,s,m,p,sp,a);old=s.plan_publish(v1)['task'];ops.approve(old['taskId'],old['fingerprint'],confirmed=True)
   v2=self.validate(ops,s,m,p,sp,a);new=s.plan_publish(v2)['task'];self.assertNotEqual(old['taskId'],new['taskId'])
   with self.assertRaises(SafetyError):ops.execute(old['taskId'])
   self.assertEqual(ops.task(old['taskId'])['status'],'superseded');self.assertEqual(c.publish_posts,0)
 def test_fresh_known_upload_can_be_used_without_nested_task_locks(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);asset=ops.task(a[0]['taskId']);asset['status']='submitted';atomic_json(ops._path(asset['taskId']),asset)
   vid=self.validate(ops,s,m,p,sp,a);self.assertEqual(s.validation_status(vid)['phase'],'validation-passed')
 def test_unsafe_submit_response_is_not_stored_or_exposed(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);vid=self.validate(ops,s,m,p,sp,a);task=s.plan_publish(vid)['task'];original=c.invoke
   def unsafe(profile,url,**kw):
    response=original(profile,url,**kw)
    if url=='/rest/sp-product/v0/product-applies':response['data']['properties']=[{'key':'apiKey','value':'synthetic-only-do-not-store'}]
    return response
   c.invoke=unsafe;ops.approve(task['taskId'],task['fingerprint'],confirmed=True);done=ops.execute(task['taskId'])
   self.assertEqual(done['status'],'unknown');self.assertNotIn('synthetic-only-do-not-store',str(done));self.assertEqual(c.publish_posts,1)
 def test_contradictory_validation_false_flag_cannot_be_ignored(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);c.validation_reply={'success':True,'validationPassed':False,'data':{}};vid=self.validate(ops,s,m,p,sp,a)
   with self.assertRaises(SafetyError):s.plan_publish(vid)
 def test_explicit_shipping_ids_are_not_silently_omitted_or_changed(self):
  for mode in ('missing','different'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d)
    if mode=='missing':p=[r for r in p if r['componentCode']!='WareTransport']
    else:next(r for r in p if r['componentCode']=='WareTransport')['value']='13'
    with self.assertRaises(SafetyError):self.plan(s,m,p,sp,a)
 def test_cli_exposes_full_native_publication_phases(self):
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d:
   state=Path(d)/'.heideng-merchant';c,ops,s,m,p,sp,a=self.make(state);schema=Path(d)/'schema.json';specs=Path(d)/'specs.json';assets=Path(d)/'assets.json'
   for path,value in ((schema,p),(specs,sp),(assets,a)):atomic_json(path,value)
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    args=parser().parse_args(['--home',d,'publish-validation-plan','--profile',f.PROFILE,'--manifest',str(m),'--schema',str(schema),'--spec-map',str(specs),'--asset-bindings',str(assets)])
    v=run(args)['task'];ops.approve(v['taskId'],v['fingerprint'],confirmed=True);ops.execute(v['taskId'])
    pub=run(parser().parse_args(['--home',d,'publish-plan','--validation-task-id',v['taskId']]))['task'];self.assertEqual(pub['scope']['operation']['url'],'/rest/sp-product/v0/product-applies')

 def test_lookup_commands_do_not_require_merchant_to_invent_brand_or_category_ids(self):
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d:
   state=Path(d)/'.heideng-merchant';c,ops,s,m,p,sp,a=self.make(state)
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    cats=run(parser().parse_args(['--home',d,'publish-categories','--profile',f.PROFILE]));self.assertTrue(any(r['categoryId']==f.CATEGORY for r in cats['items']))
    brands=run(parser().parse_args(['--home',d,'publish-brands','--profile',f.PROFILE,'--category-id',str(f.CATEGORY)]));self.assertEqual(brands['items'][0]['brandId'],f.BRAND);self.assertTrue(brands['complete'])
