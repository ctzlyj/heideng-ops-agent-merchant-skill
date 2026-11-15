"""Candidate owned source reader tests; all factories/API bytes are synthetic."""
import copy, importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heideng_merchant.safety import SafetyError
from tests import test_short_title_result_observation as existing

class OwnedOriginalEffectReadTests(unittest.TestCase):
    def observe(self, manager, root, browser):
        self.assertTrue(hasattr(manager, 'collect_effects'), 'C3 original owned effects reader is not implemented')
        return manager.collect_effects(root['importId'], browser)

    def setup(self, directory, *, complete=True):
        helper = existing.ShortTitleResultObservationTests()
        client, manager, root, browser, page, wire = helper.setup(directory)
        if complete:
            helper.complete(page, wire); manager.collect_results(root['importId'], browser)
        original = client.invoke
        calls = []
        proposed = manager.record(root['importId'])['scope']['changes'][0]['shortTitle']
        def invoke(profile, url, **kwargs):
            calls.append((url, kwargs.get('method'), copy.deepcopy(kwargs.get('params', {}))))
            value = original(profile, url, **kwargs)
            if url.endswith('/products/{productId}'):
                for row in value['data']['skuList']:
                    row['features'] = {'shortTitle': proposed if str(row['skuId']) == '101' else 'Old sibling'}
            return value
        client.invoke = invoke
        client.health[0]['healthScore'] = 99
        client.health[0]['improvementList'] = []
        return client, manager, root, browser, page, calls, proposed

    def test_original_five_siblings_kept_and_c2_not_confused_with_formal_audit(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,calls,title = self.setup(d)
            try:
                result = self.observe(m,r,b)
                self.assertEqual([v['skuId'] for v in result['rows']], ['101','102','1001','9001','9002'])
                target = result['rows'][0]
                self.assertEqual(target['actualShortTitle'], title); self.assertTrue(target['actualTitleVerified'])
                self.assertEqual(target['processingOutcome'], 'success'); self.assertEqual(target['healthTitleIssue'], False)
                self.assertTrue(result['actualTitlesVerified']); self.assertFalse(result['formalAuditVerified'])
                self.assertFalse(result['portalVerified']); self.assertFalse(result['imported']); self.assertFalse(result['retryAuthorized'])
                self.assertEqual((p.uploads,p.creates), (1,1)); self.assertFalse(c.posts)
                self.assertTrue(all(method=='GET' for _,method,_ in calls))
                self.assertTrue(result['sourceDetailsStable']); self.assertTrue(result['currentIdentityVerified'])
                self.assertEqual(len(result['detailSources']), 2)
                self.assertNotIn('synthetic-only-private', json.dumps(result))
            finally: b.close()

    def test_missing_health_score_does_not_drop_original_or_claim_health(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.setup(d);c.health[0]['healthScore']=None
            try:
                result=self.observe(m,r,b);self.assertEqual(len(result['rows']),5)
                self.assertIsNone(result['rows'][0]['healthScore']);self.assertFalse(result['healthVerified'])
                self.assertTrue(result['rows'][0]['actualTitleVerified']);self.assertFalse(result['imported'])
            finally:b.close()

    def test_malformed_improvement_list_never_becomes_no_issue(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d);c.health[0]['improvementList']=[{'improvementDetail':{}}]
            try:
                result=self.observe(m,r,b);self.assertIsNone(result['rows'][0]['healthTitleIssue']);self.assertFalse(result['healthVerified'])
            finally:b.close()

    def test_processing_unknown_even_if_live_title_matches_not_imported(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.setup(d,complete=False)
            try:
                result=self.observe(m,r,b);self.assertEqual(result['rows'][0]['processingOutcome'],'unknown')
                self.assertTrue(result['currentTargetTitlesMatch']);self.assertFalse(result['actualTitlesVerified'])
                self.assertFalse(result['imported']);self.assertFalse(result['retryAuthorized']);self.assertEqual((p.uploads,p.creates),(1,1))
            finally:b.close()

    def test_long_title_only_stays_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d);old=c.invoke
            def invoke(*args,**kw):
                result=old(*args,**kw)
                if args[1].endswith('/products/{productId}'):
                    for row in result['data']['skuList']:row.pop('features')
                return result
            c.invoke=invoke
            try:
                result=self.observe(m,r,b);self.assertFalse(result['actualTitlesVerified']);self.assertIsNone(result['rows'][0]['actualShortTitle'])
            finally:b.close()

    def test_source_detail_change_between_reads_not_stable_or_actual_verified(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d);old=c.invoke;count={}
            def invoke(profile,url,**kw):
                result=old(profile,url,**kw)
                if url.endswith('/products/{productId}'):
                    pid=kw['params']['productId'];count[pid]=count.get(pid,0)+1
                    if count[pid]>1:result['data']['skuList'][0]['features']['shortTitle']='Other operator value'
                return result
            c.invoke=invoke
            try:
                result=self.observe(m,r,b);self.assertFalse(result['sourceDetailsStable']);self.assertFalse(result['actualTitlesVerified']);self.assertFalse(result['imported'])
            finally:b.close()

    def test_missing_original_current_row_retained_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d);old=c.invoke
            def invoke(profile,url,**kw):
                result=old(profile,url,**kw)
                if url.endswith('/products/{productId}'):result['data']['skuList']=[row for row in result['data']['skuList'] if row['skuId']!=101]
                return result
            c.invoke=invoke
            try:
                result=self.observe(m,r,b);self.assertEqual(len(result['rows']),5);self.assertFalse(result['currentOriginalScopeComplete']);self.assertFalse(result['actualTitlesVerified'])
            finally:b.close()

    def test_wrong_browser_or_closed_install_owner_refused(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,calls,_=self.setup(d)
            try:
                with self.assertRaises(SafetyError):self.observe(m,r,object())
                self.assertFalse(calls)
            finally:b.close()
            with self.assertRaises(SafetyError):self.observe(m,r,b)
            self.assertFalse(calls)

    def test_identity_switch_after_first_detail_refused(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d);old=c.invoke;old_identity=c.identity;changed=[False]
            def invoke(profile,url,**kw):
                result=old(profile,url,**kw)
                if url.endswith('/products/{productId}'):changed[0]=True
                return result
            def identity(profile):
                result=old_identity(profile)
                if changed[0]:result['venderId']='77'
                return result
            c.invoke=invoke;c.identity=identity
            try:
                with self.assertRaises(SafetyError):self.observe(m,r,b)
            finally:b.close()

    def test_cli_effect_rows_uses_installed_original_scope_not_live_refresh(self):
        from heideng_merchant import cli
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,calls,_=self.setup(d)
            try:
                self.observe(m,r,b);before=len(calls)
                try:args=cli.parser().parse_args(['--home',str(Path(d).parent),'short-title-import-rows','--import-id',r['importId'],'--view','effects','--page-size','2'])
                except SystemExit:self.fail('CLI original effect rows view is not implemented')
                with patch('heideng_merchant.cli.OfficialClient',return_value=c),patch('heideng_merchant.cli.ShortTitleImports',return_value=m):result=cli.run(args)
                self.assertEqual(result['total'],5);self.assertEqual(len(result['items']),2);self.assertEqual(len(calls),before)
            finally:b.close()

    def test_original_health_partial_source_stays_partial_without_scope_loss(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,_,_,_=self.setup(d)
            c.health.extend({'skuId':20000+i,'productId':99,'healthScore':100,'improvementList':[]} for i in range(120))
            try:
                result=m.collect_effects(r['importId'],b,max_pages=1)
                self.assertEqual(len(result['rows']),5);self.assertFalse(result['healthSource']['complete']);self.assertFalse(result['healthVerified'])
                self.assertFalse(result['rows'][0]['healthRowObserved']);self.assertFalse(result['retryAuthorized'])
            finally:b.close()

    def test_sensitive_health_or_changed_original_root_never_persists_effect(self):
        for kind in ('health','root'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                c,m,r,b,_,calls,_=self.setup(d)
                if kind=='health':c.health[0]['access_token']='SYNTHETIC_ONLY_DO_NOT_PERSIST'
                else:
                    from heideng_merchant.safety import read_json,atomic_json
                    file=Path(d)/'short-title-imports'/f"{r['importId']}.json";record=read_json(file);record['fingerprint']='0'*64;atomic_json(file,record)
                try:
                    with self.assertRaises(SafetyError):m.collect_effects(r['importId'],b)
                    self.assertFalse(list((Path(d)/'short-title-effect-observations').glob('*/*.json')))
                    if kind=='root':self.assertFalse(calls)
                finally:b.close()

if __name__=='__main__':unittest.main(verbosity=2)
