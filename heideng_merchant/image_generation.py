"""Thin merchant binding for the established MIT LTS4AI image client."""
from __future__ import annotations
import os,re,time
from decimal import Decimal,InvalidOperation
from pathlib import Path
from . import lts4ai_client as client
from .operations import digest
from .safety import SafetyError,atomic_json,read_json,file_sha,is_linked,redact
from .state import FileLock

ENDPOINT='https://api.lts4ai.com/v1'
MODEL='gpt-image-2.5'

def positive_amount(value):
 try:amount=Decimal(str(value))
 except InvalidOperation:raise SafetyError('valid-image-quote-and-budget-required') from None
 if not amount.is_finite() or amount<=0:raise SafetyError('positive-image-quote-and-budget-required')
 return amount

def checked_path(value):
 if not isinstance(value,str) or not value:raise SafetyError('image-path-required')
 path=Path(value).absolute()
 if any(is_linked(part) for part in (path,*path.parents)):raise SafetyError('linked-image-path-forbidden')
 return path.resolve()

class ImageGeneration:
 def __init__(self,state):self.root=Path(state)/'image-generation'
 def path(self,plan_id):
  if not isinstance(plan_id,str) or not re.fullmatch('[a-f0-9]{64}',plan_id):raise SafetyError('invalid-image-plan-id')
  return self.root/(plan_id+'.json')
 def status(self,plan_id):
  plan=read_json(self.path(plan_id))
  if not isinstance(plan,dict) or plan.get('planId')!=plan_id or digest(plan.get('scope'))!=plan.get('fingerprint'):raise SafetyError('image-plan-missing-or-changed')
  if plan['scope']['endpoint']!=ENDPOINT or plan['scope']['model']!=MODEL:raise SafetyError('selected-image-provider-mismatch')
  return plan
 def plan(self,request):
  allowed={'requestId','prompt','size','count','images','outputDirectory','budget','quote'}
  if not isinstance(request,dict) or set(request)-allowed or redact(request)!=request:raise SafetyError('nonsecret-fixed-provider-image-request-required')
  request_id=request.get('requestId');prompt=request.get('prompt');count=request.get('count',1);size=request.get('size','1024x1024')
  if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',request_id):raise SafetyError('stable-image-request-id-required')
  if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>32000:raise SafetyError('image-prompt-required')
  if type(count)!=int or not 1<=count<=10:raise SafetyError('image-count-must-be-1-to-10')
  try:client.validate_resolution(size)
  except (client.SkillError,TypeError):raise SafetyError('supported-image-size-required') from None
  quote=request.get('quote')
  if not isinstance(quote,dict) or set(quote)!={'unitCost','currency','evidence','observedAt'}:raise SafetyError('current-nonsecret-image-quote-required')
  if quote['currency']!='LTS4AI-points' or quote['evidence'] not in ('https://api.lts4ai.com/pricing','https://api.lts4ai.com/api/pricing'):raise SafetyError('lts4ai-current-price-evidence-required')
  observed=quote['observedAt']
  if type(observed) not in (int,float) or not -60<=time.time()-observed<=86400:raise SafetyError('fresh-image-price-quote-required')
  unit=positive_amount(quote['unitCost']);budget=positive_amount(request.get('budget'));total=unit*count
  if total>budget:raise SafetyError('image-estimate-exceeds-approved-budget')
  paths=request.get('images',[])
  if not isinstance(paths,list):raise SafetyError('image-reference-list-required')
  images=[]
  if paths:
   try:refs=client.validate_reference_images([checked_path(p) for p in paths])
   except client.SkillError:raise SafetyError('supported-image-references-required') from None
   images=[{'path':str(ref.path),'sha256':file_sha(ref.path)} for ref in refs]
  scope={'requestId':request_id,'endpoint':ENDPOINT,'model':MODEL,'prompt':prompt.strip(),'size':size,'count':count,'images':images,'outputDirectory':str(checked_path(request.get('outputDirectory'))),'budget':str(budget),'quote':quote,'estimatedPoints':str(total)}
  plan_id=digest({'imageRequestId':request_id});fingerprint=digest(scope)
  with FileLock(self.root/(plan_id+'.lock')):
   if self.path(plan_id).exists():
    existing=self.status(plan_id)
    if existing['fingerprint']!=fingerprint:raise SafetyError('existing-image-request-scope-mismatch')
    return existing
   plan={'planId':plan_id,'fingerprint':fingerprint,'scope':scope,'status':'prepared','outputs':[],'attemptedRequests':0,'paidCallsVerified':False,'visualReviewRequired':True,'shopWrites':0}
   atomic_json(self.path(plan_id),plan);return plan
 def approve(self,plan_id,fingerprint,*,confirmed=False):
  self.path(plan_id)
  with FileLock(self.root/(plan_id+'.lock')):
   plan=self.status(plan_id)
   if not confirmed or fingerprint!=plan['fingerprint'] or plan['status'] not in ('prepared','approved'):raise SafetyError('exact-image-scope-and-budget-approval-required')
   if plan['status']=='approved':return plan
   plan.update(status='approved',approval={'fingerprint':fingerprint,'expiresAt':time.time()+900})
   atomic_json(self.path(plan_id),plan);return plan
 def execute(self,plan_id):
  path=self.path(plan_id)
  with FileLock(self.root/(plan_id+'.lock')):
   plan=self.status(plan_id)
   if plan['status'] in ('completed','unknown'):return plan
   if plan['status']=='submitting':
    plan.update(status='unknown',reason='interrupted-image-attempt-query-original-before-any-new-submission');atomic_json(path,plan);return plan
   approval=plan.get('approval',{})
   if plan['status']!='approved' or approval.get('fingerprint')!=plan['fingerprint'] or approval.get('expiresAt',0)<time.time():raise SafetyError('exact-image-scope-and-budget-approval-required')
   scope=plan['scope'];output=checked_path(scope['outputDirectory']);refs=[]
   for image in scope['images']:
    p=checked_path(image['path'])
    if file_sha(p)!=image['sha256']:raise SafetyError('approved-image-reference-changed')
    refs.append(p)
   key=os.environ.get('LTS4AI_API_KEY','').strip()
   if not key:raise SafetyError('merchant-lts4ai-key-required-secure-process-environment-no-internal-fallback')
   api=client.SfImage2Client(api_key=key,base_url=ENDPOINT,model=MODEL,retries=0,timeout=1800 if scope['size'].startswith(('2880','3840')) else 600)
   for index in range(scope['count']):
    if approval['expiresAt']<time.time():
     plan.update(status='approval-expired',reason='unsubmitted-images-not-generated');atomic_json(path,plan);return plan
    plan.update(status='submitting',attemptedRequests=index+1);atomic_json(path,plan)
    try:
     stem=plan_id[:12]+'-'+str(index+1)
     image=api.edit(scope['prompt'],client.validate_reference_images(refs),scope['size'],output,stem) if refs else api.generate(scope['prompt'],scope['size'],output,stem)
     plan['outputs'].append({'path':str(image.path),'sha256':file_sha(image.path),'mimeType':image.mime_type,'bytes':image.size,'dimensions':client.read_image_dimensions(image.path)})
    except Exception:
     plan.update(status='unknown',reason='image-attempt-unresolved-do-not-resubmit-query-original-or-account-billing');atomic_json(path,plan);return plan
    atomic_json(path,plan)
   plan.update(status='completed');atomic_json(path,plan);return plan
