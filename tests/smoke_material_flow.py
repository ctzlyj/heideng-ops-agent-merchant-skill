"""Fresh ZIP + real Pillow + isolated command processes; file-fake merchant API only."""
import hashlib,json,random,struct,subprocess,sys,tempfile,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,read_json,file_sha
from heideng_merchant.image_runtime import ImageRuntime

SHIM=r'''import base64,copy,hashlib,json,struct,sys,socket
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1))
from heideng_merchant import cli
from heideng_merchant.safety import atomic_json,read_json
class FakeAPI:
 def __init__(self,state):self.path=Path(state)/'synthetic-api.json'
 def identity(self,p):
  s=read_json(self.path);return {'venderId':'2' if s['foreign'] else '1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
 def plan_execution(self,op,*,profile):return {'transport':'synthetic-file-api','officialVersion':'synthetic-only'}
 def invoke(self,p,url,**kw):
  assert p=='merchant-smoke';s=read_json(self.path);params=kw.get('params',{});method=kw.get('method','GET')
  if method=='POST':
   assert kw['write_authorized'] is True and kw['expected_execution']=={'transport':'synthetic-file-api','officialVersion':'synthetic-only'} and kw['expected_shop']['venderId']=='1'
   assert url=='/rest/sp-product/v0/media-zones/{zoneId}/images' and params=={'zoneId':'img_synthetic'}
   body=kw['body'];assert set(body)=={'imgBase64','zoneImageDTO'};assert set(body['zoneImageDTO'])=={'imgName','categoryId'} and body['zoneImageDTO']['categoryId']==7
   raw=base64.b64decode(body['imgBase64'],validate=True);width,height=struct.unpack('>II',raw[16:24]);s['postCount']+=1
   asset={'imgId':'asset-'+str(s['postCount']),'imgUrl':'jfs/t1/1/asset-'+str(s['postCount'])+'.png','imgName':body['zoneImageDTO']['imgName'],'categoryId':7,'imgWidth':width,'imgHeight':height,'imgType':'PNG','imgSize':len(raw),'syntheticSourceSha256':hashlib.sha256(raw).hexdigest()};s['images'].append(asset);atomic_json(self.path,s)
   if s['unknown']:raise TimeoutError('synthetic response lost after acceptance')
   return {'success':True,'data':asset}
  assert method=='GET'
  if url.endswith('/media-zones'):return {'data':[{'zoneId':'img_synthetic','zoneType':1}]}
  if url.endswith('/categories'):rows=[{'categoryId':7,'categoryName':'synthetic-category','status':s['categoryStatus']}]
  elif '{imageId}' in url:return {'data':next((r for r in s['images'] if r['imgId']==params['imageId']),{})}
  elif url.endswith('/images'):rows=s['images']
  else:raise AssertionError('unexpected synthetic route')
  page=params['page'];size=params['pageSize'];return {'data':rows[(page-1)*size:page*size],'paginationData':{'totalItems':len(rows)}}
cli.OfficialClient=FakeAPI
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('network disabled in merchant command'))
socket.create_connection=socket.socket.connect
raise SystemExit(cli.main())
'''

def noise_png(seed):
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
 randomizer=random.Random(seed);pixels=b''.join(b'\0'+randomizer.randbytes(256*3) for _ in range(256))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',256,256,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')

def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip'
 with tempfile.TemporaryDirectory(prefix='merchant-material-smoke-') as temporary:
  home=Path(temporary);env=clean_environment(home);state=home/'.heideng-merchant';state.mkdir();shim=home/'fake-api-shim.py';shim.write_text(SHIM,encoding='utf-8');fixture=state/'synthetic-api.json';atomic_json(fixture,{'foreign':False,'categoryStatus':1,'unknown':False,'postCount':0,'images':[]})
  install=subprocess.run([sys.executable,'-I','-B',str(ROOT/'install.py'),'--offline','--home',str(home),'--archive',str(archive),'--sha256',file_sha(archive)],env=env,capture_output=True,timeout=60);assert install.returncode==0
  installed=home/'.codex/skills/heideng-ops-agent-merchant'
  # Public dependencies are provisioned before network-disabled merchant commands.
  sys.path.insert(0,str(installed));runtime=ImageRuntime(state);runtime.ensure()
  def command(*args,code=0):
   result=subprocess.run([sys.executable,'-I','-B',str(shim),str(installed),'--home',str(home),*args],env=env,capture_output=True,timeout=90);assert result.returncode==code,'installed command unexpected outcome';return json.loads(result.stdout)
  command('shop-connect','--profile','merchant-smoke','--shop-name','synthetic-store','--vender-id','1');assert command('material-zones','--profile','merchant-smoke')['items'][0]['zoneId']=='img_synthetic';assert command('material-categories','--profile','merchant-smoke','--zone-id','img_synthetic')['complete']
  image=home/'known.png';raw=noise_png(1);image.write_bytes(raw);plan=command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_synthetic','--category-id','7');task=plan['task'];assert task['scope']['operation']['body']['imgBase64']['omitted'];assert plan['image']['sha256']==hashlib.sha256(raw).hexdigest()
  command('task-execute','--task-id',task['taskId'],code=2);assert read_json(fixture)['postCount']==0
  command('task-approve','--task-id',task['taskId'],'--fingerprint',task['fingerprint'],'--confirm');assert command('task-execute','--task-id',task['taskId'])['status']=='submitted';verified=command('material-upload-status','--task-id',task['taskId'],'--refresh');assert verified['storageVerified'] and not verified['productBound'] and not verified['remotePixelsVerified'];assert verified['asset']['syntheticSourceSha256']==hashlib.sha256(raw).hexdigest()
  command('task-execute','--task-id',task['taskId'],code=2);assert read_json(fixture)['postCount']==1
  image=home/'unknown.png';image.write_bytes(noise_png(2));unknown=command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_synthetic','--category-id','7')['task'];command('task-approve','--task-id',unknown['taskId'],'--fingerprint',unknown['fingerprint'],'--confirm');s=read_json(fixture);s['unknown']=True;atomic_json(fixture,s);assert command('task-execute','--task-id',unknown['taskId'])['status']=='unknown';assert command('material-upload-status','--task-id',unknown['taskId'],'--refresh')['phase']=='unknown';command('task-result-readback','--task-id',unknown['taskId'],code=2);command('task-execute','--task-id',unknown['taskId'],code=2);command('material-upload-plan','--profile','merchant-smoke','--image',str(image),'--zone-id','img_synthetic','--category-id','7','--name','new-name.png',code=2);assert read_json(fixture)['postCount']==2
  record={'status':'passed','install':'fresh verified ZIP / fresh HOME','python':'real -I/-B subprocesses','pillow':runtime.status()['packages'],'decoder':'real Pillow, original valid 256x256 PNG bytes','largestImageBytes':len(raw),'base64NotInCommandOutput':True,'approvalBeforeUpload':True,'nativeFlatBody':True,'knownPostCount':1,'unknownIntentPostCount':1,'unknownDoesNotUseFilenameMatchOrUnlock':True,'storageVsProductBinding':'separate, no product bind performed','remotePixelsVerified':False,'merchantAPI':'file-fake; command main socket connect blocked, image child local-only decoder not OS firewall','realMerchantAPI':'not-run','realMerchantWrites':'not-run','modelCalls':0,'archiveSha256':file_sha(archive)}
  atomic_json(ROOT/'.agent-work/material-smoke/evidence.json',record);print(json.dumps(record))
if __name__=='__main__':main()
