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

if __name__=='__main__':unittest.main()
