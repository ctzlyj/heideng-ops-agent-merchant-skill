"""A new host can hand off a scoped diagnosis with no platform or model write."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from heideng_merchant.safety import atomic_json, clean_environment


CLI = Path(__file__).resolve().parents[1]/'scripts/merchant.py'


class CommerceHandoffTests(unittest.TestCase):
    def test_new_chat_reads_same_shop_same_product_facts_and_material_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root/'state'
            atomic_json(state/'linker/shops.json', {'profiles':{
                'fixture-a':{'shopId':'101','venderId':'202','shopName':'同名店','lastVerifiedAt':12,'status':'ok'},
                'fixture-b':{'shopId':'404','venderId':'505','shopName':'同名店','lastVerifiedAt':12,'status':'ok'}}})
            for vendor, shop, product in [('202','101','303'),('505','404','303'),('202','101','304')]:
                atomic_json(state/'work/sku-image-edits'/vendor/product/'current.json',
                            {'shopIdentity':{'shopId':shop,'venderId':vendor},'productId':product,'status':'submitted'})
            period = ['2026-09-01','2026-09-30']
            row = dict(shopId='101',venderId='202',spuId='303',domain='ads',period='current',window=period,
                       basis='点击归因7日',source='广告汇总-09',channel='POP',metrics={'spend':200})
            data = {'rows':[row], 'periods':{'current':period}, 'handoff':{
                'hypothesis':'部分点击可能来自不匹配的规格需求', 'priorityAction':'核查该款近一周的规格咨询',
                'nextRole':'客服', 'recheck':'用下一期同口径的咨询原因和点击成交检验'}}
            source = root/'in.json'
            atomic_json(source,data)

            def call(*args, code=0):
                result = subprocess.run([sys.executable,'-I','-B',str(CLI),'--state',str(state),*args],
                    env=clean_environment(root/'host'),capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,code,result.stdout+result.stderr)
                return json.loads(result.stdout)

            compare = ['compare-evidence','--shop-id','101','--vender-id','202','--spu-id','303','--input',str(source)]
            find = ['task-context','--goal','diagnosis']
            call(*compare)
            self.assertFalse((state/'commerce-handoffs').exists())
            first = call(*compare,'--save-handoff')['handoff']
            self.assertEqual(call(*compare,'--save-handoff')['handoff'], first)
            out = call(*find,'--shop-id','101','--vender-id','202','--product-id','303')
            self.assertEqual(out['selection'],'matched')
            task = out['tasks'][0]
            self.assertEqual(task['taskId'],first['taskId'])
            self.assertEqual(task['facts']['observations']['ads']['current']['spend'],200)
            self.assertFalse(task['facts']['observations']['ads']['comparable'])
            self.assertTrue(task['facts']['gaps'])
            self.assertEqual(task['hostAssessment']['hypothesis'],data['handoff']['hypothesis'])
            self.assertEqual(task['nextAction'],data['handoff']['priorityAction'])
            receipts = task['relatedReceiptsAtSave']
            self.assertEqual(len(receipts),1)
            self.assertEqual(receipts[0]['state'],'submitted')
            self.assertEqual(receipts[0]['consumerPageStatus'],'unchecked')
            for shop,vendor,spu in [('404','505','303'),('101','202','304')]:
                self.assertEqual(call(*find,'--shop-id',shop,'--vender-id',vendor,'--product-id',spu)['tasks'],[])
            # A host cannot attach rows from another merchant to this handoff.
            row['shopId']='404'
            atomic_json(source,data)
            call(*compare,'--save-handoff',code=2)
