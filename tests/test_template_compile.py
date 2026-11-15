import copy,tempfile,unittest
from pathlib import Path
from heideng_merchant.safety import SafetyError
from heideng_merchant.edit_contract import leaves,validate_baseline,project
from heideng_merchant.template_compile import compile_native
from heideng_merchant.operations import digest


def raw_source(count=3):
 detail={'productId':100,'categoryDTO':{'lastCategoryId':456},'productInfo':{'productName':'synthetic source','productDetailDesc':'<div>Original</div>'},'material':{'mainImages':[{'colorId':'0000000000','imgRefId':'0000000000','imgUrl':'jfs/t1/1/old.png','orderSort':'1','future':{'keep':True}}]},'future':[{'componentCode':'opaque','value':'retain','other':True}],'skuList':[]}
 def field(code,hint=None,**extra):return {'componentCode':code,**({'productDetailField':hint} if hint else {}),**extra}
 image_proto=field('img',properties=[{'key':k} for k in ('colorId','imgRefId','imgUrl','orderSort')])
 sale_proto=field('sale-prop-100',extra={'isColor':True},properties=[{'key':'attrValueAlias'},{'key':'mappingId'},{'key':'index'}])
 raw=[field('WareTitle','productInfo.productName',tipsDetailList=[{'tipsValue':'native rule metadata'}]),field('WareSkuImg','material.mainImages',childrenComponents=[image_proto]),field('WareEditor',childrenComponents=[field('detail',properties=[{'key':'desc','productDetailField':'productInfo.productDetailDesc'}])]),field('SKUS',childrenComponents=[field('SkuVendorSku','skuList.outerId'),field('SkuJdprice','skuList.priceInfo.jdPrice'),field('SkuStockNum','skuList.stockNum'),field('VenderCategoryValue','skuList.saleAttrs',childrenComponents=[sale_proto]),field('SkuMainImage','skuList.image',childrenComponents=[image_proto]),field('FutureSku','skuList.future')]),field('FutureControl','future')]
 for i in range(count):
  color='red' if i%2==0 else 'blue';mapping='source-'+color
  detail['skuList'].append({'skuId':2001+i,'productId':100,'outerId':'A&B-'+str(i),'priceInfo':{'jdPrice':'30.00'},'stockNum':i,'saleAttrs':[{'attrId':100,'alias':color,'mappingId':mapping,'attrValues':'fallback-'+color,'index':'1'}],'image':{'colorId':mapping,'imgRefId':mapping,'imgUrl':'jfs/t1/1/old.png','orderSort':'1','future':{'keep':i}},'future':{'retain':[i,True]}})
 return raw,detail


