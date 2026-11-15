"""Synthetic multi-product shop, including off-sale siblings and unscored SKUs."""
import copy,importlib.util,tempfile,unittest
from pathlib import Path
from tests.test_sku_materials import Client,material,READ
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError,atomic_json,read_json

PRODUCTS='/rest/sp-product/v0/products'
SKUS='/rest/sp-product/v0/skus'
HEALTH='/rest/sp-product/v0/health-infos'

class ShopClient(Client):
 def __init__(self,large=0):
  super().__init__(0);self.products=[{'productId':9,'productName':'synthetic-one','productStatus':103},{'productId':10,'productName':'synthetic-two','productStatus':103},{'productId':20,'productName':'synthetic-offsale','productStatus':104}];self.fault=None;self.product_reads=0;self.sku_reads={};self.health_reads=0
  self.skus=[{'skuId':s,'productId':p,'status':status,'skuName':'synthetic-'+str(s)} for s,p,status in ((101,9,103),(102,9,103),(103,9,103),(104,9,104),(201,10,103),(202,10,103),(203,10,103),(301,20,103))]
  self.health=[{'skuId':s,'productId':p,'healthScore':v,'improvementList':[]} for s,p,v in ((101,9,0),(102,9,90),(104,9,80),(201,10,'89'),(202,10,'not-scored'),(203,10,100),(301,20,10),(999,20,5))]
  self.health[0]['improvementList']=[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]
  if large:
   n=(large+999)//1000;self.products=[{'productId':i+9,'productName':'synthetic-'+str(i+9),'productStatus':103} for i in range(n)];self.skus=[{'skuId':i+101,'productId':9+i//1000,'status':103,'skuName':'synthetic-'+str(i)} for i in range(large)];self.skus +=[{'skuId':100000+i,'productId':i+9,'status':104,'skuName':'synthetic-offline'} for i in range(n)];self.health=[{'skuId':r['skuId'],'productId':r['productId'],'healthScore':80,'improvementList':[]} for r in self.skus if r['status']==103];self.health.pop(2)
  self.materials={str(r['skuId']):[material(r['skuId'])] for r in self.skus};self.materials['102']=[material(102,31,1)];self.materials['102'][0]['imageMaterial']['skuImages']=[]
  if not large:self.materials['201']=[{**material(201,31,1,status=5),'auditDesc':'synthetic rejected'},material(201,33,1,status=3)];self.materials['202']=[material(202,36,1,status=None)]
 def invoke(self,p,url,**kw):
  if url in (PRODUCTS,SKUS,HEALTH):
   self.calls.append((url,copy.deepcopy(kw)));q=kw['params'];size=q['pageSize'];page=q['page']
   if url==PRODUCTS:
    self.product_reads+=1;rows=[r for r in self.products if r['productStatus'] in q['productStatusList']]
    if self.fault=='product-drift' and self.product_reads>1:rows=rows[:-1]
    if self.fault=='private':rows=[{**r,'access_token':'SYNTHETIC_PRIVATE_DO_NOT_PERSIST'} for r in rows]
   elif url==SKUS:
    product=int(q['productIdList']);self.sku_reads[product]=self.sku_reads.get(product,0)+1;rows=[r for r in self.skus if r['productId']==product]
    if self.fault=='sku-drift' and self.sku_reads[product]>1:rows=rows[:-1]
    if self.fault=='foreign-sku' and rows:rows=[{**rows[0],'productId':99},*rows[1:]]
    if self.fault=='duplicate-sku' and product==10:rows=[{**rows[0],'skuId':101},*rows[1:]]
   else:self.health_reads+=1;rows=self.health
   if self.fault=='reorder':rows=list(reversed(rows))
   selected=rows[(page-1)*size:page*size];response={'data':copy.deepcopy(selected),'paginationData':{'totalItems':len(rows)}}
   if self.fault=='missing-total':response.pop('paginationData')
   return response
  if url==READ and self.fault=='shop-drift':self.foreign=True
  if url.endswith('/apis/{apiname}') and self.fault=='card-drift' and self.reads:self.card_fault='unknown'
  return super().invoke(p,url,**kw)

