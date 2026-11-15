"""Full-source new-product validation and separately authorized native submission."""
import copy,json,uuid
from pathlib import Path
from .operations import Operations
from .publish_support import PublishSupport
from .publication_contract import VALIDATE,PUBLISH,new_body,canonical_schema,read_input_json,checked_validation,receipt
from .products import identifier
from .safety import SafetyError

class PublishService:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def plan_validation(self,profile,manifest_path,schema,spec_map,asset_bindings):
  path=Path(manifest_path).absolute();manifest,sha=read_input_json(path)
  body={'scene':'pop','schema':json.dumps(canonical_schema(schema),ensure_ascii=False,separators=(',',':'),allow_nan=False),'productApplyDTO':{'categoryDTO':{'lastCategoryId':int(identifier(manifest.get('categoryId')))}}}
  operation={'url':VALIDATE,'method':'POST','params':{},'body':body,'skillId':'jdo-product-publish'}
  category,_,top,rows=new_body(operation)
  context=PublishSupport(self.state,self.client).context(profile,category,identifier(top.get('WareBrand',{}).get('value')))
  proof={'manifestPath':str(path),'manifestSha256':sha,'specMap':copy.deepcopy(spec_map),'assetBindings':copy.deepcopy(asset_bindings),'contextHash':context['contextHash'],'intentId':uuid.uuid4().hex,'publicationIntentId':manifest.get('publication',{}).get('intentId')}
  task=self.ops.prepare(profile,operation,listing_input=proof)
  return {'task':task,'skuCount':len(rows),'phase':'validation-awaiting-approval','productCount':1,'productSubmitted':False,'source':'original-full-listing-and-current-merchant-schema','notice':'Validation POST requires exact approval; it does not publish. Changed content needs new approval.'}
 def validation_status(self,task_id):
  task=self.ops.task(task_id)
  if task['scope']['operation']['url']!=VALIDATE or task['scope']['operation']['method']!='POST':raise SafetyError('native-validation-task-required')
  phase='unknown' if task['status']=='unknown' else ('validation-'+task.get('validationVerdict','not-started'))
  return {'task':task,'phase':phase,'validationPassed':task['status']=='completed' and task.get('validationVerdict')=='passed','productSubmitted':False,'onlineEffective':False}
 def plan_publish(self,validation_task_id):
  validation=self.ops.task(validation_task_id);scope=validation['scope'];checked_validation(self.ops,validation_task_id,scope['operation'].get('body'),scope['shop'])
  operation={**scope['operation'],'url':PUBLISH}
  task=self.ops.prepare(scope['shop']['profile'],operation,listing_input=scope['nativeListingInput'],validated_task_id=validation_task_id)
  _,_,_,rows=new_body(operation)
  return {'task':task,'skuCount':len(rows),'productCount':1,'phase':'publication-awaiting-approval' if task['status']=='prepared' else 'existing-publication-request','requiresApproval':task['status']=='prepared','onlineEffective':False,'notice':'One new product with the entire source SKU range. Receipt, audit and online effectiveness are separate.'}
 def status(self,task_id):
  task=self.ops.task(task_id);op=task['scope']['operation']
  if op['url']!=PUBLISH or op['method']!='POST':raise SafetyError('native-publication-task-required')
  result=receipt(task['result']) if task.get('result') is not None and task['status'] in ('submitted','verified') else None
  return {'task':task,'phase':'unknown' if task['status']=='unknown' else ('submission-receipt-known' if result else task['status']),'receipt':result,'onlineEffective':False,'allSkuOnlineVerified':False,'productImagesOnlineVerified':False}
