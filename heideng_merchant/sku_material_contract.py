"""Reference-evidenced native SKU material contract; never an image generator."""
from __future__ import annotations
import copy, hashlib, json, re
from urllib.parse import urlsplit
from .safety import SafetyError, redact
from .verification import business_payload
from .material_contract import describe_upload, check_image_evidence, validate_image_receipt, IMAGE_DETAIL, SKILL as IMAGE_SKILL, _native_read

READ='/rest/sp-product/v0/sku-materials'
WRITE=READ+'/batch'
SKILL='jdo-api-830'
SLOTS={'white':(31,1),'scene1':(32,1),'scene2':(32,2),'selling':(33,1),'transparent':(36,1),'point1':(1002,1),'point2':(1002,2),'point3':(1002,3)}
GROUPS=(((31,32,33,36),1),((1002,),2))
MAX_SKUS=1000
BATCH=50

def hash_value(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def positive(value):
 from .products import identifier
 return identifier(value)

def integer(value):
 if isinstance(value,bool) or not isinstance(value,(int,str)) or not re.fullmatch(r'-?[0-9]{1,19}',str(value)):raise SafetyError('native-material-integer-required')
 return int(value)

def jfs(value):
 if not isinstance(value,str):raise SafetyError('native-material-image-path-required')
 if value.startswith('https://'):
  u=urlsplit(value)
  if not u.hostname or not u.hostname.endswith('.360buyimg.com') or u.username or u.password or u.port or u.query or u.fragment or '/jfs/' not in u.path:raise SafetyError('native-material-owned-cdn-path-required')
  value=u.path[u.path.index('/jfs/')+1:]
 if not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',value) or '..' in value or '//' in value:raise SafetyError('native-material-safe-jfs-path-required')
 return value

def identifiers(values,maximum=MAX_SKUS):
 if not isinstance(values,list) or not values or len(values)>maximum:raise SafetyError('bounded-complete-native-sku-scope-required')
 result=[positive(v) for v in values]
 if len(set(result))!=len(result):raise SafetyError('native-sku-scope-duplicate')
 return sorted(result,key=int)

def read(client,shop,url,params,skill=SKILL):
 return _native_read(client,shop,url,params) if skill==IMAGE_SKILL else _read(client,shop,url,params,skill)

def _read(client,shop,url,params,skill):
 from .official_transport import matches_shop
 if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-sku-material-shop-mismatch')
 result=client.invoke(shop['profile'],url,method='GET',params=params,skill_id=skill)
 if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-sku-material-shop-changed-during-read')
 if redact(result)!=result:raise SafetyError('private-material-response-refused')
 business_payload(result)
 return result

def validate_schema(value,schema,depth=0):
 # Deliberately bounded JSON Schema subset; unknown declarations fail closed.
 if depth>24 or not isinstance(schema,dict):raise SafetyError('native-capability-schema-unprovable')
 known={'type','properties','required','additionalProperties','items','minItems','maxItems','minLength','maxLength','minimum','maximum','enum','const','title','description','default','examples','$schema'}
 if set(schema)-known:raise SafetyError('native-capability-schema-needs-reviewed-adapter')
 kind=schema.get('type')
 checks={'object':lambda v:isinstance(v,dict),'array':lambda v:isinstance(v,list),'string':lambda v:isinstance(v,str),'integer':lambda v:isinstance(v,int) and not isinstance(v,bool),'number':lambda v:isinstance(v,(int,float)) and not isinstance(v,bool),'boolean':lambda v:isinstance(v,bool),'null':lambda v:v is None}
 if kind is not None and (not isinstance(kind,str) or kind not in checks or not checks[kind](value)):raise SafetyError('native-capability-input-type-mismatch')
 if 'enum' in schema and (not isinstance(schema['enum'],list) or not any(hash_value(value)==hash_value(v) for v in schema['enum'])):raise SafetyError('native-capability-input-enum-mismatch')
 if 'const' in schema and hash_value(value)!=hash_value(schema['const']):raise SafetyError('native-capability-input-constant-mismatch')
 if isinstance(value,dict):
  properties=schema.get('properties',{});required=schema.get('required',[])
  if not isinstance(properties,dict) or not isinstance(required,list) or any(not isinstance(v,str) for v in required) or not set(required)<=set(value):raise SafetyError('native-capability-required-fields-missing')
  extra=schema.get('additionalProperties',True)
  if not isinstance(extra,(bool,dict)):raise SafetyError('native-capability-additional-properties-unprovable')
  for key,child in value.items():
   if key in properties:validate_schema(child,properties[key],depth+1)
   elif extra is False:raise SafetyError('native-capability-additional-field-refused')
   elif isinstance(extra,dict):validate_schema(child,extra,depth+1)
 if isinstance(value,list):
  for key,lower in (('minItems',True),('maxItems',False)):
   if key in schema and (isinstance(schema[key],bool) or not isinstance(schema[key],int) or schema[key]<0 or (len(value)<schema[key] if lower else len(value)>schema[key])):raise SafetyError('native-capability-array-size-mismatch')
  if 'items' in schema:
   for child in value:validate_schema(child,schema['items'],depth+1)
 if isinstance(value,str):
  for key,lower in (('minLength',True),('maxLength',False)):
   if key in schema and (isinstance(schema[key],bool) or not isinstance(schema[key],int) or schema[key]<0 or (len(value)<schema[key] if lower else len(value)>schema[key])):raise SafetyError('native-capability-string-length-mismatch')
 if isinstance(value,(int,float)) and not isinstance(value,bool):
  for key,lower in (('minimum',True),('maximum',False)):
   if key in schema and (isinstance(schema[key],bool) or not isinstance(schema[key],(int,float)) or (value<schema[key] if lower else value>schema[key])):raise SafetyError('native-capability-number-range-mismatch')
 hash_value(value)

def capability(client,shop,method):
 api=('POST.sp-product.v0.sku-materials.batch' if method=='POST' else 'GET.sp-product.v0.sku-materials');path=WRITE if method=='POST' else READ
 # Exact read-only route used by the official cmd_info; no credentials in args.
 response=read(client,shop,'/rest/open-metadata/v0/apis/{apiname}',{'apiname':api});card=business_payload(response)
 if not isinstance(card,dict) or card.get('apiName')!=api or card.get('method')!=method or card.get('path') not in (path,path.removeprefix('/rest')):raise SafetyError('native-material-current-capability-route-mismatch')
 schema=card.get('inputSchema')
 if isinstance(schema,str):
  def unique(pairs):
   result={}
   for key,value in pairs:
    if key in result:raise SafetyError('native-capability-duplicate-schema-key')
    result[key]=value
   return result
  try:schema=json.loads(schema,object_pairs_hook=unique)
  except (ValueError,TypeError):raise SafetyError('native-material-current-schema-unreadable') from None
 required={'skuMaterials'} if method=='POST' else {'skuIds','materialTypes','scopeSet'}
 if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(schema.get('properties'),dict) or not required<=set(schema['properties']):raise SafetyError('native-material-capability-input-schema-needs-reviewed-adapter')
 return {'apiName':api,'method':method,'path':card['path'],'inputSchema':schema,'cardSha256':hash_value(card)}

def capabilities(client,shop):return {method:capability(client,shop,method) for method in ('GET','POST')}

def census(ops,profile,product_id):
 from .products import ProductService, _sku_source
 product_id=positive(product_id);service=ProductService(ops.state,ops.client);shop=ops.shop(profile)
 detail=service.detail(profile,product_id);_,rows=_sku_source(detail)
 if any(not isinstance(row,dict) or ('productId' in row and positive(row['productId'])!=product_id) for row in rows):raise SafetyError('native-material-product-sku-parent-mismatch')
 detail_ids=identifiers([row.get('skuId') for row in rows])
 paged=service.list_skus(profile,product_id,page_size=50,max_pages=1000)
 if not paged['complete'] or paged['reportedTotal'] is None or paged['reportedTotal']!=len(paged['items']) or identifiers([row.get('skuId') for row in paged['items']])!=detail_ids:raise SafetyError('native-material-full-sibling-census-incomplete')
 from .official_transport import matches_shop
 if not matches_shop(ops.client.identity(profile),shop):raise SafetyError('native-material-census-shop-changed')
 return detail_ids,paged['items']

def normalize(material,sku,types):
 if not isinstance(material,dict) or positive(material.get('skuId'))!=sku:raise SafetyError('native-material-sku-parent-mismatch')
 kind=integer(material.get('materialType'));order=integer(material.get('order'))
 if kind not in types or order<=0:raise SafetyError('native-material-type-or-order-invalid')
 content=copy.deepcopy(material)
 for key in ('status','auditDesc','reason','auditTime','updateTime'):content.pop(key,None)
 content.update(skuId=int(sku),materialType=kind,order=order)
 if kind==1002:
  if 'imageMaterial' in content or not isinstance(content.get('textMaterial'),dict):raise SafetyError('native-text-material-structure-required')
  values=content['textMaterial'].get('contents')
  if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise SafetyError('native-text-material-contents-required')
 else:
  image=content.get('imageMaterial')
  if 'textMaterial' in content or not isinstance(image,dict) or integer(image.get('imgType'))!=1:raise SafetyError('native-image-material-structure-required')
  images=image.get('skuImages')
  if not isinstance(images,list) or len(images)>100:raise SafetyError('native-image-material-array-required')
  indices=[]
  for row in images:
   if not isinstance(row,dict) or integer(row.get('index'))<=0:raise SafetyError('native-material-image-index-required')
   row['index']=integer(row['index']);row['imgUrl']=jfs(row.get('imgUrl'));indices.append(row['index'])
  if len(set(indices))!=len(indices):raise SafetyError('native-material-image-index-duplicate')
  image['skuImages']=sorted(images,key=lambda row:row['index']);image['imgType']=1;image.pop('replaceType',None)
 status=material.get('status');status=integer(status) if status is not None else None
 return f'{kind}:{order}',content,{'status':status,'reason':redact(material.get('auditDesc') or material.get('reason') or '')}

def read_materials(client,shop,sku_ids,query_schema=None):
 if query_schema is None:query_schema=capability(client,shop,'GET')['inputSchema']
 sku_ids=identifiers(sku_ids);contents={sku:{} for sku in sku_ids};audit={sku:{} for sku in sku_ids};hashes=[]
 for start in range(0,len(sku_ids),BATCH):
  group=sku_ids[start:start+BATCH]
  for types,scope in GROUPS:
   params={'skuIds':[int(s) for s in group],'materialTypes':list(types),'scopeSet':[scope]};validate_schema(params,query_schema)
   response=read(client,shop,READ,params);rows=business_payload(response)
   if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise SafetyError('native-material-response-array-required')
   returned=[positive(row.get('skuId')) for row in rows]
   if len(returned)!=len(group) or len(set(returned))!=len(returned) or set(returned)!=set(group):raise SafetyError('native-material-complete-exact-sku-read-required')
   for row in rows:
    sku=positive(row['skuId']);materials=row.get('materials')
    if not isinstance(materials,list):raise SafetyError('native-material-explicit-array-required')
    for material in materials:
     key,content,evidence=normalize(material,sku,types)
     if key in contents[sku]:raise SafetyError('native-material-duplicate-slot')
     contents[sku][key]=content;audit[sku][key]=evidence
   hashes.append(hash_value(response))
 return {'contents':contents,'audit':audit,'sourceHashes':hashes}

def changes_checked(changes):
 if not isinstance(changes,list) or not changes or len(changes)>MAX_SKUS*len(SLOTS):raise SafetyError('explicit-bounded-material-changes-required')
 seen=set();result=[]
 for row in changes:
  if not isinstance(row,dict) or row.get('slot') not in SLOTS or row.get('review')!='passed':raise SafetyError('known-slot-and-host-content-review-required')
  kind,order=SLOTS[row['slot']];required={'skuId','slot','review','text' if kind==1002 else 'uploadTaskId'}
  if set(row)!=required:raise SafetyError('native-material-text-or-original-upload-only')
  sku=positive(row['skuId']);key=(sku,row['slot'])
  if key in seen:raise SafetyError('native-material-change-duplicate')
  seen.add(key);item={**row,'skuId':sku}
  if kind==1002:
   text=row['text']
   if not isinstance(text,str) or not 2<=len(text)<=8 or text!=text.strip() or any(ord(c)<32 for c in text) or redact(text)!=text:raise SafetyError('reviewed-short-material-text-required')
  elif not isinstance(row['uploadTaskId'],str) or not re.fullmatch('[a-f0-9]{24}',row['uploadTaskId']):raise SafetyError('known-original-upload-task-required')
  result.append(item)
 return sorted(result,key=lambda row:(int(row['skuId']),SLOTS[row['slot']]))

def upload_source(ops,shop,task_id):
 task=ops.task(task_id)
 if task['scope']['shop']!=shop or task['status'] not in ('submitted','verified') or 'materialUpload' not in task['scope'] or task.get('resultReceiptSha256')!=hash_value(task.get('result')):raise SafetyError('known-same-shop-original-material-upload-required')
 upload=describe_upload(task['scope'])
 if upload is None:raise SafetyError('native-original-image-upload-required')
 descriptor,_=upload;image=task['scope']['materialUpload']['image'];check_image_evidence(descriptor,image)
 from .material_contract import original_upload_receipt
 original=original_upload_receipt(ops,task);first=validate_image_receipt(descriptor,image,original)
 validate_image_receipt(descriptor,image,task['result'],original=original)
 previous=task.get('resultReadback')
 if previous is not None:
  from .result_verification import resolve_result_verification
  resolved=resolve_result_verification(task['scope']['resultVerification'],original)
  if previous.get('sourceResultSha256')!=hash_value(original) or hash_value({'query':previous.get('query'),'expected':previous.get('expected')})!=hash_value(resolved):raise SafetyError('native-material-original-upload-readback-conflict')
  validate_image_receipt(descriptor,image,previous.get('result'),original=original)
 current=read(ops.client,shop,IMAGE_DETAIL,{'zoneId':descriptor['zoneId'],'imageId':first['imgId'],'getReferenceFlag':True},IMAGE_SKILL)
 validate_image_receipt(descriptor,image,current,original=task['result'])
 return {'url':jfs(first['imgUrl']),'imageId':first['imgId'],'originalSha256':descriptor['sha256'],'receiptSha256':task['resultReceiptSha256']}

def body_from_proof(ops,shop,proof):
 if not isinstance(proof,dict) or set(proof)!={'version','productId','siblingSkuIds','skuIds','baseline','changes','sources','capabilities','intentHash'} or proof['version']!=1 or isinstance(proof['version'],bool):raise SafetyError('complete-native-material-source-proof-required')
 if not isinstance(proof['intentHash'],str) or not re.fullmatch('[a-f0-9]{64}',proof['intentHash']):raise SafetyError('native-material-parent-intent-required')
 product=positive(proof['productId']);siblings=identifiers(proof['siblingSkuIds']);skus=identifiers(proof['skuIds'],BATCH);changes=changes_checked(proof['changes'])
 if not set(skus)<=set(siblings) or set(proof['baseline'])!=set(skus) or set(row['skuId'] for row in changes)!=set(skus):raise SafetyError('native-material-proof-sku-scope-mismatch')
 sources={tid:upload_source(ops,shop,tid) for tid in sorted({r['uploadTaskId'] for r in changes if 'uploadTaskId' in r})}
 if sources!=proof['sources']:raise SafetyError('native-material-original-source-changed')
 expected=copy.deepcopy(proof['baseline']);rows={sku:[] for sku in skus}
 for sku,slots in proof['baseline'].items():
  if not isinstance(slots,dict):raise SafetyError('native-material-baseline-slot-map-required')
  for key,content in slots.items():
   nkey,normalized,_=normalize(content,sku,{31,32,33,36,1002})
   if nkey!=key or hash_value(normalized)!=hash_value(content):raise SafetyError('native-material-baseline-not-canonical')
 for row in changes:
  sku=row['skuId'];kind,order=SLOTS[row['slot']];key=f'{kind}:{order}'
  if key in expected[sku]:raise SafetyError('existing-material-slot-not-automatically-overwritten')
  material={'skuId':int(sku),'materialType':kind,'order':order}
  if kind==1002:material['textMaterial']={'contents':[row['text']]}
  else:material['imageMaterial']={'imgType':1,'replaceType':1,'skuImages':[{'index':1,'imgUrl':sources[row['uploadTaskId']]['url']}]}
  rows[sku].append(material);_,content,_=normalize(material,sku,{kind});expected[sku][key]=content
 # Do not introduce duplicate selling points into this SKU's supported scope.
 for slots in expected.values():
  points=[m['textMaterial']['contents'][0] for m in slots.values() if m['materialType']==1002 and len(m['textMaterial']['contents'])==1]
  if len(points)!=len(set(points)):raise SafetyError('native-material-selling-points-must-be-distinct')
 body={'skuMaterials':[{'productId':int(product),'skuId':int(sku),'materials':rows[sku]} for sku in skus]}
 current=capabilities(ops.client,shop)
 if hash_value(current)!=hash_value(proof['capabilities']):raise SafetyError('native-material-capability-changed-requires-new-approval')
 validate_schema(body,current['POST']['inputSchema'])
 return body,expected

def contract(ops,scope,*,live=False,dispatch=False):
 from .shop_material_execution_contract import contract as shop_contract
 shop_contract(ops,scope,live=live,dispatch=dispatch)
 if 'videoMaterialInput' in scope:
  from .video_binding_contract import contract as video_contract
  return video_contract(ops,scope,live=live)
 op=scope['operation'];normalized='/'+('/'.join(p for p in op['url'].split('/') if p and p!='.'));native=bool(re.fullmatch(re.escape(READ)+r'(?:/.*)?',normalized))
 proof=scope.get('skuMaterialInput')
 if not native or op['method']=='GET':
  if proof is not None:raise SafetyError('native-material-proof-only-for-binding')
  return None
 if op['url']!=WRITE or op['method']!='POST' or op['skillId']!=SKILL or op['params']!={} or any(k in scope for k in ('verification','precondition','onlineVerification','resultVerification','nativeListingInput')):raise SafetyError('canonical-native-material-binding-required-no-delete')
 if proof is None:raise SafetyError('native-material-source-proof-required')
 body,expected=body_from_proof(ops,scope['shop'],proof)
 if hash_value(body)!=hash_value(op.get('body')):raise SafetyError('native-material-approved-body-mismatch')
 if live:
  siblings,_=census(ops,scope['shop']['profile'],proof['productId'])
  if siblings!=proof['siblingSkuIds']:raise SafetyError('native-material-sibling-census-changed')
  snapshot=read_materials(ops.client,scope['shop'],proof['skuIds'],proof['capabilities']['GET']['inputSchema'])
  if hash_value(snapshot['contents'])!=hash_value(proof['baseline']):raise SafetyError('native-material-original-slots-changed')
 return expected
