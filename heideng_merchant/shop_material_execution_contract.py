"""Complete on-sale scope and ready missing-slot recipes; pure validation first."""
import copy,re
from .safety import SafetyError,redact
from .operations import digest,Operations,_same_identity
from .shop_material_audit import ShopMaterialAudit,ON_SALE,core,status
from .sku_material_contract import SLOTS,changes_checked,positive,identifiers,BATCH,census,read_materials,upload_source,capabilities,body_from_proof
from .products import ProductService

def slots_checked(slots):
 if slots is None:return sorted(SLOTS)
 if not isinstance(slots,list) or not slots or any(s not in SLOTS for s in slots) or len(set(slots))!=len(slots):raise SafetyError('explicit-known-shop-material-slots-required')
 return sorted(slots)

def source_context(ops,audit_id,fingerprint=None):
 record=ShopMaterialAudit(ops.state,ops.client).record(audit_id);a=record['scope']
 if fingerprint is not None and record['fingerprint']!=fingerprint:raise SafetyError('original-shop-material-audit-changed')
 if any(a.get(k) is not True for k in ('inventorySourceComplete','censusStable','materialSourceComplete')) or a.get('kind')!='whole-on-sale-shop-material-audit':raise SafetyError('complete-shop-inventory-and-material-source-required')
 products=a['products'];items=a['items'];sources=a['sources'];product_ids=[positive(p['productId']) for p in products]
 if len(set(product_ids))!=len(product_ids) or any(status(p['productStatus'])!=ON_SALE for p in products) or sources['products'].get('complete') is not True or set(sources['siblings'])!=set(product_ids):raise SafetyError('original-complete-on-sale-products-required')
 siblings={}
 for pid,source in sources['siblings'].items():
  if source.get('complete') is not True or not source.get('items'):raise SafetyError('original-complete-shop-sibling-source-required')
  for row in source['items']:
   sku=positive(row['skuId'])
   if sku in siblings or positive(row['productId'])!=pid or status(row.get('status')) is None:raise SafetyError('unique-original-shop-SKU-parent-required')
   siblings[sku]=row
 if len(items)!=len(siblings) or {r['skuId'] for r in items}!=set(siblings) or set(sources['materials']['contents'])!=set(siblings) or set(sources['materials']['audit'])!=set(siblings):raise SafetyError('complete-original-shop-material-coverage-required')
 for row in items:
  native=siblings[row['skuId']]
  if row['productId']!=positive(native['productId']) or row.get('onSale') is not (status(native['status'])==ON_SALE) or row.get('materialObserved') is not True:raise SafetyError('original-shop-sale-and-material-observation-required')
 return record

def changes_for_audit(record,changes,slots):
 if not isinstance(changes,list) or len(changes)>len(record['scope']['items'])*len(SLOTS):raise SafetyError('bounded-explicit-whole-shop-material-changes-required')
 items={r['skuId']:r for r in record['scope']['items']};groups={}
 for raw in changes:
  if not isinstance(raw,dict) or 'productId' not in raw:raise SafetyError('actual-product-in-shop-material-change-required')
  pid=positive(raw['productId']);sku=positive(raw.get('skuId'));row=items.get(sku)
  if row is None or row['onSale'] is not True or row['productId']!=pid or raw.get('slot') not in slots:raise SafetyError('shop-material-change-outside-approved-sale-scope')
  kind,order=SLOTS[raw['slot']]
  key=f'{kind}:{order}';content=record['scope']['sources']['materials']['contents'][sku].get(key)
  if raw.get('action')=='repair':
   from .sku_material_repair import repair_allowed
   if not repair_allowed(content,record['scope']['sources']['materials']['audit'][sku].get(key)):raise SafetyError('existing-rejected-or-approved-empty-slot-required')
  elif content is not None:raise SafetyError('existing-shop-material-slot-preserved-not-repaired')
  groups.setdefault(pid,[]).append({k:v for k,v in raw.items() if k!='productId'})
 result=[]
 for pid,rows in sorted(groups.items(),key=lambda x:int(x[0])):result.extend({'productId':pid,**r} for r in changes_checked(rows))
 return result

def groups(changes):
 result=[]
 for pid in sorted({r['productId'] for r in changes},key=int):
  rows=[{k:v for k,v in r.items() if k!='productId'} for r in changes if r['productId']==pid];ids=identifiers(sorted({r['skuId'] for r in rows},key=int))
  for start in range(0,len(ids),BATCH):
   selected=ids[start:start+BATCH];result.append((pid,selected,[r for r in rows if r['skuId'] in selected]))
 return result

