import base64,contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.cli import main
from heideng_merchant.materials import MaterialService
from heideng_merchant.operations import Operations
from heideng_merchant.official_transport import publish_response
from heideng_merchant.safety import SafetyError
from heideng_merchant.state import merchant_home
from tests import material_fixtures as fixtures

class MaterialReviewTests(unittest.TestCase):
 def make(self,d):
  c=fixtures.Client();state=merchant_home(d);ops=Operations(state,c);ops.connect('merchant-test','synthetic-store','1');service=MaterialService(state,c);p=Path(d)/'sample.png';p.write_bytes(fixtures.png());return c,ops,service,p
 def test_json_string_receipt_echo_never_publishes_original_base64(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c,ops,service,p=self.make(d);task=service.prepare_upload('merchant-test',p,'img_test',7)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);original=c.invoke
   def echo(profile,url,**kw):
    response=original(profile,url,**kw)
    if kw.get('method')=='POST':response['data']['diagnostic']=json.dumps({'imgBase64':kw['body']['imgBase64']});response=publish_response(response,{'body':kw['body'],'params':kw['params']})
    return response
   c.invoke=echo;out=io.StringIO()
   with patch('heideng_merchant.cli.OfficialClient',return_value=c),contextlib.redirect_stdout(out):code=main(['--home',d,'task-execute','--task-id',task['taskId']])
   self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue())['status'],'submitted');self.assertTrue(base64.b64encode(fixtures.png()).decode() not in out.getvalue(),'encoded media escaped through JSON text')
 def test_missing_pagination_total_never_proves_a_short_page_complete(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,service,p=self.make(d);c.categories.append({'categoryId':8,'status':1,'categoryName':'second'});original=c.invoke
   def truncate(profile,url,**kw):
    response=original(profile,url,**kw)
    if url.endswith('/categories'):response.pop('paginationData',None);response['data']=response['data'][:1]
    return response
   c.invoke=truncate;result=service.categories('merchant-test','img_test',page_size=50,max_pages=3);self.assertFalse(result['complete']);self.assertFalse(result['segmentComplete']);self.assertEqual(result['reason'],'pagination-metadata-missing');self.assertEqual(result['nextPage'],1)
 def test_int64_category_is_allowed_only_when_native_owner_response_proves_it(self):
  for category in (0,-1):
   with self.subTest(category=category),tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
    c,ops,service,p=self.make(d);c.categories.insert(0,{'categoryId':category,'status':1,'categoryName':'native-returned'});rows=service.categories('merchant-test','img_test')['items'];self.assertEqual(rows[0]['categoryId'],category);task=service.prepare_upload('merchant-test',p,'img_test',category)['task'];self.assertEqual(task['scope']['operation']['body']['zoneImageDTO']['categoryId'],category)
   with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
    c,ops,service,p=self.make(d)
    with self.assertRaises(SafetyError):service.prepare_upload('merchant-test',p,'img_test',category)

if __name__=='__main__':unittest.main()
