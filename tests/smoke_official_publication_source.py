"""Audited real official source, synthetic auth and HTTP; no business networking."""
import hashlib,json,os,socket,sys,tempfile,time,urllib.request
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.official_stdin import execute_envelope
from heideng_merchant.official_transport import AUDITED_SOURCES
from heideng_merchant.safety import atomic_json,file_sha
from tests.publish_fixtures import payload,source_product
raw=urllib.request.urlopen('https://mcp-open.jd.com/cli/jdo-cli',timeout=30).read(2*1024*1024+1)
sha=hashlib.sha256(raw).hexdigest();assert sha==AUDITED_SOURCES['0.3.7']
records=[]
for expired in (False,True):
 with tempfile.TemporaryDirectory() as d:
  state=Path(d);exe=state/'tools/stub/bin/jdo-cli.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'SYNTHETIC_NOT_EXECUTED_BINARY')
  atomic_json(state/'tools/official.json',{'version':'0.3.7','root':'tools/stub','executable':'bin/jdo-cli.exe','executableSha256':file_sha(exe),'archiveSha256':'a'*64})
  execution={'transport':'official-source-stdin','officialVersion':'0.3.7','platform':'windows-x64','binarySha256':file_sha(exe),'binaryArchiveSha256':'a'*64,'sourceSha256':sha,'sourcePath':'cli/jdo-cli','sourceStatus':'deprecated'}
  body={'scene':'pop','schema':json.dumps(payload(source_product(1000))),'productApplyDTO':{'categoryDTO':{'lastCategoryId':44207}}}
  envelope={'schemaVersion':1,'profile':'merchant-demo','operation':{'url':'/rest/sp-product/v0/product-applies','method':'POST','params':{},'body':body,'skillId':'jdo-product-publish'},'execution':execution,'source':raw.decode('utf-8'),'writeAuthorized':True,'approvalExpiresAt':100,'expectedShop':{'profile':'merchant-demo','venderId':'1','shopId':'3','shopName':'synthetic-store'}}
  calls=[];signs=[];clock=[99]
  def hook(ns):
   ns['get_auth_context']=lambda *a,**kw:{'profile_name':'merchant-demo','vender_id':'1','app_key':'SYNTHETIC_APP','app_secret':'SYNTHETIC_SECRET','access_token':'SYNTHETIC_TOKEN'}
   ns['touch_auth_usage']=lambda *a,**kw:None
   original_sign=ns['calc_sign']
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
    assert json.loads(request.data)==body
    assert len(next(r for r in json.loads(body['schema']) if r['componentCode']=='SKUS')['value'])==1000
    return Response({'success':True,'data':{'applyId':300,'productId':400}})
   ns['urlopen_with_ssl']=fake_open
  env={'HOME':str(state/'cli-home'),'JDO_CLI_HOME':str(state/'cli-home/.jdo-cli'),'JDO_CREDENTIAL_BACKEND':'windows-credential-manager'}
  def blocked(*a,**kw):raise RuntimeError('synthetic boundary forbids networking')
  with patch.dict(os.environ,env,clear=True),patch('time.time',side_effect=lambda:clock[0]),patch.object(socket.socket,'connect',blocked),patch('socket.create_connection',blocked):result=execute_envelope(envelope,state,namespace_hook=hook)
  assert result['ok'] is (not expired)
  assert calls==(['GET'] if expired else ['GET','POST'])
  assert 'SYNTHETIC_SECRET' not in json.dumps(result) and 'SYNTHETIC_TOKEN' not in json.dumps(result)
  records.append({'expiredAfterSigning':expired,'success':result['ok'],'syntheticHttpMethods':calls,'signaturesComputed':len(signs)})
evidence={'status':'passed','officialSourceSha256':sha,'officialVersion':'0.3.7','sourcePersisted':False,'binary':'synthetic receipt stub; not executed','auth':'synthetic in-memory only','http':'synthetic final boundary, socket blocked','sourceSkuCount':1000,'realOAuth':'not-run','realMerchantWrites':'not-run','cases':records}
atomic_json(ROOT/'.agent-work/publish-audit/official-source-smoke-evidence.json',evidence);print(json.dumps(evidence))
