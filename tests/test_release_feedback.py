"""JoyCode HD-006 release/installer regressions; temporary homes only."""
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import install
from heideng_merchant import VERSION,SKILL_NAME
from heideng_merchant.distribution import build_bundle,verify_install,version_key
from heideng_merchant.safety import file_sha
from heideng_merchant.state import merchant_home

class ReleaseFeedbackTests(unittest.TestCase):
 def bundle(self,root,label,version='0.1.1'):
  source=root/label;source.mkdir()
  (source/'SKILL.md').write_text('---\nname: '+SKILL_NAME+'\nversion: '+version+'\n---\n'+label,encoding='utf-8')
  (source/'VERSION').write_text(version,encoding='utf-8')
  return build_bundle(source,root/(label+'.zip'),version)
 def execute(self,home,archive=None):
  args=['--home',str(home),'--host','joycode','--offline']
  if archive:args+=['--archive',str(archive),'--sha256',file_sha(archive)]
  out=io.StringIO()
  with contextlib.redirect_stdout(out):code=install.main(args)
  return code,json.loads(out.getvalue())
 def test_new_development_source_upgrades_011_directly_without_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old=self.bundle(root,'old');home=root/'home'
   self.assertEqual(self.execute(home,old)[0],0)
   state=merchant_home(str(home));sentinel=state/'synthetic-user-state.txt';sentinel.write_text('preserve-local-state',encoding='utf-8')
   with patch('install.rollback',side_effect=AssertionError('upgrade must not rollback')):
    code,result=self.execute(home)
   self.assertEqual(code,0,result);self.assertGreater(version_key(VERSION),version_key('0.1.1'))
   target=install.target_directory('joycode',home=home)
   self.assertEqual(result['version'],VERSION);self.assertTrue(verify_install(target)['valid'])
   self.assertEqual(sentinel.read_text(),'preserve-local-state')
   code,again=self.execute(home);self.assertEqual(code,0,again);self.assertEqual(again['status'],'unchanged')
 def test_same_version_stays_blocked_with_actionable_no_rollback_guidance(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old=self.bundle(root,'original');changed=self.bundle(root,'changed');home=root/'home'
   self.assertEqual(self.execute(home,old)[0],0)
   target=install.target_directory('joycode',home=home);before=file_sha(target/'.merchant-install.json')
   with patch('install.rollback',side_effect=AssertionError('blocked install must not rollback')):
    code,result=self.execute(home,changed)
   self.assertEqual(code,2);self.assertEqual(result['error'],'same-version-different-artifact')
   self.assertEqual(result['updateAction'],'obtain-newer-version')
   self.assertIs(result['sameVersionReplacementAllowed'],False);self.assertIs(result['rollbackRequired'],False)
   self.assertIn('版本',result['guidance']);self.assertEqual(file_sha(target/'.merchant-install.json'),before)
 def test_current_version_metadata_is_consistent_and_newer_than_reported_source(self):
  root=Path(__file__).resolve().parents[1]
  self.assertGreater(version_key(VERSION),version_key('0.1.1'))
  self.assertEqual((root/'VERSION').read_text().strip(),VERSION)
  self.assertEqual(json.loads((root/'registry.json').read_text(encoding='utf-8'))['version'],VERSION)
  self.assertIn('version: '+VERSION,(root/'SKILL.md').read_text(encoding='utf-8'))
