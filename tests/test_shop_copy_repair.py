"""Original-link merchant code repairs through the registered shop-copy CLI; no external calls."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from heideng_merchant import owned_product_copy as copying, sku_image_edit as edits
from heideng_merchant.safety import atomic_json, read_json, file_sha
from tests.test_owned_product_copy import SOURCE, TARGET


def product(pid, skus, codes):
    return {'productInfo':{'productId':pid,'productName':'两色合成灯','brandInfo':{'brandId':7},
                           'categoryDetail':{'lastCategoryId':91},'itemNum':'LT-01','goodsAttrInfos':[]},
            'material':{'mainImages':[],'ggtImages':[]},
            'skuList':[{'productId':pid,'skuId':sid,'outerId':code,'upcCode':'','skuEnableStatus':1,
                        'stockNum':stock,'priceInfo':{'jdPrice':'33.20'},'goodsAttrInfos':[],
                        'futureControl':{'nested':['preserve',0]},
                        'saleAttrs':[{'dim':1,'attrId':88,'attrName':'颜色','attrValueAlias':color,
                                      'attrValues':str(sid+1000)}]}
                       for sid,code,color,stock in zip(skus,codes,('白','蓝'),(0,17))]}


def live_schema(detail):
    info = detail['productInfo']
    rows = []
    for row in reversed(detail['skuList']):
        attr = row['saleAttrs'][0]
        rows.append({'componentCode':'SKU','value':[
            {'componentCode':'SkuId','value':row['skuId']},{'componentCode':'SkuUUid','value':str(row['skuId'])},
            {'componentCode':'SkuVendorSku','value':row['outerId']},{'componentCode':'SkuJdprice','value':'33.20'},
            {'componentCode':'SkuStockNum','value':row['stockNum']},{'componentCode':'SkuEnableStatus','value':'1'},
            {'componentCode':'FutureControl','value':{'nested':['preserve',0]}},
            {'componentCode':'VenderCategoryValue','value':[{'componentCode':'sale-prop-88','properties':[
                {'key':'mappingId','value':attr['attrValues']},{'key':'attrValueAlias','value':attr['attrValueAlias']}]}]}]})
    return [{'componentCode':'WareTitle','value':info['productName']},{'componentCode':'WareItemnum','value':info['itemNum']},
            {'componentCode':'WareBrand','value':'7'},{'componentCode':'SKUS','value':rows}]


class CodeRepairEntryTests(unittest.TestCase):
    def setUp(self):
        self.home=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':str(self.home)}))
        self.enterContext(patch.object(sys,'path',[str(Path(__file__).resolve().parents[1]/'mature/listing/scripts'),*sys.path]))
        from heideng_merchant import shop_copy_command as entry
        self.entry=entry
        self.api=entry.api
        self.enterContext(patch.object(self.api,'_ACTIVE_JDO_PROFILE',None))
        self.enterContext(patch.object(self.api,'_VERIFIED_JDO_STORE',None))
        self.enterContext(patch.object(self.api,'STATE_ROOT',self.home/'mature/listing'))
        self.config=self.home/'two-stores.json'
        atomic_json(self.config,{'stores':{s['profile']:s for s in (SOURCE,TARGET)}})
        self.source=product(701,(201,202),('00001','CODE/b'))
        self.online=product(802,(301,302),('CODE/b',''))
        self.online['skuList'].reverse()
        self.application=deepcopy(self.online)
        self.draft_schema=None
        self.product_reads=0
        self.writes=[]
        self.pending=False
        self.lose_response=False
        self.publication_failure=None
        self.validation={'success':True,'data':{'wareKeeperDetectResultList':[]}}
        self.enterContext(patch.object(self.api,'get',side_effect=self.get))
        self.enterContext(patch.object(self.api,'run_jdo_large',side_effect=self.send))
        self.frozen=copying.freeze_copy(SOURCE,TARGET,self.source)
        self.task=entry.pair_key(self.frozen)
        self.root=entry.task_directory(self.task)
        self.revision=self.root/'revisions'/self.frozen['sha256'][:24]
        atomic_json(self.revision/'source.json',self.frozen)
        atomic_json(self.root/'current.json',{'taskId':self.task,'revision':self.frozen['sha256'],
                    'sourceShop':SOURCE,'targetShop':TARGET,'sourceProductId':'701','existingTargetId':802})

    def get(self, skill, url, params):
        shop = SOURCE if self.api.active_jdo_profile() == SOURCE['profile'] else TARGET
        if url.endswith('/venderinfo'):
            return {'success':True,'data':{'venderId':shop['venderId'],'shopBaseInfo':{
                'shopName':shop['shopName'],'shopId':shop['shopId'],'status':1,'type':0}}}
        if url.endswith('/products/{productId}') or url.endswith('/product-apply/{applyId}'):
            self.product_reads += 1
            details = self.source if shop==SOURCE else self.online if 'products/' in url else self.application
            return {'data':{**deepcopy(details),'shopId':shop['shopId'],'venderId':shop['venderId']}}
        if url.endswith('/product-schemas'):
            self.assertEqual(shop,TARGET)
            if 'productId' not in params:
                return {'data':[{'componentList':[{'componentCode':'SKUS','childrenComponents':[
                    {'componentCode':'SkuVendorSku'},{'componentCode':'FutureControl','productDetailField':'skuList.futureControl'}]}]}]}
            return {'data':[json.dumps(self.draft_schema if self.draft_schema is not None else live_schema(self.application))]}
        raise AssertionError((skill,url,params))

    def send(self, **request):
        self.assertEqual(request['method'],'POST')
        self.assertEqual(self.api.active_jdo_profile(),TARGET['profile'])
        if request['url'].endswith('/validations'):
            return self.validation
        body = read_json(request['body_path'])
        self.assertEqual(request['url'],'/rest/sp-product/v0/product-applies')
        self.assertEqual((body['productApplyDTO']['productId'],body['productApplyDTO']['saveActionType']),(802,0))
        self.writes.append(body)
        if self.publication_failure is not None:
            raise self.publication_failure
        schema = edits.components(json.loads(body['schema']))
        self.assertEqual(schema['WareItemnum']['value'],'LT-01')
        records = edits.sku_rows(self.application,802)
        for sku in schema['SKUS']['value']:
            fields=edits.components(sku['value'])
            self.assertNotIn('SkuStockNum',fields)
            self.assertEqual(fields['FutureControl']['value'],{'nested':['preserve',0]})
            records[str(fields['SkuId']['value'])]['outerId'] = fields['SkuVendorSku']['value']
        if not self.pending:
            self.online = deepcopy(self.application)
        if self.lose_response:
            raise TimeoutError('synthetic lost reply')
        return {'success':True,'data':{'productId':802,'applyId':903}}

    def call(self,*flags):
        stream=io.StringIO()
        with redirect_stdout(stream):
            self.entry.main(['repair-sku-codes','--task',self.task,'--target-profile',TARGET['profile'],
                             '--target-config',str(self.config),*flags])
        return json.loads(stream.getvalue().strip().splitlines()[-1])

    def confirm(self):
        return self.call('--product-id','802','--confirm','REPAIR_TARGET_SKU_CODES')

    def bind_accepted_body(self):
        pointer=read_json(self.root/'current.json');pointer.pop('existingTargetId',None)
        atomic_json(self.root/'current.json',pointer)
        components = live_schema(self.application)
        for index, group in enumerate(edits.components(components)['SKUS']['value']):
            group['value']=[field for field in group['value'] if field['componentCode'] not in ('SkuId','SkuUUid')]
            for prop in edits.components(group['value'])['VenderCategoryValue']['value'][0]['properties']:
                if prop['key']=='mappingId':
                    prop['value']=f'old-accepted-{index}'
        body={'scene':'pop','schema':json.dumps(components),'productApplyDTO':{'categoryDTO':{'lastCategoryId':91}}}
        delivery={'scope':'synthetic-target'}
        atomic_json(self.revision/'delivery-evidence.json',delivery)
        atomic_json(self.revision/'pilot.json',{'intent':'publish-one','target':TARGET,'revision':self.frozen['sha256'],
                  'body':body,'approval':edits.digest({'source':self.frozen['sha256'],'target':TARGET,'body':body,'delivery':delivery})})
        destination = self.root/'publication'/'publish-body.json'
        atomic_json(destination,body)
        atomic_json(destination.parent/'publish-body.submit-state.json',{'stage':'PUBLISHED','productId':802,'applyId':900,
                                                                      'payloadSha256':file_sha(destination)})
        atomic_json(destination.parent/'result.json',{'success':True,'data':{'productId':802,'applyId':900}})
        self.draft_schema={'componentList':[{'componentCode':'SKUS','childrenComponents':[{'componentCode':'SkuVendorSku'}]}]}
        return destination

    def test_explicit_existing_target_repaired_exactly_once_using_specs(self):
        only=self.call('--check-only')
        self.assertEqual(only['status'],'needs-repair-evidence')
        plan=self.call('--product-id','802','--check-only')
        self.assertTrue(plan['ok'],plan)
        self.assertEqual({c['targetSkuId']:c['after'] for c in plan['changes']},{'301':'00001','302':'CODE/b'})
        self.assertEqual(self.writes,[])
        self.assertTrue(self.confirm()['ok'])
        self.assertEqual(self.confirm()['status'],'sku-codes-already-match')
        self.assertEqual(len(self.writes),1)

    def test_lost_reply_with_edit_only_readback_is_never_replayed(self):
        self.pending=True
        self.lose_response=True
        self.assertEqual(self.confirm()['status'],'sku-code-repair-awaiting-readback')
        for _ in range(2):
            result=self.confirm()
            self.assertEqual(result['status'],'application-codes-observed-original-unconfirmed')
            self.assertFalse(result['online']['codesMatch'])
        with self.assertRaisesRegex(ValueError,'商家编码编辑'):
            edits.require_no_pending_sku_edit(TARGET,802)
        self.online=deepcopy(self.application)
        self.assertEqual(self.call('--reconcile')['status'],'sku-codes-observed-original-unconfirmed')
        # Only a recovered response of the original edit establishes acceptance.
        path=edits.code_repair_directory(TARGET,802)/'current.json'
        atomic_json(Path(read_json(path)['body']).with_name('response.json'),{'success':True,'data':{'productId':802,'applyId':903}})
        self.assertEqual(self.call('--reconcile')['status'],'sku-codes-verified')
        edits.require_no_pending_sku_edit(TARGET,802)
        self.assertEqual(len(self.writes),1)

    def test_uncertain_write_cannot_report_verified_after_unrelated_change(self):
        self.lose_response=True
        self.confirm()
        self.online['productInfo']['productName']='另一种经营状态'
        res=self.call('--reconcile')
        self.assertFalse(res['ok'])
        self.assertTrue(res['online']['codesMatch'])
        self.assertFalse(res['online']['otherFieldsMatch'])
        self.assertEqual(len(self.writes),1)

    def test_missing_template_ambiguous_specs_wrong_target_and_unbound_apply_stop(self):
        self.draft_schema={'componentList':[{'componentCode':'SkuVendorSku'}]}
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        self.draft_schema=None
        self.assertEqual(self.call('--product-id','803','--confirm','REPAIR_TARGET_SKU_CODES')['status'],'needs-target-evidence')
        self.online['skuList'][1]['saleAttrs']=deepcopy(self.online['skuList'][0]['saleAttrs'])
        self.assertEqual(self.confirm()['status'],'needs-repair-evidence')
        self.online=deepcopy(self.application)
        pointer=read_json(self.root/'current.json');pointer.pop('existingTargetId')
        atomic_json(self.root/'current.json',pointer)
        atomic_json(self.root/'publication/result.json',{'data':{'applyId':903}})
        self.assertEqual(self.confirm()['status'],'needs-repair-evidence')
        self.assertEqual(self.writes,[])

    def test_store_source_code_and_target_read_drift_prevent_submission(self):
        changed=self.source['skuList'][0]
        changed['outerId']='NEW'
        self.assertFalse(self.confirm().get('ok',False))
        changed['outerId']='00001'
        self.application['skuList'][0]['priceInfo']['jdPrice']='99'
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        self.assertEqual(self.writes,[])

    def test_missing_blank_code_field_needs_category_declaration_and_platform_validation(self):
        self.draft_schema = live_schema(self.application)
        for group in self.draft_schema[-1]['value']:
            cells=edits.components(group['value'])
            if cells['SkuId']['value']==302:
                group['value'].remove(cells['SkuVendorSku'])
        self.validation={'success':True,'data':{'valid':False}}
        self.assertEqual(self.confirm()['status'],'validation-needs-review')
        self.assertEqual(self.writes,[])
        self.validation={'success':True,'data':{'wareKeeperDetectResultList':[]}}
        self.assertEqual(self.confirm()['status'],'sku-codes-verified')

    def test_unfilled_category_uses_accepted_target_body_real_ids_and_current_price(self):
        self.bind_accepted_body()
        for product in (self.application,self.online):
            product['skuList'][0]['priceInfo']['jdPrice']='41.20'
        self.assertEqual(self.call('--confirm','REPAIR_TARGET_SKU_CODES')['status'],'sku-codes-verified')
        rows=edits.components(json.loads(self.writes[0]['schema']))['SKUS']['value']
        byid={str(edits.components(row['value'])['SkuId']['value']):edits.components(row['value']) for row in rows}
        self.assertEqual(set(byid),{'301','302'})
        self.assertEqual(byid['302']['SkuJdprice']['value'],'41.20')
        self.assertEqual((byid['301']['SkuVendorSku']['value'],byid['302']['SkuVendorSku']['value']),('00001','CODE/b'))

    def test_unverifiable_stale_historical_component_and_modified_body_never_submit(self):
        body=self.bind_accepted_body()
        for product in (self.application,self.online):
            product['skuList'][0]['futureControl']={'other':'changed after creation'}
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        raw=read_json(body);raw['scene']='other';atomic_json(body,raw)
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        self.assertEqual(self.writes,[])

    def test_wide_and_structured_inputs_cannot_be_overwritten_by_stale_filled_template(self):
        for product in (self.application,self.online):
            product['productInfo']['wide']=5
        self.draft_schema=live_schema(self.application)+[{'componentCode':'WareWide','value':'55'}]
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        self.draft_schema[-1]['value']='5'
        for product in (self.source,self.application,self.online):
            for row in product['skuList']:
                row['saleAttrs'][0]['templateSkuProps']=[{'id':'volume','value':'250','unit':'ml'}]
        self.frozen=copying.freeze_copy(SOURCE,TARGET,self.source)
        self.revision=self.root/'revisions'/self.frozen['sha256'][:24]
        atomic_json(self.revision/'source.json',self.frozen)
        idx=read_json(self.root/'current.json');idx['revision']=self.frozen['sha256'];atomic_json(self.root/'current.json',idx)
        for sku in edits.components(self.draft_schema)['SKUS']['value']:
            attr=edits.components(sku['value'])['VenderCategoryValue']['value'][0]
            attr['properties'].append({'key':'templateSkuProps','value':json.dumps([{'id':'volume','value':'1000','unit':'ml'}])})
        self.assertEqual(self.confirm()['status'],'needs-edit-template')
        self.assertEqual(self.writes,[])

    def test_acknowledged_code_repair_reports_natural_stock_and_status_drift_separately(self):
        self.pending=True
        self.assertEqual(self.confirm()['status'],'sku-codes-in-application')
        self.online=deepcopy(self.application)
        self.online['skuList'][0]['stockNum']=14
        self.online['productInfo']['productStatusNew']=103
        self.online['productInfo']['modifiedTime']=1010
        result=self.call('--reconcile')
        self.assertEqual(result['status'],'sku-codes-verified')
        self.assertEqual(result['submissionStatus'],'accepted')
        self.assertIn('changedCountersOrStatus',result)
        edits.require_no_pending_code_repair(TARGET,802)
        self.assertEqual(len(self.writes),1)

    def test_numeric_error_text_and_old_unverified_rejection_never_release_or_resubmit(self):
        self.publication_failure=self.api.JdoError('1010300506 synthetic text alone')
        self.assertEqual(self.confirm()['status'],'sku-code-repair-awaiting-readback')
        path=edits.code_repair_directory(TARGET,802)/'current.json'
        record=read_json(path);record.update(status='rejected',platformCode='1010300506')
        atomic_json(path,record)
        with self.assertRaisesRegex(ValueError,'原平台拒绝回执'):
            edits.require_no_pending_code_repair(TARGET,802)
        self.assertEqual(self.confirm()['submissionStatus'],'original-receipt-unconfirmed')
        self.assertEqual(read_json(path)['status'],'submitting')
        self.assertEqual(len(self.writes),1)

    def test_parsed_business_rejection_for_exact_edit_and_payload_is_terminal(self):
        try:
            self.api.parse_response(json.dumps({'success':False,'data':{},'errorList':[{'code':1010300506}]}),
                                    method='POST',url='/rest/sp-product/v0/product-applies')
        except self.api.JdoError as exc:
            self.publication_failure=exc
        self.assertEqual(self.confirm()['status'],'sku-code-repair-rejected')
        path=edits.code_repair_directory(TARGET,802)/'current.json'
        rejected=read_json(path)
        self.assertEqual(rejected['officialRejection']['bodySha256'],rejected['bodySha256'])
        # Crash after the per-attempt refusal landed and before the shared status pointer advanced.
        rejected['status']='submitting';rejected.pop('officialRejection')
        atomic_json(path,rejected)
        self.assertEqual(self.call('--reconcile')['status'],'sku-code-repair-rejected')
        self.assertEqual(self.confirm()['status'],'sku-code-repair-rejected')
        edits.require_no_pending_code_repair(TARGET,802)
        self.assertEqual(len(self.writes),1)

    def test_original_903_rejected_even_when_another_edit_made_online_codes_match(self):
        self.pending=True
        self.assertEqual(self.confirm()['status'],'sku-codes-in-application')
        self.online=deepcopy(self.application)  # the same values reached the product independently
        self.application['applyInfo']={'applyId':903,'draftComputeStatus':3}
        result=self.call('--reconcile')
        self.assertFalse(result['ok'])
        self.assertEqual((result['status'],result['applyId'],result['submissionStatus'],result['applicationOutcome']),
                         ('sku-code-application-rejected',903,'accepted','rejected'))
        self.assertEqual(result['online']['observedCodes'],{'301':'00001','302':'CODE/b'})
        self.assertTrue(result['online']['codesMatch'])
        self.assertEqual(self.confirm()['status'],'sku-code-application-rejected')
        self.assertEqual(len(self.writes),1)
        edits.require_no_pending_code_repair(TARGET,802)
        # A genuinely changed, newly checked official edit can run on the same link.
        self.application['applyInfo']={}
        for detail in (self.online,self.application):
            detail['skuList'][0]['outerId']='correct-after-review'
            detail['productInfo']['productName']='按新资料校正的灯具'
        plan=self.call('--product-id','802','--check-only')
        self.assertEqual(plan['status'],'sku-code-repair-ready')
        self.pending=False
        self.assertEqual(self.confirm()['status'],'sku-codes-verified')
        self.assertEqual(len(self.writes),2)

    def test_different_rejected_apply_cannot_end_original_pending_repair(self):
        self.pending=True
        self.confirm()
        self.online=deepcopy(self.application)
        self.application['applyInfo']={'applyId':904,'draftComputeStatus':3}
        observed=self.call('--reconcile')
        self.assertFalse(observed['ok'])
        self.assertEqual(observed['status'],'different-application-readback')
        self.assertTrue(observed['online']['codesMatch'])
        with self.assertRaisesRegex(ValueError,'商家编码编辑'):
            edits.require_no_pending_code_repair(TARGET,802)
        self.assertEqual(len(self.writes),1)
