"""Merchant-owned publication lookups; no employee endpoints or guessed IDs."""
from pathlib import Path
from .product_schema import ProductSchemaService,SCHEMAS,parse_schema
from .products import identifier
from .operations import digest
from .safety import SafetyError,redact
from .verification import business_payload,pagination_total

CATEGORIES='/rest/sp-seller/v0/vender-categories'
BRANDS='/rest/sp-seller/v0/vender-brands'
SALE='/rest/sp-product/v0/categories/{categoryId}/sale-attr-templates'

class PublishSupport(ProductSchemaService):
 def categories(self,profile,ids=(0,)):
  ids=[0 if str(i)=='0' else int(identifier(i)) for i in ids]
  response=self._read(profile,CATEGORIES,{'sceneType':3,'categoryIdList':ids},skill='jdo-product-publish');rows=business_payload(response)
  if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise SafetyError('native-category-array-required')
  keys=[identifier(row.get('categoryId')) for row in rows]
  if len(set(keys))!=len(keys):raise SafetyError('native-category-identity-ambiguous')
  if redact(rows)!=rows:raise SafetyError('private-category-response-refused')
  return rows
 def _category(self,profile,ident):
  rows=self.categories(profile,[ident]);matches=[r for r in rows if identifier(r['categoryId'])==str(ident)]
  if len(matches)!=1:raise SafetyError('actual-authorized-category-not-found')
  return matches[0]
 def _brand(self,profile,third,brand):
  seen=set();total=None;count=0
  for page in range(1,101):
   response=self._read(profile,BRANDS,{'queryType':2,'categoryId':int(third),'authStatus':2,'page':page,'pageSize':20},skill='jdo-product-publish');rows=business_payload(response)
   if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise SafetyError('native-brand-page-array-required')
   ids=[identifier(r.get('brandId')) for r in rows]
   if len(set(ids))!=len(ids) or seen.intersection(ids):raise SafetyError('native-brand-pagination-repeats')
   for row in rows:
    if identifier(row['brandId'])==brand:
     if 'authStatus' in row and str(row['authStatus'])!='2':raise SafetyError('brand-authorization-not-active')
     return row
   seen.update(ids);count+=len(rows);new_total=pagination_total(response)
   if new_total is None or (total is not None and new_total!=total):raise SafetyError('native-brand-pagination-incomplete')
   total=new_total
   if count==total:raise SafetyError('actual-authorized-brand-not-found')
   if count>total or not rows:raise SafetyError('native-brand-pagination-incomplete')
  raise SafetyError('native-brand-local-page-budget-reached-no-truncation')
 def brands(self,profile,category_id,*,name=None,max_pages=100,start_page=1):
  if any(isinstance(v,bool) or not isinstance(v,int) for v in (max_pages,start_page)) or not 1<=max_pages<=1000 or start_page<1:raise SafetyError('bounded-brand-pages-required')
  if name is not None and (not isinstance(name,str) or not name or len(name)>10 or redact(name)!=name):raise SafetyError('actual-brand-search-name-up-to-10-characters-required')
  node=self._category(profile,identifier(category_id));seen_parents=set()
  while str(node.get('categoryLevel'))!='3':
   key=identifier(node['categoryId'])
   if key in seen_parents or len(seen_parents)>=8:raise SafetyError('native-category-parent-cycle-or-budget')
   seen_parents.add(key);node=self._category(profile,identifier(node.get('parentCategoryId')))
  rows=[];ids=set();total=None;hashes=[];next_page=start_page;end=False;reason='local-page-budget-reached'
  for page in range(start_page,start_page+max_pages):
   params={'queryType':2,'categoryId':int(identifier(node['categoryId'])),'authStatus':2,'page':page,'pageSize':20}
   if name is not None:params['brandName']=name
   response=self._read(profile,BRANDS,params,skill='jdo-product-publish');data=business_payload(response)
   if not isinstance(data,list) or any(not isinstance(r,dict) for r in data):raise SafetyError('native-brand-page-array-required')
   keys=[identifier(r.get('brandId')) for r in data]
   if len(set(keys))!=len(keys) or ids.intersection(keys):reason='pagination-identity-repeat';break
   if any('authStatus' in r and str(r['authStatus'])!='2' for r in data):raise SafetyError('brand-authorization-not-active')
   new_total=pagination_total(response)
   if total is not None and new_total!=total:reason='pagination-total-changed';break
   rows.extend(data);ids.update(keys);hashes.append(digest(response));next_page=page+1;total=new_total
   if total is None:reason='pagination-metadata-missing';break
   remaining=max(total-(start_page-1)*20,0)
   if len(rows)==remaining:end=True;next_page=None;reason=None;break
   if len(rows)>remaining or not data:reason='pagination-total-incomplete';break
  if end and start_page>1:reason='earlier-pages-not-in-this-result'
  return {'items':rows,'complete':end and start_page==1,'segmentComplete':end,'nextPage':next_page,'reason':reason,'reportedTotal':total,'sourcePageHashes':hashes,'thirdCategoryId':node['categoryId'],'source':'official-realtime-merchant-authorized-brands'}
 def context(self,profile,category_id,brand_id):
  category_id=identifier(category_id);brand_id=identifier(brand_id);leaf=self._category(profile,category_id)
  if leaf.get('leafFlag') is not True or leaf.get('selectableFlag') is not True:raise SafetyError('active-authorized-leaf-category-required')
  node=leaf;ancestors=[];seen=set()
  while str(node.get('categoryLevel'))!='3':
   key=identifier(node['categoryId'])
   if key in seen or len(seen)>=8:raise SafetyError('native-category-parent-cycle-or-budget')
   seen.add(key);parent=identifier(node.get('parentCategoryId'));node=self._category(profile,parent);ancestors.append(node)
  third=identifier(node['categoryId']);brand=self._brand(profile,third,brand_id)
  response=self._read(profile,SCHEMAS,{'lastCategoryId':int(category_id),'scene':'pop'},skill='jdo-product-publish');schema,text_hash=parse_schema(response)
  structural=False
  def walk(rows):
   nonlocal structural
   for r in rows:
    if not isinstance(r,dict):continue
    if r.get('extra',{}).get('isStructure') is True:structural=True
    if isinstance(r.get('childrenComponents'),list):walk(r['childrenComponents'])
  walk(schema);sales=[]
  if structural:
   sales=business_payload(self._read(profile,SALE,{'categoryId':int(category_id)},skill='jdo-product-publish'))
   if not isinstance(sales,list):raise SafetyError('native-sale-template-array-required')
   from .publication_contract import json_value
   for row in sales:
    if not isinstance(row,dict) or row.get('templateType') not in ('1','2') or not isinstance(row.get('templateData'),str):raise SafetyError('native-sale-template-type-and-json-string-required')
    json_value(row['templateData'])  # Validate without rewriting/cropping opaque value rules.
  result={'category':leaf,'categoryAncestors':ancestors,'thirdCategoryId':int(third),'brand':brand,'schema':schema,'schemaTextSha256':text_hash,'saleAttributeTemplates':sales}
  from .product_schema import _validate_logical_properties
  _validate_logical_properties(result)
  if redact(result)!=result:raise SafetyError('private-publication-context-refused')
  result['contextHash']=digest(result)
  return result
