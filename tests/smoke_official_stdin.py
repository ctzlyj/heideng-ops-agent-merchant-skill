"""Live public source/binary acquisition; all merchant HTTP and auth are synthetic."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
PACKAGE_ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE_ROOT))
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import atomic_json,read_json,file_sha
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''import hashlib,json,os,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1));scenario=sys.argv.pop(1)
import heideng_merchant.official_stdin as driver
from heideng_merchant.safety import atomic_json
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('network disabled in smoke'))
socket.create_connection=socket.socket.connect
if scenario=='protocol':raise SystemExit(driver.main())
envelope=json.loads(sys.stdin.buffer.read());calls=[]
def hook(ns):
 def auth(*a,**k):return {'profile_name':'merchant-smoke','vender_id':'1','app_key':'SYNTHETIC_APP','app_secret':'SYNTHETIC_SECRET','access_token':'SYNTHETIC_TOKEN','uses_stored_token':True,'token_bundle':{'refresh_token':'SYNTHETIC_REFRESH'}}
 ns['get_auth_context']=auth;ns['refresh_auth_context']=lambda context,*a,**k:context;ns['touch_auth_usage']=lambda *a,**k:None
 def request(req,timeout):
  calls.append(req.get_method())
  if req.get_method()=='GET':
   assert '/rest/sp-seller/v0/venderinfo' in req.full_url
   class IdentityResponse:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):return json.dumps({'data':{'venderId':'1','shopBaseInfo':{'type':0,'shopId':'3','shopName':'synthetic-store'}}}).encode()
   return IdentityResponse()
  assert req.get_method()=='POST' and 'synthetic-zone' in req.full_url
  body=json.loads(req.data);assert len(body['imgBase64'])==900000 and body['zoneImageDTO']=={'imgName':'synthetic.png','categoryId':1}
  headers={key.lower():value for key,value in req.header_items()};assert headers['x-jos-access-token']=='SYNTHETIC_TOKEN' and headers['x-jos-request-identity']=='vender' and headers.get('x-jos-sign')
  if scenario=='lost-response':
   import urllib.error
   raise urllib.error.URLError('synthetic-response-loss')
  class Response:
   status=200
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return json.dumps({'success':False,'message':'invalid access token'} if scenario=='auth-marker' else {'data':{'imgId':'synthetic-image','bodySha256':hashlib.sha256(req.data).hexdigest(),'inputBytes':len(req.data),'detail':'SYNTHETIC_SECRET'}}).encode()
  return Response()
 ns['urlopen_with_ssl']=request
result=driver.execute_envelope(envelope,Path(os.environ['HOME']).parent,namespace_hook=hook)
atomic_json(Path(os.environ['HOME'])/('smoke-'+scenario+'.json'),{'businessHTTPCount':calls.count('POST'),'identityHTTPCount':calls.count('GET'),'scenario':scenario})
print(json.dumps(result));raise SystemExit(0 if result['ok'] else 2)
'''

def main():
 with tempfile.TemporaryDirectory(prefix='merchant-official-stdin-smoke-') as temporary:
  state=Path(temporary);shim=state/'isolated-smoke.py';shim.write_text(SHIM,encoding='utf-8');captures=[]
  def runner(args,**kw):
   assert args[1:3]==['-I','-B'] and Path(args[3]).name=='official_stdin.py';assert len(args)==4
   assert 'SYNTHETIC' not in ' '.join(args) and 'A'*100 not in ' '.join(args)
   envelope=json.loads(kw['input']);captures.append(envelope['execution'])
   result=subprocess.run([args[0],'-I','-B',str(shim),str(PACKAGE_ROOT),scenario],**kw)
   assert 'SYNTHETIC_SECRET' not in result.stdout.decode('utf-8') and 'SYNTHETIC_TOKEN' not in result.stdout.decode('utf-8')
   return result
  client=OfficialClient(state,runner=runner);installed=client.install();assert installed['version']=='0.3.7'
  client.identity=lambda profile:{'venderId':'1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
  body={'imgBase64':'A'*900000,'zoneImageDTO':{'imgName':'synthetic.png','categoryId':1}};records={}
  for scenario in ('success','auth-marker','lost-response','protocol'):
   try:result=client.invoke('merchant-smoke','/rest/sp-product/v0/media-zones/{zoneId}/images',method='POST',params={'zoneId':'synthetic-zone'},body=body,skill_id='jdo-product-material',write_authorized=True,expected_shop={'profile':'merchant-smoke','venderId':'1','shopId':'3','shopName':'synthetic-store'})
   except Exception as error:
    assert scenario in ('lost-response','protocol');result={'outcome':'unknown','errorKind':type(error).__name__}
   if scenario!='protocol':
    record=read_json(state/'cli-home'/('smoke-'+scenario+'.json'));assert record['businessHTTPCount']==1 and record['identityHTTPCount']==1;records[scenario]=record
   if scenario=='success':assert result['data']['imgId']=='synthetic-image';records[scenario]['inputBytes']=result['data']['inputBytes']
   if scenario=='auth-marker':assert result['success'] is False
   if scenario=='protocol':records[scenario]={'credentialStore':'fresh empty namespace','result':'rejected without exposed stderr or secret','businessNetwork':'socket disabled'}
  assert not any(p.name=='jdo-cli' or p.name.endswith('.log') for p in state.rglob('*'))
  record={'date':'2026-11-15','officialBinaryInstall':'real public SHA-checked download','officialVersion':installed['version'],'sourceSha256':captures[0]['sourceSha256'],'sourceStatus':captures[0]['sourceStatus'],'sourcePersistence':'memory only, never written','childRuntime':'real Python -I -B subprocess','packageCode':'fresh installed verified ZIP' if PACKAGE_ROOT!=ROOT else 'source checkout','OSArgv':'interpreter and driver only, source/business data via stdin','merchantHTTP':'intercepted inside audited official source, socket connect blocked','credentials':'synthetic auth hook, no real merchant Credential Manager entry read/write','actualSourceParserSigning':'executed against synthetic auth, signed seller-identity GET and intercepted business HTTP','writeTransientAndAuthRetries':'disabled; each scenario one business HTTP attempt','scenarios':records,'realMerchantAPI':'not-run','realMerchantWrites':'not-run','modelCalls':0}
  atomic_json(ROOT/'.agent-work/official-stdin-smoke/evidence.json',record);print(json.dumps(record))
if __name__=='__main__':main()