def intent(record,changes,slots):return {'shop':record['scope']['shop'],'auditId':record['auditId'],'auditFingerprint':record['fingerprint'],'targetSlots':slots,'changes':changes}

def current_catalog(ops,record,*,all_siblings=False):
 shop=record['scope']['shop']
 if not _same_identity(ops.client.identity(shop['profile']),shop):raise SafetyError('approved-whole-shop-identity-changed')
 found=ProductService(ops.state,ops.client).list_products(shop['profile'],filters={'productStatusList':[ON_SALE],'sortBy':'created','sortType':'asc'},page_size=50,max_pages=1000)
 if found['complete'] is not True or digest(core(found['items'],('productId','productName','productStatus'),'productId'))!=digest(core(record['scope']['products'],('productId','productName','productStatus'),'productId')):raise SafetyError('approved-whole-shop-on-sale-catalog-changed')
 if all_siblings:
  products=ProductService(ops.state,ops.client)
  for pid,original in record['scope']['sources']['siblings'].items():
   observed=products.list_skus(shop['profile'],pid,page_size=50,max_pages=1000)
   if observed['complete'] is not True or digest(core(observed['items'],('skuId','productId','skuName','status'),'skuId'))!=digest(core(original['items'],('skuId','productId','skuName','status'),'skuId')):raise SafetyError('approved-whole-shop-final-sibling-catalog-changed')
 return found

def live_product(ops,scope,record):
 proof=scope['skuMaterialInput'];shop=scope['shop'];pid=proof['productId'];products=ProductService(ops.state,ops.client)
 found=products.list_products(shop['profile'],filters={'productStatusList':[ON_SALE],'productIdList':[int(pid)]},page_size=50,max_pages=1000)
 expected=[p for p in record['scope']['products'] if positive(p['productId'])==pid]
 if found['complete'] is not True or len(found['items'])!=1 or digest(core(found['items'],('productId','productName','productStatus'),'productId'))!=digest(core(expected,('productId','productName','productStatus'),'productId')):raise SafetyError('approved-shop-material-product-no-longer-on-sale')
 actual=products.list_skus(shop['profile'],pid,page_size=50,max_pages=1000)
 if actual['complete'] is not True or digest(core(actual['items'],('skuId','productId','skuName','status'),'skuId'))!=digest(core(record['scope']['sources']['siblings'][pid]['items'],('skuId','productId','skuName','status'),'skuId')):raise SafetyError('approved-shop-material-sibling-sale-state-changed')

def contract(ops,scope,*,live=False,dispatch=False):
 outer=scope.get('shopMaterialInput')
 if outer is None:return
 if not isinstance(outer,dict) or set(outer)!={'version','intentHash','auditId','auditFingerprint'} or type(outer['version']) is not int or outer['version']!=1 or any(not isinstance(outer[k],str) or not re.fullmatch('[a-f0-9]{64}',outer[k]) for k in ('intentHash','auditFingerprint')) or 'skuMaterialInput' not in scope or 'videoMaterialInput' in scope:raise SafetyError('complete-dedicated-shop-material-proof-required')
 record=source_context(ops,outer['auditId'],outer['auditFingerprint']);proof=scope['skuMaterialInput']
 if scope['shop']!=record['scope']['shop'] or proof['intentHash']!=outer['intentHash']:raise SafetyError('shop-material-child-original-scope-mismatch')
 children=changes_for_audit(record,[{'productId':proof['productId'],**r} for r in proof['changes']],sorted(SLOTS))
 if {r['skuId'] for r in children}!=set(proof['skuIds']) or proof['baseline']!={sku:record['scope']['sources']['materials']['contents'][sku] for sku in proof['skuIds']} or proof['siblingSkuIds']!=identifiers([r['skuId'] for r in record['scope']['sources']['siblings'][proof['productId']]['items']]):raise SafetyError('shop-material-child-original-audit-proof-mismatch')
 if proof.get('version')==2 and proof.get('baselineAudit')!={sku:record['scope']['sources']['materials']['audit'][sku] for sku in proof['skuIds']}:raise SafetyError('shop-material-child-original-audit-status-proof-mismatch')
 if dispatch:
  from .shop_material_execution_state import require_dispatch
  require_dispatch(ops,scope)
 if live:live_product(ops,scope,record)
