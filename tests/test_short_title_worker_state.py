"""Worker originals, single dispatch and verified install bindings; synthetic only."""
import importlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from tests import test_short_title_browser as fixture
from heideng_merchant.distribution import build_bundle,install_archive
from heideng_merchant import VERSION,SKILL_NAME

class WorkerStateTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.short_title_worker_state'),'worker originals not implemented')
  return importlib.import_module('heideng_merchant.short_title_worker_state')
 def setup(self,d):
  c,s,p,f,b=fixture.ShortTitleBrowserTests().make(d);mod=self.module();binding={'version':VERSION,'archiveSha256':'a'*64,'filesSha256':'b'*64}
  job=mod.create_job(d,p['planId'],c,binding,source_id=b.session_id,foreground=True)
  b.open();source=b.capture();b.close()
  from heideng_merchant.short_title_imports import ShortTitleImports
  m=ShortTitleImports(d,c,clock=lambda:1000);root=m.prepare(p['planId'],source['sourceId']);mod.link_root(d,job,root['importId'],c);run=mod.begin_run(d,job)
  command={'requestId':'c'*32,'action':'execute','importId':root['importId'],'fingerprint':root['fingerprint'],'confirmed':False,'ttl':900}
  return mod,c,job,run,root,command
 def test_job_and_original_root_bind_plan_shop_source_and_runtime(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,job,run,root,cmd=self.setup(d);loaded=mod.read_job(d,job['workerId']);link=mod.read_link(d,job,c)
   self.assertEqual(loaded,job);self.assertEqual(link['fingerprint'],root['fingerprint']);self.assertEqual(job['scope']['shop']['profile'],'merchant-test')
   self.assertEqual(job['scope']['runtime']['archiveSha256'],'a'*64);self.assertFalse(c.posts)
 def test_command_same_id_same_body_recovered_changed_body_refused(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);first=mod.accept_command(d,j,run,cmd);self.assertEqual(mod.accept_command(d,j,run,cmd),first)
   changed={**cmd,'action':'effects'}
   with self.assertRaises(SafetyError):mod.accept_command(d,j,run,changed)
   self.assertEqual(mod.command_status(d,j,cmd['requestId'])['status'],'accepted-not-dispatched')
 def test_dispatch_before_result_is_unknown_and_never_dispatched_twice(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);a=mod.accept_command(d,j,run,cmd);dispatch=mod.dispatch_command(d,j,run,a)
   self.assertEqual(mod.command_status(d,j,cmd['requestId'])['status'],'original-command-outcome-unknown')
   with self.assertRaises(SafetyError):mod.dispatch_command(d,j,run,a)
   mod.write_result(d,j,run,a,dispatch,{'status':'submitted-awaiting-verification','imported':False})
   self.assertTrue(mod.command_status(d,j,cmd['requestId'])['historicalResult']);self.assertFalse(c.posts)
 def test_wrong_root_private_controls_or_unconfirmed_approval_refused(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d)
   for patch in ({'fingerprint':'0'*64},{'importId':'0'*24},{'token':'SYNTHETIC_ONLY'},{'action':'approve'},{'ttl':True}):
    with self.subTest(patch=patch),self.assertRaises(SafetyError):mod.accept_command(d,j,run,{**cmd,**patch})
 def test_active_run_or_unknown_launch_never_creates_replacement_run(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d)
   with self.assertRaises(SafetyError):mod.begin_run(d,j,resume=True)
   self.assertEqual(len(mod.read_runs(d,j)),1)
 def test_confirmed_local_stop_allows_only_original_readonly_resume(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);mod.finish_run(d,j,run,broker_stopped=True,browser_closed=True,guard_owned=True)
   resumed=mod.begin_run(d,j,resume=True);self.assertTrue(resumed['resumeReadOnly'])
   with self.assertRaises(SafetyError):mod.accept_command(d,j,resumed,cmd)
   mod.accept_command(d,j,resumed,{**cmd,'action':'recover'})
 def test_root_or_closed_command_original_corruption_blocks_resume(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);a=mod.accept_command(d,j,run,cmd);mod.finish_run(d,j,run,broker_stopped=True,browser_closed=True,guard_owned=True)
   file=Path(d)/'short-title-worker-commands'/j['workerId']/(cmd['requestId']+'.json');atomic_json(file,{})
   with self.assertRaises(SafetyError):mod.begin_run(d,j,resume=True)
 def test_managed_runtime_binding_validates_all_installed_files(self):
  mod=self.module();root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);archive=build_bundle(root,home/'package.zip',VERSION)
   import hashlib
   target=home/'.codex/skills'/SKILL_NAME;install_archive(archive,target,home/'.heideng-merchant',expected_sha=hashlib.sha256(archive.read_bytes()).hexdigest())
   binding=mod.runtime_binding(target);self.assertEqual(binding['version'],VERSION)
   (target/'heideng_merchant/short_title_browser.py').write_text('# synthetic local edit')
   with self.assertRaises(SafetyError):mod.runtime_binding(target)

 def test_changed_closed_original_cannot_remove_a_command_from_proof(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);mod.accept_command(d,j,run,cmd);mod.finish_run(d,j,run,broker_stopped=True,browser_closed=True,guard_owned=True)
   file=Path(d)/'short-title-worker-closed'/j['workerId']/(run['runId']+'.json');closed=read_json(file);closed['footprints'].pop('short-title-worker-commands/'+j['workerId']+'/'+cmd['requestId']+'.json');atomic_json(file,closed)
   with self.assertRaises(SafetyError):mod.begin_run(d,j,resume=True)
 def test_closed_worker_preserves_native_attempt_prefix_before_resume(self):
  import shutil
  from heideng_merchant.short_title_imports import ShortTitleImports
  from heideng_merchant.short_title_import_browser import ShortTitleImportBrowser
  from tests.short_title_import_fixtures import ImportFactory
  with tempfile.TemporaryDirectory() as d:
   from heideng_merchant.state import FileLock
   from heideng_merchant.short_title_worker_gate import WorkerWitness,claim_record,CLAIMS
   mod,c,j,run,root,cmd=self.setup(d);m=ShortTitleImports(d,c,clock=lambda:1000);factory=ImportFactory(d)
   with FileLock(Path(d)/'short-title-worker-owner.lock',timeout=0) as owner, FileLock(Path(d)/'install.lock',timeout=0) as guard:
    atomic_json(mod.file(d,CLAIMS,j['workerId'],run['runId']),claim_record(j,run))
    m.plans.ops.worker_witness=WorkerWitness(d,j,run,owner,guard,lambda:j['scope']['runtime'])
    b=ShortTitleImportBrowser(m,root['importId'],factory=lambda:factory,headless=True);b.open(install_guard=guard)
    try:m.approve(root['importId'],root['fingerprint'],confirmed=True);m.execute(root['importId'],b)
    finally:b.close()
    mod.finish_run(d,j,run,broker_stopped=True,browser_closed=True,guard_owned=True)
   for folder in ('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors'):
    target=(Path(d)/folder/root['importId']).resolve();target.relative_to(Path(d).resolve())
    if target.exists():shutil.rmtree(target)
   with self.assertRaises(SafetyError):mod.begin_run(d,j,resume=True)
 def test_orphan_dispatch_cannot_be_declared_a_valid_closed_run(self):
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,cmd=self.setup(d);atomic_json(Path(d)/'short-title-worker-dispatches'/j['workerId']/('d'*32+'.json'),{})
   with self.assertRaises(SafetyError):mod.finish_run(d,j,run,broker_stopped=True,browser_closed=True,guard_owned=True)

 def test_bounded_large_metadata_is_read_whole_not_truncated(self):
  with tempfile.TemporaryDirectory() as d:
   mod=self.module();p=Path(d)/'synthetic-large.json';value={'synthetic':'x'*(2*1024*1024)};p.write_text(json.dumps(value),encoding='utf-8')
   self.assertEqual(mod._read(p),value)
   p.write_bytes(b' '*(16*1024*1024+1))
   with self.assertRaises(SafetyError):mod._read(p)

if __name__=='__main__':unittest.main(verbosity=2)
