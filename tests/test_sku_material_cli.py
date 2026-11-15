import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.cli import parser,run
from heideng_merchant.operations import Operations
from heideng_merchant.state import merchant_home
from tests.test_sku_materials import Client

class SkuMaterialCliTests(unittest.TestCase):
 def test_agent_commands_follow_one_plan_scope_approval_and_readback(self):
  with tempfile.TemporaryDirectory() as d:
   c=Client();ops=Operations(merchant_home(d),c);ops.connect('merchant-test','synthetic-store','1');changes=Path(d)/'changes.json';changes.write_text(json.dumps([{'skuId':101,'slot':'point1','text':'轻巧便携','review':'passed'}]),encoding='utf-8')
   def command(*args):return run(parser().parse_args(['--home',d,*args]))
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    report=command('sku-material-audit','--profile','merchant-test','--product-id','9','--include-health');self.assertEqual(report['skuCount'],3)
    p=command('sku-material-plan','--profile','merchant-test','--product-id','9','--changes',str(changes));command('sku-material-approve','--plan-id',p['planId'],'--fingerprint',p['fingerprint'],'--confirm');r=command('sku-material-execute','--plan-id',p['planId']);self.assertTrue(r['materialFieldsVerified']);self.assertFalse(r['auditApproved']);command('sku-material-status','--plan-id',p['planId'],'--refresh');self.assertEqual(len(c.posts),1)

if __name__=='__main__':unittest.main()
