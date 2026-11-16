"""Thin stdin bridge to the original linker's task-owned host-controller contract.

The host discovers real interfaces/DOM and returns normalized identity; this
adapter never guesses JD request domains or fields, reads cookies, or exports
private action URLs. Only action id/kind/phase receipts are persisted.
"""
from __future__ import annotations
import hashlib,json,os,re,subprocess,time,uuid
from pathlib import Path
from .auth_flow import valid_oauth_url, JINGMAI_LOGIN_URL, ObservationUnavailable
from .safety import SafetyError,atomic_json,clean_environment,redact,safe_join

SHELLS={'cmd','cmd.exe','powershell','powershell.exe','pwsh','pwsh.exe','sh','bash','zsh','wscript.exe','cscript.exe'}
def validate_controller(command):
 if not isinstance(command,list) or not 1<=len(command)<=32 or any(not isinstance(x,str) or not x or len(x)>4096 or any(ord(c)<32 for c in x) or redact(x)!=x or valid_oauth_url(x) for x in command):raise SafetyError('safe-host-browser-controller-required')
 if any(re.search(r'(?i)^--?(?:api[_-]?key|(?:access|auth|session)[_-]?token|token|cookie|authorization|password|secret|credential|device[_-]?id|pt[_-]?(?:key|pin))(?:=|$)|^sk-[A-Za-z0-9_-]{12,}$|^gh[pousr]_[A-Za-z0-9]{20,}$',x) for x in command):raise SafetyError('credentials-not-allowed-in-host-controller-argv')
 executable=command[0].replace('\\','/').split('/')[-1].lower()
 if executable in SHELLS or executable.endswith(('.cmd','.bat')):raise SafetyError('direct-host-browser-controller-required-no-shell')
 return list(command)

