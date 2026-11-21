"""Offline field regressions for a missing response across different merchandise."""
import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
from tests.fee_consent import isolated_fees, signed_fixture
from tests.test_mature_listing import module


class CategoryImageRecoveryTests(unittest.TestCase):
    @isolated_fees
    def test_two_lost_responses_need_separate_informed_decisions(self):
        pg = module('photo_generation')
        pl = module('photo_listing')
        for product in ('羊毛围巾', '铝合金镜头座'):
            with self.subTest(product=product), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                out = root/'.generation'
                source = root/'reference.jpg'
                Image.new('RGB', (12, 12), 'teal').save(source)
                store = {'shopName':'合成店', 'profile':'merchant-a', 'venderId':42}
                manifest = {'schemaVersion':pl.SCHEMA_VERSION, 'packageId':product, 'store':store}
                pg.atomic_json(root/'manifest.json', manifest)
                task = {'id':'main-A', 'role':'main', 'size':'1024x1024', 'photos':[str(source)],
                        'prompt':product, 'sourceSha256':[pg.sha(source)]}
                pg.atomic_json(root/'plan.json', [task])
                scope = pg.generation_scope(manifest, [task])
                initial = signed_fixture({'scope':scope, 'units':['main-A'], 'billing':'requests', 'maxRequests':1})
                client = Mock(capacity=1)
                client.edit.side_effect = [TimeoutError(), TimeoutError(), source.read_bytes()]

                def run(approval, replace=False):
                    return pg.generate_tasks([task], out, client=client, approval=approval, scope=scope,
                                             replace_unknown=['main-A'] if replace else [])

                self.assertEqual(run(initial)['unknownCount'], 1)
                def read_only_reconcile():
                    files = {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    entry = Path(__file__).resolve().parents[1]/'scripts/mature_entry.py'
                    command = [sys.executable, '-I', '-B', str(entry), str(Path(pl.__file__)), 'reconcile-images',
                               '--package', str(root), '--units', 'main-A']
                    proc = subprocess.run(command, capture_output=True, encoding='utf-8')
                    self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                    self.assertEqual(files, {p:p.read_bytes() for p in root.rglob('*') if p.is_file()})
                    return json.loads(proc.stdout)['replacementQuote']

                ledger = out/'generation.json'
                first = pg.load(ledger)['main-A']
                quote = read_only_reconcile()
                self.assertTrue(quote['scope']['possibleDuplicateCharge'])
                with self.assertRaises(ValueError):
                    run(initial, replace=True)
                second_approval = signed_fixture(dict(quote, billing='requests'))
                self.assertEqual(run(second_approval, replace=True)['unknownCount'], 1)
                second = pg.load(ledger)['main-A']
                self.assertEqual(second['replacesUnknown'], first['reservationId'])
                third_quote = read_only_reconcile()
                with self.assertRaises(ValueError):
                    run(second_approval, replace=True)
                third_approval = signed_fixture(dict(third_quote, billing='requests'))
                self.assertEqual(run(third_approval, replace=True)['successCount'], 1)
                self.assertEqual(client.edit.call_count, 3)
                self.assertEqual(run(None)['submittedCount'], 0)
                for original in (first, second):
                    self.assertEqual(pg.load(out/'attempts'/(original['reservationId']+'.json')), original)
                self.assertEqual(len(pg.load(root/'.state/paid-image-budget.json')['requests']), 3)
                self.assertIsNone(read_only_reconcile())

    @isolated_fees
    def test_completed_bytes_are_recovered_without_replacement(self):
        pg = module('photo_generation')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = root/'.generation'
            source = root/'reference.jpg'
            Image.new('RGB', (15, 22), 'orange').save(source)
            task = dict(id='group-1', role='sku', size='1024x1024', photos=[str(source)], prompt='相机配件')
            scope = {'shop':'A', 'task':'accessories'}
            approval = signed_fixture(dict(scope=scope, units=[task['id']], maxRequests=1, billing='requests'))
            client = Mock(capacity=1)
            client.edit.side_effect = TimeoutError()
            pg.generate_tasks([task], out, scope=scope, approval=approval, client=client)
            saved = out/'generated/group-1.jpg'
            saved.parent.mkdir(exist_ok=True)
            saved.write_bytes(source.read_bytes())
            self.assertIsNotNone(pg.inspect_attempts([task], out, scope)['replacementQuote'])
            old = pg.load(out/'generation.json')[task['id']]
            pg.atomic_json(out/'attempts'/(old['reservationId']+'.result.json'),
                           {'fingerprint':old['fingerprint'], 'sha256':hashlib.sha256(saved.read_bytes()).hexdigest()})
            before = pg.inspect_attempts([task], out, scope)
            self.assertEqual(before['rows'][0]['status'], 'LOCAL_RESULT')
            self.assertIsNone(before['replacementQuote'])
            result = pg.generate_tasks([task], out, scope=scope, client=client)
            self.assertEqual(result['submittedCount'], 0)
            self.assertTrue(result['ledger']['group-1']['recovered'])
            self.assertEqual(client.edit.call_count, 1)

    @isolated_fees
    def test_budget_reservation_without_a_generation_row_is_still_recoverable(self):
        from heideng_merchant.image_budget import reserve_request
        pg = module('photo_generation')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = root/'.generation'
            source = root/'reference.jpg'
            Image.new('RGB', (10, 12), 'green').save(source)
            task = dict(id='front', role='main', size='1024x1024', photos=[str(source)], prompt='茶叶包装')
            scope = {'shop':'A', 'task':'tea'}
            approval = signed_fixture(dict(scope=scope, units=['front'], maxRequests=1, billing='requests'))
            reserve_request(root, approval, scope=scope, units=['front'], request_id='front')
            client = Mock(capacity=1)
            client.edit.return_value = source.read_bytes()
            with self.assertRaises(pg.GenerationUnknown):
                pg.generate_tasks([task], out, scope=scope, approval=approval, client=client)
            outcome = pg.inspect_attempts([task], out, scope)
            self.assertEqual(outcome['rows'][0]['status'], 'RESERVED_WITHOUT_RECEIPT')
            replacement = signed_fixture(dict(outcome['replacementQuote'], billing='requests'))
            self.assertEqual(pg.generate_tasks([task], out, scope=scope, approval=replacement,
                                              client=client, replace_unknown=['front'])['submittedCount'], 1)
            client.edit.assert_called_once()
