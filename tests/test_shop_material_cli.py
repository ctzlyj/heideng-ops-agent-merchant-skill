import tempfile,unittest
from unittest.mock import patch
from heideng_merchant.cli import parser,run
from heideng_merchant.operations import Operations
from heideng_merchant.state import merchant_home
from tests.test_shop_material_audit import ShopClient

class ShopAuditCliTests(unittest.TestCase):
 def test_agent_full_shop_summary_and_paged_source_commands(self):
  with tempfile.TemporaryDirectory() as d:
   c=ShopClient();ops=Operations(merchant_home(d),c);ops.connect('merchant-test','synthetic-store','1')
   def command(*args):return run(parser().parse_args(['--home',d,*args]))
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    r=command('sku-material-shop-audit','--profile','merchant-test');self.assertTrue(r['complete']);self.assertTrue(r['summaryOnly']);self.assertEqual(r['onSaleSkuCount'],6);self.assertFalse(any(key.endswith('Ids') for key in r));page=command('sku-material-shop-rows','--audit-id',r['auditId'],'--page-size','2','--only','gaps');self.assertEqual(len(page['items']),2);self.assertFalse(page['pageIsWholeShop']);status=command('sku-material-shop-status','--audit-id',r['auditId']);self.assertEqual(status['auditId'],r['auditId']);self.assertFalse(c.posts)
 def test_large_shop_summary_is_not_thousands_of_ids_in_tool_output(self):
  with tempfile.TemporaryDirectory() as d:
   c=ShopClient(8191);Operations(merchant_home(d),c).connect('merchant-test','synthetic-store','1')
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):r=run(parser().parse_args(['--home',d,'sku-material-shop-audit','--profile','merchant-test']))
   self.assertEqual(r['onSaleSkuCount'],8191);self.assertEqual(r['lowScoreSkuCount'],8190);self.assertEqual(r['unscoredSkuCount'],1);self.assertTrue(r['summaryOnly']);self.assertFalse(any(key.endswith('Ids') for key in r))

if __name__=='__main__':unittest.main()
