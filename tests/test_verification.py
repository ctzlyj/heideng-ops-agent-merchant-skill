import unittest
from heideng_merchant.verification import business_payload,matches_fields,validate_expected
from heideng_merchant.safety import SafetyError

class VerificationTests(unittest.TestCase):
 def test_matches_exact_sku_decimal_in_nested_official_payload(self):
  payload={'skuList':[{'skuId':1,'priceInfo':{'jdPrice':'99.8800'}},{'skuId':2,'priceInfo':{'jdPrice':'1.00'}}]}
  self.assertTrue(matches_fields(payload,{'skuList[skuId==1].priceInfo.jdPrice':{'$decimal':'99.88'}}))
  self.assertFalse(matches_fields(payload,{'skuList[skuId==2].priceInfo.jdPrice':{'$decimal':'99.88'}}))
 def test_missing_fields_and_ambiguous_sku_never_verify(self):
  self.assertFalse(matches_fields({}, {'field':None}))
  payload={'skuList':[{'skuId':'1','priceInfo':{'jdPrice':10}},{'skuId':'1','priceInfo':{'jdPrice':10}}]}
  self.assertFalse(matches_fields(payload,{'skuList[skuId==1].priceInfo.jdPrice':{'$decimal':'10'}}))
 def test_unwraps_only_business_envelopes_and_rejects_application_errors(self):
  self.assertEqual(business_payload({'data':{'data':{'skuList':[]},'errorList':[]}}),{'skuList':[]})
  for value in [{'errorList':[{'code':'denied'}],'data':{'skuList':[]}},{'data':{'success':False,'data':{'skuList':[]}}}]:
   with self.assertRaises(SafetyError):business_payload(value)
 def test_expected_selectors_and_decimal_literals_are_validated_before_execution(self):
  for expected in [{'skuList[skuId==1 or 2].priceInfo.jdPrice':1},{'a':{'$decimal':'NaN'}},{'a':{'$decimal':'Infinity'}},{'a':{'$decimal':True}},{'a':{'$regex':'.*'}}]:
   with self.assertRaises(SafetyError):validate_expected(expected)

if __name__=='__main__':unittest.main()
