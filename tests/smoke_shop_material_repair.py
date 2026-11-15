"""Actual installed CLI/module paths; synthetic repair API and original-image HTTP."""
import json,sys,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,json,copy,socket
from pathlib import Path
from unittest.mock import patch
installed,source,home,mode=map(Path,sys.argv[1:5]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import cli,operations,sku_material_repair,sku_material_contract,shop_material_execution,shop_material_execution_contract,shop_material_execution_state,update_gate,distribution
from heideng_merchant.safety import SafetyError,atomic_json
from tests.shop_material_execution_fixtures import Client
from tests.test_sku_materials import material,SkuMaterialTests
from tests.material_fixtures import probe
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (cli,operations,sku_material_repair,sku_material_contract,shop_material_execution,shop_material_execution_contract,shop_material_execution_state,update_gate,distribution))
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
c=Client(53,3);state=home/'.heideng-merchant';recipes=[]
for sku in c.skus:
 if sku['status']==103 and sku['productId']!=20:
  c.materials[str(sku['skuId'])].append(material(sku['skuId'],1002,1,'轻巧便携',5));recipes.append({'productId':sku['productId'],'skuId':sku['skuId'],'slot':'point1','text':'柔软舒适','review':'passed','action':'repair'})
c.materials['101'][0]['status']=5
empty=material(1001,31,1,status=4);empty['imageMaterial']['skuImages']=[];c.materials['1001'].append(empty)
def command(name,*args):return cli.run(cli.parser().parse_args(['--home',str(home),name,*map(str,args)]))
with patch('heideng_merchant.cli.OfficialClient',return_value=c),patch('heideng_merchant.materials.probe_image',side_effect=probe),patch('heideng_merchant.operations.probe_image',side_effect=probe),patch('heideng_merchant.workflows._asset_download',return_value=b'synthetic-original-image'):
 command('shop-connect','--profile','merchant-test','--shop-name','synthetic-store','--vender-id','1');audit=command('sku-material-shop-audit','--profile','merchant-test');before=copy.deepcopy(c.materials)
 s=shop_material_execution.ShopMaterialExecution(state,c);upload=SkuMaterialTests().upload(s,state)
 recipes.extend([{'productId':9,'skuId':101,'slot':'scene2','uploadTaskId':upload,'review':'passed','action':'repair'},{'productId':10,'skuId':1001,'slot':'white','uploadTaskId':upload,'review':'passed','action':'repair'},{'productId':9,'skuId':102,'slot':'point2','text':'轻松收纳','review':'passed'}]);recipe=home/'ready.json';atomic_json(recipe,recipes)
 p=command('shop-material-plan','--audit-id',audit['auditId'],'--changes',recipe);assert p['readyRepairCount']==58 and p['readyChangeCount']==59 and p['chunkCount']==3 and p['onSaleSkuCount']==56 and p['offSaleSiblingCount']==2
 rows=command('shop-material-rows','--plan-id',p['planId'],'--page-size',200);assert rows['total']==56*8 and any(r['state']=='ready-repair' and r['originalContentSha256'] for r in rows['items'])
 command('shop-material-approve','--plan-id',p['planId'],'--fingerprint',p['fingerprint'],'--confirm')
 if str(mode)=='unknown':c.write_fault_on=2
 if str(mode)=='drift':c.materials['101'][-1]['status']=4
 if str(mode)=='drift':
  try:command('shop-material-execute','--plan-id',p['planId'])
  except SafetyError:pass
  else:raise AssertionError('repair audit drift accepted')
  assert not c.posts
 else:
  result=command('shop-material-execute','--plan-id',p['planId'])
  if str(mode)=='unknown':
   assert result['originalOutcomeUnknown'] and result['verifiedRepairCount']==51 and len(c.posts)==2
   c.write_fault_on=None;c.fault=None;assert command('shop-material-status','--plan-id',p['planId'],'--refresh')['originalOutcomeUnknown'];command('shop-material-execute','--plan-id',p['planId']);assert len(c.posts)==2 and distribution.busy(state)
  else:
   assert result['allReadyChangesVerified'] and result['verifiedRepairCount']==58 and result['currentCatalogScopeVerified'] and not result['auditApprovedForWrittenChanges'] and not result['scoreRecalculated'] and result['awaitingMaterialCount']>0
   assert [len(p['skuMaterials']) for p in c.posts]==[50,3,3] and not distribution.busy(state)
   assert c.materials['9001']==before['9001'] and c.materials['9002']==before['9002']
   for sku in ('102','1002'):assert before[sku][0] in c.materials[sku]
 print(json.dumps({'status':'passed','case':str(mode),'installedPathsAsserted':True,'readyRepairs':58,'readyChanges':59,'nativePosts':len(c.posts),'paidGenerationCalls':0,'originalBytesDownload':'synthetic','imagePreflight':'synthetic'}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);out=ROOT/'.agent-work/shop-material-repair-audit';out.mkdir(parents=True,exist_ok=True);results={}
 with tempfile.TemporaryDirectory(prefix='hr-') as d:
  root=Path(d);child=root/'installed.py';child.write_text(CHILD,encoding='utf-8')
  for mode in ('known','unknown','drift'):
   home=root/mode;home.mkdir();env=clean_environment(home);installed=home/'.codex/skills/heideng-ops-agent-merchant'
   for label,args in [('install',[sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]),('chain',[sys.executable,'-I','-X','utf8','-B',child,installed,ROOT,home,mode])]:
    r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180);(out/(mode+'-'+label+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'installed repair smoke failed: '+mode+'-'+label
    if label=='chain':results[mode]=json.loads(r.stdout)
 assert file_sha(archive)==sha
 record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedModulePathsAsserted':True,'originalRootApproval':True,'mixedRepairAndFill':True,'allScopeRemainingGapsReported':True,'sameImageUploadUsedForOwnedProducts':True,'sourceBytesAndPreflight':'synthetic','merchantAuthAndApi':'synthetic-only','paidGenerationCalls':0,'results':results};atomic_json(out/'installed-shop-material-repair-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
