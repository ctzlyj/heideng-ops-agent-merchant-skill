import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.auth_manager import AuthManager
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from heideng_merchant.state import FileLock
from tests import test_auth_manager as managers_fixture

class AuthHostLifecycleTests(unittest.TestCase):
 def setup_manager(self,d):
  fixture=managers_fixture.ManagerTests();manager=fixture.manager(d);manager.process_probe=lambda pid:"unknown";return manager,fixture
 def receipt(self,m,job,**changes):
  data=m._record(job);data.update(changes);atomic_json(m._path(job),data)
 def test_wait_keeps_original_invocation_alive_until_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   m,f=self.setup_manager(d);progress=[]
   def sleep(_):
    job=next((Path(d)/'tasks').glob('*.json')).stem
    self.receipt(m,job,status='completed',stage='ready',ready=True)
   m.sleep=sleep
   result=m.start('test-shop',foreground=True,wait=True,progress=progress.append)
   self.assertEqual(result['status'],'completed');self.assertEqual(len(f.calls),1)
   self.assertGreaterEqual(len(progress),2)
   with FileLock(Path(d)/'auth'/'start.lock',timeout=.1):pass
 def test_wait_timeout_is_not_permission_to_replay(self):
  with tempfile.TemporaryDirectory() as d:
   m,f=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId']
   result=m.wait(job,timeout=0)
   self.assertTrue(result['waitTimedOut']);self.assertEqual(result['status'],'running')
   again=m.start('test-shop',foreground=True);self.assertEqual(again['taskId'],job);self.assertEqual(len(f.calls),1)
 def test_definitely_dead_prescan_worker_can_reconcile_then_restart(self):
  with tempfile.TemporaryDirectory() as d:
   m,f=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId']
   self.receipt(m,job,stage='created')
   m.process_probe=lambda pid:'exited'
   result=m.reconcile(job)
   self.assertEqual(result['status'],'failed');self.assertTrue(result['safeToRestart']);self.assertFalse(result['oauthReplayed'])
   self.assertEqual(m._record(job)['workerExitVerified'],True)
   second=m.restart(job,foreground=True);self.assertNotEqual(second['taskId'],job)
   self.assertEqual(m.restart(job,foreground=True)['taskId'],second['taskId']);self.assertEqual(len(f.calls),2)
 def test_dead_after_oauth_is_unknown_not_retryable(self):
  with tempfile.TemporaryDirectory() as d:
   m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId']
   self.receipt(m,job,stage='waiting_callback_server',authorizationStarted=True)
   m.process_probe=lambda pid:'exited';result=m.reconcile(job)
   self.assertEqual(result['status'],'unknown');self.assertFalse(result['safeToRestart'])
   with self.assertRaises(SafetyError):m.restart(job,foreground=True)
 def test_no_release_for_missing_process_proof_or_held_lock(self):
  for probe in ('alive','unknown'):
   with tempfile.TemporaryDirectory() as d:
    m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId'];m.process_probe=lambda pid:probe
    self.assertEqual(m.reconcile(job)['status'],'running')
  with tempfile.TemporaryDirectory() as d:
   m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId'];m.process_probe=lambda pid:'exited'
   with FileLock(Path(d)/'auth'/('worker-'+job+'.lock')):
    self.assertEqual(m.reconcile(job)['status'],'running')
 def test_identity_mismatch_or_missing_launch_never_releases(self):
  with tempfile.TemporaryDirectory() as d:
   m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId'];m.process_probe=lambda pid:'exited'
   atomic_json(Path(d)/'auth'/'handles'/(job+'.json'),{'taskId':'b'*24,'workerPid':123,'port':1234})
   self.assertEqual(m.reconcile(job)['status'],'running')
   atomic_json(Path(d)/'auth'/'handles'/(job+'.json'),{'taskId':job,'workerPid':456,'port':1234})
   self.assertEqual(m.reconcile(job)['status'],'running')
   (Path(d)/'auth'/'launches'/(job+'.json')).unlink()
   self.assertEqual(m.reconcile(job)['status'],'running')
 def test_second_dead_check_sees_new_process_and_preserves_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId'];results=iter(['exited','alive'])
   m.process_probe=lambda pid:next(results)
   self.assertEqual(m.reconcile(job)['status'],'running')
 def test_reconcile_path_is_validated_before_any_new_lock(self):
  with tempfile.TemporaryDirectory() as d:
   m=AuthManager(Path(d))
   with self.assertRaises(SafetyError):m.reconcile('../unsafe')
   self.assertFalse((Path(d)/'auth').exists())
 def test_legacy_unknown_flag_never_becomes_retryable(self):
  with tempfile.TemporaryDirectory() as d:
   m,_=self.setup_manager(d);job=m.start('test-shop',foreground=True)['taskId']
   self.receipt(m,job,stage='waiting_login',authorizationOutcomeUnknown=True);m.process_probe=lambda pid:'exited'
   result=m.reconcile(job);self.assertEqual(result['status'],'unknown');self.assertFalse(result['safeToRestart'])

