"""A cup with two finishes and a shared public image covers the actual refresh entry points."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from heideng_merchant.refresh_selection import verify_frozen
from heideng_merchant.safety import file_sha
from tests.gallery_fixture import detail

SCRIPTS = Path(__file__).resolve().parents[1] / 'mature/refresh/scripts'
SHOP = {'profile': 'cup', 'venderId': 5, 'shopName': '杯具店', 'shopId': 7}
PUBLIC = '0000000000'


def load(name):
    spec = importlib.util.spec_from_file_location('refresh_selection_test_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RefreshSelectionTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.enterContext(patch.dict(os.environ, HEIDENG_MERCHANT_HOME=str(self.root / 'state')))
        self.enterContext(patch.dict(sys.modules))
        self.enterContext(patch.object(sys, 'path', [str(SCRIPTS), *sys.path]))
        sys.modules.pop('_common', None)
        self.new, self.build, self.gen = map(load, ('new_job', 'build_plan', 'generate'))
        self.common = self.build.common
        self.live = {41: detail()}
        self.live[41]['productInfo']['productName'] = '带杯盖陶瓷杯'
        self.live[41]['material']['mainImages'][1]['imageInfoList'][0]['imgUrl'] = 'red-cup'
        client = Mock()
        client.get.side_effect = lambda *args: {'data': [{'productId': p, 'productStatus': 103} for p in self.live],
                                                'paginationData': {'totalItems': len(self.live)}}
        self.enterContext(patch.object(self.common, 'connect', return_value=client))
        self.enterContext(patch.object(self.common, 'apply_detail', side_effect=lambda cli, p: deepcopy(self.live[p])))
        self.enterContext(patch.object(self.common, 'verify_identity', side_effect=self.identity))
        self.enterContext(patch.object(self.common, 'resolve_api_key', side_effect=AssertionError('no paid request')))

    def identity(self, cli, job, run):
        self.common.save_json(run / 'identity.json', SHOP)
        return SHOP

    def create(self, name, *options):
        path = self.root / name
        self.new.main(['new_job', str(path), '--profile', 'cup', '--vender-id', '5', '--shop-name', '杯具店', *options])
        return path

    def plan(self, run):
        self.build.main(['build_plan', str(run)])
        return self.common.load_json(run / 'plan-batch.json')

    def test_source_exclusions_live_index_and_explicit_slot(self):
        path = self.root / 'copies.json'
        records = [{'sourceProductId': str(s), 'targetProductId': str(t), 'status': 'submitted',
                    'comparison': {'readbackView': 'product'}} for s, t in [(101, 41), (102, 42), (103, 43)]]
        records.append({'sourceProductId': '104', 'applyId': '99', 'status': 'publication-rejected'})
        self.common.save_json(path, {'status': 'batch-status', 'targetShop': SHOP, 'rows': records})
        run = self.create('single', '--main-selection', 'per-link', '--copy-batch-report', str(path),
                          '--exclude-source-product', '102', '--max-images', '1')
        fetched = self.plan(run)
        self.assertEqual(fetched['selectedSlotCount'], 1)
        product, = fetched['products']
        self.assertEqual(product['sourceProductId'], '101')
        self.assertEqual([s['group'] for s in product['selectedSlots']], [PUBLIC])
        self.assertEqual({r['reason'] for r in fetched['exclusions']},
                         {'excluded-source', 'target-product-unconfirmed', 'not-in-target-product-index'})
        self.assertEqual({f.name for f in (run / 'products').iterdir()}, {'41'})
        self.assertEqual(self.plan(run), fetched)
        with self.assertRaisesRegex(ValueError, '超出'):
            self.gen.main(['generate.py', str(run), '44', '--quote-only'])
        self.common.save_json(run / 'products/41/before-apply.json', {})
        with self.assertRaisesRegex(ValueError, '快照'):
            self.gen.main(['generate.py', str(run), '--quote-only'])

    def test_sku_no_spill_and_selection_limit_before_quote(self):
        run = self.create('sku', '--products', '41', '--main-selection', 'sku', '--sku-id', '301')
        product, = self.plan(run)['products']
        self.assertEqual([(s['group'], s['position']) for s in product['selectedSlots']], [('blue', 1)])
        self.live[41]['skuList'].append(dict(self.live[41]['skuList'][0], skuId=303))
        shared = self.create('shared', '--products', '41', '--main-selection', 'sku', '--sku-id', '301')
        with self.assertRaisesRegex(ValueError, '303'):
            self.plan(shared)
        over = self.create('over', '--products', '41', '--main-selection', 'sku', '--sku-id', '301',
                           '--sku-id', '303', '--sku-id', '302', '--max-images', '1')
        with self.assertRaisesRegex(ValueError, '超过'):
            self.plan(over)
        self.assertFalse((over / 'image-quote.json').exists())
        self.assertFalse((over / 'plan-batch.json').exists())

    def test_remaining_colors_use_actual_previous_slots_and_refuse_unresolved(self):
        first = self.create('first', '--products', '41', '--main-selection', 'per-link')
        original = self.plan(first)
        key, = original['tasks']
        self.common.save_json(first / 'uploads.json', {key: {'imgUrl': 'approved', 'status': 'succeeded'}})
        self.common.save_json(first / 'patch-results.json', {'41': {'ok': False, 'status': 'awaiting-readback'}})
        self.live[41]['material']['mainImages'][2]['imageInfoList'][0]['imgUrl'] = 'approved'
        permitted = self.create('colors', '--main-selection', 'remaining-colors', '--from-main-run', str(first))
        p = self.plan(permitted)
        self.assertEqual(set(p['tasks']), {s['key'] for s in p['products'][0]['selectedSlots']})
        self.assertEqual([s['group'] for s in p['products'][0]['selectedSlots']], ['blue', 'red'])
        self.live[41]['skuList'][0]['priceInfo']['jdPrice'] += 10
        blocked = self.create('pending', '--main-selection', 'remaining-colors', '--from-main-run', str(first))
        p = self.plan(blocked)
        self.assertEqual(p['tasks'], {})
        self.assertEqual(p['exclusions'][0]['reason'], 'original-first-image-awaiting-reconciliation')

    def test_approved_sample_zero_cost_verbatim_then_reject_tampering(self):
        prompt = self.root / 'brief.txt'
        exact = '仅改背景。\r\n保留杯盖、把手和卖点。\r\n'
        prompt.write_bytes(exact.encode())
        pilot = self.create('pilot', '--main-selection', 'per-link', '--products', '41', '--approved-prompt-file', str(prompt))
        p = self.plan(pilot)
        key, = p['tasks']
        source = p['tasks'][key]['sourceKey'] + '.img'
        Image.new('RGB', (40, 40), 'blue').save(pilot / 'sources' / source, 'PNG')
        self.gen.main(['generate.py', str(pilot), '--quote-only'])
        design = self.common.load_json(pilot / 'image-quote.json')['designs'][key]
        self.assertEqual(design['prompt'], exact)
        approved = pilot / 'generated' / (key + '.png')
        Image.new('RGB', (1024, 1024), 'teal').save(approved)
        self.common.save_json(pilot / 'internal-generation.json',
                              {key: {**design, 'status': 'succeeded', 'model': 'fixture', 'outputSha256': file_sha(approved)}})
        bulk = self.create('bulk', '--main-selection', 'per-link', '--products', '41', '--approved-sample', str(approved))
        self.plan(bulk)
        (bulk / 'sources' / source).write_bytes((pilot / 'sources' / source).read_bytes())
        self.gen.main(['generate.py', str(bulk), '--quote-only'])
        quote = self.common.load_json(bulk / 'image-quote.json')
        self.assertEqual((quote['newImageCount'], quote['estimatedCredits'], quote['designs'][key]['prompt']), (0, 0, exact))
        self.gen.main(['generate.py', str(bulk)])
        self.assertTrue((bulk / 'comparisons/41-compare.png').is_file())
        r = self.common.load_json(bulk / 'internal-generation.json')[key]
        self.assertEqual(r['attempts'], 0)
        self.assertEqual(r['outputSha256'], file_sha(approved))
        approved.unlink()  # An archived pilot does not invalidate its verified local copy.
        self.gen.main(['generate.py', str(bulk), '--quote-only'])
        (bulk / 'generated' / approved.name).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '成图已变化'):
            self.gen.main(['generate.py', str(bulk), '--quote-only'])

    def test_legacy_partial_plan_filters_its_unselected_positions(self):
        old = {'products': [{'productId': 41, 'positions': [{'key': 'a'}, {'key': 'b'}]},
                            {'productId': 42, 'positions': [{'key': 'c'}]}], 'tasks': {'a': {'productId': 41}}}
        result = self.common.plan_products(old)
        self.assertEqual([p['productId'] for p in result], [41])
        self.assertEqual(result[0]['positions'], [{'key': 'a'}])
        self.assertEqual(len(old['products'][0]['positions']), 2)
        verify_frozen({}, old)

    def test_merchant_brief_preference_is_shop_scoped_and_never_grants_cost(self):
        from heideng_merchant.cli import build_parser
        from heideng_merchant.image_design import handle
        state = self.root / 'state'
        self.common.save_json(state / 'linker/shops.json', {'profiles': {'cup': SHOP, 'other': {**SHOP, 'shopId': 8}}})
        prompt = self.root / 'approved.txt'
        prompt.write_bytes('保留花纹与标签。\r\n只换背景。'.encode())
        def command(*args):
            parsed = build_parser().parse_args(['image-design', *args])
            return handle(state, parsed)
        saved = command('remember', '--shop-id', '7', '--vender-id', '5', '--preference', 'merchant-first',
                        '--approved-prompt-file', str(prompt), '--source-ref', '老板消息 18')
        self.assertFalse(saved['feeAuthorized'])
        self.assertNotIn('text', saved['approvedPromptEvidence'])
        self.assertFalse(command('show', '--shop-id', '8', '--vender-id', '5')['hasApprovedPrompt'])
        old_entry = self.create('original-entry', '--products', '41', '--scope', 'main')
        self.assertTrue(self.common.load_job(old_entry)['imageDesign']['merchantBriefFirst'])
        wait = self.create('brief-first', '--main-selection', 'per-link', '--products', '41')
        plan = self.plan(wait)
        key, = plan['tasks']
        self.common.save_json(wait / 'host-prompts.json', {key: 'a host proposal'})
        self.assertNotIn('approvedPrompt', self.common.load_job(wait)['mainSelection'])
        with self.assertRaisesRegex(ValueError, '设计要求'):
            self.gen.main(['generate.py', str(wait), '--quote-only'])
        self.assertFalse((wait / 'image-quote.json').exists())
        source = wait / 'sources' / (plan['tasks'][key]['sourceKey'] + '.img')
        Image.new('RGB', (20, 20)).save(source, 'PNG')
        self.gen.main(['generate.py', str(wait), '--quote-only', '--design-brief-file', str(prompt)])
        self.assertEqual(self.common.load_json(wait / 'image-quote.json')['newImageCount'], 1)
        self.assertFalse((wait / 'fee-approval.json').exists())
        again = self.create('reuse', '--main-selection', 'per-link', '--products', '41', '--reuse-approved-prompt')
        spec = self.common.load_job(again)['mainSelection']
        self.assertEqual(spec['approvedPrompt'], prompt.read_bytes().decode())
        self.assertEqual(spec['promptSource']['sourceRef'], '老板消息 18')
        with self.assertRaises(ValueError):
            command('remember', '--shop-id', '7', '--vender-id', '5', '--preference', 'host-design')

    def test_status_and_publish_existing_never_dispatch_generation(self):
        runall = load('run_all')
        for flag, steps in [(['--progress'], ['report']), (['--sample', '10'], ['compare']),
                            (['--reconcile-uploads'], ['upload']), (['--publish-existing'], ['upload', 'patch', 'verify', 'report'])]:
            with self.subTest(flag=flag):
                self.assertEqual(runall.parse_args(['run_all', 'dir', *flag])[0], steps)
        with self.assertRaises(ValueError):
            runall.parse_args(['run_all', 'dir', '--steps', 'generate', '--progress'])
