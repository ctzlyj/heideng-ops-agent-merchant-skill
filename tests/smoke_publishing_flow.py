"""Fresh-installed real CLI/Pillow with 1000-SKU file-fake publication only."""
import copy,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from heideng_merchant.image_runtime import ImageRuntime
from tests.smoke_material_flow import SHIM as MEDIA_SHIM,noise_png
from tests.publish_fixtures import source_product,payload,template,CATEGORY,BRAND

EXTRA=r"""
BaseFakeAPI=FakeAPI
from heideng_merchant.official_transport import transport_for
class PublicationAPI(BaseFakeAPI):
 def plan_execution(self,op,*,profile):return {'transport':'synthetic-file-api','officialVersion':'synthetic-only','selectedOfficialTransport':transport_for('synthetic-cli.exe',profile,op)}
 def invoke(self,p,url,**kw):
  s=read_json(self.path);params=kw.get('params',{});method=kw.get('method','GET')
  if url=='/rest/sp-seller/v0/vender-categories':
   assert method=='GET' and params['sceneType']==3 and isinstance(params['categoryIdList'],list)
   rows=s['businessCategories'];return {'data':rows if params['categoryIdList']==[0] else [r for r in rows if r['categoryId'] in params['categoryIdList']]}
  if url=='/rest/sp-seller/v0/vender-brands':
   assert method=='GET' and params['categoryId']==1348 and params['queryType']==2 and params['authStatus']==2 and params['pageSize']==20
   return {'success':True,'data':[{'brandId':9001,'brandName':'synthetic-brand','authStatus':2}],'paginationData':{'totalItems':1}}
  if url=='/rest/sp-product/v0/product-schemas':
   assert method=='GET' and params=={'lastCategoryId':44207,'scene':'pop'}
   return {'success':True,'data':[json.dumps(s['rules'])]}
  if url in ('/rest/sp-product/v0/product-schemas/validations','/rest/sp-product/v0/product-applies'):
   assert method=='POST' and kw['write_authorized'] is True and kw['expected_shop']['venderId']=='1' and kw['expected_execution']['selectedOfficialTransport']=='official-source-stdin'
   body=kw['body'];assert set(body)=={'scene','schema','productApplyDTO'} and body['scene']=='pop' and body['productApplyDTO']=={'categoryDTO':{'lastCategoryId':44207}}
   components=json.loads(body['schema']);skus=next(r for r in components if r['componentCode']=='SKUS')['value'];assert len(skus)==1000
   assert next(r for r in components if r['componentCode']=='WareTransport')['value']=='12'
   seen=set()
   for index,row in enumerate(skus):
    f={v['componentCode']:v for v in row['value']};assert f['SkuVendorSku']['value']=='M'+str(index) and f['SkuJdprice']['value']=='30.00' and f['SkuStockNum']['value']==index
    seen.add(f['SkuUUid']['value'])
   assert len(seen)==1000
   if url.endswith('/validations'):
    s['validationCount']+=1;s['validationSchema']=body['schema'];atomic_json(self.path,s)
    return {'success':True,'data':{'wareKeeperDetectResultList':[]},'_merchantExecution':kw['expected_execution']}
   assert s['validationSchema']==body['schema'];s['publishCount']+=1;atomic_json(self.path,s)
   if s['publishUnknown']:raise TimeoutError('synthetic accepted publication response lost')
   return {'success':True,'data':{'applyId':300,'productId':400},'_merchantExecution':kw['expected_execution']}
  if method=='POST':kw={**kw,'expected_execution':{'transport':'synthetic-file-api','officialVersion':'synthetic-only'}}
  return super().invoke(p,url,**kw)
cli.OfficialClient=PublicationAPI
raise SystemExit(cli.main())
"""
SHIM=MEDIA_SHIM.replace('raise SystemExit(cli.main())','')+EXTRA

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip'
 with tempfile.TemporaryDirectory(prefix='merchant-publishing-smoke-') as temporary:
  home=Path(temporary);env=clean_environment(home);state=home/'.heideng-merchant';state.mkdir()
  fixture=state/'synthetic-api.json';atomic_json(fixture,{'foreign':False,'categoryStatus':1,'unknown':False,'postCount':0,'images':[],'businessCategories':[{'categoryId':44207,'categoryLevel':4,'categoryName':'synthetic leaf','leafFlag':True,'selectableFlag':True,'parentCategoryId':1348},{'categoryId':1348,'categoryLevel':3,'categoryName':'synthetic third','leafFlag':False,'selectableFlag':True,'parentCategoryId':2}],'rules':template(),'validationCount':0,'publishCount':0,'publishUnknown':False})
  result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',file_sha(archive)],env=env,capture_output=True,timeout=60);assert result.returncode==0
  installed=home/'.codex/skills/heideng-ops-agent-merchant';ImageRuntime(state).ensure();shim=home/'publication-shim.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   result=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=180)
   assert result.returncode==code,'installed publication command failed; raw output not logged'
   return json.loads(result.stdout)
  command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  source=home/'source';source.mkdir();(source/'source.png').write_bytes(noise_png(9));product=source_product(1000);input_file=home/'product.json';atomic_json(input_file,product);package=home/'listing'
  manifest=command('prepare-listing','--product',str(input_file),'--source-root',str(source),'--output',str(package));assert manifest['sourceProduct']==product and len(manifest['skus'])==1000
  manifest['images'][0]['visualReview']='passed';atomic_json(package/'manifest.json',manifest)
  asset=command('material-upload-plan','--profile','merchant-smoke','--image',str(package/manifest['images'][0]['localPath']),'--zone-id','img_synthetic','--category-id','7')['task']
  command('task-approve','--task-id',asset['taskId'],'--fingerprint',asset['fingerprint'],'--confirm');command('task-execute','--task-id',asset['taskId']);command('material-upload-status','--task-id',asset['taskId'],'--refresh')
  schema_file=home/'schema.json';body=payload(product)
  # Same source bytes, actual original fake receipt URL rather than a guessed JFS path.
  body=json.loads(json.dumps(body).replace('jfs/t1/1/synthetic.png','jfs/t1/1/asset-1.png'));atomic_json(schema_file,body)
  specs=home/'specs.json';assets=home/'assets.json';atomic_json(specs,{'sale-prop-100':'color','sale-prop-101':'size'});atomic_json(assets,[{'localPath':manifest['images'][0]['localPath'],'taskId':asset['taskId']}])
  def validated(manifest_path):
   plan=command('publish-validation-plan','--profile','merchant-smoke','--manifest',str(manifest_path),'--schema',str(schema_file),'--spec-map',str(specs),'--asset-bindings',str(assets));task=plan['task'];assert plan['skuCount']==1000
   command('task-execute','--task-id',task['taskId'],code=2);command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId']);assert command('publish-validation-status','--task-id',task['taskId'])['validationPassed'];return task['taskId']
  first=validated(package/'manifest.json');pub=command('publish-plan','--validation-task-id',first)['task'];command('task-execute','--task-id',pub['taskId'],code=2)
  command('task-approve','--task-id',pub['taskId'],'--fingerprint',pub['fingerprint'],'--confirm');command('task-execute','--task-id',pub['taskId']);status=command('publish-status','--task-id',pub['taskId']);assert status['receipt']=={'applyId':'300','productId':'400'} and not status['onlineEffective']
  newer=validated(package/'manifest.json');again=command('publish-plan','--validation-task-id',newer)['task'];assert again['taskId']==pub['taskId'];command('task-execute','--task-id',again['taskId'],code=2);assert read_json(fixture)['publishCount']==1
  copied=home/'copied-listing';shutil.copytree(package,copied);copy_v=validated(copied/'manifest.json');copy_pub=command('publish-plan','--validation-task-id',copy_v)['task'];assert copy_pub['taskId']==pub['taskId'];command('task-execute','--task-id',copy_pub['taskId'],code=2);assert read_json(fixture)['publishCount']==1
  # A genuinely separate declared source package tests unknown acceptance, not retry.
  product2=copy.deepcopy(product);product2['title']='synthetic second declared product';atomic_json(input_file,product2);second=home/'second-listing';m2=command('prepare-listing','--product',str(input_file),'--source-root',str(source),'--output',str(second));m2['images'][0]['visualReview']='passed';atomic_json(second/'manifest.json',m2)
  body2=json.loads(json.dumps(payload(product2)).replace('jfs/t1/1/synthetic.png','jfs/t1/1/asset-1.png'));atomic_json(schema_file,body2);unknown_v=validated(second/'manifest.json');unknown=command('publish-plan','--validation-task-id',unknown_v)['task']
  command('task-approve','--task-id',unknown['taskId'],'--fingerprint',unknown['fingerprint'],'--confirm');s=read_json(fixture);s['publishUnknown']=True;atomic_json(fixture,s);assert command('task-execute','--task-id',unknown['taskId'])['status']=='unknown'
  command('task-execute','--task-id',unknown['taskId'],code=2);assert command('publish-status','--task-id',unknown['taskId'])['receipt'] is None
  assert read_json(fixture)['publishCount']==2 and read_json(fixture)['validationCount']==4 and read_json(fixture)['postCount']==1
  evidence={'status':'passed','archiveSha256':file_sha(archive),'install':'fresh verified ZIP / fresh HOME / real -I -B command processes','imageDecoder':'real isolated Pillow','sourceSkuCount':1000,'allSourceProductFieldsPreserved':True,'validationPostCount':read_json(fixture)['validationCount'],'knownPublicationPostCount':1,'unknownSeparateIntentPostCount':1,'mediaPostCount':1,'sameSourcePackageCannotDuplicateOnNewValidationNonce':True,'copiedPackageKeepsCreationIntentAndCannotDuplicate':True,'flatSameValidationAndPublicationBody':True,'approvalBeforeBothPosts':True,'unknownNotReplayed':True,'onlineEffective':False,'allSkuOnlineVerified':False,'productImagesOnlineVerified':False,'dispatch':'file-fake native API; transport_for selection real, not real official stdin dispatch','realMerchantAuthorization':'not-run','realMerchantWrites':'not-run','paidModelCalls':0,'networkBoundary':'merchant command socket connects disabled, public decoder setup before commands'}
  atomic_json(ROOT/'.agent-work/publishing-smoke/evidence.json',evidence);print(json.dumps(evidence))

if __name__=='__main__':main()