class AuthReconciliationRaceTests(unittest.TestCase):
 def test_authorization_marker_changed_before_lock_is_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d);job=m.start('test-shop',foreground=True)['taskId']
   def probe(pid):
    data=m._record(job);data.update(authorizationStarted=True,stage='waiting_callback_server');atomic_json(m._path(job),data);return 'exited'
   m.process_probe=probe;result=m.reconcile(job)
   self.assertEqual(result['status'],'running');self.assertTrue(m._record(job)['authorizationStarted'])
   with self.assertRaises(SafetyError):m.restart(job,foreground=True)
 def test_wait_progress_contains_no_browser_or_sdk_private_fields(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d);m.process_probe=lambda pid:'unknown'
   first=m.start('test-shop',foreground=True);data=m._record(first['taskId']);data.update(token='private-test-secret',oauthUrl='https://open-oauth.jd.com/oauth2/?state=private-test-secret');atomic_json(m._path(first['taskId']),data)
   events=[];m.wait(first['taskId'],timeout=0,progress=events.append)
   self.assertNotIn('private-test-secret',json.dumps(events));self.assertEqual(len(events),1)

class AuthRealProcessTests(unittest.TestCase):
 def test_native_probe_tracks_actual_owned_process_exit(self):
  import subprocess,sys
  from heideng_merchant.auth_lifecycle import process_state
  process=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:self.assertEqual(process_state(process.pid),'alive')
  finally:process.terminate();process.wait(timeout=5)
  self.assertEqual(process_state(process.pid),'exited')
 def test_real_child_keeps_start_invocation_open_until_synthetic_completion(self):
  import subprocess,sys,time
  worker_code="""import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from heideng_merchant.safety import read_json,atomic_json
from heideng_merchant.state import FileLock
state=Path(sys.argv[2]);job=sys.argv[3];path=state/'tasks'/(job+'.json')
with FileLock(state/'auth'/('worker-'+job+'.lock')):
 data=read_json(path);data.update(stage='waiting_login');atomic_json(path,data)
 time.sleep(.8)
 data.update(status='completed',stage='ready',ready=True);atomic_json(path,data)
"""
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d);workers=[]
   def launch(args,**options):
    process=subprocess.Popen([sys.executable,'-I','-c',worker_code,str(Path(__file__).resolve().parents[1]),d,args[-1]],**options);workers.append(process);return process
   from heideng_merchant.auth_lifecycle import process_state
   m.starter=launch;m.process_probe=process_state;events=[];start=time.monotonic()
   try:
    result=m.start('test-shop',foreground=True,wait=True,wait_timeout=10,progress=events.append)
    self.assertEqual(result['status'],'completed');self.assertGreater(time.monotonic()-start,.7)
    self.assertEqual(len(workers),1);self.assertTrue(any(e['stage']=='waiting_login' for e in events))
    workers[0].wait(timeout=5)
   finally:
    for p in workers:
     if p.poll() is None:p.terminate();p.wait(timeout=5)
 def test_real_hard_exit_has_formal_prescan_recovery_without_manual_receipt_edit(self):
  import subprocess,sys
  from heideng_merchant.auth_lifecycle import process_state
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d);workers=[]
   def launch(*args,**options):
    p=subprocess.Popen([sys.executable,'-I','-c','import os; os._exit(9)'],**options);workers.append(p);return p
   m.starter=launch;m.process_probe=process_state
   first=m.start('test-shop',foreground=True);workers[0].wait(timeout=5)
   result=m.reconcile(first['taskId']);self.assertEqual(result['status'],'failed');self.assertTrue(result['safeToRestart'])
   second=m.restart(first['taskId'],foreground=True);workers[1].wait(timeout=5)
   self.assertNotEqual(second['taskId'],first['taskId']);self.assertEqual(len(workers),2)
   self.assertEqual(m.reconcile(second['taskId'])['status'],'failed')
 def test_invalid_wait_timeout_never_starts_auth(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d)
   with self.assertRaises(SafetyError):m.start('test-shop',foreground=True,wait=True,wait_timeout=-1)
   self.assertEqual(len(fixture.calls),0)
 def test_probe_exceptions_are_not_proof_of_exit(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=managers_fixture.ManagerTests();m=fixture.manager(d);job=m.start('test-shop',foreground=True)['taskId']
   def probe(pid):raise PermissionError('private-test-error')
   m.process_probe=probe;self.assertEqual(m.reconcile(job)['status'],'running')

class AuthHostCliTests(unittest.TestCase):
 def test_wait_flags_and_reconciliation_reach_correct_manager_methods(self):
  from heideng_merchant.cli import parser,run
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as managers:
   managers.return_value.start.return_value={'status':'completed'}
   run(parser().parse_args(['--home',d,'auth-start','--shop-name','test-shop','--foreground','--wait']))
   self.assertTrue(managers.return_value.start.call_args.kwargs['wait'])
   self.assertTrue(callable(managers.return_value.start.call_args.kwargs['progress']))
   managers.return_value.reconcile.return_value={'status':'failed'}
   run(parser().parse_args(['--home',d,'auth-reconcile','--task-id','a'*24]))
   managers.return_value.reconcile.assert_called_once_with('a'*24)
 def test_login_guidance_matches_homepage_and_requires_workbench_return(self):
  from heideng_merchant.auth_broker import public_status
  result=public_status({'taskId':'a'*24,'stage':'waiting_login','status':'running'})
  self.assertIn('点击',result['userAction']);self.assertIn('登录',result['userAction']);self.assertIn('京麦App',result['userAction']);self.assertIn('工作台',result['userAction'])
 def test_diagnostics_never_export_private_exception_or_page_fields(self):
  from heideng_merchant.auth_lifecycle import record_event
  with tempfile.TemporaryDirectory() as d:
   for _ in range(70):record_event(Path(d),'a'*24,'flow-stage',{'stage':'waiting_login','status':'running','token':'private-test-token','reason':'private-test-body','url':'https://private/?state=test'})
   raw=(Path(d)/'auth'/'events'/('a'*24+'.json')).read_text()
   self.assertNotIn('private-test',raw);self.assertNotIn('state=test',raw);self.assertEqual(len(json.loads(raw)),64)

class AuthHotfixVersionTests(unittest.TestCase):
 def test_patch_is_new_installable_version_not_changed_same_version(self):
  from heideng_merchant import VERSION
  from heideng_merchant.catalog import load_catalog
  self.assertEqual(VERSION,'0.1.1');self.assertEqual(load_catalog()['version'],VERSION)
