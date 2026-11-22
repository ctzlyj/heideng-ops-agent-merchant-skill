"""Shop-scoped resumption of commercial tasks from independent processes and old receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from heideng_merchant.commercial_tasks import register
from heideng_merchant.merchant_tasks import task_context
from heideng_merchant.safety import atomic_json, clean_environment


ROOT = Path(__file__).resolve().parents[1]


class CommercialTaskContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.state = Path(self.temp)/'state'
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME': str(self.state)}))
        self.store = {'profile':'shop-one','shopName':'同名店','venderId':'202'}
        atomic_json(self.state/'linker/shops.json', {'profiles':{
            'shop-one':dict(self.store,shopId='101'), 'shop-two':dict(self.store,profile='shop-two',shopId='616',venderId='303')}})

    def package(self, root, package, product, store=None, **extras):
        m = {'schemaVersion':'listing-package/v1','mode':'photo-new-listing','title':'同一商品',
             'store':store or self.store,'packageId':package,'productId':product,'skuIds':[],
             'reference':{'sourceSpuId':'70'},'status':'INFORMATION_PENDING', **extras}
        atomic_json(root/'manifest.json',m)
        return m

    def new_chat(self,*flags):
        env = clean_environment(Path(self.temp)/'fresh-chat')
        env['HEIDENG_MERCHANT_HOME'] = str(self.state)
        proc = subprocess.run([sys.executable,'-I','-B',str(ROOT/'scripts/merchant.py'),'--state',str(self.state),
                               'task-context','--shop-id','101','--vender-id','202',*flags], env=env,
                              check=True,capture_output=True,text=True,encoding='utf-8',timeout=30)
        return json.loads(proc.stdout)

    def test_two_same_source_listings_sample_and_edit_follow_exact_receipts(self):
        first = self.state/'work/listing/batch/p1'
        second = Path(self.temp)/'outside work'/ 'p2'
        wrong = self.state/'work/listing/other'
        self.package(first,'first','310')
        self.package(second,'second','320',skuIds=[900,901])
        register('listing',second,self.store,'second')
        self.package(wrong,'unrelated','320',dict(self.store,profile='shop-two',venderId='303'))
        atomic_json(second/'state.json',{'status':'SUCCEEDED','productId':'320'})
        atomic_json(second/'.publish/verification.json',{'problems':[]})
        sample = second/'.samples/front'
        self.package(sample,'sample-1',None,sampleOf={'packageId':'second','imageId':'front'},status='MATERIAL_PREVIEW')
        scope = {'shop':'202','profile':'shop-one','task':'sample-1'}
        atomic_json(sample/'image-quote.json',{'scope':scope,'units':['front']})
        atomic_json(sample/'.generation/generation.json',{'front':{'status':'UNKNOWN'}})
        approval = 'fee-'+'3'*32
        atomic_json(self.state/'fee-consents'/f'{approval}.json',
                    {'approval':{'scope':scope,'approvalRef':approval,'units':['front'],'maxRequests':2},
                     'attempts':{'one':{'directory':str(sample)}}})
        edit = self.state/'work/sku-image-edits/202/320/current.json'
        atomic_json(edit, {'productId':320,'status':'awaiting-readback'})
        for path in [first, second]:
            atomic_json(path/'state.json',{'status':'SUCCEEDED','productId':'310' if path==first else '320'})
        both=self.new_chat('--goal','listing','--source-product-id','70')
        self.assertEqual(both['selection'],'ambiguous')
        self.assertEqual({t['productId'] for t in both['tasks']},{'310','320'})
        only=self.new_chat('--goal','listing','--product-id','320')['tasks'][0]
        self.assertEqual(only['consumerLinks'],['https://item.jd.com/900.html','https://item.jd.com/901.html'])
        images_before=(sample/'.generation/generation.json').read_bytes()
        sample_result=self.new_chat('--goal','sample','--product-id','320')
        self.assertEqual(sample_result['selection'],'matched')
        match=sample_result['tasks'][0]
        self.assertEqual(match['parentTaskId'],only['taskId'])
        self.assertEqual(match['state'],'needs-reconciliation')
        self.assertEqual(match['unknownUnits'],['front'])
        self.assertIn('reconcile-images', match['readbackArgv'])
        self.assertEqual(match['feeDecisions'][0]['remainingRequests'],1)
        self.assertEqual(images_before,(sample/'.generation/generation.json').read_bytes())
        change=self.new_chat('--goal','sku-edit','--product-id','320')['tasks'][0]
        self.assertEqual(change['parentTaskId'],only['taskId'])
        self.assertEqual(change['state'],'awaiting-readback')
        self.assertFalse(task_context(self.state,'616','202')['tasks'])

    def test_external_creative_plan_and_old_complete_pending_and_unknown(self):
        from heideng_merchant.creative_images import CreativeOrder
        run=Path(self.temp)/'commercial'
        order=CreativeOrder(run,{'kind':'image-refresh','shop':self.store,'products':['88']},
                            {u:{'sourceSha256':u} for u in ('a','b','c')},['a','b','c'],None)
        atomic_json(run/'internal-generation.json',{'a':{'status':'succeeded'},'c':{'status':'unknown'}})
        result=self.new_chat('--goal','creative','--product-id','88')['tasks'][0]
        self.assertEqual(result['generatedUnits'],['a'])
        self.assertEqual(result['pendingUnits'],['b'])
        self.assertEqual(result['unknownUnits'],['c'])
        self.assertEqual(Path(result['receipt']),order.directory/'image-quote.json')
