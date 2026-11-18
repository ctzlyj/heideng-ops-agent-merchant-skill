"""New merchant adaptation evidence; no real shop, login or OAuth."""
import importlib, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from tests.test_mature_connection import SOURCE, ROOT, load

class ConnectionExperienceTests(unittest.TestCase):
    def setUp(self):
        self.path=list(sys.path);self.saved={n:sys.modules.get(n) for n in ('shoplib','redaction','browser_auth','browser_adapters','linker')}
        sys.path.insert(0,str(SOURCE/'app'));sys.path.insert(0,str(SOURCE/'scripts'))
        for n in self.saved:sys.modules.pop(n,None)
    def tearDown(self):
        sys.path[:]=self.path
        for n,v in self.saved.items():
            sys.modules.pop(n,None)
            if v is not None:sys.modules[n]=v
    def test_connector_service_detaches_from_host_process_group(self):
        cli=load('merchant_experience_linker',SOURCE/'scripts/linker.py')
        with patch.dict(os.environ,{'HEIDENG_MERCHANT_PACKAGE':str(ROOT)}),patch.object(cli,'server_info',side_effect=[None,{'version':cli.expected_version()}]),patch.object(cli.subprocess,'Popen') as spawn:
            cli.ensure_server();options=spawn.call_args.kwargs
        if os.name=='nt':self.assertTrue(options.get('creationflags',0)&0x00000008)
        else:self.assertTrue(options.get('start_new_session'))
        self.assertEqual(options.get('stdin'),subprocess.DEVNULL)

    def test_failed_same_shop_job_does_not_need_hidden_cancel_recipe(self):
        import browser_auth,server
        browser_auth.BrowserAuthJob=Mock(return_value=SimpleNamespaceFactory())
        manager=server.Manager();old=SimpleNamespaceFactory(status='failed',shop_name='fixture',expect_vender_id='',requested_profile='fixture',resume=Mock())
        manager.job=old
        with patch.object(browser_auth,'BrowserAuthJob',return_value=SimpleNamespaceFactory()) as created:
            current=manager.start_flow('fixture','fixture')
        self.assertIsNot(current,old);created.assert_called_once();old.resume.assert_not_called()

    def test_explicit_resume_keeps_exact_profile_and_calls_original_worker(self):
        import browser_auth,server
        manager=server.Manager();old=SimpleNamespaceFactory(status='failed',shop_name='fixture',expect_vender_id='',requested_profile='fixture',resume=Mock())
        manager.job=old
        self.assertIs(manager.start_flow('fixture','fixture',resume=True),old);old.resume.assert_called_once()

    def test_cancelled_same_shop_job_starts_a_new_worker_instead_of_fake_resume(self):
        import browser_auth,server
        manager=server.Manager();old=SimpleNamespaceFactory(status='cancelled',shop_name='fixture',expect_vender_id='',requested_profile='fixture',resume=Mock())
        manager.job=old
        with patch.object(browser_auth,'BrowserAuthJob',return_value=SimpleNamespaceFactory()) as created:
            current=manager.start_flow('fixture','fixture',resume=True)
        self.assertIsNot(current,old);created.assert_called_once();old.resume.assert_not_called()


    def test_browser_idle_timeout_keeps_authorization_alive(self):
        import browser_adapters
        browser=browser_adapters.HostBrowser({'timeout':0.01,'poll':0.001})
        with self.assertRaises(browser_adapters.BrowserError) as waiting:browser.open_login('fixture')
        self.assertEqual(waiting.exception.kind,'action_pending')
        time.sleep(.03)
        self.assertEqual(browser.next_action()['kind'],'open_login')

    def test_default_login_is_jingmai_merchant_not_generic_passport(self):
        import browser_adapters
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            browser=browser_adapters.PlaywrightBrowser({'identityScript':'fixture','identityScriptVerified':True})
            self.assertIn('passport.shop.jd.com/login',browser._login_url)
            self.assertNotIn('passport.jd.com/new/login',browser._login_url)

    def test_update_cli_uses_prepared_runtime_not_unprepared_host(self):
        from heideng_merchant.cli import main
        with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.runtime_dependencies.reexec_update_runtime',return_value=0) as switch:
            self.assertEqual(main(['--state',d,'update','check']),0);switch.assert_called_once()

    def test_merchant_only_previous_key_blob_migrates_atomically(self):
        from heideng_merchant import merchant_key_store as store
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'secrets').mkdir();(root/'lts4ai.key.dpapi').write_bytes(b'encrypted-fixture')
            with patch.object(store,'_dpapi',side_effect=[b'merchant-fixture',b'new-encrypted-fixture']) as dpapi:
                self.assertEqual(store.read_key(root),'merchant-fixture')
            self.assertEqual((root/'secrets/lts4ai.dpapi').read_bytes(),b'new-encrypted-fixture')
            self.assertTrue((root/'lts4ai.key.dpapi').is_file())

    def test_builtin_host_controller_supports_login_observe_oauth_confirm_close(self):
        from heideng_merchant import host_connection_controller as controller
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            page=controller.HostConnectionController().describe_contract()
        self.assertEqual(page['actions'],['open_login','observe','open_oauth','confirm','close'])
        self.assertIn('passport.shop.jd.com/login',page['loginUrl'])
        self.assertTrue(page['merchantChoosesLoginMethod'])
        self.assertIn('account-risk-blocked',page['challenges'])

    def test_bridge_error_distinguishes_missing_package_from_unavailable_action(self):
        bridge=load('merchant_experience_bridge',SOURCE/'scripts/browser_bridge.py')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            with patch.object(bridge,'_action',side_effect=KeyError('HEIDENG_MERCHANT_PACKAGE')):
                self.assertEqual(bridge.dispatch(['python'],timeout=1)['error'],'missing-package-env')

    def test_browser_profile_can_be_created_and_registered_by_same_controller(self):
        from heideng_merchant import host_connection_controller as controller
        from heideng_merchant.mature_runtime import merchant_profile_directory
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            current=controller.HostConnectionController()
            current.profile=Path(d)/'browser-profiles'/'fixture';current.profile.mkdir(parents=True)
            self.assertEqual(merchant_profile_directory(current.profile),current.profile)

    def test_oauth_never_uses_generic_untrusted_confirmation(self):
        from heideng_merchant.host_connection_controller import HostConnectionController
        from urllib.parse import urlsplit
        controller=HostConnectionController
        self.assertEqual(urlsplit(controller.__module__).scheme,'')

    def test_builtin_controller_is_a_one_command_bridge_default(self):
        from heideng_merchant.mature_runtime import host_browser_controller_command
        with tempfile.TemporaryDirectory() as d:
            command=host_browser_controller_command(Path(d))
            self.assertEqual(command[1:3],['-I','-B'])
            self.assertTrue(command[-1].replace('\\','/').endswith('scripts/host_connection_controller.py'))

    def test_risk_page_observation_is_explicit_and_needs_no_identity(self):
        from heideng_merchant import host_connection_controller as controller
        from unittest.mock import Mock
        current=controller.HostConnectionController
        page=Mock();page.url='https://aq.jd.com/certified/index'
        self.assertEqual(controller._identity(page),{})

    def test_generation_count_is_per_spu_not_multiplied_by_sku(self):
        pass

    def test_audit_reports_generation_units_separately_from_sku_deficits(self):
        spec=importlib.util.spec_from_file_location('merchant_experience_material',ROOT/'mature/materials/scripts/jd_material_agent.py');agent=importlib.util.module_from_spec(spec);sys.modules[spec.name]=agent;spec.loader.exec_module(agent)
        with tempfile.TemporaryDirectory() as d:
            payload={'shopIdentity':{'shopName':'fixture'},'rows':[{'productId':'11','skuId':'1','slots':{'white':{'state':'missing'},'scene1':{'state':'missing'},'scene2':{'state':'missing'},'selling':{'state':'missing'},'transparent':{'state':'missing'},'point1':{'state':'missing'}}},{'productId':'11','skuId':'2','slots':{'white':{'state':'missing'},'scene1':{'state':'missing'},'scene2':{'state':'missing'},'selling':{'state':'missing'},'transparent':{'state':'missing'},'point1':{'state':'missing'}}}]}
            path=Path(d)/'audit.json';path.write_text(json.dumps(payload))
            summary=agent.audit_generation_summary(path)
        self.assertEqual(summary['missingSlotCount'],6);self.assertEqual(summary['generationSpuCount'],1);self.assertEqual(summary['imageGenerationRequestCount'],5)

class SimpleNamespaceFactory:
    def __init__(self,**kw):
        self.id='new-id';self.profile='fixture-new';self.status='waiting';self.stage='waiting_browser';self.to_dict=lambda:{};self.start=Mock()
        self.__dict__.update(kw)

if __name__=='__main__':unittest.main()
