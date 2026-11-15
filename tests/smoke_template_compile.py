"""Installed automatic rule-only 1000-SKU workflow, entirely synthetic HTTP."""
import copy,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,file_sha,read_json
from tests.test_template_compile import raw_source

SHIM=r'''
import sys,json,copy,socket
from pathlib import Path
installed=sys.argv.pop(1);sys.path.insert(0,installed)
import heideng_merchant.cli as cli
from heideng_merchant.safety import read_json,atomic_json
from heideng_merchant.official_transport import transport_for
class Native:
 def __init__(self,state):self.path=Path(state)/'synthetic-native.json'
 def identity(self,profile):
  assert profile=='merchant-smoke'
  return {'venderId':'1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
 def plan_execution(self,op,*,profile):return {'transport':'synthetic-file-api','officialVersion':'synthetic-only','selectedOfficialTransport':transport_for('synthetic-cli.exe',profile,op)}
 def invoke(self,profile,url,**kwargs):
  self.identity(profile);s=read_json(self.path);method=kwargs.get('method','GET');params=kwargs.get('params',{})
  if url=='/rest/sp-product/v0/products/{productId}':
   assert method=='GET' and str(params['productId'])=='100';data=copy.deepcopy(s['product'])
   if s['online']:data['productInfo']['productDetailDesc']=s['acceptedHtml']
   return {'success':True,'data':data}
  if url=='/rest/sp-product/v0/skus':
   assert method=='GET' and params['productIdList']=='100';page=params['page'];size=params['pageSize'];rows=s['product']['skuList']
   return {'success':True,'data':rows[(page-1)*size:page*size],'paginationData':{'totalItems':len(rows)}}
  if url=='/rest/sp-product/v0/product-schemas':
   assert method=='GET' and params['scene']=='pop';return {'success':True,'data':[json.dumps(s['raw'])]}
  if url=='/rest/sp-product/v0/product-apply/{applyId}':
   assert method=='GET' and str(params['applyId'])=='300';data=copy.deepcopy(s['product']);data['productInfo']['productDetailDesc']=s['acceptedHtml'];data['applyId']=300;return {'success':True,'data':data}
  if url in ('/rest/sp-product/v0/product-schemas/validations','/rest/sp-product/v0/product-applies'):
   assert method=='POST' and kwargs['write_authorized'] and kwargs['expected_shop']['venderId']=='1'
   body=kwargs['body'];assert set(body)=={'scene','schema','productApplyDTO'} and body['productApplyDTO']=={'productId':100,'categoryDTO':{'lastCategoryId':456}};schema=json.loads(body['schema']);assert len(schema[3]['value'])==1000
   assert 'productDetailField' not in body['schema'] and 'childrenComponents' not in body['schema'] and 'tipsDetailList' not in body['schema']
   for i,row in enumerate(schema[3]['value']):
    f={r['componentCode']:r for r in row['value']};assert f['SkuId']['value']==f['SkuUUid']['value']==str(2001+i);assert f['SkuVendorSku']['value']=='A&B-'+str(i);assert f['SkuJdprice']['value']=='30.00' and f['SkuStockNum']['value']==i;assert f['FutureSku']['value']==s['product']['skuList'][i]['future']
   assert schema[-1]['value']==s['product']['future'];html=schema[2]['value'][0]['properties'][0]['value']
   if url.endswith('/validations'):
    s['validations']+=1;s['validatedBody']=body;atomic_json(self.path,s);return {'success':True,'data':{'wareKeeperDetectResultList':[]},'_merchantExecution':kwargs['expected_execution']}
   assert s['validatedBody']==body;s['posts']+=1;s['acceptedHtml']=html;atomic_json(self.path,s);return {'success':True,'data':{'applyId':300,'productId':100},'_merchantExecution':kwargs['expected_execution']}
  raise AssertionError('unexpected synthetic route')
def blocked(*a,**k):raise RuntimeError('synthetic merchant command forbids network')
socket.socket.connect=blocked;socket.create_connection=blocked
cli.OfficialClient=Native
raise SystemExit(cli.main())
'''

