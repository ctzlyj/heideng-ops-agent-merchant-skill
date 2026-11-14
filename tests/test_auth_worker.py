import json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_worker import drive_flow
from heideng_merchant.auth_broker import BrokerState
from heideng_merchant.operations import Operations
from tests import test_auth_flow as fixtures
from heideng_merchant.safety import read_json

class WorkerTests(unittest.TestCase):
 def test_verified_flow_registers_shop_without_publishing_private_data(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=fixtures.AuthFlowTests.make_flow(self,d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   broker=BrokerState()
   def step(delay):
    if flow.process is not None:flow.process.returncode=0
   r=drive_flow(flow,broker,Operations(Path(d),client),sleep=step)
   self.assertTrue(r['ready']);self.assertEqual(read_json(Path(d)/'shops.json')[flow.data['profile']]['venderId'],'1');self.assertNotIn('fake-private',json.dumps(broker.observe()));self.assertTrue(browser.closed)
 def test_cancel_event_cannot_be_ignored_while_waiting_for_scan(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=fixtures.AuthFlowTests.make_flow(self,d);broker=BrokerState();broker.cancel()
   r=drive_flow(flow,broker,Operations(Path(d),client),sleep=lambda _:None)
   self.assertFalse(r['ready']);self.assertEqual(r['stage'],'cancelled');self.assertEqual(client.calls,[])

if __name__=='__main__':unittest.main()

class WorkerStartupTests(unittest.TestCase):
 def test_broker_start_failure_is_terminal_and_cannot_replay_same_receipt(self):
  from unittest.mock import patch
  from heideng_merchant import VERSION
  from heideng_merchant.auth_worker import run_worker
  from heideng_merchant.safety import atomic_json,SafetyError
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'tasks'/('a'*24+'.json');atomic_json(path,{'kind':'shop-auth','taskId':'a'*24,'stage':'starting_worker','status':'running','ready':False,'runtimeVersion':VERSION,'shopName':'test-shop','profile':'merchant-start-a1','venderId':'1'})
   with patch('heideng_merchant.auth_worker.make_server',side_effect=OSError('private-error')):
    result=run_worker(Path(d),'a'*24)
   self.assertEqual(result['status'],'failed');self.assertNotIn('private-error',json.dumps(result))
   with self.assertRaises(SafetyError):run_worker(Path(d),'a'*24)