class ShopAuditTests(unittest.TestCase):
 def make(self,d,large=0):
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  c=ShopClient(large);s=ShopMaterialAudit(d,c);s.ops.connect('merchant-test','synthetic-store','1');return c,s
 def run_audit(self,s,**kw):return s.audit('merchant-test',**kw)
 def test_whole_shop_service_exists(self):self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.shop_material_audit'),'whole-shop source census is missing')
 def test_entire_inventory_not_score_rows_and_offline_siblings_remain_visible(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);r=self.run_audit(s);self.assertTrue(r['complete']);self.assertEqual(r['onSaleProductCount'],2);self.assertEqual(r['allSiblingSkuCount'],7);self.assertEqual(r['onSaleSkuCount'],6);self.assertEqual(r['lowScoreSkuIds'],['101','201']);self.assertEqual(r['unscoredSkuIds'],['103']);self.assertEqual(r['invalidScoreSkuIds'],['202']);self.assertIsNone(r['portalScoreEquivalent']);self.assertFalse(c.posts)
 def test_full_score_missing_material_empty_slot_pending_rejected_are_distinct(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);r=self.run_audit(s);rows=s.page(r['auditId'],page_size=50)['items'];by_id={row['skuId']:row for row in rows};self.assertIn('102',r['materialGapSkuIds']);self.assertIn('white',by_id['102']['emptyExistingSlots']);self.assertNotIn('white',by_id['102']['missingSlots']);self.assertEqual(by_id['201']['rejectedSlots'],['white']);self.assertEqual(by_id['201']['pendingSlots'],['selling']);self.assertEqual(by_id['202']['unrecognizedStatusSlots'],['transparent']);self.assertEqual(r['shortTitleIssueSkuIds'],['101'])
 def test_pagination_total_missing_or_foreign_duplicate_sku_never_complete(self):
  for fault in ('missing-total','foreign-sku','duplicate-sku'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.fault=fault;r=self.run_audit(s);self.assertFalse(r['complete']);self.assertTrue(r['reasons']);self.assertFalse(c.posts)
 def test_material_response_omission_is_unobserved_not_assumed_gap(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.fault='omitted';r=self.run_audit(s);self.assertFalse(r['materialSourceComplete']);rows=s.page(r['auditId'],page_size=50)['items'];self.assertTrue(all(row['missingSlots'] is None for row in rows));self.assertFalse(r['materialGapSkuIds'])
 def test_end_product_or_sku_census_change_and_card_change_invalidate_complete(self):
  for fault in ('product-drift','sku-drift','card-drift'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.fault=fault;r=self.run_audit(s);self.assertFalse(r['complete']);self.assertTrue(r['reasons']);self.assertFalse(c.posts)
 def test_shop_switch_and_sensitive_response_refuse_capture(self):
  for fault in ('shop-drift','private'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);c.fault=fault
    with self.assertRaises(SafetyError):self.run_audit(s)
    self.assertFalse(list((Path(d)/'shop-material-audits').glob('*.json')));self.assertFalse(c.posts)
 def test_budget_exhaustion_refuses_not_complete_truncated_shop(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d)
   for options in ({'max_products':1},{'max_skus':2}):
    with self.assertRaises(SafetyError):self.run_audit(s,**options)
 def test_health_linkage_mismatch_never_assigns_wrong_product_score(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.health[0]['productId']=99;r=self.run_audit(s);self.assertFalse(r['complete']);self.assertNotIn('101',r['lowScoreSkuIds'])
 def test_reordered_pages_accepted_and_capture_pagination_has_full_totals(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.fault='reorder';r=self.run_audit(s);self.assertTrue(r['complete']);a=s.page(r['auditId'],page_size=2);b=s.page(r['auditId'],page=2,page_size=2);self.assertEqual(a['total'],6);self.assertEqual(len(a['items']),2);self.assertFalse(a['pageIsWholeShop']);self.assertFalse({x['skuId'] for x in a['items']}&{x['skuId'] for x in b['items']});self.assertEqual(s.status(r['auditId'])['onSaleSkuCount'],6)
 def test_capture_hash_detects_persisted_business_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);r=self.run_audit(s);path=s.path(r['auditId']);raw=read_json(path);raw['scope']['items'][0]['skuId']='999';atomic_json(path,raw)
   with self.assertRaises(SafetyError):s.status(r['auditId'])
 def test_large_8191_on_sale_and_all_offline_siblings_no_1000_truncation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d,8191);r=self.run_audit(s);self.assertTrue(r['complete']);self.assertEqual(r['onSaleSkuCount'],8191);self.assertEqual(r['allSiblingSkuCount'],8200);self.assertEqual(r['lowScoreSkuCount'],8190);self.assertEqual(r['materialObservedSkuCount'],8200);self.assertEqual(len(r['unscoredSkuIds']),1);self.assertFalse(c.posts)

 def test_unavailable_or_unrequested_health_is_unobserved_not_missing_or_zero(self):
  for requested in (True,False):
   with self.subTest(requested=requested),tempfile.TemporaryDirectory() as d:
    c,s=self.make(d);original=c.invoke
    def invoke(p,url,**kw):
     if url==HEALTH:raise SafetyError('synthetic health permission unavailable')
     return original(p,url,**kw)
    c.invoke=invoke;r=self.run_audit(s,include_health=requested);self.assertFalse(r['unscoredSkuIds']);rows=s.page(r['auditId'])['items'];self.assertTrue(all(row['scoreDecimal'] is None for row in rows));self.assertTrue(all(row['scoreState'] in ('unobserved','not-requested') for row in rows));self.assertEqual(r['complete'],not requested)
 def test_empty_on_sale_shop_has_no_downstream_reads_or_false_blocker(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.products=[];original=c.invoke
   def invoke(p,url,**kw):
    if url!=PRODUCTS:raise AssertionError('empty inventory must not read unrelated health/material data')
    return original(p,url,**kw)
   c.invoke=invoke;r=self.run_audit(s);self.assertTrue(r['complete']);self.assertEqual(r['onSaleSkuCount'],0);self.assertFalse(c.posts)
 def test_nonfinite_raw_source_refuses_safely_without_invalid_json_capture(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.health[0]['healthScore']=float('nan')
   with self.assertRaises(SafetyError):self.run_audit(s)
   self.assertFalse(list((Path(d)/'shop-material-audits').glob('*.json')))


 def test_audit_holds_install_lease_and_releases_it_after_collection(self):
  from heideng_merchant.state import FileLock
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);original=c.invoke;probes=[]
   def invoke(p,url,**kw):
    if url==PRODUCTS:
     try:
      with FileLock(Path(d)/'install.lock',timeout=.01):pass
     except SafetyError:probes.append(True)
     else:probes.append(False)
    return original(p,url,**kw)
   c.invoke=invoke;r=self.run_audit(s);self.assertTrue(r['complete']);self.assertTrue(probes);self.assertTrue(all(probes),'audit did not hold immutable-code install lease')
   with FileLock(Path(d)/'install.lock',timeout=.01):pass
 def test_foreign_parent_health_advice_is_not_attributed_to_local_sku(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);c.health[0]['productId']=99;r=self.run_audit(s);row=next(x for x in s.page(r['auditId'])['items'] if x['skuId']=='101');self.assertNotIn('101',r['shortTitleIssueSkuIds']);self.assertIsNone(row['improvementList']);self.assertIsNone(row['healthScoreRaw']);self.assertIsNone(row['shortTitleIssue']);self.assertEqual(s.record(r['auditId'])['scope']['sources']['health']['items'][0]['productId'],99)
 def test_partial_census_cannot_prove_health_rows_outside_current_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);original=c.invoke
   def invoke(p,url,**kw):
    if url==SKUS and int(kw['params']['productIdList'])==9:raise SafetyError('synthetic unavailable product siblings')
    return original(p,url,**kw)
   c.invoke=invoke;r=self.run_audit(s);self.assertFalse(r['complete']);self.assertIsNone(r['healthOutsideCurrentCatalogSkuIds']);self.assertFalse(r['outsideClassificationProven']);self.assertIn('101',r['healthUnmatchedObservedSkuIds'])
 def test_default_page_does_not_claim_complete_offline_sibling_capture(self):
  with tempfile.TemporaryDirectory() as d:
   c,s=self.make(d);r=self.run_audit(s);page=s.page(r['auditId']);self.assertEqual(page['total'],6);self.assertFalse(page['pageIsWholeShop']);self.assertTrue(page['pageIsWholeSelection']);whole=s.page(r['auditId'],include_offline=True);self.assertEqual(whole['total'],7);self.assertTrue(whole['pageIsWholeShop'])

if __name__=='__main__':unittest.main()
