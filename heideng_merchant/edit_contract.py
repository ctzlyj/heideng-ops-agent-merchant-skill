"""Provenance-bound, full existing-product DTOs and image-only edit gates."""
import copy,re,json
from .safety import SafetyError,redact
from .products import identifier,_sku_source,_product_identity,_category
from .operations import digest,_same_identity
from .publication_contract import DetailHTML
from .product_schema import inventory,_check_color_consistency,_set_existing,_validate_logical_properties

KIND='schema-edit'
RULE_FIELDS=set('componentTitle label devTips inputType hidden readOnly required extra optionsValueList childrenComponents validateRule validate productDetailField productDetailFieldType josWareCommitField josWareCommitFieldType saveProductParamField saveProductParamFieldType defaultValue condition conditions type enum min max minLength maxLength pattern tips'.split())

def pointer(value,path):
 if not isinstance(path,str) or not path.startswith('/') or len(path)>8192 or len(path.split('/'))>129:raise SafetyError('exact-bounded-source-pointer-required')
 try:
  for part in path.split('/')[1:]:
   if re.search(r'~(?![01])',part):raise KeyError('invalid escape')
   key=part.replace('~1','/').replace('~0','~')
   if isinstance(value,list):
    if not re.fullmatch(r'0|[1-9][0-9]*',key):raise KeyError('invalid index')
    value=value[int(key)]
   else:value=value[key]
 except (KeyError,IndexError,TypeError,ValueError):raise SafetyError('original-source-pointer-missing') from None
 return value

DTO_CONTAINERS=set('SKUS SKU VenderCategoryValue WareEditor WareSkuImg LongImg SkuMainImage SkuRectangleImage SkuGgtImage'.split())

def container_codes(schema):
 result=set(DTO_CONTAINERS)
 def visit(row):
  if not isinstance(row,dict):return
  code=row.get('componentCode')
  if not isinstance(code,str) or not code:return
  definitions=row.get('childrenComponents')
  if isinstance(definitions,list) and definitions:result.add(code)
  for child in definitions if isinstance(definitions,list) else []:visit(child)
  if code in result and isinstance(row.get('value'),list):
   for child in row['value']:visit(child)
 for row in schema:visit(row)
 return result

def project(schema,containers=None):
 if not isinstance(schema,list) or not schema:raise SafetyError('complete-component-array-required')
 containers=container_codes(schema) if containers is None else set(containers)
 def component(row):
  if not isinstance(row,dict) or not isinstance(row.get('componentCode'),str):raise SafetyError('complete-component-array-required')
  if set(row)-{'componentCode','value','properties'}-RULE_FIELDS:raise SafetyError('unrecognized-outside-dto-field-cannot-be-silently-dropped')
  result={'componentCode':row['componentCode']}
  if 'value' in row:
   v=row['value'];result['value']=[component(x) for x in v] if row['componentCode'] in containers and isinstance(v,list) and v and all(isinstance(x,dict) and 'componentCode' in x for x in v) else copy.deepcopy(v)
  if 'properties' in row:
   if not isinstance(row['properties'],list) or any(not isinstance(p,dict) or set(p)<{'key','value'} or 'key' not in p or 'value' not in p for p in row['properties']):raise SafetyError('filled-component-property-pairs-required')
   if any(set(p)-{'key','value'}-RULE_FIELDS for p in row['properties']):raise SafetyError('unrecognized-property-field-cannot-be-silently-dropped')
   keys=[p['key'] for p in row['properties']]
   if any(not isinstance(k,str) or not k for k in keys) or len(set(keys))!=len(keys):raise SafetyError('unique-business-property-keys-required')
   result['properties']=[{'key':p['key'],'value':copy.deepcopy(p['value'])} for p in row['properties']]
  return result
 result=[component(r) for r in schema];_validate_logical_properties(result)
 if redact(result)!=result:raise SafetyError('private-edit-baseline-refused')
 digest(result);return result

def components(rows):
 from .publication_contract import _components
 return _components(rows)

def properties(row):
 from .publication_contract import _properties
 return _properties(row)

