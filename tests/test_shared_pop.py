import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_shared_pop

ROOT = Path(__file__).resolve().parents[1]


class SharedPopTests(unittest.TestCase):
    def test_status_aliases_share_one_check_and_the_next_call_observes_edits(self):
        from heideng_merchant import mature_runtime as runtime
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'mature/materials'
            entry = source / runtime.ROUTES['materials'][1]
            entry.parent.mkdir(parents=True)
            entry.write_bytes(b'example')
            name = entry.relative_to(source).as_posix()
            metadata = {'entrypoints': [name], 'upstreamVersion': 'test', 'repository': 'fixture',
                        'upstreamCommit': 'fixture', 'files': {name: {'sha256': hashlib.sha256(b'example').hexdigest()}}}
            (source / 'provenance.json').write_text(json.dumps(metadata), encoding='utf-8')
            with patch.object(runtime, 'file_sha', wraps=runtime.file_sha) as digest:
                rows = runtime.status(root)['capabilities']
                self.assertEqual(digest.call_count, 1)
            self.assertEqual({r['capability'] for r in rows if r['matureImplementationReused']},
                             {'materials', 'short-title'})
            entry.write_bytes(b'changed')
            rows = runtime.status(root)['capabilities']
            self.assertEqual([r['status'] for r in rows if r['capability'] in ('materials', 'short-title')],
                             ['mature-source-modified', 'mature-source-modified'])

    def test_recorded_blobs_and_runtime_provenance_agree(self):
        self.assertGreater(sync_shared_pop.verify(json.loads(sync_shared_pop.LOCK.read_bytes())), 0)

    def test_installed_top_sku_build_preserves_source_prices_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            skill = root / '.workbuddy/skills/heideng-ops-agent-merchant'
            state = root / 'merchant'
            subprocess.run([sys.executable, '-B', str(ROOT / 'install.py'), '--home', str(root),
                            '--host', 'workbuddy', '--state', str(state), '--offline', '--no-auto-update'],
                           capture_output=True, check=True, timeout=60)
            attrs = [{'attrId': 3, 'values': [{'attrValue': '5'}]}]
            products, rows = {}, []
            for index, (pid, price) in enumerate(((11, '15.25'), (22, '27.40')), start=1):
                sku = pid * 10
                rows.append({'n': index, 'pid': str(pid), 'skuId': str(sku),
                             'price': price, 'spec': f'样品 {index}'})
                products[str(pid)] = {
                    'productInfo': {'productId': pid, 'brandInfo': {'brandId': 1},
                                    'categoryDetail': {'lastCategoryId': 123}, 'goodsAttrInfos': attrs,
                                    'productDetailDesc': {'desc': f'<p>规格 {index}</p>'},
                                    'length': 2, 'width': 3, 'height': 4, 'weight': 1,
                                    'logisticsInfo': {'transportId': 5, 'promiseId': 6}},
                    'material': {'mainImages': [{'uuid': '0000000000', 'imageInfoList': [
                        {'imgUrl': f'jfs/{pid}/image-{n}.jpg', 'orderSort': n} for n in range(1, 6)]}]},
                    'skuList': [{'skuId': sku, 'priceInfo': {'jdPrice': price},
                                 'goodsAttrInfos': attrs, 'saleAttrs': [{'attrId': 4, 'attrName': '颜色'}]}],
                }
            config = {'venderId': 10, 'shopName': '合成测试店', 'jdoProfile': 'pop-fixture',
                      'categoryId': 123, 'title': '选品草稿', 'topN': len(rows), 'topSkus': rows}
            config_file = root / 'config.json'
            config_file.write_text(json.dumps(config), encoding='utf-8')
            (root / 'source_applies.json').write_text(json.dumps(products), encoding='utf-8')
            result = subprocess.run([sys.executable, '-B', str(skill / 'scripts/merchant.py'),
                                     '--state', str(state), 'run', '--entry', 'scripts/top_sku_aggregation.py',
                                     'listing', '--', 'build', '--config', str(config_file)],
                                    capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            receipt = json.loads(result.stdout)
            manifest = json.loads(Path(receipt['manifestPath']).read_bytes())
            self.assertEqual((receipt['status'], receipt['skuCount']), ('BUILT', 2))
            self.assertEqual(manifest['saveActionType'], 0)
            self.assertIsNone(manifest['applyId'])
            self.assertTrue(manifest['skuDetailManualPending'])
            usage = [json.loads(p.read_bytes()) for p in (state / 'updates/usage').glob('*.json')]
            locked = json.loads(sync_shared_pop.LOCK.read_bytes())['groups']
            self.assertIn(locked['top-sku']['commit'], [r['sharedPopCommits']['top-sku'] for r in usage])
            csv = (root / '新链接对照表.csv').read_text(encoding='utf-8-sig')
            for row in rows:
                self.assertIn(f"{row['price']},{row['price']}", csv)
