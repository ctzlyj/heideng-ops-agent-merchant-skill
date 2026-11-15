"""Shared new-product gates: complete source, validated body, receipt and live inputs."""
import hashlib,json,re,time,uuid
from decimal import Decimal,InvalidOperation
from html.parser import HTMLParser
from html import escape
from pathlib import Path
from .safety import SafetyError,is_linked,redact,safe_join
from .verification import business_payload

VALIDATE='/rest/sp-product/v0/product-schemas/validations'
PUBLISH='/rest/sp-product/v0/product-applies'
VALIDATION_TTL=600
MAX_INPUT_BYTES=8*1024*1024

def json_value(text):
 from .product_schema import _unique_object,_lossless_float,_nonfinite,_validate_logical_properties
 if not isinstance(text,str) or len(text.encode('utf-8'))>MAX_INPUT_BYTES:raise SafetyError('publication-json-exceeds-local-budget')
 try:value=json.loads(text,object_pairs_hook=_unique_object,parse_float=_lossless_float,parse_constant=_nonfinite)
 except (ValueError,TypeError,RecursionError):raise SafetyError('invalid-lossless-publication-json') from None
 _validate_logical_properties(value)
 if redact(value)!=value:raise SafetyError('private-publication-input-refused')
 return value

def read_input_json(path):
 path=Path(path).absolute()
 if not path.is_file() or any(is_linked(p) for p in (path,*path.parents)):raise SafetyError('actual-unlinked-publication-input-required')
 with path.open('rb') as f:raw=f.read(MAX_INPUT_BYTES+1)
 if len(raw)>MAX_INPUT_BYTES:raise SafetyError('publication-input-exceeds-local-budget')
 try:return json_value(raw.decode('utf-8-sig')),hashlib.sha256(raw).hexdigest()
 except UnicodeError:raise SafetyError('publication-utf8-input-required') from None

def _components(rows):
 if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('componentCode'),str) or not r['componentCode'] or set(r)-{'componentCode','value','properties'} for r in rows):raise SafetyError('filled-business-components-required-not-template-controls')
 result={}
 for row in rows:
  code=row['componentCode']
  if code in result:raise SafetyError('duplicate-publication-component')
  result[code]=row
 return result

def _properties(row):
 rows=row.get('properties',[])
 if not isinstance(rows,list):raise SafetyError('native-property-pairs-required')
 result={}
 for prop in rows:
  if not isinstance(prop,dict) or set(prop)!={'key','value'} or not isinstance(prop['key'],str) or prop['key'] in result:raise SafetyError('exact-unique-property-pairs-required')
  result[prop['key']]=prop['value']
 return result

def decimal_value(value):
 if isinstance(value,bool) or not isinstance(value,(int,float,str)):raise SafetyError('exact-publication-numeric-value-required')
 try:result=Decimal(str(value))
 except InvalidOperation:raise SafetyError('finite-publication-number-required') from None
 if not result.is_finite():raise SafetyError('finite-publication-number-required')
 return result


def validation_body(op):
 from .products import identifier
 body=op.get('body')
 if op.get('skillId')!='jdo-product-publish' or op.get('params',{})!={} or not isinstance(body,dict) or set(body)!={'scene','schema','productApplyDTO'} or body['scene']!='pop':raise SafetyError('canonical-flat-pop-validation-body-required')
 dto=body['productApplyDTO']
 if not isinstance(dto,dict) or not {'categoryDTO'}<=set(dto) or set(dto)-{'categoryDTO','productId'} or not isinstance(dto['categoryDTO'],dict) or set(dto['categoryDTO'])!={'lastCategoryId'}:raise SafetyError('native-validation-category-dto-required')
 identifier(dto['categoryDTO']['lastCategoryId'])
 if 'productId' in dto:identifier(dto['productId'])
 _components(canonical_schema(json_value(body['schema']),require_canonical=True))


