import json,os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from heideng_merchant.providers import MediaConfiguration,media_status,validate_external_endpoint
from heideng_merchant.video_source import VideoSource
from heideng_merchant.safety import SafetyError

class MediaTests(unittest.TestCase):
 def test_selected_image_does_not_inherit_employee_credentials_or_enable_spend(self):
  with tempfile.TemporaryDirectory() as d:
   config=MediaConfiguration(Path(d));self.assertEqual(config.status()['image']['status'],'adapter-ready');self.assertEqual(config.status()['video']['status'],'awaiting-provider')
   with self.assertRaises(SafetyError):config.generation_request('image',{'prompt':'x'})
 def test_lts4ai_selection_is_offline_and_preserves_supplied_chat_evidence(self):
  with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'LTS4AI_BASE_URL':'https://llm-gw.jd.local/v1','JD_LLM_API_KEY':'synthetic-not-a-key'}), patch('urllib.request.urlopen',side_effect=AssertionError('network-forbidden')):
   image=MediaConfiguration(Path(d)).status()['image']
   self.assertEqual(image['provider'],'lts4ai')
   self.assertEqual(image['endpoint'],'https://api.lts4ai.com/v1')
   self.assertEqual(image['model'],'gpt-image-2.5')
   self.assertEqual(image['documentedExamplePath'],'/v1/chat/completions')
   self.assertTrue(image['generationEnabled']);self.assertTrue(image['requiresExactBudgetApproval'])
   self.assertFalse(image['imageProtocolVerified'])
   self.assertFalse(image['liveVerified'])
   self.assertEqual(image['paidCalls'],0)
   self.assertNotIn('synthetic-not-a-key',json.dumps(image))
   image['model']='changed-by-caller'
   self.assertEqual(media_status()['image']['model'],'gpt-image-2.5')
 def test_catalog_records_image_selection_without_selecting_video_provider(self):
  from heideng_merchant.catalog import load_catalog
  registry=load_catalog()
  self.assertEqual(registry['imageProvider']['provider'],'lts4ai')
  self.assertEqual(registry['imageProvider']['model'],'gpt-image-2.5')
  self.assertEqual(registry['imageProvider']['endpoint'],'https://api.lts4ai.com/v1')
  for row in registry['capabilities']:
   if row['id'] in ('materials','listing','image-refresh'):
    self.assertEqual(row['mediaGeneration'],'adapter-ready')
   if row['id']=='video':self.assertEqual(row['mediaGeneration'],'awaiting-provider')
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
