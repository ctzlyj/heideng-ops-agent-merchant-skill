import json,sys,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_browser_host import HostControllerBrowser
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.safety import SafetyError,read_json
from tests.test_auth_flow import FakeClient

class Controller:
 def __init__(self):self.actions=[];self.context='fixture-owned-context';self.logged=True
 def __call__(self,args,**options):
  payload=json.loads(options['input']);action=payload['action'];self.actions.append(action)
  result={'contextId':self.context,'owned':True,'isolated':True,'ok':True}
  if action['kind']=='observe':result.update(loggedIn=self.logged,identity={'shopName':'actual-shop','venderId':'1','shopId':'9'} if self.logged else {},challenge='',token='synthetic-private-token')
  return type('P',(),{'returncode':0,'stdout':json.dumps(result).encode(),'stderr':b''})()

class HostReuseTests(unittest.TestCase):
 def browser(self,d,controller):
  return HostControllerBrowser(Path(d),'a'*24,'alias',['python','controller.py'],runner=controller,clock=lambda:0,observe_interval=0)
 def test_observed_identity_uses_original_host_controller_contract_not_domain_guess(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();browser=self.browser(d,controller);browser.open_jingmai();browser.poll()
   candidate=browser.candidates()[0]
   self.assertEqual(candidate['shopName'],'actual-shop');self.assertTrue(browser.validates_identity(candidate))
   self.assertEqual(controller.actions[0]['kind'],'open_login');self.assertEqual(controller.actions[1]['kind'],'observe')
   self.assertNotIn('synthetic-private',json.dumps(browser.public_observation()))
 def test_alias_confirm_then_oauth_runs_on_same_verified_host_context(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();browser=self.browser(d,controller);client=FakeClient();flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',client,browser)
   flow.tick();flow.tick();self.assertEqual(flow.data['stage'],'waiting_shop_confirmation');self.assertEqual(client.calls,[])
   candidate=flow.status()['identityCandidates'][0];flow.confirm_shop(candidate['fingerprint'],'actual-shop','1');flow.tick()
   self.assertTrue(flow.data['authorizationStarted']);self.assertEqual(len([a for a in controller.actions if a['kind']=='open_login']),1)
   if browser.stage=='jingmai-login':browser.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=synthetic-private-state')
   self.assertEqual(controller.actions[-1]['kind'],'open_oauth')
   with self.assertRaises(SafetyError):browser.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=synthetic-private-state')
   self.assertEqual(len([a for a in controller.actions if a['kind']=='open_oauth']),1)
   self.assertNotIn('synthetic-private',json.dumps(read_json(flow.path)))
   browser.close()
   for path in Path(d).rglob('*.json'):self.assertNotIn('synthetic-private',path.read_text(encoding='utf-8'))
 def test_context_change_never_supplies_identity_or_navigates_oauth(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();browser=self.browser(d,controller);browser.open_jingmai();controller.context='wrong'
   with self.assertRaises(SafetyError):browser.poll()
   self.assertEqual(browser.candidates(),[])
 def test_observation_losing_login_invalidates_candidate(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();browser=self.browser(d,controller);browser.open_jingmai();browser.poll();old=browser.candidates()[0]
   controller.logged=False;browser.poll()
   self.assertEqual(browser.candidates(),[])
   with self.assertRaises(SafetyError):browser.select_identity(old)
 def test_unknown_initial_browser_dispatch_retains_cleanup_guard(self):
  from heideng_merchant.auth_manager import AuthManager
  from tests.test_auth_manager import Client,Runtime
  with tempfile.TemporaryDirectory() as d:
   calls=[]
   def interrupted(args,**options):
    calls.append(json.loads(options['input'])['action']['kind'])
    raise TimeoutError('synthetic-private-error')
   browser=self.browser(d,Controller());browser.runner=interrupted
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',FakeClient(),browser)
   status=flow.tick()
   self.assertEqual(status['status'],'failed')
   self.assertTrue(status.get('cleanupIncomplete'))
   with self.assertRaises(SafetyError):browser.open_jingmai()
   manager=AuthManager(Path(d),client=Client(),runtime=Runtime(),starter=lambda *a,**k:self.fail('worker replayed'),browser_controller=['python','controller.py'])
   with self.assertRaises(SafetyError):manager.restart('a'*24,foreground=True)
   self.assertEqual(calls,['open_login'])
   self.assertNotIn('synthetic-private-error',json.dumps(status))

 def test_oauth_boundary_refreshes_identity_inside_observation_throttle(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();now=[0]
   browser=HostControllerBrowser(Path(d),'a'*24,'alias',['python','controller.py'],runner=controller,clock=lambda:now[0],observe_interval=30)
   browser.open_jingmai();browser.poll();browser.select_identity(browser.candidates()[0])
   now[0]=.1;controller.logged=False;browser.poll()
   with self.assertRaises(SafetyError):browser.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=synthetic-private-state')
   self.assertEqual([a['kind'] for a in controller.actions],['open_login','observe','observe'])
   self.assertEqual(browser.candidates(),[])

 def test_shells_and_secret_shaped_controller_arguments_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   for command in (['cmd.exe','/c','tool'],['powershell.exe','-Command','tool'],['python','--api-key=synthetic-private-value'],['python','--api-key','synthetic-private-value'],['python','sk-synthetic-private-key-value123456']):
    with self.assertRaises(SafetyError):HostControllerBrowser(Path(d),'a'*24,'alias',command)

 def test_missing_host_controller_stops_before_runtime_download_or_worker(self):
  from heideng_merchant.auth_manager import AuthManager
  from tests.test_auth_manager import Client,Runtime
  with tempfile.TemporaryDirectory() as d:
   runtime=Runtime();manager=AuthManager(Path(d),client=Client(),runtime=runtime,starter=lambda *a,**k:self.fail('worker launched'))
   with self.assertRaisesRegex(SafetyError,'host-browser-controller-required'):manager.start('actual-shop',foreground=True)
   self.assertEqual(runtime.calls,0)

 def test_worker_uses_prepared_runtime_with_official_process_dependencies(self):
  from heideng_merchant.auth_manager import AuthManager
  from heideng_merchant.auth_runtime import PACKAGES
  from tests.test_auth_manager import Client,Runtime
  with tempfile.TemporaryDirectory() as d:
   calls=[];runtime=Runtime()
   def launch(args,**options):
    calls.append(args);return type('P',(),{'pid':123})()
   manager=AuthManager(Path(d),client=Client(),runtime=runtime,starter=launch,request=lambda *a,**k:None,startup_wait=0,browser_controller=['python','controller.py'])
   manager.start('actual-shop',foreground=True)
   self.assertEqual(runtime.calls,1)
   self.assertEqual(calls[0][0],str(runtime.python()))
   self.assertIn('psutil',PACKAGES)

 def test_runtime_failure_prevents_auth_worker_and_task_creation(self):
  from heideng_merchant.auth_manager import AuthManager
  from tests.test_auth_manager import Client,Runtime
  class UnavailableRuntime(Runtime):
   def ensure(self):raise SafetyError('browser-runtime-not-prepared')
  with tempfile.TemporaryDirectory() as d:
   manager=AuthManager(Path(d),client=Client(),runtime=UnavailableRuntime(),starter=lambda *a,**k:self.fail('worker launched'),browser_controller=['python','controller.py'])
   with self.assertRaisesRegex(SafetyError,'browser-runtime-not-prepared'):manager.start('actual-shop',foreground=True)
   self.assertEqual(list((Path(d)/'tasks').glob('*.json')),[])

 def test_worker_record_retains_controller_for_safe_restart(self):
  from heideng_merchant.safety import atomic_json
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'tasks'/('a'*24+'.json')
   atomic_json(path,{'kind':'shop-auth','taskId':'a'*24,'profile':'merchant-local-a1','browserProvider':'original-linker-host-controller','browserController':['python','controller.py']})
   browser=self.browser(d,Controller());flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',FakeClient(),browser)
   self.assertEqual(flow.data['browserController'],['python','controller.py'])
   self.assertEqual(read_json(path)['browserProvider'],'original-linker-host-controller')
 def test_controller_option_is_forwarded_from_cli_without_private_payload(self):
  from unittest.mock import patch
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   config=Path(d)/'controller.json';config.write_text('["python","controller.py"]',encoding='utf-8')
   run(parser().parse_args(['--home',d,'auth-start','--shop-name','alias','--foreground','--browser-controller',str(config)]))
   self.assertEqual(manager.return_value.start.call_args.kwargs['browser_controller'],['python','controller.py'])

 def test_uncertain_browser_cleanup_never_allows_restart(self):
  from tests.test_auth_manager import ManagerTests
  from heideng_merchant.safety import atomic_json
  with tempfile.TemporaryDirectory() as d:
   manager=ManagerTests().manager(d);job=manager.start('alias',foreground=True)['taskId'];data=manager._record(job)
   data.update(status='failed',stage='browser_failed',cleanupIncomplete=True)
   atomic_json(manager._path(job),data)
   with self.assertRaises(SafetyError):manager.restart(job,foreground=True)

 def test_global_reuse_rule_and_host_setup_are_visible_to_merchant_agent(self):
  root=Path(__file__).resolve().parents[1]
  skill=(root/'SKILL.md').read_text(encoding='utf-8');registry=json.loads((root/'registry.json').read_text(encoding='utf-8'))
  guide=(root/'references/shop-connection.md').read_text(encoding='utf-8')
  self.assertIn('已验收能力优先复用',skill);self.assertIn('verified-existing-capabilities-first',registry['reusePolicy'])
  for marker in ('--browser-controller','960','不重复扫码','legacy-task-bound','不能伪造'):
   self.assertIn(marker,guide)

 def test_official_shop_id_must_match_verified_host_shop_id(self):
  import time
  with tempfile.TemporaryDirectory() as d:
   browser=self.browser(d,Controller());client=FakeClient();client.identity=lambda profile:{'shopName':'actual-shop','venderId':'1','shopId':'10','shopType':'POP'}
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',client,browser);flow.tick();flow.tick()
   candidate=browser.candidates()[0];flow.confirm_shop(candidate['fingerprint'],'actual-shop','1');flow.tick();client.process.returncode=0
   for _ in range(20):
    flow.tick()
    if flow.data['stage'] in flow.TERMINAL:break
    time.sleep(.01)
   self.assertFalse(flow.data['ready']);self.assertEqual(flow.data['stage'],'identity_mismatch')

 def test_slow_host_observation_cannot_start_oauth_after_task_deadline(self):
  with tempfile.TemporaryDirectory() as d:
   now=[0];controller=Controller();browser=HostControllerBrowser(Path(d),'a'*24,'actual-shop',['python','controller.py'],runner=controller,clock=lambda:now[0],observe_interval=0)
   client=FakeClient();flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','actual-shop',client,browser,clock=lambda:now[0],timeout=900)
   flow.tick();original=controller.__call__
   def slow(args,**options):
    value=original(args,**options)
    if json.loads(options['input'])['action']['kind']=='observe':now[0]=901
    return value
   browser.runner=slow;flow.tick()
   self.assertEqual(client.calls,[]);self.assertEqual(flow.data['stage'],'timed_out')