def verify_host_cleanup(state,job,profile,controller,actions,*,runner=None):
 """Inspect existing task resources only; never close, authorize or replay an action."""
 command=validate_controller(controller)
 action_ids=sorted(actions)
 binding=hashlib.sha256(json.dumps(actions,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 home=safe_join(Path(state),'auth/host-homes/'+job);home.mkdir(parents=True,exist_ok=True)
 payload={'jobId':job,'action':{'id':uuid.uuid4().hex,'kind':'verify_cleanup','profile':profile,'actionIds':action_ids,'receiptSha256':binding}}
 options={'input':json.dumps(payload).encode(),'capture_output':True,'timeout':15,'cwd':str(home),'env':clean_environment(home)}
 if os.name=='nt':options['creationflags']=0x08000000
 try:
  process=(runner or subprocess.run)(command,**options)
  if process.returncode or len(process.stdout)>65536:raise ValueError()
  result=json.loads(process.stdout)
  if (not isinstance(result,dict) or result.get('ok') is not True or result.get('error') or result.get('taskId')!=job or result.get('actionIds')!=action_ids or result.get('inspectionId')!=payload['action']['id']
      or result.get('owned') is not True or result.get('inspectionVerified') is not True or result.get('noLiveTaskResources') is not True):raise ValueError()
 except Exception:raise SafetyError('owned-host-cleanup-not-proven-original-task-preserved') from None
 return {'taskId':job,'inspectionId':payload['action']['id'],'actionIds':action_ids,'receiptSha256':binding,'cleanupVerified':True,'source':'owned-host-controller-inspection'}

class HostControllerBrowser:
 def __init__(self,state,job,shop_name,controller,*,vender_id=None,runner=None,clock=None,observe_interval=2):
  if not isinstance(job,str) or re.fullmatch('[a-f0-9]{24}',job) is None:raise SafetyError('invalid-auth-job-id')
  self.command=validate_controller(controller);self.state=Path(state);self.job=job;self.shop_name=shop_name;self.vender_id=str(vender_id) if vender_id else None
  self.runner=runner or subprocess.run;self.clock=clock or time.monotonic;self.interval=observe_interval;self.next_observe=0
  self.context_id=None;self.candidate=None;self.selected=None;self.stage='not-opened';self.observed=0;self.challenge='';self.action_uncertain=False;self.ownership_lost=False
 def _call(self,kind,**fields):
  action={'id':uuid.uuid4().hex,'kind':kind,**fields}
  if self.context_id:action['expectedContextId']=self.context_id
  receipt=safe_join(self.state,'auth/browser-actions/'+self.job+'/'+action['id']+'.json')
  if kind!='observe':atomic_json(receipt,{'taskId':self.job,'actionId':action['id'],'kind':kind,'phase':'dispatched'})
  home=safe_join(self.state,'auth/host-homes/'+self.job);home.mkdir(parents=True,exist_ok=True)
  options={'input':json.dumps({'jobId':self.job,'action':action},ensure_ascii=False).encode(),'capture_output':True,'timeout':15,'cwd':str(home),'env':clean_environment(home)}
  if os.name=='nt':options['creationflags']=0x08000000
  if kind!='observe':self.action_uncertain=True
  try:
   try:process=self.runner(self.command,**options)
   except (TimeoutError,subprocess.TimeoutExpired,OSError):
    if kind=='observe':raise ObservationUnavailable('host-observe-transient-unavailable') from None
    raise
   if len(process.stdout)>65536:raise ValueError()
   try:result=json.loads(process.stdout)
   except ValueError:
    if process.returncode and kind=='observe':raise ObservationUnavailable('host-observe-transient-unavailable')
    raise
   if isinstance(result,dict) and (('owned' in result and result['owned'] is not True) or (self.context_id is not None and 'contextId' in result and result['contextId']!=self.context_id)):
    self.ownership_lost=True;raise ValueError()
   if process.returncode:
    if kind=='observe':raise ObservationUnavailable('host-observe-transient-unavailable')
    raise ValueError()
   if isinstance(result,dict) and kind=='observe' and result.get('error') in ('observation-unavailable','navigation-in-progress'):raise ObservationUnavailable('host-observe-transient-unavailable')
   if not isinstance(result,dict) or result.get('ok') is False or result.get('error'):raise ValueError()
   context=result.get('contextId')
   if result.get('owned') is not True or (self.context_id is not None and context!=self.context_id):self.ownership_lost=True
   if not isinstance(context,str) or not context or len(context)>200 or redact(context)!=context or result.get('owned') is not True:raise ValueError()
   if self.context_id is None:
    if result.get('isolated') is not True and result.get('verifiedReuse') is not True:raise ValueError()
   elif context!=self.context_id:raise ValueError()
   self.context_id=context
  except ObservationUnavailable:
   self.candidate=None;self.selected=None
   raise
  except Exception:
   self.candidate=None;self.selected=None
   raise SafetyError('host-browser-action-incomplete-check-original-task-no-replay') from None
  if kind!='observe':
   atomic_json(receipt,{'taskId':self.job,'actionId':action['id'],'kind':kind,'phase':'accepted'})
   self.action_uncertain=False
  return result
 def open_jingmai(self):
  if self.stage!='not-opened' or self.action_uncertain:raise SafetyError('task-browser-already-opened-or-dispatch-unknown')
  self._call('open_login',target=self.shop_name,url=JINGMAI_LOGIN_URL);self.stage='jingmai-login'
 def poll(self,*,force=False):
  if self.stage=='closed':raise SafetyError('task-browser-closed')
  if self.stage!='jingmai-login' or (not force and self.clock()<self.next_observe):return False
  self.next_observe=self.clock()+self.interval
  self.candidate=None
  result=self._call('observe');self.observed+=1;self.challenge=result.get('challenge','')
  if type(result.get('loggedIn')) is not bool or not isinstance(self.challenge,str):raise SafetyError('host-browser-observation-required')
  self.candidate=None
  if not result['loggedIn'] or self.challenge:return True
  identity=result.get('identity',{});name=identity.get('shopName') if isinstance(identity,dict) else None
  vid=str(identity.get('venderId',''));sid=str(identity.get('shopId',''))
  if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(c)<32 for c in name) or redact(name)!=name or re.fullmatch('[1-9][0-9]{0,19}',vid) is None or re.fullmatch('[1-9][0-9]{0,19}',sid) is None:raise SafetyError('host-browser-verified-identity-required')
  normalized={'shopName':name,'venderId':vid,'shopId':sid}
  sha=hashlib.sha256(json.dumps({'identity':normalized,'contextId':self.context_id},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  self.candidate={**normalized,'source':'host-tool-observation','responseSha256':sha,'fingerprint':sha,'evidence':'original-linker-host-controller-contract'}
  return True
 def candidates(self):return [dict(self.candidate)] if self.candidate else []
 def proof(self):
  return dict(self.candidate) if self.candidate and self.candidate['shopName']==self.shop_name and (not self.vender_id or self.candidate['venderId']==self.vender_id) else None
 def validates_identity(self,proof):return bool(self.context_id and self.candidate and proof==self.candidate)
 def select_identity(self,proof):
  if not self.validates_identity(proof):raise SafetyError('current-host-identity-required')
  self.selected=dict(proof)
 def navigate_oauth(self,url):
  if self.stage!='jingmai-login' or self.action_uncertain or not valid_oauth_url(url) or not self.selected:raise SafetyError('same-verified-host-context-required')
  self.poll(force=True)
  if not valid_oauth_url(url) or not self.selected or not self.validates_identity(self.selected):raise SafetyError('same-verified-host-context-required')
  self._call('open_oauth',url=url);self.stage='official-oauth'
 def public_observation(self):
  return {'browserStage':self.stage,'observedIdentityResponses':self.observed,'matchingIdentityCount':int(bool(self.proof())),'identityCandidateCount':int(bool(self.candidate)),'identityDiagnostic':'host-platform-confirmation-required' if self.challenge else 'identity-candidates-observed' if self.candidate else 'await-host-verified-shop-identity','privatePageContent':'not-exported','taskOwnedContext':bool(self.context_id),'browserProvider':'original-linker-host-controller'}
 def close(self):
  if self.stage=='closed':return
  if self.ownership_lost:raise SafetyError('host-browser-ownership-lost-cleanup-proof-required')
  if self.action_uncertain and not self.context_id:raise SafetyError('host-browser-cleanup-unconfirmed-check-original-task')
  if self.context_id:self._call('close')
  self.candidate=None;self.selected=None;self.context_id=None;self.stage='closed'
