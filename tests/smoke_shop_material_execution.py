"""Actual fresh installed whole-shop CLI; synthetic merchant and media evidence."""
import json,sys,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,json,copy,socket
from pathlib import Path
from unittest.mock import patch
installed,source,home,mode=map(Path,sys.argv[1:5]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import cli,operations,shop_material_execution,shop_material_execution_contract,shop_material_execution_state,update_gate,distribution
from heideng_merchant.safety import read_json,atomic_json
from tests.shop_material_execution_fixtures import Client,changes
from tests.material_fixtures import probe
from tests.test_sku_materials import SkuMaterialTests
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (cli,operations,shop_material_execution,shop_material_execution_contract,shop_material_execution_state,update_gate,distribution))
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
c=Client(53,3) if str(mode)!='image' else Client(1,1);state=home/'.heideng-merchant'
def command(name,*args):return cli.run(cli.parser().parse_args(['--home',str(home),name,*map(str,args)]))
with patch('heideng_merchant.cli.OfficialClient',return_value=c):
 command('shop-connect','--profile','merchant-test','--shop-name','synthetic-store','--vender-id','1')
 if str(mode)=='image':c.materials['101']=[];c.materials['1001']=[]
 audit=command('sku-material-shop-audit','--profile','merchant-test');assert audit['inventorySourceComplete'] and audit['materialSourceComplete'];before=copy.deepcopy(c.materials)
 recipe=home/'ready.json'
 if str(mode)=='image':
  s=shop_material_execution.ShopMaterialExecution(state,c)
  with patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe):upload=SkuMaterialTests().upload(s,state)
  atomic_json(recipe,[{'productId':pid,'skuId':sku,'slot':'white','uploadTaskId':upload,'review':'passed'} for pid,sku in ((9,101),(10,1001))]);slot='white'
 else:atomic_json(recipe,changes(c));slot='point1'
 p=command('shop-material-plan','--audit-id',audit['auditId'],'--changes',recipe,'--target-slots',slot);assert p['summaryOnly'] and 'tasks' not in p and 'scope' not in p
 command('shop-material-approve','--plan-id',p['planId'],'--fingerprint',p['fingerprint'],'--confirm')
 if str(mode)=='unknown':c.write_fault_on=2
 r=command('shop-material-execute','--plan-id',p['planId'])
 if str(mode)=='unknown':
  assert r['originalOutcomeUnknown'] and not r['allReadyChangesVerified'] and len(c.posts)==2
  c.write_fault_on=None;c.fault=None;assert command('shop-material-status','--plan-id',p['planId'],'--refresh')['originalOutcomeUnknown'];command('shop-material-execute','--plan-id',p['planId']);assert len(c.posts)==2 and distribution.busy(state)
 else:
  assert r['allReadyChangesVerified'] and not r['auditApprovedForWrittenChanges'] and r['currentCatalogScopeVerified'] and not r['scoreRecalculated'] and not distribution.busy(state)
  assert [len(post['skuMaterials']) for post in c.posts]==([50,3,3] if str(mode)=='known' else [1,1])
  for sku,original in before.items():
   for row in original:assert row in c.materials[sku]
  status=command('shop-material-status','--plan-id',p['planId']);assert not status['currentCatalogScopeVerified'] and status['catalogHistoricallyMatched']
  first=command('shop-material-rows','--plan-id',p['planId'],'--page-size',2);assert first['total']==(56 if str(mode)=='known' else 2) and len(first['items'])==2
  if str(mode)=='known':
   remaining_audit=command('sku-material-shop-audit','--profile','merchant-test');pending=command('shop-material-plan','--audit-id',remaining_audit['auditId']);assert pending['readyChangeCount']==0 and pending['awaitingMaterialCount']>0 and pending['existingPendingSlotCount']>0 and not pending['noWorkInTargetScope']
 print(json.dumps({'status':'passed','case':str(mode),'installedModulesAsserted':True,'nativePosts':len(c.posts),'onSaleSkuCount':p['onSaleSkuCount'],'originalImageUploadReceiptUsed':str(mode)=='image','unknownNotReplayed':str(mode)=='unknown','scoreRecalculated':False}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);out=ROOT/'.agent-work/shop-material-execution-audit';out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='hs-') as d:
  root=Path(d);child=root/'installed.py';child.write_text(CHILD,encoding='utf-8');results={}
  for mode in ('known','unknown','image'):
   home=root/mode;home.mkdir();env=clean_environment(home);installed=home/'.codex/skills/heideng-ops-agent-merchant'
   def run(args,label):
    r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180);(out/(label+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'installed shop material smoke failed: '+label;return json.loads(r.stdout)
   run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],mode+'-install')
   results[mode]=run([sys.executable,'-I','-X','utf8','-B',child,installed,ROOT,home,mode],mode+'-chain')
  assert file_sha(archive)==sha
  record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedModulePathsAsserted':True,'syntheticMerchantAndNativeApi':True,'mockedImagePreflight':True,'realMerchantAuthorization':'not-run','realMerchantApi':'not-run','paidModelCalls':0,'defaultAllSlotsAndRemainingGaps':True,'wholeScopeOriginalParentApproval':True,'results':results};atomic_json(out/'installed-shop-material-execution-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
