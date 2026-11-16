import contextlib,io,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_flow import AuthFlow,BrowserIdentityProof
from heideng_merchant.auth_browser import PlaywrightBrowser
from heideng_merchant.safety import redact,SafetyError
from heideng_merchant.auth_broker import BrokerState,public_status,allowed_request
from tests import test_auth_browser as browser_fixture
from tests import test_auth_flow as flow_fixture

class Context(browser_fixture.Context):
 def __init__(self):super().__init__();self.handlers={};self.pages=[self.page];self.page.context=self
 def on(self,event,handler):self.handlers[event]=handler
 def popup(self):
  page=browser_fixture.Page();page.context=self;self.pages.append(page)
  if 'page' in self.handlers:self.handlers['page'](page)
  return page
class Driver(browser_fixture.Driver):
 def launch(self,**kw):
  self.browser.new_context=lambda **k:Context()
  return self.browser
class Factory:
 def __init__(self):self.driver=Driver()
 def start(self):return self.driver
class Response(browser_fixture.Response):
 def __init__(self,page,name='real-shop',vid='1',url='https://jingmai.jd.com/api/identity',content_type='application/json'):
  self.url=url;self.frame=type('Frame',(),{'page':page})();self.name=name;self.vid=vid;self.content_type=content_type
 def header_value(self,key):return self.content_type if key=='content-type' else '100'
 def json(self):return {'data':{'shopName':self.name,'venderId':self.vid,'shopType':'0','token':'private-test-value'}}

class IdentityPopupTests(unittest.TestCase):
 def browser(self):
  f=Factory();b=PlaywrightBrowser('real-shop',factory=lambda:f,headless=True);b.open_jingmai();self.addCleanup(b.close);return b
 def test_popup_identity_is_observed_and_oauth_uses_authenticated_page(self):
  b=self.browser();original=b.page;popup=b.context.popup()
  self.assertIn('response',b.context.handlers)
  b.context.handlers['response'](Response(popup));b.poll()
  self.assertEqual(b.proof()['shopName'],'real-shop');self.assertIs(b.page,popup)
  b.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=private-test-state')
  self.assertEqual(len(popup.urls),1);self.assertEqual(len(original.urls),1)
  self.assertNotIn('private-test',json.dumps(b.public_observation()))
 def test_popup_survives_original_landing_page_close(self):
  b=self.browser();original=b.page;popup=b.context.popup();original.closed=True
  b.poll();self.assertIs(b.page,popup)
 def test_response_diagnostics_distinguish_rejected_domain_type_and_missing_identity(self):
  b=self.browser();emit=b.context.handlers['response']
  emit(Response(b.page,url='https://untrusted.example/identity'))
  emit(Response(b.page,content_type='text/html'))
  result=b.public_observation()
  self.assertEqual(result['untrustedResponseCount'],1);self.assertEqual(result['nonJsonResponseCount'],1)
  self.assertEqual(result['observedIdentityResponses'],0);self.assertEqual(result['identityDiagnostic'],'no-eligible-json-response-yet')
 def test_closed_identity_page_cannot_authorize_from_landing_or_unrelated_tab(self):
  b=self.browser();popup=b.context.popup();b.context.handlers['response'](Response(popup));candidate=b.candidates()[0]
  popup.closed=True;b.poll()
  self.assertEqual(b.candidates(),[]);self.assertIsNone(b.proof())
  with self.assertRaises(SafetyError):b.select_identity(candidate)
 def test_top_level_navigation_invalidates_old_page_evidence(self):
  b=self.browser();popup=b.context.popup();popup.main_frame=object();b.context.handlers['response'](Response(popup));candidate=b.candidates()[0]
  popup.handlers['framenavigated'](popup.main_frame)
  self.assertEqual(b.candidates(),[])
  with self.assertRaises(SafetyError):b.select_identity(candidate)
 def test_wrong_context_cannot_supply_identity(self):
  b=self.browser();foreign=Context().page;b.context.handlers['response'](Response(foreign))
  self.assertIsNone(b.proof())

class CandidateBrowser(flow_fixture.FakeBrowser):
 def __init__(self,alias='alias'):
  super().__init__();self.tracker=BrowserIdentityProof(alias)
  self.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'real-shop','venderId':'1','shopType':'0'})
 def proof(self):return self.tracker.proof()
 def candidates(self):return self.tracker.candidates()
 def public_observation(self):return self.tracker.summary()

