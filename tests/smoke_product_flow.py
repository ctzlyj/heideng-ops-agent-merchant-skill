"""Fresh-installed, cross-process native-price flow with a file-backed fake API only."""
import json,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
root=Path(__file__).resolve().parents[1]
SHIM=r'''
import copy,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1))
from heideng_merchant import cli
from heideng_merchant.safety import read_json,atomic_json
class FakeAPI:
 def __init__(self,state):self.path=Path(state)/'synthetic-api.json'
 def identity(self,profile):return {'venderId':'1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
 def invoke(self,profile,url,**kw):
  state=read_json(self.path);method=kw.get('method','GET')
  if method=='PATCH':
   body=kw['body'];assert body['scene']=='pop' and body['opType']==3 and body['applyId']=='100' and body['productInfo']['productId']==100 and body['productInfo']['categoryDetail']['lastCategoryId']==456
   assert body['productApplyDTO']['id']=='100' and len(body['patchOperationList'])==1
   patch=body['patchOperationList'][0];assert patch['path']=='skus[skuId==2001]';component=json.loads(patch['value']);assert component['componentCode']=='SkuJdprice' and isinstance(component['value'],str)
   state['patchCount']+=1;state['pending']=component['value'];atomic_json(self.path,state)
   if state['unknown']:raise TimeoutError('synthetic-response-loss')
   return {'success':True,'data':{'id':'100'}}
  assert method=='GET' and kw['params']['scene']=='pop'
  if '/product-apply/' in url:return {'data':{'productInfo':{'productId':100},'skuList':[{'skuId':2001,'productId':100,'priceInfo':{'jdPrice':state['pending']}}],'applyInfo':{'bossAuditStatus':-1}}}
  assert '{productId}' in url
  return {'data':{'productId':100,'categoryDTO':{'lastCategoryId':456},'skuList':[{'skuId':2001,'productId':100,'priceInfo':{'jdPrice':state['online']}}]}}
cli.OfficialClient=FakeAPI
import socket
socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('network-disabled'))
socket.socket.connect=socket.create_connection
raise SystemExit(cli.main())
'''
archive=root/'dist'/'heideng-ops-agent-merchant-0.1.0.zip'
with tempfile.TemporaryDirectory(prefix='merchant-product-smoke-') as directory:
 home=Path(directory);env=clean_environment(home);shim=home/'fake-api-shim.py';shim.write_text(SHIM,encoding='utf-8');state=home/'.heideng-merchant';state.mkdir()
 fixture=state/'synthetic-api.json';atomic_json(fixture,{'online':'29.90','pending':'29.90','patchCount':0,'unknown':False})
 install=subprocess.run([sys.executable,'-I',str(root/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',file_sha(archive)],env=env,capture_output=True,timeout=60);assert install.returncode==0
 installed=home/'.codex'/'skills'/'heideng-ops-agent-merchant'
 def command(*args,exit_code=0):
  process=subprocess.run([sys.executable,'-I',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=30)
  assert process.returncode==exit_code,'installed command unexpected exit';return json.loads(process.stdout)
 command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
 changes=home/'changes.json';atomic_json(changes,[{'skuId':'2001','jdPrice':'20.00'}]);plan=command('price-plan','--profile','merchant-smoke','--product-id','100','--changes',str(changes));task=plan['task'];assert task['planningEvidence']['responseSha256']
 command('task-execute','--task-id',task['taskId'],exit_code=2);assert read_json(fixture)['patchCount']==0
 command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');submitted=command('task-execute','--task-id',task['taskId']);assert submitted['status']=='submitted'
 pending=command('price-status','--task-id',task['taskId'],'--refresh','pending');assert pending['phase']=='application-values-confirmed' and not pending['onlineEffective']
 assert not command('price-status','--task-id',task['taskId'],'--refresh','online')['onlineEffective']
 data=read_json(fixture);data['online']='20.00';atomic_json(fixture,data);assert command('price-status','--task-id',task['taskId'],'--refresh','online')['onlineEffective']
 command('task-execute','--task-id',task['taskId'],exit_code=2);assert read_json(fixture)['patchCount']==1
 atomic_json(changes,[{'skuId':'2001','jdPrice':'21.00'}]);unknown=command('price-plan','--profile','merchant-smoke','--product-id','100','--changes',str(changes))['task'];command('task-approve','--task-id',unknown['taskId'],'--fingerprint',unknown['fingerprint'],'--confirm')
 data=read_json(fixture);data['unknown']=True;atomic_json(fixture,data);assert command('task-execute','--task-id',unknown['taskId'])['status']=='unknown'
 assert command('price-status','--task-id',unknown['taskId'],'--refresh','pending')['phase']=='unknown'
 data=read_json(fixture);data['online']='21.00';atomic_json(fixture,data);assert command('price-status','--task-id',unknown['taskId'],'--refresh','online')['phase']=='unknown'
 atomic_json(changes,[{'skuId':'2001','jdPrice':'22.00'}]);command('price-plan','--profile','merchant-smoke','--product-id','100','--changes',str(changes),exit_code=2);command('task-execute','--task-id',unknown['taskId'],exit_code=2);assert read_json(fixture)['patchCount']==2
record={'status':'passed','install':'fresh verified ZIP in isolated HOME','commandProcesses':'real Python -I subprocesses','api':'file-backed fake, network disabled in test commands','approvalBeforeWrite':True,'nativeFlatPatch':True,'pendingNotOnline':True,'onlineReadback':True,'knownRequestPatchCount':1,'unknownRequestIntentCount':1,'unknownTargetMatchDoesNotUnlock':True,'realMerchantAPI':'not-run','realMerchantWrites':'not-run','modelCalls':0,'archiveSha256':file_sha(archive)}
output=root/'.agent-work'/'product-smoke';output.mkdir(parents=True,exist_ok=True);atomic_json(output/'installed-flow-evidence.json',record);print(json.dumps(record))
