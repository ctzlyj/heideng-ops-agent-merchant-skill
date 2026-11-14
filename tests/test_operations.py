import tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError

class FakeClient:
 def __init__(self):self.calls=[];self.fail=False;self.other=False
 def identity(self,profile):return {'venderId':'2' if self.other else '1','shopId':'3','shopName':'测试店','shopType':'POP'}
 def invoke(self,profile,url,**kw):
  self.calls.append((profile,url,kw))
  if self.fail:raise TimeoutError('synthetic unknown')
  return {'data':{'skuId':'9','price':'10.00'}}

class OperationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.client=FakeClient();self.ops=Operations(Path(self.tmp.name),self.client)
  self.shop=self.ops.connect('merchant-demo','测试店','1')
  self.op={'skillId':'jdo-product-update','url':'/rest/sp-product/v0/products/9','method':'PUT','body':{'price':'10.00'},'params':{}}
 def tearDown(self):self.tmp.cleanup()
 def plan(self):return self.ops.prepare('merchant-demo',self.op)
 def test_write_requires_exact_approval(self):
  p=self.plan()
  with self.assertRaises(SafetyError):self.ops.execute(p['taskId'])
  with self.assertRaises(SafetyError):self.ops.approve(p['taskId'],'wrong',confirmed=True)
  self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True)
  self.assertEqual(self.ops.execute(p['taskId'])['status'],'submitted')
  with self.assertRaises(SafetyError):self.ops.execute(p['taskId'])
  self.assertEqual(len(self.client.calls),1)
 def test_unknown_cannot_be_replayed_or_replaced(self):
  p=self.plan();self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.client.fail=True
  self.assertEqual(self.ops.execute(p['taskId'])['status'],'unknown')
  with self.assertRaises(SafetyError):self.ops.execute(p['taskId'])
  changed={**self.op,'body':{'price':'11.00'}}
  with self.assertRaises(SafetyError):self.ops.prepare('merchant-demo',changed)
  self.assertEqual(len(self.client.calls),1)
 def test_wrong_shop_stops_before_write(self):
  p=self.plan();self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.client.other=True
  with self.assertRaises(SafetyError):self.ops.execute(p['taskId'])
  self.assertEqual(self.client.calls,[])
 def test_parallel_one_submission(self):
  p=self.plan();self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True)
  def attempt(n):
   try:return self.ops.execute(p['taskId'])['status']
   except SafetyError:return 'blocked'
  with ThreadPoolExecutor(3) as pool:results=list(pool.map(attempt,range(3)))
  self.assertEqual(results.count('submitted'),1);self.assertEqual(len(self.client.calls),1)
 def test_read_needs_identity_but_not_write_approval(self):
  p=self.ops.prepare('merchant-demo',{'url':'/rest/sp-product/v0/products','method':'GET','params':{'page':1},'skillId':'jdo-product-price'})
  self.assertEqual(self.ops.execute(p['taskId'])['status'],'completed')
 def test_payload_credentials_rejected(self):
  with self.assertRaises(SafetyError):self.ops.prepare('merchant-demo',{**self.op,'body':{'access_token':'fake'}})
 def test_default_and_wrong_identity_connect_rejected(self):
  with self.assertRaises(SafetyError):self.ops.connect('default','测试店','1')
  with self.assertRaises(SafetyError):self.ops.connect('merchant-demo','其他店','1')

 def test_unbound_readback_cannot_close_write(self):
  p=self.plan();self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.ops.execute(p['taskId'])
  with self.assertRaises(SafetyError):self.ops.readback(p['taskId'],{'url':'/rest/sp-product/v0/products/other'}, {'skuId':'9'})
 def test_runtime_change_invalidates_old_approval(self):
  from unittest.mock import patch
  p=self.plan();self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True)
  with patch('heideng_merchant.operations.VERSION','9.0.0'):
   with self.assertRaises(SafetyError):self.ops.execute(p['taskId'])

 def test_bound_official_readback_can_verify_target_state(self):
  query={'url':'/rest/sp-product/v0/products/9','method':'GET','params':{},'skillId':'jdo-product-update'}
  expected={'skuId':'9','price':'10.00'}
  p=self.ops.prepare('merchant-demo',self.op,{'query':query,'expected':expected});self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.ops.execute(p['taskId'])
  self.assertEqual(self.ops.readback(p['taskId'],query,expected)['status'],'verified')
 def test_changed_readback_expected_is_rejected(self):
  query={'url':'/rest/sp-product/v0/products/9','method':'GET','params':{},'skillId':'jdo-product-update'}
  p=self.ops.prepare('merchant-demo',self.op,{'query':query,'expected':{'skuId':'9','price':'10.00'}});self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.ops.execute(p['taskId'])
  with self.assertRaises(SafetyError):self.ops.readback(p['taskId'],query,{'skuId':'9'})

 def test_unknown_target_state_match_does_not_prove_original_terminal(self):
  query={'url':'/rest/sp-product/v0/products/9','method':'GET','params':{},'skillId':'jdo-product-update'};expected={'skuId':'9','price':'10.00'}
  p=self.ops.prepare('merchant-demo',self.op,{'query':query,'expected':expected});self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True);self.client.fail=True;self.ops.execute(p['taskId']);self.client.fail=False
  r=self.ops.readback(p['taskId'],query,expected);self.assertEqual(r['status'],'unknown');self.assertTrue(r['targetStateVerified'])
  with self.assertRaises(SafetyError):self.ops.prepare('merchant-demo',{**self.op,'body':{'price':'11.00'}})

if __name__=='__main__':unittest.main()
