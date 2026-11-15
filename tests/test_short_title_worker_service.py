"""Service starts only original jobs, never PID/timeout-based replacement actors."""
import importlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant import VERSION,short_title_worker_state as original
from heideng_merchant.safety import SafetyError
from tests import test_short_title_browser as fixture

class Runtime:
 def __init__(self):self.calls=0
 def ensure(self):self.calls+=1
 def python(self):return Path('synthetic-public-python')

class WorkerServiceTests(unittest.TestCase):
 def make(self,d):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.short_title_worker_service'),'merchant worker service is not implemented')
  mod=importlib.import_module('heideng_merchant.short_title_worker_service');c,s,p,f,b=fixture.ShortTitleBrowserTests().make(d);calls=[];runtime=Runtime()
  def start(args,**kwargs):calls.append((args,kwargs));return object()
  binding={'version':VERSION,'archiveSha256':'a'*64,'filesSha256':'b'*64}
  service=mod.ShortTitleWorkerService(d,client=c,runtime=runtime,starter=start,runtime_verifier=lambda:binding,startup_wait=0)
  return service,p,c,calls,runtime
 def test_start_requires_foreground_before_dependency_or_launch(self):
  with tempfile.TemporaryDirectory() as d:
   service,p,c,calls,runtime=self.make(d)
   with self.assertRaises(SafetyError):service.start(p['planId'],foreground=False)
   self.assertFalse(calls);self.assertEqual(runtime.calls,0)
 def test_duplicate_start_recovers_original_and_does_not_launch_again(self):
  with tempfile.TemporaryDirectory() as d:
   service,p,c,calls,runtime=self.make(d);first=service.start(p['planId'],foreground=True);second=service.start(p['planId'],foreground=True)
   self.assertEqual(first['workerId'],second['workerId']);self.assertEqual(first['runId'],second['runId']);self.assertEqual(len(calls),1);self.assertEqual(runtime.calls,1);self.assertFalse(first['workerReachable'])
   args,opts=calls[0];self.assertIn('--run',args);self.assertIn('-I',args);self.assertNotIn('JD_LLM_API_KEY',opts['env']);self.assertNotIn('--token',args)
   if os.name=='nt':self.assertEqual(opts['creationflags'],0x08000000)
 def test_unknown_launch_is_not_retried_or_treated_as_closed(self):
  with tempfile.TemporaryDirectory() as d:
   service,p,c,calls,runtime=self.make(d)
   def fail(*args,**kwargs):calls.append('unknown');raise OSError('synthetic-private-body')
   service.starter=fail;first=service.start(p['planId'],foreground=True);second=service.start(p['planId'],foreground=True)
   self.assertEqual(len(calls),1);self.assertEqual(second['status'],'original-worker-outcome-unconfirmed');self.assertNotIn('synthetic-private-body',json.dumps(second))
   with self.assertRaises(SafetyError):service.resume(first['workerId'])
 def test_resume_retains_original_scope_and_is_strictly_readonly(self):
  with tempfile.TemporaryDirectory() as d:
   service,p,c,calls,runtime=self.make(d);first=service.start(p['planId'],foreground=True);j=original.read_job(d,first['workerId']);r=original.read_runs(d,j)[first['runId']]
   original.finish_run(d,j,r,broker_stopped=True,browser_closed=True,guard_owned=True);resumed=service.resume(first['workerId']);new=original.read_runs(d,j)[resumed['runId']]
   self.assertTrue(new['resumeReadOnly']);self.assertEqual(resumed['workerId'],first['workerId']);self.assertEqual(len(calls),2)
   with self.assertRaises(SafetyError):service.command(first['workerId'],'execute',import_id='e'*24,fingerprint='f'*64)
 def test_default_execute_request_is_stable_after_lost_response(self):
  with tempfile.TemporaryDirectory() as d:
   from tests import test_short_title_worker_state as sf
   mod,c,j,r,root,cmd=sf.WorkerStateTests().setup(d);service=importlib.import_module('heideng_merchant.short_title_worker_service').ShortTitleWorkerService(d,client=c,runtime=Runtime(),runtime_verifier=lambda:j['scope']['runtime'],startup_wait=0)
   service.request=lambda *a,**k:(_ for _ in ()).throw(OSError('synthetic lost reply'))
   a=service.command(j['workerId'],'execute',import_id=root['importId'],fingerprint=root['fingerprint']);b=service.command(j['workerId'],'execute',import_id=root['importId'],fingerprint=root['fingerprint'])
   self.assertEqual(a['requestId'],b['requestId']);self.assertEqual(a['status'],'delivery-unknown-read-original-request');self.assertEqual(service.command_status(j['workerId'],a['requestId'])['status'],'not-found')
 def test_cli_exposes_worker_commands_without_factories_or_runtime_override(self):
  from heideng_merchant.cli import parser
  p=parser()
  try:args=p.parse_args(['short-title-worker-start','--plan-id','a'*24,'--foreground'])
  except SystemExit:self.fail('merchant CLI has no persistent worker entry')
  self.assertEqual(args.plan_id,'a'*24);self.assertTrue(args.foreground)
  with self.assertRaises(SystemExit):p.parse_args(['short-title-worker-start','--plan-id','a'*24,'--runtime-binding','synthetic'])

 def test_duplicate_start_returns_active_actor_while_actual_worker_holds_both_guards(self):
  from heideng_merchant.state import FileLock
  with tempfile.TemporaryDirectory() as d:
   service,p,c,calls,runtime=self.make(d);first=service.start(p['planId'],foreground=True)
   with FileLock(Path(d)/'short-title-worker-owner.lock',timeout=0),FileLock(Path(d)/'install.lock',timeout=0):
    second=service.start(p['planId'],foreground=True)
   self.assertEqual(second['workerId'],first['workerId']);self.assertEqual(len(calls),1)

 def test_catalog_and_agent_guide_advertise_worker_without_claiming_c3_complete(self):
  root=Path(__file__).resolve().parents[1];registry=json.loads((root/'registry.json').read_text(encoding='utf-8-sig'));cap=next(c for c in registry['capabilities'] if c['id']=='short-titles')
  self.assertTrue(cap['importCLIWorkerIntegrated']);self.assertFalse(cap['C3Complete']);self.assertIn('short-title-worker-execute',cap['builtInCommands'])
  guide=(root/cap['workerReference']).read_text(encoding='utf-8');self.assertIn('command-status',guide);self.assertIn('readonly',guide);self.assertIn('未知',guide)
