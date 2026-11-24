"""Official 0.3.7 receipt shapes in an isolated home; no native CLI or credential store."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tests import test_audit_connection_contracts as fixtures


class MacLoginReceiptTests(unittest.TestCase):
    def setUp(self):
        fixtures.AuditConnectionTests.setUp(self)
        self.addCleanup(fixtures.AuditConnectionTests.tearDown, self)
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.dict(os.environ, {'HOME':str(self.home),'USERPROFILE':str(self.home),
                                                 'HEIDENG_MERCHANT_HOME':str(self.home),
                                                 'JDO_HOME':str(self.home),'JDO_CLI_HOME':str(self.home),
                                                 'JINGMAI_LINKER_HOME':str(self.home/'linker')},clear=True))
        self.enterContext(patch('sys.platform', 'darwin'))
        import server
        self.server = server
        self.job = server.LoginJob('fixture-original','演示店',force=False,defer_registry=True)
        self.profile = self.job.profile
        self.profile_file = self.home/'profiles'/f'{self.profile}.json'
        self.profile_file.parent.mkdir()
        self.profile_file.write_bytes(b'{"shop_name":"fixture"}')
        self.identity = {'shopName':'演示店','shopId':'808','venderId':'556'}
        self.scope = '0123456789abcdef'
        self.account = f'token:{self.profile}:{self.scope}:default'
        self.login = {'command':'login','ok':True,'cliVersion':'0.3.7','timestamp':1,'profile':self.profile,
                      'home':str(self.home),'alreadyAuthorized':True,'reusedAuthorization':True,
                      'authorizationStatus':'reused_existing_credentials','authorizationStage':'credential_reuse',
                      'authorizeUrlPrinted':False,'appKeyConfigured':True,'appSecretStored':True,
                      'tokenStored':True,'tokenMocked':False,'loginCompleted':True}
        self.status = {'ok':True,'command':'status','home':str(self.home),'defaultProfile':self.profile,
                       'profile':{'exists':True,'appKeyConfigured':True,'path':str(self.profile_file)},
                       'credentialStore':{'appSecretStored':True,'tokenCredentialAccount':self.account},
                       'credentialInputs':{'oauthTokenStored':True,'oauthTokenMocked':False,
                                           'accessTokenFromEnv':False,'appSecretFromEnv':False}}
        def run(args,timeout):
            if args == ['status']:
                return 0,json.dumps(self.status)
            if args == ['status','--profile',self.profile]:
                return 2,'unsupported option'
            raise AssertionError(args)
        self.read = self.enterContext(patch.object(server.sl,'run_jdo',side_effect=run))
        self.verify = self.enterContext(patch.object(server.sl,'verify_profile',return_value=self.identity))
        self.enterContext(patch.object(server,'copy_credential',side_effect=AssertionError('credential store accessed')))
        server.sl.mark_auth_pending(self.profile,self.job.id,shop_name='演示店')

    def monitor(self, login):
        self.job.proc = Mock()
        self.job.proc.wait.return_value = 0
        self.job._raw_output = [json.dumps(login)]
        self.job._monitor()

    def test_reuse_without_account_registers_only_after_same_profile_status_and_live_identity(self):
        self.status['credentialStore']['tokenCredentialAccount'] = self.account.removesuffix('default')+'556'
        self.status['profile']['venderId'] = '556'
        self.monitor(self.login)
        self.assertEqual(self.job.status,'success')
        self.assertEqual(self.job.identity,self.identity)
        self.assertGreaterEqual(self.verify.call_count,2)
        self.assertTrue(all(call.args == (self.profile,) for call in self.verify.call_args_list))
        proof = self.server.sl._proof_data()['profiles'][self.profile]
        self.assertTrue(proof['nativeReused'])
        self.assertEqual((proof['shopId'],proof['officialShopName']),('808','演示店'))
        for changed in ({'shopId':'909'},{'venderId':'100'},{'shopName':'演示店二店'}):
            with self.subTest(changed=changed), self.assertRaises(self.server.sl.VerifyError):
                self.server.sl.assert_profile_proof(self.profile,{**self.identity,**changed})

    def test_numeric_slot_rejects_same_merchant_and_name_but_different_second_shop_id(self):
        self.status['credentialStore']['tokenCredentialAccount']=self.account.removesuffix('default')+'556'
        self.status['profile']['venderId']='556'
        self.verify.side_effect=[self.identity,{**self.identity,'shopId':'909'}]
        self.job.defer_registry=False
        self.monitor(self.login)
        self.assertEqual(self.job.status,'failed')
        self.assertNotIn(self.profile,self.server.sl.load_registry()['profiles'])
        proof=self.server.sl._proof_data()['profiles'][self.profile]
        self.assertEqual(proof['status'],'rejected')
        with self.assertRaises(self.server.sl.VerifyError):
            self.server.sl.require_auth_slot(self.profile,required=True)

    def test_legacy_numeric_proof_is_completed_only_when_live_result_matches_registered_store(self):
        sl = self.server.sl
        sl.mark_auth_slot(self.profile,'556',job_id=self.job.id)
        sl.save_registry({'profiles':{self.profile:{**self.identity,'lastVerifiedAt':5}}})
        old=sl._proof_data()
        self.assertNotIn('shopId',old['profiles'][self.profile])
        for changed in ({'shopId':'909'}, {'shopName':'演示店二店'}, {'venderId':'654'}):
            with self.subTest(changed=changed):
                self.verify.return_value={**self.identity,**changed}
                result=sl.scan_profiles([self.profile],self.verify)
                self.assertEqual(result[self.profile]['error'],'credential_isolation')
                self.assertEqual(sl._proof_data(),old)
                self.assertEqual(sl.load_registry()['profiles'][self.profile]['shopId'],'808')
        self.verify.return_value=self.identity
        self.assertEqual(sl.scan_profiles([self.profile],self.verify)[self.profile]['identity'],self.identity)
        proof=sl._proof_data()['profiles'][self.profile]
        self.assertEqual((proof['shopId'],proof['officialShopName'],proof['status']),('808','演示店','verified'))

    def test_no_new_shop_binding_from_incomplete_official_identity(self):
        self.status['credentialStore']['tokenCredentialAccount']=self.account.removesuffix('default')+'556'
        self.status['profile']['venderId']='556'
        self.verify.return_value={**self.identity,'shopId':''}
        self.monitor(self.login)
        self.assertEqual(self.job.error_kind,'native_receipt_pending')
        self.assertTrue(self.server.sl._proof_data()['profiles'][self.profile]['nativeCompleted'])
        self.assertNotIn(self.profile,self.server.sl.load_registry()['profiles'])

    def test_resume_native_numeric_slot_without_first_identity_rechecks_before_binding(self):
        sl=self.server.sl
        sl.mark_auth_native_completed(self.profile,self.job.id,'original')
        sl.mark_auth_slot(self.profile,'556',job_id=self.job.id)
        before=sl._proof_data()
        self.verify.side_effect=[self.identity,{**self.identity,'shopId':'909'}]
        drift=sl.scan_profiles([self.profile],self.verify)
        self.assertEqual(drift[self.profile]['error'],'credential_isolation')
        self.assertEqual(sl._proof_data(),before)
        self.verify.side_effect=[self.identity,self.identity]
        self.assertEqual(sl.scan_profiles([self.profile],self.verify)[self.profile]['identity'],self.identity)
        proof=sl._proof_data()['profiles'][self.profile]
        self.assertEqual((proof['nativeJobId'],proof['shopId'],proof['status']),('original','808','verified'))

    def test_default_slot_remains_in_place_and_subsequent_reads_check_scope_and_both_ids(self):
        fresh = {**self.login,'alreadyAuthorized':False,'reusedAuthorization':False,
                 'authorizeUrlPrinted':True,'authorizationStatus':'logged_in','authorizationStage':'credential_saved',
                 'tokenCredentialAccount':self.account}
        original = self.profile_file.read_bytes()
        self.monitor(fresh)
        self.assertEqual(self.job.status,'success')
        proof = self.server.sl._proof_data()['profiles'][self.profile]
        self.assertEqual((proof['slotKind'],proof['profileDefaultScope'],proof['shopId']),('profile-default',self.scope,'808'))
        self.assertEqual(self.profile_file.read_bytes(),original)
        self.server.sl.assert_profile_proof(self.profile,self.identity)
        for changed in ({'shopId':'909'},{'venderId':'111'}):
            with self.subTest(changed=changed), self.assertRaises(self.server.sl.VerifyError):
                self.server.sl.assert_profile_proof(self.profile,{**self.identity,**changed})
        self.status['credentialStore']['tokenCredentialAccount'] = f'token:{self.profile}:fedcba9876543210:default'
        with self.assertRaises(self.server.sl.VerifyError):
            self.server.sl.require_auth_slot(self.profile,required=True)

    def test_another_default_preserves_original_native_completion_then_recovers_without_login(self):
        self.status['defaultProfile'] = 'fixture-other'
        self.monitor(self.login)
        self.assertEqual(self.job.error_kind,'native_receipt_pending')
        self.verify.assert_not_called()
        proof = self.server.sl._proof_data()['profiles'][self.profile]
        self.assertTrue(proof['nativeCompleted'])
        self.assertFalse(proof['slotVerified'])
        self.assertEqual(proof['status'],'pending')
        pending = {'query':'演示店','shopName':'演示店','venderId':'','profile':self.profile,'jobId':self.job.id,
                   'processRunning':False,'outcome':'native_receipt_pending'}
        browser_dir = self.home/'browser-profiles'/'original'
        browser_dir.mkdir(parents=True)
        pending.update(browserProfileDir=str(browser_dir),browserChannel='chrome')
        args = type('Args',(),{'shop':'演示店','profile':None,'no_auth':True})()
        with patch.object(self.cli,'_env_blockers',return_value=None), patch.object(self.server.sl,'load_pending',return_value=pending), patch.object(
                self.server.sl,'resolve',return_value={'status':'error','errorKind':'credential_isolation'}), patch.object(
                self.server.LoginJob,'start',side_effect=AssertionError('new authorization')):
            self.assertEqual(self.cli._cmd_ensure_shop(args)['status'],'paused')
            self.status['defaultProfile'] = self.profile
            result = self.cli._cmd_ensure_shop(args)
            self.assertEqual((result['status'],result['profile']),('ready',self.profile))
            self.assertEqual(result['identity'],self.identity)
            self.assertEqual(self.server.sl.load_registry()['profiles'][self.profile]['browserProfileDir'],str(browser_dir))

    def test_reuse_rejects_other_home_wrong_flags_false_claim_and_environment_override(self):
        for changed in ({'profile':'fixture-other'}, {'home':str(self.home/'other')}, {'tokenMocked':True},
                        {'authorizationStage':'credential_saved'}, {'authorizeUrlPrinted':True}, {'alreadyAuthorized':False}):
            with self.subTest(changed=changed):
                self.assertFalse(self.job._owned_login_receipt({**self.login,**changed}))
        for changed in ({'appSecretFromEnv':True},{'accessTokenFromEnv':True},{'oauthTokenMocked':True}):
            with self.subTest(changed=changed), patch.dict(self.status['credentialInputs'],changed):
                self.assertFalse(self.job._owned_login_receipt(self.login))
        for value in ('token:fixture-other:0123456789abcdef:default', 'token:bad'):
            with patch.dict(self.status['credentialStore'],{'tokenCredentialAccount':value}):
                self.assertFalse(self.job._owned_login_receipt(self.login))
        self.verify.assert_not_called()

    def test_first_store_keeps_official_init_default_existing_other_default_is_restored(self):
        config = self.home/'config.json'
        self.profile_file.unlink()
        def init():
            self.server.sl.write_json(config,{'default_profile':self.profile})
        for original, registry, expected in ((None, {}, self.profile), ('', {}, self.profile),
                ('previous', {}, 'previous'), ('', {'old':{'venderId':'99'}}, '')):
            if original is not None:
                self.server.sl.write_json(config,{'default_profile':original})
            self.server.sl.save_registry({'profiles':registry})
            with self.subTest(original=original), patch.object(self.server,'jdo_exe',return_value='synthetic-cli'), patch.object(
                    self.server,'ensure_callback_port_free'), patch.object(self.job,'_init_profile',side_effect=init), patch.object(
                    self.server.subprocess,'Popen',side_effect=OSError('no native launch')), self.assertRaises(OSError):
                self.job.start()
            self.assertEqual(self.server.sl.read_json(config)['default_profile'],expected)

    def test_browser_flow_consumes_completed_login_without_requesting_an_oauth_page(self):
        import browser_auth
        browser = Mock()
        browser.observe.return_value = {'loggedIn':True,'identity':self.identity,'challenge':''}
        completed = Mock(url='',status='success')
        completed._done = threading.Event()
        completed._done.set()
        factory = Mock(return_value=completed)
        flow = browser_auth.BrowserAuthJob('fixture','演示店',browser=browser,login_factory=factory)
        with patch.object(flow,'_verify_and_commit') as commit:
            flow.run()
        self.assertFalse(factory.call_args.kwargs['force'])
        browser.open_oauth.assert_not_called()
        browser.confirm.assert_not_called()
        commit.assert_called_once()

    def test_ambiguous_name_can_read_only_the_explicit_original_job(self):
        from argparse import Namespace
        sl = self.server.sl
        other = {'venderId':'777','shopId':'888','shopName':self.identity['shopName'],'lastVerifiedAt':5}
        sl.save_registry({'profiles':{'second-store':other}})
        sl.write_json(sl.profiles_dir()/'second-store.json', {'shop_name':other['shopName']})
        sl.write_json(self.profile_file, {'shop_name':other['shopName']})
        original_file = self.profile_file.read_bytes()
        self.status['defaultProfile'] = 'second-store'
        self.monitor(self.login)
        self.assertEqual(self.job.error_kind, 'native_receipt_pending')
        pending = {'query':'演示店','shopName':'演示店','venderId':'','profile':self.profile,'jobId':self.job.id,
                   'processRunning':False,'outcome':'native_receipt_pending'}
        sl.save_pending(pending)
        args = Namespace(shop='演示店',profile=self.profile,job_id=self.job.id,resume=True,no_auth=True)
        resolve = sl.resolve
        def local_resolve(query):
            return resolve(query, verify=self.verify)
        with patch.object(self.cli,'_env_blockers',return_value=None), patch.object(sl,'resolve',side_effect=local_resolve), patch.object(
                self.server.LoginJob,'start',side_effect=AssertionError('unexpected new authorization')), patch.object(
                self.cli,'ensure_embedded_server',side_effect=AssertionError('unexpected service')):
            by_name = self.cli._cmd_ensure_shop(Namespace(shop='演示店',profile=None,resume=False,no_auth=True))
            self.assertEqual(by_name['status'],'ambiguous')
            self.assertEqual(by_name['originalReceipt']['jobId'],self.job.id)
            for changed in ({'job_id':'old'},{'resume':False},{'profile':'second-store'},{'shop':'演-示店'},{'fresh':True}):
                with self.subTest(changed=changed):
                    result=self.cli.cmd_ensure_shop(Namespace(**{**vars(args),**changed}))
                    self.assertEqual(result['errorKind'],'original_task_mismatch')
            self.assertEqual(self.cli.cmd_ensure_shop(args)['status'],'paused')
            self.verify.assert_not_called()
            self.status['defaultProfile'] = self.profile
            self.status['credentialStore']['tokenCredentialAccount'] = self.account.removesuffix('default')+'556'
            self.status['profile']['venderId'] = '556'
            result = self.cli.cmd_ensure_shop(args)
            self.assertEqual((result['status'],result['profile'],result['jobId']),('ready',self.profile,self.job.id))
            self.assertTrue(all(call.args == (self.profile,) for call in self.verify.call_args_list))
            self.assertEqual(self.profile_file.read_bytes(),original_file)
            self.assertEqual(sl.load_registry()['profiles']['second-store'],other)
            self.assertEqual(self.cli._cmd_ensure_shop(Namespace(shop='演示店',no_auth=True))['status'],'ambiguous')

    def test_ambiguous_lookup_never_advertises_an_unrelated_pending_job(self):
        from argparse import Namespace
        sl = self.server.sl
        sl.mark_auth_native_completed(self.profile,self.job.id,'native')
        pending = {'query':'同名','profile':self.profile,'jobId':self.job.id,'outcome':'callback_unknown','processRunning':False}
        with patch.object(self.cli,'_env_blockers',return_value=None), patch.object(
                sl,'resolve',side_effect=lambda query:{'status':'ambiguous','candidates':[{'profile':self.profile}]}):
            for changed in ({'query':'另一家'}, {'jobId':'different'}, {'processRunning':True}):
                with self.subTest(changed=changed):
                    sl.save_pending({**pending,**changed})
                    self.assertNotIn('originalReceipt',self.cli._cmd_ensure_shop(Namespace(shop='同名',no_auth=True)))
