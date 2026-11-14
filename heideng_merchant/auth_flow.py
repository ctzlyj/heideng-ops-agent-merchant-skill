"""Single-owner authentication state machine. Private OAuth streams stay in memory."""
from __future__ import annotations
import hashlib,json,queue,re,threading,time,urllib.parse
from pathlib import Path
from . import VERSION
from .safety import SafetyError,atomic_json,redact,safe_join,read_json
from .official import validate_profile
from .operations import Operations

JINGMAI_HOSTS={'jingmai.jd.com','api.m.jd.com'}

def eligible_identity_source(url):
 if not isinstance(url,str) or len(url)>16384 or any(ord(c)<32 for c in url):return False
 try:
  p=urllib.parse.urlsplit(url)
  if p.port not in (None,443):return False
 except ValueError:return False
 host=(p.hostname or '').lower()
 return p.scheme=='https' and not p.username and not p.password and (host in JINGMAI_HOSTS or host.endswith('.jingmai.jd.com'))

def public_source(url):
 p=urllib.parse.urlsplit(url);return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,'',''))

class BrowserIdentityProof:
 def __init__(self,shop_name,vender_id=None):self.shop_name=shop_name;self.vender_id=str(vender_id) if vender_id else None;self.matches={};self.observed=0
 def observe_json(self,url,payload):
  if not eligible_identity_source(url) or not isinstance(payload,(dict,list)):return
  try:sha=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
  except (TypeError,ValueError):return
  self.observed+=1
  def visit(value,path=''):
   if isinstance(value,dict):
    name=value.get('shopName');vid=value.get('venderId',value.get('vendorId'))
    if not name and isinstance(value.get('shopBaseInfo'),dict):name=value['shopBaseInfo'].get('shopName')
    shop_type=value.get('shopType')
    if isinstance(value.get('shopBaseInfo'),dict):shop_type=value['shopBaseInfo'].get('type',shop_type)
    if name==self.shop_name and str(vid or '').isdigit() and (self.vender_id is None or str(vid)==self.vender_id) and str(shop_type)!='1':
     self.matches[str(vid)]={'shopName':name,'venderId':str(vid),'source':public_source(url),'responseSha256':sha,'fieldPath':path or '$','evidence':'task-context-network-response'}
    for key,child in value.items():
     if isinstance(child,(dict,list)):visit(child,path+'.'+str(key))
   elif isinstance(value,list):
    for i,child in enumerate(value[:200]):visit(child,path+'['+str(i)+']')
  visit(payload)
 def proof(self):return next(iter(self.matches.values())) if len(self.matches)==1 else None
 def summary(self):return {'observedIdentityResponses':self.observed,'matchingIdentityCount':len(self.matches),'ambiguous':len(self.matches)>1}

def valid_oauth_url(url):
 if not isinstance(url,str) or len(url)>16384 or any(ord(c)<32 for c in url):return False
 try:
  p=urllib.parse.urlsplit(url)
  if p.port not in (None,443):return False
 except ValueError:return False
 return p.scheme=='https' and p.hostname=='open-oauth.jd.com' and not p.username and not p.password and p.path.startswith('/oauth2/')

def _decode(raw):
 if isinstance(raw,str):return raw
 try:return raw.decode('utf-8-sig')
 except UnicodeDecodeError:return raw.decode('gb18030')

def _contains_mock(value):
 if isinstance(value,dict):return value.get('mock') is True or value.get('tokenMocked') is True or value.get('authorizationStatus')=='mock_token_stored' or any(_contains_mock(v) for v in value.values())
 if isinstance(value,list):return any(_contains_mock(v) for v in value)
 return False

