"""Exercise the two-shop CLI with real workbooks and synthetic platform receipts."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from heideng_merchant import shop_copy_short_titles as titles
from heideng_merchant.safety import atomic_json, read_json
from tests.test_owned_product_copy import SOURCE, TARGET, sample


class CopyShortTitlesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(self.root)}))
        listing = Path(__file__).resolve().parents[1]/'mature/listing/scripts'
        self.enterContext(patch.object(sys, 'path', [str(listing), *sys.path]))
        from heideng_merchant import shop_copy_command as entry
        self.entry = entry
        self.agent, _, self.workflow, self.browser = titles._services()
        self.src, self.dst = sample(), sample(True)
        self.left = '=合成可调光白色阅读灯'
        self.src['skuList'][0]['features'] = [{'key':'shortTitle','value':self.left}]
        self.src['skuList'][1]['features'] = {'shortTitle':'蓝色书桌合成阅读灯'}
        self.dst['skuList'][0]['features'] = {'shortTitle':'店内保留的蓝色阅读灯'}
        self.dst['skuList'][1]['features'] = {'shortTitle':''}
        self.profile = self.enterContext(patch.object(titles, 'registered_browser_profile', return_value=self.root/'profile'))
        def verify(config, profile):
            self.active = {SOURCE['profile']:SOURCE, TARGET['profile']:TARGET}[profile]
            return self.active
        self.enterContext(patch.object(entry, 'verify', side_effect=verify))
        self.reads = self.enterContext(patch.object(entry, 'read_owned_detail', side_effect=self.detail))
        self.enterContext(patch.object(entry.api, 'recheck_verified_jdo_store', side_effect=lambda:self.active))
        self.enterContext(patch.object(entry.pipeline, 'list_products', side_effect=lambda **_:[
            self.src['productInfo'] if self.active == SOURCE else self.dst['productInfo']]))
        self.enterContext(patch.object(entry, 'reference', return_value=None))
        self.upload = self.enterContext(patch.object(self.workflow, '_import_delivery', side_effect=self.submit))
        self.reconcile = self.enterContext(patch.object(self.browser, '_import_short_title_batch', side_effect=self.resume))
        self.mode = 'accepted'
        self.expected_rows = {'301':self.left}

    def detail(self, pid):
        self.assertEqual(self.active, SOURCE if pid == 701 else TARGET)
        return deepcopy(self.src if pid == 701 else self.dst)

    def submit(self, args, paths, seller, agent, receipts):
        self.assertEqual((seller, self.active), (TARGET, TARGET))
        self.assertEqual(self.workflow._workbook_titles(paths[0]), self.expected_rows)
        ledger = read_json(next(self.root.rglob('requests.json')))
        request = ledger[receipts[0]['sha256']]
        self.assertEqual(request['result'], {'status':'dispatch-intent'})
        if self.mode == 'lost':
            raise TimeoutError('lost result')
        if self.mode == 'preflight':
            return {'imports':[{'status':'blocked-import','dispatchState':'before-upload'}]}
        val = {'status':'import-pending','creationAccepted':True,'taskId':'777777', 'shopName':TARGET['shopName'],
               'shopId':TARGET['shopId'], 'sha256':request['sha256'], 'uploadSourceHashes':[]}
        atomic_json(Path(request['receiptFile']), val)
        return {'imports':[val]}

    def resume(self, profile, workbook, **options):
        self.assertTrue(options['reconcile_only'])
        self.assertEqual(options['expected_shop_id'], TARGET['shopId'])
        receipt = read_json(options['receipt_path'])
        failed = int(self.mode == 'failed')
        if not failed:
            self.dst['skuList'][1]['features'] = {'shortTitle':self.left}
        return {**receipt, 'status':'import-failed' if failed else 'import-completed',
                'successRows':1-failed, 'failedRows':failed}

    def run_cli(self, *extras):
        output = StringIO()
        with redirect_stdout(output):
            code = self.entry.main(['copy-short-titles','--source-profile',SOURCE['profile'],
                      '--source-config','source-local.json','--source-product-id','701',
                      '--target-profile',TARGET['profile'],'--target-config','target-local.json',
                      '--target-product-id','802', *extras])
        result = json.loads(output.getvalue())
        self.assertIn('reportFile', result)
        self.assertEqual(code, 0 if result['ok'] else 2)
        return result, read_json(Path(result['reportFile']))

    def run_import(self, *extras):
        return self.run_cli('--confirm','IMPORT_COPY_SHORT_TITLES', *extras)

    def test_handoff_uses_literal_source_and_independent_target_ids(self):
        result, report = self.run_cli()
        self.assertEqual(result['preparedRows'], 1)
        self.assertEqual(report['skuCounts'], {'ready':1, 'target-preserved':1})
        check, rows = self.agent.inspect_short_title_workbook(result['workbooks'][0])
        self.assertTrue(check['contentValid'])
        self.assertEqual(rows, [('301', self.left)])
        self.assertFalse(list(self.root.rglob('requests.json')))
        self.upload.assert_not_called()

    def test_source_and_target_field_must_be_explicit_and_sku_pair_must_be_unique(self):
        self.dst['skuList'][1]['features'] = [{'key':'other','value':''}]
        self.dst['skuList'][1]['shortTitle'] = ''
        self.dst['skuList'][0]['features'] = {'shortTitle':''}
        self.src['skuList'][1]['features'] = [{'key':'shortTitle','value':'x'},{'key':'shortTitle','value':'y'}]
        result, _ = self.run_import()
        self.assertEqual(result['skuCounts'], {'target-unreported':1, 'source-unreported':1})
        self.assertFalse(result['workbooks'])
        self.dst['skuList'][0]['saleAttrs'] = deepcopy(self.dst['skuList'][1]['saleAttrs'])
        result, report = self.run_import()
        self.assertEqual(result['skuCounts'], {'unpaired':2})
        self.assertEqual(len(report['unpairedTargetSkus']), 2)
        self.upload.assert_not_called()

    def test_unrelated_product_and_missing_registered_browser_do_not_upload(self):
        self.dst['productInfo']['productName'] = '另一件商品'
        result, _ = self.run_import()
        self.assertEqual(result['status'], 'unverified-product-pair')
        self.dst['productInfo']['productName'] = self.src['productInfo']['productName']
        self.profile.return_value = None
        result, _ = self.run_import()
        self.assertEqual((result['preparedRows'], result['status']), (1, 'blocked-target-browser'))
        self.assertFalse(list(self.root.rglob('requests.json')))
        self.upload.assert_not_called()

    def test_legacy_readback_proves_only_its_own_target_when_item_numbers_changed(self):
        history = self.root/'old-run'
        member = history/'batch5/701'
        folder = member/'201_lamp'
        archive = folder/'.pipeline/publish'
        variants = [{'sourceSku':'201'},{'sourceSku':'202'}]
        name = self.src['productInfo']['productName']
        atomic_json(folder/'manifest.json', {'sourceSpu':'701','sourceSku':'201','variants':variants})
        atomic_json(folder/'listing.json', {'source':{'spu':'701','sku':'201'},'product':{'title':name,'itemNumber':'701'},
                                            'category':{'id':800},'skus':variants})
        original = {'ok':False,'productId':802,'productName':name,'expectedSkuCount':2,'actualSkuCount':2,
                    'productStatus':103,'verifiedAt':'2026-11-12T14:00:00+08:00'}
        atomic_json(archive/'verification.json', original)
        state = {'sourceSpu':701,'sourceSku':201,'store':TARGET,'productId':803,'folder':str(folder),'verification':original}
        atomic_json(member/'state/201.json', state)
        self.dst['productInfo']['itemNum'] = '701'
        result, _ = self.run_cli()
        self.assertEqual(result['preparedRows'], 0)
        result, _ = self.run_cli('--history-dir', str(history))
        self.assertEqual(result['productPair']['basis'], 'legacy-product-readback')
        self.assertEqual(result['preparedRows'], 1)
        original['productId'] = 804
        atomic_json(archive/'verification.json', original)
        atomic_json(member/'state/201.json', state)
        result, _ = self.run_import('--history-dir', str(history))
        self.assertEqual(result['preparedRows'], 0)
        self.upload.assert_not_called()

    def test_loss_before_receipt_reserves_even_if_source_text_changes(self):
        self.mode = 'lost'
        self.run_import()
        self.src['skuList'][0]['features'] = {'shortTitle':'原店新改的阅读灯短标题'}
        result, report = self.run_import()
        self.assertEqual(result['platformAcceptedRows'], 0)
        self.assertEqual(report['originalRequests'][0]['reconciliation'], 'original-receipt-or-workbook-unavailable')
        self.assertEqual(self.upload.call_count, 1)
        self.reconcile.assert_not_called()

    def test_target_filled_after_handoff_is_preserved_at_dispatch(self):
        seen = []
        def change(pid):
            if pid == 802 and pid in seen:
                self.dst['skuList'][1]['features'] = {'shortTitle':'经办人新维护的短标题'}
            seen.append(pid)
            return self.detail(pid)
        self.reads.side_effect = change
        _, report = self.run_import()
        self.assertEqual(report['changedBeforeWrite'], ['301'])
        self.upload.assert_not_called()

    def test_source_title_changed_after_handoff_cannot_upload_stale_text(self):
        seen = []
        def change(pid):
            if pid == 701 and pid in seen:
                self.src['skuList'][0]['features'] = {'shortTitle':'原店刚换的灯具短标题'}
            seen.append(pid)
            return self.detail(pid)
        self.reads.side_effect = change
        _, report = self.run_import()
        self.assertEqual(report['changedBeforeWrite'], ['301'])
        self.assertEqual(report['originalRequests'], [])
        self.upload.assert_not_called()

    def test_handoff_sent_by_regular_import_is_reconciled_after_source_changes(self):
        first, _ = self.run_cli()
        workbook = Path(first['workbooks'][0])
        meta = self.agent.validate_short_title_workbook(workbook)
        native = self.browser.batch_receipt_path(workbook, meta['sha256'])
        atomic_json(native, {'sha256':meta['sha256'], 'rowCount':1, 'status':'import-pending', 'creationAccepted':True,
                     'taskId':'777777', 'shopName':TARGET['shopName'], 'shopId':TARGET['shopId']})
        self.src['skuList'][0]['features'] = {'shortTitle':'原店新改的阅读灯短标题'}
        result, _ = self.run_cli('--reconcile')
        self.assertEqual(result['originalTaskIds'], ['777777'])
        self.assertEqual(result['originalTargetTitlesMatched'], 1)
        self.assertEqual(result['workbooks'], [])
        self.upload.assert_not_called()

    def test_read_only_reconciliation_without_original_does_not_prepare_or_upload(self):
        result, _ = self.run_cli('--reconcile')
        self.assertEqual(result['status'], 'no-original-import')
        self.assertEqual(result['workbooks'], [])
        self.assertFalse(list(self.root.rglob('*.xlsx')))
        self.upload.assert_not_called()

    def test_original_receipt_reconciles_and_keeps_import_and_health_separate(self):
        def health(*_):
            return {'status':'observed','skus':{'301':{'score':87,'improvements':[
                   {'improvementDetail':{'troubleCode':'hasShortTitle'}}]}, '302':{'score':99,'improvements':[]}}}
        with patch.object(titles.materials, '_health', side_effect=health):
            result, _ = self.run_import('--health')
            self.assertEqual((result['uploadedRows'],result['platformAcceptedRows'], result['platformSuccessRows']), (1,1,0))
            result, report = self.run_cli('--reconcile','--health')
        self.assertEqual(result['platformSuccessRows'], 1)
        self.assertEqual(result['originalTargetTitlesMatched'], 1)
        self.assertEqual(result['originalTargetScoreClearRows'], 0)
        self.assertEqual(report['targetHealth']['perSku'], {'301':'issue-present','302':'clear'})
        self.assertEqual(self.upload.call_count, 1)
        self.assertEqual(self.reconcile.call_count, 1)

    def test_row_failure_does_not_rewrite_exact_source_title(self):
        self.run_import()
        self.mode = 'failed'
        result, _ = self.run_import()
        self.assertEqual(result['status'], 'short-title-import-row-failures')
        self.assertEqual((result['platformSuccessRows'], result['platformFailedRows']), (0,1))
        self.run_import()
        self.assertEqual(self.upload.call_count, 1)

    def test_known_before_upload_browser_failure_can_resume_original_table(self):
        self.mode = 'preflight'
        self.run_import()
        self.mode = 'accepted'
        result, report = self.run_import()
        self.assertEqual(result['platformAcceptedRows'], 1)
        self.assertEqual(len(report['originalRequests']), 1)
        self.assertEqual(self.upload.call_count, 2)


if __name__ == '__main__':
    unittest.main()
