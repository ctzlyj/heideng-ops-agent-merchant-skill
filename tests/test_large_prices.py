import copy, json, tempfile, unittest
from pathlib import Path
from heideng_merchant.products import ProductService, DETAIL, APPLY_DETAIL
from heideng_merchant.operations import Operations
from heideng_merchant.official_transport import transport_for
from heideng_merchant.safety import SafetyError
from heideng_merchant.verification import validate_expected

class LargePriceClient:
    def __init__(self, count=1000):
        self.rows=[{'skuId':str(1000000000000000000+i), 'productId':100, 'priceInfo':{'jdPrice':'30.00'}} for i in range(count)]
        self.pending=None; self.writes=[]; self.unknown=False
    def identity(self, profile):
        return {'venderId':'1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
    def invoke(self, profile, url, **kw):
        if kw.get('method')=='PATCH':
            self.writes.append(copy.deepcopy(kw))
            self.pending=copy.deepcopy(self.rows)
            prices={p['path'].split('==')[1][:-1]:json.loads(p['value'])['value'] for p in kw['body']['patchOperationList']}
            for row in self.pending:row['priceInfo']['jdPrice']=prices.get(row['skuId'],row['priceInfo']['jdPrice'])
            if self.unknown:raise TimeoutError('synthetic accepted response lost')
            return {'success':True,'data':{'id':'100'}}
        return {'data':{'productInfo':{'productId':100},'categoryDTO':{'lastCategoryId':456},'skuList':copy.deepcopy(self.pending if url==APPLY_DETAIL and self.pending is not None else self.rows)}}

class LargePriceTests(unittest.TestCase):
    def make(self, d, count=1000):
        client=LargePriceClient(count);ops=Operations(Path(d),client);ops.connect('merchant-large','synthetic-store','1')
        return client,ops,ProductService(Path(d),client)
    def changes(self,c):return [{'skuId':r['skuId'],'jdPrice':'20.00','expectedOldPrice':'30.00'} for r in c.rows]
    def test_one_thousand_skus_use_stdin_and_keep_every_three_stage_value(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,p=self.make(d);plan=p.prepare_price('merchant-large',100,self.changes(c));task=plan['task'];scope=task['scope']
            self.assertEqual(len(plan['preview']),1000);self.assertEqual(len(scope['operation']['body']['patchOperationList']),1000)
            self.assertEqual(transport_for('synthetic-cli.exe','merchant-large',scope['operation']),'official-source-stdin')
            for section in ('precondition','verification','onlineVerification'):
                self.assertTrue(any(c.rows[-1]['skuId'] in key for key in scope[section]['expected']))
            ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId'])
            self.assertEqual(p.price_status(task['taskId'],refresh='pending')['phase'],'application-values-confirmed')
            self.assertFalse(p.price_status(task['taskId'],refresh='online')['onlineEffective'])
            c.rows=copy.deepcopy(c.pending)
            self.assertTrue(p.price_status(task['taskId'],refresh='online')['onlineEffective']);self.assertEqual(len(c.writes),1)
    def test_last_sku_old_price_drift_stops_entire_scope_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,p=self.make(d);task=p.prepare_price('merchant-large',100,self.changes(c))['task']
            ops.approve(task['taskId'],task['fingerprint'],confirmed=True);c.rows[-1]['priceInfo']['jdPrice']='31.00'
            with self.assertRaises(SafetyError):ops.execute(task['taskId'])
            self.assertEqual(c.writes,[])
    def test_large_unknown_scope_is_never_replayed_or_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,p=self.make(d,160);task=p.prepare_price('merchant-large',100,self.changes(c))['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);c.unknown=True
            self.assertEqual(ops.execute(task['taskId'])['status'],'unknown')
            self.assertEqual(p.price_status(task['taskId'],refresh='pending')['phase'],'unknown')
            with self.assertRaises(SafetyError):ops.execute(task['taskId'])
            with self.assertRaises(SafetyError):p.prepare_price('merchant-large',100,[{'skuId':c.rows[-1]['skuId'],'jdPrice':'19.00'}])
            self.assertEqual(len(c.writes),1)
    def test_over_local_scope_limit_rejects_without_truncating_or_writing(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,p=self.make(d,1001)
            with self.assertRaises(SafetyError):p.prepare_price('merchant-large',100,self.changes(c))
            self.assertEqual(c.writes,[])
    def test_expanded_field_budget_is_still_bounded(self):
        validate_expected({'field'+str(i):i for i in range(1024)})
        with self.assertRaises(SafetyError):validate_expected({'field'+str(i):i for i in range(1025)})

    def test_verification_memory_budget_counts_utf8_bytes_not_characters(self):
        with tempfile.TemporaryDirectory() as d:
            c,ops,p=self.make(d,1);query={'url':DETAIL,'method':'GET','params':{'productId':100,'scene':'pop'}}
            with self.assertRaisesRegex(SafetyError,'verification-scope-too-large'):
                ops.prepare('merchant-large',query,{'query':query,'expected':{'title':'图'*100000}})
