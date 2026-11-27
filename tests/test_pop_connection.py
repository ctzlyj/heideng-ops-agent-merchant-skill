from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ConnectionBusinessTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        module = root/'mature/connection' if (root/'scripts/merchant.py').is_file() else root
        self.enterContext(patch.object(sys, 'path', [str(module/'app'), str(root), *sys.path]))
        import importlib.util
        spec = importlib.util.spec_from_file_location('fixture_pop_connection', module/'app/pop_connection.py')
        self.shared = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.shared)
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = root

    def test_lost_response_on_normal_cli(self):
        import runpy
        execute = runpy.run_path(str(Path(__file__).with_name('connection_contract.py')))['execute']
        execute(self.root, merchant=(self.root/'scripts/merchant.py').is_file())

    def test_explicit_original_profile_is_respected(self):
        import re
        observed = {'shopName':'Fixture','shopId':'9','venderId':'200'}
        sl = SimpleNamespace(PROFILE_RE=re.compile('[a-z0-9-]+'), verify_profile=Mock(return_value=observed),
                             assert_profile_proof=Mock(), VerifyError=ValueError)
        result = self.shared.explicit_profile(sl, {**observed,'profile':'second','status':'ready',
                                              'shopId':'19'}, 'original', 'Fixture')
        self.assertEqual(('mismatch','original'), (result['status'],result['profile']))
        sl.verify_profile.assert_called_once_with('original')
        self.assertTrue(self.shared.original_target({'profile':'original','jobId':'one','query':'Fixture'},
                                                     'original','one','Fixture'))

    def test_wrong_origin_and_two_concurrent_calls_cannot_create_a_second_request(self):
        seen = []
        entered, release = threading.Event(), threading.Event()
        def send(path, payload):
            seen.append(payload['authorizationRequestId'])
            entered.set()
            release.wait(5)
            raise subprocess.TimeoutExpired('fixture',1)
        sl = SimpleNamespace(linker_home=lambda:self.home, load_pending=lambda:{}, save_pending=Mock())
        data = {'profile':'fixture-alpha', 'shopName':'Alpha', 'venderId':'11'}
        results = []
        worker = threading.Thread(target=lambda:results.append(self.shared.dispatch(sl, send, data, {}, requested_profile=data['profile'])))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            second = self.shared.dispatch(sl, send, data, {}, requested_profile=data['profile'])
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(second['errorKind'], 'result_unknown')
        self.assertEqual(results[0]['errorKind'], 'result_unknown')
        self.assertEqual(len(seen), 1)
        self.assertFalse(sl.save_pending.called)
        other = self.shared.dispatch(sl, send, {**data, 'venderId':'22'}, {}, requested_profile=data['profile'])
        self.assertEqual(other['errorKind'], 'result_unknown')
        self.assertEqual(len(seen), 1)
        self.shared.settle_ready(sl, {**data, 'venderId':'22','status':'ready'}, 'Alpha', data['profile'])
        self.assertTrue(self.shared._client(self.home, data['profile']).exists())

    def test_native_reuse_is_bound_to_this_profile_and_home(self):
        data = {'ok':True,'command':'login','cliVersion':'0.3.7','profile':'fixture','home':str(self.home),
                'timestamp':100,'authorizationStatus':'reused_existing_credentials','authorizationStage':'credential_reuse',
                'alreadyAuthorized':True,'reusedAuthorization':True,'loginCompleted':True,'appKeyConfigured':True,
                'appSecretStored':True,'tokenStored':True,'tokenMocked':False,'authorizeUrlPrinted':False}
        self.assertTrue(self.shared.reuse_receipt(data, 'fixture', self.home))
        self.assertFalse(self.shared.reuse_receipt(data, 'other', self.home))
        self.assertFalse(self.shared.reuse_receipt(data, 'fixture', self.home/'other'))
        self.assertFalse(self.shared.reuse_receipt({**data,'tokenMocked':True}, 'fixture', self.home))

    def test_scan_completion_observes_original_context_once(self):
        job = SimpleNamespace(stage='waiting_login', status='waiting', _cancelled=threading.Event(),
            _workspace_check_requested=threading.Event(), _workspace_check_handled=False, browser=Mock())
        job.browser.observe.return_value = {'loggedIn':False}
        for _ in range(2):
            self.assertTrue(self.shared.signal_workspace_check(job))
            self.assertFalse(self.shared.observe_workspace(job)['loggedIn'])
        job.browser.check_workspace_after_login.assert_called_once_with()
        self.assertEqual(job.browser.observe.call_count, 2)
        job.status = 'success'
        self.assertFalse(self.shared.signal_workspace_check(job))


if __name__ == '__main__':
    unittest.main()