class IdentityConfirmationTests(unittest.TestCase):
 def flow(self,d):
  client=flow_fixture.FakeClient();browser=CandidateBrowser();flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',client,browser)
  flow.tick();flow.tick();return flow,client,browser
 def test_alias_waits_for_user_confirmation_without_second_scan(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=self.flow(d);status=flow.status()
   self.assertEqual(status['stage'],'waiting_shop_confirmation');self.assertEqual(client.calls,[])
   candidate=status['identityCandidates'][0]
   flow.confirm_shop(candidate['fingerprint'],'real-shop','1');flow.tick()
   self.assertEqual(flow.data['shopName'],'real-shop');self.assertEqual(flow.data['requestedShopName'],'alias')
   self.assertTrue(flow.data['authorizationStarted']);self.assertEqual(len(browser.opened),1)
   self.assertEqual(len([c for c in client.calls if c[0]=='login']),1)
 def test_changed_or_wrong_candidate_never_authorizes(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=self.flow(d);candidate=flow.status()['identityCandidates'][0]
   with self.assertRaises(SafetyError):flow.confirm_shop(candidate['fingerprint'],'wrong-shop','1')
   browser.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'changed-shop','venderId':'1','shopType':'0'})
   with self.assertRaises(SafetyError):flow.confirm_shop(candidate['fingerprint'],'real-shop','1')
   self.assertEqual(client.calls,[])
 def test_candidate_change_after_confirmation_requires_fresh_confirmation(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=self.flow(d);candidate=browser.candidates()[0]
   flow.confirm_shop(candidate['fingerprint'],'real-shop','1')
   browser.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'changed-shop','venderId':'1','shopType':'0'})
   flow.tick()
   self.assertEqual(client.calls,[]);self.assertEqual(flow.data['stage'],'waiting_shop_confirmation')
   self.assertFalse(flow.data['identityConfirmed'])
 def test_multiple_candidates_require_exact_choice_and_never_pick_first(self):
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=self.flow(d);browser.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'second-shop','venderId':'2','shopType':'0'});flow.tick()
   self.assertEqual(len(flow.data['identityCandidates']),2);self.assertEqual(client.calls,[])
 def test_explicit_vender_id_cannot_be_overridden_by_confirmation(self):
  with tempfile.TemporaryDirectory() as d:
   client=flow_fixture.FakeClient();browser=CandidateBrowser();flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',client,browser,expected_vender_id='2')
   flow.tick();flow.tick();candidate=browser.candidates()[0]
   with self.assertRaises(SafetyError):flow.confirm_shop(candidate['fingerprint'],'real-shop','1')
   self.assertEqual(client.calls,[])
 def test_discovered_candidates_strip_sensitive_fields_and_passport_is_not_identity(self):
  tracker=BrowserIdentityProof('alias')
  tracker.observe_json('https://passport.shop.jd.com/login',{'shopName':'fake-shop','venderId':'3'})
  tracker.observe_json('https://jingmai.jd.com/identity?token=private-test-token',{'shopName':'real-shop','venderId':'1','token':'private-test-token'})
  self.assertEqual(len(tracker.candidates()),1);self.assertNotIn('private-test',json.dumps(tracker.candidates()))
 def test_response_paths_and_object_keys_are_not_exported_as_evidence(self):
  tracker=BrowserIdentityProof('alias')
  tracker.observe_json('https://jingmai.jd.com/private-test-secret/identity',{'private-test-key':{'shopName':'real-shop','venderId':'1'}})
  self.assertNotIn('private-test',json.dumps(tracker.candidates()))

class StateBooleanTests(unittest.TestCase):
 def test_known_boolean_fields_stay_boolean_in_cli_json(self):
  from unittest.mock import patch
  from heideng_merchant.cli import main
  with patch('heideng_merchant.cli.run',return_value={'status':'cancelled','authorizationOutcomeUnknown':False,'authorizationStarted':True}),contextlib.redirect_stdout(io.StringIO()) as out:
   self.assertEqual(main(['catalog']),0)
  value=json.loads(out.getvalue());self.assertIs(value['authorizationOutcomeUnknown'],False);self.assertIs(value['authorizationStarted'],True)
 def test_boolean_exemption_does_not_expose_strings_or_credentials(self):
  for value in ('private-test-value',{'token':'private-test-value'},1):
   self.assertEqual(redact({'authorizationOutcomeUnknown':value})['authorizationOutcomeUnknown'],'[REDACTED]')
  self.assertEqual(redact({'token':False,'Authorization':'Bearer private-test-value'})['token'],'[REDACTED]')
  self.assertIs(json.loads(redact('{"authorizationOutcomeUnknown":false}'))['authorizationOutcomeUnknown'],False)

