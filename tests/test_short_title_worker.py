"""Owning-thread lifecycle with only synthetic native browser/client factories."""
import importlib,importlib.util,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant import VERSION,short_title_worker_state as original
from heideng_merchant.safety import SafetyError,read_json
from tests import test_short_title_browser as fixture
from tests.short_title_import_fixtures import ImportFactory

class WorkerLifecycleTests(unittest.TestCase):
 def make(self,d,tick=None):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.short_title_worker'),'owning-thread worker is not implemented')
  mod=importlib.import_module('heideng_merchant.short_title_worker')
  c,s,p,source,b=fixture.ShortTitleBrowserTests().make(d);binding={'version':VERSION,'archiveSha256':'a'*64,'filesSha256':'b'*64}
  j=original.create_job(d,p['planId'],c,binding,source_id=b.session_id);run=original.begin_run(d,j);native=ImportFactory(d)
  w=mod.ShortTitleWorker(d,j['workerId'],run['runId'],client=c,source_factory=lambda:source,import_factory=lambda:native,clock=lambda:1000,runtime_verifier=lambda:binding,headless=True)
  if tick:
   old=native.driver.context.new_page
   def page():
    out=old();out.wait_for_timeout=lambda n:tick(w);return out
   native.driver.context.new_page=page
  return w,c,j,run,source,native
 def command(self,w,action,rid):
  link=original.read_link(w.state,w.job)
  return {'requestId':rid*32,'action':action,'importId':link['importId'] if link else None,'fingerprint':link['fingerprint'] if link else None,'confirmed':action=='approve','ttl':900}
 def test_start_is_readonly_and_stop_closes_guard_and_original_resources(self):
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,lambda w:w.broker.submit(self.command(w,'stop','f')))
   out=w.run();self.assertEqual(out['status'],'closed');self.assertFalse(c.posts);self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(0,0))
   self.assertTrue(source.driver.context.closed);self.assertTrue(native.driver.context.closed);self.assertFalse(w.install_guard.acquired)
   self.assertEqual(original.command_status(d,j,'f'*32)['status'],'completed');original.begin_run(d,j,resume=True)
 def test_explicit_approval_and_execute_once_on_owner_thread(self):
  actions=iter([('approve','a'),('execute','b'),('stop','f')]);threads=[]
  def tick(w):
   threads.append(threading.get_ident());a,rid=next(actions);w.broker.submit(self.command(w,a,rid))
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,tick);owner=threading.get_ident();out=w.run()
   self.assertEqual(out['status'],'closed');self.assertEqual(set(threads),{owner});self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(1,1))
   self.assertEqual(original.command_status(d,j,'b'*32)['status'],'completed');self.assertFalse(original.command_status(d,j,'b'*32)['result']['imported']);self.assertFalse(c.posts)
 def test_claimed_original_actor_cannot_launch_again_even_after_local_close(self):
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,lambda w:w.broker.submit(self.command(w,'stop','f')));w.run()
   with self.assertRaises(SafetyError):w.run()
   self.assertEqual(len(source.driver.launches),1);self.assertEqual(len(native.driver.launches),1)
 def test_lost_result_never_reexecutes_and_readonly_resume_cannot_approve(self):
  actions=iter([('approve','a'),('execute','b')])
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,lambda w:w.broker.submit(self.command(w,*next(actions))))
   real=original.write_result
   def lost(state,job,run,accepted,dispatch,result):
    if accepted['command']['action']=='execute':raise OSError('synthetic result delivery lost')
    return real(state,job,run,accepted,dispatch,result)
   with patch('heideng_merchant.short_title_worker.original.write_result',side_effect=lost),self.assertRaises(SafetyError):w.run()
   self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(1,1));self.assertEqual(original.command_status(d,j,'b'*32)['status'],'original-command-outcome-unknown')
   resume=original.begin_run(d,j,resume=True)
   with self.assertRaises(SafetyError):original.accept_command(d,j,resume,self.command(w,'approve','d'))
 def test_stop_while_scanning_does_not_capture_or_reload(self):
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d);old=source.driver.context.new_page
   def page():
    out=old();out.identities=[];out.wait_for_timeout=lambda n:w.broker.submit(self.command(w,'stop','f'));return out
   source.driver.context.new_page=page;w.run();self.assertIsNone(original.read_link(d,j));self.assertEqual(len(source.driver.context.page.urls),1);self.assertFalse(native.driver.launches)
 def test_runtime_change_blocks_native_command_before_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   def tick(w):
    w.broker.submit(self.command(w,'approve','a'));w.runtime_verifier=lambda:{'version':VERSION,'archiveSha256':'c'*64,'filesSha256':'d'*64}
   w,c,j,r,source,native=self.make(d,tick)
   with self.assertRaises(SafetyError):w.run()
   self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(0,0));self.assertEqual(original.command_status(d,j,'a'*32)['status'],'accepted-not-dispatched')
 def test_unknown_browser_close_never_confirms_worker_closed(self):
  with tempfile.TemporaryDirectory() as d:
   def tick(w):
    native.driver.context.fail_close=True;w.broker.submit(self.command(w,'stop','f'))
   w,c,j,r,source,native=self.make(d,tick)
   with self.assertRaises(SafetyError):w.run()
   self.assertFalse(original.file(d,'short-title-worker-closed',j['workerId'],r['runId']).exists())
   with self.assertRaises(SafetyError):original.begin_run(d,j,resume=True)
   self.assertTrue(w.install_guard.acquired);native.driver.context.fail_close=False;w.close()

 def test_durable_actor_claim_refuses_fresh_instance_even_before_browser_launch(self):
  from heideng_merchant.short_title_worker_gate import CLAIMS,claim_record
  from heideng_merchant.safety import atomic_json
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,lambda w:w.broker.submit(self.command(w,'stop','f')))
   atomic_json(original.file(d,CLAIMS,j['workerId'],r['runId']),claim_record(j,r))
   with self.assertRaises(SafetyError):w.run()
   self.assertFalse(source.driver.launches);self.assertFalse(native.driver.launches)
 def test_changed_closed_endpoint_cannot_make_resume_safe(self):
  from heideng_merchant.short_title_worker_gate import ENDPOINTS
  from heideng_merchant.safety import atomic_json
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,lambda w:w.broker.submit(self.command(w,'stop','f')));w.run()
   path=original.file(d,ENDPOINTS,j['workerId'],r['runId']);value=read_json(path);value['port']=12345 if value['port']!=12345 else 12346;atomic_json(path,value)
   with self.assertRaises(SafetyError):original.begin_run(d,j,resume=True)

 def test_erased_active_native_prefix_cannot_reupload_with_new_execute_id(self):
  def tick(w):
   index=len(actions);action,rid=[('approve','a'),('execute','b'),('execute','c')][index];actions.append(action)
   if index==2:
    root=original.read_link(w.state,w.job)
    for folder in ('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors'):
     directory=Path(w.state)/folder/root['importId']
     for path in directory.glob('*.json'):path.unlink()
   w.broker.submit(self.command(w,action,rid))
  actions=[]
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,tick)
   try:
    with self.assertRaises(SafetyError):w.run()
    self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(1,1))
   finally:
    # Do not fabricate closure after evidence loss; release test-only handles.
    if w.browser is not None:w.browser.close();w.browser=None
    for guard in (w.install_guard,w.owner_guard):
     if guard.acquired:guard.__exit__(None,None,None)

 def test_owner_validation_waits_for_admission_commit_not_empty_half_record(self):
  opened=threading.Event();release=threading.Event();validation_errors=[];once=original._once;started=[False]
  def paused(path,value):
   if 'short-title-worker-commands' not in path.parts:return once(path,value)
   import json,os
   path.parent.mkdir(parents=True,exist_ok=True)
   with path.open('x',encoding='utf-8') as f:
    opened.set();release.wait(3);f.write(json.dumps(value));f.flush();os.fsync(f.fileno())
  def tick(w):
   if started[0]:w.broker.submit(self.command(w,'stop','f'));return
   started[0]=True;command=self.command(w,'approve','a');publisher=threading.Thread(target=lambda:w.broker.submit(command));publisher.start();self.assertTrue(opened.wait(3))
   timer=threading.Timer(.1,release.set);timer.start()
   try:w._validate_action()
   except SafetyError as e:validation_errors.append(e)
   finally:release.set();publisher.join(3);timer.join(3)
  with tempfile.TemporaryDirectory() as d:
   w,c,j,r,source,native=self.make(d,tick)
   with patch('heideng_merchant.short_title_worker_state._once',side_effect=paused):w.run()
   self.assertFalse(validation_errors);self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(0,0))
