import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from heideng_merchant import VERSION

class InstallEntryTests(unittest.TestCase):
 def test_single_repository_installs_and_onboards_in_clean_home(self):
  with tempfile.TemporaryDirectory() as d:
   p=subprocess.run([sys.executable,'install.py','--home',d,'--host','codex','--offline'],capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr.decode('utf-8','replace'));r=json.loads(p.stdout);self.assertEqual(r['status'],'installed')
   entry=Path(d)/'.codex'/'skills'/'heideng-ops-agent-merchant'/'scripts'/'merchant.py';self.assertTrue(entry.is_file())
   result=subprocess.run([sys.executable,str(entry),'--home',d,'onboarding'],capture_output=True)
   self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['version'],VERSION)
   again=subprocess.run([sys.executable,'install.py','--home',d,'--host','codex','--offline'],capture_output=True)
   self.assertEqual(json.loads(again.stdout)['status'],'unchanged')
 def test_coexists_with_internal_sentinels(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);internal=root/'.codex'/'skills'/'heideng-ops-agent';internal.mkdir(parents=True);(internal/'SKILL.md').write_text('internal unchanged');config=root/'internal-config.txt';config.write_text('fake company sentinel')
   p=subprocess.run([sys.executable,'install.py','--home',d,'--offline'],capture_output=True)
   self.assertEqual(p.returncode,0,p.stdout.decode('utf-8','replace')+p.stderr.decode('utf-8','replace'));self.assertEqual((internal/'SKILL.md').read_text(),'internal unchanged');self.assertEqual(config.read_text(),'fake company sentinel')

if __name__=='__main__':unittest.main()
