import tempfile
import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError, safe_join, clean_environment, redact, atomic_json

class SafetyTests(unittest.TestCase):
 def test_unsafe_paths(self):
  with tempfile.TemporaryDirectory() as d:
   for value in ('../outside','/root','C:/root','a\\b','a/../b','a//b','CON','a/NUL.txt','a.','a ','a/%2e%2e/b'):
    with self.subTest(value=value), self.assertRaises(SafetyError): safe_join(Path(d),value)
   self.assertEqual(safe_join(Path(d),'nested/file.json'),Path(d)/'nested'/'file.json')
 def test_link_escape(self):
  with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
   try: (Path(d)/'link').symlink_to(other,target_is_directory=True)
   except OSError: self.skipTest('symlink privilege unavailable')
   with self.assertRaises(SafetyError): safe_join(Path(d),'link/item')
 def test_environment_does_not_inherit_employee_or_models(self):
  env=clean_environment(Path('isolated'),{'PATH':'safe','SystemRoot':'C:/Windows','JD_LLM_API_KEY':'fake-employee','ARK_API_KEY':'fake-ambient','PYTHONPATH':'poison','HTTP_PROXY':'poison'})
  self.assertNotIn('JD_LLM_API_KEY',env);self.assertNotIn('ARK_API_KEY',env);self.assertNotIn('PYTHONPATH',env);self.assertNotIn('HTTP_PROXY',env)
  self.assertEqual(env['USERPROFILE'],str(Path('isolated').resolve()))
 def test_redaction(self):
  result=redact({'headers':{'Authorization':'Bearer fake-key'},'api_key':'fake-key','detail':'failed using fake-secret; Cookie: abc; token=abc'},secrets=('fake-secret',))
  self.assertNotIn('fake-key',str(result));self.assertNotIn('fake-secret',str(result));self.assertNotIn('token=abc',str(result))
 def test_atomic_json(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.json';atomic_json(p,{'state':'ready'})
   self.assertEqual(p.read_text(encoding='utf-8'),'\x7b"state":"ready"\x7d\n')

 @unittest.skipUnless(os.name=='nt','Windows junction metadata')
 def test_junction_rejected_even_without_python312_helper(self):
  import subprocess
  with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
   root=Path(d);link=root/'junction';inside=root/'inside';inside.mkdir()
   p=subprocess.run(['cmd','/c','mklink','/J',str(link),str(inside)],capture_output=True,creationflags=0x08000000)
   if p.returncode:self.skipTest('junction creation unavailable')
   try:
    with patch('pathlib.Path.is_junction',return_value=False,create=True):
     with self.assertRaises(SafetyError):safe_join(root,'junction/item')
   finally:os.rmdir(link)



class WindowsCleanEnvironmentTests(unittest.TestCase):
 def test_uppercase_os_roots_are_retained_without_credentials(self):
  if os.name!='nt':self.skipTest('Windows-specific environment convention')
  from heideng_merchant.safety import clean_environment
  with tempfile.TemporaryDirectory() as d:
   env=clean_environment(Path(d),{'SYSTEMROOT':os.environ.get('SystemRoot','C:/Windows'),'WINDIR':os.environ.get('WINDIR','C:/Windows'),'PATH':os.environ.get('PATH',''),'JD_LLM_API_KEY':'synthetic-company-marker'})
   self.assertTrue(env.get('SystemRoot'))
   self.assertNotIn('JD_LLM_API_KEY',env)
 def test_missing_os_roots_do_not_crash_native_node_rng(self):
  if os.name!='nt':self.skipTest('Windows-specific native runtime')
  import shutil,subprocess
  from heideng_merchant.safety import clean_environment
  with tempfile.TemporaryDirectory() as d:
   env=clean_environment(Path(d),{'PATH':os.environ.get('PATH','')})
   self.assertTrue(env.get('SystemRoot'))
   result=subprocess.run([shutil.which('node'),'--version'],env=env,capture_output=True,timeout=15)
   self.assertEqual(result.returncode,0,'native Node failed in minimal clean environment')

if __name__=='__main__':unittest.main()
