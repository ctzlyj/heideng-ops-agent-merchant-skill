import base64,io,json,os,tempfile,time,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.providers import MediaConfiguration
from heideng_merchant.safety import SafetyError

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
class Response:
 def __init__(self,data):self.data=data;self.headers={'Content-Type':'application/json'}
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self):return self.data

class Lts4aiGenerationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.config=MediaConfiguration(self.root/'state')
 def request(self,**overrides):
  request={'requestId':'synthetic-one','prompt':'A product photo using only supplied facts','size':'1024x1024','count':1,'outputDirectory':str(self.root/'images'),'budget':'3','quote':{'unitCost':'3','currency':'LTS4AI-points','evidence':'https://api.lts4ai.com/pricing','observedAt':time.time()}}
  request.update(overrides);return request
 def approved(self,**overrides):
  p=self.config.image_plan(self.request(**overrides))
  return self.config.image_approve(p['planId'],p['fingerprint'],confirmed=True)
 def response(self):return Response(json.dumps({'data':[{'b64_json':base64.b64encode(PNG).decode()}]}).encode())
 def test_text_generation_reaches_fixed_provider_and_saves_original(self):
  plan=self.approved()
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key','JD_LLM_API_KEY':'synthetic-internal-key','LTS4AI_BASE_URL':'https://llm-gw.jd.local/v1'}),patch('urllib.request.OpenerDirector.open',return_value=self.response()) as send:
   result=self.config.generation_request('image',{'planId':plan['planId']})
  self.assertEqual(result['status'],'completed');self.assertEqual(send.call_count,1)
  request=send.call_args.args[0];self.assertEqual(request.full_url,'https://api.lts4ai.com/v1/images/generations')
  body=json.loads(request.data);self.assertEqual(body,{'model':'gpt-image-2.5','prompt':plan['scope']['prompt'],'size':'1024x1024','output_format':'png'})
  self.assertEqual(request.get_header('Authorization'),'Bearer synthetic-lts-key')
  self.assertEqual(Path(result['outputs'][0]['path']).read_bytes(),PNG)
  self.assertNotIn('synthetic-lts-key',json.dumps(result));self.assertNotIn('synthetic-internal-key',json.dumps(result))
  self.assertEqual(result['attemptedRequests'],1)
 def test_reference_edit_uses_multipart_and_exact_input_order(self):
  refs=[]
  for name in ('first.png','second.png'):
   p=self.root/name;p.write_bytes(PNG);refs.append(str(p))
  plan=self.approved(images=refs)
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key'}),patch('urllib.request.OpenerDirector.open',return_value=self.response()) as send:
   result=self.config.generation_request('image',{'planId':plan['planId']})
  request=send.call_args.args[0];self.assertEqual(request.full_url,'https://api.lts4ai.com/v1/images/edits')
  self.assertIn('multipart/form-data',request.get_header('Content-type'));self.assertLess(request.data.index(b'first.png'),request.data.index(b'second.png'))
  self.assertEqual(result['status'],'completed')
 def test_unapproved_and_missing_key_make_no_network_request(self):
  plan=self.config.image_plan(self.request())
  with patch.dict(os.environ,{},clear=True),patch('urllib.request.OpenerDirector.open') as send:
   with self.assertRaises(SafetyError):self.config.generation_request('image',{'planId':plan['planId']})
   self.config.image_approve(plan['planId'],plan['fingerprint'],confirmed=True)
   with self.assertRaises(SafetyError):self.config.generation_request('image',{'planId':plan['planId']})
   send.assert_not_called()
 def test_timeout_is_durable_unknown_and_cannot_replay(self):
  plan=self.approved()
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key'}),patch('urllib.request.OpenerDirector.open',side_effect=TimeoutError('synthetic-lts-key')) as send:
   first=self.config.generation_request('image',{'planId':plan['planId']});second=self.config.generation_request('image',{'planId':plan['planId']})
  self.assertEqual(first['status'],'unknown');self.assertEqual(second['status'],'unknown');self.assertEqual(send.call_count,1)
  self.assertNotIn('synthetic-lts-key',json.dumps(second))
 def test_completed_replay_does_not_generate_again(self):
  plan=self.approved()
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key'}),patch('urllib.request.OpenerDirector.open',return_value=self.response()) as send:
   self.config.generation_request('image',{'planId':plan['planId']});result=self.config.generation_request('image',{'planId':plan['planId']})
  self.assertEqual(result['status'],'completed');self.assertEqual(send.call_count,1)
 def test_changed_reference_is_rejected_before_submission(self):
  p=self.root/'product.png';p.write_bytes(PNG);plan=self.approved(images=[str(p)]);p.write_bytes(PNG+b'changed')
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key'}),patch('urllib.request.OpenerDirector.open') as send:
   with self.assertRaises(SafetyError):self.config.generation_request('image',{'planId':plan['planId']})
   send.assert_not_called()
 def test_budget_overrun_and_source_override_rejected(self):
  for values in ({'count':2},{'endpoint':'https://llm-gw.jd.local/v1'},{'model':'other-model'}):
   with self.subTest(values=values),self.assertRaises(SafetyError):self.config.image_plan(self.request(**values))
 def test_fixed_count_partial_failure_stops_remaining_submissions(self):
  plan=self.approved(count=3,budget='9')
  with patch.dict(os.environ,{'LTS4AI_API_KEY':'synthetic-lts-key'}),patch('urllib.request.OpenerDirector.open',side_effect=[self.response(),TimeoutError()]) as send:
   result=self.config.generation_request('image',{'planId':plan['planId']})
  self.assertEqual(send.call_count,2);self.assertEqual(result['status'],'unknown');self.assertEqual(len(result['outputs']),1)
 def test_generation_route_is_available_but_not_live_verified(self):
  status=self.config.status()['image']
  self.assertTrue(status['adapterAvailable']);self.assertTrue(status['generationEnabled']);self.assertFalse(status['liveVerified'])

class ImageDownloadSafetyTests(unittest.TestCase):
 def test_provider_result_url_cannot_route_to_internal_or_private_network(self):
  from heideng_merchant.lts4ai_client import download_remote_image
  for url in ('https://llm-gw.jd.local/result.png','https://127.0.0.1/result.png','https://name:password@cdn.example/result.png'):
   with self.subTest(url=url),patch('urllib.request.OpenerDirector.open') as send:
    with self.assertRaises(SafetyError):download_remote_image(url,10)
    send.assert_not_called()
 def test_result_download_does_not_forward_lts4ai_credentials(self):
  from heideng_merchant.lts4ai_client import download_remote_image
  response=Response(PNG);response.headers={'Content-Type':'image/png'}
  with patch('urllib.request.OpenerDirector.open',return_value=response) as send:
   data,mime=download_remote_image('https://cdn.example/result.png?signature=synthetic',10)
  self.assertEqual(data,PNG);self.assertEqual(mime,'image/png')
  self.assertIsNone(send.call_args.args[0].get_header('Authorization'))

class Lts4aiCliTests(unittest.TestCase):
 def test_agent_cli_has_plan_approve_execute_status_without_secret_argument(self):
  from heideng_merchant import cli
  for command,args in (
   ('image-plan',['--request','nonsecret-request.json']),
   ('image-approve',['--plan-id','a'*64,'--fingerprint','b'*64,'--confirm']),
   ('image-execute',['--plan-id','a'*64]),
   ('image-status',['--plan-id','a'*64])):
   with self.subTest(command=command):self.assertEqual(cli.parser().parse_args([command,*args]).command,command)
  self.assertNotIn('--api-key',cli.parser().format_help())
