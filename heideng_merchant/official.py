"""Official Jingmai protocol; no company installer or credential exporting."""
from __future__ import annotations
import hashlib,io,json,os,platform,re,stat,subprocess,tarfile,urllib.request,uuid,zipfile
from pathlib import Path
from .safety import SafetyError,safe_join,file_sha,atomic_json,read_json,clean_environment,redact
from .state import FileLock
from .distribution import version_key

BASE='https://mcp-open.jd.com/'
POLICY=BASE+'cli/version-policy.json'
MAX_BYTES=64*1024*1024
SKILLS=('jdo-seller-info','jdo-product-price','jdo-product-material','jdo-product-publish','jdo-product-update','jdo-product-status','jdo-support-data')

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise SafetyError('official-download-redirect-refused')

def official_download(url):
 if not url.startswith(BASE) or not re.fullmatch(r'https://mcp-open\.jd\.com/[A-Za-z0-9_./-]+',url):raise SafetyError('untrusted-official-url')
 if '..' in url:raise SafetyError('unsafe-official-url')
 try:
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=90) as response:raw=response.read(MAX_BYTES+1)
 except SafetyError:raise
 except Exception:raise SafetyError('official-network-unavailable') from None
 if len(raw)>MAX_BYTES:raise SafetyError('official-download-too-large')
 return raw

def validate_profile(profile):
 if not isinstance(profile,str) or profile=='default' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,40}',profile):raise SafetyError('explicit-non-default-profile-required')
 return profile

def validate_route(url):
 if not isinstance(url,str) or not re.fullmatch(r'/rest/sp-[a-z0-9-]+/v[0-9]+/[A-Za-z0-9_/{},.-]+',url) or '..' in url:raise SafetyError('official-rest-route-required')
 return url

def identity_from_response(response):
 data=response.get('data',{})
 if isinstance(data,dict) and 'data' in data and 'shopBaseInfo' not in data:data=data['data']
 shop=data.get('shopBaseInfo',{}) if isinstance(data,dict) else {}
 if str(shop.get('type'))!='0':raise SafetyError('pop-shop-required')
 result={'venderId':str(data.get('venderId','')),'shopId':str(shop.get('shopId','')),'shopName':shop.get('shopName',''),'shopType':'POP'}
 if not result['venderId'].isdigit() or not result['shopId'].isdigit() or not result['shopName']:raise SafetyError('incomplete-shop-identity')
 return result

