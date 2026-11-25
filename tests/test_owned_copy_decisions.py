"""Local review, independent SKU identity and target-verified structured sale attributes."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from heideng_merchant import owned_product_copy as copy
from mature.listing.scripts.sale_attr_templates import from_official
from tests.test_owned_product_copy import sample, reference, SOURCE, TARGET


def template_for_text(attr_id, choices):
    values=[{'id':value_id,'name':value} for value,value_id in choices.items()]
    item={'properties':{'id':{'enum':['finish']},
                        'value':{'enum':[{'preprocessingSaleAttrValTemplateValueList':values}]}},
          'features':{'isLocked':True,'text':'饰面'}}
    rows=[{'templateType':'2','templateData':json.dumps([{'attrId':attr_id,
            'valueRules':json.dumps({'items':[item],'title':'饰面'})}])}]
    return from_official(rows,attr_id)


class OwnedCopyDecisionTests(unittest.TestCase):
    def setUp(self):
        self.src=sample()
        self.dst=sample(True)
        self.ref=reference()
        self.ref['structuredSaleTemplates']={'25':template_for_text('25',{'白':710,'蓝':720})}
        self.enterContext(patch('heideng_merchant.shop_copy_delivery.compare_delivery',
            side_effect=lambda src,dst,*args,**kw:{'status':'verified' if dst else 'ready-to-apply','targetValues':{}}))

    def freeze(self):
        return copy.freeze_copy(SOURCE,TARGET,self.src,video_rows={'201':[],'202':[]})

    def compare(self,**kwargs):
        return copy.compare_copy(self.freeze(),TARGET,self.dst,video_rows={'301':[],'302':[]},**kwargs)

    def test_swapped_codes_are_two_real_mismatches_not_two_self_matches(self):
        self.dst['skuList'][0]['outerId'],self.dst['skuList'][1]['outerId']=(
            self.dst['skuList'][1]['outerId'],self.dst['skuList'][0]['outerId'])
        report=self.compare()
        self.assertEqual(report['skuPairs'],{'201':'301','202':'302'})
        self.assertEqual(report['merchantCodeCoverage'],{'sourceSkuCount':2,'independentlyPaired':2,
                                                       'verified':0,'different':2,'unverified':0})

    def test_absent_category_controls_are_outside_draft_scope_only_with_two_templates(self):
        self.ref.pop('structuredSaleTemplates')
        for detail in (self.src,self.dst):
            detail['productInfo'].pop('height')
            for row in detail['skuList']:
                row.pop('upcCode')
        nodes = self.ref['schema']['componentList']
        nodes[:] = [n for n in nodes if n['componentCode'] != 'WareHeight']
        frozen = copy.freeze_copy(SOURCE,TARGET,self.src,source_components=nodes,video_rows={'201':[],'202':[]})
        media = {url:{url} for url in copy.plan_copy(frozen)['imageUrls']}
        _,gaps,_ = copy._prepare_schema(frozen,self.ref,media,{'status':'ready-to-apply'})
        self.assertEqual(gaps,[])
        fields = {'packaging.height','sku.201.upcCode','sku.202.upcCode'}
        self.assertEqual(copy.outside_creation_templates(frozen,self.ref),fields)
        result = copy.compare_copy(frozen,TARGET,self.dst,video_rows={'301':[],'302':[]},target_schema=self.ref)
        self.assertEqual(set(result['outsideTemplateFields']), fields)
        self.assertFalse(fields & {c['field'] for c in result['checks']})
        nodes.append({'componentCode':'WareHeight'})
        _,gaps,_ = copy._prepare_schema(frozen,self.ref,media,{'status':'ready-to-apply'})
        self.assertTrue(any('WareHeight' in x for x in gaps))
        self.assertEqual(copy.outside_creation_templates(self.freeze(),self.ref),set())

    def test_nonempty_packing_uses_only_explicit_target_field_mapping(self):
        self.ref.pop('structuredSaleTemplates')
        self.src['productInfo']['packSpecification'] = '12袋×5克'
        frozen = self.freeze()
        media = {url:{url} for url in copy.plan_copy(frozen)['imageUrls']}
        delivery = {'status':'ready-to-apply'}
        _,gaps,_ = copy._prepare_schema(frozen,self.ref,media,delivery)
        self.assertTrue(any('packSpecification' in g for g in gaps))
        self.ref['schema']['componentList'].append({'componentCode':'WarePacking','productDetailField':'productInfo.packSpecification'})
        body,gaps,_ = copy._prepare_schema(frozen,self.ref,media,delivery)
        self.assertEqual(gaps,[])
        self.assertEqual(next(c['value'] for c in body if c['componentCode']=='WarePacking'),'12袋×5克')

    def test_equal_duplicate_codes_are_allowed_but_cannot_disambiguate_specifications(self):
        for row in self.src['skuList']+self.dst['skuList']:row['outerId']='00100'
        self.assertEqual(self.compare()['merchantCodeCoverage']['verified'],2)
        self.dst['skuList'][0]['saleAttrs']=deepcopy(self.dst['skuList'][1]['saleAttrs'])
        report=self.compare()
        self.assertEqual(report['skuPairs'],{})
        self.assertEqual(report['merchantCodeCoverage']['unverified'],2)
        self.assertIn('target-specifications-not-unique',report['skuPairingEvidence']['reasons'].values())

    def test_local_draft_keeps_unknown_optional_fields_and_explicit_zero_without_target_writes(self):
        self.src['skuList'][0].pop('upcCode')
        self.src['productInfo']['packSpecification']='每盒1件'
        self.src['material'].pop('rectangleImages')
        frozen=copy.freeze_copy(SOURCE,TARGET,self.src,video_rows={'201':[]})
        with patch.object(copy,'_media',side_effect=AssertionError('no staged media')), \
                patch('heideng_merchant.shop_copy_delivery.compare_delivery',side_effect=AssertionError('no target rules')):
            draft=copy.local_copy_draft(frozen)
        self.assertEqual(draft['status'],'local-draft-ready')
        self.assertIsNone(draft['approvalFingerprint'])
        self.assertFalse(draft['publicationChecked'])
        self.assertEqual(draft['platformWrites'],0)
        by_id={s['sourceSkuId']:s for s in draft['skuRows']}
        self.assertEqual(by_id['201']['stock'],0)
        self.assertIsNone(by_id['201']['upcCode'])
        self.assertEqual(by_id['201']['videoIds'],[])
        self.assertIsNone(by_id['202']['videoIds'])
        self.assertEqual(by_id['201']['mainImages'],['hero1','angle1','size1'])
        self.assertTrue({'sku.201.upcCode','sku.202.videoIds','packSpecification'}<=set(draft['missing']))
        self.assertEqual(draft['product']['packSpecification'],'每盒1件')
        strict=copy.prepare_copy_schema(frozen,TARGET,reference())
        self.assertEqual(strict['status'],'needs-evidence')

    def test_official_structured_box_remaps_option_ids_without_changing_raw_business_values(self):
        for product,ids in ((self.src,{'白':100,'蓝':200}),(self.dst,{'白':710,'蓝':720})):
            for row in product['skuList']:
                axis=row['saleAttrs'][0]
                axis['templateSkuProps']=[{'id':'finish','value':axis['attrValueAlias'],'valueId':ids[axis['attrValueAlias']]}]
        frozen=self.freeze()
        media={url:{url} for url in copy.plan_copy(frozen)['imageUrls']}
        schema,missing,_=copy._prepare_schema(frozen,self.ref,media,{'status':'ready-to-apply','targetValues':{}})
        self.assertEqual(missing,[])
        sku=next(n for n in schema if n['componentCode']=='SKUS')['value'][0]
        sales=next(n for n in sku['value'] if n['componentCode']=='VenderCategoryValue')['value'][0]
        props={p['key']:p['value'] for p in sales['properties']}
        self.assertEqual(props['attrValueAlias'],'[白]')
        self.assertEqual(json.loads(props['templateSkuProps']),[{'id':'finish','value':'白','valueId':710}])
        self.assertEqual(self.compare(target_schema=self.ref)['status'],'verified')
        self.assertEqual(self.compare()['status'],'needs-evidence')
        self.dst['skuList'][0]['saleAttrs'][0]['templateSkuProps'][0]['valueId']=999
        self.assertEqual(self.compare(target_schema=self.ref)['status'],'different')

    def test_scalar_can_fill_one_proven_target_option_only_without_tokenising_alias(self):
        report=self.freeze()
        for row in self.dst['skuList']:
            axis=row['saleAttrs'][0]
            axis['templateSkuProps']=[{'id':'finish','value':axis['attrValueAlias'],'valueId':710 if axis['attrValueAlias']=='白' else 720}]
        self.assertEqual(self.compare(target_schema=self.ref)['status'],'verified')
        target=deepcopy(self.ref)
        target['structuredSaleTemplates']['25']['inputs'].append({'id':'extra','text':'附加','options':[]})
        _,missing,_=copy._prepare_schema(report,target,{url:{url} for url in copy.plan_copy(report)['imageUrls']},{'status':'ready-to-apply'})
        self.assertTrue(any('不按标签切词' in text for text in missing))

    def test_wrong_units_unmapped_boxes_and_conflicting_options_are_never_silently_dropped(self):
        attr={'attrId':42,'attrValueAlias':'25cm','templateSkuProps':[{'id':'measure','value':'25','unit':'cm'}]}
        target={'attrId':'42','inputs':[{'id':'measure','unit':'cm'}],'source':{'kind':'official-interface'}}
        ref={**self.ref,'structuredSaleTemplates':{'42':target}}
        self.assertEqual(copy._target_props(attr,{},ref),[{'id':'measure','value':'25','unit':'cm'}])
        for change in ({'unit':'mm'},{'id':'other'},{'locked':True,'options':[]},
                       {'options':[{'value':'25','valueId':1},{'value':'25','valueId':2}]}):
            bad=deepcopy(ref);bad['structuredSaleTemplates']['42']['inputs'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):copy._target_props(attr,{},bad)
