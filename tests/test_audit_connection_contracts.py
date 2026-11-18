"""Connection audit regressions, synthetic transport only; no OAuth network."""
import io,json,os,sys,tempfile,time,unittest,importlib.util
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'mature/connection/app';SCRIPT=ROOT/'mature/connection/scripts/linker.py'

class AuditConnectionTests(unittest.TestCase):
    def setUp(self):
        self.old_path=list(sys.path);self.names=('shoplib','redaction','browser_auth','browser_adapters','server','linker')
        self.saved={n:sys.modules.pop(n,None) for n in self.names};sys.path.insert(0,str(APP))
        spec=importlib.util.spec_from_file_location('linker',SCRIPT);self.cli=importlib.util.module_from_spec(spec);sys.modules['linker']=self.cli;spec.loader.exec_module(self.cli)
    def tearDown(self):
        sys.path[:]=self.old_path
        for name,value in self.saved.items():
            sys.modules.pop(name,None)
            if value is not None:sys.modules[name]=value
    def test_stage_changes_emit_sanitized_progress_without_duplicate_events(self):
        jobs=[{'id':'one','profile':'fixture','status':'waiting','stage':stage,'message':'token=fixture-secret','browserChannel':'msedge'} for stage in ('waiting_login','waiting_login','waiting_oauth')]
        jobs.append({'id':'one','profile':'fixture','status':'success','stage':'ready','identity':{'shopName':'fixture-shop','venderId':'123'}})
        with patch.object(self.cli,'api',side_effect=[(200,{'job':j}) for j in jobs]),redirect_stdout(io.StringIO()) as out:
            result=self.cli.wait_job(5,0,job_id='one',profile='fixture',shop_name='fixture-shop',vender_id='123')
        events=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([e['stage'] for e in events],['waiting_login','waiting_oauth','ready'])
        self.assertNotIn('fixture-secret',out.getvalue());self.assertNotIn('identity',events[0])
        self.assertEqual(result['status'],'ready')
    def test_login_and_oauth_share_one_budget(self):
        import browser_auth
        job=browser_auth.BrowserAuthJob('fixture','fixture-shop',browser=Mock(),login_timeout=600,oauth_timeout=600,connection_timeout=10)
        with patch.object(browser_auth.time,'monotonic',return_value=job.connection_deadline-1):
            self.assertLessEqual(job.phase_deadline(600),job.connection_deadline)
        self.assertEqual(job.phase_deadline(600),job.connection_deadline)
    def test_numeric_target_can_begin_oauth_without_fabricating_vender_id(self):
        import browser_auth
        job=browser_auth.BrowserAuthJob('fixture','',expect_vender_id='123',browser=Mock())
        self.assertTrue(job._browser_matches({'shopName':'fixture-shop'}))
        self.assertEqual(job.expect_vender_id,'123')
        self.assertFalse(job._matches({'shopName':'fixture-shop','venderId':'456'}))
        self.assertFalse(job._browser_matches({'shopName':'fixture-shop','venderId':'456'}))
    def test_foreground_return_is_paused_not_false_background_execution(self):
        args=type('Args',(),{'no_wait':False,'no_open':False,'browser_config':None,'timeout':600})()
        pending={'ok':True,'status':'awaiting_auth','stage':'waiting_oauth','jobId':'one','profile':'fixture'}
        snapshot={'status':'failed','stage':'paused','errorKind':'callback_unknown','profile':'fixture','id':'one'}
        with patch.object(self.cli,'_cmd_ensure_shop',return_value=pending),patch.object(self.cli,'close_embedded_server',return_value=snapshot):
            result=self.cli.cmd_ensure_shop(args)
        self.assertEqual(result['status'],'paused');self.assertFalse(result['processRunning'])
        self.assertEqual(result['profile'],'fixture');self.assertFalse(result['retryAllowed'])
    def test_shutdown_joins_worker_and_closes_owned_browser(self):
        import browser_auth
        browser=Mock();browser.observe.return_value={'loggedIn':False,'identity':{}}
        with patch.object(browser_auth.sl,'mark_auth_pending'):
            job=browser_auth.BrowserAuthJob('fixture','fixture-shop',browser=browser,poll_interval=.01)
            job.start()
            try:
                deadline=time.monotonic()+2
                while job.stage!='waiting_login' and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(job.shutdown(timeout=2))
                self.assertFalse(job._worker_thread.is_alive());browser.close.assert_called_once()
                self.assertEqual(job.stage,'paused')
            finally:job.cancel()

    def test_paused_callback_is_reconciled_on_original_profile_before_new_auth(self):
        args=type('Args',(),{'shop':'fixture-shop','profile':None,'no_auth':False,'no_open':False,'no_wait':True,'resume':False,'fresh':False,'browser_config':None,'timeout':600})()
        pending={'query':'fixture-shop','shopName':'fixture-shop','venderId':'123','profile':'old-owned-profile','jobId':'one','processRunning':False,'outcome':'callback_unknown'}
        with patch.object(self.cli,'_env_blockers',return_value=None),patch.object(self.cli.sl,'resolve',return_value={'status':'needs_auth','shopName':'fixture-shop','venderId':'123'}),patch.object(self.cli.sl,'load_pending',return_value=pending),patch.object(self.cli.sl,'require_auth_slot'),patch.object(self.cli.sl,'assert_profile_proof'),patch.object(self.cli.sl,'verify_profile',return_value={'shopName':'fixture-shop','venderId':'123'}) as verify,patch.object(self.cli.sl,'update_registry'),patch.object(self.cli.sl,'clear_pending'),patch.object(self.cli.sl,'suggest_profile_name',return_value='new-suggested'),patch.object(self.cli,'api',return_value=(200,{'ok':False,'status':'unexpected-new-auth'})) as api:
            result=self.cli.cmd_ensure_shop(args)
        self.assertEqual(result['status'],'ready');self.assertEqual(result['profile'],'old-owned-profile')
        verify.assert_called_once_with('old-owned-profile');api.assert_not_called()
    def test_other_shop_pending_with_empty_id_is_never_resumed(self):
        args=type('Args',(),{'shop':'fixture-b','profile':None,'no_auth':False,'no_open':False,'no_wait':True,'resume':False,'fresh':False,'browser_config':None,'timeout':600})()
        pending={'query':'fixture-a','shopName':'fixture-a','venderId':'','profile':'b-suggested','jobId':'one'}
        with patch.object(self.cli,'_env_blockers',return_value=None),patch.object(self.cli.sl,'resolve',return_value={'status':'needs_auth','shopName':'fixture-b'}),patch.object(self.cli.sl,'load_pending',return_value=pending),patch.object(self.cli.sl,'suggest_profile_name',return_value='b-suggested'),patch.object(self.cli.sl,'save_pending'),patch.object(self.cli,'api',return_value=(200,{'ok':True,'profile':'b-suggested','jobId':'two'})) as api:
            self.cli.cmd_ensure_shop(args)
        self.assertFalse(api.call_args.args[1]['resume'])

    def test_command_interrupt_records_paused_exit_and_keeps_exact_pending_profile(self):
        args=type('Args',(),{'no_wait':False,'no_open':False,'browser_config':None,'timeout':600})()
        snapshot={'status':'failed','stage':'paused','errorKind':'callback_unknown','profile':'fixture','id':'one'}
        pending={'jobId':'one','profile':'fixture','query':'fixture-shop'}
        with patch.object(self.cli,'_cmd_ensure_shop',side_effect=KeyboardInterrupt),patch.object(self.cli,'close_embedded_server',return_value=snapshot),patch.object(self.cli.sl,'load_pending',return_value=pending),patch.object(self.cli.sl,'save_pending') as save:
            try:result=self.cli.cmd_ensure_shop(args)
            except KeyboardInterrupt:self.fail('用户离开时必须给出暂停回执')
        self.assertEqual(result['status'],'paused');self.assertEqual(result['profile'],'fixture')
        self.assertFalse(save.call_args.args[0]['processRunning'])
    def test_resource_close_failure_is_not_reported_as_complete_cleanup(self):
        import browser_auth
        browser=Mock();browser.observe.return_value={'loggedIn':False,'identity':{}}
        browser.close.side_effect=RuntimeError('fixture-close-failed')
        with patch.object(browser_auth.sl,'mark_auth_pending'):
            job=browser_auth.BrowserAuthJob('fixture','fixture-shop',browser=browser,poll_interval=.01)
            job.start()
            try:
                time.sleep(.05)
                self.assertFalse(job.shutdown(timeout=2))
            finally:job.cancel()

    def test_late_login_does_not_start_a_fresh_full_oauth_budget(self):
        import browser_auth,threading
        start=time.monotonic();browser=Mock()
        browser.observe.side_effect=lambda:{'loggedIn':time.monotonic()-start>.15,'identity':{'shopName':'fixture-shop'}}
        browser.confirm.return_value={}
        login=Mock();login.status='waiting';login._done=threading.Event();login.url='https://passport.jd.com/oauth/fixture';login.proc=None
        factory=Mock(return_value=login)
        with patch.object(browser_auth.sl,'mark_auth_pending'),patch.object(browser_auth.sl,'require_auth_slot'),patch.object(browser_auth.sl,'verify_profile',side_effect=browser_auth.sl.VerifyError('auth_missing','no synthetic callback')):
            job=browser_auth.BrowserAuthJob('fixture','fixture-shop',browser=browser,login_factory=factory,login_timeout=.25,oauth_timeout=.25,connection_timeout=.25,poll_interval=.005)
            job.start()
            try:
                self.assertTrue(job._done.wait(.7),'共享预算应在本次预算内结束等待')
                self.assertTrue(job.shutdown(timeout=1))
                self.assertLess(time.monotonic()-start,.8)
                self.assertEqual(job.error_kind,'callback_unknown');factory.assert_called_once()
                browser.confirm.assert_called_once();self.assertFalse(job._worker_thread.is_alive())
            finally:job.cancel()

    def test_terminal_cancel_and_failure_are_not_relabelled_as_pending_pause(self):
        args=type('Args',(),{'no_wait':False,'no_open':False,'browser_config':None,'timeout':600})()
        for state in ('cancelled','failed','mismatch'):
            with self.subTest(state=state),patch.object(self.cli,'_cmd_ensure_shop',return_value={'ok':False,'status':state,'profile':'fixture'}),patch.object(self.cli,'close_embedded_server',return_value={'status':state,'stage':state,'profile':'fixture','id':'one'}):
                result=self.cli.cmd_ensure_shop(args)
            self.assertEqual(result['status'],state)
            self.assertFalse(result.get('processRunning',False))

    def test_mismatch_shutdown_does_not_turn_rejected_identity_into_pending_callback(self):
        import browser_auth
        browser=Mock();browser.observe.return_value={'loggedIn':True,'identity':{'shopName':'wrong-shop','venderId':'456'}}
        with patch.object(browser_auth.sl,'mark_auth_pending'),patch.object(browser_auth.sl,'mark_auth_rejected'),patch.object(browser_auth.sl,'require_auth_slot',side_effect=browser_auth.sl.VerifyError('credential_isolation','rejected original')),patch.object(browser_auth.sl,'verify_profile') as verify:
            job=browser_auth.BrowserAuthJob('fixture','fixture-shop',expect_vender_id='123',browser=browser,poll_interval=.01)
            job.start()
            try:
                self.assertTrue(job._done.wait(1))
                job.login=Mock(proc=None)  # An earlier OAuth already produced a rejected identity.
                self.assertTrue(job.shutdown(timeout=2))
                self.assertEqual(job.status,'mismatch');verify.assert_not_called()
            finally:job.cancel()

    def test_wall_clock_adjustment_does_not_end_the_monotonic_login_budget(self):
        waiting={'id':'one','profile':'fixture','status':'waiting','stage':'waiting_login'}
        ready={**waiting,'status':'success','stage':'ready','identity':{'shopName':'fixture-shop','venderId':'123'}}
        with patch.object(self.cli.time,'time',side_effect=[0,10000,10000]),patch.object(self.cli.time,'monotonic',return_value=1),patch.object(self.cli,'api',side_effect=[(200,{'job':waiting}),(200,{'job':ready})]),redirect_stdout(io.StringIO()):
            result=self.cli.wait_job(5,0,job_id='one',profile='fixture')
        self.assertEqual(result['status'],'ready')

if __name__=='__main__':unittest.main()
