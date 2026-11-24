"""Two synthetic verified stores with independent freight and dispatch contracts."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from heideng_merchant.shop_copy_delivery import FREIGHT_API, capture_freight, compare_delivery


SOURCE = {'profile':'source-demo','shopId':'21','venderId':'31'}
TARGET = {'profile':'target-demo','shopId':'22','venderId':'32'}


def detail(pid, sku, freight, promise, override):
    return {'productInfo':{'productId':pid,'logisticsInfo':{'transportId':freight,'promiseId':promise},
                           'features':[{'key':'is7ToReturn','value':'0'},{'key':'isPayFirst','value':'1'}]},
            'skuList':[{'skuId':sku,'logisticsInfo':{'promiseId':override}},
                       {'skuId':sku+1,'logisticsInfo':{'promiseId':None}}]}


def template(tid, rules):
    return {'id':str(tid),'name':'默认模板','complete':True,'selectable':True,
            'receipt':'official-page/fixture/'+str(tid),'rules':rules}


def freight(by='item'):
    return {'payer':'buyer','currency':'CNY','chargeBy':by,'unit':'件' if by=='item' else 'kg',
            'zones':[{'regions':['皖','苏'],'firstQuantity':1,'firstFee':'8.50','nextQuantity':1,'nextFee':2},
                     {'regions':['测试岛'],'type':'excluded'}]}


def side(shop, ids, charge='item'):
    return {'shop':shop,'freightTemplates':[template(ids[0],freight(charge))],
            'promiseTemplates':[template(ids[1],{'commitment':'24小时内发货','cutoff':'15:00'}),
                                template(ids[2],{'commitment':'72小时内发货','holiday':'顺延'})]}


class OwnedShopDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.src=detail(100,501,11,12,13)
        self.dst=detail(200,701,91,92,93)
        self.mapping={'501':'701','502':'702'}
        self.ev={'source':side(SOURCE,(11,12,13)), 'target':side(TARGET,(91,92,93))}

    def compare(self, draft=False):
        return compare_delivery(self.src,None if draft else self.dst,SOURCE,TARGET,self.mapping,self.ev)

    def test_prepare_uses_target_owned_ids_and_verify_checks_every_level(self):
        target=self.ev['target']['freightTemplates'][0]['rules']['zones']
        target.reverse()
        target[1]['regions'].reverse()
        target[1]['firstFee']='8.5'
        plan=self.compare(draft=True)
        self.assertEqual(plan['status'],'ready-to-apply')
        self.assertEqual(plan['targetValues'],{'WareTransport':'91','WarePromise':'92','SkuPromise':{'501':'93'},
                                                'WareSevenDayReturn':'0','isPayFirst':'1'})
        self.assertEqual(self.compare()['status'],'verified')
        self.dst['skuList'][0]['logisticsInfo']['promiseId']=92
        self.dst['productInfo']['features'][0]['value']='1'
        different=[row['field'] for row in self.compare()['checks'] if row['status']=='different']
        self.assertCountEqual(different,['SkuPromise[501]','WareSevenDayReturn'])

    def test_equal_names_never_hide_freight_differences_and_partial_data_stays_unknown(self):
        source=freight('weight')
        self.ev['source']['freightTemplates'][0]['rules']=source
        for key,value in [('payer','seller'),('chargeBy','item'),('unit','斤'),('currency','USD'),
                          ('threshold','满200免邮')]:
            with self.subTest(key=key):
                self.ev['target']['freightTemplates'][0]['rules']={**source,key:value}
                result=self.compare()
                self.assertEqual(result['status'],'different')
                self.assertNotIn('WareTransport',result['targetValues'])
        for key,value in [('firstFee','3.2'),('nextFee','5'),('firstQuantity',2),('nextQuantity',3),('regions',['苏'])]:
            with self.subTest(key=key):
                changed=deepcopy(source)
                changed['zones'][0][key]=value
                self.ev['target']['freightTemplates'][0]['rules']=changed
                self.assertEqual(self.compare()['status'],'different')
        self.ev['target']['freightTemplates'][0]['rules']={'payer':'buyer'}
        result=self.compare()
        self.assertIn('WareTransport',result['needsEvidence'])
        self.assertNotIn('WareTransport',result['targetValues'])

    def test_default_freight_and_ware_level_time_need_explicit_effective_rules(self):
        for record in (self.src,self.dst):
            record['productInfo']['logisticsInfo'].update(transportId='',promiseId=None)
        result=self.compare()
        self.assertIn('WareTransport',result['needsEvidence'])
        self.assertIn('defaultPromise',result['needsEvidence'])
        for side_name in ('source','target'):
            evidence=self.ev[side_name]
            evidence['defaultFreight']={'complete':True,'receipt':'official-page/default','rules':{
                'payer':'seller','zones':[{'regions':['苏','皖']}]}}
            evidence['defaultPromise']={'complete':True,'receipt':'official-page/default',
                                        'rules':{'commitment':'48小时内发货','holiday':'不顺延'}}
        self.assertEqual(self.compare()['status'],'verified')
        self.ev['target']['defaultFreight']['rules']['zones'][0]['regions']=['全国']
        self.assertEqual(self.compare()['status'],'different')

    def test_unknown_sku_level_does_not_inherit_until_actual_page_shows_it(self):
        del self.src['skuList'][1]['logisticsInfo']
        self.assertIn('SkuPromise[502]',self.compare()['needsEvidence'])
        self.ev['source']['productSelections']={'productId':'100','receipt':'official-edit/100','SkuPromise':{'502':None}}
        self.assertEqual(self.compare()['status'],'verified')
        self.ev['source']['productSelections']['productId']='101'
        self.assertIn('SkuPromise[502]',self.compare()['needsEvidence'])
        self.ev['target']['shop']=SOURCE
        with self.assertRaisesRegex(ValueError,'店铺或 Profile'):
            self.compare()

    def test_different_categories_reuse_observed_item_or_weight_terms_only(self):
        for category,method in ((3101,'item'),(9102,'weight')):
            with self.subTest(category=category,method=method):
                self.src['productInfo']['categoryDetail']={'lastCategoryId':category}
                self.dst['productInfo']['categoryDetail']={'lastCategoryId':category}
                self.ev={'source':side(SOURCE,(11,12,13),method),'target':side(TARGET,(91,92,93),method)}
                row=self.ev['target']['freightTemplates'][0]
                row.pop('selectable')
                self.ev['target']['schemaOptionIds']={'WareTransport':[]}
                pending=self.compare(draft=True)
                self.assertIn('WareTransport',pending['needsEvidence'])
                self.ev['target']['schemaOptionIds']['WareTransport']=['91']
                self.assertEqual(self.compare(draft=True)['targetValues']['WareTransport'],'91')
                self.assertEqual(self.compare()['status'],'verified')
                row['readSha256']='uncorroborated'
                self.assertIn('WareTransport',self.compare()['needsEvidence'])

    def test_empty_options_still_read_applied_id_via_current_card_and_exact_profile(self):
        api=Mock()
        api.require_verified_jdo_store.return_value=SOURCE
        card={'apiName':FREIGHT_API,'method':'GET','path':'/rest/sp-seller/v0/shipping-templates/{templateId}',
              'inputSchema':{'type':'object','required':['templateId'],'properties':{'templateId':{'type':'integer'}}}}
        def read(argv):
            self.assertEqual(argv[argv.index('--profile')+1],SOURCE['profile'])
            if argv[0]=='info':return card
            self.assertEqual(argv[argv.index('--method')+1],'GET')
            self.assertEqual(argv[argv.index('--url')+1],card['path'])
            return {'success':True,'data':{'templateId':json.loads(argv[argv.index('--params')+1])['templateId']},
                    'requestId':'read-fixture'}
        api.run_jdo.side_effect=read
        schema=[{'componentCode':'WareTransport','optionsValueList':[]}]
        result=capture_freight(api,self.src,schema,SOURCE,template_ids=[15])
        self.assertEqual(set(result['freightReads']),{'11','15'})
        self.assertEqual(result['freightReads']['11']['requestId'],'read-fixture')
        api.run_jdo.reset_mock()
        self.src['productInfo']['logisticsInfo']['transportId']=None
        self.assertEqual(capture_freight(api,self.src,schema,SOURCE)['status'],'needs-template-id')
        api.run_jdo.assert_not_called()
        self.src['productInfo']['logisticsInfo']['transportId']='11'
        card['method']='POST'
        self.assertEqual(capture_freight(api,self.src,schema,SOURCE)['status'],'needs-official-page')
        self.assertEqual(api.run_jdo.call_count,1)

    def test_live_card_definitions_can_interpret_rates_without_guessing_numeric_codes(self):
        zones = [{'where':['皖','苏'],'start':1,'base':'8.5','step':1,'extra':'2'}]
        data = {'tid':11,'payerCode':7,'chargeBy':'weight','unit':'kg','currency':'CNY','zones':zones,
                'additionalCondition':'限普通配送'}
        zone_schema = {k:{'title':label} for k,label in (
            ('where','配送区域'),('start','首重'),('base','首重费用'),('step','续重'),('extra','续重费用'))}
        fields = {'tid':{'title':'运费模板ID'},'payerCode':{'title':'运费承担方','oneOf':[{'const':7,'title':'买家承担'}]},
                  'chargeBy':{},'unit':{},'currency':{},'additionalCondition':{},
                  'zones':{'type':'array','items':{'type':'object','properties':zone_schema}}}
        card={'apiName':FREIGHT_API,'method':'GET','path':'/rest/sp-seller/v0/shipping-templates/{templateId}',
              'inputSchema':{'type':'object','properties':{'templateId':{'type':'integer'}}},
              'outputSchema':{'type':'object','properties':fields}}
        api=Mock()
        api.require_verified_jdo_store.return_value=SOURCE
        api.run_jdo.side_effect=lambda argv:card if argv[0]=='info' else {'success':True,'data':data}
        result=capture_freight(api,self.src,[],SOURCE)
        template=result['freightTemplates'][0]
        self.assertEqual(template['readSha256'],result['freightReads']['11']['sha256'])
        self.assertEqual(template['rules']['payer'],'buyer')
        self.assertEqual(template['rules']['additionalCondition'],'限普通配送')
        self.assertEqual(template['rules']['zones'][0]['nextFee'],'2')
        del fields['payerCode']['oneOf']
        self.assertFalse(capture_freight(api,self.src,[],SOURCE).get('freightTemplates'))
        fields['payerCode']['oneOf']=[{'const':7,'title':'买家承担'}]
        del data['additionalCondition']
        self.assertFalse(capture_freight(api,self.src,[],SOURCE).get('freightTemplates'))
