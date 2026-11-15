"""Receipt-bound type42 contracts; never generation or a generic write bypass."""
import copy,json,re
from .safety import SafetyError,redact
from .operations import digest
from .verification import business_payload,pagination_total
from .sku_material_contract import READ,WRITE,SKILL,BATCH,identifiers,integer,jfs,read,capabilities,validate_schema,census,read_materials
from .video_contract import native_id,id_value,zone
TAGS='/rest/sp-product/v0/sku-material-tags'
RELS='/rest/sp-product/v0/media-zones/{zoneId}/video-sku-rels'
APIS={TAGS:'GET.sp-product.v0.sku-material-tags',RELS:'GET.sp-product.v0.media-zones._zoneId.video-sku-rels'}

def capability(client,shop,path):
 api=APIS[path];data=business_payload(read(client,shop,'/rest/open-metadata/v0/apis/{apiname}',{'apiname':api}))
 if not isinstance(data,dict) or data.get('apiName')!=api or data.get('method')!='GET' or data.get('path') not in (path,path.removeprefix('/rest')):raise SafetyError('native-video-binding-card-route-mismatch')
 schema=data.get('inputSchema')
 if isinstance(schema,str):
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise SafetyError('duplicate-native-binding-schema-key')
    out[k]=v
   return out
  try:schema=json.loads(schema,object_pairs_hook=unique)
  except (TypeError,ValueError):raise SafetyError('native-video-binding-schema-unreadable') from None
 fields={'materialType','secondCategoryId'} if path==TAGS else {'zoneId','videoType','videoIds','page','pageSize','scopeSet'}
 if not isinstance(schema,dict) or schema.get('type')!='object' or not fields<=set(schema.get('properties',{})) or redact(schema)!=schema:raise SafetyError('native-video-binding-schema-needs-reviewed-adapter')
 return {'apiName':api,'method':'GET','path':data['path'],'inputSchema':schema,'cardSha256':digest(data)}

def cards(client,shop):return {**capabilities(client,shop),TAGS:capability(client,shop,TAGS),RELS:capability(client,shop,RELS)}

def source(ops,shop,session_id,*,media=False,write_ready=True):
 from .video_delivery import VideoDelivery,_load
 session=_load(ops.state,session_id)
 if not isinstance(session.get('approval'),dict) or session['approval'].get('confirmed') is not True or session['approval'].get('fingerprint')!=session['fingerprint']:raise SafetyError('original-native-video-upload-approval-required')
 if session['scope']['shop']!=shop or session['status'] not in ({'ready'} if write_ready else {'ready','saved','rejected'}) or set(session['receipts']) not in ({'allocate','transfer','save'},{'allocate','renew','transfer','save'}):raise SafetyError('known-ready-same-shop-original-video-session-required')
 service=VideoDelivery(ops.state,ops.client)
 if media:service._source(session)
 zone(ops.client,shop,session['scope']['zoneId']);metadata=service._query(session)
 if not metadata or write_ready and metadata['status'] not in (2,4) or 'indexImage' not in metadata:raise SafetyError('original-video-transcode-and-index-image-required')
 metadata={k:v for k,v in metadata.items() if k!='status'};metadata['indexImage']=jfs(metadata['indexImage'])
 return {'sessionId':session_id,'fingerprint':session['fingerprint'],'approvalSha256':session['approvalSha256'],'receipts':session['receipts'],'videoSha256':session['scope']['video']['sha256'],'listingFingerprint':session['scope']['video']['listingFingerprint'],'zoneId':session['scope']['zoneId'],'metadata':metadata}

def product(ops,shop,product_id):
 from .products import ProductService
 product_id=native_id(product_id);siblings,_=census(ops,shop['profile'],product_id);detail=ProductService(ops.state,ops.client).detail(shop['profile'],product_id);found=[]
 for path in ('categoryDetail','categoryDTO'):
  for owner in (detail,detail.get('productInfo',{})):
   value=owner.get(path,{}) if isinstance(owner,dict) else {}
   if isinstance(value,dict) and value.get('secondCategoryId') is not None:found.append(native_id(value['secondCategoryId']))
 if not found or len(set(found))!=1:raise SafetyError('actual-unambiguous-second-category-required-no-fallback')
 return {'productId':product_id,'skuIds':siblings,'secondCategoryId':found[0],'detailSha256':digest(detail)}

