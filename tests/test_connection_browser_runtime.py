"""Offline preflight and recovery contracts for a local browser connection."""
from argparse import Namespace
from contextlib import ExitStack
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from heideng_merchant import host_connection_controller as controller
from heideng_merchant import mature_runtime, runtime_dependencies as deps
from heideng_merchant.safety import SafetyError


ROOT = Path(__file__).resolve().parents[1]


class ConnectionBrowserRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME': str(self.state),
                                                       'HEIDENG_MANAGED_CONNECTION_RUNTIME': '1'}))
        self.stack.enter_context(patch.object(sys, 'path', [str(ROOT/'mature/connection/scripts'),
                                                           str(ROOT/'mature/connection/app'), *sys.path]))

    def test_ready_no_auth_and_host_provided_browser_skip_dependency_preparation(self):
        cli = importlib.import_module('linker')
        args = Namespace(shop='fixture',profile=None,no_auth=False,no_open=False,no_wait=True,
                         resume=False,browser_config=None,timeout=5)
        with patch.object(cli, '_env_blockers', return_value=None), patch.object(cli.sl, 'load_pending', return_value={}), \
                patch.object(cli.sl, 'resolve', return_value={'status':'ready'}) as resolve, \
                patch.object(deps, 'connection_python_problem', return_value=74) as probe, \
                patch.object(cli, 'api') as api:
            self.assertEqual(cli._cmd_ensure_shop(args)['status'], 'ready')
            resolve.return_value = {'status':'needs_auth','suggestedProfile':'fixture-profile'}
            args.no_auth = True
            self.assertEqual(cli._cmd_ensure_shop(args)['status'], 'needs_auth')
            args.no_auth = False
            with patch.object(cli, 'ensure_embedded_server') as server, self.assertRaises(SystemExit) as denied:
                cli._cmd_ensure_shop(args, 5)
            self.assertEqual(denied.exception.code, 74)
            probe.assert_called_once()
            api.assert_not_called()
            server.assert_not_called()
            cli.check_browser_python({'provider':'host'})
            probe.assert_called_once()

    def test_parent_repairs_only_reserved_pre_job_result_and_exactly_once(self):
        with patch.object(mature_runtime, '_run_with_lease', side_effect=[75, 0]) as child, \
                patch.object(deps, 'prepare_runtime') as repair:
            self.assertEqual(mature_runtime.run('connection',['browser-check'],state=self.state),0)
            self.assertEqual(child.call_count,2)
            repair.assert_called_once_with(self.state, ROOT, optional='connection-browser')
        with patch.object(mature_runtime, '_run_with_lease', side_effect=[74, 76]), \
                patch.object(deps, 'prepare_runtime') as repair, self.assertRaisesRegex(SafetyError,'playwright'):
            mature_runtime.run('connection',['ensure-shop'],state=self.state)
        repair.assert_called_once()
        with patch.object(mature_runtime, '_run_with_lease', return_value=1), patch.object(deps, 'prepare_runtime') as repair:
            self.assertEqual(mature_runtime.run('connection',['ensure-shop'],state=self.state),1)
            repair.assert_not_called()

    def test_dependency_probe_uses_process_prefix_and_loads_native_modules(self):
        with patch.object(sys, 'prefix', str(self.state)):
            self.assertEqual(deps.connection_python_problem(self.state),73)
        real = importlib.import_module
        for module, code in [('greenlet',74), ('cryptography.hazmat.primitives.asymmetric.ed25519',75),
                             ('playwright.sync_api',76)]:
            def load(name):
                if name == module:
                    raise ImportError('wrong architecture')
                return Mock() if name in ('greenlet','cryptography.hazmat.primitives.asymmetric.ed25519','playwright.sync_api') else real(name)
            with self.subTest(module=module), patch.object(sys, 'prefix', str(self.state/'runtime-venv')), \
                    patch.object(importlib, 'import_module', side_effect=load):
                self.assertEqual(deps.connection_python_problem(self.state),code)
        requirements = deps.requirements_for_sources(ROOT, 'connection-browser')
        self.assertEqual({x.split('>')[0].lower() for x in requirements}, {'cryptography','playwright'})

    def test_launch_diagnoses_permissions_missing_channel_and_driver_without_exposing_raw_details(self):
        cases = [('driver', OSError('driver IPC closed secret=fixture'), 'browser_driver_failed'),
                 ('channel', RuntimeError("Executable doesn't exist at /private/example"), 'browser_channel_missing'),
                 ('channel', RuntimeError('bootstrap_check_in com.google.Chrome.Crashpad ... Permission denied (1100)'), 'browser_host_permission'),
                 ('channel', RuntimeError('unexpected browser crash'), 'browser_channel_launch_failed')]
        for phase, error, expected in cases:
            with self.subTest(expected=expected):
                ctrl = controller.HostConnectionController(state=self.state)
                launcher = Mock()
                if phase == 'driver':
                    launcher.return_value.start.side_effect = error
                else:
                    launcher.return_value.start.return_value.chromium.launch_persistent_context.side_effect = error
                with patch('playwright.sync_api.sync_playwright',launcher), self.assertRaises(controller.BrowserStartError) as failed:
                    ctrl._launch('chrome')
                self.assertEqual(failed.exception.kind,expected)
                self.assertNotIn('secret=',failed.exception.hint)
                self.assertIsNone(ctrl.context)

    def test_builtin_prepares_and_opens_only_one_browser_in_its_owned_profile(self):
        adapters = importlib.import_module('browser_adapters')
        launcher = Mock()
        launch = launcher.return_value.start.return_value.chromium.launch_persistent_context
        page = Mock(url='about:blank')
        page.is_closed.return_value = False
        launch.return_value.pages = [page]
        with patch('playwright.sync_api.sync_playwright',launcher):
            browser = adapters.BuiltinBrowser({'shopName':'fixture'})
            browser.prepare_launch()
            page.goto.assert_not_called()
            browser.open_login('fixture')
            browser.close()
        launcher.return_value.start.assert_called_once()
        launch.assert_called_once()
        self.assertTrue(launch.call_args.kwargs['chromium_sandbox'])
        self.assertTrue(Path(launch.call_args.args[0]).is_relative_to(self.state/'browser-profiles'))
        self.assertEqual(page.goto.call_args.args,(controller.LOGIN_URL,))

    def test_permission_denial_is_reported_before_waiting_or_starting_oauth(self):
        auth = importlib.import_module('browser_auth')
        sl = importlib.import_module('shoplib')
        browser = Mock()
        browser.prepare_launch.side_effect = controller.BrowserStartError('browser_host_permission')
        factory = Mock()
        job = auth.BrowserAuthJob('fixture','fixture','',browser=browser,login_factory=factory)
        with patch.object(sl,'mark_auth_pending') as pending:
            job.run()
        self.assertEqual((job.stage,job.error_kind),('checking_browser_runtime','browser_host_permission'))
        self.assertEqual(job.status,'failed')
        pending.assert_not_called()
        browser.open_login.assert_not_called()
        factory.assert_not_called()

    def test_local_check_uses_only_a_temporary_blank_page(self):
        launcher = Mock()
        launch = launcher.return_value.start.return_value.chromium.launch_persistent_context
        page = Mock(url='about:blank');page.is_closed.return_value=False;page.evaluate.return_value=4
        launch.return_value.pages = [page]
        with patch('playwright.sync_api.sync_playwright',launcher):
            value = controller.check_local_browser('chrome')
        self.assertTrue(value['ok'])
        self.assertFalse(value['merchantLoginStarted'])
        self.assertTrue(launch.call_args.kwargs['offline'])
        self.assertEqual(page.goto.call_args.args,('about:blank',))
        self.assertFalse(Path(launch.call_args.args[0]).exists())
        launch.return_value.close.assert_called_once()
