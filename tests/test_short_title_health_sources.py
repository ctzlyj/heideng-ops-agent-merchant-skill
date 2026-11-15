"""Official native health detail contract; only synthetic clients and payloads."""
import copy,importlib,importlib.util,json,tempfile,unittest
from heideng_merchant.products import ProductService
from heideng_merchant.safety import SafetyError
from tests import test_short_titles as fixture

DETAIL='/rest/sp-product/v0/health-infos/{healthInfoId}'
class NativeHealthSourceTests(unittest.TestCase):
 def data(self):
  return {'skuId':101,'productId':11,'healthScoreId':101,'healthScore':99,'improvementList':[]}
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.short_title_health_sources'),'native complete health-source projection is absent')
  return importlib.import_module('heideng_merchant.short_title_health_sources')
 def read(self,reader,profile,sku):
  self.assertTrue(callable(getattr(reader,'health_detail',None)),'official health detail route is absent')
  return reader.health_detail(profile,sku)
 def make(self,d,data):
  c,s,a=fixture.ShortTitlePlansTests().make(d);calls=[];invoke=c.invoke
  def call(profile,url,**kw):
   if url==DETAIL:
    calls.append((profile,url,kw));return {'code':200,'data':copy.deepcopy(data)}
   return invoke(profile,url,**kw)
  c.invoke=call;return c,ProductService(d,c),calls
 def test_exact_documented_route_params_and_merchant_profile_no_filters(self):
  with tempfile.TemporaryDirectory() as d:
   c,reader,calls=self.make(d,self.data());out=self.read(reader,'merchant-test','101');self.assertEqual(out,self.data())
   self.assertEqual(calls,[('merchant-test',DETAIL,{'method':'GET','params':{'healthInfoId':101},'skill_id':'jdo-product-price'})]);self.assertFalse(c.posts)
 def test_detail_rejects_wrong_sku_health_id_shape_and_business_failure(self):
  for patch in ({'skuId':102},{'skuId':True},{'healthScoreId':102},{'productId':None}):
   with self.subTest(patch=patch),tempfile.TemporaryDirectory() as d:
    c,reader,calls=self.make(d,{**self.data(),**patch})
    with self.assertRaises(SafetyError):self.read(reader,'merchant-test','101')
 def test_projection_checks_original_product_and_never_substitutes_unknown_fields(self):
  m=self.module();value=m.project_detail(self.data(),'11','101')
  self.assertTrue(value['scoreObserved']);self.assertTrue(value['issuesObserved']);self.assertEqual(value['healthTitleIssue'],False);self.assertEqual(value['healthScore'],99)
  with self.assertRaises(SafetyError):m.project_detail({**self.data(),'productId':12},'11','101')
  for patch in ({'healthScore':None},{'healthScore':True},{'healthScore':'99'},{'healthScore':0},{'improvementList':None},{'improvementList':[{'improvementDetail':{}}]}):
   with self.subTest(patch=str(patch)):
    result=m.project_detail({**self.data(),**patch},'11','101');self.assertFalse(result['scoreObserved'] and result['issuesObserved'])
  with self.assertRaises(SafetyError):m.project_detail({**self.data(),'healthScore':float('nan')},'11','101')
 def test_signed_source_data_is_hashed_but_never_returned_or_fetched(self):
  m=self.module();data={**self.data(),'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle','sourceData':'https://storage.jd.com/synthetic.xlsx?token=SYNTHETIC_ONLY'}}]}
  out=m.project_detail(data,'11','101');self.assertTrue(out['healthTitleIssue']);self.assertEqual(out['troubleCodes'],['hasShortTitle']);self.assertNotIn('SYNTHETIC_ONLY',json.dumps(out));self.assertNotIn('https://',json.dumps(out));self.assertRegex(out['detailSha256'],'^[0-9a-f]{64}$')
 def test_native_sku_and_health_id_cannot_be_inferred_from_a_name_or_score(self):
  m=self.module()
  for field in ('skuId','productId','healthScoreId'):
   data=self.data();data.pop(field)
   if field=='healthScoreId':
    # Native endpoint already binds SKU. Optional echoed health ID is never invented.
    out=m.project_detail(data,'11','101');self.assertIsNone(out['healthScoreId'])
   else:
    with self.assertRaises(SafetyError):m.project_detail(data,'11','101')

 def test_only_documented_signed_source_data_url_can_be_exempted_from_privacy_gate(self):
  m=self.module()
  for extra in ({'access_token':'SYNTHETIC_ONLY'}, {'other':{'cookie':'SYNTHETIC_ONLY'}}):
   data={**self.data(),**extra}
   with self.subTest(extra=extra),self.assertRaises(SafetyError):m.project_detail(data,'11','101')
  data={**self.data(),'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle','sourceData':'Bearer SYNTHETIC_ONLY_DO_NOT_ALLOW_SECRET'}}]}
  with self.assertRaises(SafetyError):m.project_detail(data,'11','101')
