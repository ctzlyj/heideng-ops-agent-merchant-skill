"""Fresh installed 1000-SKU source-backed full edit, synthetic HTTP only."""
import copy,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from heideng_merchant.image_runtime import ImageRuntime
from tests.smoke_material_flow import SHIM as MEDIA_SHIM,noise_png
from tests.edit_fixtures import setup

EXTRA=r'''
BaseFakeAPI=FakeAPI
from heideng_merchant.official_transport import transport_for
class FullEditAPI(BaseFakeAPI):
 def plan_execution(self,op,*,profile):return {'transport':'synthetic-file-api','officialVersion':'synthetic-only','selectedOfficialTransport':transport_for('synthetic-cli.exe',profile,op)}
 def invoke(self,p,url,**kw):
  s=read_json(self.path);method=kw.get('method','GET');params=kw.get('params',{})
  if url=='/rest/sp-product/v0/products/{productId}':
   assert method=='GET' and params=={'productId':100,'scene':'pop'};return {'success':True,'data':s['product']}
  if url=='/rest/sp-product/v0/skus':
   assert method=='GET' and params['productIdList']=='100';size=params['pageSize'];page=params['page'];return {'success':True,'data':s['product']['skuList'][(page-1)*size:page*size],'paginationData':{'totalItems':len(s['product']['skuList'])}}
  if url=='/rest/sp-product/v0/product-schemas':
   assert method=='GET' and params=={'productId':100,'lastCategoryId':456,'scene':'pop'};return {'success':True,'data':[json.dumps(s['schema'])]}
  if url=='/rest/sp-product/v0/product-apply/{applyId}':
   assert method=='GET' and params=={'applyId':500,'scene':'pop'};return {'success':True,'data':{'applyId':500,**s['pending']}}
  if url in ('/rest/sp-product/v0/product-schemas/validations','/rest/sp-product/v0/product-applies'):
   assert method=='POST' and kw['write_authorized'] and kw['expected_execution']['selectedOfficialTransport']=='official-source-stdin';body=kw['body'];assert set(body)=={'scene','schema','productApplyDTO'} and body['productApplyDTO']=={'productId':100,'categoryDTO':{'lastCategoryId':456}}
   schema=json.loads(body['schema']);rows=next(r for r in schema if r['componentCode']=='SKUS')['value'];assert len(rows)==1000
   for i,row in enumerate(rows):
    fields={r['componentCode']:r for r in row['value']};assert set([r['componentCode'] for r in row['value'][:2]])=={'SkuId','SkuUUid'};assert fields['SkuId']['value']==fields['SkuUUid']['value']==str(2001+i);assert fields['SkuVendorSku']['value']=='M'+str(i) and fields['SkuJdprice']['value']=='30.00' and fields['SkuStockNum']['value']==i
   assert schema[-1]['value']=={'opaque':[1,'retain']}
   if url.endswith('/validations'):
    s['validationCount']+=1;s['validatedSchema']=body['schema'];atomic_json(self.path,s);return {'success':True,'data':{},'_merchantExecution':kw['expected_execution']}
   assert body['schema']==s['validatedSchema'];s['editCount']+=1;s['sentSchema']=schema;pending=copy.deepcopy(s['product']);pending['material']['mainImages'][0]['imgUrl']=schema[1]['value'][0]['properties'][2]['value'];pending['desc']=schema[3]['value'][0]['properties'][0]['value']
   for source,row in zip(pending['skuList'],rows):source['image']['imgUrl']=next(f for f in row['value'] if f['componentCode']=='SkuMainImage')['value'][0]['properties'][2]['value']
   s['pending']=pending;atomic_json(self.path,s)
   if s.get('editUnknown'):raise TimeoutError('synthetic accepted edit reply lost')
   return {'success':True,'data':{'applyId':500,'productId':100},'_merchantExecution':kw['expected_execution']}
  if method=='POST':kw={**kw,'expected_execution':{'transport':'synthetic-file-api','officialVersion':'synthetic-only'}}
  return super().invoke(p,url,**kw)
cli.OfficialClient=FullEditAPI
'''
SHIM=MEDIA_SHIM.replace('cli.OfficialClient=FakeAPI',EXTRA)

