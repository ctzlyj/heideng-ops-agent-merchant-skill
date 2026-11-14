import tempfile,unittest
from pathlib import Path
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError
from tests import test_operations as fixtures

class OperationEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.client=fixtures.FakeClient();self.ops=Operations(Path(self.tmp.name),self.client);self.ops.connect('merchant-demo','测试店','1');self.op={'url':'/rest/sp-product/v0/product-applies/{applyId}','method':'PATCH','params':{'applyId':'9'},'body':{'testOnly':'10'},'skillId':'jdo-product-update'}
  self.query={'url':'/rest/sp-product/v0/products/{productId}','method':'GET','params':{'productId':9,'scene':'pop'},'skillId':'jdo-product-update'}
 def tearDown(self):self.tmp.cleanup()
 def approve(self,p):self.ops.approve(p['taskId'],p['fingerprint'],confirmed=True)
 def test_current_value_precondition_is_bound_and_checked_before_write(self):
  p=self.ops.prepare('merchant-demo',self.op,precondition={'query':self.query,'expected':{'price':'9.00'}});self.approve(p)
  with self.assertRaisesRegex(SafetyError,'precondition'):self.ops.execute(p['taskId'])
  self.assertEqual(len(self.client.calls),1);self.assertEqual(self.client.calls[0][2]['method'],'GET');self.assertEqual(self.ops.task(p['taskId'])['status'],'prepared')
 def test_already_prepared_second_write_is_blocked_after_first_unknown(self):
  first=self.ops.prepare('merchant-demo',self.op);second=self.ops.prepare('merchant-demo',{**self.op,'body':{'testOnly':'11'}});self.approve(first);self.approve(second);self.client.fail=True;self.ops.execute(first['taskId']);self.client.fail=False
  with self.assertRaises(SafetyError):self.ops.execute(second['taskId'])
  self.assertEqual(len(self.client.calls),1)
 def test_unknown_same_shop_cannot_be_bypassed_by_another_profile(self):
  self.ops.connect('merchant-second','测试店','1');p=self.ops.prepare('merchant-demo',self.op);self.approve(p);self.client.fail=True;self.ops.execute(p['taskId'])
  with self.assertRaises(SafetyError):self.ops.prepare('merchant-second',{**self.op,'body':{'testOnly':'11'}})
 def test_nested_sku_pending_and_online_evidence_are_distinct(self):
  pending={**self.query,'url':'/rest/sp-product/v0/product-apply/{applyId}','params':{'applyId':9,'scene':'pop'}};expected={'skuList[skuId==9].priceInfo.jdPrice':{'$decimal':'10.00'}}
  p=self.ops.prepare('merchant-demo',self.op,{'query':pending,'expected':expected},online_verification={'query':self.query,'expected':expected});self.approve(p);self.ops.execute(p['taskId'])
  price={'value':'10.000'}
  self.client.invoke=lambda profile,url,**kw:{'data':{'skuList':[{'skuId':9,'priceInfo':{'jdPrice':price['value']}}]}}
  task=self.ops.readback(p['taskId'],pending,expected);self.assertEqual(task['status'],'verified');self.assertNotIn('onlineStateVerified',task)
  price['value']='9';self.assertFalse(self.ops.verify_online(p['taskId']).get('onlineStateVerified',False));price['value']='10.00';self.assertTrue(self.ops.verify_online(p['taskId'])['onlineStateVerified'])
 def test_online_target_match_still_does_not_resolve_unknown_request(self):
  expected={'price':'10.00'};p=self.ops.prepare('merchant-demo',self.op,{'query':self.query,'expected':expected},online_verification={'query':self.query,'expected':expected});self.approve(p);self.client.fail=True;self.ops.execute(p['taskId']);self.client.fail=False
  task=self.ops.verify_online(p['taskId']);self.assertEqual(task['status'],'unknown');self.assertTrue(task['onlineStateVerified'])

if __name__=='__main__':unittest.main()

class EmptyAcknowledgementTests(unittest.TestCase):
 def test_empty_write_response_is_unknown_not_submitted(self):
  with tempfile.TemporaryDirectory() as d:
   client=fixtures.FakeClient();ops=Operations(Path(d),client);ops.connect('merchant-demo','测试店','1');op={'url':'/rest/sp-product/v0/product-applies/9','method':'PATCH','body':{'testOnly':True}};plan=ops.prepare('merchant-demo',op);ops.approve(plan['taskId'],plan['fingerprint'],confirmed=True);client.invoke=lambda *a,**k:{}
   self.assertEqual(ops.execute(plan['taskId'])['status'],'unknown')

class FreshnessTests(unittest.TestCase):
 def test_approval_expiry_during_preflight_stops_before_write(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   client=fixtures.FakeClient();ops=Operations(Path(d),client);ops.connect('merchant-demo','测试店','1');clock={'value':100}
   with patch('heideng_merchant.operations.time.time',side_effect=lambda:clock['value']):
    task=ops.prepare('merchant-demo',{'url':'/rest/sp-product/v0/product-applies/9','method':'PATCH','body':{'testOnly':True}},precondition={'query':{'url':'/rest/sp-product/v0/products/9'},'expected':{'price':'10.00'}});ops.approve(task['taskId'],task['fingerprint'],confirmed=True,ttl_seconds=1)
    original=client.invoke
    def query(*args,**kw):clock['value']=102;return original(*args,**kw)
    client.invoke=query
    with self.assertRaises(SafetyError):ops.execute(task['taskId'])
    self.assertEqual(len(client.calls),1)

class LiveRuntimeVersionTests(unittest.TestCase):
 def test_loaded_old_runtime_cannot_execute_after_installed_version_file_changes(self):
  import importlib,shutil,sys,uuid
  with tempfile.TemporaryDirectory(prefix='merchant-version-test-') as d:
   root=Path(d);name='runtime_'+uuid.uuid4().hex;package=root/name;package.mkdir();source=Path(__file__).resolve().parents[1]/'heideng_merchant'
   for file in source.glob('*.py'):shutil.copyfile(file,package/file.name)
   (root/'VERSION').write_text('0.1.0');sys.path.insert(0,str(root))
   try:
    module=importlib.import_module(name+'.operations');client=fixtures.FakeClient();ops=module.Operations(root/'state',client);ops.connect('merchant-demo','测试店','1');task=ops.prepare('merchant-demo',{'url':'/rest/sp-product/v0/product-applies/9','method':'PATCH','body':{'testOnly':True}});ops.approve(task['taskId'],task['fingerprint'],confirmed=True);(root/'VERSION').write_text('0.2.0')
    try:ops.execute(task['taskId'])
    except Exception as error:self.assertEqual(type(error).__name__,'SafetyError')
    else:self.fail('loaded old code submitted after live installation changed')
    self.assertEqual(client.calls,[])
   finally:
    sys.path.remove(str(root))
    for key in list(sys.modules):
     if key==name or key.startswith(name+'.'):del sys.modules[key]
