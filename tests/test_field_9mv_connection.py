"""Real-field connection shapes; no merchant, credentials, browser network or OAuth."""
import unittest,tempfile,os,json,threading
from pathlib import Path
from unittest.mock import Mock,patch
import tests.test_audit_connection_contracts as helpers
from heideng_merchant.host_connection_controller import HostConnectionController,_identity

class ObservationTests(unittest.TestCase):
    def test_menu_customer_service_is_not_shop_identity(self):
        page=Mock();page.evaluate.side_effect=[None,'客服']
        self.assertEqual(_identity(page),{})
    def test_workspace_tab_in_same_context_is_observed_without_refreshing_login(self):
        with tempfile.TemporaryDirectory() as d:controller=HostConnectionController(state=d,shop_identity={'shopName':'fixture'})
        login=Mock(url='https://passport.shop.jd.com/login/index.action');work=Mock(url='https://shop.jd.com/jdm/home')
        controller.page=login;controller.context=Mock(pages=[login,work]);login.is_closed.return_value=False;work.is_closed.return_value=False
        with patch('heideng_merchant.host_connection_controller._identity',side_effect=lambda p:{'shopName':'fixture'} if p is work else {}),patch.object(controller,'_result',side_effect=lambda x:x):result=controller._observe()
        self.assertTrue(result['loggedIn']);self.assertIs(controller.page,work);login.reload.assert_not_called()
    def test_persistent_login_page_can_probe_workspace_without_reading_cookies(self):
        with tempfile.TemporaryDirectory() as d:controller=HostConnectionController(state=d,shop_identity={'shopName':'fixture'})
        login=Mock(url='https://passport.shop.jd.com/login/index.action');work=Mock(url='about:blank')
        work.goto.side_effect=lambda *_a,**_k:setattr(work,'url','https://shop.jd.com/jdm/home')
        login.is_closed.return_value=False;work.is_closed.return_value=False
        controller.page=login;controller.context=Mock(pages=[login]);controller.context.new_page.return_value=work
        with patch('heideng_merchant.host_connection_controller._identity',side_effect=lambda p:{'shopName':'fixture'} if p is work else {}),patch.object(controller,'_result',side_effect=lambda x:x):result=controller._observe()
        self.assertTrue(result['loggedIn']);controller.context.cookies.assert_not_called()
        work.goto.assert_called_once();login.reload.assert_not_called()

    def test_optional_workspace_probe_timeout_keeps_original_login_pending(self):
        with tempfile.TemporaryDirectory() as d:controller=HostConnectionController(state=d,shop_identity={'shopName':'fixture'})
        login=Mock(url='https://passport.shop.jd.com/login/index.action');work=Mock(url='about:blank')
        login.is_closed.return_value=False;work.is_closed.return_value=False;work.goto.side_effect=TimeoutError('synthetic probe timeout')
        controller.page=login;controller.context=Mock(pages=[login]);controller.context.new_page.return_value=work
        with patch.object(controller,'_result',side_effect=lambda x:x):
            result=controller._observe();again=controller._observe()
        self.assertFalse(result['loggedIn']);self.assertFalse(again['loggedIn']);self.assertIs(controller.page,login)
        controller.context.new_page.assert_called_once();work.goto.assert_called_once();login.reload.assert_not_called()