def layout(schema,containers=None):
 containers=DTO_CONTAINERS if containers is None else set(containers)
 # Unknown business blobs are one leaf, copied/proven in their entirety.
 def comp(r):
  v=r.get('value');child=[comp(x) for x in v] if r['componentCode'] in containers and isinstance(v,list) and v and all(isinstance(x,dict) and 'componentCode' in x for x in v) else ('leaf' if 'value' in r else None)
  return [r['componentCode'],child,[p['key'] for p in r.get('properties',[])]]
 return [comp(r) for r in schema]

def leaves(schema,containers=None):
 containers=DTO_CONTAINERS if containers is None else set(containers)
 result={}
 def comp(r,path,sku=None):
  code=r['componentCode']
  if code=='SKU':sku=identifier(components(r.get('value',[])).get('SkuId',{}).get('value'))
  if 'value' in r:
   v=r['value']
   if code in containers and isinstance(v,list) and v and all(isinstance(x,dict) and 'componentCode' in x for x in v):
    for i,x in enumerate(v):comp(x,path+'/value/'+str(i),sku)
   else:result[path+'/value']={'value':v,'component':code,'property':None,'skuId':sku}
  for i,p in enumerate(r.get('properties',[])):result[path+'/properties/'+str(i)+'/value']={'value':p['value'],'component':code,'property':p['key'],'skuId':sku}
 for i,r in enumerate(schema):comp(r,'/'+str(i))
 return result

def source_rows(detail):
 _,rows=_sku_source(detail);result={}
 for row in rows:
  if not isinstance(row,dict):raise SafetyError('complete-native-sku-rows-required')
  key=identifier(row.get('skuId'))
  if key in result:raise SafetyError('duplicate-original-sku-id')
  result[key]=row
 return result

def mapping(record):
 value=record.get('mappingId')
 if value in (None,''):value=record.get('attrValues')
 if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value):raise SafetyError('actual-original-sale-mapping-or-attr-values-required')
 return str(value)

def converted(value,mode):
 if mode=='identity':return value
 if mode=='string':
  if isinstance(value,bool) or not isinstance(value,(int,str)):raise SafetyError('lossless-original-string-or-id-required')
  return str(value)
 if mode=='html':return DetailHTML().vetted(value)
 if mode=='jfs':
  if not isinstance(value,str):raise SafetyError('native-original-image-url-required')
  value=value.removeprefix('https://img14.360buyimg.com/imgzone/')
  if not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',value) or '..' in value:raise SafetyError('native-original-image-url-required')
  return value
 if mode=='mapping' and isinstance(value,dict):return mapping(value)
 raise SafetyError('unreviewed-source-conversion')

def bound_value(detail,rows,binding):
 source=detail if binding['skuId'] is None else rows[identifier(binding['skuId'])]
 return converted(pointer(source,binding['sourcePointer']),binding['conversion'])

def declared_field(capture,target,binding,sales,context):
 code=target['component'];prop=target['property'];path=binding['schemaPointer']
 critical={'SkuId':'/skuId','SkuUUid':'/skuId','SkuVendorSku':'/outerId','SkuJdprice':'/priceInfo/jdPrice','SkuStockNum':'/stockNum'}
 if code in critical and prop is None:
  if binding['sourcePointer']!=critical[code]:raise SafetyError('native-critical-sku-source-field-required')
  allowed={'identity','string'} if code in ('SkuId','SkuUUid') else {'identity'}
  if binding['conversion'] not in allowed:raise SafetyError('critical-sku-fields-only-lossless-native-conversion')
  return
 if prop=='mappingId' and code.startswith('sale-prop-'):
  if binding['conversion'] not in ('identity','string','mapping'):raise SafetyError('only-native-mapping-conversion-allowed')
  source=context['sales'].get((target['skuId'],code))
  if source is None:raise SafetyError('native-sale-source-required')
  rows=context['rows'];record=pointer(rows[target['skuId']],source['sourcePointer']);field='attrValues' if record.get('mappingId') in (None,'') else 'mappingId'
  expected=source['sourcePointer'] if binding['conversion']=='mapping' else source['sourcePointer']+'/'+field
  if binding['sourcePointer']!=expected:raise SafetyError('actual-native-sale-mapping-field-required')
  return
 owner=pointer(capture['scope']['schema'],path.rsplit('/',1)[0]);hint=owner.get('productDetailField') if isinstance(owner,dict) else None
 if not isinstance(hint,str) or not re.fullmatch('[A-Za-z0-9_.]+',hint):raise SafetyError('original-component-field-declaration-required-not-unrelated-value')
 parts=hint.split('.')
 if target['skuId'] is not None:
  if parts[0]=='skuList':parts=parts[1:]
  elif parts[:2]==['productInfo','skuList']:parts=parts[2:]
 else:
  if parts[0]=='skuList':raise SafetyError('sku-field-must-use-native-sku-selector')
 if binding['sourcePointer']!='/'+('/'.join(parts)):raise SafetyError('source-binding-does-not-match-original-component-field-declaration')
 if binding['conversion']=='html' and path not in context['detailSlots'] or binding['conversion']=='jfs' and path not in context['imageSlots'] or binding['conversion']=='mapping':raise SafetyError('source-conversion-not-for-this-component-field')
 if binding['conversion']=='string':
  value=pointer(capture['scope']['productDetail'] if target['skuId'] is None else context['rows'][target['skuId']],binding['sourcePointer'])
  if not isinstance(value,str) and owner.get('josWareCommitFieldType') not in ('String','string'):raise SafetyError('unknown-numeric-business-type-must-not-be-coerced')

