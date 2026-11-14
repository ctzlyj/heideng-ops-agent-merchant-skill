"""On-demand public browser dependencies in a merchant-owned virtual environment."""
from __future__ import annotations
import json,os,re,subprocess,sys,urllib.request,uuid
from pathlib import Path
from .safety import SafetyError,safe_join,atomic_json,read_json,clean_environment,file_sha
from .state import FileLock

PACKAGES=('playwright','psutil')

def pypi_metadata(url):
 if not re.fullmatch(r'https://pypi\.org/pypi/(playwright|psutil)/json',url):raise SafetyError('public-runtime-source-required')
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=30) as response:raw=response.read(4*1024*1024+1)
  if len(raw)>4*1024*1024:raise SafetyError('runtime-metadata-too-large')
  return json.loads(raw)
 except Exception:raise SafetyError('public-runtime-metadata-unavailable') from None

class BrowserRuntime:
 def __init__(self,state,*,runner=None,metadata=None):self.state=Path(state).resolve();self.runner=runner or subprocess.run;self.metadata=metadata or pypi_metadata;self.receipt=self.state/'runtime'/'browser-runtime.json'
 def _run(self,args,home,timeout=300):
  env=clean_environment(home);env['PIP_CONFIG_FILE']=os.devnull
  opts={'env':env,'cwd':str(home),'capture_output':True,'timeout':timeout}
  if os.name=='nt':opts['creationflags']=0x08000000
  try:p=self.runner(args,**opts)
  except (OSError,subprocess.TimeoutExpired):raise SafetyError('browser-runtime-step-incomplete-check-local-state') from None
  if p.returncode!=0:raise SafetyError('browser-runtime-step-failed-no-internal-fallback')
  return p.stdout
 def _probe(self,python,home):
  code="import importlib.metadata as m,json; print(json.dumps({name:m.version(name) for name in ('playwright','psutil')}))"
  raw=self._run([str(python),'-I','-c',code],home,30)
  try:return json.loads(raw)
  except ValueError:raise SafetyError('browser-runtime-probe-invalid') from None
 def ready(self):
  receipt=read_json(self.receipt,{})
  if not receipt:return False
  try:
   python=safe_join(self.state,receipt['python']);home=safe_join(self.state,receipt['home'])
   return python.is_file() and file_sha(python)==receipt['pythonSha256'] and self._probe(python,home)==receipt['packages']
  except (KeyError,OSError,SafetyError):return False
 def status(self):
  receipt=read_json(self.receipt,{})
  return {'status':'ready' if self.ready() else 'not-prepared','packages':receipt.get('packages',{}),'source':'public-pypi','isolated':True}
 def python(self):
  if not self.ready():raise SafetyError('browser-runtime-not-prepared')
  return safe_join(self.state,read_json(self.receipt)['python'])
 def ensure(self):
  with FileLock(self.state/'runtime'/'install.lock',timeout=10):
   if self.ready():return self.status()
   if read_json(self.receipt):raise SafetyError('existing-browser-runtime-changed-preserve-and-review')
   sources={};pins={}
   for name in PACKAGES:
    info=self.metadata('https://pypi.org/pypi/'+name+'/json');version=info.get('info',{}).get('version','')
    if not re.fullmatch('[0-9][0-9A-Za-z._+-]{0,40}',version):raise SafetyError('invalid-browser-runtime-version')
    pins[name]=version;sources[name]={'url':'https://pypi.org/pypi/'+name+'/json','version':version,'license':info.get('info',{}).get('license') or info.get('info',{}).get('license_expression'),'artifactSha256':[r.get('digests',{}).get('sha256') for r in info.get('urls',[]) if r.get('packagetype')=='bdist_wheel']}
   relative='runtime/browser-'+uuid.uuid4().hex;root=safe_join(self.state,relative);root.mkdir(parents=True);home=root/'home';home.mkdir()
   self._run([sys.executable,'-I','-m','venv',str(root/'venv')],home,90)
   python=root/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
   self._run([str(python),'-I','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--no-cache-dir','--only-binary=:all:',*[name+'=='+pins[name] for name in PACKAGES]],home,300)
   actual=self._probe(python,home)
   if actual!=pins:raise SafetyError('browser-runtime-package-version-mismatch')
   record={'python':python.relative_to(self.state).as_posix(),'home':home.relative_to(self.state).as_posix(),'pythonSha256':file_sha(python),'packages':actual,'sources':sources,'channel':'system-chrome-or-edge','status':'ready'}
   atomic_json(self.receipt,record);return self.status()