class OfficialClient:
 def __init__(self,state,*,download=None,runner=None,platform_name=None):
  self.state=Path(state).resolve();self.download=download or official_download;self.runner=runner or subprocess.run
  self.platform_name=platform_name or ('windows-x64' if os.name=='nt' and platform.machine().lower() in ('amd64','x86_64') else 'macos-arm64' if platform.system()=='Darwin' and platform.machine()=='arm64' else 'unsupported')
  self.receipt_path=self.state/'tools'/'official.json'
 def policy(self):
  try:p=json.loads(self.download(POLICY))
  except ValueError:raise SafetyError('invalid-official-policy') from None
  if p.get('product')!='jdo-cli':raise SafetyError('wrong-official-product')
  version_key(p.get('stableVersion'))
  return p
 def ready(self):
  receipt=read_json(self.receipt_path,{})
  if not receipt:return False
  try:
   root=safe_join(self.state,receipt['root']);p=safe_join(root,receipt['executable'])
   return p.is_file() and file_sha(p)==receipt['executableSha256']
  except (KeyError,OSError,SafetyError):return False
 def install(self):
  p=self.policy();artifact=p.get('artifacts',{}).get('binaries',{}).get(self.platform_name)
  if not artifact:raise SafetyError('official-platform-not-supported')
  version=artifact.get('version');version_key(version)
  if version!=p['stableVersion']:raise SafetyError('official-version-mismatch')
  name=artifact.get('path','');safe_join(self.state,name)
  if not name.startswith('cli/releases/') or not re.fullmatch('[0-9a-f]{64}',artifact.get('sha256','')):raise SafetyError('invalid-official-artifact')
  safe_join(self.state,artifact['executable'])
  with FileLock(self.state/'tools'/'install.lock'):
   current=read_json(self.receipt_path,{})
   if current and self.ready():
    if version_key(version)<version_key(current['version']):raise SafetyError('official-downgrade-refused')
    if version==current['version'] and current.get('archiveSha256')==artifact['sha256']:return {'status':'unchanged','version':version}
   raw=self.download(BASE+name)
   if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise SafetyError('official-sha256-mismatch')
   files={};seen=set();total=0
   def accept(name,data,mode):
    nonlocal total
    name=name.rstrip('/');safe_join(self.state,name)
    if name.casefold() in seen or stat.S_ISLNK(mode):raise SafetyError('unsafe-official-member')
    seen.add(name.casefold());total+=len(data)
    if total>128*1024*1024:raise SafetyError('official-expanded-size-limit')
    files[name]=data
   try:
    if artifact['format']=='zip':
     with zipfile.ZipFile(io.BytesIO(raw)) as z:
      for item in z.infolist():
       if item.is_dir():safe_join(self.state,item.filename.rstrip('/'));continue
       if item.file_size>MAX_BYTES:raise SafetyError('official-member-too-large')
       accept(item.filename,z.read(item),item.external_attr>>16)
    elif artifact['format']=='tar.gz':
     with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:
      for item in t.getmembers():
       safe_join(self.state,item.name.rstrip('/'))
       if item.isdir():continue
       if not item.isfile() or item.size>MAX_BYTES:raise SafetyError('unsafe-official-member')
       accept(item.name,t.extractfile(item).read(MAX_BYTES+1),item.mode)
    else:raise SafetyError('unsupported-official-format')
   except (zipfile.BadZipFile,tarfile.TarError):raise SafetyError('invalid-official-archive') from None
   if artifact['executable'] not in files:raise SafetyError('official-executable-missing')
   rel='tools/official-'+version+'-'+uuid.uuid4().hex[:12];root=safe_join(self.state,rel);root.mkdir(parents=True)
   for name,data in files.items():dest=safe_join(root,name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
   exe=safe_join(root,artifact['executable']);exe.chmod(exe.stat().st_mode|stat.S_IXUSR)
   atomic_json(self.receipt_path,{'version':version,'root':rel,'executable':artifact['executable'],'executableSha256':file_sha(exe),'archiveSha256':artifact['sha256'],'source':BASE})
   atomic_json(self.state/'tools'/'version-policy.json',p)
   return {'status':'installed','version':version,'binaryVerified':True}
 def document(self,skill_id):
  if skill_id not in SKILLS:raise SafetyError('official-document-not-in-merchant-bootstrap')
  p=read_json(self.state/'tools'/'version-policy.json') or self.policy();wanted='cli/skills/'+skill_id+'/SKILL.md'
  entry=next((e for e in p['artifacts']['skills']['files'] if e['path']==wanted),None)
  if not entry:raise SafetyError('official-document-unavailable')
  sha=entry['sha256'];safe_join(self.state,wanted)
  dest=safe_join(self.state,'official-docs/'+skill_id+'/SKILL.md')
  if dest.is_file() and file_sha(dest)==sha:return dest
  raw=self.download(BASE+wanted)
  if len(raw)>2*1024*1024 or hashlib.sha256(raw).hexdigest()!=sha:raise SafetyError('official-document-sha256-mismatch')
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);return dest
 def executable(self):
  if not self.ready():raise SafetyError('official-cli-not-installed-or-modified')
  receipt=read_json(self.receipt_path);return safe_join(safe_join(self.state,receipt['root']),receipt['executable'])
 def _run(self,args,timeout=45):
  home=self.state/'cli-home';home.mkdir(parents=True,exist_ok=True);env=clean_environment(home);env['JDO_ENV']='prod'
  if os.name=='nt':env['PATH']=str(Path(env.get('SystemRoot','C:/Windows'))/'System32')
  options={'env':env,'capture_output':True,'timeout':timeout,'cwd':str(home)}
  if os.name=='nt':options['creationflags']=0x08000000
  try:p=self.runner([str(self.executable()),'--endpoint',BASE.rstrip('/'),*args],**options)
  except (subprocess.TimeoutExpired,ConnectionError,OSError):raise SafetyError('official-outcome-unknown') from None
  output=p.stdout or b'{}'
  if isinstance(output,bytes):
   try:output=output.decode('utf-8-sig')
   except UnicodeDecodeError:
    try:output=output.decode('gb18030')
    except UnicodeDecodeError:raise SafetyError('official-response-encoding-unknown') from None
  try:data=json.loads(output)
  except ValueError:raise SafetyError('official-response-invalid-or-unknown') from None
  if p.returncode!=0 or (isinstance(data,dict) and data.get('ok') is False):raise SafetyError('official-call-failed-check-permissions-or-outcome')
  return redact(data)
 def invoke(self,profile,url,*,method='GET',params=None,body=None,skill_id='jdo-seller-info',write_authorized=False):
  validate_profile(profile);validate_route(url);method=method.upper()
  if method not in ('GET','POST','PUT','PATCH','DELETE'):raise SafetyError('invalid-http-method')
  if method!='GET' and not write_authorized:raise SafetyError('explicit-shop-write-approval-required')
  params={} if params is None else params
  if not isinstance(params,dict) or (body is not None and not isinstance(body,(dict,list))):raise SafetyError('invalid-business-payload')
  payload=json.dumps(params,ensure_ascii=False,separators=(',',':'),allow_nan=False)
  body_json=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False) if body is not None else None
  if len(payload)+(len(body_json) if body_json else 0)>18000:raise SafetyError('large-payload-use-authorized-browser-upload')
  if not re.fullmatch('[a-z0-9-]+',skill_id):raise SafetyError('invalid-official-skill-id')
  args=['invoke','--profile',profile,'--skill-id',skill_id,'--url',url,'--method',method,'--params',payload,'--request-identity','vender','--timeout','30']
  if body_json is not None:args+=['--body',body_json]
  if method!='GET':args+=['--yes']
  return self._run(args)
 def identity(self,profile):
  return identity_from_response(self.invoke(profile,'/rest/sp-seller/v0/venderinfo',params={'scopeSet':'baseInfo'},skill_id='jdo-seller-info'))
 def initialize(self,profile):return self._run(['init','--profile',validate_profile(profile),'--skip-network'])
 def login_plan(self,profile,shop_name,vender_id=None):
  validate_profile(profile)
  return {'status':'awaiting_auth','profile':profile,'shopName':shop_name,'venderId':str(vender_id or ''),'browser':'task-owned-jingmai-session','steps':['先让商家用京麦App扫码任务专属京麦网页','在同一浏览器上下文衔接官方OAuth；授权URL只通过受控工具内存传递','成功后执行实时venderinfo核验店名/venderId/Profile，不以本地状态或扫码成功当作授权签发成功'],'officialCommand':['login','--profile',profile,'--no-browser'],'unsafeFlagsForbidden':['--mock-token-on-service-market-block','--print-code','--code','--force']}
