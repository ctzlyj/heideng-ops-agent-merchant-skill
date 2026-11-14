import hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import atomic_json,SafetyError

class AuthNativeTests(unittest.TestCase):
 def client(self,root):
  client=OfficialClient(Path(root),platform_name='windows-x64');binary=Path(root)/'tools'/'stub'/'bin'/'jdo-cli.exe';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake executable')
  atomic_json(client.receipt_path,{'version':'0.3.7','root':'tools/stub','executable':'bin/jdo-cli.exe','executableSha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
  return client
 def test_login_arguments_and_native_store_namespace(self):
  calls=[]
  def popen(args,**kwargs):calls.append((args,kwargs));return object()
  with tempfile.TemporaryDirectory() as d:
   c=self.client(d)
   with patch('subprocess.Popen',side_effect=popen):c.login_process('merchant-native-a1','测试店','1')
   args,kw=calls[0];self.assertIn('--no-browser',args);self.assertIn('--vender-id',args);self.assertNotIn('--force',args);self.assertNotIn('--app-secret',args);self.assertNotIn('--code',args)
   self.assertEqual(kw['env']['JDO_CREDENTIAL_BACKEND'],'windows-credential-manager');self.assertEqual(kw['env']['JDO_CLI_HOME'],str(Path(d)/'cli-home'/'.jdo-cli'));self.assertNotIn('JD_LLM_API_KEY',kw['env']);self.assertNotIn('JDO_ACCESS_TOKEN',kw['env'])
 def test_login_never_uses_default_or_legacy_namespace(self):
  with tempfile.TemporaryDirectory() as d:
   c=self.client(d)
   for profile in ('default','legacy-shop'):
    with self.assertRaises(SafetyError):c.login_process(profile,'测试店','1')
 def test_native_initialize_can_bind_observed_identity_metadata(self):
  calls=[]
  class Result:
   returncode=0;stdout=b'{"ok":true}';stderr=b''
  with tempfile.TemporaryDirectory() as d:
   c=self.client(d);c.runner=lambda args,**kw:(calls.append((args,kw)) or Result());c.initialize('merchant-native-a1',vender_id='1',shop_name='测试店')
   self.assertIn('--vender-id',calls[0][0]);self.assertIn('--shop-name',calls[0][0]);self.assertEqual(calls[0][1]['env']['JDO_CREDENTIAL_BACKEND'],'windows-credential-manager')

if __name__=='__main__':unittest.main()

class AuthCleanupTests(unittest.TestCase):
 def test_cleanup_stops_only_owned_process_tree(self):
  import subprocess,sys
  import psutil
  child_code='import time; time.sleep(60)'
  parent_code='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c",'+repr(child_code)+']); print(p.pid,flush=True); time.sleep(60)'
  owned=subprocess.Popen([sys.executable,'-c',parent_code],stdout=subprocess.PIPE)
  other=subprocess.Popen([sys.executable,'-c',child_code])
  try:
   child_pid=int(owned.stdout.readline());child=psutil.Process(child_pid)
   with tempfile.TemporaryDirectory() as d:OfficialClient(Path(d)).stop_login(owned)
   self.assertIsNotNone(owned.poll());self.assertFalse(child.is_running());self.assertIsNone(other.poll())
  finally:
   for process in (owned,other):
    if process.poll() is None:process.terminate()
    process.wait(timeout=5)
   owned.stdout.close()
   if child.is_running():child.terminate();child.wait(timeout=5)
 def test_macos_auth_refuses_upstream_secret_argv_backend(self):
  with tempfile.TemporaryDirectory() as d:
   c=AuthNativeTests.client(self,d);c.platform_name='macos-arm64'
   with patch('subprocess.Popen') as launch:
    with self.assertRaisesRegex(SafetyError,'secret-argv'):c.login_process('merchant-native-a1','测试店','1')
    launch.assert_not_called()
