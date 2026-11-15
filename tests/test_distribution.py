import io,json,tempfile,unittest,zipfile
from pathlib import Path
from heideng_merchant.distribution import build_bundle,install_archive,rollback,verify_install
from heideng_merchant.safety import SafetyError,file_sha

class DistributionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'source';self.src.mkdir()
  (self.src/'SKILL.md').write_text('---\nname: heideng-ops-agent-merchant\n---\nmerchant',encoding='utf-8')
  (self.src/'VERSION').write_text('0.1.0');(self.src/'heideng_merchant').mkdir();(self.src/'heideng_merchant'/'__init__.py').write_text('VERSION="0.1.0"')
  self.target=self.root/'skills'/'heideng-ops-agent-merchant';self.state=self.root/'state'
 def tearDown(self):self.tmp.cleanup()
 def bundle(self,version='0.1.0'):
  (self.src/'VERSION').write_text(version);return build_bundle(self.src,self.root/(version+'.zip'),version)
 def install(self,archive):return install_archive(archive,self.target,self.state,expected_sha=file_sha(archive))
 def test_fresh_and_idempotent(self):
  bundle=self.bundle();self.assertEqual(self.install(bundle)['status'],'installed');self.assertEqual(self.install(bundle)['status'],'unchanged');self.assertTrue(verify_install(self.target)['valid'])
 def test_unrelated_directory_preserved(self):
  self.target.mkdir(parents=True);(self.target/'keep.txt').write_text('private')
  with self.assertRaises(SafetyError):self.install(self.bundle())
  self.assertEqual((self.target/'keep.txt').read_text(),'private')
 def test_wrong_destination(self):
  with self.assertRaises(SafetyError):install_archive(self.bundle(),self.root/'skills'/'heideng-ops-agent',self.state,expected_sha=file_sha(self.bundle()))
 def test_modified_install_never_overwritten(self):
  self.install(self.bundle());(self.target/'SKILL.md').write_text('user edits')
  with self.assertRaises(SafetyError):self.install(self.bundle('0.2.0'))
  self.assertEqual((self.target/'SKILL.md').read_text(),'user edits')
 def test_upgrade_and_rollback(self):
  self.install(self.bundle());self.install(self.bundle('0.2.0'))
  self.assertEqual(rollback(self.target,self.state)['version'],'0.1.0')
  self.assertEqual((self.target/'VERSION').read_text(),'0.1.0')
 def test_no_downgrade(self):
  self.install(self.bundle('0.2.0'))
  with self.assertRaises(SafetyError):self.install(self.bundle('0.1.0'))
 def test_hash_mismatch(self):
  with self.assertRaises(SafetyError):install_archive(self.bundle(),self.target,self.state,expected_sha='0'*64)
 def test_unsafe_members_rejected_even_if_not_used(self):
  for member in ('../escape','A/../escape','C:/escape','a\\b','CON.txt'):
   with self.subTest(member=member):
    raw=self.root/'evil.zip'
    with zipfile.ZipFile(raw,'w') as z:z.writestr(member,'bad')
    with self.assertRaises(SafetyError):self.install(raw)
 def test_case_collision(self):
  raw=self.root/'duplicate.zip'
  with zipfile.ZipFile(raw,'w') as z:z.writestr('a.txt','1');z.writestr('A.txt','2')
  with self.assertRaises(SafetyError):self.install(raw)
 def test_active_task_defers_upgrade(self):
  self.install(self.bundle());(self.state/'tasks').mkdir();(self.state/'tasks'/'job.json').write_text('{"status":"unknown"}')
  with self.assertRaises(SafetyError):self.install(self.bundle('0.2.0'))

 def test_unknown_runtime_file_rejected_even_with_valid_manifest(self):
  import hashlib
  archive=self.bundle();files={}
  with zipfile.ZipFile(archive) as z:
   for name in z.namelist():files[name]=z.read(name)
  manifest=json.loads(files['package-manifest.json']);files['employee.env']=b'fake-only';manifest['files']['employee.env']=hashlib.sha256(files['employee.env']).hexdigest();files['package-manifest.json']=json.dumps(manifest).encode()
  with zipfile.ZipFile(archive,'w') as z:
   for name,raw in files.items():z.writestr(name,raw)
  with self.assertRaises(SafetyError):self.install(archive)

 def test_source_line_endings_have_identical_release(self):
  for p in self.src.rglob('*'):
   if p.is_file():p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
  first=self.bundle();before=file_sha(first)
  for p in self.src.rglob('*'):
   if p.is_file():p.write_bytes(p.read_bytes().replace(b'\n',b'\r\n'))
  second=self.bundle();self.assertEqual(file_sha(second),before)

