"""Fresh-HOME real install/CLI plus synthetic native API, never real auth/write."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from tests.test_sku_materials import Client
from tests.material_fixtures import png
from heideng_merchant.image_runtime import ImageRuntime

SHIM=r'''
import sys,socket
from pathlib import Path
installed=Path(sys.argv[1]);repo=Path(sys.argv[2]);del sys.argv[1:3];sys.path[:0]=[str(installed),str(repo)]
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline socket blocked'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline socket blocked'))
from heideng_merchant import cli
from heideng_merchant.safety import read_json,atomic_json
from heideng_merchant.official_transport import transport_for
from tests.test_sku_materials import Client
class Native(Client):
 def __init__(self,state):
  self.fixture=Path(state)/'synthetic-material-api.json';saved=read_json(self.fixture);super().__init__(len(saved['skus']));self.skus=saved['skus'];self.materials=saved['materials'];self.images=saved['images'];self.posts=saved['posts'];self.fault=saved.get('fault');self.reads=saved.get('reads',0)
 def ready(self):return False
 def plan_execution(self,op,*,profile):return {'transport':transport_for(Path('synthetic.exe'),profile,op),'officialVersion':'0.3.7','boundary':'synthetic'}
 def invoke(self,p,url,**kw):
  try:return super().invoke(p,url,**kw)
  finally:atomic_json(self.fixture,{'skus':self.skus,'materials':self.materials,'images':self.images,'posts':self.posts,'fault':self.fault,'reads':self.reads})
cli.OfficialClient=Native
assert Path(cli.__file__).resolve().is_relative_to(installed.resolve())
raise SystemExit(cli.main())
'''

def main():
 bundle=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';expected=file_sha(bundle)
 with tempfile.TemporaryDirectory(prefix='merchant-sku-material-install-') as temporary:
  home=Path(temporary);env=clean_environment(home);env['PYTHONUTF8']='1';archive=home/'input.zip';archive.write_bytes(bundle.read_bytes());state=home/'.heideng-merchant';state.mkdir();c=Client(1000);fixture=state/'synthetic-material-api.json';atomic_json(fixture,{'skus':c.skus,'materials':c.materials,'images':[],'posts':[],'fault':None})
  ImageRuntime(state).ensure() # Public Pillow runtime, before socket-disabled commands.
  r=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',expected],env=env,capture_output=True,timeout=60);assert r.returncode==0,'fresh isolated install failed'
  installed=home/'.codex/skills/heideng-ops-agent-merchant';shim=home/'synthetic-native.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   r=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),str(ROOT),'--home',str(home),*args],env=env,capture_output=True,timeout=300)
   if r.returncode!=code:atomic_json(ROOT/'.agent-work/information-score-audit/smoke-failure.json',{'command':args[0],'returncode':r.returncode,'output':(r.stdout+r.stderr).decode('utf-8','replace')})
   assert r.returncode==code,'installed SKU material command failed; ignored synthetic diagnostic recorded'
   return json.loads(r.stdout)
  command('onboarding');command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  report=command('sku-material-audit','--profile','merchant-smoke','--product-id','9','--include-health');assert report['skuCount']==1000 and report['complete'] and len(report['unscoredSkuIds'])==999 and report['portalScoreEquivalent'] is None
  image=home/'sample.png';image.write_bytes(png());upload=command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_test','--category-id','7')['task'];command('task-approve','--task-id',upload['taskId'],'--fingerprint',upload['fingerprint'],'--confirm');command('task-execute','--task-id',upload['taskId']);assert command('material-upload-status','--task-id',upload['taskId'],'--refresh')['storageVerified']
  changes=[]
  for row in c.skus:changes.extend([{'skuId':row['skuId'],'slot':'white','uploadTaskId':upload['taskId'],'review':'passed'},{'skuId':row['skuId'],'slot':'point1','text':'轻巧便携','review':'passed'}])
  change_file=home/'changes.json';atomic_json(change_file,changes);plan=command('sku-material-plan','--profile','merchant-smoke','--product-id','9','--changes',str(change_file));assert plan['skuCount']==1000 and plan['changeCount']==2000 and len(plan['tasks'])==20
  command('sku-material-execute','--plan-id',plan['planId'],code=2);assert not read_json(fixture)['posts']
  command('sku-material-approve','--plan-id',plan['planId'],'--fingerprint',plan['fingerprint'],'--confirm','--ttl-seconds','900');result=command('sku-material-execute','--plan-id',plan['planId']);assert result['verifiedChunkCount']==20 and result['materialFieldsVerified'] and not result['auditApproved'] and not result['scoreRecalculated']
  saved=read_json(fixture);assert len(saved['posts'])==20 and sum(len(b['skuMaterials']) for b in saved['posts'])==1000
  for task in plan['tasks']:
   t=read_json(state/'tasks'/f"{task['taskId']}.json");assert t['scope']['officialExecution']['transport']=='official-source-stdin'
  repeated=command('sku-material-plan','--profile','merchant-smoke','--product-id','9','--changes',str(change_file));assert repeated['planId']==plan['planId'];command('sku-material-execute','--plan-id',plan['planId']);assert len(read_json(fixture)['posts'])==20
  saved=read_json(fixture);saved['skus'].reverse();atomic_json(fixture,saved);assert command('sku-material-status','--plan-id',plan['planId'],'--refresh')['materialFieldsVerified']
  saved=read_json(fixture);last=str(saved['skus'][0]['skuId']);saved['materials'][last][0]['imageMaterial']['skuImages'][0]['imgUrl']='jfs/t1/preserved-drift.png';atomic_json(fixture,saved);drift=command('sku-material-status','--plan-id',plan['planId'],'--refresh');assert not drift['materialFieldsVerified'] and drift['verifiedChunkCount']==19;command('sku-material-execute','--plan-id',plan['planId']);assert len(read_json(fixture)['posts'])==20
  assert file_sha(bundle)==file_sha(archive)==expected
  record={'status':'passed','archiveSha256':expected,'freshHomeInstall':True,'installedRuntimePathAsserted':True,'socketNetworkBlocked':True,'skuCount':1000,'filledSlotCount':2000,'chunkSize':50,'nativeMaterialPostCount':20,'originalImageUploadCount':1,'wholePlanApprovalCount':1,'approvalBeforePostRequired':True,'deadlineStdinTransportSelectedForEveryChunk':True,'samePlanResumedWithoutNewPost':True,'skuAndMaterialResponseReorderAccepted':True,'preservedLastSkuOrderDriftRejected':True,'unknownCoveredByIsolatedUnitTests':True,'pendingAuditNotClaimedApproved':True,'portalScoreEquivalence':'unverified','scoreRecalculated':False,'realMerchantAuthorization':'not-run','realMerchantWrites':'not-run','paidModelCalls':0,'officialDispatch':'transport selection helper + synthetic boundary; live schema and authenticated stdin dispatch not tested by this smoke'}
  atomic_json(ROOT/'.agent-work/information-score-audit/installed-sku-material-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
