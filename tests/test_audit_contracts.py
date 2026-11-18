"""Audit-derived real return-shape regressions. No merchant calls."""
import io,json,unittest,os,sys,subprocess,tempfile
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
from heideng_merchant.merchant_experience import task_summary
from heideng_merchant.safety import SafetyError

class AuditResultTests(unittest.TestCase):
    def test_report_return_shapes_never_claim_running_or_allow_replay(self):
        cases=[
            ({'status':'submitted-for-manual-verification','spuCount':2,'batches':[{'completedSpus':2}]},'submitted',False),
            ({'status':'no-work'},'completed',True),
            ({'status':'repair-incomplete','failedCount':1},'needs-agent-action',False),
            ({'status':'completed-materials','productAttributes':{'status':'attrs-incomplete'}},'needs-agent-action',False),
            ({'status':'unrecognized-return'},'needs-agent-action',False),
        ]
        for payload,phase,completed in cases:
            with self.subTest(payload=payload):
                result=task_summary(payload)
                self.assertEqual(result['phase'],phase)
                self.assertEqual(result['completed'],completed)
                self.assertFalse(result['retryAllowed'])
                self.assertNotIn('正在处理',result['message'])
                self.assertTrue(result['canLeave'])
    def test_actual_repair_counts_and_unknown_errors_are_not_erased(self):
        payload={'status':'repair-incomplete','rows':[{'skuId':'1','status':'pending'}],
                 'errors':[{'skuId':'2','status':'unknown','reason':'original receipt'}]}
        result=task_summary(payload)
        self.assertEqual(result['phase'],'needs-reconciliation')
        self.assertGreaterEqual(result['failedCount'],1)
        self.assertEqual(result['pendingReviewCount'],1)
        self.assertFalse(result['retryAllowed'])
    def test_each_requested_component_can_prevent_whole_task_completion(self):
        for key in ('shortTitleDelivery','productAttributes','rejectedRepairs','externalImages'):
            with self.subTest(key=key):
                result=task_summary({'status':'completed-materials',key:{'status':'blocked'}})
                self.assertFalse(result['completed'])
                self.assertEqual(result['components'][key]['status'],'blocked')
    def test_attributes_without_status_but_failed_verification_prevent_completion(self):
        result=task_summary({'status':'completed-materials','productAttributes':{'allVerified':False,'failedCount':1}})
        self.assertFalse(result['completed']);self.assertGreaterEqual(result['failedCount'],1)
    def test_returned_title_and_repair_receipts_preserve_row_failures_and_review(self):
        failed=task_summary({'status':'import-completed-with-row-failures','platformFailedRows':2,'imports':[{'status':'import-failed','failedRows':2}]})
        self.assertEqual(failed['phase'],'needs-agent-action');self.assertEqual(failed['failedCount'],2)
        for status in ('repairs-submitted-awaiting-review','jingmai-submitted-awaiting-review','import-completed-awaiting-review'):
            with self.subTest(status=status):
                result=task_summary({'status':status})
                self.assertEqual(result['phase'],'waiting-review');self.assertFalse(result['completed']);self.assertFalse(result['retryAllowed'])
        verified=task_summary({'status':'repairs-submitted-awaiting-review','allApproved':True,'rows':[{'status':'approved'}]})
        self.assertTrue(verified['completed'])
    def test_technical_task_failure_does_not_request_a_merchant_decision(self):
        result=task_summary({'status':'repair-incomplete','errors':[{'status':'blocked','failureClass':'ImportError'}]})
        self.assertFalse(result['needsUserAction']);self.assertFalse(result['needsMerchantAction'])
        self.assertTrue(result['needsAgentAction'])
    def test_explicit_merchant_decision_remains_distinct_from_agent_diagnosis(self):
        result=task_summary({'status':'blocked','needsMerchantAction':True})
        self.assertTrue(result['needsUserAction']);self.assertTrue(result['needsMerchantAction'])
        self.assertEqual(result['phase'],'needs-merchant-action')
    def test_default_cli_status_is_small_without_technical_inventory(self):
        from heideng_merchant.cli import main
        detail={'capabilities':[{'upstreamCommit':'f'*40,'capability':'fixture'}]*50}
        with patch('heideng_merchant.cli.status',return_value=detail),patch('heideng_merchant.update_client.consume_notice',return_value=None),patch('heideng_merchant.update_client.maybe_schedule'),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['status']),0)
        result=json.loads(out.getvalue())
        self.assertNotIn('capabilities',result);self.assertNotIn('detail',result)
        self.assertLess(len(out.getvalue()),1800)
    def test_cli_error_uses_chinese_projection_and_sanitized_technical_reason(self):
        from heideng_merchant.cli import main
        with patch('heideng_merchant.cli.run',side_effect=SafetyError('runtime-network-unavailable; token=fixture-private')),patch('heideng_merchant.update_client.maybe_schedule'),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['run','materials','--','fixture']),2)
        result=json.loads(out.getvalue())
        self.assertEqual(result.get('kind'),'retryable-environment')
        self.assertFalse(result['needsMerchantAction']);self.assertTrue(result['needsAgentAction'])
        self.assertNotIn('fixture-private',out.getvalue());self.assertIn('当前',result['message'])

class AuditChildErrorTests(unittest.TestCase):
    def test_actual_mature_child_failure_is_structured_not_a_traceback(self):
        from heideng_merchant.safety import clean_environment
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env=clean_environment(Path(d)/'home')
            env['HEIDENG_MERCHANT_HOME']=str(Path(d)/'state');env['HEIDENG_MERCHANT_PACKAGE']=str(root)
            command=[sys.executable,'-I','-B',str(root/'scripts/mature_entry.py'),str(root/'mature/materials/scripts/jd_material_agent.py'),
                     'fill-template','--manifest',str(Path(d)/'missing.xlsx'),'--url-export',str(Path(d)/'missing.csv'),'--output',str(Path(d)/'output.xlsx')]
            result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,2)
        self.assertNotIn('Traceback',result.stderr)
        payload=json.loads(result.stdout)
        self.assertEqual(payload['status'],'blocked');self.assertTrue(payload['needsAgentAction'])
        self.assertFalse(payload['needsMerchantAction']);self.assertFalse(payload['retryAllowed'])

if __name__=='__main__':unittest.main()
