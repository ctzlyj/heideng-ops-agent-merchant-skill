"""Merchant-facing projections and recovery only; no real business."""
import importlib.util,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'mature/connection'

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

class ExperienceTests(unittest.TestCase):
 def setUp(self):
  self.path=list(sys.path);self.names=('shoplib','redaction','browser_auth','browser_adapters','server','linker')
  self.saved={n:sys.modules.get(n) for n in self.names};sys.path[:0]=[str(SOURCE/'app'),str(SOURCE/'scripts')]
  for n in self.names:sys.modules.pop(n,None)
 def tearDown(self):
  sys.path[:]=self.path
  for n,v in self.saved.items():
   sys.modules.pop(n,None)
   if v is not None:sys.modules[n]=v
 def test_status_is_small_merchant_summary_with_detailed_source_retained(self):
  from heideng_merchant.cli import main
  with patch('heideng_merchant.cli.status',return_value={'capabilities':[{'capability':'fixture','upstreamCommit':'x'*40}] for _ in range(15)}),patch('heideng_merchant.update_client.consume_notice',return_value=None),patch('builtins.print') as output:
   self.assertEqual(main(['status','--detail']),0)
  result=json.loads(output.call_args.args[0]);self.assertEqual(result['version'],(ROOT/'VERSION').read_text().strip());self.assertIn('merchantSummary',result);self.assertIn('detail',result)
  self.assertNotIn('capabilities',result);self.assertLess(len(output.call_args.args[0]),1800)

 def test_pending_review_is_not_success_or_failure(self):
  from heideng_merchant.merchant_experience import task_summary
  summary=task_summary({'status':'waiting-review','spuCount':10,'skuCount':229,'batches':[{'binding':{'pending_spus':10,'failed_spus':0}}]})
  self.assertEqual(summary['phase'],'waiting-review');self.assertTrue(summary['canLeave']);self.assertFalse(summary['completed']);self.assertIn('审核',summary['message']);self.assertIn('恢复',summary['nextAction'])

 def test_unknown_result_requires_original_receipt_not_blind_retry(self):
  from heideng_merchant.merchant_experience import task_summary
  summary=task_summary({'status':'paused-unknown-write','resultFile':'/fixture/result.json'})
  self.assertEqual(summary['phase'],'needs-reconciliation');self.assertFalse(summary['retryAllowed']);self.assertIn('原任务',summary['nextAction'])

 def test_reconcile_receipts_report_actual_recovery_not_zero_progress(self):
  from heideng_merchant.merchant_experience import task_summary
  result=task_summary({'reconciledUploads':[{'status':'accepted'}],'reconciledBindings':[{'status':'pending'}],'unresolvedUploads':[],'unresolvedBindings':[]})
  self.assertEqual(result['phase'],'waiting-review');self.assertTrue(result['canLeave']);self.assertNotIn('0/0',result['message'])
  unresolved=task_summary({'reconciledUploads':[],'reconciledBindings':[],'unresolvedUploads':[],'unresolvedBindings':[{'reason':'fixture'}]})
  self.assertEqual(unresolved['phase'],'needs-reconciliation');self.assertFalse(unresolved['retryAllowed'])


 def test_same_shop_retry_defaults_resume_but_mismatch_never_silently_resumes(self):
  import server,browser_auth
  old=type('Job',(),{'status':'failed','stage':'waiting_login','errorKind':'login_timeout','shop_name':'fixture','expect_vender_id':'','requested_profile':'fixture','resume':Mock()})()
  manager=server.Manager();manager.job=old
  self.assertIs(manager.start_flow('fixture','fixture',resume=True),old);old.resume.assert_called_once()
  old.status='mismatch';old.resume.reset_mock()
  with patch.object(browser_auth,'BrowserAuthJob') as created:manager.start_flow('fixture','fixture',resume=True)
  created.assert_called_once();old.resume.assert_not_called()

 def test_wait_timeout_same_shop_attempt_is_resume_not_fresh(self):
  cli=load('experience_linker',SOURCE/'scripts/linker.py')
  args=type('Args',(),{'shop':'fixture','profile':None,'no_auth':False,'no_open':False,'no_wait':True,'resume':False,'fresh':False,'browser_config':None,'timeout':3})()
  pending={'jobId':'old','profile':'fixture-profile','shopName':'fixture'}
  with patch.object(cli,'_env_blockers',return_value=None),patch.object(cli.sl,'resolve',return_value={'status':'needs_auth','shopName':'fixture'}),patch.object(cli.sl,'load_pending',return_value=pending),patch.object(cli.sl,'suggest_profile_name',return_value='fixture-profile'),patch.object(cli.sl,'save_pending'),patch.object(cli,'api',return_value=(200,{'ok':True,'status':'awaiting_auth','profile':'fixture-profile','jobId':'old','job':{'stage':'waiting_login'}})) as api:
   cli.cmd_ensure_shop(args)
  self.assertTrue(api.call_args.args[1]['resume']);self.assertEqual(api.call_args.args[1]['profile'],'fixture-profile')

 def test_shop_sessions_are_separate_not_one_global_profile(self):
  from heideng_merchant.host_connection_controller import HostConnectionController
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
   a=HostConnectionController(shop_identity={'venderId':'123','shopName':'fixture-a'});b=HostConnectionController(shop_identity={'venderId':'456','shopName':'fixture-b'})
   self.assertNotEqual(a._state_path,b._state_path)

 def test_progress_reads_existing_receipts_without_new_queue(self):
  from heideng_merchant.merchant_experience import task_summary
  result=task_summary({'status':'submitted-with-failures','spuCount':20,'batches':[{'completedSpus':18,'failedSpus':['a'],'binding':{'pending_spus':0,'failed_spus':0}}],'shortTitleDelivery':{'status':'verified'}})
  self.assertEqual(result['completedCount'],18);self.assertEqual(result['totalCount'],20);self.assertTrue(result['needsAgentAction']);self.assertFalse(result['needsUserAction'])

 def test_run_registers_actual_usage_lease_without_changing_entrypoint(self):
  from heideng_merchant.mature_runtime import run
  from heideng_merchant import update_client
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.mature_runtime.source_path',return_value=(ROOT/'mature/materials/scripts/jd_material_agent.py',{})),patch('heideng_merchant.mature_runtime.child_environment',return_value={}),patch('heideng_merchant.mature_runtime.ensure_core',create=True),patch('heideng_merchant.mature_runtime.FileLock'),patch('heideng_merchant.mature_runtime.subprocess.run',return_value=Mock(returncode=0)),patch('heideng_merchant.runtime_dependencies.runtime_python',return_value=Path(sys.executable)),patch('heideng_merchant.mature_runtime.OfficialClient') as official,patch.object(update_client,'usage',side_effect=[{'packageRoot':'fixture'}, {'active':True},{'active':False}]) as usage:
   official.return_value.ready.return_value=False
   self.assertEqual(run('materials',['--help'],state=Path(d)),0)
  self.assertEqual([c.args[1] for c in usage.call_args_list],['begin','heartbeat','end'])

if __name__=='__main__':unittest.main()
