"""Drive a single copy through its registered entry using two synthetic official stores."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from heideng_merchant.safety import atomic_json
from tests.test_owned_product_copy import SOURCE, TARGET, reference, sample
from tests.test_shop_copy_delivery import side

ROOT = Path(__file__).resolve().parents[1]


class ShopCopyEntryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(self.root)}))
        self.enterContext(patch.object(sys,'path',[str(ROOT/'mature/listing/scripts'),*sys.path]))
        from heideng_merchant import shop_copy_command as entry
        self.entry = entry
        api = entry.api
        self.enterContext(patch.object(api,'_ACTIVE_JDO_PROFILE',None))
        self.enterContext(patch.object(api,'_VERIFIED_JDO_STORE',None))
        self.source, self.target = sample(), sample(True)
        self.delivery = self.root/'规则.json'
        self.config = self.root/'两店.json'
        atomic_json(self.config, {'stores':{s['profile']:s for s in (SOURCE,TARGET)}})
        ev = {}
        for name,detail,shop,ids in (('source',self.source,SOURCE,(11,12,13)),('target',self.target,TARGET,(91,92,93))):
            detail['productInfo'].update(logisticsInfo={'transportId':ids[0],'promiseId':ids[1]},
                       features=[{'key':'is7ToReturn','value':'0'},{'key':'isPayFirst','value':'1'}])
            for row in detail['skuList']:
                row['logisticsInfo'] = {'promiseId':None}
            ev[name] = side(shop, ids)
        atomic_json(self.delivery,ev)
        self.ref = reference()
        self.ref['schema']['componentList'].extend({'componentCode':v} for v in
            ('WareTransport','WarePromise','WareSevenDayReturn','PayMethodLimit','SkuPromise'))
        self.pages = {}
        def get(skill,url,params=None):
            shop = SOURCE if api.active_jdo_profile()==SOURCE['profile'] else TARGET
            current = self.source if shop==SOURCE else self.target
            if url.endswith('/venderinfo'):
                return {'success':True,'data':{'venderId':shop['venderId'],'shopBaseInfo':{
                    'shopName':shop['shopName'],'shopId':shop['shopId'],'type':0,'status':1}}}
            if url.endswith('/products/{productId}'):
                return {'data':deepcopy(current)}
            if url == '/rest/sp-product/v0/products':
                if 'productIdList' in params:
                    return {'data':[{'productId':current['productInfo']['productId']}]}
                self.assertEqual(shop,SOURCE)
                return self.pages[params['page']]
            if url.endswith('/product-schemas'):
                return {'data':[json.dumps(self.ref['schema'])]}
            if url.endswith('/vender-brands'):
                return {'data':self.ref['brands']}
            if url.endswith('/sku-stocks'):
                return {'data':[{'skuId':r['skuId'],'stockNum':r['stockNum']} for r in current['skuList']]}
            if url.endswith('/sku-materials'):
                return {'data':[{'skuId':r['skuId'],'materials':[]} for r in current['skuList']]}
            raise AssertionError(url)
        self.enterContext(patch.object(api,'get',side_effect=get))
        self.enterContext(patch.object(api,'run_jdo',side_effect=api.JdoError('fixture: capability unavailable')))
        self.enterContext(patch('heideng_merchant.sku_image_edit.media_space',return_value=('zone',1)))
        def download(url):
            result=BytesIO()
            Image.new('RGB',(8,8),tuple(sha256(url.encode()).digest()[:3])).save(result,format='PNG')
            return result.getvalue()
        self.enterContext(patch('heideng_merchant.sample_comparison.download_image',side_effect=download))
        self.upload=self.enterContext(patch.object(api,'upload',side_effect=lambda z,c,p:{'imgUrl':'jfs/'+p.stem}))
        self.requests=[]
        def invoke(**kwargs):
            self.requests.append((api.active_jdo_profile(),kwargs['url']))
            if kwargs['url'].endswith('/validations'):
                return {'success':True,'data':{}}
            self.assertTrue(kwargs['url'].endswith('/product-applies'))
            if self.lose_reply:raise TimeoutError('simulated response loss')
            return {'success':True,'data':{'productId':802,'applyId':8802}}
        self.enterContext(patch.object(api,'run_jdo_large',side_effect=invoke))
        self.lose_reply = False
        self.src=['--source-profile',SOURCE['profile'],'--source-config',str(self.config)]
        self.dst=['--target-profile',TARGET['profile'],'--target-config',str(self.config)]

    def call(self, action, *args, ok=True):
        output=StringIO()
        with redirect_stdout(output):rc=self.entry.main([action,*self.dst,*args])
        data=json.loads(output.getvalue())
        if ok:self.assertEqual(rc,0,data)
        else:self.assertTrue(rc or data['status'] not in ('submitted','pilot-prepared'),data)
        return data

    def make_pilot(self):
        frozen=self.call('freeze',*self.src,'--product-id','701')
        self.assertEqual(frozen['platformWrites'],0)
        self.assertEqual(frozen['gallerySlots'],{'0000000000':2,'sourcegroup1':3,'sourcegroup2':3})
        self.assertEqual(frozen['sourceExampleSkuUrl'],'https://item.jd.com/201.html')
        task=['--task',frozen['taskId']]
        draft=self.call('prepare',*task)
        self.assertEqual(draft['status'],'local-draft-ready')
        self.assertEqual(draft['currentStage']['merchantDecisions'],[])
        self.assertIn('000134',Path(draft['previewFile']).read_text(encoding='utf-8'))
        self.upload.assert_not_called()
        self.call('stage-media',*task,'--confirm','UPLOAD_COPY_MEDIA')
        count=self.upload.call_count
        self.call('stage-media',*task,'--confirm','UPLOAD_COPY_MEDIA')
        self.assertEqual(self.upload.call_count,count)
        self.assertGreater(count,0)
        draft=self.call('prepare',*task,'--delivery-evidence',str(self.delivery))
        self.assertEqual(draft['status'],'local-draft-ready',draft)
        self.assertEqual(self.requests,[])
        self.call('submit-one',*task,*self.src,'--approval','draft','--confirm','PUBLISH_ONE_COPY',ok=False)
        self.assertEqual(self.requests,[])
        plan=self.call('prepare',*task,'--intent','publish-one')
        self.assertEqual(plan['status'],'pilot-prepared',plan)
        return task, plan

    def test_pilot_only_and_resume_without_replaying_publication(self):
        task,plan=self.make_pilot()
        args=task+self.src+['--approval',plan['approvalFingerprint'],'--confirm','PUBLISH_ONE_COPY']
        result=self.call('submit-one',*args)
        self.assertEqual((result['status'],result['targetProductId']),('submitted',802))
        self.assertEqual(result['consumerPageStatus'],'unchecked')
        with patch.object(self.entry,'verify',side_effect=AssertionError('local preview contacted a shop')):
            output=StringIO()
            with redirect_stdout(output):
                self.assertEqual(self.entry.main(['prepare',*task]),0)
            self.assertIn('000134',Path(json.loads(output.getvalue())['previewFile']).read_text(encoding='utf-8'))
        repeated=self.call('submit-one',*args)
        self.assertEqual((repeated['targetProductId'],repeated['comparison']['status']),
                         (result['targetProductId'],result['comparison']['status']))
        self.assertEqual([name for name,_ in self.requests],[TARGET['profile']]*2)
        current=self.call('compare',*task)
        self.assertEqual(current['sourceProductId'],'701')
        self.assertTrue(current['skuLinks'])
        self.assertNotIn('bulkAuthorized',current)
        self.assertEqual(current['readbackScope'],'single-product')

    def test_lost_reply_is_only_reconciled_and_freight_drift_stops_before_publish(self):
        task,plan=self.make_pilot()
        args=task+self.src+['--approval',plan['approvalFingerprint'],'--confirm','PUBLISH_ONE_COPY']
        self.source['productInfo']['logisticsInfo']['promiseId'] = 121
        self.call('submit-one',*args,ok=False)
        self.assertEqual(self.requests,[])
        self.source['productInfo']['logisticsInfo']['promiseId'] = 12
        self.lose_reply=True
        self.assertEqual(self.call('submit-one',*args,ok=False)['status'],'submission-needs-reconciliation')
        self.assertEqual(self.call('submit-one',*args,ok=False)['status'],'submission-needs-reconciliation')
        self.assertEqual(len(self.requests),2)
        from heideng_merchant.merchant_tasks import task_context
        ctx = task_context(self.root,TARGET['shopId'],TARGET['venderId'],goal='shop-copy',source_product_id='701')
        self.assertEqual(ctx['tasks'][0]['state'],'needs-reconciliation')
        self.assertEqual(ctx['tasks'][0]['taskId'],task[1])
        self.assertEqual(task_context(self.root,'888',TARGET['venderId'],goal='shop-copy')['tasks'],[])

    def test_unknown_media_is_not_sent_again(self):
        frozen=self.call('freeze',*self.src,'--product-id','701')
        args=['--task',frozen['taskId'],'--confirm','UPLOAD_COPY_MEDIA']
        self.upload.side_effect=TimeoutError('upload response missing')
        self.call('stage-media',*args,ok=False)
        self.assertEqual(self.call('stage-media',*args,ok=False)['status'],'upload-needs-reconciliation')
        self.assertEqual(self.upload.call_count,1)

    def test_inventory_requires_complete_pagination_and_never_submits(self):
        self.pages = {i:{'data':[{'productId':700+i,'productStatus':103,'productName':'合成样品'}],
                         'paginationData':{'totalItems':2,'pageNum':i}} for i in (1,2)}
        result = self.call('inventory',*self.src,'--status','103')
        self.assertEqual((result['status'],result['recordedProducts'],result['publishedProducts']),
                         ('inventory-ready',2,0))
        self.pages[2]['data'] = self.pages[1]['data']
        partial=self.call('inventory',*self.src,'--status','103',ok=False)
        self.assertEqual((partial['status'],partial['recordedProducts']),('partial-inventory',1))
        self.assertEqual(self.requests,[])
        self.upload.assert_not_called()

    def test_existing_sample_is_read_back_without_creating_a_replacement(self):
        start=self.call('freeze',*self.src,'--product-id','701','--existing-target-id','802')
        self.entry.api.get.reset_mock()
        observed=self.call('compare','--task',start['taskId'],ok=False)
        self.assertEqual(observed['matchedSkuCount'],2,observed)
        self.assertEqual(observed['buyerPurchaseStatus'],'unverified')
        self.assertFalse(any(call.args[1].endswith('/vender-brands') for call in self.entry.api.get.call_args_list))
        result=self.call('submit-one','--task',start['taskId'],*self.src,'--approval','other',
                         '--confirm','PUBLISH_ONE_COPY')
        self.assertEqual(result['status'],'existing-target-for-comparison')
        self.assertEqual(result['comparison']['targetProductId'],'802')
        self.assertEqual(self.requests,[])
        self.upload.assert_not_called()

    def test_missing_official_validation_success_never_creates(self):
        task,plan=self.make_pilot()
        for response in ({'data':{}}, {'success':True,'data':{'valid':False,'wareKeeperDetectResultList':[]}},
                         {'success':True,'errorList':[{'code':'refused'}],'data':{}},
                         {'success':True,'data':{'wareKeeperDetectResultList':[{'detectResult':1}]}}):
            with self.subTest(response=response), patch.object(self.entry.api,'run_jdo_large',return_value=response) as calls:
                result=self.call('submit-one',*task,*self.src,'--approval',plan['approvalFingerprint'],
                                 '--confirm','PUBLISH_ONE_COPY',ok=False)
                self.assertEqual(result['status'],'validation-needs-review')
                self.assertEqual([v.kwargs['url'] for v in calls.call_args_list],
                                 ['/rest/sp-product/v0/product-schemas/validations'])
