import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from tests import test_official as fixtures

SOURCE=b"CLI_VERSION='0.3.7'\ndef main(): pass\n"
SOURCE_SHA=hashlib.sha256(SOURCE).hexdigest()

class TransportTests(unittest.TestCase):
 def client(self,d,runner=None):
  archive,policy=fixtures.OfficialTests.fixture(self)
  policy['artifacts']['cli']={'version':'0.3.7','path':'cli/jdo-cli','sha256':SOURCE_SHA,'deprecated':True}
  calls=[]
  def download(url):
   calls.append(url)
   if url.endswith('version-policy.json'):return json.dumps(policy).encode()
   return SOURCE if url.endswith('/jdo-cli') else archive
  c=OfficialClient(Path(d),download=download,runner=runner,platform_name='windows-x64');c.install()
  c.identity=lambda profile:{'venderId':'1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
  return c,policy,calls
 def success(self,execution):return type('Result',(),{'returncode':0,'stdout':json.dumps({'ok':True,'response':{'data':{'imgId':'synthetic-image'}},'execution':execution}).encode(),'stderr':b''})()
 def test_large_body_uses_stdin_not_native_argv(self):
  captured=[]
  def runner(args,**kw):captured.append((args,kw));return self.success(json.loads(kw['input'])['execution'])
  with tempfile.TemporaryDirectory() as d:
   c,policy,downloads=self.client(d,runner)
   with patch('heideng_merchant.official_transport.AUDITED_SOURCES',{'0.3.7':SOURCE_SHA}):
    result=c.invoke('merchant-demo','/rest/sp-product/v0/media-zones/{zoneId}/images',method='POST',params={'zoneId':'synthetic-zone'},body={'imgBase64':'A'*250000,'zoneImageDTO':{'imgName':'sample.png','categoryId':1}},skill_id='jdo-product-material',write_authorized=True,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
   args,kw=captured[0];self.assertEqual(len(captured),1);self.assertIn('-I',args);self.assertIn('-B',args);self.assertNotIn('A'*100,' '.join(args));self.assertIn('input',kw)
   envelope=json.loads(kw['input']);self.assertEqual(len(envelope['operation']['body']['imgBase64']),250000);self.assertEqual(envelope['execution']['sourceSha256'],SOURCE_SHA)
   self.assertNotIn('JDO_ACCESS_TOKEN',kw['env']);self.assertEqual(kw['env']['JDO_CREDENTIAL_BACKEND'],'windows-credential-manager');self.assertEqual(result['data']['imgId'],'synthetic-image')
   self.assertFalse(any(x.suffix=='.py' for x in Path(d).rglob('*')))
 def test_small_invocations_keep_native_binary(self):
  calls=[]
  def runner(args,**kw):calls.append((args,kw));return type('Result',(),{'returncode':0,'stdout':b'{"data":{}}','stderr':b''})()
  with tempfile.TemporaryDirectory() as d:
   c,policy,downloads=self.client(d,runner);c.invoke('merchant-demo','/rest/sp-product/v0/products')
   self.assertEqual(len(calls),1);self.assertNotIn('input',calls[0][1]);self.assertNotIn('https://mcp-open.jd.com/cli/jdo-cli',downloads)
 def test_quote_expansion_overflow_is_routed_before_native_submission(self):
  with tempfile.TemporaryDirectory() as d:
   c,policy,downloads=self.client(d)
   with patch('heideng_merchant.official_transport.AUDITED_SOURCES',{'0.3.7':SOURCE_SHA}):
    execution=c.plan_execution({'url':'/rest/sp-product/v0/products','method':'POST','params':{},'body':{'text':'"'*10000},'skillId':'jdo-product-publish'})
   self.assertEqual(execution['transport'],'official-source-stdin')
 def test_source_or_version_mismatch_stops_before_any_process(self):
  for kind in ('source-version','hash','unreviewed-source','binary-version','source-path'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    with patch('subprocess.run') as runner:
     c,p,calls=self.client(d,runner)
     if kind=='source-version':p['artifacts']['cli']['version']='0.3.8'
     elif kind=='hash':p['artifacts']['cli']['sha256']='f'*64
     elif kind=='binary-version':p['stableVersion']='0.3.8'
     elif kind=='source-path':p['artifacts']['cli']['path']='cli/other-source'
     with patch('heideng_merchant.official_transport.AUDITED_SOURCES',{} if kind=='unreviewed-source' else {'0.3.7':SOURCE_SHA}):
      with self.assertRaises(SafetyError):c.invoke('merchant-demo','/rest/sp-product/v0/products',method='POST',body={'text':'x'*30000},write_authorized=True,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
     runner.assert_not_called()
 def test_unknown_stdin_outcome_never_falls_back_to_binary(self):
  calls=[]
  def runner(args,**kw):calls.append(args);raise subprocess.TimeoutExpired(args,1)
  with tempfile.TemporaryDirectory() as d:
   c,p,downloads=self.client(d,runner)
   with patch('heideng_merchant.official_transport.AUDITED_SOURCES',{'0.3.7':SOURCE_SHA}):
    with self.assertRaisesRegex(SafetyError,'unknown'):c.invoke('merchant-demo','/rest/sp-product/v0/products',method='POST',body={'text':'x'*30000},write_authorized=True,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
   self.assertEqual(len(calls),1)
 def test_expired_approval_does_not_launch_selected_transport(self):
  with tempfile.TemporaryDirectory() as d:
   with patch('subprocess.run') as runner:
    c,p,calls=self.client(d,runner)
    with patch('heideng_merchant.official_transport.AUDITED_SOURCES',{'0.3.7':SOURCE_SHA}):
     with self.assertRaisesRegex(SafetyError,'approval-expired'):c.invoke('merchant-demo','/rest/sp-product/v0/products',method='POST',body={'text':'x'*30000},write_authorized=True,authorization_expires_at=1,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
    runner.assert_not_called()
 def test_payload_and_macos_boundaries_before_source_download(self):
  with tempfile.TemporaryDirectory() as d:
   with patch('subprocess.run') as runner:
    c,p,calls=self.client(d,runner);prior=len(calls)
    for body in ({'text':'x'*(8*1024*1024)},{'nested':json.dumps({'eid':'SYNTHETIC_ONLY'})}):
     with self.assertRaises(SafetyError):c.invoke('merchant-demo','/rest/sp-product/v0/products',method='POST',body=body,write_authorized=True,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
    c.platform_name='macos-arm64'
    with self.assertRaisesRegex(SafetyError,'secret-argv'):c.invoke('merchant-demo','/rest/sp-product/v0/products',method='POST',body={'text':'x'*30000},write_authorized=True,expected_shop={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'})
    self.assertEqual(len(calls),prior);runner.assert_not_called()

if __name__=='__main__':unittest.main()
