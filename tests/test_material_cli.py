import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.cli import parser,run,main
from heideng_merchant.operations import Operations
from heideng_merchant.state import merchant_home
from tests import material_fixtures as fixtures

class MaterialCliTests(unittest.TestCase):
 def test_agent_upload_plan_and_result_readback_commands_use_same_scope(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c=fixtures.Client();state=merchant_home(d);ops=Operations(state,c);ops.connect('merchant-test','synthetic-store','1');p=Path(d)/'sample.png';p.write_bytes(fixtures.png())
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    plan=run(parser().parse_args(['--home',d,'material-upload-plan','--profile','merchant-test','--image',str(p),'--zone-id','img_test','--category-id','7']));task=plan['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);result=run(parser().parse_args(['--home',d,'material-upload-status','--task-id',task['taskId'],'--refresh']));self.assertTrue(result['storageVerified']);self.assertFalse(result['productBound'])
 def test_cli_never_prints_base64_even_when_showing_local_task_scope(self):
  import base64,contextlib,io
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.materials.probe_image',side_effect=fixtures.probe),patch('heideng_merchant.operations.probe_image',side_effect=fixtures.probe):
   c=fixtures.Client();ops=Operations(merchant_home(d),c);ops.connect('merchant-test','synthetic-store','1');p=Path(d)/'sample.png';p.write_bytes(fixtures.png());stdout=io.StringIO()
   with patch('heideng_merchant.cli.OfficialClient',return_value=c),contextlib.redirect_stdout(stdout):code=main(['--home',d,'material-upload-plan','--profile','merchant-test','--image',str(p),'--zone-id','img_test','--category-id','7'])
   self.assertEqual(code,0);self.assertTrue(base64.b64encode(fixtures.png()).decode() not in stdout.getvalue(),'base64 was printed');data=json.loads(stdout.getvalue());self.assertEqual(data['task']['scope']['body'] if 'body' in data['task']['scope'] else data['task']['scope']['operation']['body']['imgBase64']['omitted'],True)

if __name__=='__main__':unittest.main()
