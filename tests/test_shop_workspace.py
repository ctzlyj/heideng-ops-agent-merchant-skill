"""The CLI profile, merchant-owned browser and observed storefront are separate sources of evidence."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from heideng_merchant import host_connection_controller as host, shop_workspace as workspace
from heideng_merchant.mature_runtime import merchant_profile_directory, registered_browser_profile
from heideng_merchant.safety import atomic_json
from tests import test_audit_connection_contracts as fixtures


class WindowsHttpsChoiceTests(unittest.TestCase):
    def test_default_https_executable_wins_and_unknown_progid_never_selects_edge(self):
        winreg = MagicMock()
        winreg.QueryValueEx.return_value = ('CustomBrowserHTML',1)
        shell = Mock()
        def chrome(flags, field, protocol, verb, output, size):
            output.value = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
            return 0
        with tempfile.TemporaryDirectory() as directory, patch.object(host,'os',Mock(name='windows')), patch(
                'ctypes.WinDLL',create=True,return_value=shell), patch.dict(sys.modules,{'winreg':winreg}):
            host.os.name = 'nt'
            ctrl = host.HostConnectionController(state=directory)
            shell.AssocQueryStringW.side_effect = chrome
            self.assertEqual(ctrl._default_channel(),'chrome')
            winreg.QueryValueEx.assert_not_called()
            shell.AssocQueryStringW.side_effect = None
            shell.AssocQueryStringW.return_value = 1
            self.assertEqual(ctrl._default_channel(),'chrome')
            self.assertEqual(ctrl._default_reason,'supported-browser-default')


class ShopWorkspaceTests(unittest.TestCase):
    def setUp(self):
        fixtures.AuditConnectionTests.setUp(self)
        self.addCleanup(fixtures.AuditConnectionTests.tearDown,self)
        self.sl = self.cli.sl
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':str(self.root),'HOME':str(self.root),
            'USERPROFILE':str(self.root),'JDO_HOME':str(self.root/'official'),'JINGMAI_LINKER_HOME':str(self.root/'linker')}))
        self.shop = {'shopName':'星河器具店','shopId':'301','venderId':'101'}
        self.other = {'shopName':'青杉器具店','shopId':'302','venderId':'102'}
        self.stores = {'fixture-a':self.shop,'fixture-b':self.other}
        self.sl.save_registry({'profiles':{key:{**value,'lastVerifiedAt':1} for key,value in self.stores.items()}})
        self.enterContext(patch.object(self.sl,'verify_profile',side_effect=lambda profile:dict(self.stores[profile])))
        self.enterContext(patch.object(self.sl,'_desktop_browser',return_value=Path(sys.executable)))
        self.desktop = self.root.parent/(self.root.name+'-desktop')
        self.desktop.mkdir()
        self.addCleanup(self.remove_desktop)
        self.enterContext(patch.object(self.sl,'_merchant_desktop',return_value=self.desktop))
        def write(path, command, owner):
            if path.exists() and path.read_text() == owner:
                return 'existing'
            path.write_text(owner)
            return 'created'
        self.writer = self.enterContext(patch.object(self.sl,'_write_browser_shortcut',side_effect=write))
        self.enterContext(patch.object(host.HostConnectionController,'_default_channel',return_value='chrome'))
        self.launcher = self.enterContext(patch('playwright.sync_api.sync_playwright'))
        self.launch = self.launcher.return_value.start.return_value.chromium.launch_persistent_context
        self.context = self.launch.return_value
        self.page = Mock(url='about:blank')
        self.page.is_closed.return_value = False
        self.context.pages = [self.page]
        self.navigations = []
        self.on_workspace = True
        self.observed = dict(self.shop)
        def go(url, **options):
            self.navigations.append(url)
            self.page.url = url if self.on_workspace else host.LOGIN_URL
        self.page.goto.side_effect = go
        def evaluate(script, *args):
            if 'const selectors' in script:
                return [self.observed['shopName']]
            if 'const fields' in script:
                return {k:self.observed[k] for k in ('shopId','venderId') if k in self.observed}
            return None
        self.page.evaluate.side_effect = evaluate

    def remove_desktop(self):
        for item in self.desktop.iterdir():
            item.unlink()
        self.desktop.rmdir()

    def run_workspace(self, profile='fixture-a',shop=None,channel=None,progress=None):
        return workspace.ensure_workspace(self.sl,profile,shop or self.shop['shopName'],channel,1,progress or (lambda event:None))

    def test_window_coordinates_allow_real_left_monitor_but_detect_an_unusable_sliver(self):
        primary=(0,0,1920,1080)
        left=(-1920,0,0,1080)
        old=(-1425,32,30,900)
        self.assertFalse(self.sl._window_on_screen(old,[primary]))
        self.assertTrue(self.sl._window_on_screen(old,[left,primary]))
        self.assertFalse(self.sl._window_on_screen((-32000,-32000,-31400,-31000),[left,primary]))

    def test_wrong_profile_and_explicit_ensure_shop_never_return_another_ready_store(self):
        outcome = self.run_workspace(profile='fixture-b')
        self.assertEqual(outcome['status'],'mismatch')
        with patch.object(self.cli,'_env_blockers',return_value=None), patch.object(self.sl,'resolve',
                return_value={'ok':True,'status':'ready','profile':'fixture-a',**self.shop}):
            args = type('Args',(),{'shop':self.shop['shopName'],'profile':'fixture-b','no_auth':True})()
            self.assertEqual(self.cli._cmd_ensure_shop(args)['status'],'mismatch')
        self.launch.assert_not_called()
        self.writer.assert_not_called()

    def test_empty_and_shared_directories_are_never_web_proof(self):
        registry = self.sl.load_registry()
        directory = self.root/'browser-profiles'/'shared'
        directory.mkdir(parents=True)
        for name in ('fixture-a','fixture-b'):
            registry['profiles'][name].update(browserProfileDir=str(directory),browserChannel='msedge')
        self.sl.save_registry(registry)
        self.assertIsNone(registered_browser_profile('fixture-a',self.shop))
        self.assertEqual(self.sl.create_verified_desktop_shortcut('fixture-a',self.shop['shopName'])['reason'],'shop-browser-profile-conflict')
        registry['profiles']['fixture-b'].pop('browserProfileDir')
        self.sl.save_registry(registry)
        self.assertEqual(self.sl.create_verified_desktop_shortcut('fixture-a',self.shop['shopName'])['reason'],'shop-browser-verification-required')
        self.assertIsNone(merchant_profile_directory(directory.parent))
        self.assertIsNone(merchant_profile_directory(''))
        self.writer.assert_not_called()
        # A hand-written empty directory also cannot pick Edge or be adopted when repairing the shop.
        result = self.run_workspace()
        self.assertTrue(result['webLoginVerified'])
        self.assertNotEqual(result['browserProfileDir'],str(directory))
        self.assertEqual(result['browserChannel'],'chrome')

    def test_stale_alias_cannot_take_precedence_over_another_official_shop_name(self):
        registry = self.sl.load_registry()
        registry['profiles']['fixture-a']['aliases'] = [self.other['shopName']]
        self.sl.save_registry(registry)
        self.assertEqual(self.run_workspace(shop=self.other['shopName'])['status'],'ambiguous')
        self.launch.assert_not_called()

    def test_verified_web_binding_changes_browser_only_with_separate_profile(self):
        first = self.run_workspace(channel='msedge')
        self.assertEqual(first['status'],'web-verified')
        old = Path(first['browserProfileDir'])
        first_proof = json.loads((old/workspace.MARKER).read_bytes())
        self.assertEqual(first_proof['shopId'],self.shop['shopId'])
        self.page.url = 'about:blank'
        second = self.run_workspace(channel='chrome')
        self.assertEqual(second['status'],'web-verified')
        self.assertEqual(second['browserChannel'],'chrome')
        self.assertNotEqual(second['browserProfileDir'],str(old))
        self.assertEqual(json.loads((old/workspace.MARKER).read_bytes()),first_proof)
        self.assertEqual(self.sl.load_registry()['profiles']['fixture-b']['shopId'],'302')
        self.page.url = 'about:blank'
        third = self.run_workspace()
        self.assertEqual(third['browserProfileDir'],second['browserProfileDir'])
        self.assertEqual(self.launch.call_args.kwargs['channel'],'chrome')

    def test_same_display_name_wrong_numeric_id_never_creates_a_shortcut(self):
        self.observed = {**self.shop,'shopId':self.other['shopId']}
        result = self.run_workspace()
        self.assertEqual(result['status'],'mismatch')
        self.assertTrue(result['officialReady'])
        self.assertFalse(result['webLoginVerified'])
        self.assertNotIn('browserProfileDir',self.sl.load_registry()['profiles']['fixture-a'])
        self.writer.assert_not_called()
        self.context.close.assert_called_once()
        wrong_directory = self.launch.call_args.args[0]
        self.observed = dict(self.shop)
        recovered = self.run_workspace()
        self.assertTrue(recovered['webLoginVerified'])
        self.assertNotEqual(recovered['browserProfileDir'],wrong_directory)

    def test_explicit_channel_never_opens_another_channels_existing_session(self):
        initial = host.HostConnectionController(state=self.root,shop_identity=self.shop)
        initial._launch('msedge')
        edge = initial.profile
        initial._close()
        replacement = host.HostConnectionController(state=self.root,shop_identity=self.shop)
        replacement._launch('chrome')
        try:
            self.assertEqual(replacement.channel,'chrome')
            self.assertNotEqual(edge,replacement.profile)
            self.assertEqual(json.loads(initial._state_path.read_bytes())['browserChannel'],'msedge')
        finally:
            replacement._close()

    def test_merchant_reports_scan_done_and_original_job_checks_same_page(self):
        self.on_workspace = False
        jobs = []
        def scanned(event):
            self.assertEqual(self.navigations,[host.WORKSPACE_URL])
            self.on_workspace = True
            jobs.append(event['jobId'])
            self.assertTrue(self.cli.cmd_login_completed(type('Args',(),{'job_id':jobs[0]})())['ok'])
        result = self.run_workspace(progress=scanned)
        self.assertTrue(result['webLoginVerified'])
        self.assertEqual(self.navigations,[host.WORKSPACE_URL,host.WORKSPACE_URL])
        self.context.new_page.assert_not_called()
        self.assertFalse(workspace.signal_login(jobs[0])['ok'])
        read_only = self.sl._public('fixture-a',self.shop,self.sl.load_registry()['profiles']['fixture-a'])
        self.assertEqual(read_only['webLoginStatus'],'not-checked')
        self.assertTrue(read_only['lastWebVerificationAt'])

    def test_legacy_exact_session_can_be_reverified_without_adopting_another_store(self):
        registry = self.sl.load_registry()
        directory = self.root/'browser-profiles'/'owned-legacy'
        directory.mkdir(parents=True)
        registry['profiles']['fixture-a'].update(browserProfileDir=str(directory),browserChannel='msedge')
        self.sl.save_registry(registry)
        legacy = host.HostConnectionController(state=self.root,shop_identity=self.shop)
        atomic_json(legacy._state_path,{'shopIdentity':self.shop,'profileDir':str(directory),
                                       'browserChannel':'msedge','contextId':'owned'})
        result = self.run_workspace()
        self.assertEqual((result['status'],result['browserProfileDir'],result['browserChannel']),
                         ('web-verified',str(directory),'msedge'))