def main():
 archive_source=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip'
 with tempfile.TemporaryDirectory() as t:
  home=Path(t);archive=home/'pinned-input.zip';shutil.copyfile(archive_source,archive);env=clean_environment(home);env['PYTHONUTF8']='1';state=home/'.heideng-merchant';fixture=state/'synthetic-api.json'
  generator=home/'generator';generator.mkdir();c,_,cap,bindings,sales=setup(generator,1000)
  atomic_json(fixture,{'foreign':False,'categoryStatus':1,'images':[],'postCount':0,'nextId':1,'unknown':False,'product':c.product,'schema':c.schema,'validationCount':0,'editCount':0,'editUnknown':False})
  result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',file_sha(archive)],env=env,capture_output=True,timeout=60);assert result.returncode==0
  installed=home/'.codex/skills/heideng-ops-agent-merchant';ImageRuntime(state).ensure();shim=home/'edit-shim.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   result=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=240)
   if result.returncode!=code:
    from heideng_merchant.safety import redact
    atomic_json(ROOT/'.agent-work/full-edit-smoke/last-failure.json',{'command':args[0],'returncode':result.returncode,'expected':code,'diagnostic':redact((result.stdout+result.stderr).decode('utf-8','replace')[-4096:])})
   assert result.returncode==code,'installed full-edit command failed; diagnostic kept in ignored audit file'
   return json.loads(result.stdout)
  command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  def upload(seed):
   image=home/('new-'+str(seed)+'.png');image.write_bytes(noise_png(seed));task=command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_synthetic','--category-id','7')['task'];command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId']);command('material-upload-status','--task-id',task['taskId'],'--refresh');return task['taskId']
  def baseline():
   cap=command('product-schema','--profile','merchant-smoke','--product-id','100');assert len(cap['scope']['productDetail']['skuList'])==1000;files=[]
   for name,obj in (('schema',cap['scope']['schema']),('bindings',bindings),('sales',sales)):
    path=home/(name+'.json');atomic_json(path,obj);files.append(str(path))
   base=command('schema-edit-baseline','--capture-id',cap['captureId'],'--schema',files[0],'--bindings',files[1],'--sale-sources',files[2]);assert base['skuIdentityMappingVerified'] and base['skuCount']==1000;return cap,base
  def validation(base,changes):
   path=home/'changes.json';atomic_json(path,changes);task=command('schema-edit-validation-plan','--baseline-id',base['baselineId'],'--changes',str(path))['task'];command('task-execute','--task-id',task['taskId'],code=2);command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId']);return task['taskId']
  asset=upload(11);cap,base=baseline();changes=[{'pointer':p['pointer'],'assetTaskId':asset} for p in cap['imageTargets']];assert len(changes)==1001
  html='<div>Revised original detail<img src="https://img14.360buyimg.com/imgzone/jfs/t1/1/asset-1.png"></div>';changes.append({'pointer':'/3/value/0/properties/0/value','html':html,'assetTaskIds':[asset]})
  v=validation(base,changes);edit=command('schema-edit-plan','--validation-task-id',v)['task'];command('task-execute','--task-id',edit['taskId'],code=2);command('task-approve','--task-id',edit['taskId'],'--fingerprint',edit['fingerprint'],'--confirm');command('task-execute','--task-id',edit['taskId']);assert not command('schema-edit-status','--task-id',edit['taskId'])['onlineEffective']
  pending=command('schema-edit-status','--task-id',edit['taskId'],'--refresh');assert pending['pendingFieldsVerified'];assert not command('schema-edit-online','--task-id',edit['taskId'])['onlineEffective']
  # Original intent is stable across a fresh validation nonce, never a second POST.
  v2=validation(base,changes);again=command('schema-edit-plan','--validation-task-id',v2)['task'];assert again['taskId']==edit['taskId'];command('task-execute','--task-id',again['taskId'],code=2)
  s=read_json(fixture);s['product']=copy.deepcopy(s['pending']);atomic_json(fixture,s);assert command('schema-edit-online','--task-id',edit['taskId'])['onlineEffective']
  # Native row order can differ without swapping any SKU's identity or values.
  s=read_json(fixture);s['product']['skuList'].reverse();atomic_json(fixture,s);assert command('schema-edit-online','--task-id',edit['taskId'])['allSkuOnlineVerified']
  s=read_json(fixture);s['product']['skuList'][-1]['stockNum']=99999;atomic_json(fixture,s);assert not command('schema-edit-online','--task-id',edit['taskId'])['onlineEffective']
  s=read_json(fixture);s['product']=copy.deepcopy(s['pending']);s['product']['skuList'][-1]['saleAttrs'][0]['attrId']=999;atomic_json(fixture,s);assert not command('schema-edit-online','--task-id',edit['taskId'])['onlineEffective']
  s=read_json(fixture);s['product']=copy.deepcopy(s['pending']);atomic_json(fixture,s)
  # Next explicit edit captures current original values; its acceptance becomes unknown.
  s=read_json(fixture)
  for binding in bindings:
   parts=binding['schemaPointer'].split('/')[1:];target=s['schema'];sent=s['sentSchema']
   for key in parts[:-1]:target=target[int(key)] if isinstance(target,list) else target[key];sent=sent[int(key)] if isinstance(sent,list) else sent[key]
   target[parts[-1]]=copy.deepcopy(sent[parts[-1]])
  atomic_json(fixture,s);asset2=upload(12);cap2,base2=baseline();unknown_v=validation(base2,[{'pointer':cap2['imageTargets'][0]['pointer'],'assetTaskId':asset2}]);unknown=command('schema-edit-plan','--validation-task-id',unknown_v)['task'];command('task-approve','--task-id',unknown['taskId'],'--fingerprint',unknown['fingerprint'],'--confirm');s=read_json(fixture);s['editUnknown']=True;atomic_json(fixture,s);assert command('task-execute','--task-id',unknown['taskId'])['status']=='unknown';assert command('schema-edit-status','--task-id',unknown['taskId'],'--refresh')['phase']=='unknown';command('schema-edit-online','--task-id',unknown['taskId'],code=2);command('task-execute','--task-id',unknown['taskId'],code=2)
  assert read_json(fixture)['editCount']==2
  evidence={'status':'passed','archiveSha256':file_sha(archive),'install':'fresh verified ZIP/fresh HOME/real -I -B commands','decoder':'real isolated Pillow','skuCount':1000,'existingImageSlots':1001,'realSkuIdentityAndCompleteCodePriceStock':True,'unknownBusinessBlobPreserved':True,'nativeFieldDeclarationsAndAllValuesSourceBound':True,'knownEditPostCount':1,'unknownSeparateEditPostCount':1,'sameIntentNewValidationNonceNoDuplicate':True,'originalApplyPendingCompleteFieldsVerified':True,'onlineAndPendingSeparated':True,'nativeSkuReorderAcceptedWithoutWrongMapping':True,'lastSkuFieldDriftRejected':True,'lastSkuAttributeIdentityDriftRejected':True,'inputArchivePinnedThroughoutInstall':True,'unknownNotReplayedOrResolvedByTargetMatch':True,'remotePixelsVerified':False,'realMerchantAuthorization':'not-run','realMerchantWrites':'not-run','paidModelCalls':0,'dispatch':'file-fake API; real transport selection helper; not real official network dispatch'}
  atomic_json(ROOT/'.agent-work/full-edit-smoke/evidence.json',evidence);print(json.dumps(evidence))
if __name__=='__main__':main()
