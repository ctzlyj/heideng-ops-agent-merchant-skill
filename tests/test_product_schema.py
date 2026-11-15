import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.product_schema import ProductSchemaService, SCHEMAS
from heideng_merchant.products import DETAIL
from heideng_merchant.operations import Operations
from heideng_merchant.materials import MaterialService
from heideng_merchant.safety import SafetyError, atomic_json, read_json
from tests import material_fixtures as fixtures


def img_component(code, ref='red'):
    return {'componentCode':code,'label':'KEEP CONTROL','value':[{'componentCode':'img','properties':[{'key':'colorId','value':ref},{'key':'imgRefId','value':ref},{'key':'imgUrl','value':'jfs/t1/1/old.png'},{'key':'orderSort','value':'1'},{'key':'future','value':{'nested':True}}]}]}

def schema_fixture():
    return [img_component('WareSkuImg','0000000000'),{'componentCode':'SKUS','value':[{'componentCode':'SKU','value':[{'componentCode':'SkuUUid','value':'schema-uuid-'+str(i)},img_component('SkuMainImage'),{'componentCode':'SkuStockNum','value':i}]} for i in range(3)]},{'componentCode':'WareEditor','value':[{'componentCode':'detail','properties':[{'key':'desc','value':'<div>KEEP ALL DETAILS</div>'}]}]},{'componentCode':'FutureControl','future':{'choices':[1,2,3]},'value':None}]

class SchemaClient(fixtures.Client):
    def __init__(self):
        super().__init__();self.schema=schema_fixture();self.schema_text=None;self.total=3;self.schemas_count=1;self.drift=False;self.detail_calls=0;self.after_schema_foreign=False
        self.product={'productId':100,'categoryDTO':{'lastCategoryId':456},'skuList':[{'skuId':2001+i,'productId':100,'priceInfo':{'jdPrice':'30.00'}} for i in range(3)]}
    def invoke(self,profile,url,**kw):
        if url==SCHEMAS:
            self.calls.append((url,copy.deepcopy(kw)))
            if self.after_schema_foreign:self.foreign=True
            return {'success':True,'data':[self.schema_text if self.schema_text is not None else json.dumps(self.schema,ensure_ascii=False)]*self.schemas_count}
        if url==DETAIL:
            self.calls.append((url,copy.deepcopy(kw)));self.detail_calls+=1;data=copy.deepcopy(self.product)
            if self.drift and self.detail_calls>1:data['categoryDTO']['lastCategoryId']=789
            return {'success':True,'data':data}
        if url=='/rest/sp-product/v0/skus':
            self.calls.append((url,copy.deepcopy(kw)));page=kw['params']['page'];size=kw['params']['pageSize']
            result={'data':copy.deepcopy(self.product['skuList'][(page-1)*size:page*size])}
            if self.total is not None:result['paginationData']={'totalItems':self.total}
            return result
        return super().invoke(profile,url,**kw)

