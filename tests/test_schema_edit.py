import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.schema_edit import EditService
from heideng_merchant.materials import MaterialService
from heideng_merchant.publication_contract import VALIDATE,PUBLISH
from heideng_merchant.safety import SafetyError,atomic_json
from tests import edit_fixtures as f
from tests import material_fixtures as media

class EditTests(unittest.TestCase):
 def make(self,d,count=3):
  c,ops,cap,b,a=f.setup(d,count);return c,ops,EditService(d,c),cap,b,a
 def asset(self,d,c,ops):
  path=Path(d)/'edit.png';path.write_bytes(media.png())
  with patch('heideng_merchant.materials.probe_image',side_effect=media.probe),patch('heideng_merchant.operations.probe_image',side_effect=media.probe):
   task=MaterialService(d,c).prepare_upload('merchant-test',path,'img_test',7)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);MaterialService(d,c).upload_status(task['taskId'],refresh=True)
  return task['taskId']
 def baseline(self,s,cap,b,a):return s.baseline(cap['captureId'],cap['scope']['schema'],b,a)
 def fake_posts(self,c):
  original=c.invoke;c.edit_posts=0;c.validation_posts=0;c.validation_reply={'success':True,'data':{}}
  def invoke(profile,url,**kw):
   if url in (VALIDATE,PUBLISH):
    self.assertTrue(kw['write_authorized']);self.assertEqual(kw['body']['productApplyDTO'],{'productId':100,'categoryDTO':{'lastCategoryId':456}})
    if url==VALIDATE:c.validation_posts+=1;return copy.deepcopy(c.validation_reply)
    c.edit_posts+=1;c.last_edit=copy.deepcopy(kw['body']);return {'success':True,'data':{'applyId':500,'productId':100}}
   if url=='/rest/sp-product/v0/product-apply/{applyId}':
    self.assertEqual(kw['params']['applyId'],500);return {'success':True,'data':{'applyId':500,**copy.deepcopy(c.pending)}}
   return original(profile,url,**kw)
  c.invoke=invoke
 def validation(self,ops,s,baseline,changes):
  task=s.plan_validation(baseline['baselineId'],changes)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);return task['taskId']
 def test_baseline_proves_real_ids_every_value_and_retains_full_source(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);base=self.baseline(s,cap,b,a)
   self.assertTrue(base['skuIdentityMappingVerified']);self.assertEqual(base['skuCount'],3);self.assertEqual(cap['scope']['productDetail'],c.product);self.assertEqual(base['schema'][-1]['value'],c.product['future']);self.assertNotIn('label',base['schema'][0])
 def test_baseline_missing_last_value_unknown_control_or_forged_uuid_refused(self):
  for mode in ('binding','control','sku','uuid','stock','outerId','sales'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,cap,b,a=self.make(d);schema=copy.deepcopy(cap['scope']['schema'])
    if mode=='binding':b.pop()
    elif mode=='control':schema.pop()
    elif mode=='sku':schema[2]['value'].pop()
    elif mode=='uuid':schema[2]['value'][-1]['value'][1]['value']='random-uuid'
    elif mode=='stock':schema[2]['value'][-1]['value'][4]['value']=999
    elif mode=='outerId':next(x for x in b if x['schemaPointer']=='/2/value/0/value/2/value')['sourcePointer']='/skuId'
    else:a[-1]['sourcePointer']='/priceInfo'
    with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)
 def test_full_edit_two_approvals_preserves_every_unedited_leaf(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);changes=[{'pointer':t['pointer'],'assetTaskId':asset} for t in cap['imageTargets']];plan=s.plan_validation(base['baselineId'],changes);v=plan['task']
   with self.assertRaises(SafetyError):ops.execute(v['taskId'])
   ops.approve(v['taskId'],v['fingerprint'],confirmed=True);ops.execute(v['taskId']);edit=s.plan_edit(v['taskId'])['task']
   self.assertEqual(v['scope']['operation']['body'],edit['scope']['operation']['body']);self.assertEqual(c.edit_posts,0)
   with self.assertRaises(SafetyError):ops.execute(edit['taskId'])
   ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);self.assertEqual(c.edit_posts,1);self.assertFalse(s.status(edit['taskId'])['onlineEffective'])
   sent=json.loads(c.last_edit['schema']);self.assertEqual(sent[-1],base['schema'][-1]);self.assertEqual(len(sent[2]['value']),3)
   with self.assertRaises(SafetyError):ops.execute(edit['taskId'])
 def test_unknown_and_validation_rejection_do_not_replay(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);c.validation_reply={'success':True,'otherReport':['rejected'],'data':{}};v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
   with self.assertRaises(SafetyError):s.plan_edit(v)
   self.assertEqual(c.edit_posts,0)
 def test_pending_and_online_are_full_field_reads_not_receipt_success(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);c.pending=copy.deepcopy(c.product);c.pending['material']['mainImages'][0]['imgUrl']='jfs/t1/1/synthetic.png'
   status=s.status(edit['taskId'],refresh=True);self.assertTrue(status['pendingFieldsVerified']);self.assertFalse(status['onlineEffective'])
   c.product=copy.deepcopy(c.pending);c.product['skuList'].reverse();self.assertTrue(s.verify_online(edit['taskId'])['onlineEffective'])
   c.product['skuList'][-1]['stockNum']=999;self.assertFalse(s.verify_online(edit['taskId'])['onlineEffective'])

 def test_known_pending_full_edit_blocks_another_write_until_original_readback(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId'])
   second=self.baseline(s,cap,b,a)
   with self.assertRaises(SafetyError):s.plan_validation(second['baselineId'],[{'pointer':t['pointer'],'assetTaskId':asset} for t in cap['imageTargets']])
 def test_readback_cannot_certify_foreign_parent_for_last_sku(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);c.pending=copy.deepcopy(c.product);c.pending['material']['mainImages'][0]['imgUrl']='jfs/t1/1/synthetic.png';c.pending['skuList'][-1]['productId']=999
   self.assertFalse(s.status(edit['taskId'],refresh=True)['pendingFieldsVerified'])
 def test_color_classification_comes_from_template_children_not_filled_dto(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d)
   for row in c.schema[2]['value']:row['value'][5]['value'][0].pop('extra')
   c.schema[2]['childrenComponents']=[{'componentCode':'VenderCategoryValue','childrenComponents':[{'componentCode':'sale-prop-100','extra':{'isColor':True,'dim':1}}]}]
   cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');self.assertTrue(self.baseline(s,cap,b,a)['skuIdentityMappingVerified'])
 def test_ambiguous_original_unknown_property_keys_refused(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.schema[1]['value'][0]['properties'].append(copy.deepcopy(c.schema[1]['value'][0]['properties'][-1]));b.append({'schemaPointer':'/1/value/0/properties/5/value','sourcePointer':'/material/mainImages/0/future','skuId':None,'conversion':'identity'});cap=ProductSchemaService(d,c).capture_edit('merchant-test','100')
   with self.assertRaises(SafetyError):self.baseline(s,cap,b,a)

 def test_baseline_cannot_reset_title_using_an_unrelated_original_field(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);schema=copy.deepcopy(cap['scope']['schema']);schema[0]['value']=c.product['desc'];b[0]['sourcePointer']='/desc'
   with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)
 def test_baseline_cannot_reset_unknown_control_from_unrelated_source_blob(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['otherData']={'opaque':[99]};cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');schema=copy.deepcopy(cap['scope']['schema']);schema[-1]['value']=c.product['otherData'];next(x for x in b if x['schemaPointer']=='/4/value')['sourcePointer']='/otherData'
   with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)

 def test_unrecognized_outside_dto_business_fields_are_not_silently_dropped(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.schema[-1]['futureBusinessValue']={'mustKeep':7};cap=ProductSchemaService(d,c).capture_edit('merchant-test','100')
   with self.assertRaises(SafetyError):self.baseline(s,cap,b,a)
 def test_mapping_fallback_and_single_sku_without_invented_dimensions(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d,1);row=c.product['skuList'][0];row['saleAttrs'][0]['mappingId']='';mid=row['saleAttrs'][0]['attrValues'];row['image']['colorId']=mid;row['image']['imgRefId']=mid;c.schema[2]['value'][0]['value'][5]['value'][0]['properties'][1]['value']=mid
   for prop in c.schema[2]['value'][0]['value'][6]['value'][0]['properties'][:2]:prop['value']=mid
   next(x for x in b if x['schemaPointer']=='/2/value/0/value/5/value/0/properties/1/value')['sourcePointer']='/saleAttrs/0/attrValues';cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');self.assertTrue(self.baseline(s,cap,b,a)['skuIdentityMappingVerified'])
 def test_safe_detail_edit_and_unsafe_comment_refused(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);html='<div>New detail<img src="https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png"></div>';changes=[{'pointer':'/3/value/0/properties/0/value','html':html,'assetTaskIds':[asset]}];v=self.validation(ops,s,base,changes);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);sent=json.loads(c.last_edit['schema']);self.assertEqual(sent[3]['value'][0]['properties'][0]['value'],html);self.assertEqual(sent[2],base['schema'][2])
   with self.assertRaises(SafetyError):s.plan_validation(base['baselineId'],[{'pointer':'/3/value/0/properties/0/value','html':'<!--><script>synthetic</script>-->','assetTaskIds':[]}])
 def test_unknown_original_edit_is_never_replayed_or_resolved_by_target_match(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}]);edit=s.plan_edit(v)['task'];original=c.invoke
   def lost(profile,url,**kw):
    result=original(profile,url,**kw)
    if url==PUBLISH:raise TimeoutError('synthetic accepted edit reply lost')
    return result
   c.invoke=lost;ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);self.assertEqual(ops.execute(edit['taskId'])['status'],'unknown');self.assertEqual(s.status(edit['taskId'],refresh=True)['phase'],'unknown')
   with self.assertRaises(SafetyError):ops.execute(edit['taskId'])
   with self.assertRaises(SafetyError):s.verify_online(edit['taskId'])
   self.assertEqual(c.edit_posts,1)
 def test_edit_validation_deadline_rechecked_after_slow_transport_planning(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);asset=self.asset(d,c,ops);c.plan_execution=lambda *args,**kw:{'transport':'official-source-stdin'};base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);clock=[ops.task(v)['finishedAt']+590]
   def slow(op,**kw):
    if op['url']==PUBLISH:clock[0]+=15
    return {'transport':'official-source-stdin'}
   c.plan_execution=slow
   with patch('time.time',side_effect=lambda:clock[0]):
    with self.assertRaises(SafetyError):ops.execute(edit['taskId'])
   self.assertEqual(c.edit_posts,0)
 def test_cli_runs_source_baseline_and_full_edit_stages(self):
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d:
   state=Path(d)/'.heideng-merchant';state.mkdir();c,ops,s,cap,b,a=self.make(state);self.fake_posts(c);files=[]
   for name,data in (('schema',cap['scope']['schema']),('bindings',b),('sales',a)):
    path=Path(d)/(name+'.json');atomic_json(path,data);files.append(str(path))
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    result=run(parser().parse_args(['--home',d,'schema-edit-baseline','--capture-id',cap['captureId'],'--schema',files[0],'--bindings',files[1],'--sale-sources',files[2]]));self.assertEqual(result['skuCount'],3)

 def test_review_critical_outer_id_html_conversion_is_refused(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['skuList'][0]['outerId']='A&B';c.schema[2]['value'][0]['value'][2]['value']='A&B';cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');schema=copy.deepcopy(cap['scope']['schema']);schema[2]['value'][0]['value'][2]['value']='A&amp;B';next(x for x in b if x['schemaPointer']=='/2/value/0/value/2/value')['conversion']='html'
   with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)
 def test_review_pending_and_online_revalidate_attribute_identity(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);base=self.baseline(s,cap,b,a);html='<div>New</div>';v=self.validation(ops,s,base,[{'pointer':'/3/value/0/properties/0/value','html':html,'assetTaskIds':[]}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);c.pending=copy.deepcopy(c.product);c.pending['desc']=html;c.pending['skuList'][-1]['saleAttrs'][0]['attrId']=999
   self.assertFalse(s.status(edit['taskId'],refresh=True)['pendingFieldsVerified']);c.product=copy.deepcopy(c.pending);self.assertFalse(s.verify_online(edit['taskId'])['onlineEffective'])
 def test_review_readback_recomputes_mapping_not_stale_fallback_pointer(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d,1);self.fake_posts(c);c.product['skuList'][0]['saleAttrs'][0]['mappingId']='';fallback=c.product['skuList'][0]['saleAttrs'][0]['attrValues'];c.product['skuList'][0]['image']['colorId']=fallback;c.product['skuList'][0]['image']['imgRefId']=fallback;c.schema[2]['value'][0]['value'][5]['value'][0]['properties'][1]['value']=fallback
   for p in c.schema[2]['value'][0]['value'][6]['value'][0]['properties'][:2]:p['value']=fallback
   next(x for x in b if x['schemaPointer']=='/2/value/0/value/5/value/0/properties/1/value')['sourcePointer']='/saleAttrs/0/attrValues';cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');base=self.baseline(s,cap,b,a);html='<div>New</div>';v=self.validation(ops,s,base,[{'pointer':'/3/value/0/properties/0/value','html':html,'assetTaskIds':[]}]);edit=s.plan_edit(v)['task'];ops.approve(edit['taskId'],edit['fingerprint'],confirmed=True);ops.execute(edit['taskId']);c.pending=copy.deepcopy(c.product);c.pending['desc']=html;c.pending['skuList'][0]['saleAttrs'][0]['mappingId']='different-nonempty-native-id'
   self.assertFalse(s.status(edit['taskId'],refresh=True)['pendingFieldsVerified']);c.product=copy.deepcopy(c.pending);self.assertFalse(s.verify_online(edit['taskId'])['onlineEffective'])
 def test_review_generic_partial_readback_cannot_be_attached_to_full_edit(self):
  from heideng_merchant.products import DETAIL
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);self.fake_posts(c);base=self.baseline(s,cap,b,a);v=self.validation(ops,s,base,[{'pointer':'/3/value/0/properties/0/value','html':'<div>New</div>','assetTaskIds':[]}]);scope=ops.task(v)['scope'];query={'url':DETAIL,'method':'GET','params':{'productId':100,'scene':'pop'},'skillId':'jdo-product-update'}
   with self.assertRaises(SafetyError):ops.prepare('merchant-test',{**scope['operation'],'url':PUBLISH},verification={'query':query,'expected':{'productId':100}},listing_input=scope['nativeListingInput'],validated_task_id=v)
 def test_original_sale_record_census_cannot_be_silently_omitted(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['skuList'][-1]['saleAttrs'].append({'attrId':101,'mappingId':'native-size','attrValues':'size','alias':'L','index':'2'});cap=ProductSchemaService(d,c).capture_edit('merchant-test','100')
   with self.assertRaises(SafetyError):self.baseline(s,cap,b,a)

 def test_all_original_critical_fields_require_submitted_values(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.schema[2]['value'][0]['value'][3].pop('value');b=[x for x in b if x['schemaPointer']!='/2/value/0/value/3/value'];cap=ProductSchemaService(d,c).capture_edit('merchant-test','100')
   with self.assertRaises(SafetyError):self.baseline(s,cap,b,a)
 def test_unknown_desc_property_is_not_the_product_detail_editor(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['unknownDesc']='retain';c.schema[4]['properties']=[{'key':'desc','value':'retain','productDetailField':'unknownDesc'}];b.append({'schemaPointer':'/4/properties/0/value','sourcePointer':'/unknownDesc','skuId':None,'conversion':'identity'});cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');base=self.baseline(s,cap,b,a)
   with self.assertRaises(SafetyError):s.plan_validation(base['baselineId'],[{'pointer':'/4/properties/0/value','html':'<div>Changed</div>','assetTaskIds':[]}])

 def test_opaque_business_array_with_component_code_is_not_reinterpreted_as_dto(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);value=[{'componentCode':'opaque-business-event','payload':{'keep':7}}];c.product['future']=copy.deepcopy(value);c.schema[-1]['value']=copy.deepcopy(value);cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');base=self.baseline(s,cap,b,a);self.assertEqual(base['schema'][-1]['value'],value)
 def test_unknown_numeric_business_value_cannot_be_coerced_to_string(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['future']=7;c.schema[-1]['value']=7;cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');schema=copy.deepcopy(cap['scope']['schema']);schema[-1]['value']='7';next(x for x in b if x['schemaPointer']=='/4/value')['conversion']='string'
   with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)
 def test_html_conversion_cannot_change_an_unknown_desc_business_value(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['unknownDesc']='A&B';c.schema[4]['properties']=[{'key':'desc','value':'A&B','productDetailField':'unknownDesc'}];b.append({'schemaPointer':'/4/properties/0/value','sourcePointer':'/unknownDesc','skuId':None,'conversion':'html'});cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');schema=copy.deepcopy(cap['scope']['schema']);schema[4]['properties'][0]['value']='A&amp;B'
   with self.assertRaises(SafetyError):s.baseline(cap['captureId'],schema,b,a)

 def test_single_sku_with_no_sales_dimensions_preserves_existing_references(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d,1);row=c.product['skuList'][0];row['saleAttrs']=[];row['image']['colorId']=row['image']['imgRefId']='0000000000';field=c.schema[2]['value'][0]['value'][5];field['value']=[];field['productDetailField']='skuList.saleAttrs';b=[x for x in b if not x['schemaPointer'].startswith('/2/value/0/value/5/value/')];b.append({'schemaPointer':'/2/value/0/value/5/value','sourcePointer':'/saleAttrs','skuId':'2001','conversion':'identity'})
   for prop in c.schema[2]['value'][0]['value'][6]['value'][0]['properties'][:2]:prop['value']='0000000000'
   cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');base=self.baseline(s,cap,b,[]);self.assertEqual(base['skuCount'],1);self.assertEqual(base['schema'][2]['value'][0]['value'][5]['value'],[])
 def test_nullable_original_detail_is_preserved_without_inventing_html(self):
  from heideng_merchant.product_schema import ProductSchemaService
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,cap,b,a=self.make(d);c.product['desc']=None;c.schema[3]['value'][0]['properties'][0]['value']=None;next(x for x in b if x['schemaPointer']=='/3/value/0/properties/0/value')['conversion']='identity';cap=ProductSchemaService(d,c).capture_edit('merchant-test','100');base=self.baseline(s,cap,b,a);self.assertIsNone(base['schema'][3]['value'][0]['properties'][0]['value'])
