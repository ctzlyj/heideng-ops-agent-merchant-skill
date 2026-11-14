import json,os,tempfile,unittest
from pathlib import Path
from heideng_merchant.image_runtime import ImageRuntime
from heideng_merchant.image_probe import probe_image
from heideng_merchant.safety import SafetyError

class ImageRuntimeTests(unittest.TestCase):
 def runner(self,calls):
  class Result:returncode=0;stderr=b'';stdout=b'{"Pillow":"1.2.3"}'
  def run(args,**kw):
   calls.append((args,kw))
   if 'venv' in args:
    python=Path(args[-1])/('Scripts/python.exe' if os.name=='nt' else 'bin/python');python.parent.mkdir(parents=True);python.write_bytes(b'synthetic python')
   return Result()
  return run
 def test_pillow_pool_does_not_modify_browser_runtime(self):
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);browser=state/'runtime/browser-runtime.json';browser.parent.mkdir();browser.write_text('{"sentinel":"keep"}');calls=[];urls=[]
   def metadata(url):urls.append(url);return {'info':{'version':'1.2.3','license_expression':'synthetic-license'}}
   runtime=ImageRuntime(state,runner=self.runner(calls),metadata=metadata);self.assertEqual(runtime.ensure()['status'],'ready');self.assertEqual(browser.read_text(),'{"sentinel":"keep"}');self.assertEqual(urls,['https://pypi.org/pypi/Pillow/json']);self.assertEqual(runtime.status()['packages'],{'Pillow':'1.2.3'})
   self.assertTrue(any('--isolated' in args and 'Pillow==1.2.3' in args for args,kw in calls));self.assertTrue(all('JD_LLM_API_KEY' not in kw['env'] for args,kw in calls));self.assertEqual(json.loads(runtime.receipt.read_text())['sources']['Pillow']['license'],'synthetic-license');self.assertEqual(json.loads(runtime.receipt.read_text())['channel'],'original-image-decoder')
 def test_image_runtime_probe_loads_pillow_decoder(self):
  with tempfile.TemporaryDirectory() as d:
   calls=[];runtime=ImageRuntime(Path(d),runner=self.runner(calls),metadata=lambda u:{'info':{'version':'1.2.3'}});runtime.ensure();self.assertTrue(any('PIL.Image' in arg for args,kw in calls for arg in args))
 def test_probe_requires_byte_sha_and_known_shape_from_child(self):
  import hashlib
  from unittest.mock import patch
  class Runtime:
   def ensure(self):return {'status':'ready'}
   def python(self):return Path('synthetic-python')
   def _run(self,args,home,timeout,input_data=None):return json.dumps({'sha256':'0'*64,'format':'PNG','width':2,'height':2,'bytes':len(input_data),'frames':1}).encode()
   def home(self):return Path('.')
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.image_probe.ImageRuntime',return_value=Runtime()):
   with self.assertRaises(SafetyError):probe_image(Path(d),b'synthetic image bytes')

if __name__=='__main__':unittest.main()
