"""Local CLI deadlines: synthetic executables only, no real accounts or system credential store."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tests.test_mature_connection import SOURCE, load


class ConnectionLocalTimeoutTests(unittest.TestCase):
    def setUp(self):
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'JDO_HOME':str(temporary/'jdo'), 'JINGMAI_LINKER_HOME':str(temporary/'linker')}))
        self.enterContext(patch.object(sys,'path',[str(SOURCE/'app'),*sys.path]))
        self.server=load('local_timeout_server',SOURCE/'app/server.py')
        self.sl=self.server.sl

    def test_venderinfo_local_process_timeout_does_not_claim_network_failure(self):
        with patch.object(self.sl,'run_jdo',side_effect=subprocess.TimeoutExpired(['fixture'],1)):
            with self.assertRaises(self.sl.VerifyError) as result:
                self.sl.verify_profile('fixture')
        self.assertEqual(result.exception.kind,'local_cli_timeout')
        self.assertEqual(self.sl.classify_error('timed out'), 'local_cli_timeout')
        self.assertEqual(self.sl.classify_error('getaddrinfo failed'), 'network')

    def test_status_timeout_keeps_original_completion_without_relogin_or_credential_access(self):
        job=self.server.LoginJob('fixture-profile','样例店',force=False)
        self.sl.profiles_dir().mkdir(parents=True,exist_ok=True)
        (self.sl.profiles_dir()/'fixture-profile.json').write_bytes(b'{}')
        self.sl.mark_auth_pending(job.profile,job.id,shop_name=job.shop_name)
        self.sl.mark_auth_native_completed(job.profile,job.id,'fixture-native',reused_login=True)
        before=self.sl._proof_data()
        with patch.object(self.sl,'run_jdo',side_effect=subprocess.TimeoutExpired(['fixture'],1)) as status, \
                patch.object(self.server.LoginJob,'start',side_effect=AssertionError('no OAuth')) as login, \
                patch.object(self.server,'copy_credential',side_effect=AssertionError('no credential access')):
            with self.assertRaises(self.sl.VerifyError) as pending:
                self.server.recover_owned_auth_slot(job.profile,job.id)
        self.assertEqual(pending.exception.kind,'native_receipt_pending')
        self.assertIn('status',pending.exception.message)
        self.assertIn('超时',pending.exception.message)
        self.assertEqual(status.call_args.args[0],['status'])
        login.assert_not_called()
        self.assertEqual(before,self.sl._proof_data())

    def test_login_deadline_stops_only_the_owned_sleeping_process_and_preserves_pending_job(self):
        job=self.server.LoginJob('fixture-profile','样例店',force=False,timeout=.25)
        self.sl.mark_auth_pending(job.profile,job.id,shop_name=job.shop_name)
        before=self.sl._proof_data()
        cmd=[sys.executable,'-I','-c','import time;time.sleep(25)']
        with subprocess.Popen(cmd,start_new_session=os.name!='nt') as sibling, \
                subprocess.Popen(cmd,start_new_session=os.name!='nt') as owned:
            try:
                job.proc=owned
                job._owns_process_group=os.name!='nt'
                worker=threading.Thread(target=job._monitor,daemon=True)
                worker.start()
                self.assertTrue(job._done.wait(5),'host deadline elapsed without a terminal receipt')
                worker.join(3)
                self.assertIsNotNone(owned.poll())
                self.assertIsNone(sibling.poll())
                self.assertEqual(job.error_kind,'callback_unknown')
                self.assertIn('超时',job.message)
                self.assertFalse(worker.is_alive())
                self.assertEqual(before,self.sl._proof_data())
            finally:
                for process in (owned,sibling):
                    if process.poll() is None:process.kill()

    def test_no_url_start_honours_shorter_task_deadline_and_creates_only_one_cli(self):
        job=self.server.LoginJob('fixture-profile','样例店',force=False,timeout=.4)
        self.sl.profiles_dir().mkdir(parents=True,exist_ok=True)
        (self.sl.profiles_dir()/'fixture-profile.json').write_bytes(b'{}')
        original=subprocess.Popen
        owned=[]
        def spawn(cmd,*args,**kwargs):
            if cmd[:2] == [sys.executable,'login']:
                process=original([sys.executable,'-I','-c','import time;time.sleep(25)'],*args,**kwargs)
                owned.append(process)
                return process
            return original(cmd,*args,**kwargs)
        restore=job._restore_default
        def delayed_restore():
            time.sleep(.12)
            restore()
        with patch.object(self.server,'jdo_exe',return_value=sys.executable), \
                patch.object(self.server,'ensure_callback_port_free'),patch.object(job,'_restore_default',side_effect=delayed_restore), \
                patch.object(subprocess,'Popen',side_effect=spawn):
            start=time.monotonic()
            job.start()
            self.assertTrue(job._done.wait(3))
            self.assertLess(time.monotonic()-start,5)
        self.assertEqual(job.error_kind,'callback_unknown')
        self.assertEqual(len(owned),1)
        self.assertIsNotNone(owned[0].poll())
        self.assertFalse(job._monitor_thread.is_alive())

    def test_shutdown_cannot_claim_cleanup_while_native_monitor_is_finishing(self):
        import browser_auth
        from types import SimpleNamespace
        job=browser_auth.BrowserAuthJob('fixture-profile','样例店')
        release=threading.Event()
        monitor=threading.Thread(target=release.wait)
        job.login=SimpleNamespace(_monitor_thread=monitor)
        monitor.start()
        try:
            self.assertFalse(job.shutdown(timeout=.02))
        finally:
            release.set()
        self.assertTrue(job.shutdown(timeout=2))

    def test_doctor_reports_a_local_status_timeout_even_if_executable_exists(self):
        with patch.object(self.sl,'find_jdo',return_value=Path(sys.executable)), \
                patch.object(self.sl,'run_jdo',side_effect=subprocess.TimeoutExpired(['fixture'],1)), \
                patch.object(self.sl,'cli_version_info',return_value={}),patch.object(self.sl,'port_owner',return_value=(None,'')):
            result=self.sl.doctor()
        check=next(item for item in result['checks'] if item['name']=='官方 CLI 状态回执')
        self.assertEqual(check['errorKind'],'local_cli_timeout')
        self.assertFalse(check['ok'])

    @unittest.skipIf(os.name=='nt','POSIX process group')
    def test_readonly_timeout_stops_cli_child_in_same_private_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'child-ran'
            code='import time,pathlib,sys;p=pathlib.Path(sys.argv[1]);p.with_suffix(".started").touch();time.sleep(2.5);p.touch()'
            parent='import sys,time,subprocess;subprocess.Popen([sys.executable,"-I","-c",sys.argv[1],sys.argv[2]]);time.sleep(25)'
            with patch.object(self.sl,'find_jdo',return_value=sys.executable), self.assertRaises(subprocess.TimeoutExpired):
                self.sl.run_jdo(['-I','-c',parent,code,str(path)],timeout=1.2)
            self.assertTrue(path.with_suffix('.started').exists())
            time.sleep(2.6)
            self.assertFalse(path.exists())
