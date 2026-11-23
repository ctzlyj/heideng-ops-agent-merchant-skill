"""A fake native CLI owns a real callback socket; the disposable host kills its auth caller."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT/'workbuddy-jd-connector/card.py'


def load_card():
    spec = importlib.util.spec_from_file_location('jd_card_probe', CARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_native(port, args):
    home = Path(os.environ['JDO_HOME'])
    directory = home/'profiles'
    config = home/'config.json'
    if 'init' in args:
        profile = args[args.index('--profile')+1]
        directory.mkdir(parents=True, exist_ok=True)
        (directory/(profile+'.json')).write_text('{}')
        config.write_text(json.dumps({'default_profile':profile}))
        print('{"ok":true}')
        return
    profile = json.loads(config.read_bytes())['default_profile']
    marker = home/'fake-auth-result'
    missing_token = home/'token-cleared'
    expired = home/'expired'
    account = 'token:'+profile+':0123456789abcdef:default'
    if args[0] == 'login':
        assert args[args.index('--profile')+1] == profile and '--no-browser' in args
        if marker.exists():
            assert '--force' in args
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',port))
            listener.listen(1)
            print('https://open-oauth.jd.com/oauth2/to_login?synthetic=1', flush=True)
            conn, _ = listener.accept()
            with conn:
                assert conn.recv(16) == b'fixture'
        marker.write_text('yes')
        expired.unlink(missing_ok=True)
        missing_token.unlink(missing_ok=True)
        print(json.dumps(dict(ok=True,command='login',profile=profile,home=str(home),loginCompleted=True,
                              tokenStored=True,tokenMocked=False,tokenCredentialAccount=account)))
    elif args[0] == 'status':
        actual = 'other-profile' if (home/'wrong-profile').exists() else profile
        print(json.dumps(dict(ok=True,home=str(home),defaultProfile=actual,
            profile={'exists':True, 'path':str(directory/(actual+'.json'))},
            credentialInputs={'oauthTokenStored':marker.exists() and not missing_token.exists(),'oauthTokenMocked':False,
                              'oauthExpiresAtMs':int(time.time()*1000)+(-1000 if expired.exists() else 3600000)},
            credentialStore={'tokenCredentialAccount':account,'appSecretStored':marker.exists()})))
    elif args[0] == 'invoke':
        assert '--profile='+profile in args and marker.exists()
        print(json.dumps({'success':True,'data':{'venderId':52,
              'shopBaseInfo':{'shopName':'Example','shopId':81,'status':1,'type':0}}}))
    elif args[:2] == ['auth','logout']:
        assert args[args.index('--profile')+1] == profile
        notified = marker.exists()
        marker.unlink(missing_ok=True)
        config.write_text(json.dumps({'default_profile':''}))
        print(json.dumps({'ok':True,'profile':profile,'deletedCredentials':[
            {'type':'token','account':account,'deleted':notified},
            {'type':'appSecret','account':'appsecret:'+profile+':0123456789abcdef','deleted':notified}]}))
    else:
        raise AssertionError('unexpected native command')


def fixture_card(port, args):
    base = [sys.executable,'-I','-B',str(Path(__file__).resolve())]
    return load_card().main(args,native_command=[*base,'--fake-native',str(port)],
                            worker_command=[*base,'--fake-card',str(port)],callback_port=port)


class CardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        with socket.socket() as s:
            s.bind(('127.0.0.1',0))
            self.port = s.getsockname()[1]
        self.command = [sys.executable,'-I','-B',str(Path(__file__).resolve()),'--fake-card',str(self.port),
                        '--state',str(self.root),'--core',str(ROOT)]

    def invoke(self, *args, success=True):
        proc = subprocess.run([*self.command,*args],stdin=subprocess.DEVNULL,capture_output=True,
                              encoding='utf-8',timeout=30)
        self.assertEqual(proc.returncode, 0 if success else 2, proc.stdout+proc.stderr)
        return json.loads(proc.stdout)

    def begin(self, expected='52'):
        caller = subprocess.Popen([*self.command,'auth','--expect-vender-id',expected], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,encoding='utf-8')
        self.addCleanup(caller.stdout.close)
        began = time.monotonic()
        line = caller.stdout.readline()
        try:
            self.assertEqual(line.strip(),'https://open-oauth.jd.com/oauth2/to_login?synthetic=1')
            self.assertLess(time.monotonic()-began,10)
        finally:
            caller.kill()
            caller.wait(timeout=4)

    def complete_callback(self):
        with socket.create_connection(('127.0.0.1',self.port),timeout=2) as conn:
            conn.sendall(b'fixture')
        deadline = time.monotonic()+12
        while time.monotonic()<deadline:
            value = json.loads((self.root/'jd-card/current.json').read_bytes())
            if value['status'] != 'pending':
                return value
            time.sleep(.1)
        self.fail('fixture native callback did not finish')

    def test_card_job_survives_host_exit_then_scoped_disconnect(self):
        self.assertEqual(self.invoke('status',success=False)['status'],'not-connected')
        self.assertEqual(self.invoke('prepare')['status'],'prepared')
        self.begin()
        pending = json.loads((self.root/'jd-card/current.json').read_bytes())
        self.begin()
        reused = json.loads((self.root/'jd-card/current.json').read_bytes())
        self.assertEqual((pending['attempt'],pending['handoffPort']),(reused['attempt'],reused['handoffPort']))
        self.assertEqual(self.invoke('status',success=False)['status'],'pending')
        self.assertEqual(self.complete_callback()['status'],'ready')
        result = self.invoke('status')
        self.assertEqual((result['shopId'],result['venderId']), ('81','52'))
        self.assertEqual(self.invoke('identity')['profile'],result['profile'])
        cli_home = self.root/'cli-home/.jdo-cli'
        (cli_home/'wrong-profile').touch()
        self.assertEqual(self.invoke('identity',success=False)['status'],'official-profile-mismatch')
        self.assertEqual(self.invoke('unAuth',success=False)['status'],'official-profile-mismatch')
        self.assertTrue((cli_home/'fake-auth-result').exists())
        self.assertFalse(self.invoke('status',success=False)['matched'])
        (cli_home/'wrong-profile').unlink()
        result = self.invoke('unAuth')
        self.assertEqual(result['remoteRevocation'],'unverified')
        self.assertFalse((cli_home/'fake-auth-result').exists())
        self.assertFalse(self.invoke('identity',success=False)['matched'])
        self.assertEqual(self.invoke('unAuth')['status'],'disconnected')

    def test_wrong_shop_never_appears_connected(self):
        self.begin(expected='999')
        self.assertEqual(self.complete_callback()['status'],'identity-mismatch')
        self.assertFalse(self.invoke('status',success=False)['matched'])
        self.assertEqual(self.invoke('unAuth')['status'],'disconnected')

    def test_expired_proven_profile_reconnects_without_manual_logout(self):
        self.begin()
        original = self.complete_callback()
        cli_home = self.root/'cli-home/.jdo-cli'
        self.assertEqual(self.invoke('auth',success=False)['status'],'already-connected')
        (cli_home/'expired').touch()
        (cli_home/'wrong-profile').touch()
        self.assertEqual(self.invoke('auth',success=False)['status'],'official-profile-mismatch')
        (cli_home/'wrong-profile').unlink()
        self.assertEqual(self.invoke('status',success=False)['reason'],'token-expired')
        self.begin(expected='')
        renewed = self.complete_callback()
        self.assertEqual((renewed['status'],renewed['profile'],renewed['identity']),
                         ('ready',original['profile'],original['identity']))
        (cli_home/'token-cleared').touch()
        self.assertEqual(self.invoke('status',success=False)['reason'],'token-cleared')
        self.begin(expected='')
        self.assertEqual(self.complete_callback()['identity'],original['identity'])
        self.assertEqual(self.invoke('unAuth')['status'],'disconnected')

    def test_url_must_be_a_complete_official_url(self):
        parse = load_card().authorization_url
        good = 'https://open-oauth.jd.com/oauth2/to_login?synthetic=1'
        self.assertEqual(parse('请打开 '+good),good)
        for text in ('https://other.invalid/?target='+good, good+'#fragment',
                     good.replace('.com/','.com.other.invalid/'),good.replace('https:','http:'),
                     good.split('?')[0], good+' '+good):
            with self.subTest(text=text):
                self.assertIsNone(parse(text))

    def test_prepare_installs_only_when_absent_and_ignores_unrelated_profiles(self):
        module = load_card()
        card = module.Card(self.root,ROOT)
        with patch('heideng_merchant.official.OfficialClient') as factory:
            client = factory.return_value
            client.receipt_path = self.root/'no-install-yet'
            client.executable.return_value = Path('synthetic-jdo')
            with patch.object(card,'_init_native'):
                self.assertEqual(card.prepare()['status'],'prepared')
                self.assertEqual(card.prepare()['status'],'prepared')
            client.install.assert_called_once_with()
        other_state = self.root/'different'
        other = module.Card(other_state,ROOT,native_command=['no-such-cli'])
        other.home.mkdir(parents=True)
        other.config.write_text('{"default_profile":"unrelated"}')
        with self.assertRaisesRegex(module.CardError,'dedicated-cli-home-required'):
            other.prepare()
        self.assertFalse(other.receipt.exists())

    def test_disconnect_preserves_uncertain_native_state(self):
        self.invoke('prepare')
        marker = self.root/'jd-card/current.json'
        record = json.loads(marker.read_bytes())
        record['nativeLoginStarted'] = True
        marker.write_text(json.dumps(record))
        for _ in range(2):
            self.assertEqual(self.invoke('unAuth',success=False)['status'],'cannot-confirm-callback-stopped')
            self.assertFalse(self.invoke('identity',success=False)['matched'])
        record = json.loads(marker.read_bytes())
        record['nativeLoginFinished'] = True
        marker.write_text(json.dumps(record))
        (self.root/'cli-home/.jdo-cli/profiles'/(record['profile']+'.json')).unlink()
        self.assertEqual(self.invoke('unAuth',success=False)['status'],'cannot-prove-local-logout-scope')

    def test_concurrent_disconnect_fences_pending_callback(self):
        self.begin()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:self.invoke('unAuth'), range(2)))
        self.assertEqual([result['status'] for result in results],['disconnected']*2)
        self.assertFalse(self.invoke('identity',success=False)['matched'])
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',self.port))


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fake-native':
        fake_native(int(sys.argv[2]),sys.argv[3:])
    elif len(sys.argv)>1 and sys.argv[1]=='--fake-card':
        rc = fixture_card(int(sys.argv[2]),sys.argv[3:])
        # Emulate the platform terminating a still-running launcher immediately after the URL.
        if 'auth' in sys.argv[3:] and rc==0:
            threading.Event().wait(10)
        raise SystemExit(rc)
    else:
        unittest.main()
