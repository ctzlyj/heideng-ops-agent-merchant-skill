"""Real fresh installer/installed CLI with a deterministic multi-product GET API."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
SHIM=r'''
import sys,socket
from pathlib import Path
installed=Path(sys.argv[1]);repo=Path(sys.argv[2]);del sys.argv[1:3];sys.path[:0]=[str(installed),str(repo)]
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('business networking forbidden'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('business networking forbidden'))
from heideng_merchant import cli
from heideng_merchant.safety import atomic_json,read_json
from tests.test_shop_material_audit import ShopClient,READ
class Native(ShopClient):
 def __init__(self,state):
  self.state=Path(state);settings=read_json(self.state/'synthetic-shop-settings.json');super().__init__(8191);self.fault=settings.get('fault')
 def ready(self):return False
 def invoke(self,p,url,**kw):
  assert kw.get('method','GET')=='GET','audit attempted business write'
  try:return super().invoke(p,url,**kw)
  finally:atomic_json(self.state/'synthetic-shop-counts.json',{'postCount':len(self.posts),'productReads':self.product_reads,'healthPageReads':self.health_reads,'materialQueries':self.reads,'maxMaterialSkuBatch':max((len(k['params']['skuIds']) for u,k in self.calls if u==READ),default=0)})
cli.OfficialClient=Native
assert Path(cli.__file__).resolve().is_relative_to(installed.resolve())
raise SystemExit(cli.main())
'''

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='whole-shop-installed-') as d:
  home=Path(d);env=clean_environment(home);env['PYTHONUTF8']='1';state=home/'.heideng-merchant';state.mkdir();settings=state/'synthetic-shop-settings.json';atomic_json(settings,{'fault':None})
  r=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',sha],env=env,capture_output=True,timeout=60);assert r.returncode==0
  installed=home/'.codex/skills/heideng-ops-agent-merchant';shim=home/'native-shop.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   r=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),str(ROOT),'--home',str(home),*args],env=env,capture_output=True,timeout=300)
   if r.returncode!=code:atomic_json(ROOT/'.agent-work/shop-material-audit/smoke-failure.json',{'command':args[0],'returncode':r.returncode,'output':(r.stdout+r.stderr).decode('utf-8','replace')})
   assert r.returncode==code,'installed whole-shop command failed; ignored synthetic diagnostic recorded'
   return json.loads(r.stdout)
  command('onboarding');command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  report=command('sku-material-shop-audit','--profile','merchant-smoke');assert report['complete'] and report['summaryOnly'] and report['onSaleProductCount']==9 and report['onSaleSkuCount']==8191 and report['allSiblingSkuCount']==8200 and report['materialObservedSkuCount']==8200 and report['unscoredSkuCount']==1 and report['lowScoreSkuCount']==8190 and not report['scoreCoverageComplete'];assert not any(k.endswith('Ids') for k in report)
  counts=read_json(state/'synthetic-shop-counts.json');assert counts['postCount']==0 and counts['healthPageReads']==82 and counts['maxMaterialSkuBatch']<=50 and counts['materialQueries']==328
  page=command('sku-material-shop-rows','--audit-id',report['auditId'],'--page-size','200');assert page['total']==8191 and len(page['items'])==200 and not page['pageIsWholeShop'];all_rows=command('sku-material-shop-rows','--audit-id',report['auditId'],'--include-offline','--page','41','--page-size','200');assert all_rows['total']==8200 and len(all_rows['items'])==200
  assert command('sku-material-shop-status','--audit-id',report['auditId'])['fingerprint']==report['fingerprint']
  atomic_json(settings,{'fault':'reorder'});assert command('sku-material-shop-audit','--profile','merchant-smoke')['complete']
  atomic_json(settings,{'fault':'product-drift'});assert not command('sku-material-shop-audit','--profile','merchant-smoke')['complete']
  capture=Path(report['reportPath']);saved=read_json(capture);saved['scope']['items'][0]['skuId']='999';atomic_json(capture,saved);command('sku-material-shop-status','--audit-id',report['auditId'],code=2)
  assert file_sha(archive)==sha
  evidence={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedRuntimePathAsserted':True,'businessSocketBlocked':True,'onSaleProductCount':9,'onSaleSkuCount':8191,'allSiblingSkuCount':8200,'observedMaterialsSkuCount':8200,'unscoredSkuCount':1,'unknownScoreNotZero':True,'healthDatasetPasses':1,'healthPageReads':82,'nativeMaterialQueries':328,'maximumNativeMaterialSkuBatch':50,'summaryWithoutThousandsOfIds':True,'pagedTotalsAndOfflineSiblingsVerified':True,'beforeAfterCensusAndReorderVerified':True,'productDriftInvalidatesComplete':True,'captureMutationRejected':True,'postCount':0,'realMerchantAuthorization':'not-run','realMerchantApi':'not-run','paidModelCalls':0,'merchantApi':'deterministic synthetic GET API with business socket blocked; not real native auth/HTTP','portalScoreEquivalence':'unverified','goalComplete':False}
  atomic_json(ROOT/'.agent-work/shop-material-audit/installed-shop-smoke.json',evidence);print(json.dumps(evidence))
if __name__=='__main__':main()