class DirectorySwitchRetryTests(unittest.TestCase):
 setUp=DistributionTests.setUp
 tearDown=DistributionTests.tearDown
 bundle=DistributionTests.bundle
 install=DistributionTests.install
 # Limit inherited cases: these are focused recovery regressions, not a second suite.
 def test_transient_windows_stage_denial_is_retried(self):
  import os
  from unittest.mock import patch
  original=os.replace;calls=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-'):
    calls.append(1)
    if len(calls)==1:
     error=PermissionError(13,'synthetic sharing denial');error.winerror=5;raise error
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace):result=self.install(self.bundle())
  self.assertEqual(result['status'],'installed');self.assertEqual(len(calls),2);self.assertTrue(verify_install(self.target)['valid'])
 def test_persistent_windows_stage_denial_is_bounded_and_keeps_journal(self):
  import os
  from unittest.mock import patch
  original=os.replace;calls=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-'):
    calls.append(1);error=PermissionError(13,'synthetic permanent denial');error.winerror=5;raise error
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace),patch('time.sleep'):
   with self.assertRaisesRegex(SafetyError,'install-switch-failed-recoverable'):self.install(self.bundle())
  self.assertEqual(len(calls),6);self.assertFalse(self.target.exists());journal=json.loads((self.state/'install-journal.json').read_text());self.assertTrue(Path(journal['stage']).is_dir())
 def test_non_windows_access_denial_is_not_retried(self):
  import os
  from unittest.mock import patch
  original=os.replace;calls=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-'):calls.append(1);raise PermissionError(13,'synthetic POSIX denial')
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace):
   with self.assertRaisesRegex(SafetyError,'install-switch-failed-recoverable'):self.install(self.bundle())
  self.assertEqual(len(calls),1)
 def test_destination_created_during_denial_is_never_overwritten(self):
  import os
  from unittest.mock import patch
  original=os.replace;calls=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-'):
    calls.append(1);Path(dst).mkdir();(Path(dst)/'unrelated.txt').write_text('preserve')
    error=PermissionError(13,'synthetic sharing denial');error.winerror=5;raise error
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace):
   with self.assertRaises(SafetyError):self.install(self.bundle())
  self.assertEqual(len(calls),1);self.assertEqual((self.target/'unrelated.txt').read_text(),'preserve')
 def test_source_replaced_during_denial_is_never_installed(self):
  import os
  from unittest.mock import patch
  original=os.replace;calls=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-'):
    calls.append(1);old=Path(src);old.rename(old.with_name(old.name+'-displaced'));old.mkdir();(old/'unrelated.txt').write_text('preserve')
    error=PermissionError(13,'synthetic sharing denial');error.winerror=5;raise error
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace):
   with self.assertRaises(SafetyError):self.install(self.bundle())
  self.assertEqual(len(calls),1);self.assertFalse(self.target.exists())
 def test_upgrade_and_rollback_retry_only_owned_directory_switches(self):
  import os
  from unittest.mock import patch
  self.install(self.bundle());original=os.replace;calls={}
  def replace(src,dst):
   src=Path(src);dst=Path(dst)
   if src.is_dir():
    key=(str(src),str(dst));calls[key]=calls.get(key,0)+1
    if calls[key]==1:
     error=PermissionError(13,'synthetic sharing denial');error.winerror=32;raise error
   return original(src,dst)
  with patch('heideng_merchant.distribution.os.replace',side_effect=replace):
   self.install(self.bundle('0.2.0'));self.assertEqual(rollback(self.target,self.state)['version'],'0.1.0')
  self.assertEqual(len(calls),4);self.assertEqual(set(calls.values()),{2});self.assertTrue(verify_install(self.target)['valid'])
 def test_real_windows_no_share_delete_handle_is_released_then_install_succeeds(self):
  import os
  if os.name!='nt':self.skipTest('native Windows handle test')
  import ctypes,threading
  from ctypes import wintypes
  from unittest.mock import patch
  k=ctypes.WinDLL('kernel32',use_last_error=True);k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];k.CreateFileW.restype=wintypes.HANDLE;k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
  original=os.replace;held=[];timers=[]
  def replace(src,dst):
   if Path(src).name.startswith('.heideng-ops-agent-merchant.stage-') and not held:
    handle=k.CreateFileW(str(Path(src)/'SKILL.md'),0x80000000,1,None,3,0,None);self.assertNotEqual(handle,wintypes.HANDLE(-1).value);held.append(handle)
    timer=threading.Timer(.12,lambda:k.CloseHandle(handle));timers.append(timer);timer.start()
   return original(src,dst)
  try:
   with patch('heideng_merchant.distribution.os.replace',side_effect=replace):result=self.install(self.bundle())
  finally:
   for timer in timers:timer.join()
  self.assertEqual(result['status'],'installed');self.assertTrue(verify_install(self.target)['valid'])

if __name__=='__main__':unittest.main()

class IsolatedInstallerTests(unittest.TestCase):
 def test_install_works_in_python_isolated_mode_with_clean_home(self):
  import subprocess,sys
  from heideng_merchant.safety import clean_environment
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   process=subprocess.run([sys.executable,'-I',str(root/'install.py'),'--offline','--home',d],env=clean_environment(Path(d)),capture_output=True,timeout=60)
   self.assertEqual(process.returncode,0,process.stderr.decode('utf-8','replace'))
   result=json.loads(process.stdout);self.assertFalse(result['employeeDependencies']);self.assertTrue((Path(d)/'.codex'/'skills'/'heideng-ops-agent-merchant'/'SKILL.md').is_file())
