"""Original complete shop/health source and reviewed short-title copy contracts."""
import unicodedata,re
from .operations import digest
from .safety import SafetyError,redact
from .products import identifier
from .shop_material_audit import ShopMaterialAudit,ON_SALE,status,core

BATCH=5000

def title_checked(text):
 if not isinstance(text,str) or not text or text!=text.strip() or unicodedata.normalize('NFC',text)!=text or any(unicodedata.category(c).startswith('C') for c in text) or redact(text)!=text:raise SafetyError('reviewed-safe-short-title-text-required')
 length=sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in text)
 if not 1<=length<=30:raise SafetyError('short-title-conservative-weighted-limit-30')
 return text

def issue(health,product):
 if health is None:return None
 if 'productId' in health:
  try:
   if identifier(health['productId'])!=product:return None
  except SafetyError:return None
 rows=health.get('improvementList')
 if not isinstance(rows,list):return None
 return any(isinstance(r,dict) and isinstance(r.get('improvementDetail'),dict) and r['improvementDetail'].get('troubleCode')=='hasShortTitle' for r in rows)

def source_context(state,audit_id,fingerprint=None):
 record=ShopMaterialAudit(state,None).record(audit_id);a=record['scope'];sources=a['sources']
 if redact(record)!=record or (fingerprint is not None and fingerprint!=record['fingerprint']):raise SafetyError('original-short-title-source-changed-or-private')
 if a.get('kind')!='whole-on-sale-shop-material-audit' or a.get('inventorySourceComplete') is not True or a.get('censusStable') is not True or sources['products'].get('complete') is not True or sources['endProducts'].get('complete') is not True:raise SafetyError('complete-stable-short-title-inventory-required')
 products={identifier(row['productId']):row for row in a['products']}
 if len(products)!=len(a['products']) or set(sources['siblings'])!=set(products) or set(sources['endSiblings'])!=set(products) or any(status(p['productStatus'])!=ON_SALE for p in products.values()):raise SafetyError('complete-short-title-product-source-required')
 if digest(core(sources['products']['items'],('productId','productName','productStatus'),'productId'))!=digest(core(a['products'],('productId','productName','productStatus'),'productId')) or digest(core(a['products'],('productId','productName','productStatus'),'productId'))!=digest(core(sources['endProducts']['items'],('productId','productName','productStatus'),'productId')):raise SafetyError('original-short-title-product-census-changed')
 siblings={}
 for pid,source in sources['siblings'].items():
  final=sources['endSiblings'][pid]
  if source.get('complete') is not True or final.get('complete') is not True or not source.get('items') or digest(core(source['items'],('skuId','productId','skuName','status'),'skuId'))!=digest(core(final['items'],('skuId','productId','skuName','status'),'skuId')):raise SafetyError('complete-short-title-sibling-census-required')
  for row in source['items']:
   sku=identifier(row['skuId'])
   if sku in siblings or identifier(row['productId'])!=pid or status(row.get('status')) is None:raise SafetyError('unique-short-title-sibling-parent-required')
   siblings[sku]=row
 empty=not products
 if not empty and (a.get('healthRequested') is not True or sources['health'].get('complete') is not True):raise SafetyError('complete-original-short-title-health-source-required')
 health={}
 for row in sources['health']['items']:
  sku=identifier(row['skuId'])
  if sku in health:raise SafetyError('unique-original-short-title-health-row-required')
  health[sku]=row
 items={row['skuId']:row for row in a['items']}
 if len(items)!=len(a['items']) or set(items)!=set(siblings):raise SafetyError('complete-original-short-title-coverage-required')
 coverage=[]
 for sku,native in sorted(siblings.items(),key=lambda pair:int(pair[0])):
  pid=identifier(native['productId']);on_sale=status(native['status'])==ON_SALE;flag=issue(health.get(sku),pid);saved=items[sku]
  if saved['productId']!=pid or saved.get('onSale') is not on_sale or saved.get('shortTitleIssue') is not flag:raise SafetyError('original-short-title-projection-changed')
  name=native.get('skuName') or products[pid].get('productName')
  if not isinstance(name,str) or not name.strip() or redact(name)!=name:name=None
  coverage.append({'productId':pid,'skuId':sku,'onSale':on_sale,'sourceTitle':name,'nativeTitleIssue':flag,'originalShortTitleVerified':False})
 return record,coverage

def changes_checked(coverage,changes):
 if not isinstance(changes,list) or len(changes)>len(coverage):raise SafetyError('bounded-explicit-short-title-copy-required')
 known={r['skuId']:r for r in coverage};out=[];seen=set();titles=set()
 for row in changes:
  if not isinstance(row,dict) or set(row)!={'productId','skuId','shortTitle','review'} or row['review']!='passed':raise SafetyError('reviewed-short-title-copy-fields-required')
  pid=identifier(row['productId']);sku=identifier(row['skuId']);native=known.get(sku)
  if native is None or native['onSale'] is not True or native['productId']!=pid or native['nativeTitleIssue'] is not True or native['sourceTitle'] is None:raise SafetyError('known-on-sale-original-short-title-issue-required')
  text=title_checked(row['shortTitle']);key=unicodedata.normalize('NFKC',text).casefold()
  if sku in seen or key in titles:raise SafetyError('unique-reviewed-short-title-copy-required')
  seen.add(sku);titles.add(key);out.append({'productId':pid,'skuId':sku,'shortTitle':text,'review':'passed','sourceTitleSha256':digest(native['sourceTitle'])})
 return sorted(out,key=lambda r:int(r['skuId']))

def chunks(changes):return [changes[i:i+BATCH] for i in range(0,len(changes),BATCH)]
