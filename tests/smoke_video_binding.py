"""Fresh installed full video-to-type42 chain; synthetic shop/HTTP only."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from tests.material_fixtures import png
from tests.smoke_video_handoff import PREPARE
from tests.smoke_video_delivery import SHIM as BASE_SHIM
FIELDS="('allocations','saves','transfers','video','fault','materials','posts','binding_fault')"
SHIM=BASE_SHIM.replace('from tests.video_delivery_fixtures import Client','from tests.video_binding_fixtures import Client').replace("super().__init__();self.file", "super().__init__(53);self.file").replace("('allocations','saves','transfers','video','fault')",FIELDS).replace(" def persist(self):", "  self.native.materials=self.materials;self.native.posts=self.posts\n def persist(self):").replace('raise SystemExit(cli.main())',"from heideng_merchant import video_binding,video_binding_contract,video_binding_state\nassert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (video_binding,video_binding_contract,video_binding_state))\nraise SystemExit(cli.main())")

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='hb-') as d:
  home=Path(d);state=home/'.heideng-merchant';env=clean_environment(home)
  def run(args,code=0):
   r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=600)
   if r.returncode!=code:
    out=ROOT/'.agent-work/video-binding-audit';out.mkdir(parents=True,exist_ok=True);(out/'installed-binding-failure.log').write_bytes(r.stdout+r.stderr)
   assert r.returncode==code,'installed native binding smoke failed; ignored synthetic diagnostic retained'
   return r.stdout
  run([sys.executable,'-I','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]);installed=home/'.codex/skills/heideng-ops-agent-merchant';prepare=home/'prepare.py';prepare.write_text(PREPARE,encoding='utf-8');media=home/'media';run([sys.executable,'-I','-B',prepare,installed,home,ROOT/'tests/video_fixture_producer.py',media]);shim=home/'native-binding.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):return json.loads(run([sys.executable,'-I','-B',shim,installed,ROOT,'--home',home,*args],code))
  command('shop-connect','--profile','merchant-test','--shop-name','synthetic-store','--vender-id','1');cover=home/'cover.png';cover.write_bytes(png())
  def upload(name,clip):
   manifest=home/(name+'.json');atomic_json(manifest,{'merchantPackageSchemaVersion':1,'sourceProduct':{'title':'synthetic item'}});info=command('attach-video','--manifest',manifest,'--video',clip,'--cover',cover)['video'];review=home/(name+'-video-review.json');atomic_json(review,{'sha256':info['sha256'],'coverSha256':info['coverSha256'],'listingFingerprint':info['listingFingerprint'],'visualPass':True,'voiceConfirmed':True});command('attach-video','--manifest',manifest,'--video',clip,'--cover',cover,'--review',review);plan=command('video-delivery-plan','--profile','merchant-test','--manifest',manifest,'--zone-id','video-owned');command('video-delivery-approve','--session-id',plan['sessionId'],'--fingerprint',plan['fingerprint'],'--confirm');command('video-delivery-execute','--session-id',plan['sessionId']);return plan['sessionId']
  def binding(session,name):
   preview=command('video-binding-preview','--profile','merchant-test','--product-id',9,'--session-id',session);review=home/(name+'-product-review.json');atomic_json(review,{**preview['identityReviewScope'],'passed':True});return command('video-binding-plan','--profile','merchant-test','--product-id',9,'--session-id',session,'--review',review)
  session=upload('original',media/'with-audio.mp4');native=read_json(state/'synthetic-native-video.json');assert len(native['allocations'])==len(native['transfers'])==len(native['saves'])==1
  for sku,values in native['materials'].items():values.append({'skuId':int(sku),'materialType':42,'order':2,'status':4,'videoMaterial':{'videoFrom':1,'videoId':800,'jdVideoId':801,'indexImage':'jfs/synthetic/preserved.png','title':'existing','duration':1,'tagId':18,'tagOrder':3,'tagName':'other','retainedExtension':'keep'}})
  atomic_json(state/'synthetic-native-video.json',native);plan=binding(session,'original');assert plan['skuCount']==53 and plan['chunkCount']==2;command('video-binding-execute','--plan-id',plan['planId'],code=2);assert not read_json(state/'synthetic-native-video.json')['posts'];command('video-binding-approve','--plan-id',plan['planId'],'--fingerprint',plan['fingerprint'],'--confirm');result=command('video-binding-execute','--plan-id',plan['planId']);assert result['materialFieldsVerified'] and result['relationsVerified'] and not result['auditApproved'];native=read_json(state/'synthetic-native-video.json');assert [len(p['skuMaterials']) for p in native['posts']]==[50,3]
  for values in native['materials'].values():
   assert any(m['materialType']==32 and m['order']==2 for m in values)
   assert any(m['materialType']==42 and m['order']==2 and m['status']==4 and m['videoMaterial']['retainedExtension']=='keep' for m in values)
   for m in values:
    if m['materialType']==42 and m['order']==1:assert m['videoMaterial']['videoId']==700 and m['videoMaterial']['jdVideoId']==900 and m['videoMaterial']['tagId']==17;m['status']=4
  atomic_json(state/'synthetic-native-video.json',native);assert not command('video-binding-status','--plan-id',plan['planId'],'--refresh')['auditApproved'];native=read_json(state/'synthetic-native-video.json');native['video']['status']=4;atomic_json(state/'synthetic-native-video.json',native);assert command('video-binding-status','--plan-id',plan['planId'],'--refresh')['auditApproved'];assert not command('video-binding-status','--plan-id',plan['planId'])['materialFieldsVerified'];command('video-binding-execute','--plan-id',plan['planId']);assert len(read_json(state/'synthetic-native-video.json')['posts'])==2
  # Separate synthetic scenario: external removal of order1, new original local video.
  native=read_json(state/'synthetic-native-video.json')
  for sku,values in native['materials'].items():native['materials'][sku]=[m for m in values if not(m['materialType']==42 and m['order']==1)]
  atomic_json(state/'synthetic-native-video.json',native);session2=upload('unknown',media/'silent.mp4');plan2=binding(session2,'unknown');command('video-binding-approve','--plan-id',plan2['planId'],'--fingerprint',plan2['fingerprint'],'--confirm');native=read_json(state/'synthetic-native-video.json');native['binding_fault']='timeout';atomic_json(state/'synthetic-native-video.json',native);unknown=command('video-binding-execute','--plan-id',plan2['planId']);assert unknown['originalOutcomeUnknown'] and not unknown['materialFieldsVerified'];native=read_json(state/'synthetic-native-video.json');assert len(native['posts'])==3;native['binding_fault']=None;atomic_json(state/'synthetic-native-video.json',native);assert command('video-binding-status','--plan-id',plan2['planId'],'--refresh')['originalOutcomeUnknown'];command('video-binding-execute','--plan-id',plan2['planId']);assert len(read_json(state/'synthetic-native-video.json')['posts'])==3
  op=home/'generic.json';atomic_json(op,{'url':'/rest/sp-product/v0/sku-materials/batch','method':'POST','body':{'skuMaterials':[]},'skillId':'jdo-api-830'});command('task-plan','--profile','merchant-test','--operation',op,code=2)
  assert file_sha(archive)==sha
  record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedBindingModulesAsserted':True,'realPublicDecoderAndRealLocalMedia':True,'productionMultipartWithSyntheticConnection':True,'fullSkuCount':53,'chunks':[50,3],'sourceVideoId':700,'sourceJdVideoId':900,'actualCategoryTag':17,'preservedImagesAndVideoOrder2':True,'literalHostProductIdentityReview':'synthetic-only','independentParentApproval':True,'separateTranscodeVideoMaterialAndRelationAudit':True,'historicalNotFreshVerified':True,'unknownStoppedBeforeSecondChunk':True,'unknownNotReplayedByMatchingReadback':True,'nativePostCountIncludingUnknown':3,'realMerchantAuthorization':'not-run','realMerchantApi':'not-run','realNetworkUpload':False,'paidModelCalls':0,'scoreRecalculated':False}
  atomic_json(ROOT/'.agent-work/video-binding-audit/installed-video-binding-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