class TemplateCompileTests(unittest.TestCase):
 def test_rule_only_full_native_source_and_all_provenance(self):
  raw,detail=raw_source(1000);before=copy.deepcopy((raw,detail));result=compile_native(raw,detail)
  self.assertEqual((raw,detail),before);schema=result['schema'];sku_rows=schema[3]['value'];self.assertEqual(len(sku_rows),1000)
  for index,row in enumerate(sku_rows):
   fields={r['componentCode']:r for r in row['value']};self.assertEqual([r['componentCode'] for r in row['value'][:2]],['SkuId','SkuUUid']);self.assertEqual(fields['SkuId']['value'],str(2001+index));self.assertEqual(fields['SkuUUid']['value'],str(2001+index));self.assertEqual(fields['SkuVendorSku']['value'],'A&B-'+str(index));self.assertEqual(fields['SkuStockNum']['value'],index);self.assertEqual(fields['SkuJdprice']['value'],'30.00');self.assertEqual(fields['FutureSku']['value'],detail['skuList'][index]['future'])
  self.assertEqual(len(result['bindings']),len(leaves(project(schema))));self.assertEqual(len(result['saleSources']),1000);self.assertEqual(schema[-1]['value'],detail['future'])
  capture={'scope':{'schema':schema,'skuIds':[str(r['skuId']) for r in detail['skuList']],'productId':'100','productDetail':detail,'productDetailHash':digest(detail)}}
  dto,_,_=validate_baseline(capture,schema,result['bindings'],result['saleSources']);self.assertNotIn('tipsDetailList',str(dto));self.assertNotIn('productDetailField',str(dto));self.assertEqual(dto[-1]['value'],detail['future'])
 def test_no_dimension_sku_does_not_invent_sales(self):
  raw,detail=raw_source();raw[3]['childrenComponents']=[r for r in raw[3]['childrenComponents'] if r['componentCode']!='VenderCategoryValue']
  for row in detail['skuList']:row.pop('saleAttrs')
  result=compile_native(raw,detail);self.assertEqual(result['saleSources'],[]);self.assertTrue(all('VenderCategoryValue' not in str(row) for row in result['schema'][3]['value']))
 def test_missing_or_wrong_critical_source_does_not_default(self):
  for key in ('outerId','stockNum','priceInfo'):
   with self.subTest(key=key):
    raw,detail=raw_source();detail['skuList'][-1].pop(key)
    with self.assertRaises(SafetyError):compile_native(raw,detail)
  raw,detail=raw_source();raw[3]['childrenComponents'][0]['productDetailField']='skuList.future'
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_unknown_rule_field_or_unbound_component_is_not_silently_deleted(self):
  raw,detail=raw_source();raw[0]['unreviewedBusinessField']={'retain':True}
  with self.assertRaises(SafetyError):compile_native(raw,detail)
  raw,detail=raw_source();raw[-1].pop('productDetailField')
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_sale_attr_census_mapping_and_real_identity(self):
  raw,detail=raw_source();detail['skuList'][0]['saleAttrs'][0]['mappingId']='';result=compile_native(raw,detail);sale=result['schema'][3]['value'][0]['value'][5]['value'][0];props={p['key']:p['value'] for p in sale['properties']};self.assertEqual(props['mappingId'],'fallback-red')
  raw,detail=raw_source();detail['skuList'][-1]['saleAttrs'].append({'attrId':101,'attrValues':'unknown','mappingId':'unknown'})
  with self.assertRaises(SafetyError):compile_native(raw,detail)
  raw,detail=raw_source();detail['skuList'][-1]['saleAttrs'][0]['attrId']=101
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_unknown_numeric_value_stays_numeric_and_null_detail_stays_null(self):
  raw,detail=raw_source();detail['future']=3;detail['productInfo']['productDetailDesc']=None;result=compile_native(raw,detail);self.assertEqual(result['schema'][-1]['value'],3);self.assertIsNone(result['schema'][2]['value'][0]['properties'][0]['value'])
 def test_populated_original_template_keeps_real_row_order(self):
  raw,detail=raw_source();first=compile_native(raw,detail);filled=copy.deepcopy(first['schema']);filled[3]['value'].reverse();result=compile_native(filled,detail);self.assertEqual([r['value'][0]['value'] for r in result['schema'][3]['value']],['2003','2002','2001'])
  filled[3]['value'][-1]['value'][1]['value']='9999'
  with self.assertRaises(SafetyError):compile_native(filled,detail)
 def test_native_dictionary_order_does_not_change_compilation(self):
  raw,detail=raw_source();detail['material']['mainImages'][0].update(zeta={'retain':1},alpha={'retain':2});first=compile_native(raw,detail)
  detail['material']['mainImages'][0]=dict(reversed(list(detail['material']['mainImages'][0].items())))
  self.assertEqual(compile_native(raw,detail),first)
 def test_declared_structural_container_does_not_submit_rule_metadata_as_business(self):
  raw,detail=raw_source();raw.append({'componentCode':'FutureContainer','childrenComponents':[{'componentCode':'NestedKnown','productDetailField':'productInfo.productName'}]});result=compile_native(raw,detail);dto=project(result['schema']);self.assertNotIn('productDetailField',str(dto));self.assertEqual(dto[-1]['value'][0]['value'],'synthetic source')
 def test_product_attribute_container_selects_real_attr_id_and_keeps_unknown_values(self):
  raw,detail=raw_source();detail['productInfo']['goodsAttrs']=[{'attrId':77,'attrValues':'a,b','future':{'retain':True}}];raw.append({'componentCode':'CategoryGroupList','productDetailField':'productInfo.goodsAttrs','childrenComponents':[{'componentCode':'prop-product-77','properties':[{'key':'attrValues'}]}]});result=compile_native(raw,detail);dto=project(result['schema']);self.assertEqual(dto[-1]['value'][0]['componentCode'],'prop-product-77');props={p['key']:p['value'] for p in dto[-1]['value'][0]['properties']};self.assertEqual(props['future'],{'retain':True})
 def test_agent_commands_do_not_require_handwritten_bindings(self):
  from heideng_merchant.cli import parser
  for command in ('schema-edit-prepare','schema-compile'):
   args=parser().parse_args([command,'--capture-id','a'*24]);self.assertEqual(args.command,command);self.assertEqual(args.capture_id,'a'*24)
 def test_component_business_properties_are_preserved_and_source_bound(self):
  raw,detail=raw_source();raw[0]['properties']=[{'key':'futureBiz','productDetailField':'future'}];raw[1]['properties']=[{'key':'futureBiz','productDetailField':'future'}];result=compile_native(raw,detail)
  for row in result['schema'][:2]:self.assertEqual(row['properties'][0]['value'],detail['future'])
  self.assertEqual(len(result['bindings']),len(leaves(project(result['schema']))))
 def test_unproven_component_properties_or_scalar_values_are_never_deleted(self):
  raw,detail=raw_source();raw[0]['properties']=[{'key':'futureBiz','value':'original'}]
  with self.assertRaises(SafetyError):compile_native(raw,detail)
  raw,detail=raw_source();raw.append({'componentCode':'UnknownBoth','value':'must-keep','properties':[{'key':'known','productDetailField':'future'}]})
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_sale_child_business_value_without_source_is_not_deleted(self):
  raw,detail=raw_source();raw[3]['childrenComponents'][3]['childrenComponents'][0]['value']='must-keep'
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_opaque_lookalike_without_parent_source_is_not_a_declared_container(self):
  raw,detail=raw_source();raw.append({'componentCode':'UnknownOpaque','value':[{'componentCode':'LooksLikeDTO','productDetailField':'future'}]})
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_populated_bool_and_number_are_not_treated_as_equal(self):
  raw,detail=raw_source();detail['future']=True;filled=compile_native(raw,detail)['schema'];filled[-1]['value']=1
  with self.assertRaises(SafetyError):compile_native(filled,detail)
 def test_populated_image_properties_are_not_replaced_by_child_rules(self):
  raw,detail=raw_source(1);filled=compile_native(raw,detail)['schema'];filled[1].update(productDetailField=raw[1]['productDetailField'],childrenComponents=copy.deepcopy(raw[1]['childrenComponents']));filled[1]['value'][0]['properties'].append({'key':'futureBiz','value':detail['future'],'productDetailField':'future'});result=compile_native(filled,detail);self.assertIn('futureBiz',[p['key'] for p in result['schema'][1]['value'][0]['properties']])
 def test_original_attribute_records_cannot_disappear_without_any_attribute_group(self):
  raw,detail=raw_source(1);raw[3]['childrenComponents']=[r for r in raw[3]['childrenComponents'] if r['componentCode']!='VenderCategoryValue']
  with self.assertRaises(SafetyError):compile_native(raw,detail)
 def test_declared_sales_child_value_keeps_its_generated_source_declaration(self):
  raw,detail=raw_source(1);raw[3]['childrenComponents'][3]['childrenComponents'][0].update(value='red',productDetailField='skuList.saleAttrs.0.alias');result=compile_native(raw,detail);capture={'scope':{'schema':result['schema'],'skuIds':['2001'],'productId':'100','productDetail':detail,'productDetailHash':digest(detail)}};validate_baseline(capture,result['schema'],result['bindings'],result['saleSources'])
 def test_documented_common_sku_attributes_are_not_misclassified_as_sales(self):
  raw,detail=raw_source(1);raw[3]['childrenComponents']=[r for r in raw[3]['childrenComponents'] if r['componentCode']!='VenderCategoryValue'];detail['skuList'][0].pop('saleAttrs');detail['skuList'][0]['goodsAttrInfos']=[{'attrId':77,'attrValues':['a','b'],'expands':[],'units':[]}];raw[3]['childrenComponents'].append({'componentCode':'SkuCategoryGroupList','productDetailField':'skuList.goodsAttrInfos','childrenComponents':[{'componentCode':'prop-sku-77'}],'properties':[{'key':'attrValues'},{'key':'expands'},{'key':'units'}]});result=compile_native(raw,detail);self.assertEqual(result['saleSources'],[]);fields={r['componentCode']:r for r in result['schema'][3]['value'][0]['value']};self.assertEqual(fields['SkuCategoryGroupList']['value'][0]['componentCode'],'prop-sku-77');props={p['key']:p['value'] for p in fields['SkuCategoryGroupList']['value'][0]['properties']};self.assertEqual(props['attrValues'],['a','b']);self.assertNotIn('properties',fields['SkuCategoryGroupList'])
 def test_multiple_image_definitions_reconcile_with_their_own_populated_position(self):
  raw,detail=raw_source(1);second=copy.deepcopy(detail['material']['mainImages'][0]);second['orderSort']='2';second['imgUrl']='jfs/t1/1/two.png';detail['material']['mainImages'].append(second);filled=compile_native(raw,detail)['schema'];filled[1]['productDetailField']=raw[1]['productDetailField'];filled[1]['childrenComponents']=copy.deepcopy(filled[1]['value']);result=compile_native(filled,detail);self.assertEqual([next(p['value'] for p in r['properties'] if p['key']=='orderSort') for r in result['schema'][1]['value']],['1','2'])
 def test_populated_sales_business_properties_survive_rule_reconciliation(self):
  raw,detail=raw_source(1);filled=compile_native(raw,detail)['schema'];group=filled[3]['value'][0]['value'][5];group.update(productDetailField=raw[3]['childrenComponents'][3]['productDetailField'],childrenComponents=copy.deepcopy(raw[3]['childrenComponents'][3]['childrenComponents']));group['value'][0]['properties'].append({'key':'futureBiz','value':detail['skuList'][0]['future'],'productDetailField':'skuList.future'});result=compile_native(filled,detail);self.assertIn('futureBiz',[p['key'] for p in result['schema'][3]['value'][0]['value'][5]['value'][0]['properties']])
 def test_duplicate_property_and_duplicate_native_ids_are_rejected(self):
  raw,detail=raw_source();raw[1]['childrenComponents'][0]['properties'].append({'key':'imgUrl'})
  with self.assertRaises(SafetyError):compile_native(raw,detail)
  raw,detail=raw_source();detail['skuList'][-1]['skuId']=detail['skuList'][0]['skuId']
  with self.assertRaises(SafetyError):compile_native(raw,detail)

