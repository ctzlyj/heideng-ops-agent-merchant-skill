import io,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_flow import BrowserIdentityProof,AuthFlow
from heideng_merchant.safety import SafetyError

class FakeBrowser:
 def __init__(self,proof=None):self.proof_value=proof;self.opened=[];self.navigated=[];self.closed=False;self.context='one-context'
 def open_jingmai(self):self.opened.append(self.context)
 def proof(self):return self.proof_value
 def poll(self):pass
 def navigate_oauth(self,url):self.navigated.append((self.context,url))
 def close(self):self.closed=True
 def public_observation(self):return {'page':'jingmai-login','text':'请扫码'}

class FakeProcess:
 def __init__(self):
  self.pid=123;self.returncode=None;self.terminated=False
  self.stderr=io.BytesIO(b'Open this URL to authorize jdo-cli:\nhttps://open-oauth.jd.com/oauth2/to_login?state=fake-private-state\n')
  self.stdout=io.BytesIO(json.dumps({'command':'login','ok':True,'profile':'merchant-local-a1','cliVersion':'0.3.7','timestamp':1,'loginCompleted':True,'tokenMocked':False,'authorizationStatus':'logged_in','authorizationStage':'credential_saved','tokenStored':True,'appKeyConfigured':True,'appSecretStored':True,'access_token':'fake-private-token'}).encode())
 def poll(self):return self.returncode
 def terminate(self):self.terminated=True;self.returncode=-1
 def wait(self,timeout=None):return self.returncode

class FakeClient:
 def __init__(self):self.calls=[];self.wrong=False;self.mock=False
 def initialize(self,profile,**kwargs):self.calls.append(('init',profile,kwargs));return {'ok':True}
 def login_process(self,profile,shop_name,vender_id):
  self.calls.append(('login',profile,shop_name,vender_id));self.process=FakeProcess();receipt=json.loads(self.process.stdout.getvalue());receipt['profile']=profile;self.process.stdout=io.BytesIO(json.dumps(receipt).encode())
  if self.mock:self.process.stdout=io.BytesIO(b'{"ok":true,"loginCompleted":true,"mock":true}')
  return self.process
 def callback_owned(self,process):return True
 def identity(self,profile):return {'venderId':'2' if self.wrong else '1','shopId':'9','shopName':'测试店','shopType':'POP'}

