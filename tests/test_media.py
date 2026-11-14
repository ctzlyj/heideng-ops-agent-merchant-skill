import tempfile,unittest
from pathlib import Path
from heideng_merchant.providers import MediaConfiguration,media_status,validate_external_endpoint
from heideng_merchant.video_source import VideoSource
from heideng_merchant.safety import SafetyError

class MediaTests(unittest.TestCase):
 def test_unselected_models_never_inherit_employee_credentials(self):
  with tempfile.TemporaryDirectory() as d:
   config=MediaConfiguration(Path(d));self.assertEqual(config.status()['image']['status'],'awaiting-provider');self.assertEqual(config.status()['video']['status'],'awaiting-provider')
   with self.assertRaises(SafetyError):config.generation_request('image',{'prompt':'x'})
 def test_internal_and_private_endpoints_rejected(self):
  for url in ('http://example.com/v1','https://llm-gw.jd.local/v1','https://oxygen-model.jd.com/v1','https://127.0.0.1/v1','https://10.0.0.1/v1','https://x@api.external.example/v1'):
   with self.subTest(url=url),self.assertRaises(SafetyError):validate_external_endpoint(url)
 def test_source_not_selected_not_implicitly_enabled(self):
  with tempfile.TemporaryDirectory() as d:
   c=MediaConfiguration(Path(d))
   with self.assertRaises(SafetyError):c.configure('image',{'provider':'oxygen-h3','endpoint':'https://oxygen-model.jd.com','model':'x'},selection_confirmed=True)
 def test_video_upstream_is_fixed_and_generation_deferred(self):
  with tempfile.TemporaryDirectory() as d:
   v=VideoSource(Path(d));self.assertEqual(v.status()['repository'],'ctzlyj/jd-pop-main-video-skill');self.assertNotIn('11190',str(v.status()));self.assertFalse(v.status()['generationEnabled'])
 def test_video_revision_validation(self):
  with tempfile.TemporaryDirectory() as d:
   v=VideoSource(Path(d))
   with self.assertRaises(SafetyError):v.record('not-sha','0.3.0',{})
   r=v.record('a'*40,'0.3.0',{'VERSION':'b'*64});self.assertEqual(r['commit'],'a'*40)

if __name__=='__main__':unittest.main()