def tag(client,shop,product_info,metadata_card):
 props=metadata_card['inputSchema']['properties'];params={'materialType':42,'secondCategoryId':id_value(props['secondCategoryId'],product_info['secondCategoryId'])};validate_schema(params,metadata_card['inputSchema'])
 values=business_payload(read(client,shop,TAGS,params))
 if not isinstance(values,list) or len(values)>1000 or any(not isinstance(row,dict) for row in values):raise SafetyError('native-video-tag-list-required')
 ids=[];selected=[]
 for row in values:
  ids.append(native_id(row.get('tagId')))
  if 'venderId' in row and native_id(row['venderId'])!=shop['venderId']:raise SafetyError('foreign-video-tag-refused')
  if row.get('tagName')=='产品展示':
   order=integer(row.get('sort'))
   if order<0:raise SafetyError('actual-native-tag-order-required')
   selected.append({'tagId':int(ids[-1]),'tagOrder':order,'tagName':'产品展示'})
 if len(ids)!=len(set(ids)) or len(selected)!=1:raise SafetyError('one-actual-product-display-tag-required')
 return selected[0]

def context(ops,shop,product_id,session_id,*,media=False,write_ready=True):
 selected=source(ops,shop,session_id,media=media,write_ready=write_ready);target=product(ops,shop,product_id);current=cards(ops.client,shop);chosen=tag(ops.client,shop,target,current[TAGS])
 return {'shop':shop,'source':selected,'product':target,'tag':chosen,'cards':current}

def identity_scope(ctx):return {'videoSha256':ctx['source']['videoSha256'],'listingFingerprint':ctx['source']['listingFingerprint'],'productId':ctx['product']['productId'],'skuIds':ctx['product']['skuIds'],'productSnapshotSha256':ctx['product']['detailSha256']}

def normalize(material,sku):
 if not isinstance(material,dict) or native_id(material.get('skuId'))!=sku or integer(material.get('materialType'))!=42 or integer(material.get('order'))<=0 or any(k in material for k in ('imageMaterial','textMaterial')):raise SafetyError('native-type42-exact-sku-order-required')
 out=copy.deepcopy(material)
 for key in ('status','auditDesc','reason','auditTime','updateTime'):out.pop(key,None)
 value=out.get('videoMaterial')
 if not isinstance(value,dict) or integer(value.get('videoFrom'))!=1 or not isinstance(value.get('title'),str) or not value['title'].strip() or not isinstance(value.get('tagName'),str) or not value['tagName'].strip():raise SafetyError('complete-native-owned-video-material-required')
 value.update(videoFrom=1,videoId=int(native_id(value.get('videoId'))),jdVideoId=int(native_id(value.get('jdVideoId'))),indexImage=jfs(value.get('indexImage')),duration=integer(value.get('duration')),tagId=int(native_id(value.get('tagId'))),tagOrder=integer(value.get('tagOrder')))
 if value['duration']<=0 or value['tagOrder']<0 or redact(out)!=out:raise SafetyError('native-video-material-values-unprovable')
 out.update(skuId=int(sku),materialType=42,order=integer(out['order']))
 status=material.get('status');status=integer(status) if status is not None else None
 return '42:'+str(out['order']),out,{'status':status,'reason':redact(material.get('auditDesc') or material.get('reason') or '')}

def snapshot(ops,shop,skus,metadata_card):
 skus=identifiers(skus);result=read_materials(ops.client,shop,skus,metadata_card['inputSchema'])
 for start in range(0,len(skus),BATCH):
  group=skus[start:start+BATCH];params={'skuIds':[int(s) for s in group],'materialTypes':[42],'scopeSet':[3]};validate_schema(params,metadata_card['inputSchema']);response=read(ops.client,shop,READ,params);rows=business_payload(response)
  if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise SafetyError('native-video-material-array-required')
  returned=[native_id(r.get('skuId')) for r in rows]
  if len(returned)!=len(group) or len(set(returned))!=len(returned) or set(returned)!=set(group):raise SafetyError('complete-exact-native-video-sku-read-required')
  for row in rows:
   sku=native_id(row['skuId'])
   if not isinstance(row.get('materials'),list):raise SafetyError('explicit-native-video-materials-required')
   for m in row['materials']:
    key,value,audit=normalize(m,sku)
    if key in result['contents'][sku]:raise SafetyError('duplicate-native-video-material-order')
    result['contents'][sku][key]=value;result['audit'][sku][key]=audit
  result['sourceHashes'].append(digest(response))
 return result

def target_material(ctx,sku):
 m=ctx['source']['metadata'];video={'videoFrom':1,'videoId':int(native_id(m['videoId'])),'jdVideoId':int(native_id(m['jdVideoId'])),'indexImage':m['indexImage'],'title':m['videoName'],'duration':integer(m['duration']),**ctx['tag']}
 return normalize({'skuId':int(sku),'materialType':42,'order':1,'videoMaterial':video},sku)[1]

