import copy,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.products import ProductService
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError

class ProductClient:
 def __init__(self):
  self.calls=[];self.other=False;self.pending='20.00';self.online='29.90';self.unknown=False;self.page_repeat=False
  self.detail={'productId':100,'categoryDTO':{'lastCategoryId':456},'productInfo':{'productId':100,'productTitle':{'title':'test-product'}},'skuList':[{'skuId':2001,'productId':100,'priceInfo':{'jdPrice':'29.9000'}},{'skuId':2002,'productId':100,'priceInfo':{'jdPrice':'35.00'}}]}
 def identity(self,profile):return {'venderId':'2' if self.other else '1','shopId':'3','shopName':'mock-shop','shopType':'POP'}
 def invoke(self,profile,url,**kw):
  self.calls.append((profile,url,kw));method=kw.get('method','GET')
  if method=='PATCH':
   if self.unknown:raise TimeoutError('synthetic-only')
   return {'success':True,'data':{'id':'100'}}
  if '/product-apply/' in url:return {'data':{'productInfo':{'productId':100},'skuList':[{'skuId':2001,'priceInfo':{'jdPrice':self.pending}}],'applyInfo':{'bossAuditStatus':-1}}}
  if '{productId}' in url:
   data=copy.deepcopy(self.detail);data['skuList'][0]['priceInfo']['jdPrice']=self.online;return {'data':data}
  page=kw['params']['page'];ident=1 if self.page_repeat else page
  if page<=2:return {'data':[{'productId':ident,'productName':'item-'+str(ident)}],'paginationData':{'totalItems':2}}
  return {'data':[],'paginationData':{'totalItems':2}}

class ProductTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.client=ProductClient();self.ops=Operations(Path(self.tmp.name),self.client);self.ops.connect('merchant-demo','mock-shop','1');self.service=ProductService(Path(self.tmp.name),self.client)
 def tearDown(self):self.tmp.cleanup()
 def plan(self):return self.service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'}])
 def test_native_pop_patch_plan_is_flat_and_binds_old_pending_and_online_values(self):
  plan=self.plan();task=plan['task'];op=task['scope']['operation'];body=op['body']
  self.assertEqual(op['method'],'PATCH');self.assertEqual(op['url'],'/rest/sp-product/v0/product-applies/{applyId}');self.assertEqual(body['applyId'],'100');self.assertEqual(body['productApplyDTO']['id'],'100');self.assertEqual(body['productInfo'],{'productId':100,'categoryDetail':{'lastCategoryId':456}})
  self.assertEqual(body['opType'],3);self.assertEqual(body['scene'],'pop');self.assertNotIn('request',body)
  component=body['patchOperationList'][0];self.assertEqual(component['path'],'skus[skuId==2001]');self.assertEqual(json.loads(component['value']),{'componentCode':'SkuJdprice','value':'20.00'})
  self.assertEqual(plan['preview'][0]['oldJdPrice'],'29.90');self.assertTrue(plan['requiresApproval']);self.assertIn('precondition',task['scope']);self.assertIn('onlineVerification',task['scope']);self.assertTrue(all(k[2]['method']=='GET' for k in self.client.calls))
 def test_unknown_foreign_or_duplicate_sku_and_missing_category_never_prepare_write(self):
  for changes in ([{'skuId':'999','jdPrice':'20'}],[{'skuId':'2001','jdPrice':'20'},{'skuId':2001,'jdPrice':'21'}],[{'skuId':'2001','handPrice':'20'}]):
   with self.assertRaises(SafetyError):self.service.prepare_price('merchant-demo','100',changes)
  self.client.detail['categoryDTO']={}
  with self.assertRaises(SafetyError):self.plan()
  self.assertFalse(any(call[2].get('method')=='PATCH' for call in self.client.calls))
 def test_fractional_precision_and_mismatched_explicit_old_price_are_rejected(self):
  for amount in ('NaN','20.001',True,'0','-1'):
   with self.assertRaises(SafetyError):self.service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':amount}])
  with self.assertRaises(SafetyError):self.service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20','expectedOldPrice':'30'}])
 def test_already_desired_price_is_noop_with_no_write_task(self):
  result=self.service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'29.90'}]);self.assertEqual(result['phase'],'already-current');self.assertFalse(result['requiresApproval']);self.assertIsNone(result['task'])
 def test_stale_approval_fails_before_native_patch(self):
  plan=self.plan();task=plan['task'];self.ops.approve(task['taskId'],task['fingerprint'],confirmed=True);self.client.online='31.00'
  with self.assertRaises(SafetyError):self.ops.execute(task['taskId'])
  self.assertFalse(any(k[2].get('method')=='PATCH' for k in self.client.calls))
 def test_pending_minus_one_is_not_online_effect_and_polling_never_resubmits(self):
  plan=self.plan();task=plan['task'];self.ops.approve(task['taskId'],task['fingerprint'],confirmed=True);self.ops.execute(task['taskId'])
  pending=self.service.price_status(task['taskId'],refresh='pending');self.assertEqual(pending['phase'],'application-values-confirmed');self.assertFalse(pending['onlineEffective']);self.assertEqual(pending['bossAuditStatus'],-1)
  old=self.service.price_status(task['taskId'],refresh='online');self.assertFalse(old['onlineEffective']);self.client.online='20.00';new=self.service.price_status(task['taskId'],refresh='online');self.assertTrue(new['onlineEffective']);self.assertEqual(new['phase'],'online-values-confirmed')
  self.assertEqual(sum(k[2].get('method')=='PATCH' for k in self.client.calls),1)
 def test_unknown_matching_pending_or_online_values_keeps_original_unknown(self):
  task=self.plan()['task'];self.ops.approve(task['taskId'],task['fingerprint'],confirmed=True);self.client.unknown=True;self.ops.execute(task['taskId']);self.client.online='20.00'
  self.assertEqual(self.service.price_status(task['taskId'],refresh='pending')['phase'],'unknown');self.assertEqual(self.service.price_status(task['taskId'],refresh='online')['phase'],'unknown')
 def test_product_pagination_and_identity_are_complete_without_cached_read_tasks(self):
  r=self.service.list_products('merchant-demo',page_size=1,max_pages=5);self.assertEqual([p['productId'] for p in r['items']],[1,2]);self.assertTrue(r['complete']);self.assertIsNone(r['nextPage']);self.assertEqual(self.client.calls[0][2]['params']['scopeSet'],['productId','productName','productStatus'])
  self.client.calls.clear();self.service.list_products('merchant-demo',page_size=1,max_pages=5);self.assertEqual(len(self.client.calls),2)
 def test_truncated_or_repeated_page_is_explicitly_partial(self):
  r=self.service.list_products('merchant-demo',page_size=1,max_pages=1);self.assertFalse(r['complete']);self.assertEqual(r['nextPage'],2)
  self.client.page_repeat=True;r=self.service.list_products('merchant-demo',page_size=1,max_pages=5);self.assertFalse(r['complete']);self.assertEqual(len(r['items']),1);self.assertEqual(r['reason'],'pagination-identity-repeat')