class ConfirmationBrokerTests(unittest.TestCase):
 def test_current_candidate_is_queued_not_oauth_executed_in_http_thread(self):
  state=BrokerState();candidate={'shopName':'real-shop','venderId':'1','fingerprint':'b'*64}
  state.update({'taskId':'a'*24,'status':'running','stage':'waiting_shop_confirmation','identityCandidates':[candidate]})
  self.assertTrue(state.confirm_shop('a'*24,candidate))
  self.assertEqual(state.take_confirmation(),candidate);self.assertIsNone(state.take_confirmation())
  self.assertFalse(state.confirm_shop('a'*24,{**candidate,'shopName':'wrong'}))
 def test_confirm_action_is_protected_and_payload_publication_is_bounded(self):
  headers={'Host':'127.0.0.1:1234','X-Heideng-Local':'1','X-Heideng-Task':'a'*24}
  self.assertTrue(allowed_request('POST','/confirm-shop',headers,1234,task_id='a'*24))
  self.assertFalse(allowed_request('POST','/confirm-shop',{**headers,'Origin':'https://attacker.example'},1234,task_id='a'*24))
  result=public_status({'taskId':'a'*24,'stage':'waiting_shop_confirmation','status':'running','identityCandidates':[{'shopName':'real-shop','venderId':'1','fingerprint':'b'*64,'token':'private-test-token'}]})
  self.assertIn('确认',result['userAction']);self.assertNotIn('private-test',json.dumps(result))
 def test_manager_cli_sends_exact_confirmed_identity_not_restarts(self):
  from unittest.mock import patch
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   manager.return_value.confirm_shop.return_value={'confirmationRequested':True}
   run(parser().parse_args(['--home',d,'auth-confirm-shop','--task-id','a'*24,'--shop-name','real-shop','--vender-id','1','--fingerprint','b'*64,'--confirm']))
   manager.return_value.confirm_shop.assert_called_once_with('a'*24,'real-shop','1','b'*64,confirmed=True)
   manager.return_value.start.assert_not_called()
 def test_completed_alias_reuses_exact_original_registered_profile(self):
  from tests import test_auth_manager as fixture
  from heideng_merchant.auth_manager import AuthManager
  from heideng_merchant.safety import atomic_json
  with tempfile.TemporaryDirectory() as d:
   client=fixture.Client();state=Path(d)
   atomic_json(state/'shops.json',{'merchant-prior-a1':{**client.actual,'profile':'merchant-prior-a1'}})
   atomic_json(state/'auth'/'targets.json',{'public-target-slot':'a'*24})
   atomic_json(state/'tasks'/('a'*24+'.json'),{'kind':'shop-auth','taskId':'a'*24,'status':'completed','ready':True,'identityConfirmed':True,'requestedShopName':'alias','shopName':'test-shop','venderId':'1','profile':'merchant-prior-a1'})
   manager=AuthManager(state,client=client,starter=lambda *a,**kw:self.fail('new browser opened'))
   result=manager.ensure_shop('alias');self.assertTrue(result['ready']);self.assertEqual(result['profile'],'merchant-prior-a1');self.assertEqual(client.identity_calls,1)


class ConfirmationLoopbackTests(unittest.TestCase):
 def server(self):
  import threading
  from heideng_merchant.auth_broker import make_server
  state=BrokerState();candidate={'shopName':'real-shop','venderId':'1','fingerprint':'b'*64}
  state.update({'taskId':'a'*24,'status':'running','stage':'waiting_shop_confirmation','identityCandidates':[candidate]})
  server=make_server(state);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  def cleanup():server.shutdown();server.server_close();thread.join(3)
  self.addCleanup(cleanup);return state,candidate,server
 def post(self,server,body,**extra):
  import http.client
  connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
  headers={'X-Heideng-Local':'1','X-Heideng-Task':'a'*24,'Content-Type':'application/json',**extra}
  connection.request('POST','/confirm-shop',body=body,headers=headers)
  response=connection.getresponse();code=response.status;payload=response.read();connection.close();return code,payload
 def test_exact_loopback_confirmation_queues_once(self):
  state,candidate,server=self.server();code,payload=self.post(server,json.dumps(candidate))
  self.assertEqual(code,200);self.assertTrue(json.loads(payload)['confirmationRequested'])
  self.assertEqual(state.take_confirmation(),candidate)
  self.assertEqual(self.post(server,json.dumps({**candidate,'venderId':'2'}))[0],200)
  self.assertIsNone(state.take_confirmation())
 def test_loopback_rejects_origin_wrong_task_malformed_and_oversized_body(self):
  state,candidate,server=self.server()
  for body,headers,expected in ((json.dumps(candidate),{'Origin':'https://attacker.example'},403),(json.dumps(candidate),{'X-Heideng-Task':'c'*24},403),('{',{},400),('x'*4097,{},400),(json.dumps(candidate),{'Content-Type':'text/plain'},400)):
   self.assertEqual(self.post(server,body,**headers)[0],expected)
  self.assertIsNone(state.take_confirmation())
 def test_public_candidates_reject_invalid_types_and_sensitive_names(self):
  valid={'shopName':'real-shop','venderId':'1','fingerprint':'b'*64}
  invalid=[{**valid,'shopName':{'token':'private-test-token'}},{**valid,'shopName':'Bearer private-test-token'}, {**valid,'shopName':'x'*129},{**valid,'venderId':True},{**valid,'fingerprint':'invalid'}]
  for candidate in invalid:
   result=public_status({'identityCandidates':[candidate]})
   self.assertEqual(result['identityCandidates'],[])
  self.assertEqual(public_status({'identityCandidates':None})['identityCandidates'],[])

