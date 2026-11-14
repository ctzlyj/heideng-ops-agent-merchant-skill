"""Authenticated GitHub is mediated by its official CLI; never export a token."""
import json,os,re,subprocess,uuid
from pathlib import Path
from .safety import SafetyError,safe_join,file_sha,read_json,atomic_json
from .distribution import version_key,install_archive,verify_install,busy

REPOSITORY='ctzlyj/heideng-ops-agent-merchant-skill'

def github_environment():
 return {k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH','PATHEXT','HOME','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP','GH_CONFIG_DIR','GH_TOKEN','GITHUB_TOKEN') if k in os.environ}

def github_json(route,runner=None):
 if not (route.startswith('repos/'+REPOSITORY+'/') or route.startswith('repos/ctzlyj/jd-pop-main-video-skill/')) or '..' in route:raise SafetyError('untrusted-update-repository')
 opts={'capture_output':True,'text':True,'encoding':'utf-8','errors':'strict','timeout':90,'env':github_environment()}
 if os.name=='nt':opts['creationflags']=0x08000000
 try:p=(runner or subprocess.run)(['gh','api',route],**opts)
 except (OSError,subprocess.TimeoutExpired):raise SafetyError('github-cli-or-network-unavailable-agent-repair') from None
 if p.returncode!=0:raise SafetyError('github-read-access-or-release-unavailable')
 try:return json.loads(p.stdout)
 except ValueError:raise SafetyError('invalid-github-response') from None

class ReleaseUpdates:
 def __init__(self,state,runner=None):self.state=Path(state).resolve();self.runner=runner or subprocess.run
 def check(self,current_version):
  version_key(current_version);release=github_json('repos/'+REPOSITORY+'/releases/latest',self.runner);tag=release.get('tag_name','')
  if not re.fullmatch(r'v\d+\.\d+\.\d+',tag) or release.get('draft') or release.get('prerelease'):raise SafetyError('stable-reviewed-release-required')
  latest=tag[1:];new=version_key(latest)>version_key(current_version)
  return {'status':'update-available' if new else 'current-or-newer','repository':REPOSITORY,'currentVersion':current_version,'latestVersion':latest,'tag':tag,'updateAvailable':new,'release':release,'taskActive':busy(self.state),'activation':'idle-verified-unmodified-only'}
 def download(self,check):
  version=check['latestVersion'];version_key(version);name='heideng-ops-agent-merchant-'+version+'.zip';release=check['release'];assets={a['name']:a for a in release.get('assets',[])}
  if name not in assets or 'SHA256SUMS' not in assets or assets[name].get('size',0)>64*1024*1024 or assets['SHA256SUMS'].get('size',0)>16384:raise SafetyError('verified-release-assets-required')
  destination=safe_join(self.state,'updates/'+check['tag']+'-'+uuid.uuid4().hex);destination.mkdir(parents=True)
  env=github_environment();opts={'capture_output':True,'text':True,'encoding':'utf-8','errors':'strict','timeout':180,'env':env}
  if os.name=='nt':opts['creationflags']=0x08000000
  for asset in ('SHA256SUMS',name):
   p=self.runner(['gh','release','download',check['tag'],'--repo',REPOSITORY,'--pattern',asset,'--dir',str(destination)],**opts)
   if p.returncode!=0:raise SafetyError('github-download-incomplete-no-install')
  archive=safe_join(destination,name);sums=safe_join(destination,'SHA256SUMS').read_text(encoding='ascii')
  expected=None
  for line in sums.splitlines():
   fields=line.split()
   if len(fields)==2 and fields[1]==name and re.fullmatch('[0-9a-f]{64}',fields[0]):
    if expected:raise SafetyError('duplicate-release-checksum')
    expected=fields[0]
  if not expected or archive.stat().st_size>64*1024*1024 or file_sha(archive)!=expected:raise SafetyError('release-sha256-mismatch')
  atomic_json(destination/'download-receipt.json',{'repository':REPOSITORY,'tag':check['tag'],'archive':name,'sha256':expected})
  return archive,expected
 def apply(self,target):
  current=verify_install(target)
  if not current['valid']:raise SafetyError('update-refuses-unmanaged-or-modified-install')
  check=self.check(current['version'])
  if not check['updateAvailable']:return {k:v for k,v in check.items() if k!='release'}
  if busy(self.state):raise SafetyError('task-active-update-deferred')
  archive,sha=self.download(check);return install_archive(archive,target,self.state,expected_sha=sha)
