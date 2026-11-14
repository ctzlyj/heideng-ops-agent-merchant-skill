import copy,tempfile,unittest
from pathlib import Path
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError
from tests import test_operations as fixtures

class ContractClient(fixtures.FakeClient):
 def __init__(self):super().__init__();self.contract={'transport':'official-source-stdin','officialVersion':'0.3.7','sourceSha256':'a'*64};self.plan_count=0
 def plan_execution(self,operation,*,profile):self.plan_count+=1;return copy.deepcopy(self.contract)

class BindingTests(unittest.TestCase):
 def make(self,d):
  c=ContractClient();ops=Operations(Path(d),c);ops.connect('merchant-demo','测试店','1');op={'url':'/rest/sp-product/v0/products','method':'POST','body':{'text':'x'*30000},'params':{},'skillId':'jdo-product-publish'};return c,ops,op
 def test_official_execution_manifest_is_part_of_approval_fingerprint(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op=self.make(d);first=ops.prepare('merchant-demo',op);self.assertEqual(first['scope']['officialExecution'],c.contract)
   c.contract['sourceSha256']='b'*64;second=ops.prepare('merchant-demo',op);self.assertNotEqual(first['fingerprint'],second['fingerprint'])
 def test_changed_execution_cannot_use_old_approval_or_start_write(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op=self.make(d);task=ops.prepare('merchant-demo',op);ops.approve(task['taskId'],task['fingerprint'],confirmed=True);c.contract['officialVersion']='0.3.8'
   with self.assertRaisesRegex(SafetyError,'execution-contract'):ops.execute(task['taskId'])
   self.assertEqual(c.calls,[]);self.assertEqual(ops.task(task['taskId'])['status'],'prepared')
 def test_legacy_approved_scope_cannot_enter_new_real_transport(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op=self.make(d);legacy=fixtures.FakeClient();ops.client=legacy;task=ops.prepare('merchant-demo',op);ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.client=c
   with self.assertRaisesRegex(SafetyError,'execution-contract'):ops.execute(task['taskId'])
   self.assertEqual(c.calls,[]);self.assertEqual(ops.task(task['taskId'])['status'],'prepared')
 def test_shop_changed_during_transport_preflight_stops_before_submission(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op=self.make(d);task=ops.prepare('merchant-demo',op);ops.approve(task['taskId'],task['fingerprint'],confirmed=True);original=c.plan_execution
   def change(*a,**k):c.other=True;return original(*a,**k)
   c.plan_execution=change
   with self.assertRaisesRegex(SafetyError,'shop-changed'):ops.execute(task['taskId'])
   self.assertEqual(c.calls,[])
 def test_bound_execution_and_approval_deadline_reach_actual_transport(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op=self.make(d);task=ops.prepare('merchant-demo',op);approved=ops.approve(task['taskId'],task['fingerprint'],confirmed=True);result=ops.execute(task['taskId']);self.assertEqual(result['status'],'submitted');kwargs=c.calls[0][2];self.assertEqual(kwargs['expected_execution'],c.contract);self.assertEqual(kwargs['authorization_expires_at'],approved['approval']['expiresAt'])

if __name__=='__main__':unittest.main()