class LateProofTests(unittest.TestCase):
    setUp=helpers.AuditConnectionTests.setUp
    tearDown=helpers.AuditConnectionTests.tearDown
    def test_named_login_binds_late_verified_vender_slot_without_copy_when_account_matches(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            profile=Path(d)/'profiles/fixture-profile.json';profile.parent.mkdir();profile.write_text('{}')
            server.sl.mark_auth_pending(job.profile,job.id,'','fixture-shop')
            identity={'shopName':'fixture-shop','venderId':'123','shopId':'123'}
            data={'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:sp-api:token:fixture-profile:123','tokenMocked':False,'tokenStored':True,'loginCompleted':True}
            with patch.object(server.sl,'verify_profile',return_value=identity),patch.object(server,'copy_credential') as copy:
                job._apply_identity(identity,data)
            server.sl.require_auth_slot(job.profile,required=True);copy.assert_not_called()
    def test_default_slot_migration_uses_only_exact_task_profile_and_verified_identity(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            profile=Path(d)/'profiles/fixture-profile.json';profile.parent.mkdir();profile.write_text('{}');server.sl.mark_auth_pending(job.profile,job.id,'','fixture-shop')
            identity={'shopName':'fixture-shop','venderId':'123','shopId':'123'}
            data={'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:sp-api:token:fixture-profile:default','tokenMocked':False,'tokenStored':True,'loginCompleted':True}
            with patch.object(server.sl,'verify_profile',return_value=identity),patch.object(server,'copy_credential',return_value=True) as copy:
                try:job._apply_identity(identity,data)
                except Exception as e:self.fail(f'本任务默认槽应在官方核店后安全定位：{e}')
            self.assertEqual(copy.call_args.args[:2],('jdo-cli:sp-api:token:fixture-profile:default','jdo-cli:sp-api:token:fixture-profile:123'))
            server.sl.require_auth_slot(job.profile,required=True)
    def test_connected_worker_cleanup_failure_does_not_erase_verified_ready(self):
        snapshot={'status':'success','profile':'fixture','id':'one','identity':{'shopName':'fixture','venderId':'123'}}
        worker=Mock();worker.is_alive.return_value=False
        job=Mock(status='success',_worker_thread=worker);job.shutdown.return_value=False;job.to_dict.return_value=snapshot
        httpd=Mock();httpd.RequestHandlerClass.manager.current.return_value=job
        service_thread=Mock()
        self.cli._EMBEDDED_HTTPD=httpd;self.cli._EMBEDDED_THREAD=service_thread
        try:result=self.cli.close_embedded_server()
        except Exception as e:self.fail(f'已核店应保留ready并单独报告资源收尾：{e}')
        self.assertEqual(result['status'],'success');self.assertFalse(result['cleanupComplete'])
        service_thread.join.assert_called_once_with(timeout=5);worker.join.assert_not_called()

    def test_cleanup_failure_never_stops_service_if_worker_liveness_is_unknown_or_alive(self):
        worker=Mock();worker.is_alive.return_value=True
        for value in (None,worker):
            with self.subTest(worker=value):
                job=Mock(status='success',_worker_thread=value);job.shutdown.return_value=False;job.to_dict.return_value={'status':'success'}
                httpd=Mock();httpd.RequestHandlerClass.manager.current.return_value=job
                self.cli._EMBEDDED_HTTPD=httpd;self.cli._EMBEDDED_THREAD=Mock()
                with self.assertRaises(RuntimeError):self.cli.close_embedded_server()
                httpd.shutdown.assert_not_called()
                self.cli._EMBEDDED_HTTPD=self.cli._EMBEDDED_THREAD=None

    def test_owned_official_status_attests_missing_login_metadata_without_relaxing_identity(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            account='jdo-cli:sp-api:token:fixture-profile:default'
            login={'ok':True,'profile':job.profile,'tokenCredentialAccount':account}
            status={'ok':True,'profile':job.profile,'home':d,'tokenCredentialAccount':account,'oauthTokenStored':True,'oauthTokenMocked':False}
            with patch.object(server.sl,'run_jdo',return_value=(0,json.dumps(status))) as run:
                self.assertTrue(job._owned_login_receipt(login))
                run.assert_called_once_with(['status'],timeout=15)
            for changed in ({'profile':'other-profile'},{'home':str(Path(d)/'other')},{'tokenMocked':True}):
                with self.subTest(changed=changed),patch.object(server.sl,'run_jdo') as run:
                    self.assertFalse(job._owned_login_receipt({**login,**changed}));run.assert_not_called()
            with patch.object(server.sl,'run_jdo',return_value=(0,json.dumps({**status,'oauthTokenMocked':True}))):
                self.assertFalse(job._owned_login_receipt(login))

    def test_jdo_037_status_only_attests_its_exact_default_profile(self):
        import server
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'JDO_HOME': d}, clear=True):
            job = server.LoginJob('fixture-profile', 'fixture-shop', defer_registry=True)
            account = 'jdo-cli:sp-api:token:fixture-profile:default'
            login = {'ok': True, 'profile': job.profile, 'tokenCredentialAccount': account}
            status = {'ok': True, 'home': d, 'defaultProfile': job.profile,
                      'profile': {'path': str(Path(d) / 'profiles' / f'{job.profile}.json'), 'exists': True},
                      'credentialInputs': {'oauthTokenStored': True, 'oauthTokenMocked': False},
                      'credentialStore': {'tokenCredentialAccount': account}}
            with patch.object(server.sl, 'run_jdo', return_value=(0, json.dumps(status))) as run:
                self.assertTrue(job._owned_login_receipt(login))
                run.assert_called_once_with(['status'], timeout=15)
            for changed in ({'defaultProfile': 'other-profile'},
                            {'profile': {**status['profile'], 'path': str(Path(d) / 'profiles/other-profile.json')}},
                            {'credentialInputs': {'oauthTokenStored': True, 'oauthTokenMocked': True}}):
                with self.subTest(changed=changed), patch.object(
                        server.sl, 'run_jdo', return_value=(0, json.dumps({**status, **changed}))):
                    self.assertFalse(job._owned_login_receipt(login))

    def test_completed_native_default_slot_recovers_after_first_identity_read_was_offline(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            path=Path(d)/'profiles/fixture-profile.json';path.parent.mkdir();path.write_text('{}')
            server.sl.mark_auth_pending(job.profile,job.id,'','fixture-shop')
            server.sl.mark_auth_native_completed(job.profile,job.id,'synthetic-native-job')
            status={'ok':True,'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:sp-api:token:fixture-profile:default','oauthTokenStored':True,'oauthTokenMocked':False}
            identity={'shopName':'fixture-shop','venderId':'123'}
            with patch.object(server.sl,'run_jdo',return_value=(0,json.dumps(status))),patch.object(server.sl,'verify_profile',return_value=identity),patch.object(server,'copy_credential',return_value=True) as copy,patch.object(server.LoginJob,'start') as start:
                self.assertTrue(server.recover_owned_auth_slot(job.profile,job.id))
                start.assert_not_called();copy.assert_called_once()
            server.sl.require_auth_slot(job.profile,required=True)
            self.assertEqual(server.sl._proof_data()['profiles'][job.profile]['jobId'],job.id)
            self.assertEqual(json.loads(path.read_text())['vender_id'],'123')

    def test_unknown_native_outcome_or_other_pending_job_never_recovers_default_slot(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            server.sl.mark_auth_pending('fixture-profile','original-job','','fixture-shop')
            with patch.object(server.sl,'run_jdo') as run,patch.object(server,'copy_credential') as copy:
                self.assertFalse(server.recover_owned_auth_slot('fixture-profile','original-job'))
                server.sl.mark_auth_native_completed('fixture-profile','original-job','synthetic-native-job')
                self.assertFalse(server.recover_owned_auth_slot('fixture-profile','other-job'))
                run.assert_not_called();copy.assert_not_called()

    def test_original_native_slot_recovers_when_cli_status_cannot_select_profile(self):
        import server
        with tempfile.TemporaryDirectory() as d, patch.dict(
                os.environ, {'JDO_HOME': d, 'JINGMAI_LINKER_HOME': str(Path(d) / 'linker')}, clear=True):
            job = server.LoginJob('fixture-profile', 'fixture-shop', defer_registry=True)
            path = Path(d) / 'profiles/fixture-profile.json'
            path.parent.mkdir()
            path.write_text('{}')
            server.sl.mark_auth_pending(job.profile, job.id, '', job.shop_name)
            server.sl.mark_auth_native_completed(
                job.profile, job.id, 'synthetic-native-job', default_slot_namespace='jdo-cli:sp-api:token')
            identity = {'shopName': job.shop_name, 'venderId': '123'}
            with patch.object(server.sl, 'run_jdo') as status, patch.object(
                    server.sl, 'verify_profile', return_value=identity), patch.object(
                    server, 'copy_credential', return_value=True) as copy, patch.object(
                    server.LoginJob, 'start') as start:
                self.assertTrue(server.recover_owned_auth_slot(job.profile, job.id))
                status.assert_not_called()
                start.assert_not_called()
                copy.assert_called_once_with(
                    'jdo-cli:sp-api:token:fixture-profile:default',
                    'jdo-cli:sp-api:token:fixture-profile:123', delete_old=False)
            server.sl.require_auth_slot(job.profile, required=True)

    def test_native_completion_is_preserved_before_first_network_identity_failure(self):
        import server
        for slot in ('123','default'):
            with self.subTest(slot=slot),tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
                job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True);job.proof_job_id='original-browser-job'
                server.sl.mark_auth_pending(job.profile,job.proof_job_id,'','fixture-shop')
                job.proc=Mock();job.proc.wait.return_value=0;job.proc.poll.return_value=0
                job._raw_output=[json.dumps({'ok':True,'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:sp-api:token:fixture-profile:'+slot,'loginCompleted':True,'tokenStored':True,'tokenMocked':False})]
                with patch.object(job,'_restore_default'),patch.object(server.sl,'verify_profile',side_effect=server.sl.VerifyError('network','synthetic offline identity read')):job._monitor()
                proof=server.sl._proof_data()['profiles'][job.profile]
                self.assertTrue(proof['nativeCompleted']);self.assertEqual(proof['jobId'],'original-browser-job')
                self.assertEqual(proof['nativeJobId'],job.id);self.assertEqual(proof['slotVerified'],slot.isdigit())
                self.assertNotEqual(job.status,'success')

    def test_slot_location_proof_survives_readonly_network_failure_after_owned_migration(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            path=Path(d)/'profiles/fixture-profile.json';path.parent.mkdir();path.write_text('{}');server.sl.mark_auth_pending(job.profile,job.id,'','fixture-shop')
            identity={'shopName':'fixture-shop','venderId':'123'}
            data={'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:token:fixture-profile:default','tokenMocked':False,'tokenStored':True,'loginCompleted':True}
            with patch.object(server,'copy_credential',return_value=True),patch.object(server.sl,'verify_profile',side_effect=server.sl.VerifyError('network','synthetic offline read')):
                with self.assertRaises(server.sl.VerifyError):job._apply_identity(identity,data)
            server.sl.require_auth_slot(job.profile,required=True)
            self.assertEqual(json.loads(path.read_text())['vender_id'],'123')

    def test_other_profile_or_mocked_native_receipt_never_copies_credentials(self):
        import server
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JDO_HOME':d,'JINGMAI_LINKER_HOME':str(Path(d)/'linker')},clear=True):
            job=server.LoginJob('fixture-profile','fixture-shop',defer_registry=True)
            path=Path(d)/'profiles/fixture-profile.json';path.parent.mkdir();path.write_text('{}');server.sl.mark_auth_pending(job.profile,job.id,'','fixture-shop')
            identity={'shopName':'fixture-shop','venderId':'123'}
            base={'profile':job.profile,'home':d,'tokenCredentialAccount':'jdo-cli:token:fixture-profile:default','tokenMocked':False,'tokenStored':True,'loginCompleted':True}
            for changed in ({'profile':'other-profile'},{'home':str(Path(d)/'other')},{'tokenMocked':True},{'tokenCredentialAccount':'jdo-cli:token:other-profile:default'},{'tokenCredentialAccount':'jdo-cli:token:fixture-profile:other-profile:default'}):
                with self.subTest(changed=changed),patch.object(server,'copy_credential') as copy:
                    with self.assertRaises(server.CredentialIsolationError):job._apply_identity(identity,{**base,**changed})
                    copy.assert_not_called()
            self.assertEqual(json.loads(path.read_text()),{})

    def test_builtin_close_accepts_its_local_closed_ack_without_live_context_metadata(self):
        import browser_adapters
        from heideng_merchant import host_connection_controller as hc
        controller=Mock();controller.dispatch.side_effect=[{'ok':True,'contextId':'fixture','owned':True,'isolated':True},{'ok':True}]
        with patch.object(hc,'HostConnectionController',return_value=controller):
            browser=browser_adapters.BuiltinBrowser({'shopName':'fixture'})
            browser.open_login('fixture')
            try:result=browser.close()
            except Exception as e:self.fail(f'本地关闭确认不应再强求活contextId：{e}')
        self.assertEqual(result['status'],'closed');self.assertTrue(browser._closed)

    def test_rejected_trial_profiles_do_not_create_false_shop_ambiguity_but_other_stores_do(self):
        import shoplib as sl
        registry={'profiles':{'fixture-bad':{'shopName':'fixture-shop'},'fixture-good':{'shopName':'fixture-shop','venderId':'123'}}}
        with patch.object(sl,'load_registry',return_value=registry),patch.object(sl,'list_disk_profiles',return_value=['fixture-bad','fixture-good']),patch.object(sl,'read_json',return_value={}),patch.object(sl,'_proof_data',return_value={'profiles':{'fixture-bad':{'status':'rejected'}}}):view=sl.build_view()
        self.assertEqual(len(sl.match_groups(view,'fixture-shop')),1)
        self.assertEqual(registry['profiles']['fixture-bad']['shopName'],'fixture-shop')
        view['other-valid']={'shopName':'fixture-shop','venderId':'456','hasProfile':True}
        self.assertEqual(len(sl.match_groups(view,'fixture-shop')),2)

if __name__=='__main__':unittest.main()
