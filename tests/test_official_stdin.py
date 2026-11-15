import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError,atomic_json,file_sha
from heideng_merchant.official_stdin import execute_envelope
from heideng_merchant import official_transport as transport

SOURCE="""import json,sys
from types import SimpleNamespace
CLI_VERSION='0.3.7'
def log_event(*a,**k): raise RuntimeError('should not log')
def get_auth_context(*a,**k): return {'profile_name':'merchant-demo','vender_id':'1','app_key':'SYNTHETIC_APP','app_secret':'SYNTHETIC_SECRET','access_token':'SYNTHETIC_TOKEN'}
def refresh_auth_context(context,args): return context
def execute_request_with_retry(factory,timeout,http_method,refresh_callback=None,retry_safe=False):
 return (200,json.dumps({'refresh':refresh_callback is not None,'retrySafe':retry_safe}))
def cmd_invoke(args):
 context=get_auth_context(args)
 if args.method=='GET':
  print(json.dumps({'data':{'venderId':context['vender_id'],'shopBaseInfo':{'type':0,'shopId':'3','shopName':'synthetic-store'}}}));return
 context=get_auth_context(args)
 print('token='+context['access_token'],file=sys.stderr)
 print(json.dumps({'data':{'bodyLength':len(sys.argv[sys.argv.index('--body')+1]),'detail':context['app_secret'],'retry':json.loads(execute_request_with_retry(None,30,'POST',lambda:None,True)[1])}}))
def main():
 cmd_invoke(SimpleNamespace(profile='merchant-demo',method='POST',params='{}',body=sys.argv[sys.argv.index('--body')+1],url='/rest/sp-product/v0/products',dry_run=False))
"""
SHA=hashlib.sha256(SOURCE.encode()).hexdigest()

