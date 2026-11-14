import hashlib,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_manager import AuthManager
from heideng_merchant.auth_broker import BrokerState,allowed_request
from heideng_merchant.safety import SafetyError,atomic_json

class Runtime:
 def __init__(self):self.calls=0
 def ensure(self):self.calls+=1;return {'status':'ready'}
 def python(self):return Path('test-only-python')
class Client:
 def __init__(self):self.installs=0;self.identity_calls=0;self.actual={'venderId':'1','shopId':'9','shopName':'test-shop','shopType':'POP'}
 def ready(self):return True
 def install(self):self.installs+=1
 def identity(self,profile):self.identity_calls+=1;return dict(self.actual)
class ManagerTests(unittest.TestCase):
 def manager(self,d):
  self.calls=[];self.runtime=Runtime();self.client=Client()
  def start(args,**options):self.calls.append((args,options));return type('P',(),{'pid':123})()
  return AuthManager(Path(d),client=self.client,runtime=self.runtime,starter=start,request=lambda *a,**k:None,startup_wait=0)
 def test_start_requires_foreground_and_has_no_side_effects_otherwise(self):
  with tempfile.TemporaryDirectory() as d:
   m=self.manager(d)
   with self.assertRaises(SafetyError):m.start('test-shop',foreground=False)
   self.assertEqual(self.calls,[]);self.assertEqual(self.runtime.calls,0)
 def test_repeated_start_never_launches_second_worker_even_unreachable(self):
  with tempfile.TemporaryDirectory() as d:
   m=self.manager(d);first=m.start('test-shop',foreground=True);second=m.start('test-shop',foreground=True)
   self.assertEqual(first['taskId'],second['taskId']);self.assertEqual(len(self.calls),1);self.assertTrue(first['profile'].startswith('merchant-'));self.assertFalse(first['ready']);self.assertEqual(m.status(first['taskId'])['workerReachable'],False)
   self.assertNotIn('JD_LLM_API_KEY',self.calls[0][1]['env']);self.assertNotIn('--code',self.calls[0][0])
 def test_unknown_launch_is_durable_and_not_retried(self):
  with tempfile.TemporaryDirectory() as d:
   m=self.manager(d)
   def start(*a,**k):raise OSError('fake-private-error')
   m.starter=start;first=m.start('test-shop',foreground=True);second=m.start('test-shop',foreground=True)
   self.assertEqual(second['taskId'],first['taskId']);self.assertEqual(second['status'],'unknown');self.assertNotIn('fake-private-error',json.dumps(second))
 def test_recovery_queries_only_original_profile_and_preserves_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   m=self.manager(d);r=m.start('test-shop',foreground=True,vender_id='1');path=Path(d)/'tasks'/(r['taskId']+'.json');data=json.loads(path.read_text());data.update(status='unknown',stage='auth_outcome_unknown');atomic_json(path,data)
   recovered=m.recover(r['taskId']);self.assertEqual(recovered['status'],'unknown');self.assertTrue(recovered['targetStateVerified']);self.assertEqual(len(self.calls),1)
   self.client.actual['venderId']='2'
   with self.assertRaises(SafetyError):m.recover(r['taskId'])
 def test_existing_shop_requires_realtime_validation_not_oauth(self):
  with tempfile.TemporaryDirectory() as d:
   m=self.manager(d);atomic_json(Path(d)/'shops.json',{'merchant-old-a1':{**self.client.actual,'profile':'merchant-old-a1'}})
   r=m.ensure_shop('test-shop',foreground=False);self.assertTrue(r['ready']);self.assertEqual(self.calls,[]);self.assertEqual(self.client.identity_calls,1)

class BrokerTests(unittest.TestCase):
 def test_website_and_dns_rebinding_requests_cannot_observe_or_cancel(self):
  self.assertTrue(allowed_request('POST','/cancel',{'Host':'127.0.0.1:1234','X-Heideng-Local':'1','X-Heideng-Task':'a'*24},1234,task_id='a'*24))
  for h in ({'Host':'attacker.example:1234','X-Heideng-Local':'1'},{'Host':'127.0.0.1:1234','Origin':'https://attacker.example','X-Heideng-Local':'1'},{'Host':'127.0.0.1:1234'}):
   self.assertFalse(allowed_request('POST','/cancel',h,1234))
  self.assertFalse(allowed_request('GET','/cancel',{'Host':'127.0.0.1:1234','X-Heideng-Local':'1','X-Heideng-Task':'a'*24},1234,task_id='a'*24))
 def test_broker_snapshot_drops_all_private_and_arbitrary_fields(self):
  b=BrokerState();b.update({'taskId':'a'*24,'stage':'waiting_oauth','ready':False,'oauthUrl':'https://example/?state=fake-private','token':'fake-private','unknownExtra':'fake-private'}, {'browserStage':'official-oauth','text':'fake-private','identity':None})
  self.assertNotIn('fake-private',json.dumps(b.status()));self.assertNotIn('fake-private',json.dumps(b.observe()));b.cancel();self.assertTrue(b.cancelled.is_set())

if __name__=='__main__':unittest.main()

class AuthBoundaryTests(unittest.TestCase):
 def test_recovery_validates_task_before_creating_any_lock_file(self):
  with tempfile.TemporaryDirectory() as d:
   m=AuthManager(Path(d),request=lambda *a,**k:None)
   with self.assertRaises(SafetyError):m.recover('../escaped')
   self.assertFalse((Path(d)/'escaped.lock').exists());self.assertFalse((Path(d)/'auth').exists())
 def test_same_shop_with_disagreeing_target_cannot_start_parallel_auth(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=ManagerTests();m=fixture.manager(d);m.start('test-shop',vender_id='1',foreground=True)
   with self.assertRaisesRegex(SafetyError,'active-auth-target-conflict'):m.start('test-shop',vender_id='2',foreground=True)
   self.assertEqual(len(fixture.calls),1)

class AuthRestartTests(unittest.TestCase):
 def test_explicit_prescan_restart_is_idempotent_and_keeps_original_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=ManagerTests();m=fixture.manager(d);first=m.start('test-shop',foreground=True,vender_id='1')
   path=Path(d)/'tasks'/(first['taskId']+'.json');data=json.loads(path.read_text());data.update(status='cancelled',stage='cancelled',authorizationOutcomeUnknown=False);atomic_json(path,data)
   second=m.restart(first['taskId'],foreground=True);third=m.restart(first['taskId'],foreground=True)
   self.assertNotEqual(first['taskId'],second['taskId']);self.assertEqual(second['taskId'],third['taskId']);self.assertEqual(len(fixture.calls),2);self.assertTrue(path.is_file())
 def test_unknown_or_already_started_auth_cannot_restart(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=ManagerTests();m=fixture.manager(d);first=m.start('test-shop',foreground=True,vender_id='1')
   path=Path(d)/'tasks'/(first['taskId']+'.json');data=json.loads(path.read_text());data.update(status='cancelled',stage='cancelled',authorizationStarted=True);atomic_json(path,data)
   with self.assertRaises(SafetyError):m.restart(first['taskId'],foreground=True)
   self.assertEqual(len(fixture.calls),1)