def body_from_proof(ops,shop,proof,*,live=False):
 if not isinstance(proof,dict) or set(proof)!={'version','intentHash','context','skuIds','baseline','baselineAudit'} or type(proof['version']) is not int or proof['version']!=1 or not isinstance(proof['intentHash'],str) or not re.fullmatch('[a-f0-9]{64}',proof['intentHash']):raise SafetyError('complete-native-video-binding-proof-required')
 ctx=proof['context'];skus=identifiers(proof['skuIds'],BATCH)
 if not isinstance(ctx,dict) or set(ctx)!={'shop','source','product','tag','cards','review'} or ctx['shop']!=shop or set(proof['baseline'])!=set(skus) or set(proof['baselineAudit'])!=set(skus) or not set(skus)<=set(identifiers(ctx['product']['skuIds'])):raise SafetyError('native-video-binding-complete-scope-required')
 if not isinstance(ctx['review'],dict) or ctx['review'].get('passed') is not True or ctx['review']!={**identity_scope(ctx),'passed':True}:raise SafetyError('exact-video-product-identity-review-required')
 current=context(ops,shop,ctx['product']['productId'],ctx['source']['sessionId'],media=live,write_ready=live)
 if digest(current)!=digest({k:v for k,v in ctx.items() if k!='review'}):raise SafetyError('native-video-binding-source-product-tags-or-cards-changed')
 expected=copy.deepcopy(proof['baseline']);rows=[]
 from .sku_material_contract import normalize as other_normalize
 for sku in skus:
  for key,value in expected[sku].items():
   nkey,normalized,_=normalize(value,sku) if str(key).startswith('42:') else other_normalize(value,sku,{31,32,33,36,1002})
   if key!=nkey or digest(normalized)!=digest(value):raise SafetyError('native-video-binding-baseline-not-canonical')
  if '42:1' in expected[sku]:raise SafetyError('existing-main-video-cannot-be-overwritten')
  desired=target_material(ctx,sku);expected[sku]['42:1']=desired;rows.append({'productId':int(ctx['product']['productId']),'skuId':int(sku),'materials':[desired]})
 body={'skuMaterials':rows};validate_schema(body,ctx['cards']['POST']['inputSchema'])
 if live:
  actual=snapshot(ops,shop,skus,ctx['cards']['GET'])
  if digest(actual['contents'])!=digest(proof['baseline']):raise SafetyError('native-video-binding-baseline-changed')
 return body,expected

def contract(ops,scope,*,live=False):
 op=scope['operation']
 if op['url']!=WRITE or op['method']!='POST' or op['params']!={} or op['skillId']!=SKILL or any(k in scope for k in ('skuMaterialInput','verification','precondition','onlineVerification','resultVerification','nativeListingInput')):raise SafetyError('canonical-exclusive-native-video-binding-required')
 body,expected=body_from_proof(ops,scope['shop'],scope['videoMaterialInput'],live=live)
 if digest(body)!=digest(op.get('body')):raise SafetyError('native-video-binding-approved-body-mismatch')
 return expected

def relations(ops,ctx):
 shop=ctx['shop'];src=ctx['source'];target=ctx['product'];c=ctx['cards'][RELS];props=c['inputSchema']['properties'];idschema=props['videoIds'].get('items',{});rows=[];total=None;seen=set();hashes=[]
 for page in range(1,1001):
  params={'zoneId':src['zoneId'],'videoType':42,'videoIds':[id_value(idschema,src['metadata']['videoId'])],'page':page,'pageSize':50,'scopeSet':['BASE']};validate_schema(params,c['inputSchema']);response=read(ops.client,shop,RELS,params);part=business_payload(response);count=pagination_total(response)
  if not isinstance(part,list) or any(not isinstance(r,dict) for r in part) or count is None or count>len(target['skuIds']) or len(part)>50 or total is not None and total!=count:raise SafetyError('stable-bounded-video-relation-pagination-required')
  total=count
  for row in part:
   sku=native_id(row.get('skuId'))
   if sku in seen or sku not in target['skuIds'] or native_id(row.get('productId'))!=target['productId'] or native_id(row.get('videoId'))!=native_id(src['metadata']['videoId']) or integer(row.get('videoType'))!=42:raise SafetyError('unique-same-product-exact-video-relations-required')
   if 'jdVideoId' in row and native_id(row['jdVideoId'])!=native_id(src['metadata']['jdVideoId']):raise SafetyError('relation-original-platform-video-id-mismatch')
   if 'venderId' in row and native_id(row['venderId'])!=shop['venderId']:raise SafetyError('foreign-video-relation-owner')
   status=row.get('relationStatus',row.get('status'))
   if 'relationStatus' in row and 'status' in row and row['relationStatus']!=row['status']:raise SafetyError('contradictory-video-relation-audit-status')
   if status is None:raise SafetyError('original-video-relation-audit-status-required')
   status=integer(status)
   if status not in (3,4,5):raise SafetyError('original-video-relation-audit-status-unrecognized')
   rows.append({'skuId':sku,'status':status});seen.add(sku)
  hashes.append(digest(response))
  if len(rows)==total:break
  if not part or len(rows)>total:raise SafetyError('incomplete-original-video-relation-page')
 else:raise SafetyError('video-relation-page-limit')
 return {'rows':sorted(rows,key=lambda r:int(r['skuId'])),'total':total,'sourceHashes':hashes}
