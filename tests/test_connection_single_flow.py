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

if __name__=='__main__':unittest.main()
