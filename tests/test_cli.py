import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from heideng_merchant.catalog import route,load_catalog

class CliTests(unittest.TestCase):
 def test_catalog_is_not_a_whitelist(self):
  self.assertEqual(len(load_catalog()['capabilities']),8)
  self.assertEqual(route('帮我看一下店铺广告诊断')['matches'][0]['id'],'diagnosis')
  self.assertEqual(route('一个清单没写的合法任务')['status'],'open-toolbox')
 def test_onboarding_does_not_require_model_key(self):
  with tempfile.TemporaryDirectory() as d:
   p=subprocess.run([sys.executable,'scripts/merchant.py','--home',d,'onboarding'],capture_output=True,text=True,encoding='utf-8')
   self.assertEqual(p.returncode,0,p.stderr);r=json.loads(p.stdout);self.assertEqual(r['media']['image']['status'],'awaiting-provider');self.assertFalse(r['requiresEmployeeAccess']);self.assertEqual(r['version'],'0.1.0')
 def test_cli_offline_diagnosis(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'input.json';source.write_text('[{"skuId":"1","revenue":"20","orders":"2"}]')
   p=subprocess.run([sys.executable,'scripts/merchant.py','--home',d,'diagnose','--source',str(source),'--output',str(root/'report.json')],capture_output=True,text=True,encoding='utf-8')
   self.assertEqual(p.returncode,0,p.stderr);self.assertTrue((root/'report.json').is_file());self.assertEqual(json.loads(p.stdout)['scope'],'uploaded-rows')

if __name__=='__main__':unittest.main()

class VideoCliTests(unittest.TestCase):
 def test_video_runtime_status_is_offline_and_does_not_install(self):
  with tempfile.TemporaryDirectory() as d:
   p=subprocess.run([sys.executable,'scripts/merchant.py','--home',d,'video-runtime-status'],capture_output=True,text=True,encoding='utf-8')
   self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['status'],'not-prepared');self.assertFalse((Path(d)/'.heideng-merchant/runtime/video-runtime.json').exists())
 def test_preflight_rejects_missing_video_manifest_without_shop_calls(self):
  with tempfile.TemporaryDirectory() as d:
   manifest=Path(d)/'manifest.json';manifest.write_text('{"merchantPackageSchemaVersion":1}')
   p=subprocess.run([sys.executable,'scripts/merchant.py','--home',d,'video-preflight','--manifest',str(manifest)],capture_output=True,text=True,encoding='utf-8')
   self.assertEqual(p.returncode,2);self.assertEqual(json.loads(p.stdout)['error'],'video-handoff-not-reviewed-for-current-listing')