def new_body(operation):
 from .products import identifier
 body=operation.get('body')
 if operation.get('skillId')!='jdo-product-publish' or operation.get('params',{})!={} or not isinstance(body,dict) or set(body)!={'scene','schema','productApplyDTO'} or body['scene']!='pop':raise SafetyError('canonical-flat-pop-publication-body-required')
 dto=body['productApplyDTO']
 if not isinstance(dto,dict) or set(dto)!={'categoryDTO'} or not isinstance(dto['categoryDTO'],dict) or set(dto['categoryDTO'])!={'lastCategoryId'}:raise SafetyError('new-product-only-no-existing-product-or-apply-id')
 category=identifier(dto['categoryDTO']['lastCategoryId']);schema=canonical_schema(json_value(body['schema']),require_canonical=True);top=_components(schema)
 skus=top.get('SKUS',{}).get('value')
 if not isinstance(skus,list) or not skus:raise SafetyError('complete-new-sku-array-required')
 keys=[];codes=[]
 for row in skus:
  if not isinstance(row,dict) or row.get('componentCode')!='SKU' or set(row)!={'componentCode','value'}:raise SafetyError('native-sku-row-required')
  fields=_components(row['value'])
  if 'SkuId' in fields:raise SafetyError('existing-sku-id-forbidden-in-new-product-flow')
  ident=fields.get('SkuUUid',{}).get('value')
  try:uuid.UUID(ident)
  except (ValueError,TypeError,AttributeError):raise SafetyError('new-unique-sku-uuid-required') from None
  code=fields.get('SkuVendorSku',{}).get('value')
  if not isinstance(code,str) or not code:raise SafetyError('all-original-merchant-codes-required')
  if decimal_value(fields.get('SkuJdprice',{}).get('value'))<=0:raise SafetyError('positive-new-sku-price-required')
  stock=decimal_value(fields.get('SkuStockNum',{}).get('value'))
  if stock<0 or stock!=stock.to_integral_value():raise SafetyError('nonnegative-integer-sku-stock-required')
  keys.append(uuid.UUID(ident).hex);codes.append(code)
 if len(set(keys))!=len(keys) or len(set(codes))!=len(codes):raise SafetyError('new-sku-uuid-or-merchant-code-duplicate')
 return category,schema,top,skus

class DetailHTML(HTMLParser):
 # Reconstruct vetted markup; never approve the HTMLParser's raw input.
 def __init__(self):super().__init__(convert_charrefs=True);self.urls=[];self.parts=[];self.stack=[]
 def handle_starttag(self,tag,attrs):
  if tag not in ('div','p','span','br','img'):raise SafetyError('active-or-unreviewed-detail-html-refused')
  pairs=dict(attrs)
  if len(pairs)!=len(attrs) or any(k not in ({'src','alt','title','width','height'} if tag=='img' else {'class'}) or not isinstance(v,str) for k,v in attrs):raise SafetyError('unreviewed-detail-html-attributes-refused')
  if tag=='img':
   src=pairs.get('src');prefix='https://img14.360buyimg.com/imgzone/'
   if not isinstance(src,str) or not src.startswith(prefix) or not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',src[len(prefix):]) or '..' in src:raise SafetyError('original-imgzone-detail-image-required')
   self.urls.append(src[len(prefix):])
  self.parts.append('<'+tag+''.join(' '+k+'="'+escape(v,quote=True)+'"' for k,v in sorted(attrs))+'>')
  if tag not in ('br','img'):self.stack.append(tag)
 def handle_startendtag(self,tag,attrs):
  self.handle_starttag(tag,attrs)
  if tag not in ('br','img'):self.handle_endtag(tag)
 def handle_endtag(self,tag):
  if not self.stack or self.stack[-1]!=tag:raise SafetyError('mismatched-detail-html-refused')
  self.stack.pop();self.parts.append('</'+tag+'>')
 def handle_data(self,data):self.parts.append(escape(data,quote=False))
 def handle_comment(self,data):raise SafetyError('detail-html-comment-refused')
 def handle_decl(self,decl):raise SafetyError('detail-html-declaration-refused')
 def unknown_decl(self,data):raise SafetyError('detail-html-unknown-declaration-refused')
 def handle_pi(self,data):raise SafetyError('detail-html-processing-instruction-refused')
 def vetted(self,html):
  if not isinstance(html,str):raise SafetyError('detail-html-string-required')
  self.feed(html);self.close()
  if self.stack:raise SafetyError('unclosed-detail-html-refused')
  return ''.join(self.parts)

def canonical_schema(schema,*,require_canonical=False):
 import copy
 result=copy.deepcopy(schema)
 def walk(value):
  if isinstance(value,list):
   for item in value:walk(item)
  elif isinstance(value,dict):
   if value.get('key')=='desc':
    original=value.get('value');canonical=DetailHTML().vetted(original)
    if require_canonical and canonical!=original:raise SafetyError('canonical-safe-detail-html-required-before-approval')
    value['value']=canonical
   for item in value.values():walk(item)
 walk(result);return result

