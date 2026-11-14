"""Explicitly deferred media contracts. No model selection or network fallback."""
import ipaddress,re,urllib.parse
from pathlib import Path
from .safety import SafetyError,atomic_json,read_json

INTERNAL=('jd.local','jd.com','oxygen','joybuilder','360buyimg.com','skillhub')

def validate_external_endpoint(url):
 if not isinstance(url,str):raise SafetyError('external-https-endpoint-required')
 p=urllib.parse.urlsplit(url);host=(p.hostname or '').lower().rstrip('.')
 if p.scheme!='https' or not host or p.username or p.password or p.query or p.fragment or p.port not in (None,443):raise SafetyError('external-https-endpoint-required')
 if any(x in host for x in INTERNAL) or host=='localhost' or host.endswith(('.local','.internal','.localhost')):raise SafetyError('internal-media-source-forbidden')
 try:
  if not ipaddress.ip_address(host).is_global:raise SafetyError('private-media-source-forbidden')
 except ValueError:pass
 if not re.fullmatch('[a-z0-9.-]+',host):raise SafetyError('invalid-external-host')
 return url

def media_status():
 return {kind:{'status':'awaiting-provider','reason':'生图和生成视频来源等待用户确认；不读取旧Key，不调用任何内部或默认付费模型','paidCalls':0} for kind in ('image','video')}

class MediaConfiguration:
 def __init__(self,state):self.path=Path(state)/'media-contracts.json'
 def status(self):
  result=media_status();config=read_json(self.path,{})
  for kind,contract in config.items():result[kind]={'status':'contract-recorded-adapter-pending','provider':contract['provider'],'model':contract['model'],'generationEnabled':False}
  return result
 def configure(self,kind,contract,*,selection_confirmed=False):
  if kind not in ('image','video') or not selection_confirmed:raise SafetyError('explicit-media-source-selection-required')
  if not isinstance(contract,dict) or set(contract)-{'provider','endpoint','model','documentation','limits','pricingEvidence','credentialSlot'}:raise SafetyError('nonsecret-media-contract-required')
  provider=str(contract.get('provider','')).lower()
  if not provider or any(t in provider for t in INTERNAL):raise SafetyError('internal-media-provider-forbidden')
  validate_external_endpoint(contract.get('endpoint'))
  if not contract.get('model') or not contract.get('documentation') or not contract.get('pricingEvidence'):raise SafetyError('current-model-and-pricing-evidence-required')
  config=read_json(self.path,{});config[kind]=contract;atomic_json(self.path,config)
  return self.status()[kind]
 def generation_request(self,kind,payload):
  # User intentionally reserved these actual model sources. Recording a contract is not spend approval.
  raise SafetyError('media-generation-deferred-until-selected-adapter-and-explicit-budget-approval')