class ConfirmationWorkerTests(unittest.TestCase):
 def test_worker_consumes_confirmation_in_owner_thread_without_new_browser(self):
  import threading
  from heideng_merchant.auth_worker import drive_flow
  with tempfile.TemporaryDirectory() as d:
   flow,client,browser=IdentityConfirmationTests.flow(self,d);broker=BrokerState();caller=threading.get_ident();owner=[]
   original=flow.confirm_shop
   def confirm(*args):owner.append(threading.get_ident());return original(*args)
   flow.confirm_shop=confirm
   def step(_):
    if flow.data['stage']=='waiting_shop_confirmation':
     candidate=broker.status()['identityCandidates'][0]
     thread=threading.Thread(target=lambda:self.assertTrue(broker.confirm_shop(flow.data['taskId'],candidate)))
     thread.start();thread.join(3)
    elif flow.process is not None:broker.cancel()
   drive_flow(flow,broker,flow.registrar,sleep=step)
   self.assertEqual(owner,[caller]);self.assertEqual(len(browser.opened),1)
   self.assertEqual(len([c for c in client.calls if c[0]=='login']),1)


class AuthFeedbackGuideTests(unittest.TestCase):
 def test_agent_guide_exposes_original_task_confirmation_and_diagnostics(self):
  root=Path(__file__).resolve().parents[1]
  skill=(root/'SKILL.md').read_text(encoding='utf-8');guide=(root/'references/shop-connection.md').read_text(encoding='utf-8')
  self.assertIn('auth-confirm-shop',skill)
  for text in ('waiting_shop_confirmation','--fingerprint','identityDiagnostic','同一长命令','不取消重扫'):
   self.assertIn(text,guide)
  self.assertIn('凭据',guide)


class AuthReviewRegressionTests(unittest.TestCase):
 def test_lost_multi_shop_confirmation_never_reenables_automatic_exact_auth(self):
  with tempfile.TemporaryDirectory() as d:
   client=flow_fixture.FakeClient();browser=CandidateBrowser('real-shop')
   browser.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'other-shop','venderId':'2'})
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','real-shop',client,browser)
   flow.tick();flow.tick();candidate=browser.candidates()[0]
   flow.confirm_shop(candidate['fingerprint'],'real-shop','1')
   browser.tracker.discovered.clear();flow.tick()
   browser.tracker.observe_json('https://jingmai.jd.com/identity',{'shopName':'real-shop','venderId':'1'})
   flow.tick()
   self.assertEqual(client.calls,[]);self.assertEqual(flow.data['stage'],'waiting_shop_confirmation')
 def test_unknown_confirmed_alias_with_new_known_id_cannot_start_second_oauth(self):
  from heideng_merchant.auth_manager import AuthManager
  from heideng_merchant.safety import atomic_json
  from tests import test_auth_manager as fixture
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);job='a'*24
   atomic_json(state/'auth/targets.json',{'original-no-id-slot':job})
   atomic_json(state/'tasks'/(job+'.json'),{'kind':'shop-auth','taskId':job,'profile':'merchant-local-a1','shopName':'real-shop','requestedShopName':'alias','venderId':'1','status':'unknown','stage':'auth_outcome_unknown','authorizationStarted':True,'authorizationOutcomeUnknown':True})
   manager=AuthManager(state,client=fixture.Client(),runtime=fixture.Runtime(),starter=lambda *a,**kw:self.fail('second worker launched'))
   with self.assertRaisesRegex(SafetyError,'active-auth-target-conflict'):manager.start('alias',vender_id='1',foreground=True)
 def test_persisted_task_contains_only_public_candidates_not_response_keys(self):
  from heideng_merchant.safety import read_json
  with tempfile.TemporaryDirectory() as d:
   browser=CandidateBrowser();browser.tracker.discovered.clear()
   browser.tracker.observe_json('https://jingmai.jd.com/private-test-path/identity',{'Authorization=Bearer private-test-secret':{'shopName':'real-shop','venderId':'1'}})
   flow=AuthFlow(Path(d),'a'*24,'merchant-local-a1','alias',flow_fixture.FakeClient(),browser)
   flow.tick();flow.tick();value=read_json(flow.path)
   self.assertNotIn('private-test',json.dumps(value))
   self.assertEqual(set(value['identityCandidates'][0]),{'shopName','venderId','fingerprint'})
