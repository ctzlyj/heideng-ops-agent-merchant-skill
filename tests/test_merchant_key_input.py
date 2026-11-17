import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from heideng_merchant.safety import SafetyError

class MerchantKeyTests(unittest.TestCase):
    def test_preflight_failure_never_opens_key_input_or_runs_business(self):
        from heideng_merchant import merchant_key_ui as ui
        action=Mock();preflight=Mock(side_effect=SafetyError('runtime-unavailable'))
        with patch.object(ui,'prompt_key') as prompt:
            with self.assertRaises(SafetyError):ui.with_key(action,preflight=preflight)
        prompt.assert_not_called();action.assert_not_called()

    def test_loopback_form_refuses_wrong_host_origin_and_csrf(self):
        from heideng_merchant.merchant_key_ui import KeyInputSession
        session=KeyInputSession(43111)
        for host,origin,csrf in [('foreign.invalid','http://127.0.0.1:43111',session.csrf),('127.0.0.1:43111','https://foreign.invalid',session.csrf),('127.0.0.1:43111','http://127.0.0.1:43111','wrong')]:
            with self.assertRaises(SafetyError):session.accept(host,origin,csrf,'fixture-only',False)
        self.assertIsNone(session.value)
        session.accept('127.0.0.1:43111','http://127.0.0.1:43111',session.csrf,'fixture-only',False)
        self.assertEqual(session.value,'fixture-only');self.assertFalse(session.remember)
        with self.assertRaises(SafetyError):session.accept('127.0.0.1:43111','http://127.0.0.1:43111',session.csrf,'second',False)

    def test_saved_merchant_key_skips_repeat_prompt_but_environment_is_restored(self):
        from heideng_merchant import merchant_key_ui as ui
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{},clear=True),patch.object(ui,'read_key',return_value='fixture-only'),patch.object(ui,'prompt_key') as prompt:
            value=ui.with_key(lambda: os.environ['HEIDENG_MERCHANT_LTS4AI_API_KEY'],state=Path(d))
            self.assertEqual(value,'fixture-only');prompt.assert_not_called();self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',os.environ)

    def test_runtime_preflight_runs_no_business_entry_and_injects_no_key(self):
        from heideng_merchant.mature_runtime import preflight
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.mature_runtime.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')) as run:
            preflight('materials',['auto-maintain','--profile','fixture'],state=Path(d))
        self.assertIn('runtime_preflight.py',' '.join(run.call_args.args[0]))
        self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',run.call_args.kwargs['env'])

    def test_missing_core_is_transparently_prepared_before_task_without_key_or_login(self):
        from heideng_merchant.runtime_dependencies import ensure_core
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.runtime_dependencies.subprocess.run',side_effect=[SimpleNamespace(returncode=1),SimpleNamespace(returncode=0)]) as probe,patch('heideng_merchant.runtime_dependencies.prepare_runtime',return_value={'status':'prepared'}) as prepare:
            result=ensure_core(Path(d),Path(__file__).resolve().parents[1])
        self.assertEqual(result['status'],'ready');prepare.assert_called_once()
        self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',probe.call_args.kwargs['env'])

    def test_actual_loopback_password_page_accepts_one_form_without_key_echo(self):
        from heideng_merchant.merchant_key_ui import _prompt_local_page
        import threading,urllib.request,urllib.parse
        errors=[]
        def browser(url,new):
            def submit():
                try:
                    base=urllib.parse.urlsplit(url);csrf=urllib.parse.parse_qs(base.query)['session'][0]
                    page=urllib.request.urlopen(url).read()
                    self.assertIn(b'type=password',page);self.assertNotIn(b'fixture-key',page)
                    form=urllib.parse.urlencode({'csrf':csrf,'key':'fixture-key','remember':'yes'}).encode()
                    req=urllib.request.Request(f'http://{base.netloc}/key',data=form,headers={'Origin':f'http://{base.netloc}','Content-Type':'application/x-www-form-urlencoded'})
                    body=urllib.request.urlopen(req).read();self.assertNotIn(b'fixture-key',body)
                except Exception as error:errors.append(error)
            thread=threading.Thread(target=submit,daemon=True);thread.start();return True
        with patch('webbrowser.open',side_effect=browser):value,remember=_prompt_local_page(timeout=3)
        self.assertFalse(errors,errors);self.assertEqual(value,'fixture-key');self.assertTrue(remember)

    @unittest.skipUnless(os.name=='nt','Windows DPAPI test only')
    def test_windows_storage_is_os_protected_and_never_plaintext(self):
        from heideng_merchant.merchant_key_store import read_key,store_key,forget_key
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);store_key(state,'fixture-only-not-a-real-api-key')
            self.assertEqual(read_key(state),'fixture-only-not-a-real-api-key')
            for p in state.rglob('*'):
                if p.is_file():self.assertNotIn(b'fixture-only-not-a-real-api-key',p.read_bytes())
            forget_key(state);self.assertIsNone(read_key(state))

if __name__=='__main__':unittest.main()