def complete_login_receipt(value,profile):
 if not isinstance(value,dict):return False
 if value.get('command')!='login' or value.get('profile')!=profile:return False
 if any(value.get(key) is not True for key in ('ok','loginCompleted','appKeyConfigured','tokenStored','appSecretStored')):return False
 if value.get('tokenMocked') is not False:return False
 pairs={'logged_in':'credential_saved','reused_existing_credentials':'credential_reuse'}
 if value.get('authorizationStatus') not in pairs or value.get('authorizationStage')!=pairs[value['authorizationStatus']]:return False
 if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',str(value.get('cliVersion',''))):return False
 return isinstance(value.get('timestamp'),int) and not isinstance(value['timestamp'],bool) and value['timestamp']>0

class AuthFlow:
 TERMINAL={'ready','identity_mismatch','oauth_failed','auth_outcome_unknown','cancelled','timed_out','browser_failed'}
 def __init__(self,state,job_id,profile,shop_name,client,browser,*,expected_vender_id=None,clock=None,timeout=900):
  if not re.fullmatch('[a-f0-9]{24}',job_id):raise SafetyError('invalid-auth-job-id')
  validate_profile(profile)
  if not profile.startswith('merchant-') or not shop_name:raise SafetyError('merchant-auth-namespace-required')
  self.state=Path(state);self.path=safe_join(self.state,'tasks/'+job_id+'.json');self.client=client;self.browser=browser;self.clock=clock or time.time;self.deadline=self.clock()+timeout;self.process=None;self._urls=queue.Queue(maxsize=1);self._stdout=[];self._stdout_done=threading.Event();self._overflow=False;self._oauth_url=None;self._navigated=False;self._started=False
  self.data={'kind':'shop-auth','taskId':job_id,'profile':profile,'shopName':shop_name,'venderId':str(expected_vender_id or ''),'status':'running','stage':'created','ready':False,'runtimeVersion':VERSION,'createdAt':self.clock()}
  prior=read_json(self.path,{})
  if prior.get('kind')=='shop-auth' and prior.get('taskId')==job_id and prior.get('profile')==profile and re.fullmatch('[a-f0-9]{24}',str(prior.get('restartOf',''))):self.data['restartOf']=prior['restartOf']
  self.registrar=Operations(self.state,self.client)
  self._save()
 def _save(self):self.data['updatedAt']=self.clock();atomic_json(self.path,self.data)
 def status(self):return dict(self.data)
 def _stderr_reader(self):
  try:
   for raw in iter(lambda:self.process.stderr.readline(16385),b''):
    try:text=_decode(raw).strip()
    except UnicodeError:continue
    if valid_oauth_url(text):
     try:self._urls.put_nowait(text)
     except queue.Full:pass
  except Exception:pass
 def _stdout_reader(self):
  total=0
  try:
   while True:
    raw=self.process.stdout.read(4096)
    if not raw:break
    raw=raw.encode() if isinstance(raw,str) else raw;total+=len(raw)
    if total>1024*1024:self._overflow=True
    elif not self._overflow:self._stdout.append(raw)
  except Exception:self._overflow=True
  finally:self._stdout_done.set()
 def _finish(self):
  if not self._stdout_done.wait(.2):return
  if self._overflow:self.data.update(stage='auth_outcome_unknown',status='unknown',reason='official-result-too-large');self._close();return
  try:result=json.loads(_decode(b''.join(self._stdout)) or '{}')
  except (ValueError,UnicodeError):result={}
  self._stdout.clear();self._oauth_url=None
  if _contains_mock(result):
   self.data.update(stage='oauth_failed',status='failed',reason='mock-authorization-rejected');self._close();return
  if self.process.poll()!=0 or not complete_login_receipt(result,self.data['profile']):
   self.data.update(stage='auth_outcome_unknown',status='unknown',reason='official-oauth-incomplete-no-replay');self._close();return
  self.data['stage']='verifying_cli';self._save()
  try:identity=self.client.identity(self.data['profile'])
  except Exception:self.data.update(stage='auth_outcome_unknown',status='unknown',reason='token-outcome-awaits-realtime-query');self._close();return
  if identity.get('shopType')!='POP' or identity.get('shopName')!=self.data['shopName'] or str(identity.get('venderId'))!=self.data['venderId']:
   self.data.update(stage='identity_mismatch',status='failed',reason='authorized-shop-does-not-match-target');self._close();return
  try:registered=self.registrar.connect(self.data['profile'],self.data['shopName'],self.data['venderId'])
  except Exception:self.data.update(stage='auth_outcome_unknown',status='unknown',ready=False,reason='shop-registration-awaits-realtime-recovery');self._close();return
  self.data.update(stage='ready',status='completed',ready=True,identity=registered,finishedAt=self.clock());self._close()
 def _close(self):
  if self.process is not None:
   try:
    if hasattr(self.client,'stop_login'):self.client.stop_login(self.process)
    elif self.process.poll() is None:self.process.terminate();self.process.wait(timeout=3)
   except Exception:self.data['cleanupIncomplete']=True
  try:self.browser.close()
  except Exception:self.data['cleanupIncomplete']=True
  if self.data.get('cleanupIncomplete'):
   unknown=self.process is not None or self.data.get('authorizationStarted',False)
   self.data.update(ready=False,stage='auth_outcome_unknown' if unknown else 'browser_failed',status='unknown' if unknown else 'failed',reason='owned-auth-cleanup-incomplete-no-replay')
  self._oauth_url=None;self._save()
 def cancel(self,timeout=False):
  started=self.process is not None or self.data.get('authorizationStarted',False)
  self.data.update(stage='auth_outcome_unknown' if timeout and started else 'timed_out' if timeout else 'cancelled',status='unknown' if started else 'cancelled',ready=False,authorizationOutcomeUnknown=started)
  self._close()
 def tick(self):
  if self.data['stage'] in self.TERMINAL:return self.status()
  if self.clock()>self.deadline:self.cancel(timeout=True);return self.status()
  if not self._started:
   self._started=True
   try:self.browser.open_jingmai()
   except Exception:self.data.update(stage='browser_failed',status='failed',reason='task-browser-unavailable');self._close();return self.status()
   self.data['stage']='waiting_login';self._save();return self.status()
  try:self.browser.poll()
  except Exception:self.data.update(stage='browser_failed',status='unknown' if self.process else 'failed');self._close();return self.status()
  if self.data['stage']=='waiting_login':
   proof=self.browser.proof()
   if not proof:return self.status()
   if proof.get('shopName')!=self.data['shopName'] or not str(proof.get('venderId','')).isdigit() or (self.data['venderId'] and str(proof['venderId'])!=self.data['venderId']) or not eligible_identity_source(proof.get('source','')):return self.status()
   self.data['venderId']=str(proof['venderId']);self.data['browserIdentityProof']=redact(proof)
   try:
    self.client.initialize(self.data['profile'],vender_id=self.data['venderId'],shop_name=self.data['shopName'])
    self.data['authorizationStarted']=True;self._save()
    self.process=self.client.login_process(self.data['profile'],self.data['shopName'],self.data['venderId'])
   except Exception:self.data.update(stage='auth_outcome_unknown' if self.data.get('authorizationStarted') else 'oauth_failed',status='unknown' if self.data.get('authorizationStarted') else 'failed',reason='official-auth-start-not-confirmed-no-replay');self._close();return self.status()
   self.data.update(stage='waiting_callback_server');self._save()
   threading.Thread(target=self._stderr_reader,daemon=True).start();threading.Thread(target=self._stdout_reader,daemon=True).start()
  if self.process:
   if self.process.poll() is not None:self._finish();return self.status()
   if not self._oauth_url:
    try:self._oauth_url=self._urls.get(timeout=.01)
    except queue.Empty:pass
   if self._oauth_url and not self._navigated:
    try:owned=self.client.callback_owned(self.process)
    except Exception:owned=False
    if owned:
     try:self.browser.navigate_oauth(self._oauth_url)
     except Exception:self.data.update(stage='auth_outcome_unknown',status='unknown',reason='oauth-navigation-outcome-unknown');self._close();return self.status()
     self._navigated=True;self.data['stage']='waiting_oauth';self.data['sameContextNavigation']=True;self._save()
  return self.status()
