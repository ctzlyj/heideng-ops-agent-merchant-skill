import io,json,tempfile,unittest,zipfile,hashlib
from pathlib import Path
from heideng_merchant.official import OfficialClient,identity_from_response,validate_profile
from heideng_merchant.safety import SafetyError

class OfficialTests(unittest.TestCase):
 def test_profile_and_identity(self):
  for value in ('default','','../shop','UPPER','a'):
   with self.assertRaises(SafetyError):validate_profile(value)
  self.assertEqual(validate_profile('merchant-shop-1'),'merchant-shop-1')
  result=identity_from_response({'data':{'venderId':12,'shopBaseInfo':{'shopId':34,'shopName':'测试店','type':0}}})
  self.assertEqual(result,{'venderId':'12','shopId':'34','shopName':'测试店','shopType':'POP'})
  with self.assertRaises(SafetyError):identity_from_response({'data':{'venderId':12,'shopBaseInfo':{'shopId':34,'shopName':'自营店','type':1}}})
 def fixture(self):
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:z.writestr('bin/jdo-cli.exe',b'fake executable')
  raw=out.getvalue();sha=hashlib.sha256(raw).hexdigest()
  policy={'product':'jdo-cli','stableVersion':'0.3.7','artifacts':{'binaries':{'windows-x64':{'version':'0.3.7','path':'cli/releases/0.3.7/cli.zip','sha256':sha,'format':'zip','executable':'bin/jdo-cli.exe'}},'skills':{'files':[]}}}
  return raw,policy
 def test_verified_install_uses_only_official_source(self):
  raw,p=self.fixture();urls=[]
  def download(url):urls.append(url);return json.dumps(p).encode() if url.endswith('version-policy.json') else raw
  with tempfile.TemporaryDirectory() as d:
   client=OfficialClient(Path(d),download=download,platform_name='windows-x64');r=client.install()
   self.assertEqual(r['version'],'0.3.7');self.assertTrue(all(u.startswith('https://mcp-open.jd.com/') for u in urls))
   self.assertTrue(client.ready())
 def test_checksum_mismatch_never_installs(self):
  raw,p=self.fixture();p['artifacts']['binaries']['windows-x64']['sha256']='0'*64
  with tempfile.TemporaryDirectory() as d:
   client=OfficialClient(Path(d),download=lambda u:json.dumps(p).encode() if u.endswith('.json') else raw,platform_name='windows-x64')
   with self.assertRaises(SafetyError):client.install()
   self.assertFalse(client.ready())
 def test_internal_download_path_is_rejected(self):
  raw,p=self.fixture();p['artifacts']['binaries']['windows-x64']['path']='https://internal.invalid/cli'
  with tempfile.TemporaryDirectory() as d:
   c=OfficialClient(Path(d),download=lambda u:json.dumps(p).encode(),platform_name='windows-x64')
   with self.assertRaises(SafetyError):c.install()
 def test_invoke_environment_and_arguments(self):
  raw,p=self.fixture();calls=[]
  class Result:
   returncode=0;stdout='{"data":[]}';stderr=''
  def runner(args,**kwargs):calls.append((args,kwargs));return Result()
  with tempfile.TemporaryDirectory() as d:
   c=OfficialClient(Path(d),download=lambda u:json.dumps(p).encode() if u.endswith('.json') else raw,runner=runner,platform_name='windows-x64');c.install()
   c.invoke('merchant-demo','/rest/sp-product/v0/products',params={'page':1},skill_id='jdo-product-price')
   args,opts=calls[-1];self.assertIn('--profile',args);self.assertIn('merchant-demo',args);self.assertEqual(opts['env']['JDO_ENV'],'prod');self.assertNotIn('JDO_ACCESS_TOKEN',opts['env']);self.assertNotIn('JD_LLM_API_KEY',opts['env'])
   with self.assertRaises(SafetyError):c.invoke('default','/rest/sp-product/v0/products')
   with self.assertRaises(SafetyError):c.invoke('merchant-demo','https://internal.invalid')

 def test_official_gbk_json_preserves_shop_identity(self):
  raw,p=self.fixture()
  class Result:
   returncode=0;stdout=json.dumps({'data':{'venderId':'1','shopBaseInfo':{'shopId':'2','shopName':'测试店','type':0}}},ensure_ascii=False).encode('gb18030');stderr=b''
  with tempfile.TemporaryDirectory() as d:
   c=OfficialClient(Path(d),download=lambda u:json.dumps(p).encode() if u.endswith('.json') else raw,runner=lambda *a,**k:Result(),platform_name='windows-x64');c.install()
   self.assertEqual(c.identity('merchant-demo')['shopName'],'测试店')

if __name__=='__main__':unittest.main()

class OfficialReferenceTests(unittest.TestCase):
 def test_reference_documents_are_sha_checked_and_not_limited_to_entrypoint(self):
  raw,policy=OfficialTests.fixture(self);body=b'# public test reference';name='cli/skills/jdo-product-update/references/update-api.md';policy['artifacts']['skills']['files']=[{'path':name,'sha256':hashlib.sha256(body).hexdigest()}];calls=[]
  def download(url):calls.append(url);return json.dumps(policy).encode() if url.endswith('version-policy.json') else body
  with tempfile.TemporaryDirectory() as d:
   c=OfficialClient(Path(d),download=download);path=c.document('jdo-product-update','references/update-api.md');self.assertEqual(path.read_bytes(),body);self.assertTrue(calls[-1].endswith(name))
   for relative in ('../../secret.env','references/unknown.md','references/a.py'):
    with self.assertRaises(SafetyError):c.document('jdo-product-update',relative)
 def test_business_credentials_are_rejected_before_native_argument_construction(self):
  with tempfile.TemporaryDirectory() as d:
   client=OfficialClient(Path(d));client._run=lambda *a,**k:self.fail('credential reached native invocation')
   with self.assertRaises(SafetyError):client.invoke('merchant-test','/rest/sp-product/v0/products',params={'apiKey':'synthetic-private'})