def validate_baseline(capture,schema,bindings,sale_sources):
 scope=capture['scope'];detail=scope.get('productDetail')
 if not isinstance(detail,dict) or digest(detail)!=scope['productDetailHash']:raise SafetyError('full-original-capture-detail-required')
 _validate_logical_properties(detail)
 if redact(detail)!=detail:raise SafetyError('private-capture-source-refused')
 codes=container_codes(scope['schema']);submitted=project(schema,codes);original=project(scope['schema'],codes)
 if layout(submitted,codes)!=layout(original,codes):raise SafetyError('entire-original-component-and-property-layout-required')
 submitted=canonical_edit(submitted);top=components(submitted);rows=top.get('SKUS',{}).get('value');native=source_rows(detail)
 if not isinstance(rows,list) or len(rows)!=len(native) or set(native)!=set(scope['skuIds']):raise SafetyError('complete-original-sku-range-required')
 original_rows=components(original).get('SKUS',{}).get('value',[]);ids=[]
 for i,row in enumerate(rows):
  fields=components(row.get('value',[]));sid=identifier(fields.get('SkuId',{}).get('value'));uid=identifier(fields.get('SkuUUid',{}).get('value'))
  if sid!=uid or sid not in native or set([r['componentCode'] for r in row['value'][:2]])!={'SkuId','SkuUUid'}:raise SafetyError('real-sku-id-and-uuid-in-first-two-fields-required')
  old=components(original_rows[i].get('value',[])).get('SkuId',{}).get('value')
  if old is not None and identifier(old)!=sid:raise SafetyError('original-schema-sku-order-must-be-retained')
  if native[sid].get('productId') is not None and identifier(native[sid]['productId'])!=scope['productId']:raise SafetyError('original-sku-parent-mismatch')
  for code,key in (('SkuVendorSku','outerId'),('SkuJdprice','priceInfo'),('SkuStockNum','stockNum')):
   if code not in fields or 'value' not in fields[code] or key not in native[sid]:raise SafetyError('complete-original-code-price-stock-required')
  ids.append(sid)
 if len(set(ids))!=len(ids) or set(ids)!=set(native):raise SafetyError('complete-unique-real-sku-identity-required')
 if not isinstance(sale_sources,list) or any(not isinstance(s,dict) for s in sale_sources):raise SafetyError('original-sale-attribute-source-list-required')
 if any(set(s)!={'skuId','componentCode','sourcePointer'} or not isinstance(s.get('componentCode'),str) for s in sale_sources):raise SafetyError('exact-native-sale-source-required')
 context={'rows':native,'sales':{(identifier(s['skuId']),s['componentCode']):s for s in sale_sources},'detailSlots':detail_pointers(original),'imageSlots':{t['pointer'] for t in inventory(original)[0]}}
 expected=leaves(submitted,codes)
 if not isinstance(bindings,list) or len(bindings)!=len(expected):raise SafetyError('all-edit-baseline-values-need-original-source-bindings')
 seen={}
 critical={'SkuId':'/skuId','SkuUUid':'/skuId','SkuVendorSku':'/outerId','SkuJdprice':'/priceInfo/jdPrice','SkuStockNum':'/stockNum'}
 for binding in bindings:
  if not isinstance(binding,dict) or set(binding)!={'schemaPointer','sourcePointer','skuId','conversion'} or binding['schemaPointer'] not in expected or binding['schemaPointer'] in seen:raise SafetyError('exact-unique-baseline-source-bindings-required')
  target=expected[binding['schemaPointer']]
  if binding['skuId']!=target['skuId']:raise SafetyError('source-binding-must-use-this-real-sku-not-row-position')
  if target['property'] is None and target['component'] in critical and binding['sourcePointer']!=critical[target['component']]:raise SafetyError('native-critical-sku-source-field-required')
  declared_field(capture,target,binding,sale_sources,context)
  try:actual=bound_value(detail,native,binding)
  except (KeyError,TypeError):raise SafetyError('source-sku-or-field-not-found') from None
  if digest(actual)!=digest(target['value']):raise SafetyError('baseline-value-not-proven-by-original-source')
  seen[binding['schemaPointer']]=binding
 if not isinstance(sale_sources,list):raise SafetyError('original-sale-attribute-source-list-required')
 sales={}
 for source in sale_sources:
  if not isinstance(source,dict) or set(source)!={'skuId','componentCode','sourcePointer'}:raise SafetyError('exact-native-sale-attribute-source-required')
  sid=identifier(source['skuId']);code=source['componentCode'];key=(sid,code)
  if sid not in native or key in sales or not isinstance(code,str) or not re.fullmatch('sale-prop-[0-9]+',code):raise SafetyError('unique-original-sale-attribute-source-required')
  record=pointer(native[sid],source['sourcePointer'])
  if not isinstance(record,dict) or str(record.get('attrId'))!=code.removeprefix('sale-prop-'):raise SafetyError('native-sale-attribute-id-mismatch')
  sales[key]=(record,source)
 consumed=set()
 raw_top=next(r for r in scope['schema'] if r.get('componentCode')=='SKUS')
 raw_rows={identifier(next(f for f in r['value'] if f.get('componentCode')=='SkuId')['value']):r for r in raw_top['value']}
 parent=next((r for r in raw_top.get('childrenComponents',[]) if r.get('componentCode')=='VenderCategoryValue'),{})
 rules={r['componentCode']:r for r in parent.get('childrenComponents',[]) if isinstance(r,dict) and 'componentCode' in r}
 for row in rows:
  fields=components(row['value']);sid=identifier(fields['SkuId']['value']);attrs=components(fields.get('VenderCategoryValue',{}).get('value',[]));color=None
  for code,attr in attrs.items():
   key=(sid,code)
   if key not in sales:raise SafetyError('every-original-sale-attribute-source-required')
   native_attr,src=sales[key];mid=mapping(native_attr);p=properties(attr)
   if str(p.get('mappingId'))!=mid:raise SafetyError('edit-sale-mapping-must-retain-native-id-or-fallback')
   consumed.add(key)
   # Only actual captured metadata, with conflicts rejected.
   raw_attr=next((r for r in next((f for f in raw_rows[sid]['value'] if f.get('componentCode')=='VenderCategoryValue'),{}).get('value',[]) if r.get('componentCode')==code),{})
   flags=[r.get('extra',{}).get('isColor') for r in (raw_attr,rules.get(code,{})) if 'isColor' in r.get('extra',{})]
   if not flags or any(not isinstance(f,bool) for f in flags) or len(set(flags))!=1:raise SafetyError('actual-unambiguous-sale-color-classification-required')
   if flags[0]:
    if color is not None:raise SafetyError('ambiguous-color-dimension')
    color=mid
  for image_code in ('SkuMainImage','SkuRectangleImage'):
   for image in fields.get(image_code,{}).get('value',[]):
    p=properties(image)
    if color is not None and (p.get('colorId')!=color or p.get('imgRefId')!=color):raise SafetyError('sku-image-references-must-use-original-color-mapping')
 if consumed!=set(sales):raise SafetyError('unreferenced-sale-attribute-source-refused')
 check_sales(detail,sale_sources,submitted)
 return submitted,ids,expected

