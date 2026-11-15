"""Verified public CLI source, real parser/signing, synthetic final HTTP only."""
import hashlib,json,os,socket,sys,tempfile,urllib.request,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.official_stdin import execute_envelope
from heideng_merchant.official_transport import AUDITED_SOURCES
from heideng_merchant.safety import atomic_json,file_sha
from heideng_merchant.video_contract import ALLOC,VIDEOS,SKILL
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('https://mcp-open.jd.com/cli/jdo-cli',timeout=45) as response:raw=response.read(2*1024*1024+1)
sha=hashlib.sha256(raw).hexdigest();assert sha==AUDITED_SOURCES['0.3.7']
records=[]
for action in ('allocate','save'):
 for expired in (False,True):
  with tempfile.TemporaryDirectory(prefix='native-video-sdk-') as d:
   state=Path(d);exe=state/'tools/stub/bin/jdo-cli.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'SYNTHETIC_NONEXECUTABLE');atomic_json(state/'tools/official.json',{'version':'0.3.7','root':'tools/stub','executable':'bin/jdo-cli.exe','executableSha256':file_sha(exe),'archiveSha256':'a'*64})
   execution={'transport':'official-source-stdin','officialVersion':'0.3.7','platform':'windows-x64','binarySha256':file_sha(exe),'binaryArchiveSha256':'a'*64,'sourceSha256':sha,'sourcePath':'cli/jdo-cli','sourceStatus':'deprecated'}
   operation={'url':ALLOC if action=='allocate' else VIDEOS,'method':'GET' if action=='allocate' else 'POST','params':{'zoneId':'video-owned'},'skillId':SKILL}
   if action=='allocate':operation['params'].update(fileName='fixture.mp4',fileSize=200,videoType=1)
   else:operation['body']={'zoneVideoDTO':{'videoName':'synthetic','videoDesc':'商品主图展示','videoSize':200,'jdVideoId':900,'videoType':1}}
   envelope={'schemaVersion':1,'profile':'merchant-demo','operation':operation,'execution':execution,'source':raw.decode(),'writeAuthorized':True,'approvalExpiresAt':100,'expectedShop':{'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}}
   if action=='allocate':envelope['responseMode']='video-upload-grant'
   calls=[];signs=[];retry_flags=[];clock=[99];credential=uuid.uuid4().hex;upload_secret=uuid.uuid4().hex
   def hook(ns):
    ns['get_auth_context']=lambda *a,**kw:{'profile_name':'merchant-demo','vender_id':'1','app_key':credential,'app_secret':credential,'access_token':credential};ns['touch_auth_usage']=lambda *a,**kw:None;original_sign=ns['calc_sign'];original_request=ns['execute_request_with_retry']
    def request(factory,timeout,method,refresh_callback=None,retry_safe=False):retry_flags.append({'method':method,'refresh':refresh_callback is not None,'retrySafe':retry_safe});return original_request(factory,timeout,method,refresh_callback,retry_safe)
    ns['execute_request_with_retry']=request
    def signing(*a,**kw):
     value=original_sign(*a,**kw);signs.append(1)
     if expired and len(signs)==2:clock[0]=101
     return value
    ns['calc_sign']=signing
    class Response:
     status=200
     def __init__(self,obj):self.obj=obj
     def __enter__(self):return self
     def __exit__(self,*a):pass
     def read(self):return json.dumps(self.obj).encode()
    def fake_open(request,timeout=30):
     method=request.get_method()
     if '/sp-seller/' in request.full_url:calls.append('identity-read');return Response({'success':True,'data':{'venderId':'1','shopBaseInfo':{'type':0,'shopId':'3','shopName':'synthetic-store'}}})
     calls.append(action)
     if action=='allocate':assert method=='GET' and '/media-zones/video-owned/upload-urls' in request.full_url;return Response({'success':True,'data':{'jdVideoId':900,'httpsUploadUrl':'https://upload.example.test/file?grant='+upload_secret}})
     assert method=='POST' and json.loads(request.data)==operation['body'];return Response({'success':True,'data':{'videoId':700,'jdVideoId':900}})
    ns['urlopen_with_ssl']=fake_open
   def blocked(*a,**kw):raise RuntimeError('synthetic HTTP only')
   env={'HOME':str(state/'cli-home'),'JDO_CLI_HOME':str(state/'cli-home/.jdo-cli'),'JDO_CREDENTIAL_BACKEND':'windows-credential-manager'}
   with patch.dict(os.environ,env,clear=True),patch('time.time',side_effect=lambda:clock[0]),patch.object(socket.socket,'connect',blocked),patch('socket.create_connection',blocked):result=execute_envelope(envelope,state,namespace_hook=hook)
   assert result['ok'] is (not expired) and calls==(['identity-read'] if expired else ['identity-read',action]) and len(signs)==2,'actual public source boundary failed'
   assert retry_flags[-1]['refresh'] is False and retry_flags[-1]['retrySafe'] is False
   assert credential not in json.dumps(result)
   if action=='allocate' and not expired:assert result['grant']['jdVideoId']=='900' and upload_secret in result['grant']['uploadUrl']
   records.append({'action':action,'expiredAfterSigning':expired,'success':result['ok'],'httpStages':calls,'signaturesComputed':len(signs),'businessRetryDisabled':True})
record={'status':'passed','officialVersion':'0.3.7','officialSourceSha256':sha,'realSourceParserAndSigning':True,'finalDeadlineAfterSigningEnforced':True,'allocationGETTreatedAsNonReplayableSideEffect':True,'onlyConfidentialGrantFieldsReturned':True,'nativeCredentialsNotPublished':True,'cases':records,'nativeAuth':'synthetic in-memory only','nativeHttp':'synthetic boundary with sockets blocked','realMerchantAuthorization':'not-run','realMerchantWrites':0,'paidModelCalls':0}
atomic_json(ROOT/'.agent-work/video-delivery-audit/official-source-video-smoke.json',record);print(json.dumps(record))