if __name__=='__main__':unittest.main()

class ProductBoundaryTests(unittest.TestCase):
 def make(self,d):
  client=ProductClient();ops=Operations(Path(d),client);ops.connect('merchant-demo','mock-shop','1');return ProductService(Path(d),client),client,ops
 def test_nested_pagination_total_cannot_hide_missing_products(self):
  with tempfile.TemporaryDirectory() as d:
   service,client,ops=self.make(d);original=client.invoke
   def nested(*a,**kw):result=original(*a,**kw);return {'data':result}
   client.invoke=nested;result=service.list_products('merchant-demo',page_size=20,max_pages=5);self.assertEqual(len(result['items']),2);self.assertTrue(result['complete'])
 def test_resumed_page_segment_is_not_claimed_as_complete_shop_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   service,client,ops=self.make(d);result=service.list_products('merchant-demo',page_size=1,start_page=2,max_pages=5);self.assertFalse(result['complete']);self.assertTrue(result['segmentComplete']);self.assertEqual([r['productId'] for r in result['items']],[2])
 def test_category_change_after_approval_is_blocked_before_patch(self):
  with tempfile.TemporaryDirectory() as d:
   service,client,ops=self.make(d);task=service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'}])['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);client.detail['categoryDTO']['lastCategoryId']=789
   with self.assertRaises(SafetyError):ops.execute(task['taskId'])
   self.assertFalse(any(c[2].get('method')=='PATCH' for c in client.calls))
 def test_requested_unchanged_sku_is_still_part_of_final_online_goal(self):
  with tempfile.TemporaryDirectory() as d:
   service,client,ops=self.make(d);task=service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'},{'skuId':'2002','jdPrice':'35.00'}])['task']
   self.assertIn('skuList[skuId==2002].priceInfo.jdPrice',task['scope']['onlineVerification']['expected']);self.assertIn('skuList[skuId==2002].priceInfo.jdPrice',task['scope']['precondition']['expected']);self.assertEqual(len(task['scope']['operation']['body']['patchOperationList']),1)
 def test_actual_sku_and_health_pages_use_current_merchant_scope(self):
  with tempfile.TemporaryDirectory() as d:
   service,client,ops=self.make(d)
   def rows(profile,url,**kw):
    client.calls.append((profile,url,kw));page=kw['params']['page'];return {'data':[{'skuId':2000+page,'productId':100,'healthScore':70}],'paginationData':{'totalItems':2}}
   client.invoke=rows
   skus=service.list_skus('merchant-demo','100',page_size=1,max_pages=5);self.assertTrue(skus['complete']);self.assertEqual(len(skus['items']),2);self.assertEqual(client.calls[0][2]['params']['productIdList'],'100')
   health=service.list_health('merchant-demo',page_size=1,max_pages=5);self.assertTrue(health['complete']);self.assertEqual(client.calls[-1][1],'/rest/sp-product/v0/health-infos')

class PriceRefreshTests(unittest.TestCase):
 def test_explicit_pending_refresh_after_verification_queries_again(self):
  with tempfile.TemporaryDirectory() as d:
   client=ProductClient();ops=Operations(Path(d),client);ops.connect('merchant-demo','mock-shop','1');service=ProductService(Path(d),client);task=service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'}])['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId'])
   service.price_status(task['taskId'],refresh='pending');before=len(client.calls);client.pending='21.00';status=service.price_status(task['taskId'],refresh='pending');self.assertEqual(len(client.calls),before+1);self.assertFalse(status['pendingValuesMatch']);self.assertIsNotNone(status['pendingObservedAt'])