def image_urls(schema):
 urls=[]
 def walk(node):
  if isinstance(node,list):
   for value in node:walk(value)
  elif isinstance(node,dict):
   if node.get('key')=='imgUrl':
    if not isinstance(node.get('value'),str) or not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',node['value']) or '..' in node['value']:raise SafetyError('native-jfs-image-value-required')
    urls.append(node['value'])
   if node.get('key')=='desc':
    if not isinstance(node.get('value'),str):raise SafetyError('detail-html-string-required')
    parser=DetailHTML();canonical=parser.vetted(node['value'])
    if canonical!=node['value']:raise SafetyError('canonical-safe-detail-html-required-before-approval')
    urls.extend(parser.urls)
   for value in node.values():walk(value)
 walk(schema)
 if not urls:raise SafetyError('new-product-actual-images-required')
 return urls

def validation_verdict(response,*,expected_execution=None):
 # Failure dominates ambiguity. Inspect every envelope, never early-return on
 # an empty report or silently ignore an unfamiliar outer business field.
 from .product_schema import _validate_logical_properties
 _validate_logical_properties(response)
 pending=[response]
 while pending:
  node=pending.pop()
  if isinstance(node,dict):
   if any(value is False and re.search(r'success|valid|pass|compli|allow|publish|^ok$',str(key),re.I) for key,value in node.items()):return 'failed'
   if node.get('wareKeeperDetectResultList') or node.get('errorList'):return 'failed'
   pending.extend(node.values())
  elif isinstance(node,list):pending.extend(node)
 current=response;success=False;ambiguous=False;depth=0
 while isinstance(current,dict):
  depth+=1
  if depth>128:return 'unproven'
  allowed={'wareKeeperDetectResultList','success','ok','status','code','message','errorList','data'}
  if depth==1 and '_merchantExecution' in current:
   allowed.add('_merchantExecution')
   if expected_execution is None or current['_merchantExecution']!=expected_execution:ambiguous=True
  if set(current)-allowed:ambiguous=True
  for flag in ('success','ok'):
   if flag in current and not isinstance(current[flag],bool):ambiguous=True
  if current.get('success') is True:success=True
  if 'status' in current:
   if current['status'] in ('error','ERROR','failed','FAILED'):return 'failed'
   if current['status'] not in ('success','SUCCESS','ok','OK'):ambiguous=True
  if 'code' in current and current['code'] not in (None,0,'0',200,'200','SUCCESS'):ambiguous=True
  if 'wareKeeperDetectResultList' in current and not isinstance(current['wareKeeperDetectResultList'],list):ambiguous=True
  if 'errorList' in current and current['errorList'] not in (None,[]):ambiguous=True
  if 'message' in current and not isinstance(current['message'],(str,type(None))):ambiguous=True
  if 'data' not in current:break
  current=current['data']
  if not isinstance(current,dict):
   if current not in (None,[]):ambiguous=True
   break
 return 'passed' if success and not ambiguous else 'unproven'

def receipt(response):
 from .product_schema import _validate_logical_properties
 _validate_logical_properties(response)
 from .products import identifier
 data=business_payload(response)
 if not isinstance(data,dict):raise SafetyError('native-publication-receipt-object-required')
 result={k:identifier(data[k]) for k in ('applyId','productId') if k in data}
 if not result:raise SafetyError('original-publication-apply-or-product-id-required')
 return result

def checked_validation(ops,ident,body,shop):
 from .operations import digest
 task=ops.task(ident)
 if task['status']!='completed' or task['scope']['operation']['url']!=VALIDATE or task['scope']['operation']['body']!=body or task['scope']['shop']!=shop or task.get('resultReceiptSha256')!=digest(task.get('result')) or validation_verdict(task.get('result'),expected_execution=task['scope'].get('officialExecution'))!='passed' or not 0<=time.time()-task.get('finishedAt',0)<=VALIDATION_TTL:raise SafetyError('fresh-original-successful-same-body-validation-required')
 if not isinstance(task['scope'].get('nativeListingInput'),dict):raise SafetyError('validation-lacks-complete-listing-source-proof')
 return task

