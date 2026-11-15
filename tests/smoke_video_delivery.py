"""Real fresh install/decoder/multipart, synthetic native API and connection only."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from tests.material_fixtures import png
from tests.smoke_video_handoff import PREPARE

SHIM=r'''
import sys,socket,json,io
from pathlib import Path
installed=Path(sys.argv[1]);repo=Path(sys.argv[2]);del sys.argv[1:3];sys.path[:0]=[str(installed),str(repo)]
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic native HTTP only'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic native HTTP only'))
from heideng_merchant import cli
from heideng_merchant.safety import atomic_json,read_json
from heideng_merchant.video_delivery import VideoDelivery
from heideng_merchant.video_transfer import transfer_video
from tests.video_delivery_fixtures import Client
class Native(Client):
 def __init__(self,state):
  super().__init__();self.file=Path(state)/'synthetic-native-video.json';saved=read_json(self.file,{})
  for k in ('allocations','saves','transfers','video','fault'):setattr(self,k,saved.get(k,getattr(self,k)))
 def persist(self):atomic_json(self.file,{k:getattr(self,k) for k in ('allocations','saves','transfers','video','fault')})
 def invoke(self,*a,**kw):
  try:return super().invoke(*a,**kw)
  finally:self.persist()
 def allocate_video_upload(self,*a,**kw):
  try:return super().allocate_video_upload(*a,**kw)
  finally:self.persist()
 def transfer(self,grant,path,sha,size,deadline,**kw):
  owner=self;chunks=[]
  class Response:
   status=200
   def __init__(self):self.data=io.BytesIO(b'HTTP response only; not storage proof')
   def read(self,n):return self.data.read(n)
  class Connection:
   def __init__(self,*a,**kw):pass
   def putrequest(self,method,path,**kw):assert method=='POST'
   def putheader(self,key,value):assert key.lower() not in ('cookie','authorization')
   def endheaders(self):owner.transfers.append(grant.jd_video_id)
   def send(self,raw):chunks.append(raw)
   def getresponse(self):
    if owner.fault=='transfer-timeout':raise TimeoutError('synthetic HTTP unknown')
    return Response()
   def close(self):pass
  def resolver(*a,**kw):return [(2,1,6,'',('127.0.0.1' if owner.fault=='before-transfer' else '8.8.8.8',443))]
  try:
   result=transfer_video(grant,path,sha,size,deadline,resolver=resolver,connection_factory=Connection,**kw)
   assert Path(path).read_bytes() in b''.join(chunks) and b'name="video_file"' in b''.join(chunks)
   return result
  finally:self.persist()
cli.OfficialClient=Native
cli.VideoDelivery=lambda state,client:VideoDelivery(state,client,transfer=client.transfer)
assert Path(cli.__file__).resolve().is_relative_to(installed.resolve())
raise SystemExit(cli.main())
'''

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='hv-') as d:
  home=Path(d);env=clean_environment(home);state=home/'.heideng-merchant';state.mkdir()
  def run(args,code=0):
   result=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=600)
   if result.returncode!=code:out=ROOT/'.agent-work/video-delivery-audit';out.mkdir(parents=True,exist_ok=True);(out/'installed-video-failure.log').write_bytes(result.stdout+result.stderr)
   assert result.returncode==code,'installed native video smoke failed; ignored synthetic diagnostic retained'
   return result.stdout
  run([sys.executable,'-I','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]);installed=home/'.codex/skills/heideng-ops-agent-merchant';prepare=home/'prepare.py';prepare.write_text(PREPARE,encoding='utf-8');media=home/'media';run([sys.executable,'-I','-B',prepare,installed,home,ROOT/'tests/video_fixture_producer.py',media])
  shim=home/'native-video.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):return json.loads(run([sys.executable,'-I','-B',shim,installed,ROOT,'--home',home,*args],code))
  command('shop-connect','--profile','merchant-test','--shop-name','synthetic-store','--vender-id','1')
  cover=home/'cover.png';cover.write_bytes(png())
  def package(name,clip):
   manifest=home/(name+'.json');atomic_json(manifest,{'merchantPackageSchemaVersion':1,'sourceProduct':{'title':'synthetic item'}})
   info=command('attach-video','--manifest',manifest,'--video',clip,'--cover',cover)['video'];review=home/(name+'-review.json');atomic_json(review,{'sha256':info['sha256'],'coverSha256':info['coverSha256'],'listingFingerprint':info['listingFingerprint'],'visualPass':True,'voiceConfirmed':True});command('attach-video','--manifest',manifest,'--video',clip,'--cover',cover,'--review',review);return manifest
  manifest=package('reviewed',media/'with-audio.mp4');plan=command('video-delivery-plan','--profile','merchant-test','--manifest',manifest,'--zone-id','video-owned');command('video-delivery-execute','--session-id',plan['sessionId'],code=2);assert not read_json(state/'synthetic-native-video.json')['allocations']
  command('video-delivery-approve','--session-id',plan['sessionId'],'--fingerprint',plan['fingerprint'],'--confirm');result=command('video-delivery-execute','--session-id',plan['sessionId']);assert result['status']=='ready' and result['storageVerified'] and not result['auditApproved'] and result['videoId']=='700' and result['jdVideoId']=='900'
  command('video-delivery-execute','--session-id',plan['sessionId']);native=read_json(state/'synthetic-native-video.json');assert len(native['allocations'])==len(native['transfers'])==len(native['saves'])==1
  assert not command('video-delivery-status','--session-id',plan['sessionId'])['storageVerified'];assert command('video-delivery-status','--session-id',plan['sessionId'],'--refresh')['storageVerified']
  other=package('unknown',media/'silent.mp4');plan2=command('video-delivery-plan','--profile','merchant-test','--manifest',other,'--zone-id','video-owned');command('video-delivery-approve','--session-id',plan2['sessionId'],'--fingerprint',plan2['fingerprint'],'--confirm');native['fault']='transfer-timeout';atomic_json(state/'synthetic-native-video.json',native)
  unknown=command('video-delivery-execute','--session-id',plan2['sessionId']);assert unknown['status']=='unknown' and unknown['unknownStage']=='transfer';before=read_json(state/'synthetic-native-video.json');before['fault']=None;atomic_json(state/'synthetic-native-video.json',before);command('video-delivery-status','--session-id',plan2['sessionId'],'--refresh');command('video-delivery-execute','--session-id',plan2['sessionId'],code=2);after=read_json(state/'synthetic-native-video.json');assert all(len(before[k])==len(after[k]) for k in ('allocations','transfers','saves'))
  operation=home/'generic-save.json';atomic_json(operation,{'url':'/rest/sp-product/v0/media-zones/{zoneId}/videos','method':'POST','params':{'zoneId':'video-owned'},'body':{'zoneVideoDTO':{'videoType':1}}});command('task-plan','--profile','merchant-test','--operation',operation,code=2)
  assert file_sha(archive)==sha
  record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedRuntimeAsserted':True,'realPublicDecoderDependencies':True,'realLocalVideoAndCoverDecode':True,'productionMultipartUsedWithSyntheticConnection':True,'multipartOriginalBytesMatch':True,'allocationRequiresParentApproval':True,'saveUsesOriginalJdVideoId':True,'distinctMerchantVideoId':'700','originalJdVideoId':'900','transcodeNotAuditApproval':True,'historicalStatusNotFreshVerification':True,'unknownNotReplayedOrUnlockedByReadback':True,'genericSaveGuarded':True,'independentOriginalReceipts':True,'realMerchantAuthorization':'not-run','realMerchantApi':'not-run','realNetworkVideoUpload':False,'paidGenerationCalls':0,'skuBinding':'not-performed','visualReview':'synthetic assertions only, not commercial acceptance'}
  atomic_json(ROOT/'.agent-work/video-delivery-audit/installed-video-delivery-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
