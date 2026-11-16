"""Merchant-only mature Node diagnosis; offline plans and transport contract only."""
import json,os,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class MatureDiagnosisTests(unittest.TestCase):
 def test_real_readonly_cli_is_dispatched_from_selected_upstream(self):
  from heideng_merchant.mature_runtime import source_path
  path,meta=source_path('diagnosis')
  self.assertEqual(path,ROOT/'mature/diagnosis/scripts/cli.cjs')
  self.assertEqual(meta['upstreamCommit'],'42971c041248bab27f4d627357dcc475f848eb75')
 def test_dry_run_uses_original_scope_identity_and_no_network(self):
  script=ROOT/'mature/diagnosis/scripts/cli.cjs'
  result=subprocess.run(['node',str(script),'scan','--profile','fixture-profile','--shop-id','12345','--shop-name','fixture-shop','--scope','sample','--limit','1','--dry-run'],capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
  data=json.loads(result.stdout);self.assertTrue(data['readOnly']);self.assertTrue(data['planOnly']);self.assertEqual(data['shopId'],'12345')
 def test_source_does_not_include_employee_or_new_dispatch_runtime(self):
  base=ROOT/'mature/diagnosis';meta=json.loads((base/'provenance.json').read_text(encoding='utf-8'))
  self.assertNotIn('scripts/dispatch-cli.cjs',meta['files'])
  text='\n'.join((base/n).read_text(encoding='utf-8') for n in meta['files'] if n.endswith('.cjs'))
  self.assertNotIn('llm-gw',text);self.assertNotIn('JD_LLM_API_KEY',text)
if __name__=='__main__':unittest.main()