def detail_pointers(schema):
 result=set()
 for i,component in enumerate(schema):
  if component.get('componentCode')!='WareEditor':continue
  for j,row in enumerate(component.get('value',[])):
   if not isinstance(row,dict) or row.get('componentCode')!='detail':continue
   for k,prop in enumerate(row.get('properties',[])):
    if prop.get('key')=='desc':result.add('/'+str(i)+'/value/'+str(j)+'/properties/'+str(k)+'/value')
 return result

def canonical_edit(schema):
 result=copy.deepcopy(schema)
 for p in detail_pointers(result):
  value=pointer(result,p)
  if value is not None:_set_existing(result,p,DetailHTML().vetted(value))
 return result

def edit_image_urls(schema):
 urls=[]
 for target in inventory(schema)[0]:
  url=target['oldValue']
  if not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',url) or '..' in url:raise SafetyError('native-original-edit-image-url-required')
  urls.append(url)
 for p in detail_pointers(schema):
  parser=DetailHTML();html=pointer(schema,p)
  if html is None:continue
  if parser.vetted(html)!=html:raise SafetyError('canonical-safe-edit-detail-required')
  urls.extend(parser.urls)
 return urls

def check_sales(detail,sources,schema):
 rows=source_rows(detail);wanted={};groups={}
 for row in components(schema)['SKUS']['value']:
  fields=components(row['value']);sid=identifier(fields['SkuId']['value'])
  for code,attr in components(fields.get('VenderCategoryValue',{}).get('value',[])).items():wanted[(sid,code)]=str(properties(attr).get('mappingId'))
 observed=set()
 for source in sources:
  sid=identifier(source['skuId']);code=source['componentCode'];record=pointer(rows[sid],source['sourcePointer']);key=(sid,code)
  if key not in wanted or key in observed or not isinstance(record,dict) or str(record.get('attrId'))!=code.removeprefix('sale-prop-') or mapping(record)!=wanted[key]:raise SafetyError('current-native-sale-identity-or-mapping-mismatch')
  observed.add(key);parent=source['sourcePointer'].rsplit('/',1)[0];groups.setdefault((sid,parent),set()).add(str(record['attrId']))
 if observed!=set(wanted):raise SafetyError('complete-current-sale-source-range-required')
 for (sid,parent),expected in groups.items():
  container=pointer(rows[sid],parent)
  if not isinstance(container,list) or any(not isinstance(r,dict) or 'attrId' not in r for r in container):raise SafetyError('complete-native-sale-record-container-required')
  ids=[str(r['attrId']) for r in container]
  if len(set(ids))!=len(ids) or set(ids)!=expected:raise SafetyError('native-sale-record-census-missing-or-duplicated')

