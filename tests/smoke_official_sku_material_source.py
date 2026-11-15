"""Actual audited official source at native SKU material endpoint, synthetic HTTP."""
import hashlib,json,os,socket,sys,tempfile,urllib.request
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.official_stdin import execute_envelope
from heideng_merchant.official_transport import AUDITED_SOURCES
from heideng_merchant.safety import atomic_json,file_sha
raw=urllib.request.urlopen('https://mcp-open.jd.com/cli/jdo-cli',timeout=30).read(2*1024*1024+1);sha=hashlib.sha256(raw).hexdigest();assert sha==AUDITED_SOURCES['0.3.7']
body={'skuMaterials':[{'productId':9,'skuId':sku,'materials':[{'skuId':sku,'materialType':31,'order':1,'imageMaterial':{'imgType':1,'replaceType':1,'skuImages':[{'index':1,'imgUrl':'jfs/t1/synthetic.png'}]}},{'skuId':sku,'materialType':1002,'order':1,'textMaterial':{'contents':['轻巧便携']}}]} for sku in range(101,151)]}
records=[]
for expired in (False,True):
 with tempfile.TemporaryDirectory(prefix='native-material-sdk-') as d:
  state=Path(d);exe=state/'tools/stub/bin/jdo-cli.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'SYNTHETIC_NOT_EXECUTED_BINARY');atomic_json(state/'tools/official.json',{'version':'0.3.7','root':'tools/stub','executable':'bin/jdo-cli.exe','executableSha256':file_sha(exe),'archiveSha256':'a'*64})
  execution={'transport':'official-source-stdin','officialVersion':'0.3.7','platform':'windows-x64','binarySha256':file_sha(exe),'binaryArchiveSha256':'a'*64,'sourceSha256':sha,'sourcePath':'cli/jdo-cli','sourceStatus':'deprecated'}
  envelope={'schemaVersion':1,'profile':'merchant-demo','operation':{'url':'/rest/sp-product/v0/sku-materials/batch','method':'POST','params':{},'body':body,'skillId':'jdo-api-830'},'execution':execution,'source':raw.decode('utf-8'),'writeAuthorized':True,'approvalExpiresAt':100,'expectedShop':{'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}}
  calls=[];signs=[];clock=[99]
  def hook(ns):
   ns['get_auth_context']=lambda *a,**kw:{'profile_name':'merchant-demo','vender_id':'1','app_key':'SYNTHETIC_APP','app_secret':'SYNTHETIC_SECRET','access_token':'SYNTHETIC_TOKEN'};ns['touch_auth_usage']=lambda *a,**kw:None;original_sign=ns['calc_sign']
   def signing(*a,**kw):
    result=original_sign(*a,**kw);signs.append(1)
    if expired and len(signs)==2:clock[0]=101
    return result
   ns['calc_sign']=signing
   class Response:
    status=200
    def __init__(self,obj):self.obj=obj
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):return json.dumps(self.obj).encode()
   def fake_open(request,timeout=30):
    method=request.get_method();calls.append(method)
    if method=='GET':return Response({'success':True,'data':{'venderId':'1','shopBaseInfo':{'type':0,'shopId':'3','shopName':'synthetic-store'}}})
    assert request.full_url.endswith('/rest/sp-product/v0/sku-materials/batch') and json.loads(request.data)==body
    assert len(json.loads(request.data)['skuMaterials'])==50
    return Response({'success':True,'data':{'receipt':'synthetic-only'}})
   ns['urlopen_with_ssl']=fake_open
  def blocked(*a,**kw):raise RuntimeError('network forbidden at synthetic native SDK boundary')
  env={'HOME':str(state/'cli-home'),'JDO_CLI_HOME':str(state/'cli-home/.jdo-cli'),'JDO_CREDENTIAL_BACKEND':'windows-credential-manager'}
  with patch.dict(os.environ,env,clear=True),patch('time.time',side_effect=lambda:clock[0]),patch.object(socket.socket,'connect',blocked),patch('socket.create_connection',blocked):result=execute_envelope(envelope,state,namespace_hook=hook)
  assert result['ok'] is (not expired) and calls==(['GET'] if expired else ['GET','POST']) and len(signs)==2
  assert all(secret not in json.dumps(result) for secret in ('SYNTHETIC_APP','SYNTHETIC_SECRET','SYNTHETIC_TOKEN'))
  records.append({'expiredAfterSigning':expired,'success':result['ok'],'syntheticHttpMethods':calls,'signaturesComputed':len(signs),'nativeSkuCount':50})
record={'status':'passed','officialSourceSha256':sha,'officialVersion':'0.3.7','binary':'synthetic receipt stub; not executed','auth':'synthetic in-memory only','http':'synthetic final boundary with socket blocked','endpoint':'native SKU materials batch','originalSourceSigningExecuted':True,'finalDeadlineAfterSigningEnforced':True,'cases':records,'realMerchantAuthorization':'not-run','realMerchantWrites':'not-run','paidModelCalls':0}
atomic_json(ROOT/'.agent-work/information-score-audit/official-native-material-smoke.json',record);print(json.dumps(record))
