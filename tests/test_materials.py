import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.operations import Operations
from heideng_merchant.materials import MaterialService
from heideng_merchant.safety import SafetyError
from tests import material_fixtures as fixtures

class MaterialTests(unittest.TestCase):
 def make(self,d):
  c=fixtures.Client();ops=Operations(Path(d),c);ops.connect('merchant-test','synthetic-store','1');p=Path(d)/'sample.png';p.write_bytes(fixtures.png());return c,ops,MaterialService(Path(d),c),p
 def test_native_spaces_categories_and_complete_image_pages(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,service,p=self.make(d);self.assertEqual(service.zones('merchant-test')['items'][0]['zoneId'],'img_test');c.categories.append({'categoryId':8,'status':1,'categoryName':'second'})
   result=service.categories('merchant-test','img_test',page_size=1,max_pages=3);self.assertTrue(result['complete']);self.assertEqual([r['categoryId'] for r in result['items']],[7,8]);self.assertEqual(len(result['sourcePageHashes']),2)
   resumed=service.categories('merchant-test','img_test',page_size=1,start_page=2,max_pages=3);self.assertFalse(resumed['complete']);self.assertTrue(resumed['segmentComplete'])
 def test_upload_and_readback_are_not_product_binding_or_visual_identity_proof(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c,ops,service,p=self.make(d);planned=service.prepare_upload('merchant-test',p,'img_test',7);task=planned['task'];self.assertTrue(planned['requiresApproval']);self.assertEqual(planned['image']['sha256'],fixtures.probe(None,fixtures.png())['sha256'])
   with self.assertRaises(SafetyError):ops.execute(task['taskId'])
   ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);status=service.upload_status(task['taskId'],refresh=True);self.assertTrue(status['storageVerified']);self.assertFalse(status['productBound']);self.assertFalse(status['remotePixelsVerified']);self.assertEqual(status['asset']['imgId'],'asset-1');self.assertEqual(sum(k.get('method')=='POST' for u,k in c.calls),1)
 def test_unknown_response_never_refreshes_by_filename_or_allows_next_write(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c,ops,service,p=self.make(d);task=service.prepare_upload('merchant-test',p,'img_test',7)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);c.unknown=True;ops.execute(task['taskId']);count=len(c.calls);status=service.upload_status(task['taskId'],refresh=True);self.assertEqual(status['phase'],'unknown');self.assertFalse(status['storageVerified']);self.assertEqual(len(c.calls),count)
   with self.assertRaises(SafetyError):service.prepare_upload('merchant-test',p,'img_test',7,name='other.png')
 def test_unknown_filters_or_cookie_strings_do_not_reach_native_arguments(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,service,p=self.make(d)
   for filters in ({'unknown':1},{'imgName':'eid=SYNTHETIC_PRIVATE'},{'categoryId':{'token':'synthetic'}}):
    with self.assertRaises(SafetyError):service.images('merchant-test','img_test',filters=filters)
   self.assertEqual(c.calls,[])
 def test_repeated_page_is_partial_without_dropping_original_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,service,p=self.make(d);original=c.invoke
   def repeat(profile,url,**kw):
    if url.endswith('/categories'):kw['params']['page']=1
    result=original(profile,url,**kw)
    if 'paginationData' in result:result['paginationData']['totalItems']=3
    return result
   c.invoke=repeat;data=service.categories('merchant-test','img_test',page_size=1,max_pages=3);self.assertFalse(data['complete']);self.assertEqual(len(data['items']),1);self.assertEqual(data['reason'],'pagination-identity-repeat')

if __name__=='__main__':unittest.main()
