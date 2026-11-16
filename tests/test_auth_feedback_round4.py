"""Synthetic regressions for HD-009/010/011/012/015, no merchant access."""
import json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.auth_browser_host import HostControllerBrowser
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from heideng_merchant.operations import Operations
from tests import test_auth_manager as manager_fixtures
from tests.test_host_auth_reuse import Controller
from tests.test_auth_flow import FakeClient

class FeedbackAuthTests(unittest.TestCase):
 def dead_cleanup(self,d):
  fixture=manager_fixtures.ManagerTests();manager=fixture.manager(d);job=manager.start('test-shop',foreground=True)['taskId']
  data=manager._record(job);data.update(status='failed',stage='browser_failed',cleanupIncomplete=True,authorizationStarted=False,authorizationOutcomeUnknown=False)
  atomic_json(manager._path(job),data);launch=read_json(Path(d)/'auth/launches'/f'{job}.json')
  atomic_json(Path(d)/'auth/handles'/f'{job}.json',{'taskId':job,'workerPid':123,'port':12345,'brokerStopped':True,'startedAt':launch['startedAt']})
  action='b'*32;atomic_json(Path(d)/'auth/browser-actions'/job/f'{action}.json',{'taskId':job,'actionId':action,'kind':'open_login','phase':'dispatched'})
  manager.process_probe=lambda pid:'exited'
  return manager,fixture,job,action
 def inspection(self,job,action,**changes):
  def runner(command,**options):
   payload=json.loads(options['input']);self.assertEqual(payload['action']['kind'],'verify_cleanup');self.assertEqual(payload['jobId'],job)
   result={'ok':True,'taskId':job,'inspectionId':payload['action']['id'],'actionIds':[action],'owned':True,'inspectionVerified':True,'noLiveTaskResources':True,**changes}
   return type('P',(),{'returncode':0,'stdout':json.dumps(result).encode()})()
  return runner
 def test_failed_cleanup_has_formal_next_action(self):
  with tempfile.TemporaryDirectory() as d:
   manager,fixture,job,action=self.dead_cleanup(d)
   self.assertEqual(manager.reconcile(job).get('nextAction'),'auth-prove-cleanup')
 def test_proven_owned_cleanup_unlocks_original_target_without_replay(self):
  with tempfile.TemporaryDirectory() as d:
   manager,fixture,job,action=self.dead_cleanup(d);manager.controller_runner=self.inspection(job,action)
   with self.assertRaises(SafetyError):manager.restart(job,foreground=True)
   result=manager.prove_cleanup(job)
   self.assertTrue(result['cleanupVerified']);self.assertTrue(result['safeToRestart']);self.assertFalse(result['cleanupIncomplete']);self.assertFalse(result['oauthReplayed'])
   new=manager.restart(job,foreground=True);self.assertNotEqual(new['taskId'],job);self.assertEqual(len(fixture.calls),2)
 def test_cleanup_inspection_must_bind_exact_task_and_actions(self):
  for changes in ({'taskId':'c'*24},{'inspectionId':'0'*32},{'actionIds':[]},{'owned':False},{'inspectionVerified':False},{'noLiveTaskResources':False}):
   with self.subTest(changes=changes),tempfile.TemporaryDirectory() as d:
    manager,_,job,action=self.dead_cleanup(d);manager.controller_runner=self.inspection(job,action,**changes)
    with self.assertRaises(SafetyError):manager.prove_cleanup(job)
    self.assertTrue(manager._record(job)['cleanupIncomplete'])
 def test_cleanup_never_inspects_alive_unknown_or_started_oauth(self):
  for field,value in (('process','alive'),('process','unknown'),('authorizationStarted',True),('authorizationOutcomeUnknown',True)):
   with self.subTest(field=field,value=value),tempfile.TemporaryDirectory() as d:
    manager,_,job,action=self.dead_cleanup(d);manager.controller_runner=lambda *a,**kw:self.fail('unsafe inspection')
    if field=='process':manager.process_probe=lambda pid:value
    else:
     data=manager._record(job);data[field]=value;atomic_json(manager._path(job),data)
    with self.assertRaises(SafetyError):manager.prove_cleanup(job)
    self.assertTrue(manager._record(job)['cleanupIncomplete'])
 def test_cleanup_rechecks_original_receipt_after_inspection(self):
  with tempfile.TemporaryDirectory() as d:
   manager,_,job,action=self.dead_cleanup(d);valid=self.inspection(job,action)
   def changed(command,**options):
    result=valid(command,**options);data=manager._record(job);data['authorizationStarted']=True;atomic_json(manager._path(job),data);return result
   manager.controller_runner=changed
   with self.assertRaises(SafetyError):manager.prove_cleanup(job)
   self.assertTrue(manager._record(job)['cleanupIncomplete'])
 def test_start_and_wait_distinguish_cancelled_old_task_from_new_launch(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=manager_fixtures.ManagerTests();manager=fixture.manager(d);first=manager.start('test-shop',foreground=True)
   self.assertTrue(first.get('newTask'));self.assertFalse(first.get('reusedExisting'))
   data=manager._record(first['taskId']);data.update(status='cancelled',stage='cancelled');atomic_json(manager._path(first['taskId']),data)
   for wait in (False,True):
    old=manager.start('test-shop',foreground=True,wait=wait)
    self.assertFalse(old['newTask']);self.assertTrue(old['reusedExisting']);self.assertEqual(old['nextAction'],'auth-restart');self.assertEqual(old['taskId'],first['taskId'])
   self.assertEqual(len(fixture.calls),1)
 def test_explicit_alias_binding_reuses_existing_auth_and_survives_refresh(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=manager_fixtures.ManagerTests();manager=fixture.manager(d);Operations(Path(d),manager.client).connect('merchant-prior-a1','test-shop','1')
   with self.assertRaises(SafetyError):manager.bind_alias('alias','merchant-prior-a1',confirmed=False)
   manager.bind_alias('alias','merchant-prior-a1',confirmed=True)
   result=manager.ensure_shop('alias');self.assertTrue(result['ready']);self.assertEqual(result['profile'],'merchant-prior-a1');self.assertEqual(fixture.calls,[])
   manager.ensure_shop('test-shop');self.assertIn('alias',read_json(Path(d)/'shops.json')['merchant-prior-a1']['aliases'])
 def test_alias_cannot_cross_bind_or_skip_official_identity_check(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=manager_fixtures.ManagerTests();manager=fixture.manager(d);Operations(Path(d),manager.client).connect('merchant-prior-a1','test-shop','1')
   atomic_json(Path(d)/'shops.json',{**read_json(Path(d)/'shops.json'),'merchant-other-a1':{'shopName':'other','venderId':'2','shopId':'8','aliases':['alias']}})
   with self.assertRaises(SafetyError):manager.bind_alias('alias','merchant-prior-a1',confirmed=True)
   manager.client.actual['venderId']='2'
   with self.assertRaises(SafetyError):manager.bind_alias('new-alias','merchant-prior-a1',confirmed=True)

class FeedbackAliasCollisionTests(unittest.TestCase):
 def test_later_real_name_collision_keeps_both_exact_authorizations_usable(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=manager_fixtures.ManagerTests();manager=fixture.manager(d)
   identities={'merchant-shop-a1':{'shopName':'shop-a','venderId':'1','shopId':'9','shopType':'POP'},'merchant-shop-b1':{'shopName':'shop-b','venderId':'2','shopId':'8','shopType':'POP'}}
   manager.client.identity=lambda profile:dict(identities[profile])
   ops=Operations(Path(d),manager.client)
   ops.connect('merchant-shop-a1','shop-a','1',confirmed_alias='shop-b')
   ops.connect('merchant-shop-b1','shop-b','2')
   with self.assertRaises(SafetyError):manager.ensure_shop('shop-b')
   self.assertEqual(manager.ensure_shop('shop-b',vender_id='1')['profile'],'merchant-shop-a1')
   self.assertEqual(manager.ensure_shop('shop-b',vender_id='2')['profile'],'merchant-shop-b1')
   self.assertEqual(fixture.calls,[])
   self.assertIn('shop-b',read_json(Path(d)/'shops.json')['merchant-shop-a1']['aliases'])
   with self.assertRaisesRegex(SafetyError,'confirm-vender-id'):manager.ensure_shop('shop-b')

class FeedbackCommandTests(unittest.TestCase):
 def test_agent_can_verify_cleanup_and_confirm_existing_shop_alias(self):
  from unittest.mock import patch
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   manager.return_value.prove_cleanup.return_value={'cleanupVerified':True}
   run(parser().parse_args(['--home',d,'auth-prove-cleanup','--task-id','a'*24]))
   manager.return_value.prove_cleanup.assert_called_once_with('a'*24)
   manager.return_value.bind_alias.return_value={'ready':True}
   run(parser().parse_args(['--home',d,'auth-bind-alias','--shop-name','alias','--profile','merchant-prior-a1','--confirm']))
   manager.return_value.bind_alias.assert_called_once_with('alias','merchant-prior-a1',confirmed=True)

class FeedbackObservationTests(unittest.TestCase):
 def setup_flow(self,d,runner,*,interval=0,clock=None):
  browser=HostControllerBrowser(Path(d),'a'*24,'alias',['python','fixture.py'],runner=runner,observe_interval=interval,clock=clock)
  flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',FakeClient(),browser)
  flow.tick();return flow,browser
 def test_one_navigation_timeout_waits_and_can_observe_again(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();seen=[0]
   def runner(command,**options):
    if json.loads(options['input'])['action']['kind']=='observe':
     seen[0]+=1
     if seen[0]==1:raise TimeoutError('synthetic-private-error')
    return controller(command,**options)
   flow,browser=self.setup_flow(d,runner);first=flow.tick()
   self.assertEqual(first['status'],'running');self.assertEqual(first['observeConsecutiveFailures'],1);self.assertEqual(flow.client.calls,[])
   second=flow.tick();self.assertEqual(second['stage'],'waiting_shop_confirmation');self.assertEqual(second['observeConsecutiveFailures'],0);self.assertEqual(second['observeFailureCount'],1)
   self.assertNotIn('synthetic-private-error',json.dumps(second))
 def test_throttled_tick_does_not_reset_error_streak(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();now=[0]
   def runner(command,**options):
    if json.loads(options['input'])['action']['kind']=='observe':raise TimeoutError()
    return controller(command,**options)
   flow,browser=self.setup_flow(d,runner,interval=2,clock=lambda:now[0]);flow.tick()
   now[0]=.1
   for _ in range(10):flow.tick()
   self.assertEqual(flow.status()['observeConsecutiveFailures'],1);self.assertEqual(flow.status()['status'],'running')
 def test_bounded_repeated_unavailable_has_clear_reason(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller()
   def runner(command,**options):
    if json.loads(options['input'])['action']['kind']=='observe':raise TimeoutError('synthetic-private-error')
    return controller(command,**options)
   flow,browser=self.setup_flow(d,runner)
   for _ in range(5):flow.tick()
   result=flow.status();self.assertEqual(result['status'],'failed');self.assertEqual(result['reason'],'host-observe-repeated-unavailable');self.assertEqual(result['observeConsecutiveFailures'],5);self.assertEqual(flow.client.calls,[])
 def test_changed_context_is_fatal_not_transient(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();flow,browser=self.setup_flow(d,controller);controller.context='not-the-owned-context'
   result=flow.tick();self.assertEqual(result['status'],'failed');self.assertEqual(result.get('observeError'),'host-observe-invalid-or-unavailable')
   self.assertFalse(any(action['kind']=='close' for action in controller.actions));self.assertTrue(result['cleanupIncomplete'])
 def test_transient_read_at_oauth_boundary_does_not_relaunch_or_navigate_twice(self):
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();inside=[False];fail=[True]
   def runner(command,**options):
    if inside[0] and fail[0] and json.loads(options['input'])['action']['kind']=='observe':fail[0]=False;raise TimeoutError()
    return controller(command,**options)
   browser=HostControllerBrowser(Path(d),'a'*24,'actual-shop',['python','fixture.py'],runner=runner,observe_interval=0)
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','actual-shop',FakeClient(),browser)
   navigate=browser.navigate_oauth
   def boundary(url):
    inside[0]=True
    try:return navigate(url)
    finally:inside[0]=False
   browser.navigate_oauth=boundary
   for _ in range(20):
    result=flow.tick();self.assertEqual(result['status'],'running')
    if result['stage']=='waiting_oauth':break
   self.assertEqual(result['stage'],'waiting_oauth');self.assertFalse(fail[0])
   self.assertEqual(len([a for a in controller.actions if a['kind']=='open_oauth']),1)
   self.assertEqual(len([a for a in flow.client.calls if a[0]=='login']),1)

 def test_error_reply_cannot_hide_explicit_ownership_loss(self):
  for returncode in (0,1):
   for error in ('controller-failed','navigation-in-progress'):
    with self.subTest(returncode=returncode,error=error),tempfile.TemporaryDirectory() as d:
     controller=Controller()
     def runner(command,**options):
      if json.loads(options['input'])['action']['kind']=='observe':
       return type('P',(),{'returncode':returncode,'stdout':json.dumps({'ok':False,'error':error,'owned':False,'contextId':'other-context'}).encode()})()
      return controller(command,**options)
     flow,browser=self.setup_flow(d,runner);result=flow.tick()
     self.assertEqual(result['status'],'failed');self.assertTrue(result['cleanupIncomplete']);self.assertTrue(browser.ownership_lost)
     self.assertFalse(any(action['kind']=='close' for action in controller.actions))

 def test_pre_navigation_failure_limit_survives_successful_regular_poll(self):
  for nonzero in (False,True):
   with self.subTest(nonzero=nonzero),tempfile.TemporaryDirectory() as d:
    controller=Controller();inside=[False]
    def runner(command,**options):
     if inside[0] and json.loads(options['input'])['action']['kind']=='observe':
      if nonzero:return type('P',(),{'returncode':1,'stdout':b'{}'})()
      raise TimeoutError()
     return controller(command,**options)
    browser=HostControllerBrowser(Path(d),'a'*24,'actual-shop',['python','fixture.py'],runner=runner,observe_interval=0)
    flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','actual-shop',FakeClient(),browser)
    original=browser.navigate_oauth
    def boundary(url):
     inside[0]=True
     try:return original(url)
     finally:inside[0]=False
    browser.navigate_oauth=boundary
    for _ in range(30):
     result=flow.tick()
     if result['status']!='running':break
    self.assertEqual(result['status'],'unknown');self.assertEqual(result['reason'],'host-observe-repeated-unavailable');self.assertEqual(result['preNavigationConsecutiveFailures'],5)
    self.assertFalse(any(action['kind']=='open_oauth' for action in controller.actions));self.assertEqual(len([a for a in flow.client.calls if a[0]=='login']),1)

 def test_confirmed_alias_survives_pre_navigation_timeout_and_is_saved(self):
  class ActualClient(FakeClient):
   def identity(self,profile):return {'shopName':'actual-shop','venderId':'1','shopId':'9','shopType':'POP'}
  with tempfile.TemporaryDirectory() as d:
   controller=Controller();inside=[False];fail=[True]
   def runner(command,**options):
    if inside[0] and fail[0] and json.loads(options['input'])['action']['kind']=='observe':fail[0]=False;raise TimeoutError()
    return controller(command,**options)
   browser=HostControllerBrowser(Path(d),'a'*24,'alias',['python','fixture.py'],runner=runner,observe_interval=0)
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',ActualClient(),browser);flow.tick();flow.tick()
   candidate=flow.status()['identityCandidates'][0];flow.confirm_shop(candidate['fingerprint'],'actual-shop','1')
   original=browser.navigate_oauth
   def boundary(url):
    inside[0]=True
    try:return original(url)
    finally:inside[0]=False
   browser.navigate_oauth=boundary
   for _ in range(20):
    result=flow.tick()
    if result['stage']=='waiting_oauth':break
   self.assertEqual(result['stage'],'waiting_oauth');flow.client.process.returncode=0
   for _ in range(10):flow.tick()
   self.assertTrue(flow.status()['ready']);self.assertTrue(flow.status()['identityConfirmed']);self.assertIn('alias',read_json(Path(d)/'shops.json')['merchant-local-a1']['aliases'])

 def test_ready_has_verified_diagnostic_and_current_candidate(self):
  class ActualClient(FakeClient):
   def identity(self,profile):return {'shopName':'actual-shop','venderId':'1','shopId':'9','shopType':'POP'}
  with tempfile.TemporaryDirectory() as d:
   browser=HostControllerBrowser(Path(d),'a'*24,'actual-shop',['python','fixture.py'],runner=Controller(),observe_interval=0)
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','actual-shop',ActualClient(),browser);flow.tick();flow.tick();flow.client.process.returncode=0
   for _ in range(10):flow.tick()
   result=flow.status();self.assertTrue(result['ready']);self.assertEqual(result['identityDiagnostic'],'official-shop-identity-verified');self.assertEqual(len(result['identityCandidates']),1)

if __name__=='__main__':unittest.main()
