"""Installed CLI, real Pillow, file-fake schemas and 1000-SKU prices. No live shop."""
import copy, json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from heideng_merchant.image_runtime import ImageRuntime
from tests.smoke_material_flow import SHIM as MATERIAL_SHIM, noise_png
from tests.test_product_schema import img_component

EXTRA=r"""
BaseFakeAPI=FakeAPI
from heideng_merchant.official_transport import transport_for
class FullFakeAPI(BaseFakeAPI):
 def plan_execution(self,op,*,profile):
  return {'transport':'synthetic-file-api','officialVersion':'synthetic-only','selectedOfficialTransport':transport_for('synthetic-cli.exe',profile,op)}
 def invoke(self,p,url,**kw):
  s=read_json(self.path);params=kw.get('params',{});method=kw.get('method','GET')
  if url=='/rest/sp-product/v0/product-schemas':
   assert method=='GET' and params=={'lastCategoryId':456,'scene':'pop','productId':100}
   return {'success':True,'data':[json.dumps(s['schema'],ensure_ascii=False)]}
  if url=='/rest/sp-product/v0/skus':
   assert method=='GET' and params['productIdList']=='100'
   rows=s['schemaRows'];page=params['page'];size=params['pageSize']
   return {'data':rows[(page-1)*size:page*size],'paginationData':{'totalItems':len(rows)}}
  if url=='/rest/sp-product/v0/product-applies/{applyId}':
   assert method=='PATCH' and kw['write_authorized'] and kw['expected_execution']['selectedOfficialTransport']=='official-source-stdin'
   body=kw['body'];assert body['applyId']=='200' and body['productInfo']=={'productId':200,'categoryDetail':{'lastCategoryId':456}}
   patches=body['patchOperationList'];assert len(patches)==1000
   prices={patch['path'].split('==')[1][:-1]:json.loads(patch['value'])['value'] for patch in patches}
   assert set(prices)=={r['skuId'] for r in s['priceRows']}
   s['pending']=copy.deepcopy(s['priceRows'])
   for r in s['pending']:r['priceInfo']['jdPrice']=prices[r['skuId']]
   s['patchCount']+=1;atomic_json(self.path,s)
   if s['priceUnknown']:raise TimeoutError('synthetic accepted price response lost')
   return {'success':True,'data':{'id':'200'}}
  if url=='/rest/sp-product/v0/products/{productId}':
   assert method=='GET' and params['scene']=='pop'
   pid=params['productId'];rows=s['schemaRows'] if pid==100 else s['priceRows']
   return {'success':True,'data':{'productId':pid,'categoryDTO':{'lastCategoryId':456},'skuList':rows}}
  if url=='/rest/sp-product/v0/product-apply/{applyId}':
   assert method=='GET' and params=={'applyId':200,'scene':'pop'}
   return {'data':{'productInfo':{'productId':200},'skuList':s['pending'],'applyInfo':{'bossAuditStatus':-1}}}
  # Native media writes remain file-fake; the inherited assertions bind every field.
  if method=='POST':
   expected=kw['expected_execution'];assert expected['transport']=='synthetic-file-api'
   kw={**kw,'expected_execution':{'transport':'synthetic-file-api','officialVersion':'synthetic-only'}}
  return super().invoke(p,url,**kw)
cli.OfficialClient=FullFakeAPI
raise SystemExit(cli.main())
"""
SHIM=MATERIAL_SHIM.replace('raise SystemExit(cli.main())','')+EXTRA

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip'
 with tempfile.TemporaryDirectory(prefix='merchant-schema-smoke-') as temp:
  home=Path(temp);env=clean_environment(home);state=home/'.heideng-merchant';state.mkdir()
  schema=[img_component('WareSkuImg','0000000000'),{'componentCode':'SKUS','value':[{'componentCode':'SKU','value':[{'componentCode':'SkuUUid','value':'retained-uuid-'+str(i)},img_component('SkuMainImage'),{'componentCode':'FutureSkuField','value':{'retained':i}}]} for i in range(64)]},{'componentCode':'WareEditor','value':'<div>KEEP ALL DETAILS</div>'},{'componentCode':'FutureControl','value':{'retained':[1,2,3]}}]
  schema_rows=[{'skuId':2001+i,'productId':100,'priceInfo':{'jdPrice':'30.00'}} for i in range(64)]
  prices=[{'skuId':str(1000000000000000000+i),'productId':200,'priceInfo':{'jdPrice':'30.00'}} for i in range(1000)]
  fixture=state/'synthetic-api.json';atomic_json(fixture,{'foreign':False,'categoryStatus':1,'unknown':False,'postCount':0,'images':[], 'schema':schema,'schemaRows':schema_rows,'priceRows':prices,'pending':prices,'patchCount':0,'priceUnknown':False})
  install=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',file_sha(archive)],env=env,capture_output=True,timeout=60)
  assert install.returncode==0,'verified ZIP install failed'
  installed=home/'.codex/skills/heideng-ops-agent-merchant'
  sys.path.insert(0,str(installed));runtime=ImageRuntime(state);runtime.ensure()
  shim=home/'schema-shim.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):
   p=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=120)
   assert p.returncode==code,'installed command unexpected exit; output intentionally not logged'
   return json.loads(p.stdout)
  command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1')
  image=home/'source.png';image.write_bytes(noise_png(3));task=command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_synthetic','--category-id','7')['task']
  command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');command('task-execute','--task-id',task['taskId'])
  cap=command('product-schema','--profile','merchant-smoke','--product-id','100');assert len(cap['scope']['skuIds'])==64 and cap['schemaSkuRowCount']==64 and cap['scope']['schema']==schema
  assert not cap['submissionReady'] and not cap['skuIdentityMappingVerified']
  changes=home/'image-changes.json';atomic_json(changes,[{'pointer':t['pointer'],'assetTaskId':task['taskId']} for t in cap['imageTargets']])
  draft=command('schema-image-draft','--capture-id',cap['captureId'],'--changes',str(changes));expected=copy.deepcopy(schema)
  expected[0]['value'][0]['properties'][2]['value']='jfs/t1/1/asset-1.png'
  for r in expected[1]['value']:r['value'][1]['value'][0]['properties'][2]['value']='jfs/t1/1/asset-1.png'
  assert draft['schema']==expected and len(draft['changes'])==65 and not draft['submissionReady'] and not draft['productBound']
  assert command('schema-draft-status','--draft-id',draft['draftId'])['fingerprint']==draft['fingerprint']
  assert read_json(fixture)['postCount']==1 and read_json(fixture)['patchCount']==0
  price_changes=home/'prices.json';atomic_json(price_changes,[{'skuId':r['skuId'],'jdPrice':'20.00'} for r in prices])
  plan=command('price-plan','--profile','merchant-smoke','--product-id','200','--changes',str(price_changes));price=plan['task']
  assert len(plan['preview'])==1000 and price['scope']['officialExecution']['selectedOfficialTransport']=='official-source-stdin'
  command('task-execute','--task-id',price['taskId'],code=2);assert read_json(fixture)['patchCount']==0
  command('task-approve','--task-id',price['taskId'],'--fingerprint',price['fingerprint'],'--confirm');command('task-execute','--task-id',price['taskId'])
  assert command('price-status','--task-id',price['taskId'],'--refresh','pending')['phase']=='application-values-confirmed'
  assert not command('price-status','--task-id',price['taskId'],'--refresh','online')['onlineEffective']
  s=read_json(fixture);s['priceRows']=s['pending'];atomic_json(fixture,s)
  assert command('price-status','--task-id',price['taskId'],'--refresh','online')['onlineEffective']
  command('task-execute','--task-id',price['taskId'],code=2)
  atomic_json(price_changes,[{'skuId':r['skuId'],'jdPrice':'19.00'} for r in prices]);unknown=command('price-plan','--profile','merchant-smoke','--product-id','200','--changes',str(price_changes))['task']
  command('task-approve','--task-id',unknown['taskId'],'--fingerprint',unknown['fingerprint'],'--confirm');s=read_json(fixture);s['priceUnknown']=True;atomic_json(fixture,s)
  assert command('task-execute','--task-id',unknown['taskId'])['status']=='unknown'
  assert command('price-status','--task-id',unknown['taskId'],'--refresh','pending')['phase']=='unknown'
  command('task-execute','--task-id',unknown['taskId'],code=2)
  assert read_json(fixture)['patchCount']==2 and read_json(fixture)['postCount']==1
  evidence={'status':'passed','archiveSha256':file_sha(archive),'install':'fresh verified ZIP/fresh HOME/installed CLI -I -B', 'decoder':'real isolated Pillow','schemaSkuCount':64,'imageSlotCount':65,'entireSchemaAndUnknownComponentsPreserved':True,'skuMappingVerified':False,'productSchemaSubmissionCount':0,'productBound':False,'remotePixelsVerified':False,'priceSkuCount':1000,'knownPricePatchCount':1,'unknownPricePatchCount':1,'unknownDoesNotReplay':True,'officialStdinSelection':'real transport_for helper; dispatch is file-fake, not real official stdin request','realMerchantAPI':'not-run','realOAuth':'not-run','paidModelCalls':0,'networkBoundary':'merchant command socket connects disabled; public Pillow setup only before commands'}
  atomic_json(ROOT/'.agent-work/schema-smoke/evidence.json',evidence);print(json.dumps(evidence))

if __name__=='__main__':main()
