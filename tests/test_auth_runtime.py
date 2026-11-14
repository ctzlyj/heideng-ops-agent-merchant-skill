import json,os,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_runtime import BrowserRuntime
from heideng_merchant.safety import SafetyError

class RuntimeTests(unittest.TestCase):
 def runner(self,calls):
  class Result:
   returncode=0;stdout=b'{"playwright":"1.2.3","psutil":"1.2.3"}';stderr=b''
  def run(args,**kwargs):
   calls.append((args,kwargs))
   if 'venv' in args:
    dest=Path(args[-1]);python=dest/('Scripts/python.exe' if os.name=='nt' else 'bin/python');python.parent.mkdir(parents=True);python.write_bytes(b'fake python')
   return Result()
  return run
 def test_public_isolated_runtime_and_receipt(self):
  calls=[];urls=[]
  def metadata(url):urls.append(url);return {'info':{'version':'1.2.3','license':'test-only'}}
  with tempfile.TemporaryDirectory() as d:
   runtime=BrowserRuntime(Path(d),runner=self.runner(calls),metadata=metadata);r=runtime.ensure();self.assertEqual(r['status'],'ready');self.assertTrue(all(u.startswith('https://pypi.org/pypi/') for u in urls));self.assertTrue(all('JD_LLM_API_KEY' not in opts['env'] for _,opts in calls));self.assertTrue(any('--isolated' in args and '--index-url' in args for args,_ in calls));self.assertEqual(runtime.ensure()['status'],'ready')
 def test_failed_install_is_not_ready(self):
  class Result:returncode=1;stdout=b'';stderr=b'synthetic failure'
  with tempfile.TemporaryDirectory() as d:
   runtime=BrowserRuntime(Path(d),runner=lambda *a,**k:Result(),metadata=lambda u:{'info':{'version':'1.2.3'}})
   with self.assertRaises(SafetyError):runtime.ensure()
   self.assertFalse(runtime.ready())
 def test_existing_unrelated_runtime_not_overwritten(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);sentinel=root/'runtime'/'user.txt';sentinel.parent.mkdir();sentinel.write_text('keep')
   BrowserRuntime(root,runner=self.runner(calls),metadata=lambda u:{'info':{'version':'1.2.3'}}).ensure();self.assertEqual(sentinel.read_text(),'keep')

if __name__=='__main__':unittest.main()

class RuntimeLicenseTests(unittest.TestCase):
 def test_modern_pypi_license_expression_is_recorded_not_misreported_missing(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   fixture=RuntimeTests();runtime=BrowserRuntime(Path(d),runner=fixture.runner(calls),metadata=lambda u:{'info':{'version':'1.2.3','license':None,'license_expression':'Apache-2.0'}})
   runtime.ensure();receipt=json.loads(runtime.receipt.read_text(encoding='utf-8-sig'));self.assertEqual(receipt['sources']['playwright']['license'],'Apache-2.0')
