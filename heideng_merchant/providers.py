"""Explicit user-selected media metadata. Selection never authorizes paid calls."""
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
 # Product-owner selection is public metadata, not a credential or spend approval.
 return {
  'image':{'status':'adapter-ready','provider':'lts4ai','endpoint':'https://api.lts4ai.com/v1','model':'gpt-image-2.5','documentedExamplePath':'/v1/chat/completions','documentation':'https://api.lts4ai.com/pricing','reference':'references/lts4ai-image.md','generationEnabled':True,'adapterAvailable':True,'requiresMerchantKey':True,'requiresExactBudgetApproval':True,'imageProtocolVerified':False,'liveVerified':False,'paidCalls':0,'reason':'LTS4AI / gpt-image-2.5已接入现成生图与参考图编辑客户端；需要商家自己的Key及本次预算批准，真实网关调用未实测'},
  'video':{'status':'awaiting-provider','generationEnabled':False,'paidCalls':0,'reason':'视频生成服务尚未选择；不读取旧Key，不调用内部或默认付费模型'}
 }

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
 def image_plan(self,request):
  from .image_generation import ImageGeneration
  return ImageGeneration(self.path.parent).plan(request)
 def image_approve(self,plan_id,fingerprint,*,confirmed=False):
  from .image_generation import ImageGeneration
  return ImageGeneration(self.path.parent).approve(plan_id,fingerprint,confirmed=confirmed)
 def image_status(self,plan_id):
  from .image_generation import ImageGeneration
  return ImageGeneration(self.path.parent).status(plan_id)
 def generation_request(self,kind,payload):
  if kind!='image':raise SafetyError('video-generation-provider-not-selected')
  if not isinstance(payload,dict) or set(payload)!={'planId'}:raise SafetyError('approved-image-plan-required')
  contract=read_json(self.path,{}).get('image')
  if contract and (contract.get('provider')!='lts4ai' or contract.get('model')!='gpt-image-2.5' or contract.get('endpoint')!='https://api.lts4ai.com/v1'):raise SafetyError('selected-image-provider-mismatch')
  from .image_generation import ImageGeneration
  return ImageGeneration(self.path.parent).execute(payload['planId'])
