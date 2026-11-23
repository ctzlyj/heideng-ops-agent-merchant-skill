"""The local sample stage keeps the SKU, base pixels, and readable artwork together."""
from io import BytesIO
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image

from heideng_merchant.overlay_preview import preview, verify_pilot_preview
from heideng_merchant.safety import SafetyError, file_sha


class OverlayPreviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / '包袋 样图'
        self.root.mkdir()
        base = Image.new('RGB', (120, 90), (140, 60, 32))
        base.save(self.root / 'base.jpg')
        art = Image.new('RGBA', (6, 4), 'blue')
        art.paste('red', (0, 0, 3, 4))
        art.save(self.root / 'art.png')
        self.plan = {'target': {'shopId': '11', 'venderId': '32', 'productId': '600', 'skuId': '751'},
                     'source': {'file': 'base.jpg'},
                     'layers': [{'file': 'art.png', 'box': [6, 6, 12, 10], 'mirror': True},
                                {'file': 'art.png', 'box': [12, 12, 18, 16]}],
                     'compareBox': [0, 0, 24, 24]}
        self.spec = self.root / 'design.json'

    def save(self):
        self.spec.write_text(json.dumps(self.plan), encoding='utf-8')
        return self.spec

    def test_cli_lossless_two_layers_and_old_preview_survives_revision(self):
        state = self.root / 'state'
        merchant = Path(__file__).resolve().parents[1] / 'scripts' / 'merchant.py'
        result = subprocess.run([sys.executable, '-I', '-B', str(merchant), '--state', str(state),
                                 'preview-overlay', '--plan', str(self.save())], check=True, capture_output=True,
                                env={**os.environ, 'HEIDENG_MERCHANT_HOME': str(state)})
        first = json.loads(result.stdout)
        self.assertEqual((first['status'], first['platformWrites'], first['paidRequests']), ('local-preview', 0, 0))
        with Image.open(first['previewPath']) as out, Image.open(self.root / 'base.jpg') as base:
            self.assertEqual(out.size, base.size)
            self.assertEqual(out.crop((24, 24, 120, 90)).convert('RGB').tobytes(),
                             base.crop((24, 24, 120, 90)).tobytes())
            self.assertEqual(out.getpixel((6, 6))[:3], (0, 0, 255))
            self.assertEqual(out.getpixel((12, 12))[:3], (255, 0, 0))
        with Image.open(first['comparisonPath']) as comparison:
            self.assertEqual(comparison.size, (48, 24))
            self.assertNotEqual(comparison.getpixel((6, 6)), comparison.getpixel((30, 6)))
        self.assertEqual(first['source']['sha256'], file_sha(self.root / 'base.jpg'))
        self.assertEqual(preview(self.spec)['previewPath'], first['previewPath'])
        self.plan['layers'][0]['box'] = [48, 48, 54, 52]
        self.assertNotEqual(preview(self.save())['previewPath'], first['previewPath'])
        self.assertTrue(Path(first['previewPath']).is_file())

    def test_image_space_link_keeps_exact_bytes_even_for_small_files(self):
        actual = 'https://img10.360buyimg.com/imgzone/jfs/sample/bag.jpg'
        raw = (self.root / 'base.jpg').read_bytes()
        fetch = Mock(return_value=raw)
        self.plan['target']['galleryUrl'] = 'jfs/sample/bag.jpg'
        self.plan['source'] = {'url': actual, 'sha256': file_sha(self.root / 'base.jpg')}
        result = preview(self.save(), fetch=fetch)
        fetch.assert_called_once_with(actual)
        self.assertEqual((Path(result['receiptPath']).parent / 'source.img').read_bytes(), raw)
        self.assertEqual(result['source']['bytes'], len(raw))
        self.plan['source']['url'] = actual.replace('/imgzone/', '/n12/')
        different = BytesIO()
        Image.new('RGB', (120, 90), 'black').save(different, format='PNG')
        with self.assertRaisesRegex(ValueError, '底图内容'):
            preview(self.save(), fetch=lambda _: different.getvalue())
        self.plan['target']['galleryUrl'] = 'jfs/sample/another-sku.jpg'
        with self.assertRaisesRegex(ValueError, '资源标识不同'):
            preview(self.save(), fetch=fetch)
        fetch.assert_called_once_with(actual)

    def test_padded_box_preserves_aspect_ratio_and_rejects_invalid_inputs(self):
        self.plan['layers'] = [{'file': 'art.png', 'crop': [0, 0, 3, 4], 'box': [12, 12, 24, 36]}]
        result = preview(self.save())
        self.assertEqual(result['layers'][0]['placedBox'], [12, 16, 24, 32])
        Path(result['previewPath']).write_bytes(b'broken')
        with self.assertRaisesRegex(SafetyError, '原样图'):
            preview(self.spec)
        self.plan['layers'][0]['crop'] = [0, 0, 7, 4]
        with self.assertRaisesRegex(ValueError, '超出原图'):
            preview(self.save())
        self.plan['layers'][0]['file'] = '../external.png'
        with self.assertRaises(SafetyError):
            preview(self.save())

    def test_pilot_checks_original_target_and_sample_file(self):
        self.plan['target']['galleryUrl'] = 'jfs/sample/bag.jpg'
        output = preview(self.save())
        path = Path(output['previewPath'])
        store = {'shopId': 11, 'venderId': 32}
        verify_pilot_preview(path, store, 600, 751, 'jfs/sample/bag.jpg')
        for wrong in ((store, 600, 752), (store, 601, 751), ({**store, 'shopId': 12}, 600, 751)):
            with self.assertRaisesRegex(ValueError, 'SKU 与本次试发不一致'):
                verify_pilot_preview(path, *wrong, 'jfs/sample/bag.jpg')
        with self.assertRaisesRegex(ValueError, '图源不一致'):
            verify_pilot_preview(path, store, 600, 751, 'jfs/sample/new.jpg')
        with self.assertRaisesRegex(ValueError, 'preview.png'):
            verify_pilot_preview(output['comparisonPath'], store, 600, 751, 'jfs/sample/bag.jpg')
        verify_pilot_preview(self.root / 'base.jpg', store, 600, 751, 'jfs/sample/bag.jpg')
