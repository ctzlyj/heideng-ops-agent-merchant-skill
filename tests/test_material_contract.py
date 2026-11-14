import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError
from tests import material_fixtures as fixtures

class MaterialContractTests(unittest.TestCase):
 def make(self,d):
  c=fixtures.Client();ops=Operations(Path(d),c);ops.connect('merchant-test','synthetic-store','1');op,verify=fixtures.upload_scope();return c,ops,op,verify
 def test_generic_upload_cannot_omit_or_substitute_result_verification(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op,verify=self.make(d)
   with self.assertRaises(SafetyError):ops.prepare('merchant-test',op)
   verify['query']['params']['zoneId']='img_foreign'
   with self.assertRaises(SafetyError):ops.prepare('merchant-test',op,result_verification=verify)
   self.assertEqual(c.calls,[])
 def test_original_image_and_native_zone_category_proof_enter_scope(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c,ops,op,verify=self.make(d);task=ops.prepare('merchant-test',op,result_verification=verify);self.assertEqual(task['scope']['materialUpload']['image'],fixtures.probe(None,fixtures.png()));self.assertTrue(task['materialPlanningEvidence']['categoryChecked']);self.assertFalse(any(kw.get('method')=='POST' for url,kw in c.calls))
 def test_wrong_zone_category_or_changed_category_prevents_any_upload(self):
  for kind in ('zone','category','after-approval'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d,patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
    c,ops,op,verify=self.make(d)
    if kind=='zone':c.zones=[]
    elif kind=='category':c.categories=[]
    if kind=='after-approval':
     task=ops.prepare('merchant-test',op,result_verification=verify);ops.approve(task['taskId'],task['fingerprint'],confirmed=True);c.categories[0]['status']=0
     with self.assertRaises(SafetyError):ops.execute(task['taskId'])
    else:
     with self.assertRaises(SafetyError):ops.prepare('merchant-test',op,result_verification=verify)
    self.assertFalse(any(kw.get('method')=='POST' for url,kw in c.calls))
 def test_bad_base64_wrapper_or_fileurl_cannot_use_native_upload_route(self):
  for body in ({'postMediaZoneImageRequest':{}},{'fileUrl':'https://example.invalid/image.png','zoneImageDTO':{'imgName':'sample.png','categoryId':7}},{'imgBase64':'data:image/png;base64,AAAA','zoneImageDTO':{'imgName':'sample.png','categoryId':7}}):
   with self.subTest(kind=list(body)),tempfile.TemporaryDirectory() as d:
    c,ops,op,verify=self.make(d);op['body']=body
    with self.assertRaises(SafetyError):ops.prepare('merchant-test',op,result_verification=verify)
    self.assertEqual(c.calls,[])
 def test_known_receipt_is_verified_by_same_image_id_and_url_without_binding_product(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c,ops,op,verify=self.make(d);task=ops.prepare('merchant-test',op,result_verification=verify);ops.approve(task['taskId'],task['fingerprint'],confirmed=True);self.assertEqual(ops.execute(task['taskId'])['status'],'submitted');c.images[0]['imgUrl']='jfs/t1/foreign/other.png'
   with self.assertRaises(SafetyError):ops.verify_result(task['taskId'])
   self.assertEqual(ops.task(task['taskId'])['status'],'submitted');self.assertEqual(sum(kw.get('method')=='POST' for url,kw in c.calls),1)

if __name__=='__main__':unittest.main()
