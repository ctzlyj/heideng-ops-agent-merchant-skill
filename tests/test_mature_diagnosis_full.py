"""True internal-dispatched diagnosis source; only local fixtures/plan validation."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'mature/diagnosis'
def module(path):
 spec=importlib.util.spec_from_file_location('merchant_diagnosis_plans',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class MatureFullDiagnosisTests(unittest.TestCase):
 def test_bundle_is_actual_internal_dispatched_full_source(self):
  from heideng_merchant.mature_runtime import source_path
  _,meta=source_path('diagnosis')
  self.assertEqual(meta['repository'],'ctzlyj/jd-store-diagnosis-skill')
  self.assertEqual(meta['upstreamCommit'],'42971c041248bab27f4d627357dcc475f848eb75')
  self.assertEqual(meta['upstreamVersion'],'0.2.0')
  for name in ('scripts/make_plans.py','scripts/jzt-run.js','scripts/sz-fetch.js','scripts/validate_report.py'):self.assertIn(name,meta['entrypoints'])
 def test_original_plans_preserve_ad_metrics_and_attribution(self):
  m=module(SOURCE/'scripts/make_plans.py')
  cfg={'start_date':'2026-09-01','end_date':'2026-09-30','compare_start':'2026-08-01','compare_end':'2026-08-31','pin_id':'fixture-ad-account','cid2':123,'cid3':456,'top_sku_ids':[100001]}
  ads=m.build_jzt_report_plan(cfg)
  self.assertGreaterEqual(len(ads),5)
  self.assertIn('totalOrderROI',ads[0]['body']['columns'])
  self.assertEqual(ads[0]['body']['pinIds'],['fixture-ad-account'])
  self.assertEqual(ads[0]['body']['clickOrOrderDay'],30)
  self.assertTrue(m.build_sz_plan(cfg))
 def test_cdp_does_not_borrow_default_work_browser(self):
  code="const assert=require('node:assert');const {Cdp}=require(process.argv[1]);global.fetch=()=>{throw Error('NETWORK_MUST_NOT_RUN')};assert.rejects(Cdp.connect('http://127.0.0.1:9224'),/merchant-browser-session-required/).catch(e=>{console.error(e.message);process.exit(1)})"
  result=subprocess.run(['node','-e',code,str(SOURCE/'scripts/cdp-lib.js')],capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
 def test_readonly_plan_boundary_and_response_redaction(self):
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);profile=state/'browser-profiles'/'fixture';profile.mkdir(parents=True)
   cfg=state/'browser.json';cfg.write_text(json.dumps({'owned':True,'isolated':True,'contextId':'fixture-context','identity':{'shopName':'fixture','venderId':'12345'},'profileDir':str(profile),'cdpEndpoint':'http://127.0.0.1:9321','jztPinId':'fixture-account'}))
   code="""const assert=require('node:assert');const b=require(process.argv[1]);const plan={name:'jzt-account-sep',url:'https://jzt-api.jd.com/reweb/msa/base/account/list',body:{pinIds:['fixture-account']}};b.validatePlan([plan],'jzt','http://127.0.0.1:9321');assert.throws(()=>b.validatePlan([{...plan,url:'https://jzt-api.jd.com/plan/create'}],'jzt','http://127.0.0.1:9321'),/original-readonly-plan-required/);assert.throws(()=>b.validatePlan([{...plan,body:{pinIds:['other-account']}}],'jzt','http://127.0.0.1:9321'),/merchant-ad-account-mismatch/);assert.throws(()=>b.validatePlan([{...plan,body:{...plan.body,apiKey:'synthetic-fixture'}}],'jzt','http://127.0.0.1:9321'),/credential-fields-not-accepted/);const out=JSON.parse(b.responseText(JSON.stringify({code:1,data:{cost:42,token:'synthetic-fixture'}})));assert.equal(out.data.cost,42);assert.equal(out.data.token,'[REDACTED]');assert.equal(JSON.parse(b.responseText('<html>login</html>')).unavailable,'non-json-or-login-response');"""
   env=dict(os.environ,HEIDENG_MERCHANT_HOME=str(state),HEIDENG_MERCHANT_BROWSER_CONFIG=str(cfg))
   result=subprocess.run(['node','-e',code,str(SOURCE/'scripts/merchant-browser.cjs')],env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)
 def test_merchant_cdp_namespace_survives_nested_dispatch(self):
  from heideng_merchant.mature_runtime import child_environment
  with tempfile.TemporaryDirectory() as d:
   first=child_environment(Path(d),{'PATH':os.environ.get('PATH',''),'HEIDENG_MERCHANT_SHOP_CDP':'http://127.0.0.1:9321'})
   second=child_environment(Path(d),first)
   self.assertEqual(second.get('SHOP_CDP'),'http://127.0.0.1:9321')
   self.assertEqual(second.get('HEIDENG_MERCHANT_SHOP_CDP'),'http://127.0.0.1:9321')
 def test_original_report_validator_is_not_a_new_report_engine(self):
  source=(SOURCE/'scripts/validate_report.py').read_text(encoding='utf-8')
  self.assertIn('Excel 至少 3 张表',source);self.assertIn('成交金额',source)
  self.assertIn('数据缺口',source)
 def test_employee_ge_and_sso_model_components_are_not_bundled(self):
  meta=json.loads((SOURCE/'provenance.json').read_text(encoding='utf-8'))
  self.assertNotIn('scripts/ge-sz-fetch.py',meta['files'])
  self.assertNotIn('scripts/easybi_shop_query.py',meta['files'])
  self.assertNotIn('scripts/doctor.py',meta['files'])
if __name__=='__main__':unittest.main()
