"""Only merchant connector adaptation; no actual OAuth or native credential reads."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mature' / 'connection'

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class MatureConnectionTests(unittest.TestCase):
    def setUp(self):
        self.old_path=list(sys.path)
        self.old_modules={name:sys.modules.get(name) for name in ('shoplib','redaction','browser_auth','browser_adapters')}
        sys.path.insert(0, str(SOURCE/'app'))
        for name in self.old_modules:sys.modules.pop(name,None)
    def tearDown(self):
        sys.path[:]=self.old_path
        for name,old in self.old_modules.items():
            sys.modules.pop(name,None)
            if old is not None:sys.modules[name]=old
    def test_dispatch_resolves_actual_mature_connector(self):
        from heideng_merchant.mature_runtime import source_path
        entry,provenance=source_path('connection')
        self.assertEqual(entry,SOURCE/'scripts/linker.py')
        self.assertEqual(provenance['upstreamCommit'],'1c438fc5419cd86f709cc4a501325782fd4a1e36')
        self.assertEqual(provenance['license'],'owner-authorized-distribution')
        self.assertIn('scripts/browser_bridge.py',provenance['entrypoints'])
    def test_ready_existing_authorization_never_starts_server_or_connects(self):
        from argparse import Namespace
        cli=load('merchant_test_linker',SOURCE/'scripts/linker.py')
        ready={'status':'ready','profile':'merchant-existing','venderId':'fixture-vender','shopName':'fixture-shop'}
        with patch.object(cli,'_env_blockers',return_value=None), patch.object(cli.sl,'resolve',return_value=ready), patch.object(cli,'api',side_effect=AssertionError('ready must not authorize')):
            result=cli.cmd_ensure_shop(Namespace(shop='fixture-shop',profile=None,no_auth=False))
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['profile'],ready['profile'])
    def test_permission_hint_has_no_employee_platform(self):
        sl=load('merchant_test_shoplib',SOURCE/'app/shoplib.py')
        text=sl.permission_hint()
        self.assertNotIn('joyspace',text.lower())
        self.assertNotIn('采销',text)
        self.assertIn('京麦',text)
    def test_paths_use_isolated_namespace_not_personal_home(self):
        from heideng_merchant.mature_runtime import child_environment
        sl=load('merchant_test_shoplib',SOURCE/'app/shoplib.py')
        with tempfile.TemporaryDirectory() as d:
            env=child_environment(Path(d),{'PATH':os.environ.get('PATH',''),'JDO_HOME':'personal-home'})
            with patch.dict(os.environ,env,clear=True):
                self.assertEqual(sl.jdo_home(),Path(d)/'cli-home'/'.jdo-cli')
                self.assertEqual(sl.linker_home(),Path(d)/'linker')
                generated=sl.suggest_profile_name('fixture-shop')
                self.assertTrue(generated.startswith('hm-'),generated)
    def test_macos_listener_inspection_uses_no_socket_probe(self):
        import subprocess
        sl=load('merchant_test_shoplib',SOURCE/'app/shoplib.py')
        with patch.object(sl.os,'name','posix'),patch.object(sl.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'4242\n',b'')) as run:
            self.assertEqual(sl.port_owner(9001)[0],4242)
            self.assertEqual(run.call_args.args[0][:2],['lsof','-nP'])
            self.assertNotIn('connect',str(run.call_args))
    def test_only_owned_same_context_profile_directory_can_be_handed_to_pop(self):
        import time
        from heideng_merchant.mature_runtime import child_environment
        adapter=load('merchant_test_browser_adapters',SOURCE/'app/browser_adapters.py')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,child_environment(Path(d)),clear=True):
            directory=Path(d)/'browser-profiles'/'fixture';directory.mkdir(parents=True)
            browser=adapter.HostBrowser()
            browser._pending={'action':{'id':'fixture-action','kind':'open_login'},'deadline':time.monotonic()+10}
            result={'contextId':'fixture-context','owned':True,'isolated':True,'profileDir':str(directory)}
            self.assertEqual(browser.report('fixture-action',result)['status'],'accepted')
            self.assertEqual(browser.profile_directory,directory.resolve())
            browser._pending={'action':{'id':'next-action','kind':'observe'},'deadline':time.monotonic()+10}
            rejected=browser.report('next-action',{**result,'contextId':'unrelated-context'})
            self.assertEqual(rejected['status'],'rejected')
            self.assertEqual(browser.profile_directory,directory.resolve())

    def test_install_quiesces_owned_idle_connector_via_original_shutdown(self):
        import subprocess, time, urllib.request
        from heideng_merchant.mature_runtime import child_environment
        from heideng_merchant.installation_guard import quiesce_mature_connector
        with tempfile.TemporaryDirectory() as d:
            env=child_environment(Path(d));port=env['JINGMAI_LINKER_PORT']
            command=[sys.executable,'-I','-B',str(ROOT/'scripts/mature_entry.py'),str(SOURCE/'app/server.py'),'--port',port,'--no-clipboard']
            proc=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:'+port+'/api/health',timeout=1) as response:
                            health=json.loads(response.read())
                        if health.get('ok'):break
                    except OSError:time.sleep(.1)
                else:self.fail('original connector service did not start')
                quiesce_mature_connector(ROOT,Path(d))
                proc.wait(timeout=8)
                self.assertEqual(proc.returncode,0)
            finally:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=5)

    def test_background_connector_starts_through_same_sanitized_source_launcher(self):
        cli=load('merchant_test_linker',SOURCE/'scripts/linker.py')
        with patch.dict(os.environ,{'HEIDENG_MERCHANT_PACKAGE':str(ROOT)}),patch.object(cli,'server_info',side_effect=[None,{'version':cli.expected_version()}]),patch.object(cli.subprocess,'Popen') as spawn:
            self.assertTrue(cli.ensure_server())
        argv=spawn.call_args.args[0]
        self.assertEqual(argv[1:3],['-I','-B'])
        self.assertEqual(Path(argv[3]),ROOT/'scripts/mature_entry.py')
        self.assertEqual(Path(argv[4]),SOURCE/'app/server.py')

    def test_merchant_installer_delegates_existing_verified_official_download(self):
        sl=load('merchant_test_shoplib',SOURCE/'app/shoplib.py')
        from heideng_merchant.official import OfficialClient
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}),patch.object(sl,'find_jdo',return_value=None),patch.object(OfficialClient,'install',return_value={'status':'installed'}) as install,patch.object(OfficialClient,'executable',return_value=Path(d)/'jdo/bin/jdo-cli.exe'):
            result=sl.install_jdo()
        install.assert_called_once()
        self.assertTrue(result['ok'])
        self.assertTrue(result['installed'])

if __name__=='__main__':unittest.main()