def assets(ops,client,shop,ids):
 from .material_contract import describe_upload,check_image_evidence,validate_image_receipt,IMAGE_DETAIL,SKILL
 from .verification import business_payload
 result={}
 for ident in sorted(set(ids)):
  task=ops.task(ident)
  if task['scope']['shop']!=shop or task['status'] not in ('submitted','verified') or task.get('resultReceiptSha256')!=digest(task.get('result')):raise SafetyError('known-original-same-profile-image-receipt-required')
  upload=describe_upload(task['scope'])
  if upload is None:raise SafetyError('native-image-upload-required')
  descriptor,_=upload;image=task['scope']['materialUpload']['image'];check_image_evidence(descriptor,image);original=business_payload(task['result'])
  reply=client.invoke(shop['profile'],IMAGE_DETAIL,method='GET',params={'zoneId':descriptor['zoneId'],'imageId':original['imgId']},skill_id=SKILL)
  result[ident]=validate_image_receipt(descriptor,image,reply,original=task['result'])['imgUrl']
 return result

def changed_schema(base,changes,uploads,containers=None):
 schema=copy.deepcopy(base);target_list,_=inventory(base);targets={t['pointer']:t for t in target_list};desc=detail_pointers(base);seen=set();replace={}
 if not isinstance(changes,list) or not changes or len(changes)>10000:raise SafetyError('explicit-bounded-edit-changes-required')
 allowed_old=set(edit_image_urls(base))
 for change in changes:
  if not isinstance(change,dict) or change.get('pointer') in seen:raise SafetyError('distinct-exact-edit-pointers-required')
  p=change.get('pointer');seen.add(p)
  if set(change)=={'pointer','assetTaskId'} and p in targets:
   if change['assetTaskId'] not in uploads:raise SafetyError('original-upload-required')
   replace[p]=uploads[change['assetTaskId']];_set_existing(schema,p,replace[p])
  elif set(change)=={'pointer','html','assetTaskIds'} and p in desc:
   html=DetailHTML().vetted(change['html'])
   if html!=change['html'] or not isinstance(change['assetTaskIds'],list) or any(x not in uploads for x in change['assetTaskIds']):raise SafetyError('canonical-explicit-detail-html-and-assets-required')
   parser=DetailHTML();parser.vetted(html)
   if set(parser.urls)-allowed_old-{uploads[x] for x in change['assetTaskIds']}:raise SafetyError('detail-images-must-be-original-or-bound-owned-uploads')
   _set_existing(schema,p,html)
  else:raise SafetyError('only-original-image-slots-or-explicit-detail-html-editable')
 linked=[]
 sku_rows=components(base).get('SKUS',{}).get('value',[])
 for target in target_list:
  if target['dimension']=='sku':
   fields=components(sku_rows[target['skuRowIndex']]['value']);attr_ids={str(properties(a).get('mappingId')) for a in fields.get('VenderCategoryValue',{}).get('value',[])}
   if str(target['references'].get('colorId')) not in attr_ids:continue
  linked.append(target)
 _check_color_consistency(linked,replace)
 if digest(schema)==digest(base):raise SafetyError('actual-image-or-detail-change-required')
 return schema

