"""Merchant plan, local publication body and evidence without platform or model calls."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

from tests.test_mature_listing import module


class ListingFeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.pl = module('photo_listing')
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name,size,color in [('front',(800,800),'green'),('detail',(790,1250),'orange')]:
            Image.new('RGB', size, color).save(self.root / (name+'.jpg'))

    def fixture(self, dimensions):
        manifest = self.pl.initial_manifest(
            {'profile':'pop-fixture','venderId':100,'shopName':'合成测试商家'},
            ['front.jpg','detail.jpg'], '测试产品', None)
        manifest['packageId'] = 'fixture-package'
        fields = [{'componentCode':'sale-prop-'+str(i+1), 'componentTitle':name,'extra':{'dim':i+1}}
                  for i,name in enumerate(dimensions)]
        reference = {'category':{'id':3}, 'brands':[{'brandId':-1}], 'componentCatalog':[],
                     'media':{'defaultCategoryId':9,'categories':[{'categoryId':9}]},
                     'schema':{'componentList':fields}}
        manifest['facts'] = {'confirmed':True, 'brandId':-1, 'title':'测试产品','categoryId':3,
            'saleDimensions':dimensions, 'categoryAttributes':[], 'requiredDetailTopics':['适用范围','规格'],
            'freightTemplateId':1,'sevenDayReturnCode':'1','skus':[]}
        design = [{'id':'main','role':'main','reusePhoto':'front.jpg'}]
        for index in range(2 if dimensions else 1):
            key = str(index)
            attrs = {name: (name+'甲' if i<len(dimensions)-1 else name+key)
                     for i,name in enumerate(dimensions)}
            manifest['facts']['skus'].append({'key':key,'spec':'规格'+key,'attributes':attrs,
                'jdPrice':'10.00','stock':3,'skuAttributes':[]})
            design.append({'id':'sku-'+key,'role':'sku','skuKey':key,'reusePhoto':'front.jpg'})
        design.append({'id':'detail','role':'detail','kind':'usage','covers':['适用范围','规格'],
                       'reusePhoto':'detail.jpg'})
        self.pl.atomic_json(self.root/'manifest.json', manifest)
        self.pl.atomic_json(self.root/'reference.json', reference)
        return manifest,reference,{'images':design}

    def test_complete_free_plan_to_actual_variable_dimension_body(self):
        pl,root = self.pl,self.root
        for dimensions in [[],['装量'],['颜色','长度'],['颜色','容量','套装']]:
            with self.subTest(dimensions=dimensions):
                manifest, reference, design = self.fixture(dimensions)
                outcome = pl.make_plan(root, reference, design=design)
                self.assertEqual(outcome['quote']['estimatedPaidImageCount'],0)
                self.assertEqual(pl.generate_plan(root)['submittedCount'], 0)
                listing = pl.build_listing(pl.read_manifest(root),root,reference)
                for item in listing['images']:
                    # Identical original pixels resolve to the same gallery reference.
                    item['upload']={'imgUrl':'jfs/'+('detail' if item['role']=='detail' else 'front')}
                schema = {c['componentCode']:c for c in pl.cli.build_publish_schema(listing)}
                for sku, group in zip(listing['skus'], schema['SKUS']['value']):
                    components = {c['componentCode']:c for c in group['value']}
                    sale = components.get('VenderCategoryValue',{}).get('value',[])
                    self.assertEqual([r['componentCode'] for r in sale],listing['product']['saleDimensionCodes'])
                    self.assertEqual(len(sale),len(dimensions))
                    names = [{p['key']:p['value'] for p in r['properties']} for r in sale]
                    self.assertEqual([v['attrName'] for v in names],dimensions)
                    self.assertEqual([v['attrValueAlias'][1:-1] for v in names],
                                     pl.cli.expected_sale_aliases(listing['product'],sku))

    def test_late_failure_cases_are_rejected_before_a_quote(self):
        m,ref,design = self.fixture(['容量','颜色','套装'])
        ref['schema']['componentList'][2]['extra']['isStructure']=True
        with self.assertRaisesRegex(ValueError,'templateSkuProps'):
            self.pl.make_plan(self.root,ref,design=design)
        self.assertFalse((self.root/'image-quote.json').exists())
        for sku in m['facts']['skus']:
            sku['saleTemplateProps']={'sale-prop-3':[{'name':'型号','value':'示例'}]}
        self.pl.atomic_json(self.root/'manifest.json',m)
        self.pl.make_plan(self.root,ref,design=design)
        missing = dict(design, images=[dict(image,covers=[]) for image in design['images']])
        with self.assertRaisesRegex(ValueError,'详情页还需说明：适用范围'):
            self.pl.make_plan(self.root,ref,design=missing)
        # A merchant may request a paid sample before any publication facts exist.
        m['facts']={}
        preview = {'images':[{'id':'sample','role':'main','prompt':'展示外观','photos':['front.jpg']}]}
        self.assertEqual(len(self.pl.prepare_creative_plan(m,self.root,{},preview,preview=True)[0]),1)

    def test_published_three_dimension_readback_requires_real_receipt_and_correct_sku_image(self):
        pl, root = self.pl,self.root
        _, ref, design = self.fixture(['颜色','容量','组合'])
        pl.make_plan(root,ref,design=design)
        pl.generate_plan(root)
        manifest = pl.read_manifest(root)
        listing = pl.build_listing(manifest,root,ref)
        for image in listing['images']:
            image['upload'] = {'imgUrl':'jfs/'+image['role']}
        pl.atomic_json(root/'listing.json',listing)
        manifest['productId'] = 99
        pl.atomic_json(root/'manifest.json',manifest)
        rows = []
        for i, sku in enumerate(listing['skus'], 1):
            sale = [{'attrId':v['componentCode'].removeprefix('sale-prop-'),
                     'attrValueAlias':v['alias'],'attrValues':v['mappingId']} for v in sku['saleValues']]
            rows.append({'outerId':sku['vendorSku'],'skuId':i,'priceInfo':{'jdPrice':sku['jdPrice']},
                         'skuEnableStatus':1,'skuStats':{'onOffShelfStatus':1},'logo':'jfs/sku_main',
                         'saleAttrs':list(reversed(sale))})
        detail = {'skuList':rows,'productInfo':{'productId':99,'productName':listing['product']['title'],
                                                'productStatus':{'productStatusNew':103}}}
        first_group = listing['skus'][0]['saleValues'][0]['mappingId']
        groups = [{'uuid':key,'imageInfoList':[{'orderSort':1,'imgUrl':img}]}
                  for key,img in [('0000000000','jfs/spu_main'),(first_group,'jfs/sku_main')]]
        html = pl.dp.detail_html([pl.cli.detail_image_url('jfs/detail')])
        apply = {'material':{'mainImages':groups},'productInfo':{'productDetailDesc':{'desc':html,'mobileDesc':html}}}
        def response(_skill,url,_params):
            return {'data':apply if 'product-apply' in url else detail}
        with patch.object(pl,'verify_store'), patch.object(pl.cli,'get',side_effect=response), \
                patch.object(pl.cli,'query_sku_stocks',return_value=[{'skuId':r['skuId'],'stockNum':3} for r in rows]):
            self.assertFalse(pl.verify_package(root,1,0)['deliveryChecks']['platformValidationPassed'])
            pl.atomic_json(root/'.publish/validation-response.json',{'success':True,'data':{}})
            self.assertEqual(pl.verify_package(root,1,0)['status'],'VERIFIED')
            rows[0]['logo']='jfs/wrong'
            outcome=pl.verify_package(root,1,0)
            self.assertEqual(outcome['status'],'VERIFICATION_FAILED')
            self.assertTrue(outcome['deliveryChecks']['productOnSale'])
            self.assertIn('交付待核对',outcome['statement'])
