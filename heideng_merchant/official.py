"""Official Jingmai protocol; no company installer or credential exporting."""
from __future__ import annotations
import hashlib,io,json,os,platform,re,stat,subprocess,tarfile,urllib.request,uuid,zipfile,sys,time,math
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
 def document(self,skill_id,relative='SKILL.md',*,refresh=False):
  if not isinstance(skill_id,str) or not re.fullmatch(r'jdo-[a-z0-9-]{1,100}',skill_id):raise SafetyError('official-document-name-required')
  if relative!='SKILL.md' and not re.fullmatch(r'references/[A-Za-z0-9_-]+\.md',relative):raise SafetyError('official-markdown-reference-required')
  p=self.policy() if refresh else read_json(self.state/'tools'/'version-policy.json') or self.policy();wanted='cli/skills/'+skill_id+'/'+relative
  entry=next((e for e in p['artifacts']['skills']['files'] if e['path']==wanted),None)
  if not entry:raise SafetyError('official-document-unavailable')
  sha=entry['sha256'];safe_join(self.state,wanted)
  dest=safe_join(self.state,'official-docs/'+skill_id+'/'+relative)
  if dest.is_file() and file_sha(dest)==sha:return dest
  raw=self.download(BASE+wanted)
  if len(raw)>2*1024*1024 or hashlib.sha256(raw).hexdigest()!=sha:raise SafetyError('official-document-sha256-mismatch')
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);return dest
 def executable(self):
  if not self.ready():raise SafetyError('official-cli-not-installed-or-modified')
  receipt=read_json(self.receipt_path);return safe_join(safe_join(self.state,receipt['root']),receipt['executable'])
 def _environment(self):
  # Even GET/status can refresh a token and invoke upstream security -w secret.
  # Installation/document inspection stay available; credential-bearing CLI does not.
  if self.platform_name=='macos-arm64':raise SafetyError('official-credential-refresh-secret-argv-backend-not-admitted')
  home=self.state/'cli-home';home.mkdir(parents=True,exist_ok=True);env=clean_environment(home);env['JDO_ENV']='prod';env['JDO_CLI_HOME']=str(home/'.jdo-cli')
  backend={'windows-x64':'windows-credential-manager','macos-arm64':'macos-keychain'}.get(self.platform_name)
  if not backend:raise SafetyError('supported-native-credential-backend-required-no-plaintext-fallback')
  env['JDO_CREDENTIAL_BACKEND']=backend
  if os.name=='nt':env['PATH']=str(Path(env.get('SystemRoot','C:/Windows'))/'System32')
  return env
 def _run(self,args,timeout=45):
  env=self._environment();home=Path(env['HOME'])
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
 def plan_execution(self,operation,*,profile='merchant-contract'):
  from .official_transport import normalize_operation,transport_for,binary_execution,source_manifest,validate_source
  if self.platform_name=='macos-arm64':raise SafetyError('official-credential-refresh-secret-argv-backend-not-admitted')
  op=normalize_operation(profile,operation,write_authorized=True);transport=transport_for(self.executable(),profile,op);execution=binary_execution(self.state,self.platform_name,transport)
  if transport=='official-source-stdin':
   if self.platform_name!='windows-x64':raise SafetyError('official-stdin-native-credential-platform-not-admitted')
   from .official_transport import MAX_SOURCE_BYTES
   execution=source_manifest(self.policy(),execution)
   cached=getattr(self,'_verified_source',None)
   if not cached or cached[0]!=execution['sourceSha256']:
    raw=self.download(BASE+execution['sourcePath']);validate_source(raw,execution);self._verified_source=(execution['sourceSha256'],raw)
  return execution
 def _run_stdin(self,profile,operation,execution,authorization_expires_at=None,expected_shop=None,response_mode=None):
  from .official_transport import MAX_ENVELOPE_BYTES,publish_response
  env=self._environment();envelope={'schemaVersion':1,'profile':profile,'operation':operation,'execution':execution,'source':self._verified_source[1].decode('utf-8-sig'),'writeAuthorized':operation['method']!='GET','approvalExpiresAt':authorization_expires_at,'expectedShop':expected_shop}
  if response_mode is not None:
   envelope['responseMode']=response_mode;envelope['writeAuthorized']=True
  raw=json.dumps(envelope,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
  if len(raw)>MAX_ENVELOPE_BYTES:raise SafetyError('official-stdin-envelope-too-large')
  options={'env':env,'input':raw,'capture_output':True,'timeout':90,'cwd':env['HOME']}
  if os.name=='nt':options['creationflags']=0x08000000
  try:process=self.runner([sys.executable,'-I','-B',str(Path(__file__).with_name('official_stdin.py'))],**options)
  except (subprocess.TimeoutExpired,ConnectionError,OSError):raise SafetyError('official-stdin-outcome-unknown') from None
  try:result=json.loads(process.stdout or b'{}')
  except (ValueError,TypeError,UnicodeError):raise SafetyError('official-stdin-response-invalid-or-unknown') from None
  if process.returncode!=0 or not isinstance(result,dict) or result.get('ok') is not True or result.get('execution')!=execution:raise SafetyError('official-stdin-outcome-unknown-check-original-task')
  if response_mode=='video-upload-grant':
   from .video_transfer import UploadGrant
   grant=result.get('grant')
   if not isinstance(grant,dict) or set(grant)!={'jdVideoId','uploadUrl'}:raise SafetyError('official-confidential-grant-outcome-unknown')
   return UploadGrant(grant['jdVideoId'],grant['uploadUrl'])
  response=publish_response(result.get('response'),operation)
  return {**response,'_merchantExecution':execution} if isinstance(response,dict) else {'data':response,'_merchantExecution':execution}
 def invoke(self,profile,url,*,method='GET',params=None,body=None,skill_id='jdo-seller-info',write_authorized=False,expected_execution=None,authorization_expires_at=None,expected_shop=None):
  from .official_transport import normalize_operation,invoke_args,validate_expected_shop,matches_shop,publish_response
  op=normalize_operation(profile,{'url':url,'method':method,'params':{} if params is None else params,'body':body,'skillId':skill_id},write_authorized=write_authorized)
  from .video_contract import guarded_video_route
  if op['method']=='GET' and guarded_video_route(op['url'],'GET'):raise SafetyError('native-video-allocation-requires-confidential-session')
  execution=self.plan_execution(op,profile=profile)
  if expected_execution is not None and execution!=expected_execution:raise SafetyError('official-execution-contract-changed-prepare-new-approval')
  if op['method']!='GET':
   expected_shop=validate_expected_shop(expected_shop,profile)
   if not matches_shop(self.identity(profile),expected_shop):raise SafetyError('shop-changed-before-official-dispatch')
  if authorization_expires_at is not None and (isinstance(authorization_expires_at,bool) or not isinstance(authorization_expires_at,(int,float)) or not math.isfinite(authorization_expires_at) or authorization_expires_at<=time.time()):raise SafetyError('approval-expired-before-official-transport')
  if execution['transport']=='official-source-stdin':return self._run_stdin(profile,op,execution,authorization_expires_at,expected_shop)
  result=publish_response(self._run(invoke_args(profile,op)),op)
  return {**result,'_merchantExecution':execution} if isinstance(result,dict) else result
 def allocate_video_upload(self,profile,params,*,write_authorized=False,expected_execution=None,authorization_expires_at=None,expected_shop=None):
  from .video_contract import ALLOC,SKILL,native_id
  from .result_verification import resource_id
  from .official_transport import normalize_operation,validate_expected_shop
  if write_authorized is not True or authorization_expires_at is None or expected_execution is None:raise SafetyError('approved-confidential-video-allocation-required')
  if not isinstance(params,dict) or set(params) not in ({'zoneId','fileName','fileSize','videoType'},{'zoneId','fileName','fileSize','videoType','jdVideoId','breakPointFlag'}):raise SafetyError('exact-native-video-allocation-fields-required')
  resource_id(params['zoneId'])
  if type(params['videoType']) is not int or params['videoType']!=1 or type(params['fileSize']) is not int or not 0<params['fileSize']<=500*1024*1024 or not isinstance(params['fileName'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}\.mp4',params['fileName']):raise SafetyError('native-merchant-video-allocation-input-invalid')
  if 'jdVideoId' in params:
   native_id(params['jdVideoId'])
   if params['breakPointFlag'] is not True:raise SafetyError('known-original-video-id-renewal-required')
  shop=validate_expected_shop(expected_shop,profile)
  if isinstance(authorization_expires_at,bool) or not isinstance(authorization_expires_at,(int,float)) or not math.isfinite(authorization_expires_at) or authorization_expires_at<=time.time():raise SafetyError('native-video-approval-expired-before-allocation')
  operation=normalize_operation(profile,{'url':ALLOC,'method':'GET','params':params,'skillId':SKILL},write_authorized=True)
  execution=self.plan_execution(operation,profile=profile)
  if execution!=expected_execution or execution['transport']!='official-source-stdin':raise SafetyError('native-video-allocation-execution-contract-changed')
  return self._run_stdin(profile,operation,execution,authorization_expires_at,shop,'video-upload-grant')
 def identity(self,profile):
  return identity_from_response(self.invoke(profile,'/rest/sp-seller/v0/venderinfo',params={'scopeSet':'baseInfo'},skill_id='jdo-seller-info'))
 def initialize(self,profile,*,vender_id=None,shop_name=None):
  validate_profile(profile)
  if not profile.startswith('merchant-'):raise SafetyError('merchant-owned-profile-namespace-required')
  args=['init','--profile',profile,'--skip-network']
  if vender_id is not None:
   if not str(vender_id).isdigit():raise SafetyError('actual-vender-id-required')
   args+=['--vender-id',str(vender_id)]
  if shop_name:args+=['--shop-name',shop_name]
  return self._run(args)
 def login_process(self,profile,shop_name,vender_id):
  if self.platform_name!='windows-x64':raise SafetyError('official-auth-secret-argv-backend-not-admitted')
  validate_profile(profile)
  if not profile.startswith('merchant-') or not shop_name or not str(vender_id).isdigit():raise SafetyError('merchant-owned-auth-target-required')
  env=self._environment();args=[str(self.executable()),'--endpoint',BASE.rstrip('/'),'login','--profile',profile,'--no-browser','--vender-id',str(vender_id),'--shop-name',shop_name,'--timeout','900']
  options={'env':env,'cwd':env['HOME'],'stdin':subprocess.DEVNULL,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE}
  if os.name=='nt':options['creationflags']=0x08000000
  return subprocess.Popen(args,**options)
 def _login_owners(self,process):
  # Retain proven psutil handles before a wrapper parent exits. Never rediscover
  # children by a reused PID or walk unrelated processes after losing ownership.
  import psutil
  parent=getattr(process,'_merchant_owner',None)
  cache=getattr(process,'_merchant_descendants',{})
  if process.poll() is None:
   if parent is None:parent=psutil.Process(process.pid);process._merchant_owner=parent
   if parent.is_running():
    for child in parent.children(recursive=True):cache[child.pid]=child
    process._merchant_descendants=cache
  return ([parent] if parent is not None else [])+list(cache.values())
 def callback_owned(self,process):
  try:
   for owner in self._login_owners(process):
    for connection in owner.net_connections(kind='tcp'):
     if connection.status=='LISTEN' and connection.laddr.ip in ('127.0.0.1','::1') and connection.laddr.port==9001:return True
  except Exception:return False
  return False
 def stop_login(self,process):
  import psutil
  try:owners=self._login_owners(process)
  except (psutil.NoSuchProcess,psutil.AccessDenied):owners=[]
  descendants=owners[1:]
  for owner in reversed(descendants):
   try:owner.terminate()
   except psutil.NoSuchProcess:pass
  if process.poll() is None:process.terminate()
  _,alive=psutil.wait_procs(descendants,timeout=3)
  for owner in alive:
   try:owner.kill()
   except psutil.NoSuchProcess:pass
  if process.poll() is None:
   try:process.wait(timeout=3)
   except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
  if psutil.wait_procs(alive,timeout=3)[1]:raise SafetyError('owned-auth-process-cleanup-incomplete')
 def login_plan(self,profile,shop_name,vender_id=None):
  validate_profile(profile)
  return {'status':'awaiting_auth','profile':profile,'shopName':shop_name,'venderId':str(vender_id or ''),'browser':'task-owned-jingmai-session','steps':['先让商家用京麦App扫码任务专属京麦网页','在同一浏览器上下文衔接官方OAuth；授权URL只通过受控工具内存传递','成功后执行实时venderinfo核验店名/venderId/Profile，不以本地状态或扫码成功当作授权签发成功'],'officialCommand':['login','--profile',profile,'--no-browser'],'unsafeFlagsForbidden':['--mock-token-on-service-market-block','--print-code','--code','--force']}