class AuthFlowTests(unittest.TestCase):
 def test_response_proof_is_exact_and_private_values_not_exported(self):
  tracker=BrowserIdentityProof('测试店')
  tracker.observe_json('https://jingmai.jd.com/api/identity?token=fake-private-token',{'data':{'shopName':'测试店','venderId':'1','shopId':'9','token':'fake-private-token'}})
  proof=tracker.proof();self.assertEqual(proof['venderId'],'1');self.assertNotIn('fake-private-token',json.dumps(proof));self.assertNotIn('?',proof['source'])
 def test_wrong_source_and_shop_id_not_vender_id(self):
  tracker=BrowserIdentityProof('测试店','1')
  tracker.observe_json('https://ge.jd.com/api/identity',{'shopName':'测试店','venderId':'1'})
  tracker.observe_json('https://jingmai.jd.com/api/identity',{'shopName':'测试店','shopId':'1'})
  self.assertIsNone(tracker.proof())
 def test_mismatched_shop_not_selected(self):
  tracker=BrowserIdentityProof('测试店','1');tracker.observe_json('https://jingmai.jd.com/api/identity',{'shopName':'其他店','venderId':'2'});self.assertIsNone(tracker.proof())
 def make_flow(self,root,proof=None):
  client=FakeClient();browser=FakeBrowser(proof);flow=AuthFlow(Path(root),'a'*24,'merchant-local-a1','测试店',client,browser,expected_vender_id='1');return flow,client,browser
 def test_no_oauth_until_browser_identity_matches(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d);flow.tick();flow.tick();self.assertEqual(c.calls,[]);self.assertEqual(len(b.opened),1);self.assertEqual(flow.status()['stage'],'waiting_login')
 def test_same_context_and_single_oauth_launch_no_private_output(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   for _ in range(10):flow.tick()
   self.assertEqual(sum(x[0]=='login' for x in c.calls),1);self.assertEqual(len(b.navigated),1);self.assertEqual(b.navigated[0][0],b.opened[0]);self.assertNotIn('fake-private-state',json.dumps(flow.status()));self.assertNotIn('fake-private-state',(Path(d)/'tasks'/('a'*24+'.json')).read_text(encoding='utf-8'))
 def test_cli_completion_alone_is_not_ready(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   for _ in range(5):flow.tick()
   c.wrong=True;c.process.returncode=0;flow.tick();self.assertEqual(flow.status()['stage'],'identity_mismatch');self.assertFalse(flow.status()['ready'])
 def test_success_is_realtime_identity_and_no_token_export(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   for _ in range(5):flow.tick()
   c.process.returncode=0;flow.tick();self.assertEqual(flow.status()['stage'],'ready');self.assertTrue(b.closed);self.assertNotIn('fake-private-token',json.dumps(flow.status()))
 def test_mock_token_result_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   c.mock=True
   for _ in range(5):flow.tick()
   c.process.returncode=0;flow.tick();self.assertFalse(flow.status()['ready'])
 def test_cancel_owns_only_its_process_and_browser(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   for _ in range(5):flow.tick()
   flow.cancel();self.assertTrue(c.process.terminated);self.assertTrue(b.closed);self.assertEqual(flow.status()['stage'],'cancelled')

if __name__=='__main__':unittest.main()

class AuthFailureTests(unittest.TestCase):
 make_flow=AuthFlowTests.make_flow
 def test_incomplete_cli_result_stays_unknown_without_relogin(self):
  for raw in (b'', b'not json', b'[]', b'{"ok":true}'):
   with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
    flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
    original=c.login_process
    def login(*args):
     process=original(*args);process.stdout=io.BytesIO(raw);return process
    c.login_process=login
    flow.tick();flow.tick();c.process.returncode=0;flow.tick();flow.tick()
    self.assertEqual(flow.status()['status'],'unknown');self.assertFalse(flow.status()['ready']);self.assertEqual(len(c.calls),2)
 def test_browser_failure_terminates_only_held_cli_and_stays_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=self.make_flow(d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   flow.tick();flow.tick()
   def failed():raise RuntimeError('private-state-never-published')
   b.poll=failed;flow.tick()
   self.assertTrue(c.process.terminated);self.assertEqual(flow.status()['status'],'unknown');self.assertTrue(b.closed)

class OAuthInputTests(unittest.TestCase):
 def test_official_urls_reject_alternate_ports_control_chars_and_large_private_payloads(self):
  from heideng_merchant.auth_flow import valid_oauth_url,eligible_identity_source
  for url in ['https://open-oauth.jd.com:444/oauth2/to_login','https://open-oauth.jd.com/oauth2/to_login\n','https://open-oauth.jd.com/oauth2/to_login?state='+('x'*20000),None]:
   self.assertFalse(valid_oauth_url(url))
  self.assertFalse(eligible_identity_source('https://jingmai.jd.com:444/identity'))
 def test_failed_oauth_spawn_is_unknown_not_retryable_failure(self):
  with tempfile.TemporaryDirectory() as d:
   flow,c,b=AuthFlowTests.make_flow(self,d,{'shopName':'测试店','venderId':'1','source':'https://jingmai.jd.com/api/identity'})
   def ambiguous(*args):raise OSError('private-error')
   c.login_process=ambiguous;flow.tick();r=flow.tick();self.assertEqual(r['status'],'unknown');self.assertTrue(r['authorizationStarted']);self.assertNotIn('private-error',json.dumps(r))
