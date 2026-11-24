"""Two synthetic stores with different IDs, image URLs and SKU ordering; no remote operations."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from heideng_merchant import owned_product_copy as copy
from heideng_merchant.safety import file_sha


SOURCE={'profile':'lantern-source','shopName':'甲灯具','shopId':'910','venderId':'110'}
TARGET={'profile':'lantern-target','shopName':'乙灯具','shopId':'920','venderId':'120'}


def sample(target=False):
    pid=802 if target else 701
    first=300 if target else 200
    prefix='target' if target else 'source'
    def group(gid,urls):
        return {'uuid':gid,'imageInfoList':[{'orderSort':pos,'imgUrl':url} for pos,url in enumerate(urls,1)]}
    groups=[group(copy.PUBLIC_GROUP,['shared','features'])]
    rows=[]
    specs=[]
    for n,color in enumerate(('白','蓝'),1):
        sid=first+n
        gid=prefix+'group'+str(n)
        groups.append(group(gid,[f'hero{n}',f'angle{n}',f'size{n}']))
        specs.append({'uuid':str(sid),'imageUrl':f'spec{n}'})
        rows.append({'skuId':sid,'productId':pid,'outerId':('000134','LED/A-9')[n-1],'logo':f'hero{n}',
                     'saleAttrs':[{'attrId':25,'attrName':'饰面','attrValueAlias':color,'attrValues':gid,'dim':1,'attrValuesSeqNo':n}],
                     'priceInfo':{'jdPrice':('18.50','22.75')[n-1]},'stockNum':(0,17)[n-1],'skuEnableStatus':1,
                     'upcCode':'', 'goodsAttrInfos':[]})
    return {'productInfo':{'productId':pid,'productName':'合成阅读灯','brandInfo':{'brandId':12},'itemNum':'L-008',
                           'categoryDetail':{'lastCategoryId':800},'goodsAttrInfos':[],'length':210,'wide':120,
                           'height':80,'weight':'.52','packSpecification':'',
                           'productDetailDesc':{'desc':'<p>使用说明<img src="detail1"><img src="detail2"></p>',
                                                'mobileDesc':'<p><img data-src="mobile1"></p>'}},
            'skuList':list(reversed(rows)) if target else rows,
            'material':{'mainImages':groups,'rectangleImages':[],'ggtImages':specs}}


def reference():
    codes=('WareTitle WareItemnum WareBrand WareSkuImg WareEditor WareLength WareWide WareHeight WareWeight '
           'SKUS SKU SkuVendorSku SkuJdprice SkuStockNum SkuEnableStatus SkuMainImage VenderCategoryValue sale-prop-25')
    return {'shopIdentity':TARGET,'category':{'id':800},'brands':[{'brandId':12}],
            'schema':{'componentList':[{'componentCode':c} for c in codes.split()]}}


class OwnedProductCopyTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source=sample()
        self.target=sample(True)
        self.frozen=copy.freeze_copy(SOURCE,TARGET,self.source,video_rows={'201':[],'202':[]})
        def delivery(src,dst,*args,**kwargs):
            return {'status':'verified' if dst else 'ready-to-apply','targetValues':{}}
        self.enterContext(patch('heideng_merchant.shop_copy_delivery.compare_delivery',side_effect=delivery))

    def compare(self,**kwargs):
        return copy.compare_copy(self.frozen,TARGET,self.target,video_rows={'301':[],'302':[]},**kwargs)

    def evidence(self):
        images=[]
        for index,url in enumerate(copy.plan_copy(self.frozen)['imageUrls']):
            path=self.root/f'source-{index}'
            path.write_bytes(b'original-image-'+str(index).encode())
            digest=file_sha(path)
            images.append({'sourceUrl':url,'sourceFile':str(path),'sourceSha256':digest,'uploadReceipt':{
                'shopIdentity':TARGET,'status':'accepted','sha256':digest,'imgUrl':'dst-'+url}})
        return {'sourceShop':SOURCE,'targetShop':TARGET,'sourceProductId':'701','images':images}

    def test_official_sku_ids_may_change_while_merchant_codes_gallery_group_ownership_and_order_match(self):
        result=self.compare()
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['skuPairs'],{'201':'301','202':'302'})
        self.assertEqual(result['consumerPageStatus'],'unchecked')
        self.assertEqual(result['packagingListStatus'],'needs-evidence')
        self.target['skuList'][0]['outerId']='invented-0001'
        self.target['skuList'][1]['stockNum']=500
        self.target['material']['mainImages'][2]['imageInfoList'].pop()
        self.target['productInfo']['weight']='2.0'
        self.target['productInfo']['productDetailDesc']['mobileDesc']='<p>手机端变了</p>'
        result=self.compare()
        differences={c['field'] for c in result['checks'] if c['status']=='different'}
        self.assertTrue({'sku.202.merchantSku','sku.201.stock','packaging.weight','mainGroups.sourcegroup2.count',
                         'details.mobileDesc.markupAndText'}<=differences)

    def test_reordered_secondary_gallery_or_ambiguous_group_relation_cannot_pass(self):
        items=self.target['material']['mainImages'][1]['imageInfoList']
        items[0]['imgUrl'],items[2]['imgUrl']=items[2]['imgUrl'],items[0]['imgUrl']
        self.assertEqual(self.compare()['status'],'different')
        self.target=sample(True)
        row=self.target['skuList'][0]
        row['saleAttrs'][0].update(dim=2,attrValues='targetgroup2')
        self.assertTrue(any(c['status']=='needs-evidence' and c['field'].endswith('.ownership')
                            for c in self.compare()['checks']))

    def test_target_draft_uses_every_position_zero_stock_original_codes_and_separate_pc_mobile_text(self):
        media=self.evidence()
        draft=copy.prepare_copy_schema(self.frozen,TARGET,reference(),media_evidence=media)
        self.assertEqual(draft['status'],'ready',draft['missing'])
        top={c['componentCode']:c['value'] for c in draft['schema']}
        skus=[{c['componentCode']:c['value'] for c in r['value']} for r in top['SKUS']]
        self.assertEqual([(s['SkuVendorSku'],s['SkuStockNum'],s['SkuJdprice']) for s in skus],
                         [('000134',0,'18.5'),('LED/A-9',17,'22.75')])
        def props(item):return {x['key']:x['value'] for x in item['properties']}
        groups={}
        for item in top['WareSkuImg']:
            row=props(item)
            groups.setdefault(row['colorId'],[]).append(row['imgUrl'])
        self.assertEqual(groups[copy.PUBLIC_GROUP],['dst-shared','dst-features'])
        for n,s in enumerate(skus,1):
            gid=props(s['VenderCategoryValue'][0])['mappingId']
            self.assertEqual(groups[gid],[f'dst-hero{n}',f'dst-angle{n}',f'dst-size{n}'])
            self.assertEqual([props(img)['imgUrl'] for img in s['SkuMainImage']],groups[gid])
        pc,mobile=(props(d)['desc'] for d in top['WareEditor'])
        self.assertIn('使用说明',pc)
        self.assertLess(pc.index('dst-detail1'),pc.index('dst-detail2'))
        self.assertIn('dst-mobile1',mobile)
        self.assertNotIn('detail2',mobile)
        self.assertEqual(len([x for x in draft['followUp'] if isinstance(x,dict)]),2)

    def test_original_bytes_and_target_identity_are_required_for_changed_media_urls(self):
        self.target['material']['mainImages'][0]['imageInfoList'][0]['imgUrl']='dst-shared'
        self.assertEqual(self.compare()['status'],'needs-evidence')
        media=self.evidence()
        self.assertEqual(self.compare(media_evidence=media)['status'],'verified')
        wrong=deepcopy(media);wrong['images'][0]['uploadReceipt']['shopIdentity']=SOURCE
        with self.assertRaises(ValueError):self.compare(media_evidence=wrong)
        Path(media['images'][0]['sourceFile']).write_bytes(b'other bytes')
        with self.assertRaises(ValueError):self.compare(media_evidence=media)

    def test_unknown_inventory_media_and_shipping_template_never_inherit_historical_defaults(self):
        self.frozen=copy.freeze_copy(SOURCE,TARGET,self.source,stock_rows=[{'skuId':201,'stockNum':0}])
        ref=reference()
        ref['schema']['componentList'].append({'componentCode':'prop-sku-other','validateRule':[{'validateType':'required','validateRule':'true'}]})
        draft=copy.prepare_copy_schema(self.frozen,TARGET,ref)
        self.assertEqual(draft['status'],'needs-evidence')
        self.assertTrue(any('SkuStockNum' in msg for msg in draft['missing']))
        self.assertTrue(any('prop-sku-other' in msg for msg in draft['missing']))
        self.assertTrue(any('素材' in msg for msg in draft['missing']))
        self.assertTrue(any('视频' in msg for msg in draft['missing']))
        self.assertFalse(any(c.get('componentCode')=='WareTransport' for c in draft['schema']))
        self.assertEqual(self.compare()['status'],'needs-evidence')

    def test_two_size_skus_with_distinct_direct_galleries_must_not_collapse_into_one_colour(self):
        self.source['material']['mainImages'][1]['uuid']='201'
        self.source['material']['mainImages'][2]['uuid']='202'
        for i,sku in enumerate(self.source['skuList']):
            sku['saleAttrs'][0].update(attrValueAlias='绿色',attrValues='shared-colour')
            sku['saleAttrs'].append({'dim':2,'attrId':26,'attrName':'尺码','attrValueAlias':['S','M'][i],
                                     'attrValues':str(990+i),'attrValuesSeqNo':i+1})
        self.frozen=copy.freeze_copy(SOURCE,TARGET,self.source)
        ref=reference();ref['schema']['componentList'].append({'componentCode':'sale-prop-26'})
        draft=copy.prepare_copy_schema(self.frozen,TARGET,ref,media_evidence=self.evidence())
        self.assertTrue(any('多个源图组' in msg for msg in draft['missing']))

    def test_fidelity_ignores_observation_timestamp_but_detects_delivery_sale_order_and_detail_flag_changes(self):
        self.source['productInfo'].update(logisticsInfo={'transportId':'A','promiseId':'B'},
                                         features=[{'key':'isPayFirst','value':'1'},{'key':'is7ToReturn','value':'1'}])
        self.source['skuList'][0]['logistics']={'promiseId':'old'}
        def projection(data):
            return copy.source_fidelity(copy.freeze_copy(SOURCE,TARGET,data,video_rows={'201':[],'202':[]}))
        expected=projection(self.source)
        changed=deepcopy(self.source)
        changed['productInfo'].update(modifiedTime='later')
        changed['skuList'].reverse()
        self.assertEqual(expected,projection(changed))
        for section,key,value in [('product','transportId','new'),('sku','promiseId',None),
                                  ('feature','value','0'),('sale','attrValuesSeqNo',77),('detail','zhuangBaUseFlag',1)]:
            with self.subTest(section=section):
                data=deepcopy(self.source)
                parts={'product':data['productInfo']['logisticsInfo'],'sku':data['skuList'][0]['logistics'],
                       'feature':data['productInfo']['features'][0],'sale':data['skuList'][0]['saleAttrs'][0],
                       'detail':data['productInfo']['productDetailDesc']}
                parts[section][key]=value
                self.assertNotEqual(expected,projection(data))

    def test_wrong_store_changed_snapshot_and_original_product_as_target_are_rejected(self):
        with self.assertRaises(ValueError):copy.compare_copy(self.frozen,SOURCE,self.target)
        with self.assertRaises(ValueError):copy.compare_copy(self.frozen,TARGET,self.source)
        self.frozen['sourceDetail']['skuList'][0]['stockNum']=500
        with self.assertRaisesRegex(ValueError,'快照'):copy.plan_copy(self.frozen)

    def test_absent_source_fields_block_one_sample_but_known_post_create_bindings_are_explicit(self):
        self.source['skuList'][0].pop('upcCode')
        self.source['material'].pop('ggtImages')
        self.source['material'].pop('rectangleImages')
        self.frozen=copy.freeze_copy(SOURCE,TARGET,self.source,video_rows={'202':[{'videoMaterial':{'videoId':9001}}]})
        result=copy.prepare_copy_schema(self.frozen,TARGET,reference(),media_evidence=self.evidence())
        self.assertEqual(result['status'],'needs-evidence')
        reasons=' '.join(result['missing'])
        for field in ('201 条码','201 的规格图','rectangleGroups','201 的主图视频'):
            self.assertIn(field,reasons)
        self.assertEqual(result['followUp'],[{'action':'verify-and-bind-main-video','sourceSkuId':'202','sourceVideoIds':['9001']}])

    def test_single_public_group_zero_stock_no_brand_and_verified_barcode_component_in_another_category(self):
        item=self.source['productInfo']
        item.update(productName='单本线装笔记本',itemNum='NOTE-00',categoryDetail={'lastCategoryId':970},brandInfo={'brandId':-1})
        self.source['skuList']=self.source['skuList'][:1]
        self.source['skuList'][0].update(saleAttrs=[],logo='shared',upcCode='0001200345000')
        self.source['material'].update(mainImages=self.source['material']['mainImages'][:1],ggtImages=[])
        self.frozen=copy.freeze_copy(SOURCE,TARGET,self.source,video_rows={'201':[]})
        ref=reference();ref.update(category={'id':970},brands=[])
        ref['schema']['componentList'].append({'componentCode':'SkuUpcCode'})
        media=self.evidence()
        without=copy.prepare_copy_schema(self.frozen,TARGET,ref,media_evidence=media)
        self.assertTrue(any('品牌' in v for v in without['missing']))
        node=next(c for c in ref['schema']['componentList'] if c['componentCode']=='WareBrand')
        node['optionsValueList']=[{'label':'无品牌','value':-1}]
        result=copy.prepare_copy_schema(self.frozen,TARGET,ref,media_evidence=media)
        self.assertEqual(result['status'],'ready',result['missing'])
        top={c['componentCode']:c['value'] for c in result['schema']}
        sku={c['componentCode']:c['value'] for c in top['SKUS'][0]['value']}
        self.assertEqual(top['WareBrand'],-1)
        self.assertEqual((top['WareItemnum'],sku['SkuUpcCode'],sku['SkuVendorSku'],sku['SkuStockNum']),
                         ('NOTE-00','0001200345000','000134',0))
        self.assertNotIn('VenderCategoryValue',sku)
        ref['schema']['componentList'].append({'componentCode':'SkuWareUpccode'})
        ambiguous=copy.prepare_copy_schema(self.frozen,TARGET,ref,media_evidence=media)
        self.assertTrue(any('条码' in v for v in ambiguous['missing']))
