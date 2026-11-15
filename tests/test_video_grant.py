"""Synthetic-only coverage of confidential native video grants."""
import importlib.util,json,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError
import tests.test_official_stdin as fixtures
SHA=fixtures.SHA
from heideng_merchant.official_stdin import execute_envelope
import heideng_merchant.official_transport as transport

ALLOC='/rest/sp-product/v0/media-zones/{zoneId}/upload-urls'
class GenericVideoGuardTests(unittest.TestCase):
 def test_generic_allocation_and_video_save_cannot_bypass_native_session(self):
  from tests.material_fixtures import Client
  with tempfile.TemporaryDirectory() as d:
   c=Client();ops=Operations(Path(d),c);ops.connect('merchant-test','synthetic-store','1')
   for url,method in ((ALLOC,'GET'),('/rest/sp-product/v0/media-zones/{zoneId}/videos','POST')):
    op={'url':url,'method':method,'params':{'zoneId':'video-owned'},'skillId':'jdo-api-830'}
    if method=='POST':op['body']={'zoneVideoDTO':{'videoName':'synthetic','videoType':1,'jdVideoId':900}}
    with self.subTest(method=method),self.assertRaises(SafetyError):ops.prepare('merchant-test',op)

class ConfidentialGrantTests(unittest.TestCase):
 def fixture(self,d):
  f=fixtures.StdinTests();envelope=f.envelope(d);envelope.update(responseMode='video-upload-grant',approvalExpiresAt=time.time()+900);envelope['operation']={'url':ALLOC,'method':'GET','params':{'zoneId':'video-owned','fileName':'sample.mp4','fileSize':128,'videoType':1},'skillId':'jdo-api-830'}
  return f,envelope
 def test_allocation_has_no_retry_and_only_whitelisted_confidential_fields(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d:
   fixture,envelope=self.fixture(d);secret=uuid.uuid4().hex;url='https://upload.example.test/file?grant='+secret;calls=[]
   def hook(ns):
    def original(factory,timeout,method,refresh_callback=None,retry_safe=False):calls.append((refresh_callback,retry_safe));return 200,'{}'
    def cmd(args):
     context=ns['get_auth_context'](args)
     if args.url.endswith('venderinfo'):print(json.dumps({'data':{'venderId':'1','shopBaseInfo':{'type':0,'shopId':'3','shopName':'synthetic-store'}}}));return
     ns['execute_request_with_retry'](None,30,'GET',lambda:None,True)
     print(json.dumps({'success':True,'data':{'httpsUploadUrl':url,'jdVideoId':900,'access_token':context['access_token']}}))
    ns['execute_request_with_retry']=original;ns['cmd_invoke']=cmd;ns['urlopen_with_ssl']=lambda *a,**k:None;ns['main']=lambda:cmd(SimpleNamespace(profile='merchant-demo',method='GET',params='{}',body=None,url=ALLOC,dry_run=False,path_params=None,skill_id='jdo-api-830'))
   with fixture.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):result=execute_envelope(envelope,Path(d),namespace_hook=hook)
   self.assertTrue(result['ok']);self.assertEqual(calls,[(None,False)]);self.assertEqual(set(result['grant']),{'jdVideoId','uploadUrl'});self.assertEqual(result['grant']['uploadUrl'],url);self.assertNotIn('SYNTHETIC_TOKEN',json.dumps(result))
 def test_allocation_without_approval_deadline_or_shop_is_refused(self):
  for field,value in (('writeAuthorized',False),('approvalExpiresAt',None),('expectedShop',None)):
   with tempfile.TemporaryDirectory() as d:
    fixture,envelope=self.fixture(d);envelope[field]=value
    with fixture.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}),self.assertRaises(SafetyError):execute_envelope(envelope,Path(d))
 def test_grant_type_is_nonserializable_and_consumed_once(self):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.video_transfer'),'missing confidential grant/transfer module')
  from heideng_merchant.video_transfer import UploadGrant
  secret=uuid.uuid4().hex;grant=UploadGrant(900,'https://upload.example.test/file?grant='+secret)
  self.assertNotIn(secret,repr(grant))
  with self.assertRaises(TypeError):json.dumps(grant)
  self.assertEqual(grant.consume()[0],'900')
  with self.assertRaises(SafetyError):grant.consume()

class OfficialGrantClientTests(unittest.TestCase):
 def test_client_uses_captured_stdin_and_returns_opaque_grant(self):
  from heideng_merchant.official import OfficialClient
  from heideng_merchant.safety import clean_environment
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);secret=uuid.uuid4().hex;calls=[];execution={'transport':'official-source-stdin','officialVersion':'0.3.7'}
   class Result:returncode=0;stdout=json.dumps({'ok':True,'execution':execution,'grant':{'jdVideoId':'900','uploadUrl':'https://upload.example.test/file?grant='+secret}}).encode()
   def run(args,**kw):calls.append((args,kw));return Result()
   c=OfficialClient(state,runner=run);c._environment=lambda:clean_environment(state/'cli-home');c._verified_source=('a'*64,b'\n');c.plan_execution=lambda *a,**k:execution
   params={'zoneId':'video-owned','fileName':'sample.mp4','fileSize':100,'videoType':1};shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}
   grant=c.allocate_video_upload('merchant-demo',params,write_authorized=True,expected_execution=execution,expected_shop=shop,authorization_expires_at=time.time()+900)
   self.assertNotIn(secret,repr(grant));self.assertEqual(grant.jd_video_id,'900');self.assertNotIn(secret,repr(calls));envelope=json.loads(calls[0][1]['input']);self.assertEqual(envelope['responseMode'],'video-upload-grant');self.assertTrue(envelope['writeAuthorized']);self.assertEqual(envelope['expectedShop'],shop)
 def test_generic_official_invoke_cannot_publish_allocation_response(self):
  from heideng_merchant.official import OfficialClient
  with tempfile.TemporaryDirectory() as d:
   c=OfficialClient(Path(d))
   with self.assertRaises(SafetyError) as error:c.invoke('merchant-demo',ALLOC,params={'zoneId':'video-owned'})
   self.assertIn('confidential',str(error.exception))