class SchemaTests(unittest.TestCase):
    def make(self,d):
        c=SchemaClient();ops=Operations(Path(d),c);ops.connect('merchant-test','synthetic-store','1')
        return c,ops,ProductSchemaService(Path(d),c)
    def capture(self,s):return s.capture_edit('merchant-test',100)
    def upload(self,d,c,ops):
        p=Path(d)/'sample.png';p.write_bytes(fixtures.png())
        with patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
            task=MaterialService(Path(d),c).prepare_upload('merchant-test',p,'img_test',7)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId'])
        return task['taskId']
    def test_native_edit_template_is_complete_readonly_and_not_sku_mapping_proof(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);cap=self.capture(s)
            self.assertEqual(cap['scope']['schema'],c.schema);self.assertEqual(cap['scope']['skuIds'],['2001','2002','2003'])
            request=next(kw for url,kw in c.calls if url==SCHEMAS)
            self.assertEqual(request['params'],{'lastCategoryId':456,'scene':'pop','productId':100});self.assertEqual(request['skill_id'],'jdo-product-publish')
            self.assertEqual(len(cap['imageTargets']),4);self.assertFalse(cap['submissionReady']);self.assertFalse(cap['skuIdentityMappingVerified']);self.assertEqual(cap['schemaSkuRowCount'],3)
            self.assertTrue(all(kw.get('method','GET')=='GET' for _,kw in c.calls))
    def test_lossless_replacement_preserves_all_skus_refs_controls_and_detail(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);asset=self.upload(d,c,ops);cap=self.capture(s);targets=cap['imageTargets'];changes=[{'pointer':t['pointer'],'assetTaskId':asset} for t in targets]
            writes=sum(kw.get('method')=='POST' for _,kw in c.calls);draft=s.draft_images(cap['captureId'],changes)
            expected=copy.deepcopy(c.schema)
            expected[0]['value'][0]['properties'][2]['value']='jfs/t1/1/synthetic.png'
            for row in expected[1]['value']:row['value'][1]['value'][0]['properties'][2]['value']='jfs/t1/1/synthetic.png'
            self.assertEqual(draft['schema'],expected);self.assertEqual(cap['scope']['schema'],c.schema)
            self.assertFalse(draft['submissionReady']);self.assertFalse(draft['productBound']);self.assertFalse(draft['remotePixelsVerified']);self.assertEqual(len(draft['changes']),4)
            self.assertEqual(sum(kw.get('method')=='POST' for _,kw in c.calls),writes)
            self.assertEqual(s.draft(draft['draftId'])['fingerprint'],draft['fingerprint'])
    def test_multiple_templates_duplicate_json_keys_and_nonfinite_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d)
            for text in ('[{"componentCode":"SKUS","componentCode":"WareSkuImg"}]','[{"componentCode":"SKUS","value":NaN}]'):
                c.schema_text=text
                with self.assertRaises(SafetyError):self.capture(s)
            c.schema_text=None;c.schemas_count=2
            with self.assertRaises(SafetyError):self.capture(s)
    def test_incomplete_or_conflicting_sku_census_and_wrong_parent_are_rejected(self):
        for mode in ('no-total','partial','foreign'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                c,ops,s=self.make(d)
                if mode=='no-total':c.total=None
                elif mode=='partial':c.total=4
                else:c.product['skuList'][-1]['productId']=999
                with self.assertRaises(SafetyError):self.capture(s)
    def test_source_and_shop_drift_during_capture_are_rejected(self):
        for mode in ('source','shop'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                c,ops,s=self.make(d);c.drift=mode=='source';c.after_schema_foreign=mode=='shop'
                with self.assertRaises(SafetyError):self.capture(s)
    def test_unknown_shapes_are_retained_but_do_not_become_editable_image_slots(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);c.schema.append({'componentCode':'FutureImage','value':[{'key':'imgUrl','value':'KEEP'}]});cap=self.capture(s)
            self.assertEqual(cap['scope']['schema'],c.schema);self.assertEqual(len(cap['imageTargets']),4)
    def test_capture_mutation_does_not_allow_drafts(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);cap=self.capture(s);p=Path(d)/'product-schemas'/'captures'/(cap['captureId']+'.json');v=read_json(p);v['scope']['schema'][0]['value']=[];atomic_json(p,v)
            with self.assertRaises(SafetyError):s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':'0'*24}])
    def test_non_image_pointer_and_duplicate_pointer_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);cap=self.capture(s);asset=self.upload(d,c,ops);pointer=cap['imageTargets'][0]['pointer']
            for changes in ([{'pointer':'/0/value/0/properties/0/value','assetTaskId':asset}],[{'pointer':pointer,'assetTaskId':asset}]*2):
                with self.assertRaises(SafetyError):s.draft_images(cap['captureId'],changes)
    def test_stale_template_or_material_receipt_is_rejected(self):
        for mode in ('schema','asset'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                c,ops,s=self.make(d);asset=self.upload(d,c,ops);cap=self.capture(s)
                if mode=='schema':c.schema[-1]['value']='changed'
                else:c.images[0]['imgUrl']='jfs/t1/1/different.png'
                with self.assertRaises(SafetyError):s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
    def test_other_profile_or_unknown_upload_is_rejected_without_repost(self):
        for mode in ('profile','unknown'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                c,ops,s=self.make(d);cap=self.capture(s);asset=self.upload(d,c,ops)
                if mode=='profile':
                    ops.connect('merchant-other','synthetic-store','1');other=s.capture_edit('merchant-other',100);cap=other
                else:
                    task=ops.task(asset);task['status']='unknown';atomic_json(ops._path(asset),task)
                writes=sum(kw.get('method')=='POST' for _,kw in c.calls)
                with self.assertRaises(SafetyError):s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
                self.assertEqual(sum(kw.get('method')=='POST' for _,kw in c.calls),writes)

    def test_cli_exposes_native_capture_draft_and_record_reads(self):
        from heideng_merchant.cli import parser, run
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'.heideng-merchant';state.mkdir();c,ops,service=self.make(state);asset=self.upload(state,c,ops)
            with patch('heideng_merchant.cli.OfficialClient',return_value=c):
                cap=run(parser().parse_args(['--home',d,'product-schema','--profile','merchant-test','--product-id','100']))
                changes=Path(d)/'changes.json';atomic_json(changes,[{'pointer':t['pointer'],'assetTaskId':asset} for t in cap['imageTargets']])
                draft=run(parser().parse_args(['--home',d,'schema-image-draft','--capture-id',cap['captureId'],'--changes',str(changes)]))
                self.assertFalse(draft['submissionReady'])
                read=run(parser().parse_args(['--home',d,'schema-draft-status','--draft-id',draft['draftId']]))
                self.assertEqual(read['schema'],draft['schema'])
    def test_partial_same_color_replacement_is_not_silently_fanned_out(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);asset=self.upload(d,c,ops);cap=self.capture(s)
            sku=next(t for t in cap['imageTargets'] if t['dimension']=='sku')
            with self.assertRaisesRegex(SafetyError,'same-color'):
                s.draft_images(cap['captureId'],[{'pointer':sku['pointer'],'assetTaskId':asset}])
    def test_duplicate_image_property_and_missing_schema_sku_rows_are_not_usable(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);c.schema[0]['value'][0]['properties'].append({'key':'imgUrl','value':'other'})
            with self.assertRaises(SafetyError):self.capture(s)
            c.schema=schema_fixture();c.schema[1]['value'].pop();cap=self.capture(s);asset=self.upload(d,c,ops)
            with self.assertRaisesRegex(SafetyError,'sku-row-count'):
                s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
    def test_non_string_asset_reference_is_rejected_before_remote_calls(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);cap=self.capture(s);calls=len(c.calls)
            for bad in ({},[],None,True,'../../foreign'):
                with self.assertRaises(SafetyError):
                    s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':bad}])
            self.assertEqual(len(c.calls),calls)

    def test_source_changes_during_asset_readback_do_not_produce_a_fresh_draft(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);asset=self.upload(d,c,ops);cap=self.capture(s);original=c.invoke
            def changed(profile,url,**kw):
                response=original(profile,url,**kw)
                if '{imageId}' in url:c.schema[-1]['value']='changed during asset read'
                return response
            c.invoke=changed
            with self.assertRaisesRegex(SafetyError,'source-stale'):
                s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])

    def test_precision_that_cannot_roundtrip_is_rejected_without_persisting(self):
        from heideng_merchant.product_schema import parse_schema
        for number in ('0.123456789012345678901','0.123456789012345678902','1e999'):
            with self.subTest(number=number),self.assertRaises(SafetyError):
                parse_schema({'data':['[{"componentCode":"Future","value":'+number+'}]']})
        schema,_=parse_schema({'data':['[{"componentCode":"Future","value":0.125}]']})
        self.assertEqual(schema[0]['value'],0.125)
    def test_boolean_to_integer_source_drift_cannot_compare_equal(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);c.schema[-1]['value']=True;asset=self.upload(d,c,ops);cap=self.capture(s);c.schema[-1]['value']=1
            with self.assertRaisesRegex(SafetyError,'source-stale'):
                s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
    def test_logical_secret_properties_are_rejected_before_capture_and_cli_output(self):
        import contextlib, io
        from heideng_merchant.cli import main
        from heideng_merchant.product_schema import parse_schema
        for key in ('apiKey','Authorization','refreshToken','app_secret','deviceId','Cookie'):
            with self.subTest(key=key),self.assertRaises(SafetyError):
                parse_schema({'data':[json.dumps([{'componentCode':'Future','value':{'nested':[{'key':key,'value':'synthetic-secret-marker'}]}}])]})
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'.heideng-merchant';state.mkdir();c,ops,s=self.make(state);c.schema.append({'componentCode':'Future','properties':[{'key':'apiKey','value':'synthetic-secret-marker'}]});out=io.StringIO()
            with patch('heideng_merchant.cli.OfficialClient',return_value=c),contextlib.redirect_stdout(out):
                code=main(['--home',d,'product-schema','--profile','merchant-test','--product-id','100'])
            self.assertEqual(code,2);self.assertNotIn('synthetic-secret-marker',out.getvalue())
            self.assertFalse(any((state/'product-schemas').rglob('*.json')))
    def test_changed_native_image_size_is_not_accepted_as_fresh_original_asset(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);asset=self.upload(d,c,ops);cap=self.capture(s);c.images[0]['imgSize']+=17
            with self.assertRaisesRegex(SafetyError,'original-receipt'):
                s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
    def test_long_and_rectangle_slots_preserve_every_other_native_property(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);c.schema.append(img_component('LongImg','0000000000'))
            c.schema[-1]['value'][0]['properties'].append({'key':'index','value':'7'})
            for row in c.schema[1]['value']:row['value'].append(img_component('SkuRectangleImage'))
            asset=self.upload(d,c,ops);cap=self.capture(s);draft=s.draft_images(cap['captureId'],[{'pointer':t['pointer'],'assetTaskId':asset} for t in cap['imageTargets']])
            expected=copy.deepcopy(c.schema)
            def replace(value):
                if isinstance(value,list):
                    for item in value:replace(item)
                elif isinstance(value,dict):
                    if value.get('key')=='imgUrl':value['value']='jfs/t1/1/synthetic.png'
                    else:
                        for item in value.values():replace(item)
            replace(expected)
            self.assertEqual(draft['schema'],expected);self.assertEqual(len(draft['changes']),8)

    def test_high_precision_source_change_is_rejected_even_when_float_would_compare_equal(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,s=self.make(d);asset=self.upload(d,c,ops);base=json.dumps(c.schema)[:-1]
            c.schema_text=base+',{ "componentCode":"ExactNumber", "value":0.12345678901234568}]'
            cap=self.capture(s)
            c.schema_text=base+',{ "componentCode":"ExactNumber", "value":0.123456789012345678901}]'
            with self.assertRaisesRegex(SafetyError,'cannot-roundtrip'):
                s.draft_images(cap['captureId'],[{'pointer':cap['imageTargets'][0]['pointer'],'assetTaskId':asset}])
    def test_schema_depth_budget_fails_closed_without_echoing_content(self):
        from heideng_merchant.product_schema import parse_schema
        value='"plain-synthetic-content"'
        for _ in range(130):value='['+value+']'
        with self.assertRaisesRegex(SafetyError,'depth-budget'):
            parse_schema({'data':['[{"componentCode":"Future","value":'+value+'}]']})

    def test_logical_private_properties_in_embedded_json_strings_are_rejected(self):
        from heideng_merchant.product_schema import parse_schema
        embedded=json.dumps({'properties':[{'key':'apiKey','value':'synthetic-only-marker'}]})
        with self.assertRaisesRegex(SafetyError,'credentials-not-allowed'):
            parse_schema({'data':[json.dumps([{'componentCode':'Future','value':embedded}])]})
