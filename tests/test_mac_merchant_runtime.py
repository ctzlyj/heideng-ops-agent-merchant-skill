"""Portable regressions for Mac reports. No live shop or credential access."""
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from heideng_merchant.cli_diagnostics import public_cli_check
from tests.test_mature_connection import SOURCE, load


class MerchantMacRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'JDO_HOME': str(self.root / 'jdo'),
                                                  'JINGMAI_LINKER_HOME': str(self.root / 'linker')}))
        self.enterContext(patch.object(sys, 'path', [str(SOURCE / 'app'), *sys.path]))
        self.server = load('fixture_mac_runtime', SOURCE / 'app/server.py')
        self.sl = self.server.sl

    def test_exact_shop_discards_only_proven_unconnected_attempt(self):
        identity = {'shopName': '示例灯具', 'venderId': '313', 'shopId': '919'}
        registry = {'profiles': {'shop-live': {**identity, 'lastVerifiedAt': 1234}}}
        for name in ('shop-live', 'shop-old'):
            self.sl.write_json(self.sl.profiles_dir() / (name + '.json'), {'shop_name': identity['shopName']})
        self.sl.save_registry(registry)
        def verify(name):
            if name == 'shop-old':
                raise self.sl.VerifyError('auth_missing', 'missing')
            return identity
        result = self.sl.resolve(identity['shopName'], verify=verify)
        self.assertEqual((result['status'], result['profile'], result['unconnectedAttempts']),
                         ('ready', 'shop-live', ['shop-old']))
        self.assertTrue((self.sl.profiles_dir() / 'shop-old.json').exists())
        for error in ('network', 'auth_expired', 'permission'):
            self.assertEqual(self.sl.resolve(identity['shopName'], verify=Mock(
                side_effect=self.sl.VerifyError(error, 'fixture')))['status'], 'ambiguous')
        self.sl.save_pending({'profile': 'shop-old', 'jobId': 'previous', 'outcome': 'callback_unknown',
                              'processRunning': False})
        self.assertEqual(self.sl.resolve(identity['shopName'], verify=verify)['status'], 'ambiguous')

    def test_login_parses_only_stdout_and_diagnoses_stderr_without_exposing_it(self):
        job = self.server.LoginJob('shop-live', '示例灯具')
        job.proc = Mock()
        job.proc.wait.return_value = 1
        job._reader(StringIO('{"ok":true,"tokenStored":true}\n'), True)
        job._reader(StringIO('ssl.create_default_context\nFileNotFoundError: /private/sys-path\n'), True)
        self.assertEqual(job._raw_output, [])
        job._monitor()
        self.assertEqual(job.error_kind, 'tls-runtime-file-missing')
        self.assertNotIn('private', json.dumps(job.to_dict()))
        self.assertFalse(job.log)
        self.assertEqual(job._stderr, [])

    @unittest.skipIf(os.name == 'nt', 'POSIX child process')
    def test_cancel_stops_owned_posix_process_and_releases_its_listener(self):
        import socket
        child = "import socket,time;s=socket.socket();s.bind(('127.0.0.1',0));s.listen();print(s.getsockname()[1],flush=True);time.sleep(45)"
        job = self.server.LoginJob('shop-live', '示例灯具')
        with subprocess.Popen([sys.executable, '-c', child], stdout=subprocess.PIPE, text=True,
                              start_new_session=True) as proc:
            try:
                job.proc = proc
                job._owns_process_group = True
                port = int(proc.stdout.readline())
                job.cancel()
                self.assertIsNotNone(proc.poll())
                self.assertEqual(job.status, 'cancelled')
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_public_probe_uses_empty_home_and_requires_an_uncached_official_receipt(self):
        client = Mock(platform_name='macos-arm64', receipt_path=self.root / 'official.json')
        client.receipt_path.write_text(json.dumps({'version':'0.3.7','archiveSha256':'a'*64,'executableSha256':'b'*64}))
        client.executable.return_value = self.root / 'official'
        receipt = {'command':'update check','ok':True,'cacheUsed':False,'cliVersion':'0.3.7',
                   'versionPolicy':{'product':'jdo-cli'}}
        def run(argv, **kwargs):
            self.assertNotIn('login', argv)
            self.assertNotEqual(kwargs['env']['JDO_HOME'], os.environ['JDO_HOME'])
            self.assertFalse(Path(kwargs['env']['JDO_HOME']).exists())
            return subprocess.CompletedProcess(argv, 0, json.dumps(receipt), 'unrelated diagnostic')
        with patch('subprocess.run', side_effect=run):
            self.assertEqual(public_cli_check(client)['status'], 'verified')
            receipt['cacheUsed'] = True
            self.assertEqual(public_cli_check(client)['reason'], 'public-receipt-unverified')
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'semctl: operation not permitted')):
            self.assertEqual(public_cli_check(client)['reason'], 'local-execution-permission')
