"""Portable regressions for Mac reports. No live shop or credential access."""
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from heideng_merchant.cli_diagnostics import compare_connection_failure, public_cli_check
from tests.test_mature_connection import SOURCE, load


class OfficialReleaseIntegrityTests(unittest.TestCase):
    """A synthetic macOS CLI archive in a disposable merchant state; never run its program."""
    def setUp(self):
        from hashlib import sha256
        from io import BytesIO
        import tarfile
        from heideng_merchant.official import BASE, POLICY, OfficialClient

        self.state=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.payload={'bin/jdo-cli':b'synthetic official CLI','templates/oauth-success.html':b'page'}
        self.payload.update({f'skills/sample-{n}/SKILL.md':str(n).encode() for n in range(63)})
        data=BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as archive:
            for name,body in self.payload.items():
                entry=tarfile.TarInfo(name)
                entry.mode=0o755 if name=='bin/jdo-cli' else 0o644
                entry.size=len(body)
                archive.addfile(entry,BytesIO(body))
        archive=data.getvalue()
        path='cli/releases/0.3.7/fixture.tar.gz'
        self.release={'version':'0.3.7','path':path,'sha256':sha256(archive).hexdigest(),
                      'format':'tar.gz','executable':'bin/jdo-cli'}
        self.policy={'product':'jdo-cli','stableVersion':'0.3.7','artifacts':{'binaries':{'macos-arm64':self.release}}}
        self.responses={BASE+path:archive,POLICY:json.dumps(self.policy).encode()}
        self.client=OfficialClient(self.state,download=self.responses.__getitem__,platform_name='macos-arm64')
        self.client.install()
        self.original=json.loads(self.client.receipt_path.read_bytes())
        self.program=self.state/self.original['root']

    def test_complete_legacy_receipt_verifies_all_files_and_keeps_unknown_files(self):
        (self.program/'personal.txt').write_bytes(b'personal')
        # Unchanged installations created by 0.4.23 have this same receipt schema.
        result=self.client.install()
        self.assertEqual((result['status'],result['releaseFilesVerified']),('unchanged',65))
        self.assertEqual(json.loads(self.client.receipt_path.read_bytes()),self.original)
        self.assertEqual((self.program/'personal.txt').read_bytes(),b'personal')

    def test_missing_and_changed_official_members_restore_a_clean_tree_beside_old_files(self):
        (self.program/'templates/oauth-success.html').unlink()
        changed=self.program/'skills/sample-51/SKILL.md'
        changed.write_bytes(b'customised content')
        private=self.program/'my-note.txt'
        private.write_bytes(b'local')
        state_receipt=self.state/'linker/unknown.json'
        state_receipt.parent.mkdir()
        state_receipt.write_bytes(b'{"status":"unknown"}')
        self.assertTrue(self.client.ready())
        result=self.client.install()
        self.assertTrue(result['repaired'])
        self.assertEqual(result['releaseFilesVerified'],65)
        new=self.state/json.loads(self.client.receipt_path.read_bytes())['root']
        self.assertNotEqual(new,self.program)
        self.assertEqual({p.relative_to(new).as_posix():p.read_bytes() for p in new.rglob('*') if p.is_file()},self.payload)
        self.assertEqual((changed.read_bytes(),private.read_bytes(),state_receipt.read_bytes()),(b'customised content',b'local',b'{"status":"unknown"}'))
        self.assertEqual(self.client.install()['status'],'unchanged')

    @unittest.skipIf(os.name=='nt','native POSIX execute bits')
    def test_lost_execute_permission_blocks_business_probe_and_is_restored(self):
        from heideng_merchant.safety import SafetyError
        old_exe=self.client.executable()
        old_exe.chmod(0o644)
        self.assertFalse(self.client.ready())
        with self.assertRaises(SafetyError):
            self.client.executable()
        self.assertTrue(self.client.install()['repaired'])
        self.assertTrue(os.access(self.client.executable(),os.X_OK))
        self.assertEqual(old_exe.stat().st_mode & 0o777,0o644)

    def test_same_length_change_to_an_official_note_is_detected_by_content(self):
        name='skills/sample-22/SKILL.md'
        (self.program/name).write_bytes(b'XX')
        self.assertTrue(self.client.install()['repaired'])
        new=self.state/json.loads(self.client.receipt_path.read_bytes())['root']
        self.assertEqual((new/name).read_bytes(),self.payload[name])
        self.assertEqual((self.program/name).read_bytes(),b'XX')

    def test_repair_checks_original_archive_before_changing_active_receipt(self):
        from heideng_merchant.official import BASE
        from heideng_merchant.safety import SafetyError
        (self.program/'templates/oauth-success.html').unlink()
        original=self.client.receipt_path.read_bytes()
        self.responses[BASE+self.release['path']]=b'wrong archive'
        with self.assertRaisesRegex(SafetyError,'official-sha256-mismatch'):
            self.client.install()
        self.assertEqual(self.client.receipt_path.read_bytes(),original)

    def test_connector_install_repairs_managed_cli_without_reinitializing_shop(self):
        with patch.object(sys,'path',[str(SOURCE/'app'),*sys.path]):
            sl=load('fixture_integrity_shoplib',SOURCE/'app/shoplib.py')
        (self.program/'templates/oauth-success.html').unlink()
        with patch.dict(os.environ,HEIDENG_MERCHANT_HOME=str(self.state)), \
                patch.object(sl,'find_jdo',return_value=self.client.executable()), \
                patch('heideng_merchant.official.OfficialClient',return_value=self.client) as constructor:
            result=sl.install_jdo()
            constructor.assert_called_once_with(self.state)
        self.assertTrue(result['ok'] and result['repaired'])
        self.assertFalse(result['installed'])  # The existing configuration has its original binding.
        self.assertEqual(result['releaseFilesVerified'],65)


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

    def test_joined_pre_oauth_attempt_remains_identifiable_after_pending_switch(self):
        import browser_auth
        sl = self.sl
        shop = {'shopName':'同名灯具店','venderId':'33','shopId':'99','lastVerifiedAt':1}
        sl.save_registry({'profiles':{'fixture-live':shop}})
        browser = Mock()
        browser.observe.return_value = {'loggedIn':False,'identity':{}}
        flow = browser_auth.BrowserAuthJob('fixture-old',shop['shopName'],browser=browser,
                                         browser_config={'provider':'host'},poll_interval=.005)
        for name in ('fixture-live',flow.profile):
            sl.write_json(sl.profiles_dir()/(name+'.json'),{'shop_name':shop['shopName']})
        def verify(profile):
            if profile == flow.profile:
                raise sl.VerifyError('auth_missing','synthetic missing')
            return shop
        flow.start()
        try:
            deadline = time.monotonic()+2
            while flow.stage != 'waiting_login' and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(flow.stage,'waiting_login')
            self.assertTrue(flow.shutdown(timeout=2))
        finally:
            flow.cancel()
        browser.open_oauth.assert_not_called()
        closed = sl._proof_data()['preOAuthClosures'][flow.id]
        self.assertEqual((closed['profile'],closed['status'],closed['outcome']),(flow.profile,'closed','login_timeout'))
        sl.save_pending({'profile':'unrelated','query':'other','jobId':'later','processRunning':True})
        result=sl.resolve(shop['shopName'],verify=verify)
        self.assertEqual((result['status'],result['unconnectedAttempts']),('ready',[flow.profile]))
        self.assertTrue((sl.profiles_dir()/(flow.profile+'.json')).exists())
        for kind in ('network','permission','auth_expired'):
            with self.subTest(kind=kind):
                self.assertEqual(sl.resolve(shop['shopName'],verify=Mock(side_effect=sl.VerifyError(kind,'synthetic')))['status'],'ambiguous')
        # Resuming the same job invalidates its earlier closure as evidence for today's lookup.
        sl.mark_auth_pending(flow.profile,flow.id,shop_name=shop['shopName'])
        self.assertEqual(sl._proof_data()['preOAuthClosures'][flow.id]['status'],'resumed')
        self.assertEqual(sl.resolve(shop['shopName'],verify=verify)['status'],'ambiguous')
        # An older pending proof with no durable close is still insufficient, even with auth_missing.
        sl.mark_auth_pending(flow.profile,'new-attempt',shop_name=shop['shopName'])
        self.assertEqual(sl.resolve(shop['shopName'],verify=verify)['status'],'ambiguous')

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
        error = json.dumps({'networkError': "[Errno 2] No such file or directory: '/private/test/opt/certifi/cacert.pem'"})
        with patch('subprocess.run', side_effect=[subprocess.CompletedProcess([], 0, 'help', ''),
                                                  subprocess.CompletedProcess([], 2, error, '')]):
            failure = public_cli_check(client)
        self.assertEqual((failure['stage'], failure['errno'], failure['resourceNamedByCli']),
                         ('public-https', 2, 'certifi/cacert.pem'))
        self.assertNotIn('/private', json.dumps(failure))

    def test_missing_file_adds_read_only_comparison_to_the_same_connection_receipt(self):
        binary = self.root / 'official-cli'
        binary.touch()
        other = self.root / 'other-cli'
        other.touch()
        original = {'status':'paused', 'jobId':'fixture-job', 'errorKind':'callback_unknown',
                    'cliRuntimeError':'runtime-file-missing'}
        with patch('heideng_merchant.official.OfficialClient') as factory, patch(
                'heideng_merchant.cli_diagnostics.public_cli_check', return_value={'status':'verified'}) as probe:
            factory.return_value.platform_name = 'macos-arm64'
            factory.return_value.executable.return_value = binary
            self.assertEqual(compare_connection_failure(original, self.root, other), original)
            probe.assert_not_called()
            result = compare_connection_failure(original, self.root, binary)
            self.assertEqual(result['officialCliCheck']['status'], 'verified')
            self.assertEqual(result['status'], 'paused')
            self.assertEqual(result['jobId'], original['jobId'])
            self.assertFalse(result['retryAllowed'])
            probe.assert_called_once()
