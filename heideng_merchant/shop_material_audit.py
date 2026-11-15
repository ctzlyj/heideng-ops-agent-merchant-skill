"""Complete-scope read-only shop census; scores never stand in for inventory."""
from __future__ import annotations
import time,re
from decimal import Decimal,InvalidOperation
from pathlib import Path
from .operations import Operations,digest
from .products import ProductService,identifier
from .safety import SafetyError,atomic_json,read_json,safe_join,redact
from .state import FileLock
from .official_transport import matches_shop
from .sku_material_contract import SLOTS,capability,read_materials,integer

ON_SALE=103

def score(value):
 if isinstance(value,bool) or not isinstance(value,(str,int,float)):return None
 try:result=Decimal(str(value).strip())
 except InvalidOperation:return None
 if not result.is_finite() or not 0<=result<=100:return None
 return result

def status(value):
 try:return integer(value)
 except SafetyError:return None

def core(rows,fields,key):
 return sorted([{field:row.get(field) for field in fields} for row in rows],key=lambda row:int(row[key]))

class ShopMaterialAudit:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client);self.products=ProductService(self.state,client)
 def _shop(self,shop):
  if not matches_shop(self.client.identity(shop['profile']),shop):raise SafetyError('shop-changed-during-whole-shop-audit')
 def _collect(self,shop,call,reasons,label):
  self._shop(shop)
  try:result=call()
  except (ValueError,TypeError,RecursionError):raise SafetyError('native-shop-source-unrepresentable-json-refused') from None
  except SafetyError as error:
   self._shop(shop)
   if 'private' in str(error) or 'sensitive' in str(error):raise SafetyError('sensitive-whole-shop-response-refused') from None
   reasons.append(label+' unavailable or incomplete');return {'items':[],'complete':False,'reportedTotal':None,'sourcePageHashes':[],'reason':'source-unavailable-or-incomplete'}
  self._shop(shop)
  if redact(result['items'])!=result['items']:raise SafetyError('sensitive-whole-shop-response-refused')
  complete=bool(result['complete']) and result['reportedTotal'] is not None and result['reportedTotal']==len(result['items']) and result.get('startPage')==1
  if not complete:reasons.append(label+' lacks complete stable pagination total')
  return {**result,'complete':complete}
 def path(self,audit_id):
  if not isinstance(audit_id,str) or not re.fullmatch('[a-f0-9]{24}',audit_id):raise SafetyError('invalid-shop-material-audit-id')
  return safe_join(self.state,'shop-material-audits/'+audit_id+'.json')
 def record(self,audit_id):
  value=read_json(self.path(audit_id))
  if not isinstance(value,dict) or not isinstance(value.get('scope'),dict) or digest(value['scope'])!=value.get('fingerprint') or value['fingerprint'][:24]!=audit_id or value.get('auditId')!=audit_id:raise SafetyError('shop-material-audit-missing-or-modified')
  return value
 def audit(self,profile,*,threshold=89,max_products=10000,max_skus=100000,max_pages=1000,include_health=True,install_guard=None):
  for value,minimum,maximum in ((threshold,0,99),(max_products,1,100000),(max_skus,1,1000000),(max_pages,1,1000)):
   if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:raise SafetyError('bounded-whole-shop-audit-options-required')
  if not isinstance(include_health,bool):raise SafetyError('explicit-health-read-choice-required')
  if install_guard is not None:
   if not isinstance(install_guard,FileLock):raise SafetyError('existing-same-owner-install-guard-required')
   install_guard.require_owned(self.state/'install.lock')
  shop={k:self.ops.shop(profile)[k] for k in ('profile','venderId','shopId','shopName')};self._shop(shop)
  with (__import__('contextlib').nullcontext() if install_guard is not None else FileLock(self.state/'install.lock')),FileLock(self.state/'shop-material-audit.lock'):
   started=time.time();reasons=[];filters={'productStatusList':[ON_SALE],'sortBy':'created','sortType':'asc'}
   def product_read():return self.products.list_products(profile,filters=filters,page_size=50,max_pages=max_pages)
   products=self._collect(shop,product_read,reasons,'product census')
   if (products['reportedTotal'] or 0)>max_products or len(products['items'])>max_products:raise SafetyError('whole-shop-product-budget-exceeded-no-truncation')
   valid_products=[];inventory_complete=products['complete']
   for row in products['items']:
    if status(row.get('productStatus'))!=ON_SALE:inventory_complete=False;reasons.append('product query returned an unproven on-sale status');continue
    valid_products.append(row)
   siblings={};sku_sources={}
   for product in sorted(valid_products,key=lambda row:int(row['productId'])):
    product_id=identifier(product['productId']);source=self._collect(shop,lambda p=product_id:self.products.list_skus(profile,p,page_size=50,max_pages=max_pages),reasons,'SKU census '+product_id);sku_sources[product_id]=source;inventory_complete=inventory_complete and source['complete']
    if not source['items']:inventory_complete=False;reasons.append('on-sale product '+product_id+' has no proven sibling SKU set')
    for row in source['items']:
     sku=identifier(row['skuId'])
     if sku in siblings:inventory_complete=False;reasons.append('duplicate SKU across products');continue
     siblings[sku]=row
     if status(row.get('status')) is None:inventory_complete=False;reasons.append('SKU on-sale status unproven')
     if len(siblings)>max_skus:raise SafetyError('whole-shop-SKU-budget-exceeded-no-truncation')
   empty_inventory=inventory_complete and not valid_products
   health=self._collect(shop,lambda:self.products.list_health(profile,page_size=100,max_pages=max_pages),reasons,'information-health') if include_health and not empty_inventory else {'items':[],'complete':False,'reportedTotal':None,'sourcePageHashes':[],'reason':'not-required-empty-inventory' if empty_inventory else 'not-requested'}
   health_by_sku={identifier(row['skuId']):row for row in health['items']};health_parent_mismatch=[]
   for sku,row in health_by_sku.items():
    if sku in siblings and 'productId' in row:
     try:matches=identifier(row['productId'])==identifier(siblings[sku]['productId'])
     except SafetyError:matches=False
     if not matches:health_parent_mismatch.append(sku);reasons.append('health row parent linkage inconsistent')
   snapshot={'contents':{},'audit':{},'sourceHashes':[]};material_complete=True;card=None
   sku_ids=sorted(siblings,key=int)
   if not empty_inventory:
    try:card=capability(self.client,shop,'GET')
    except SafetyError as error:
     self._shop(shop)
     if 'private' in str(error) or 'sensitive' in str(error):raise SafetyError('sensitive-whole-shop-response-refused') from None
     material_complete=False;reasons.append('native material capability unavailable or unproven')
   if card is not None:
    for start in range(0,len(sku_ids),1000):
     try:part=read_materials(self.client,shop,sku_ids[start:start+1000],card['inputSchema'])
     except SafetyError as error:
      self._shop(shop)
      if 'private' in str(error) or 'sensitive' in str(error):raise SafetyError('sensitive-whole-shop-response-refused') from None
      material_complete=False;reasons.append('material segment unavailable/incomplete; gaps not inferred');continue
     for key in ('contents','audit'):snapshot[key].update(part[key])
     snapshot['sourceHashes'].extend(part['sourceHashes'])
    try:latest=capability(self.client,shop,'GET')
    except SafetyError as error:
     self._shop(shop)
     if 'private' in str(error) or 'sensitive' in str(error):raise SafetyError('sensitive-whole-shop-response-refused') from None
     material_complete=False;reasons.append('final material capability unavailable');latest=None
    if latest is None or digest(latest)!=digest(card):material_complete=False;reasons.append('material capability changed during audit')
   end_products=self._collect(shop,product_read,reasons,'final product census');stable=bool(products['complete'] and end_products['complete']) and digest(core(products['items'],('productId','productName','productStatus'),'productId'))==digest(core(end_products['items'],('productId','productName','productStatus'),'productId'))
   if not stable:reasons.append('on-sale product census changed or incomplete')
   end_skus={}
   for product_id,source in sku_sources.items():
    final=self._collect(shop,lambda p=product_id:self.products.list_skus(profile,p,page_size=50,max_pages=max_pages),reasons,'final SKU census '+product_id);end_skus[product_id]=final
    if not source['complete'] or not final['complete'] or digest(core(source['items'],('skuId','productId','skuName','status'),'skuId'))!=digest(core(final['items'],('skuId','productId','skuName','status'),'skuId')):stable=False;reasons.append('sibling SKU census changed or incomplete')
   self._shop(shop);items=[]
   for sku in sku_ids:
    native=siblings[sku];health_row=health_by_sku.get(sku);raw_score=health_row.get('healthScore') if health_row else None;parsed=score(raw_score);mismatch=sku in health_parent_mismatch
    if mismatch:parsed=None
    score_state='mismatched-parent' if mismatch else 'valid' if parsed is not None else 'missing' if health_row is None or raw_score in (None,'') else 'invalid'
    if not include_health:score_state='not-requested'
    elif health_row is None and not health['complete']:score_state='unobserved'
    sale_status=status(native.get('status'));on_sale=None if sale_status is None else sale_status==ON_SALE;observed=sku in snapshot['contents'];slots=snapshot['contents'].get(sku,{});audit=snapshot['audit'].get(sku,{});missing=[];empty=[];pending=[];rejected=[];unrecognized=[]
    for name,(kind,order) in SLOTS.items():
     key=f'{kind}:{order}';material=slots.get(key)
     if material is None:missing.append(name);continue
     values=material['textMaterial']['contents'] if kind==1002 else material['imageMaterial']['skuImages']
     if not values or (kind==1002 and not any(v.strip() for v in values)):empty.append(name)
     material_status=audit[key]['status']
     if material_status==3:pending.append(name)
     elif material_status==5:rejected.append(name)
     elif material_status!=4:unrecognized.append(name)
    improvements=health_row.get('improvementList') if health_row and not mismatch else None;short_title=None
    if isinstance(improvements,list):short_title=any(isinstance(row,dict) and isinstance(row.get('improvementDetail'),dict) and row['improvementDetail'].get('troubleCode')=='hasShortTitle' for row in improvements)
    items.append({'skuId':sku,'productId':identifier(native['productId']),'skuName':native.get('skuName'),'onSale':on_sale,'scoreState':score_state,'healthScoreRaw':None if mismatch else raw_score,'scoreDecimal':str(parsed) if parsed is not None else None,'lowScore':on_sale is True and parsed is not None and parsed<=threshold,'materialObserved':observed,'missingSlots':missing if observed else None,'emptyExistingSlots':empty if observed else None,'pendingSlots':pending if observed else None,'rejectedSlots':rejected if observed else None,'unrecognizedStatusSlots':unrecognized if observed else None,'shortTitleIssue':short_title,'improvementList':improvements,'auditReasons':audit if observed else None})
   complete=inventory_complete and stable and material_complete and len(snapshot['contents'])==len(siblings) and not health_parent_mismatch and (health['complete'] or not include_health or empty_inventory)
   scope={'kind':'whole-on-sale-shop-material-audit','shop':shop,'startedAt':started,'finishedAt':time.time(),'threshold':threshold,'healthRequested':include_health,'emptyInventory':empty_inventory,'products':valid_products,'items':items,'sources':{'products':products,'siblings':sku_sources,'health':health,'materials':snapshot,'materialCapability':card,'endProducts':end_products,'endSiblings':end_skus},'inventorySourceComplete':inventory_complete,'censusStable':stable,'healthSourceComplete':health['complete'],'materialSourceComplete':material_complete and len(snapshot['contents'])==len(siblings),'complete':bool(complete),'reasons':list(dict.fromkeys(reasons))}
   if redact(scope)!=scope:raise SafetyError('sensitive-whole-shop-response-refused')
   if len(str(scope))>128*1024*1024:raise SafetyError('whole-shop-capture-memory-budget-exceeded')
   fingerprint=digest(scope);audit_id=fingerprint[:24];atomic_json(self.path(audit_id),{'auditId':audit_id,'fingerprint':fingerprint,'scope':scope})
   return self.status(audit_id)
 def status(self,audit_id):
  value=self.record(audit_id);scope=value['scope'];items=scope['items'];sale=[row for row in items if row['onSale'] is True]
  selections={'lowScoreSkuIds':lambda r:r['lowScore'],'unscoredSkuIds':lambda r:r['scoreState']=='missing','unobservedScoreSkuIds':lambda r:r['scoreState'] in ('unobserved','not-requested'),'invalidScoreSkuIds':lambda r:r['scoreState']=='invalid','materialGapSkuIds':lambda r:r['materialObserved'] and bool(r['missingSlots'] or r['emptyExistingSlots']),'pendingSkuIds':lambda r:bool(r['pendingSlots']),'rejectedSkuIds':lambda r:bool(r['rejectedSlots']),'shortTitleIssueSkuIds':lambda r:r['shortTitleIssue'] is True,'unobservedMaterialSkuIds':lambda r:not r['materialObserved']}
  result={'auditId':audit_id,'fingerprint':value['fingerprint'],'reportPath':str(self.path(audit_id)),'scope':'all on-sale products and every sibling SKU, not off-sale products','complete':scope['complete'],'reasons':scope['reasons'],'profile':scope['shop']['profile'],'onSaleProductCount':len(scope['products']),'reportedOnSaleProductTotal':scope['sources']['products']['reportedTotal'],'allSiblingSkuCount':len(items),'onSaleSkuCount':len(sale),'inventorySourceComplete':scope['inventorySourceComplete'],'censusStable':scope['censusStable'],'scoreSourceComplete':scope['healthSourceComplete'],'materialSourceComplete':scope['materialSourceComplete'],'materialObservedSkuCount':len(scope['sources']['materials']['contents']),'healthRequested':scope['healthRequested'],'metricName':'商品信息健康分','metricField':'healthScore','portalScoreEquivalent':None,'startedAt':scope['startedAt'],'finishedAt':scope['finishedAt'],'historicalCapture':True,'noWorkInScope':scope['complete'] and not sale,'scoreCoverageComplete':scope['healthSourceComplete'] and all(r['scoreState']=='valid' for r in sale),'transactionSnapshot':False,'writesPerformed':False,'scoreRecalculated':False}
  for key,predicate in selections.items():
   result[key]=[row['skuId'] for row in sale if predicate(row)];result[key[:-3]+'Count']=len(result[key])
  result['lowScoreSkuCount']=len(result['lowScoreSkuIds'])
  unmatched=sorted(set(identifier(r['skuId']) for r in scope['sources']['health']['items'])-{r['skuId'] for r in items},key=int);proven=scope['inventorySourceComplete'] and scope['censusStable']
  result.update(healthUnmatchedObservedSkuIds=unmatched,healthUnmatchedObservedSkuCount=len(unmatched),healthOutsideCurrentCatalogSkuIds=unmatched if proven else None,outsideClassificationProven=proven,outsideHealthCoverageComplete=proven and scope['healthSourceComplete'])
  return result
 def page(self,audit_id,*,page=1,page_size=50,include_offline=False,only='all'):
  if isinstance(page,bool) or not isinstance(page,int) or not 1<=page<=1000000 or isinstance(page_size,bool) or not isinstance(page_size,int) or not 1<=page_size<=200 or not isinstance(include_offline,bool):raise SafetyError('bounded-shop-audit-page-required')
  filters={'all':lambda r:True,'low-score':lambda r:r['lowScore'],'gaps':lambda r:r['materialObserved'] and bool(r['missingSlots'] or r['emptyExistingSlots']),'pending':lambda r:bool(r['pendingSlots']),'rejected':lambda r:bool(r['rejectedSlots']),'unscored':lambda r:r['scoreState']=='missing','short-title':lambda r:r['shortTitleIssue'] is True,'unobserved':lambda r:not r['materialObserved']}
  if only not in filters:raise SafetyError('known-shop-audit-page-filter-required')
  scope=self.record(audit_id)['scope'];rows=[row for row in scope['items'] if (include_offline or row['onSale'] is True) and filters[only](row)];start=(page-1)*page_size;selected=rows[start:start+page_size]
  return {'auditId':audit_id,'items':selected,'total':len(rows),'page':page,'pageSize':page_size,'only':only,'includeOfflineSiblings':include_offline,'captureComplete':scope['complete'],'pageIsWholeSelection':scope['complete'] and page==1 and len(selected)==len(rows),'pageIsWholeShop':scope['complete'] and only=='all' and page==1 and len(selected)==len(scope['items']),'rowScope':'all siblings of on-sale products' if include_offline else 'on-sale SKU rows only','nextPage':page+1 if start+len(selected)<len(rows) else None,'historicalCapture':True,'writesPerformed':False}

 def summary(self,audit_id):
  result=self.status(audit_id)
  return {**{k:v for k,v in result.items() if not k.endswith('Ids')},'summaryOnly':True,'rowAccess':'sku-material-shop-rows or full local capture; ID lists are not clipped into an alleged full-shop result'}
