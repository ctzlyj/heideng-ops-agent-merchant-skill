import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.cli import parser,run
from heideng_merchant.state import merchant_home
from heideng_merchant.operations import Operations
from tests import test_products as fixtures

class ProductCliTests(unittest.TestCase):
 def test_agent_native_product_reads_and_price_plan_use_same_scoped_client(self):
  with tempfile.TemporaryDirectory() as d:
   client=fixtures.ProductClient();state=merchant_home(d);Operations(state,client).connect('merchant-demo','mock-shop','1');source=Path(d)/'changes.json';source.write_text(json.dumps([{'skuId':'2001','jdPrice':'20.00'}]))
   with patch('heideng_merchant.cli.OfficialClient',return_value=client):
    data=run(parser().parse_args(['--home',d,'product-detail','--profile','merchant-demo','--product-id','100']));self.assertEqual(data['productId'],100)
    listing=run(parser().parse_args(['--home',d,'product-list','--profile','merchant-demo','--page-size','1','--max-pages','3']));self.assertTrue(listing['complete'])
    result=run(parser().parse_args(['--home',d,'price-plan','--profile','merchant-demo','--product-id','100','--changes',str(source)]));task=result['task'];self.assertTrue(result['requiresApproval'])
    Operations(state,client).approve(task['taskId'],task['fingerprint'],confirmed=True);Operations(state,client).execute(task['taskId'])
    status=run(parser().parse_args(['--home',d,'price-status','--task-id',task['taskId'],'--refresh','pending']));self.assertEqual(status['phase'],'application-values-confirmed');self.assertFalse(status['onlineEffective'])
    self.assertEqual(sum(call[2].get('method')=='PATCH' for call in client.calls),1)
 def test_task_plan_can_bind_precondition_and_online_query_from_files(self):
  with tempfile.TemporaryDirectory() as d:
   client=fixtures.ProductClient();Operations(merchant_home(d),client).connect('merchant-demo','mock-shop','1');root=Path(d)
   op={'url':'/rest/sp-product/v0/product-applies/100','method':'PATCH','body':{'testOnly':True}}
   evidence={'query':{'url':'/rest/sp-product/v0/products/100'},'expected':{'productId':'100'}}
   for name,value in [('op.json',op),('guard.json',evidence),('online.json',evidence)]: (root/name).write_text(json.dumps(value))
   with patch('heideng_merchant.cli.OfficialClient',return_value=client):result=run(parser().parse_args(['--home',d,'task-plan','--profile','merchant-demo','--operation',str(root/'op.json'),'--precondition',str(root/'guard.json'),'--online-verification',str(root/'online.json')]))
   self.assertIn('precondition',result['scope']);self.assertIn('onlineVerification',result['scope'])

if __name__=='__main__':unittest.main()
