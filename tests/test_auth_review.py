import io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.auth_broker import BrokerState,allowed_request
from heideng_merchant.auth_manager import AuthManager
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import atomic_json,read_json
from tests import test_auth_flow as fixtures
from tests import test_auth_manager as managers

class ReviewBoundaryTests(unittest.TestCase):
 def test_ready_is_not_visible_until_shop_registration_completes(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=fixtures.AuthFlowTests.make_flow(self,d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/identity'})
   from heideng_merchant.auth_worker import drive_flow
   from heideng_merchant.operations import Operations
   broker=BrokerState();ops=Operations(Path(d),c);observed=[];original=ops.connect
   def connect(*args):observed.append((broker.status().get('ready'),read_json(flow.path)['ready']));return original(*args)
   ops.connect=connect
   def step(_):
    if flow.process is not None:flow.process.returncode=0
   result=drive_flow(flow,broker,ops,sleep=step)
   self.assertTrue(result['ready']);self.assertEqual(observed,[(False,False)])
 def test_two_boolean_fields_are_not_complete_official_nonmock_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=fixtures.AuthFlowTests.make_flow(self,d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/identity'})
   original=c.login_process
   def login(*a):p=original(*a);p.stdout=io.BytesIO(b'{"ok":true,"loginCompleted":true}');return p
   c.login_process=login;flow.tick();flow.tick();c.process.returncode=0;r=flow.tick();self.assertFalse(r['ready']);self.assertEqual(r['status'],'unknown');self.assertFalse((Path(d)/'shops.json').exists())
 def test_task_mismatch_is_rejected_before_broker_cancel(self):
  headers={'Host':'127.0.0.1:1234','X-Heideng-Local':'1','X-Heideng-Task':'a'*24}
  self.assertFalse(allowed_request('POST','/cancel',headers,1234,task_id='b'*24))
  self.assertTrue(allowed_request('POST','/cancel',headers,1234,task_id='a'*24))
 def test_cancel_reply_for_other_task_is_not_acknowledged(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers.ManagerTests();m=fixture.manager(d);job=m.start('test-shop',foreground=True)['taskId']
   atomic_json(Path(d)/'auth'/'handles'/(job+'.json'),{'port':1234})
   m.request=lambda *a,**k:{'taskId':'b'*24,'cancelRequested':True}
   self.assertFalse(m.cancel(job)['cancelRequested'])
 def test_worker_preserves_safe_restart_provenance(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers.ManagerTests();m=fixture.manager(d);first=m.start('test-shop',vender_id='1',foreground=True);path=Path(d)/'tasks'/(first['taskId']+'.json');original=read_json(path);original.update(status='cancelled',stage='cancelled',authorizationStarted=False);atomic_json(path,original)
   second=m.restart(first['taskId'],foreground=True)
   AuthFlow(Path(d),second['taskId'],second['profile'],'test-shop',fixture.client,fixtures.FakeBrowser(),expected_vender_id='1')
   self.assertEqual(m.restart(first['taskId'],foreground=True)['taskId'],second['taskId'])

class DescendantReviewTests(unittest.TestCase):
 def test_proven_owned_child_is_stopped_after_parent_exits(self):
  import psutil
  child_code='import time; time.sleep(60)'
  parent_code='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c",'+repr(child_code)+']); print(p.pid,flush=True); time.sleep(60)'
  parent=subprocess.Popen([sys.executable,'-c',parent_code],stdout=subprocess.PIPE)
  child=None
  try:
   child=psutil.Process(int(parent.stdout.readline()))
   with tempfile.TemporaryDirectory() as d:
    client=OfficialClient(Path(d));client._login_owners(parent);parent.terminate();parent.wait(timeout=5);client.stop_login(parent)
   self.assertFalse(child.is_running())
  finally:
   if parent.poll() is None:parent.terminate()
   parent.wait(timeout=5);parent.stdout.close()
   if child is not None and child.is_running():child.terminate();child.wait(timeout=5)

if __name__=='__main__':unittest.main()

class CleanupReadinessTests(unittest.TestCase):
 def test_incomplete_owned_cleanup_cannot_leave_completed_ready(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=fixtures.AuthFlowTests.make_flow(self,d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/identity'})
   def failed_cleanup(process):raise RuntimeError('private-error')
   c.stop_login=failed_cleanup;flow.tick();flow.tick();c.process.returncode=0;r=flow.tick()
   self.assertFalse(r['ready']);self.assertEqual(r['status'],'unknown');self.assertTrue(r['cleanupIncomplete']);self.assertNotIn('private-error',json.dumps(r))
