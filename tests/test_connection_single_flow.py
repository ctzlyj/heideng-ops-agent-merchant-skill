"""Product-level one-flow tests; no real shop login/OAuth."""
import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch,call
from tests.test_mature_connection import SOURCE,ROOT
class SingleFlowTests(unittest.TestCase):
 def setUp(self):
  self.path=list(sys.path);self.names=('shoplib','redaction','browser_auth','browser_adapters','linker','server')
  self.saved={n:sys.modules.get(n) for n in self.names};sys.path.insert(0,str(SOURCE/'app'));sys.path.insert(0,str(SOURCE/'scripts'))
  for n in self.names:sys.modules.pop(n,None)
 def tearDown(self):
  sys.path[:]=self.path
  for n,v in self.saved.items():
   sys.modules.pop(n,None)
   if v is not None:sys.modules[n]=v
 def load(self,name,file):
  spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
 def test_default_flow_uses_builtin_browser_not_host_agent_polling(self):
  m=self.load('flow_adapters',SOURCE/'app/browser_adapters.py')
  with patch.object(m,'_BUILTIN_FACTORY') as factory:
   browser=m.create_browser({'provider':'builtin','shopIdentity':{'shopName':'fixture','venderId':'123'}})
  factory.assert_called_once_with({'shopName':'fixture','venderId':'123'})

 def test_default_new_auth_selects_builtin_without_changing_explicit_host(self):
  cli=self.load('flow_linker',SOURCE/'scripts/linker.py')
  args=type('Args',(),{'shop':'fixture','profile':None,'no_auth':False,'no_open':False,'no_wait':True,'resume':False,'browser_config':None,'timeout':3})()
  with patch.object(cli,'_env_blockers',return_value=None),patch.object(cli.sl,'resolve',return_value={'status':'needs_auth','shopName':'fixture'}),patch.object(cli.sl,'suggest_profile_name',return_value='fixture-profile'),patch.object(cli.sl,'save_pending'),patch.object(cli,'api',return_value=(200,{'ok':True,'status':'awaiting_auth','profile':'fixture-new','jobId':'fixture','job':{'stage':'waiting_browser','message':'waiting'}})) as api:
   result=cli.cmd_ensure_shop(args)
  self.assertEqual(api.call_args.args[1]['browserConfig']['provider'],'builtin')
  self.assertEqual(api.call_args.args[1]['browserConfig']['shopIdentity']['shopName'],'fixture')

 def test_no_generic_shop_name_is_not_logged_in_identity(self):
  from heideng_merchant.host_connection_controller import _identity
  page=Mock();page.evaluate.return_value='京东-欢迎登录'
  self.assertEqual(_identity(page),{})

 def test_builtin_worker_drives_until_ready_without_external_bridge(self):
  m=self.load('flow_builtin',SOURCE/'app/browser_adapters.py')
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
   from heideng_merchant import host_connection_controller as hc
   controller=Mock();controller.dispatch.side_effect=[{'ok':True,'contextId':'fixture','owned':True,'isolated':True},{'ok':True,'contextId':'fixture','owned':True,'isolated':True,'loggedIn':True,'identity':{'shopName':'fixture','venderId':'123','shopId':'123'}},{'ok':True,'contextId':'fixture','owned':True,'isolated':True}]
   with patch.object(hc,'HostConnectionController',return_value=controller):
    browser=m.create_browser({'provider':'builtin','shopIdentity':{'shopName':'fixture','venderId':'123'}})
    browser.open_login('fixture');observation=browser.observe();browser.close()
   self.assertTrue(observation['loggedIn']);self.assertEqual(controller.dispatch.call_count,3)

 def test_login_page_never_counts_as_logged_in_without_workspace_identity(self):
  from heideng_merchant.host_connection_controller import HostConnectionController
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):controller=HostConnectionController(shop_identity={'shopName':'fixture','venderId':'123'})
  controller.context=Mock();controller.context_id='fixture';controller.profile=Mock();controller.channel='chrome'
  page=Mock();page.url='https://passport.shop.jd.com/login/index.action/jdm';page.evaluate.return_value='店铺: 错误示例'
  controller.page=page
  controller.context.new_page.return_value=Mock(url='https://passport.shop.jd.com/login/index.action')
  with patch.object(controller,'_result',side_effect=lambda value:value),patch('heideng_merchant.host_connection_controller._identity',return_value={}):
   observation=controller._observe()
  self.assertFalse(observation['loggedIn']);self.assertEqual(observation['identity'],{})

 def test_default_browser_channel_is_not_overridden_by_open_login(self):
  from heideng_merchant.host_connection_controller import HostConnectionController
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
   controller=HostConnectionController(shop_identity={'shopName':'fixture'})
   with patch.object(controller,'_default_channel',return_value='msedge'),patch.object(controller,'_launch',side_effect=lambda channel=None:(setattr(controller,'selected_channel',channel or controller._default_channel()),setattr(controller,'page',Mock(url='about:blank')),setattr(controller,'profile',Path(d)/'browser-profiles'/'fixture'))[0]),patch.object(controller,'_save'):
    controller._open_login({})
   self.assertEqual(controller.selected_channel,'msedge')

 def test_builtin_controller_does_not_force_second_oauth_confirmation(self):
  m=self.load('flow_oauth_browser',SOURCE/'app/browser_adapters.py')
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
   controller=Mock();controller.dispatch.return_value={'ok':True,'contextId':'fixture','owned':True,'isolated':True,'loggedIn':True,'identity':{'shopName':'fixture','venderId':'123','shopId':'123'}}
   from heideng_merchant import host_connection_controller as hc
   with patch.object(hc,'HostConnectionController',return_value=controller):
    browser=m.BuiltinBrowser({'shopName':'fixture'});browser.open_oauth('https://passport.jd.com/oauth/login');browser.confirm()
   self.assertEqual(controller.dispatch.call_count,2)
   controller.dispatch.return_value={'ok':True,'contextId':'fixture','owned':True,'isolated':True,'challenge':'confirmation-pending'}
   with self.assertRaisesRegex(Exception,'动作仍在处理'):browser.confirm()


 def test_controller_help_and_contract_do_not_require_merchant_state(self):
  from heideng_merchant import host_connection_controller as controller
  for argv in (['--help'],['--describe-contract']):
   with self.subTest(argv=argv),patch.dict(os.environ,{},clear=True),patch('builtins.print') as output:
    try:result=controller.main(argv)
    except Exception as error:self.fail(f'{argv} 不应依赖商家状态目录：{error}')
    self.assertEqual(result,0);self.assertTrue(output.called)
    if argv==['--describe-contract']:
     contract=json.loads(output.call_args.args[0]);self.assertIn('open_login',contract['actions'])


 def test_workspace_shop_name_selector_is_accepted_as_browser_identity(self):
  from heideng_merchant.host_connection_controller import _identity
  page=Mock();page.evaluate.side_effect=lambda script:'fixture-shop' if '#shop-base-name' in script else None
  self.assertEqual(_identity(page),{'shopName':'fixture-shop'})

 def test_empty_and_generic_identity_nodes_do_not_hide_the_visible_shop(self):
  from heideng_merchant.host_connection_controller import _identity
  page = Mock()
  page.evaluate.return_value = ['', '店铺', 'fixture-shop']
  self.assertEqual(_identity(page), {'shopName': 'fixture-shop'})

 def test_resumed_profile_opens_the_workspace_before_the_login_form(self):
  from heideng_merchant import host_connection_controller as controller
  with tempfile.TemporaryDirectory() as directory:
   host = controller.HostConnectionController(state=directory, shop_identity={'shopName': 'fixture-shop'})
   host.page = Mock(url='about:blank')
   host.page.goto.side_effect = lambda url, **kwargs: setattr(host.page, 'url', url)
   with patch.object(host, '_load', return_value={'contextId': 'owned'}), patch.object(
       host, '_launch'), patch.object(host, '_result', return_value={'ok': True}):
    self.assertTrue(host._open_login({})['ok'])
   host.page.goto.assert_called_once_with(controller.WORKSPACE_URL, wait_until='domcontentloaded', timeout=10000)

 def test_unrecognized_official_consent_form_waits_for_the_merchant(self):
  from heideng_merchant.host_connection_controller import HostConnectionController
  with tempfile.TemporaryDirectory() as directory:
   host = HostConnectionController(state=directory, shop_identity={'shopName': 'fixture-shop'})
   host.page = Mock(url='https://open-oauth.jd.com/oauth2/to_login')
   with patch.object(host, '_launch'), patch.object(host, '_observe', return_value={}), patch.object(
       host, '_result', side_effect=lambda extra=None: {'ok': True, **(extra or {})}):
    self.assertIn('challenge', host._confirm())
   host.page.locator.assert_not_called()
   host.page.get_by_role.assert_not_called()

 def test_confirmed_shop_name_preserves_the_original_owned_browser_identity(self):
  cli = self.load('flow_confirmed_alias', SOURCE/'scripts/linker.py')
  args = type('Args', (), {'shop':'fixture alias', 'profile':None, 'no_auth':False, 'no_open':False,
                          'no_wait':False, 'resume':True, 'browser_config':None, 'timeout':60,
                          'confirmed_shop_name':'fixture official name'})()
  pending = {'query':args.shop, 'shopName':args.shop, 'venderId':'', 'jobId':'previous',
             'processRunning':False, 'outcome':'login_timeout'}
  started = {'ok':True, 'status':'awaiting_auth', 'profile':'fixture-new', 'jobId':'next'}
  with patch.object(cli,'_env_blockers',return_value=None), patch.object(
      cli.sl,'resolve',return_value={'status':'needs_auth','shopName':args.shop,'suggestedProfile':'fixture-profile'}), patch.object(
      cli.sl,'load_pending',return_value=pending), patch.object(cli.sl,'save_pending') as save, patch.object(
      cli,'ensure_embedded_server'), patch.object(cli,'wait_job',return_value={'status':'awaiting_auth'}), patch.object(
      cli,'api',return_value=(200,started)) as api:
   cli._cmd_ensure_shop(args, wait_timeout=60)
   payload = api.call_args.args[1]
   self.assertEqual(payload['shopName'], args.confirmed_shop_name)
   self.assertEqual(payload['browserConfig']['shopIdentity']['shopName'], args.shop)
   self.assertEqual(save.call_args.args[0]['confirmedShopName'], args.confirmed_shop_name)
   pending['outcome'] = 'callback_unknown'
   api.reset_mock()
   result = cli._cmd_ensure_shop(args, wait_timeout=60)
   self.assertEqual(result['status'], 'blocked')
   api.assert_not_called()

 def test_confirmed_name_requires_exact_match_in_browser_and_cli(self):
  browser_auth = self.load('flow_exact_browser_name', SOURCE/'app/browser_auth.py')
  name = 'fixture official'
  job = browser_auth.BrowserAuthJob('fixture-profile', name, browser=Mock(),
                                   browser_config={'provider':'builtin','confirmedShopName':name})
  self.assertTrue(job._browser_matches({'shopName':name}))
  self.assertFalse(job._browser_matches({'shopName':name+' other'}))
  self.assertTrue(job._matches({'shopName':name,'venderId':'123'}))
  self.assertFalse(job._matches({'shopName':name+' other','venderId':'123'}))

 def test_closed_name_mismatch_can_resume_the_original_browser(self):
  cli = self.load('flow_closed_name_mismatch', SOURCE/'scripts/linker.py')
  args = type('Args', (), {'no_wait':False,'no_open':False,'browser_config':None,'timeout':60})()
  pending = {'jobId':'original','query':'fixture alias'}
  snapshot = {'id':'original','status':'mismatch','stage':'mismatch','errorKind':'mismatch','cleanupComplete':True}
  with patch.object(cli, '_cmd_ensure_shop', return_value={'ok':False,'status':'mismatch'}), patch.object(
      cli, 'close_embedded_server', return_value=snapshot), patch.object(cli.sl,'load_pending',return_value=pending), patch.object(
      cli.sl, 'save_pending') as save:
   result = cli.cmd_ensure_shop(args)
  self.assertEqual(result['status'], 'mismatch')
  save.assert_called_once_with({**pending,'stage':'mismatch','outcome':'mismatch','processRunning':False})

 def test_name_only_workspace_identity_can_reach_official_oauth(self):
  import threading
  m=self.load('flow_name_only_auth',SOURCE/'app/browser_auth.py')
  browser=Mock();browser.observe.return_value={'loggedIn':True,'identity':{'shopName':'fixture-shop'},'challenge':''};browser.confirm.return_value={}
  login=Mock();login.status='success';login.error_kind='';login.url='https://passport.jd.com/oauth/fixture';login._done=threading.Event();login._done.set()
  with patch.object(m.sl,'mark_auth_pending'):
   job=m.BrowserAuthJob('fixture-profile','fixture-shop',browser=browser,login_factory=Mock(return_value=login))
   with patch.object(job,'_verify_and_commit'):
    job.run()
  job.login_factory.assert_called_once()
  self.assertEqual(job.shop_name,'fixture-shop');self.assertEqual(job.expect_vender_id,'')
  browser.open_oauth.assert_called_once_with('https://passport.jd.com/oauth/fixture')

 def test_official_profile_verification_still_requires_complete_identity(self):
  m=self.load('flow_official_identity_auth',SOURCE/'app/browser_auth.py')
  job=m.BrowserAuthJob('fixture-profile','fixture-shop',browser=Mock())
  self.assertFalse(job._matches({'shopName':'fixture-shop'}))
  self.assertFalse(job._matches({'shopName':'other-shop','venderId':'123'}))
  self.assertTrue(job._matches({'shopName':'fixture-shop','venderId':'123'}))

 def test_low_level_connect_uses_explicit_shop_arguments(self):
  cli=self.load('flow_low_level_connect',SOURCE/'scripts/linker.py')
  args=type('Args',(),{'shop':'fixture-shop','profile':'fixture-profile','vender_id':'123','no_open':False})()
  with patch.object(cli,'api',return_value=(200,{'ok':True,'jobId':'job-fixture','profile':'fixture-profile-task'})) as api,patch.object(cli.sl,'save_pending'):
   try:cli.cmd_connect(args)
   except NameError as error:self.fail(f'底层连接不应引用未定义变量：{error}')
  payload=api.call_args.args[1]['browserConfig']['shopIdentity']
  self.assertEqual(payload,{'shopName':'fixture-shop','venderId':'123'})

 def test_missing_live_job_is_lost_not_still_waiting(self):
  cli=self.load('flow_missing_job',SOURCE/'scripts/linker.py')
  with patch.object(cli,'api',return_value=(200,{'ok':True,'job':None})):
   result=cli.wait_job(0,0,job_id='fixture-job')
  self.assertFalse(result['ok']);self.assertEqual(result['status'],'job_lost');self.assertIn('恢复',result['error'])

 def test_polling_a_closed_job_does_not_start_a_connector(self):
  cli = self.load('flow_idle_job', SOURCE/'scripts/linker.py')
  with patch.object(cli, 'server_info', return_value=None), patch.object(cli, 'ensure_server') as start:
   result = cli.cmd_job(None)
  self.assertEqual(result['status'], 'job_lost')
  start.assert_not_called()

 def test_no_wait_result_exposes_actual_browser_channel(self):
  cli=self.load('flow_channel_receipt',SOURCE/'scripts/linker.py')
  args=type('Args',(),{'shop':'fixture','profile':None,'no_auth':False,'no_open':False,'no_wait':True,'resume':False,'fresh':False,'browser_config':None,'timeout':3})()
  started={'ok':True,'status':'awaiting_auth','profile':'fixture-new','jobId':'fixture','job':{'stage':'waiting_login','message':'waiting','browserChannel':'msedge','browserSelectionReason':'system-default-https'}}
  with patch.object(cli,'_env_blockers',return_value=None),patch.object(cli.sl,'resolve',return_value={'status':'needs_auth','shopName':'fixture'}),patch.object(cli.sl,'suggest_profile_name',return_value='fixture-profile'),patch.object(cli.sl,'save_pending'),patch.object(cli,'api',return_value=(200,started)):
   result=cli.cmd_ensure_shop(args)
  self.assertEqual(result.get('browserChannel'),'msedge');self.assertEqual(result.get('browserSelectionReason'),'system-default-https')

if __name__=='__main__':unittest.main()
