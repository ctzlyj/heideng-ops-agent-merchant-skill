"""Hash-backed media readback and streamed batch transfer across an interrupted host."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from heideng_merchant import media_upload
from tests.test_mature_listing import module as listing_module
from tests.test_refresh_selection import load, SCRIPTS


class UploadRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        self.enterContext(patch.dict(sys.modules))
        self.enterContext(patch.object(sys, 'path', [str(SCRIPTS), *sys.path]))
        sys.modules.pop('_common', None)
        self.upload = load('upload')
        self.common = self.upload.common
        self.api = Mock()
        self.enterContext(patch.object(self.common, 'connect', return_value=self.api))
        self.enterContext(patch.object(self.common, 'verify_identity'))
        self.enterContext(patch.object(self.upload, 'media_space', return_value=('zone', 2)))
        self.store = {'profile': 'pop-a', 'shopName': 'fixture', 'venderId': '5'}
        self.common.save_json(self.run / 'job.json', {**self.store, 'productIds': [1], 'uploadConcurrency': 4})
        (self.run / 'generated').mkdir()
        self.rows, self.bytes_by_url = {}, {}
        self.api.get.side_effect = self.lookup
        self.enterContext(patch.object(media_upload, 'matching_original', side_effect=lambda url, digest, size:
                                      len(self.bytes_by_url[url]) == size and sha256(self.bytes_by_url[url]).hexdigest() == digest))

    def lookup(self, _skill, _route, params):
        self.assertEqual((params['zoneId'], params['categoryId']), ('zone', 2))
        return {'data': self.rows.get(params['imgName'], [])}

    def prepare(self, count):
        keys = [f'key-{i}' for i in range(count)]
        self.common.save_json(self.run / 'plan-batch.json', {'tasks': {k: {'productId': 1} for k in keys}})
        self.common.save_json(self.run / 'internal-generation.json', {k: {'status': 'succeeded'} for k in keys})
        for i, k in enumerate(keys):
            Image.new('RGB', (50, 40), (0, i + 1, 70)).save(self.run / 'generated' / (k + '.png'))
        return keys

    def store_bytes(self, name, raw):
        remote = media_upload.platform_image_name(name)
        uri = 'jfs/test/' + remote
        self.rows[Path(remote).stem] = [{'imgName': remote, 'imgSize': len(raw), 'categoryId': 2, 'imgId': remote, 'imgUrl': uri}]
        self.bytes_by_url[uri] = raw
        return {'imgUrl': uri, 'imgId': remote}

    def test_32_transfers_lost_ack_readback_no_second_post(self):
        self.prepare(32)
        def dispatch(_zone, _category, img):
            result = self.store_bytes(img.name, img.read_bytes())
            if img.name == missing_name:
                raise TimeoutError('response lost')
            return result
        raw = (self.run / 'generated/key-0.png').read_bytes()
        missing_name = sha256(raw).hexdigest() + '.png'
        self.api.upload.side_effect = dispatch
        with self.assertRaises(SystemExit):
            self.upload.main(['upload', str(self.run)])
        ledger = self.common.load_json(self.run / 'uploads.json')
        self.assertEqual(sum(r['status'] == 'succeeded' for r in ledger.values()), 31)
        old = ledger['key-0']
        self.assertNotEqual(old['platformName'], old['name'])
        self.upload.main(['upload', str(self.run), '--reconcile-uploads'])
        recovered = self.common.load_json(self.run / 'uploads.json')['key-0']
        self.assertEqual((recovered['status'], recovered['originalStatus'], recovered['uploadSha256']),
                         ('succeeded', 'unknown', sha256(raw).hexdigest()))
        self.assertEqual(self.api.upload.call_count, 32)
        self.assertEqual(len(list((self.run / 'generated').iterdir())), 32)
        self.assertFalse(list(self.run.rglob('request-*.json')))
        self.assertFalse(list(self.run.rglob('upload-*.json')))

    def test_absence_wrong_category_content_or_shop_do_not_authorize_replay(self):
        self.prepare(1)
        self.api.upload.side_effect = TimeoutError('interrupted')
        with self.assertRaises(SystemExit):
            self.upload.main(['upload', str(self.run)])
        ledger_path = self.run / 'uploads.json'
        ledger = self.common.load_json(ledger_path)
        previous = ledger['key-0']
        self.assertEqual(previous['status'], 'unknown')
        raw = (self.run / 'generated/key-0.png').read_bytes()
        outcome = self.store_bytes(previous['name'], raw)
        remote = previous['platformName']
        row = self.rows[Path(remote).stem][0]
        for case in ('absent', 'category', 'bytes', 'shop'):
            with self.subTest(case=case):
                self.rows[Path(remote).stem] = [] if case == 'absent' else [{**row, 'categoryId': 99 if case == 'category' else 2}]
                self.bytes_by_url[outcome['imgUrl']] = bytes(len(raw)) if case == 'bytes' else raw
                self.common.save_json(ledger_path, {'key-0': {**previous, 'shopIdentity': {} if case != 'shop' else {'venderId': '9'}}})
                with self.assertRaisesRegex(RuntimeError, '原素材上传回执'):
                    self.upload.main(['upload', str(self.run)])
                self.assertEqual(self.common.load_json(ledger_path)['key-0']['status'], 'unknown')
        self.api.upload.assert_called_once()

    def test_official_bridge_receives_actual_payload_on_stdin(self):
        cli = listing_module('jdo_listing_mvp')
        probe = listing_module('jdo_bridge_probe')
        runtime = self.run / 'runtime.pyc'
        runtime.write_bytes(b'fixture')
        data = b'synthetic' * 10000
        self.enterContext(patch.object(cli, 'active_jdo_profile', return_value='pop-fixture'))
        shop = self.enterContext(patch.object(cli, 'recheck_verified_jdo_store'))
        self.enterContext(patch.object(cli, 'ensure_jdo_runtime', return_value=runtime))
        self.enterContext(patch.object(probe, 'find_bridge_python', return_value=sys.executable))
        self.enterContext(patch.object(probe, 'probe_runtime', return_value={'ok': True}))
        self.enterContext(patch.object(cli, 'parse_response', return_value={'data': {'imgUrl': 'jfs/image'}}))
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as transport:
            result = cli.upload('zone', 2, media_upload.UploadImage('a' * 64 + '.png', data))
        self.assertEqual(result['imgUrl'], 'jfs/image')
        args = transport.call_args
        self.assertIn('--request-stdin', args.args[0])
        request = json.loads(args.kwargs['input'])
        self.assertEqual((request['profile'], request['params'], request['method']), ('pop-fixture', {'zoneId': 'zone'}, 'POST'))
        self.assertEqual(base64.b64decode(json.loads(request['body'])['imgBase64']), data)
        self.assertNotIn('bodyFile', request)
        shop.assert_called_once()