def check_scope(ops,scope,client):
 op=scope['operation'];url=op['url'].rstrip('/')
 if op['method']!='POST' or url not in (VALIDATE,PUBLISH):return None
 if op['url']!=url:raise SafetyError('canonical-publication-route-required')
 proof=scope.get('nativeListingInput')
 if url==VALIDATE and proof is None:
  validation_body(op)
  return 'validation'
 category,schema,top,rows=new_body(op)
 if url==PUBLISH:
  previous=checked_validation(ops,scope.get('publicationValidationTaskId'),op['body'],scope['shop'])
  if proof!=previous['scope']['nativeListingInput']:raise SafetyError('publication-source-proof-changed-after-validation')
 if proof is not None:verify_input(ops,scope,client,category,schema,top,rows,proof)
 if url==PUBLISH:checked_validation(ops,scope['publicationValidationTaskId'],op['body'],scope['shop'])
 return 'validation' if url==VALIDATE else 'publication'

def verify_input(ops,scope,client,category,schema,top,rows,proof):
 from .operations import digest,_same_identity
 from .products import identifier
 from .publish_support import PublishSupport
 from .material_contract import describe_upload,check_image_evidence,validate_image_receipt,IMAGE_DETAIL,SKILL
 if not isinstance(proof,dict) or set(proof)!={'manifestPath','manifestSha256','specMap','assetBindings','contextHash','intentId','publicationIntentId'}:raise SafetyError('complete-publication-source-proof-required')
 manifest,sha=read_input_json(proof['manifestPath'])
 if sha!=proof['manifestSha256'] or not isinstance(manifest,dict) or not isinstance(manifest.get('sourceProduct'),dict):raise SafetyError('publication-manifest-changed-or-source-input-missing')
 intent=proof['publicationIntentId']
 if not isinstance(intent,str) or not re.fullmatch('[a-f0-9]{32}',intent) or manifest.get('publication',{}).get('intentId')!=intent:raise SafetyError('persistent-original-publication-intent-required')
 original=manifest['sourceProduct']
 if original.get('skus')!=manifest.get('skus') or original.get('title')!=manifest.get('title') or str(original.get('categoryId'))!=str(manifest.get('categoryId')) or str(manifest.get('categoryId'))!=category:raise SafetyError('original-listing-product-and-all-skus-must-be-preserved')
 photos=manifest.get('images',[])
 if not isinstance(photos,list) or not photos or manifest.get('source',{}).get('fingerprint')!=digest({'product':original,'photoHashes':[p.get('sha256') for p in photos]}):raise SafetyError('original-product-and-photo-fingerprint-required')
 brand=identifier(top.get('WareBrand',{}).get('value'));ctx=PublishSupport(ops.state,client).context(scope['shop']['profile'],category,brand)
 if ctx['contextHash']!=proof['contextHash']:raise SafetyError('publication-template-or-authorization-changed')
 if str(original.get('brandId',brand))!=brand or top.get('WareTitle',{}).get('value')!=manifest['title']:raise SafetyError('original-title-and-brand-required')
 for source_key,component_code in (('transportId','WareTransport'),('promiseId','WarePromise'),('spuId','SpuId')):
  if source_key in original and str(top.get(component_code,{}).get('value'))!=str(original[source_key]):raise SafetyError('explicit-original-publishing-id-missing-or-changed')
 definitions={r.get('componentCode'):r for r in ctx['schema']}
 if set(top)-set(definitions)-({'SpuId'} if str(original.get('spuId'))==str(top.get('SpuId',{}).get('value')) else set()):raise SafetyError('publication-component-not-in-current-template')
 sku_defs={r.get('componentCode'):r for r in definitions.get('SKUS',{}).get('childrenComponents',[])}
 sale_defs={r.get('componentCode'):r for r in sku_defs.get('VenderCategoryValue',{}).get('childrenComponents',[])}
 specs=proof['specMap']
 if not isinstance(specs,dict) or set(specs)-set(sale_defs) or any(not isinstance(v,str) for v in specs.values()) or len(set(specs.values()))!=len(specs):raise SafetyError('actual-sale-attribute-to-source-spec-map-required')
 source=manifest['skus'];by_code={str(s['merchantCode']):s for s in source}
 if len(by_code)!=len(source) or len(rows)!=len(source):raise SafetyError('complete-original-sku-range-required')
 seen=set();mapping={};reverse={};color_urls={}
 for row in rows:
  fields=_components(row['value']);code=fields['SkuVendorSku']['value']
  if code not in by_code or code in seen or set(fields)-set(sku_defs):raise SafetyError('original-sku-and-template-components-required')
  seen.add(code);sku=by_code[code]
  if decimal_value(fields['SkuJdprice']['value'])!=decimal_value(sku['price']) or decimal_value(fields['SkuStockNum']['value'])!=decimal_value(sku['stock']):raise SafetyError('all-original-sku-prices-and-stocks-required')
  if not isinstance(sku.get('specs'),dict) or set(specs.values())!=set(sku['specs']):raise SafetyError('all-original-spec-dimensions-required')
  attrs=_components(fields.get('VenderCategoryValue',{}).get('value',[]))
  if set(attrs)!=set(specs):raise SafetyError('all-original-sale-attributes-required')
  color=None
  for attr,key in specs.items():
   props=_properties(attrs[attr]);alias=props.get('attrValueAlias');mid=props.get('mappingId');rule=sale_defs[attr].get('extra',{})
   if alias!=str(sku['specs'][key]) or str(props.get('index'))!=str(rule.get('dim')) or not isinstance(mid,str) or not mid:raise SafetyError('original-spec-alias-dimension-and-mapping-required')
   try:uuid.UUID(mid)
   except (ValueError,TypeError):raise SafetyError('new-sale-value-mapping-uuid-required') from None
   group=(attr,alias);other=(attr,mid)
   if group in mapping and mapping[group]!=mid or other in reverse and reverse[other]!=alias:raise SafetyError('new-sale-mapping-must-be-consistent-and-distinct')
   mapping[group]=mid;reverse[other]=alias
   if rule.get('isColor') is True:color=mid
  if color is not None:
   for image_code in ('SkuMainImage','SkuRectangleImage'):
    for index,img in enumerate(fields.get(image_code,{}).get('value',[])):
     props=_properties(img)
     if props.get('colorId')!=color or props.get('imgRefId')!=color:raise SafetyError('pop-image-reference-must-use-actual-color-mapping')
     group=(image_code,color,str(props.get('orderSort',index)))
     if group in color_urls and color_urls[group]!=props.get('imgUrl'):raise SafetyError('same-color-image-content-must-be-consistent')
     color_urls[group]=props.get('imgUrl')
 if seen!=set(by_code):raise SafetyError('complete-original-sku-range-required')
 root=Path(proof['manifestPath']).absolute().parent;photo_map={p['localPath']:p for p in photos};allowed=set()
 bindings=proof['assetBindings']
 if not isinstance(bindings,list) or not bindings:raise SafetyError('original-photo-upload-bindings-required')
 used=set()
 for binding in bindings:
  if not isinstance(binding,dict) or set(binding)!={'localPath','taskId'} or binding['localPath'] not in photo_map or binding['localPath'] in used:raise SafetyError('unique-original-photo-bindings-required')
  used.add(binding['localPath']);photo=photo_map[binding['localPath']];path=safe_join(root,binding['localPath'])
  if photo.get('visualReview')!='passed':raise SafetyError('host-visual-review-of-original-photos-required')
  from .safety import file_sha
  if not path.is_file() or file_sha(path)!=photo.get('sha256'):raise SafetyError('publication-original-photo-changed')
  task=ops.task(binding['taskId'])
  if task['scope']['shop']!=scope['shop'] or task['status'] not in ('submitted','verified') or 'materialUpload' not in task['scope']:raise SafetyError('known-same-profile-original-photo-upload-required')
  original_result=task.get('result')
  if task.get('resultReceiptSha256')!=digest(original_result):raise SafetyError('original-photo-receipt-missing-or-modified')
  upload=describe_upload(task['scope'])
  if upload is None:raise SafetyError('native-original-image-upload-required')
  descriptor,_=upload;info=task['scope']['materialUpload']['image'];check_image_evidence(descriptor,info)
  original=business_payload(original_result)
  response=client.invoke(scope['shop']['profile'],IMAGE_DETAIL,method='GET',params={'zoneId':descriptor['zoneId'],'imageId':original['imgId']},skill_id=SKILL)
  live=validate_image_receipt(descriptor,info,response,original=original_result)
  if descriptor['sha256']!=photo['sha256']:raise SafetyError('original-photo-upload-source-mismatch')
  allowed.add(live['imgUrl'])
 if set(image_urls(schema))-allowed:raise SafetyError('all-schema-and-detail-images-must-be-original-owned-uploads')
 if not _same_identity(client.identity(scope['shop']['profile']),scope['shop']):raise SafetyError('publication-shop-changed-during-preflight')