def main():
 original=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';expected=file_sha(original)
 with tempfile.TemporaryDirectory(prefix='merchant-template-smoke-') as temporary:
  home=Path(temporary);archive=home/'input.zip';archive.write_bytes(original.read_bytes());env=clean_environment(home);env['PYTHONUTF8']='1';state=home/'.heideng-merchant';state.mkdir()
  raw,product=raw_source(1000);fixture=state/'synthetic-native.json';atomic_json(fixture,{'raw':raw,'product':product,'posts':0,'validations':0,'online':False,'acceptedHtml':''})
  result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',expected],env=env,capture_output=True,timeout=60);assert result.returncode==0
  installed=home/'.codex/skills/heideng-ops-agent-merchant';shim=home/'native-shim.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   r=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=240)
   if r.returncode!=code:
    from heideng_merchant.safety import redact
    atomic_json(ROOT/'.agent-work/template-compile-audit/smoke-command-failure.json',{'command':args[0],'returncode':r.returncode,'diagnostic':redact((r.stdout+r.stderr).decode('utf-8','replace'))})
   assert r.returncode==code,'installed automatic native command failed; ignored diagnostic recorded'
   return json.loads(r.stdout)
  command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  cap=command('product-schema','--profile','merchant-smoke','--product-id','100');assert cap['schemaSkuRowCount']==0
  baseline=command('schema-edit-prepare','--capture-id',cap['captureId']);again=command('schema-edit-prepare','--capture-id',cap['captureId']);assert baseline['baselineId']==again['baselineId'] and baseline['skuCount']==1000
  compiled=command('schema-compile','--capture-id',cap['captureId']);assert compiled['schemaSkuRowCount']==1000 and len(compiled['imageTargets'])==1001 and compiled['scope']['schemaCompiler']['originalCaptureId']==cap['captureId'];assert command('schema-capture-status','--capture-id',cap['captureId'])['schemaSkuRowCount']==0
  changes=home/'changes.json';atomic_json(changes,[{'pointer':'/2/value/0/properties/0/value','html':'<div>New synthetic detail</div>','assetTaskIds':[]}])
  def validate():
   plan=command('schema-edit-validation-plan','--baseline-id',baseline['baselineId'],'--changes',str(changes));task=plan['task'];command('task-execute','--task-id',task['taskId'],code=2);command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId']);return task['taskId']
  validation=validate();task=command('schema-edit-plan','--validation-task-id',validation)['task'];command('task-execute','--task-id',task['taskId'],code=2);command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId'])
  status=command('schema-edit-status','--task-id',task['taskId'],'--refresh');assert status['pendingFieldsVerified'] and not status['onlineEffective'];assert not command('schema-edit-online','--task-id',task['taskId'])['onlineEffective']
  newer=validate();old=command('schema-edit-plan','--validation-task-id',newer)['task'];assert old['taskId']==task['taskId'];command('task-execute','--task-id',old['taskId'],code=2);assert read_json(fixture)['posts']==1
  s=read_json(fixture);s['online']=True;s['product']['skuList'].reverse();atomic_json(fixture,s);assert command('schema-edit-online','--task-id',task['taskId'])['onlineEffective']
  s=read_json(fixture);s['product']['skuList'][0]['stockNum']+=1;atomic_json(fixture,s);assert not command('schema-edit-online','--task-id',task['taskId'])['onlineEffective']
  assert file_sha(archive)==file_sha(original)==expected
  record={'status':'passed','archiveSha256':expected,'skuCount':1000,'originalRuleTemplateSkuRows':0,'materializedImageSlots':1001,'handwrittenSchemaOrBindingsOrSaleSources':False,'originalCaptureRetained':True,'automaticBaselineReentrantSameIntent':True,'validationPostCount':2,'formalEditPostCount':1,'recompileAndNewValidationDoNotRepeatFormalPost':True,'wholeNativeFieldsAndUnknownValuesPreserved':True,'pendingAndOnlineSeparated':True,'onlineSkuReorderAccepted':True,'lastNativeSkuStockDriftRejected':True,'inputArchivePinned':True,'remotePixelsVerified':False,'realMerchantAuthorization':'not-run','realMerchantWrites':'not-run','paidModelCalls':0,'http':'file-fake native API, merchant-command socket blocked','officialDispatch':'real transport selection helper; not real authenticated native stdin dispatch'}
  atomic_json(ROOT/'.agent-work/template-compile-audit/installed-template-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
