"""Owned C3 original evidence, recovery and cross-capability quarantine tests."""
import copy, json, shutil, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError, read_json, atomic_json
from heideng_merchant.operations import digest
from tests import test_short_title_effect_sources as source_tests
from tests import test_short_title_imports as import_tests

class EffectEvidenceTests(unittest.TestCase):
    def make(self, directory, *, complete=True):
        return source_tests.OwnedOriginalEffectReadTests().setup(directory, complete=complete)

    def collect(self, manager, root, browser):
        result=manager.collect_effects(root['importId'],browser)
        self.assertTrue(result.get('C3ReceiptPersisted') is True, 'C3 original observation/receipt is not persisted')
        return result

    def file(self,d,folder,root,n=1):
        return Path(d)/folder/root['importId']/f'{n:06d}.json'

    def head(self,d,root):return Path(d)/'short-title-effect-heads'/f"{root['importId']}.json"

    def test_original_snapshot_and_independent_receipt_head_are_bound(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.make(d)
            try:
                result=self.collect(m,r,b);self.assertEqual(result['effectObservationSequence'],1)
                item=read_json(self.file(d,'short-title-effect-observations',r));receipt=read_json(self.file(d,'short-title-effect-receipts',r));head=read_json(self.head(d,r))
                self.assertEqual(item['fingerprint'],r['fingerprint']);self.assertEqual(item['previousReceiptSha256'],r['fingerprint'])
                self.assertEqual(receipt['observationSha256'],digest(item));self.assertEqual(head['receiptSha256'],digest(receipt))
                self.assertEqual(item['observation']['originalAnchors'].keys(),{'000001'})
                self.assertEqual(item['observation']['originalResultSequence'],1)
                self.assertFalse(item['observation']['formalAuditVerified']);self.assertFalse(item['observation']['imported']);self.assertEqual((p.uploads,p.creates),(1,1))
            finally:b.close()

    def test_status_and_rows_are_original_historical_not_current_reads(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,calls,_=self.make(d)
            try:
                self.collect(m,r,b);before=len(calls);status=m.status(r['importId']);rows=m.rows(r['importId'],view='effects',page_size=2)
                self.assertEqual(len(calls),before);self.assertEqual(rows['total'],5);self.assertEqual(len(rows['items']),2)
                self.assertTrue(status['effectEvidenceHistorical']);self.assertTrue(status['actualTitlesVerified']);self.assertFalse(status['currentEffectSourceVerified'])
                self.assertFalse(status['formalAuditVerified']);self.assertFalse(status['healthVerified']);self.assertFalse(status['imported'])
            finally:b.close()

    def test_second_observation_appends_and_retains_original_field_values(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.make(d)
            try:
                self.collect(m,r,b);first=self.file(d,'short-title-effect-observations',r);raw=first.read_bytes();old=c.invoke
                def invoke(profile,url,**kw):
                    data=old(profile,url,**kw)
                    if url.endswith('/products/{productId}'):
                        for row in data['data']['skuList']:
                            if row['skuId']==101:row['features']['shortTitle']='Changed externally'
                    return data
                c.invoke=invoke;second=self.collect(m,r,b)
                self.assertEqual(second['effectObservationSequence'],2);self.assertEqual(first.read_bytes(),raw);self.assertFalse(second['actualTitlesVerified'])
                self.assertEqual((p.uploads,p.creates),(1,1));self.assertFalse(second['retryAuthorized'])
            finally:b.close()

    def test_missing_receipt_or_genuine_first_head_recovers_original_only(self):
        for kind in ('receipt','head'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                c,m,r,b,p,_,_=self.make(d)
                try:
                    self.collect(m,r,b);original=self.file(d,'short-title-effect-observations',r).read_bytes()
                    missing=self.file(d,'short-title-effect-receipts',r) if kind=='receipt' else self.head(d,r);missing.unlink()
                    with self.assertRaises(SafetyError):m.status(r['importId'])
                    out=self.collect(m,r,b);self.assertEqual(out['effectObservationSequence'],2)
                    self.assertEqual(self.file(d,'short-title-effect-observations',r).read_bytes(),original);self.assertTrue(missing.is_file());self.assertEqual((p.uploads,p.creates),(1,1))
                finally:b.close()

    def test_existing_invalid_head_never_treated_as_missing(self):
        for kind in ('null','bool','float','directory'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                c,m,r,b,p,calls,_=self.make(d)
                try:
                    self.collect(m,r,b);head=self.head(d,r);value=read_json(head)
                    if kind=='directory':head.unlink();head.mkdir()
                    elif kind=='null':atomic_json(head,None)
                    else:value['sequence']=True if kind=='bool' else 1.0;atomic_json(head,value)
                    before=len(calls)
                    with self.assertRaises(SafetyError):m.status(r['importId'])
                    with self.assertRaises(SafetyError):m.collect_effects(r['importId'],b)
                    self.assertEqual(len(calls),before);self.assertEqual((p.uploads,p.creates),(1,1))
                finally:b.close()

    def test_missing_observation_or_nonfirst_absent_head_refused(self):
        for kind in ('observation','head-after-two'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                c,m,r,b,p,calls,_=self.make(d)
                try:
                    self.collect(m,r,b)
                    if kind=='head-after-two':self.collect(m,r,b);self.head(d,r).unlink()
                    else:self.file(d,'short-title-effect-observations',r).unlink()
                    before=len(calls)
                    with self.assertRaises(SafetyError):m.collect_effects(r['importId'],b)
                    self.assertEqual(len(calls),before);self.assertEqual((p.uploads,p.creates),(1,1))
                finally:b.close()

    def test_derived_title_claims_and_source_references_recomputed_not_trusted(self):
        for kind in ('title','identity','result-prefix','coverage','anchor'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                c,m,r,b,p,calls,_=self.make(d)
                try:
                    self.collect(m,r,b);file=self.file(d,'short-title-effect-observations',r);item=read_json(file);value=item['observation']
                    if kind=='title':value['rows'][0]['actualShortTitle']='Different'
                    elif kind=='identity':value['identitySha256']='0'*64
                    elif kind=='result-prefix':value['originalResultReceiptSha256']='0'*64
                    elif kind=='anchor':value['originalAnchors']['000001']='0'*64
                    else:value['rows']=value['rows'][:-1]
                    atomic_json(file,item);receipt=read_json(self.file(d,'short-title-effect-receipts',r));receipt['observationSha256']=digest(item);atomic_json(self.file(d,'short-title-effect-receipts',r),receipt)
                    head=read_json(self.head(d,r));head['receiptSha256']=digest(receipt);atomic_json(self.head(d,r),head);before=len(calls)
                    with self.assertRaises(SafetyError):m.status(r['importId'])
                    with self.assertRaises(SafetyError):m.collect_effects(r['importId'],b)
                    self.assertEqual(len(calls),before);self.assertEqual((p.uploads,p.creates),(1,1))
                finally:b.close()

    def test_c3_anchor_survives_without_c2_and_blocks_deleted_b2_prefix_replay(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.make(d,complete=False)
            try:
                self.collect(m,r,b)
                for folder in ('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors'):
                    target=(Path(d)/folder/r['importId']).resolve();target.relative_to(Path(d).resolve())
                    if target.exists():shutil.rmtree(target)
                with self.assertRaises(SafetyError):m.execute(r['importId'],b)
                with self.assertRaises(SafetyError):m.plans.ops._assert_resolved(m.record(r['importId'])['scope']['shop'])
                self.assertEqual((p.uploads,p.creates),(1,1))
            finally:b.close()

    def test_orphan_c3_observation_receipt_or_head_blocks_prepared_shop_and_update(self):
        from heideng_merchant.short_title_import_gate import busy
        for folder in ('short-title-effect-observations','short-title-effect-receipts','short-title-effect-heads'):
            with self.subTest(folder=folder),tempfile.TemporaryDirectory() as d:
                c,s,p,src,m,r=import_tests.ShortTitleImportsTests().make(d)
                root=m.record(r['importId']);file=Path(d)/folder/(('a'*24+'.json') if folder.endswith('heads') else 'a'*24+'/000001.json');atomic_json(file,{})
                self.assertTrue(busy(d))
                with self.assertRaises(SafetyError):m.plans.ops._assert_resolved(root['scope']['shop'])

    def test_c2_new_prefix_preserves_old_effect_observation_and_updates_current_proof(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.make(d)
            try:
                self.collect(m,r,b);old=self.file(d,'short-title-effect-observations',r).read_bytes()
                p.result_dom=['7000000001 处理中 成功：0 失败：0']
                m.collect_results(r['importId'],b);latest=self.collect(m,r,b)
                self.assertEqual(latest['originalResultSequence'],2);self.assertFalse(latest['actualTitlesVerified'])
                self.assertEqual(self.file(d,'short-title-effect-observations',r).read_bytes(),old)
                self.assertEqual(m.status(r['importId'])['effectObservationCount'],2)
            finally:b.close()

    def test_append_cannot_write_an_older_c2_prefix_after_newer_original_effect(self):
        from heideng_merchant.short_title_import_state import evidence
        from heideng_merchant.short_title_effect_state import append_observation
        with tempfile.TemporaryDirectory() as d:
            c,m,r,b,p,_,_=self.make(d)
            try:
                self.collect(m,r,b);old=read_json(self.file(d,'short-title-effect-observations',r))['observation']
                p.result_dom=['7000000001 处理中 成功：0 失败：0'];m.collect_results(r['importId'],b);self.collect(m,r,b)
                root=m.record(r['importId'])
                with self.assertRaises(SafetyError):append_observation(d,root,evidence(d,root)[3],old,1000)
                self.assertFalse(self.file(d,'short-title-effect-observations',r,3).exists())
            finally:b.close()

if __name__=='__main__':unittest.main(verbosity=2)
