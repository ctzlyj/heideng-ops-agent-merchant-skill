import copy,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.operations import Operations
from heideng_merchant.products import ProductService
from heideng_merchant.safety import SafetyError,redact
from heideng_merchant.official import OfficialClient
from unittest.mock import patch
from tests import test_products as fixtures

class ProductReviewTests(unittest.TestCase):
 def make(self,d):
  client=fixtures.ProductClient();ops=Operations(Path(d),client);ops.connect('merchant-demo','mock-shop','1');return client,ops,ProductService(Path(d),client)
 def test_generic_price_patch_cannot_omit_native_evidence_bindings(self):
  with tempfile.TemporaryDirectory() as d:
   client,ops,service=self.make(d);op={'url':'/rest/sp-product/v0/product-applies/{applyId}','method':'PATCH','params':{'applyId':'100'},'skillId':'jdo-product-update','body':{'applyId':'100','opType':3,'scene':'pop','productInfo':{'productId':100,'categoryDetail':{'lastCategoryId':456}},'productApplyDTO':{'id':'100'},'patchOperationList':[{'path':'skus[skuId==2001]','value':json.dumps({'componentCode':'SkuJdprice','value':'20.00'})}]}}
   with self.assertRaises(SafetyError):ops.prepare('merchant-demo',op)
   self.assertEqual(client.calls,[])
 def test_full_native_consistency_is_rechecked_not_just_chosen_paths(self):
  for kind in ('foreign-sku','duplicate-unrelated','conflicting-category'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    client,ops,service=self.make(d);task=service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'}])['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True)
    if kind=='foreign-sku':client.detail['skuList'][0]['productId']=999
    elif kind=='duplicate-unrelated':client.detail['skuList'].append(copy.deepcopy(client.detail['skuList'][1]))
    else:client.detail['categoryDetail']={'lastCategoryId':999}
    with self.assertRaises(SafetyError):ops.execute(task['taskId'])
    self.assertFalse(any(call[2].get('method')=='PATCH' for call in client.calls))
 def test_unknown_query_fields_and_cookie_aliases_do_not_reach_arguments(self):
  with tempfile.TemporaryDirectory() as d:
   client,ops,service=self.make(d)
   for filters in ({'pt_key':'synthetic-private'}, {'unknownField':'synthetic-private'},{'productName':{'pt_key':'synthetic-private'}}):
    with self.assertRaises(SafetyError):service.list_products('merchant-demo',filters=filters)
   self.assertEqual(client.calls,[])
 def test_sensitive_json_filter_values_are_rejected_before_invoke(self):
  aliases=('eid','fp','signature','thor','pt_key','pt_pin','deviceId','sso_ticket','tgt')
  with tempfile.TemporaryDirectory() as d:
   client,ops,service=self.make(d)
   for alias in aliases:
    for key in (alias,'raw_'+alias+'_value'):
     with self.subTest(key=key):
      filters={'productName':json.dumps({key:'SYNTHETIC_ONLY'})}
      with self.assertRaises(SafetyError):service.list_products('merchant-demo',filters=filters)
   self.assertEqual(client.calls,[])
 def test_sensitive_json_business_values_are_rejected_before_argv(self):
  with tempfile.TemporaryDirectory() as d:
   client=OfficialClient(Path(d))
   with patch.object(client,'_run') as run:
    for alias in ('eid','fp','signature'):
     for value in (json.dumps({alias:'SYNTHETIC_ONLY'}),alias+'=SYNTHETIC_ONLY',json.dumps({alias:'SYNTHETIC_ONLY'}).replace(alias,''.join('\\u%04x'%ord(c) for c in alias))):
      with self.subTest(alias=alias,value_kind=value[:10]):
       with self.assertRaises(SafetyError):client.invoke('merchant-demo','/rest/sp-product/v0/products',params={'productName':value})
    run.assert_not_called()
 def test_sensitive_dictionary_and_text_alias_coverage_is_shared(self):
  for alias in ('authorization','token','cookie','api_key','secret','password','credential','pt_key','pt-pin','thor','eid','fp','sso_ticket','tgt','device_id','deviceId','signature'):
   with self.subTest(alias=alias):
    self.assertNotIn('SYNTHETIC_ONLY',str(redact({alias:'SYNTHETIC_ONLY'})))
    self.assertNotIn('SYNTHETIC_ONLY',redact(json.dumps({alias:'SYNTHETIC_ONLY'})))
    self.assertNotIn('SYNTHETIC_ONLY',redact('failed: '+alias+'=SYNTHETIC_ONLY'))
 def test_foreign_pending_product_never_verifies_or_unlocks_second_write(self):
  with tempfile.TemporaryDirectory() as d:
   client,ops,service=self.make(d);task=service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'20.00'}])['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);original=client.invoke
   def foreign(profile,url,**kw):
    result=original(profile,url,**kw)
    if '/product-apply/' in url:result['data']['productInfo']['productId']=999
    return result
   client.invoke=foreign
   with self.assertRaises(SafetyError):service.price_status(task['taskId'],refresh='pending')
   self.assertEqual(ops.task(task['taskId'])['status'],'submitted')
   with self.assertRaises(SafetyError):service.prepare_price('merchant-demo','100',[{'skuId':'2001','jdPrice':'21.00'}])
   self.assertEqual(sum(call[2].get('method')=='PATCH' for call in client.calls),1)

if __name__=='__main__':unittest.main()
