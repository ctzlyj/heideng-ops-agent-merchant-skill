"""Real mature driver paths/policies and dynamic fallback stay isolated, no live source requests."""
import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.mature_runtime import collection_environment,child_environment
ROOT=Path(__file__).resolve().parents[1];BATCH=ROOT/'mature/collection/scripts/batch_driver'
class MatureDriverTests(unittest.TestCase):
 def test_driver_uses_explicit_output_not_new_state_parent(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d)/'merchant';out=Path(d)/'output';env=collection_environment(home,['--root',str(out)],child_environment(home))
   self.assertEqual(env['HEIDENG_COLLECTION_ROOT'],str(out.resolve()))
   self.assertNotEqual(Path(env['HEIDENG_COLLECTION_STATE_DIR']).parent,out.resolve())
   old=sys.path[:];sys.path.insert(0,str(BATCH))
   try:
    with patch.dict(os.environ,env,clear=True):
     spec=importlib.util.spec_from_file_location('original_batch_driver_test',BATCH/'batch_driver.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
     actual,stage,scripts=m.task_paths()
     self.assertEqual(actual,out.resolve());self.assertEqual(stage,Path(env['HEIDENG_COLLECTION_STATE_DIR']));self.assertEqual(scripts,BATCH.parent)
   finally:sys.path[:]=old
 def test_inherited_old_original_price_flag_is_not_merchant_authorization(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'JD_BATCH_ORIGINAL_PRICE_FALLBACK':'1'}):
   env=collection_environment(Path(d),['--root',str(Path(d)/'output')],child_environment(Path(d)))
   self.assertNotEqual(env.get('JD_BATCH_ORIGINAL_PRICE_FALLBACK'),'1')
 def test_fallback_wrapper_uses_only_existing_dynamic_batch_marker(self):
  from types import SimpleNamespace
  spec=importlib.util.spec_from_file_location('original_fallback_test',BATCH/'original_price_fallback.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with self.assertRaisesRegex(RuntimeError,'AUTHORIZATION_REQUIRED'):m.attach_fallback(SimpleNamespace(fallback_marker=lambda:None))
  original=lambda sku:None
  self.assertIs(m.attach_fallback(SimpleNamespace(fallback_marker=lambda:'original_price_user_authorized_fixture',live_data=original)),original)
 def test_vendor_stage_pending_is_git_head_not_dirty_personal_experiment(self):
  import hashlib,subprocess
  original=Path(r'D:/UserData/.codex/skills/jd-hot-link-collector')
  if not original.exists():self.skipTest('source reference not present on this test host')
  blob=subprocess.check_output(['git','-C',str(original),'show','90ef8dfd8455848d539d22560ae26ba8bac52e2a:scripts/batch_driver/stage_pending_materials.py'])
  meta=json.loads((ROOT/'mature/collection/provenance.json').read_text(encoding='utf-8'))
  self.assertEqual(meta['files']['scripts/batch_driver/stage_pending_materials.py']['upstreamSha256'],hashlib.sha256(blob).hexdigest())
if __name__=='__main__':unittest.main()