def upload_ids(changes):
 ids=[]
 if not isinstance(changes,list):raise SafetyError('edit-changes-array-required')
 for c in changes:
  if not isinstance(c,dict):raise SafetyError('exact-edit-change-object-required')
  if 'assetTaskId' in c:ids.append(c['assetTaskId'])
  if 'assetTaskIds' in c:
   if not isinstance(c['assetTaskIds'],list):raise SafetyError('detail-assets-list-required')
   ids.extend(c['assetTaskIds'])
 if any(not isinstance(i,str) or not re.fullmatch('[a-f0-9]{24}',i) for i in ids):raise SafetyError('original-upload-task-ids-required')
 return sorted(set(ids))

def check_scope(ops,scope,client):
 from .schema_edit import EditService
 proof=scope['nativeListingInput']
 if not isinstance(proof,dict) or set(proof)!={'kind','baselineId','baselineFingerprint','editIntentId','changes','assetBindings','intentId'} or proof['kind']!=KIND:raise SafetyError('complete-original-edit-source-proof-required')
 service=EditService(ops.state,client);record=service._load(proof['baselineId']);b=record['scope'];cap=service.schemas._load('captures',b['captureId'])
 if record['fingerprint']!=proof['baselineFingerprint'] or cap['fingerprint']!=b['captureFingerprint'] or proof['editIntentId']!=record['baselineId'] or b['shop']!=scope['shop']:raise SafetyError('original-edit-baseline-and-intent-mismatch')
 schema,ids,_=validate_baseline(cap,b['schema'],b['bindings'],b['saleSources']);service._fresh(cap)
 refs=upload_ids(proof['changes'])
 if proof['assetBindings']!=[{'taskId':i} for i in refs]:raise SafetyError('exact-edit-image-asset-bindings-required')
 output=changed_schema(schema,proof['changes'],assets(ops,client,scope['shop'],refs),b['containerCodes']);expected=service._body(b,output)
 if scope['operation'].get('skillId')!='jdo-product-publish' or scope['operation'].get('params')!={} or scope['operation'].get('body')!=expected:raise SafetyError('same-canonical-full-existing-edit-body-required')
 service._fresh(cap)
 return output

def matches_source(detail,baseline,schema):
 try:
  _validate_logical_properties(detail)
  if redact(detail)!=detail:raise SafetyError('private-readback-refused')
  _product_identity(detail,baseline['productId']);category,_=_category(detail)
  if category!=baseline['lastCategoryId']:return False
  rows=source_rows(detail)
  if set(rows)!=set(baseline['skuIds']) or any(r.get('productId') is not None and identifier(r['productId'])!=baseline['productId'] for r in rows.values()):return False
  check_sales(detail,baseline['saleSources'],schema)
  expected=leaves(schema,baseline['containerCodes'])
  for binding in baseline['bindings']:
   if digest(bound_value(detail,rows,binding))!=digest(expected[binding['schemaPointer']]['value']):return False
  return True
 except (SafetyError,KeyError,TypeError,ValueError):return False