class StdinTests(unittest.TestCase):
 def envelope(self,d):
  state=Path(d);exe=state/'tools/stub/bin/jdo-cli.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'synthetic executable')
  atomic_json(state/'tools/official.json',{'version':'0.3.7','root':'tools/stub','executable':'bin/jdo-cli.exe','executableSha256':file_sha(exe),'archiveSha256':'a'*64})
  execution={'transport':'official-source-stdin','officialVersion':'0.3.7','platform':'windows-x64','binarySha256':file_sha(exe),'binaryArchiveSha256':'a'*64,'sourceSha256':SHA,'sourcePath':'cli/jdo-cli','sourceStatus':'deprecated'}
  return {'schemaVersion':1,'profile':'merchant-demo','operation':{'url':'/rest/sp-product/v0/media-zones/{zoneId}/images','method':'POST','params':{'zoneId':'synthetic-zone'},'body':{'imgBase64':'A'*250000},'skillId':'jdo-product-material'},'execution':execution,'source':SOURCE,'writeAuthorized':True,'approvalExpiresAt':None,'expectedShop':{'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}}
 def environment(self,d):return patch.dict(os.environ,{'HOME':str(Path(d)/'cli-home'),'JDO_CLI_HOME':str(Path(d)/'cli-home/.jdo-cli'),'JDO_CREDENTIAL_BACKEND':'windows-credential-manager'},clear=True)
 def test_memory_parser_capture_redaction_and_no_write_retry(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);before=set(Path(d).rglob('*'));result=execute_envelope(envelope,Path(d));self.assertTrue(result['ok']);self.assertGreater(result['response']['data']['bodyLength'],250000)
   self.assertNotIn('SYNTHETIC_SECRET',json.dumps(result));self.assertNotIn('SYNTHETIC_TOKEN',json.dumps(result));self.assertEqual(result['response']['data']['retry'],{'refresh':False,'retrySafe':False});self.assertEqual(result['execution'],envelope['execution']);self.assertEqual(before,set(Path(d).rglob('*')))
 def test_unverified_source_or_changed_binary_never_executes(self):
  for kind in ('source','version','binary','archive','transport'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
    envelope=self.envelope(d)
    if kind=='source':envelope['source']+='\nprint("unsafe")'
    elif kind=='version':envelope['execution']['officialVersion']='0.3.8'
    elif kind=='binary':(Path(d)/'tools/stub/bin/jdo-cli.exe').write_bytes(b'changed')
    elif kind=='archive':envelope['execution']['binaryArchiveSha256']='b'*64
    elif kind=='transport':envelope['execution']['transport']='unknown'
    with self.assertRaises(SafetyError):execute_envelope(envelope,Path(d))
 def test_unapproved_foreign_profile_or_secret_business_input_rejected(self):
  for kind in ('approval','profile','secret','unknown-field','backend','ambient-token'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
    envelope=self.envelope(d)
    if kind=='approval':envelope['writeAuthorized']=False
    elif kind=='profile':envelope['profile']='default'
    elif kind=='secret':envelope['operation']['body']['text']=json.dumps({'eid':'SYNTHETIC_PRIVATE'})
    elif kind=='unknown-field':envelope['argv']=['login']
    elif kind=='backend':os.environ['JDO_CREDENTIAL_BACKEND']='file'
    else:os.environ['JDO_ACCESS_TOKEN']='SYNTHETIC_AMBIENT'
    with self.assertRaises(SafetyError):execute_envelope(envelope,Path(d))
 def test_approval_expiry_during_worker_setup_prevents_business_request(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);envelope['approvalExpiresAt']=1
   with patch('heideng_merchant.official_stdin.time.time',return_value=2):result=execute_envelope(envelope,Path(d))
   self.assertFalse(result['ok'])
 def test_request_echo_and_known_secret_json_keys_are_not_published(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d)
   def hook(ns):
    def main():
     ctx=ns['get_auth_context'](type('Args',(),{'method':'POST','params':'{}','body':'{}','url':'/rest/sp-product/v0/products','dry_run':False})())
     print(json.dumps({'data':{'imgId':'safe-id','request':envelope['operation']['body']},ctx['access_token']:'echo'}))
    ns['main']=main
   result=execute_envelope(envelope,Path(d),namespace_hook=hook);self.assertTrue(result['ok']);serialized=json.dumps(result);self.assertTrue('A'*1024 not in serialized,'request echo was published');self.assertTrue('SYNTHETIC_TOKEN' not in serialized,'known secret key was published');self.assertEqual(result['response']['data']['imgId'],'safe-id')
 def test_mismatched_authorized_vender_never_runs_business_request(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);envelope['expectedShop']={'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}
   def hook(ns):
    original=ns['get_auth_context']
    def foreign(*a,**k):ctx=original(*a,**k);ctx['vender_id']='2';return ctx
    ns['get_auth_context']=foreign
   result=execute_envelope(envelope,Path(d),namespace_hook=hook);self.assertFalse(result['ok'])
 def test_live_shop_check_and_business_use_one_frozen_auth_context(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);reads=[]
   def hook(ns):
    original=ns['get_auth_context']
    def changing(*a,**k):
     result=original(*a,**k);reads.append(1)
     if len(reads)>1:result['vender_id']='2'
     return result
    ns['get_auth_context']=changing
   result=execute_envelope(envelope,Path(d),namespace_hook=hook);self.assertTrue(result['ok']);self.assertEqual(len(reads),1)
 def test_bad_upstream_output_is_unknown_without_echoing_stderr(self):
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d)
   def hook(namespace):
    def fail():print('SYNTHETIC_PRIVATE');raise RuntimeError('SYNTHETIC_PRIVATE')
    namespace['main']=fail
   result=execute_envelope(envelope,Path(d),namespace_hook=hook);self.assertFalse(result['ok']);self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(result))

 def test_publication_deadline_after_signing_prevents_http_open(self):
  import time
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);envelope['operation']={'url':'/rest/sp-product/v0/product-applies','method':'POST','params':{},'body':{'schema':'[]'},'skillId':'jdo-product-publish'};envelope['approvalExpiresAt']=100;clock=[99];opened=[]
   def hook(ns):
    def http_open(*a,**kw):opened.append(1);return (200,'{}')
    def request(factory,timeout,http_method,refresh_callback=None,retry_safe=False):
     signed=factory();return ns['urlopen_with_ssl'](signed,timeout=timeout)
    def main():
     def signing():clock[0]=101;return object()
     ns['execute_request_with_retry'](signing,30,'POST');print('{}')
    ns.update(urlopen_with_ssl=http_open,execute_request_with_retry=request,main=main)
   with patch('time.time',side_effect=lambda:clock[0]):result=execute_envelope(envelope,Path(d),namespace_hook=hook)
   self.assertFalse(result['ok']);self.assertEqual(opened,[])

 def test_publication_native_http_fallback_cannot_send_after_deadline(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d,self.environment(d),patch.dict(transport.AUDITED_SOURCES,{'0.3.7':SHA}):
   envelope=self.envelope(d);envelope['operation']={'url':'/rest/sp-product/v0/product-applies','method':'POST','params':{},'body':{'schema':'[]'},'skillId':'jdo-product-publish'};envelope['approvalExpiresAt']=100;clock=[99];opened=[]
   def hook(ns):
    def native(*a,**kw):
     opened.append(1)
     if len(opened)==1:clock[0]=101;raise RuntimeError('synthetic TLS failure before application acceptance')
     return (200,'{}')
    module=SimpleNamespace(request=SimpleNamespace(urlopen=native));ns['urllib']=module
    def http_open(*a,**kw):
     try:return module.request.urlopen(*a,**kw)
     except RuntimeError:return module.request.urlopen(*a,**kw)
    def request(factory,timeout,http_method,refresh_callback=None,retry_safe=False):return ns['urlopen_with_ssl'](factory(),timeout=timeout)
    def main():ns['execute_request_with_retry'](lambda:object(),30,'POST');print('{}')
    ns.update(urlopen_with_ssl=http_open,execute_request_with_retry=request,main=main)
   with patch('time.time',side_effect=lambda:clock[0]):result=execute_envelope(envelope,Path(d),namespace_hook=hook)
   self.assertFalse(result['ok']);self.assertEqual(opened,[1])

if __name__=='__main__':unittest.main()