class AutomaticBaselineTests(unittest.TestCase):
 def setup(self,count=3):
  from tests.test_product_schema import SchemaClient
  from heideng_merchant.operations import Operations
  from heideng_merchant.product_schema import ProductSchemaService
  from heideng_merchant.schema_edit import EditService
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);state=Path(self.temp.name);c=SchemaClient();c.total=count;c.schema,c.product=raw_source(count);ops=Operations(state,c);ops.connect('merchant-test','synthetic-store','1');schemas=ProductSchemaService(state,c);cap=schemas.capture_edit('merchant-test','100')
  return state,c,schemas,cap,EditService(state,c)
 def test_original_rule_capture_is_immutable_and_prepare_is_idempotent(self):
  state,c,schemas,cap,service=self.setup(1000);before=copy.deepcopy(cap['scope']['schema']);baseline=service.prepare_baseline(cap['captureId']);again=service.prepare_baseline(cap['captureId']);self.assertEqual(baseline['baselineId'],again['baselineId']);self.assertEqual(baseline['skuCount'],1000);self.assertTrue(baseline['allBaselineValuesSourceBound']);self.assertEqual(schemas.capture(cap['captureId'])['scope']['schema'],before);self.assertNotEqual(baseline['scope']['captureId'],cap['captureId']);self.assertFalse(list((state/'tasks').glob('*.json')))
 def test_compiled_fields_cannot_be_forged_by_rehashing_record(self):
  from heideng_merchant.safety import atomic_json,read_json
  state,c,schemas,cap,service=self.setup();baseline=service.prepare_baseline(cap['captureId']);ident=baseline['scope']['captureId'];path=schemas._path('captures',ident);record=read_json(path);record['scope']['schema'][0]['value']='forged';record['fingerprint']=digest(record['scope']);atomic_json(path,record)
  with self.assertRaises(SafetyError):schemas.capture(ident)
 def test_raw_declarations_cannot_be_replaced_while_original_capture_is_unchanged(self):
  from heideng_merchant.safety import atomic_json,read_json
  state,c,schemas,cap,service=self.setup();baseline=service.prepare_baseline(cap['captureId']);ident=baseline['scope']['captureId'];path=schemas._path('captures',ident);record=read_json(path);record['scope']['rawSchema'][0]['productDetailField']='future';record['fingerprint']=digest(record['scope']);atomic_json(path,record)
  with self.assertRaises(SafetyError):schemas.capture(ident)
 def test_raw_schema_alias_without_compiler_proof_cannot_bypass_live_template_check(self):
  from heideng_merchant.safety import atomic_json,read_json
  state,c,schemas,cap,service=self.setup();path=schemas._path('captures',cap['captureId']);record=read_json(path);record['scope']['rawSchema']=copy.deepcopy(record['scope']['schema']);record['fingerprint']=digest(record['scope']);atomic_json(path,record)
  with self.assertRaises(SafetyError):schemas.capture(cap['captureId'])
 def test_cached_baseline_type_change_is_not_hidden_by_python_equality(self):
  from heideng_merchant.safety import atomic_json,read_json
  state,c,schemas,cap,service=self.setup();baseline=service.prepare_baseline(cap['captureId']);path=service._path(baseline['baselineId']);record=read_json(path);row=record['scope']['schema'][3]['value'][0];next(r for r in row['value'] if r['componentCode']=='FutureSku')['value']['retain'][1]=1;record['fingerprint']=digest(record['scope']);atomic_json(path,record)
  with self.assertRaises(SafetyError):service.prepare_baseline(cap['captureId'])
 def test_compiler_contract_boolean_is_not_integer_version(self):
  from heideng_merchant.safety import atomic_json,read_json
  state,c,schemas,cap,service=self.setup();baseline=service.prepare_baseline(cap['captureId']);ident=baseline['scope']['captureId'];path=schemas._path('captures',ident);record=read_json(path);record['scope']['schemaCompiler']['contract']=True;record['fingerprint']=digest(record['scope']);atomic_json(path,record)
  with self.assertRaises(SafetyError):schemas.capture(ident)
 def test_cached_prepare_rechecks_current_source_and_template(self):
  state,c,schemas,cap,service=self.setup();baseline=service.prepare_baseline(cap['captureId']);c.product['skuList'][-1]['stockNum']+=1
  with self.assertRaises(SafetyError):service.prepare_baseline(cap['captureId'])

if __name__=='__main__':unittest.main()
