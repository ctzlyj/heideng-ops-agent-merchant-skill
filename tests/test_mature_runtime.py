"""Regressions for installed execution, not just registry source labels."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from heideng_merchant.distribution import build_bundle, validate_archive

ROOT = Path(__file__).resolve().parents[1]

class MatureRuntimeTests(unittest.TestCase):
    def test_release_excludes_duplicate_business_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = build_bundle(ROOT, Path(d)/'merchant.zip', (ROOT/'VERSION').read_text().strip())
            _, files = validate_archive(bundle)
            self.assertFalse('heideng_merchant/auth_manager.py' in files)
            self.assertFalse('heideng_merchant/short_title_worker.py' in files)
            self.assertFalse('heideng_merchant/publication_contract.py' in files)
            self.assertIn('heideng_merchant/mature_runtime.py', files)

    def test_missing_mature_source_never_falls_back_to_builtin(self):
        from heideng_merchant.mature_runtime import source_path, MatureSourceUnavailable
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(MatureSourceUnavailable):
                source_path('connection',package_root=Path(d))

    def test_sanitized_child_uses_merchant_only_homes_and_key(self):
        from heideng_merchant.mature_runtime import child_environment
        with tempfile.TemporaryDirectory() as d:
            env = child_environment(Path(d), {'PATH': os.environ.get('PATH',''), 'HOME':'unrelated-home','JD_LLM_API_KEY':'company-marker','GPT_IMAGE2_API_KEY':'legacy-marker', 'LTS4AI_API_KEY':'personal-marker', 'JDO_HOME':'unrelated-jdo','JINGMAI_LINKER_PORT':'8765'})
            self.assertNotIn('JD_LLM_API_KEY', env)
            self.assertNotIn('GPT_IMAGE2_API_KEY', env)
            self.assertNotIn('LTS4AI_API_KEY', env)
            self.assertEqual(env['HEIDENG_MERCHANT_HOME'], str(Path(d).resolve()))
            self.assertEqual(env['JDO_HOME'], str(Path(d).resolve()/'cli-home'/'.jdo-cli'))
            self.assertEqual(env['JDO_CLI_HOME'], env['JDO_HOME'])
            self.assertEqual(env['JINGMAI_LINKER_HOME'], str(Path(d).resolve()/'linker'))
            self.assertNotEqual(env['JINGMAI_LINKER_PORT'], '8765')

    def test_guard_blocks_company_host_but_not_merchant_platform(self):
        from heideng_merchant.mature_runtime import allowed_host
        self.assertFalse(allowed_host('llm-gw.jd.local'))
        self.assertFalse(allowed_host('o2.jd.com'))
        self.assertFalse(allowed_host('joyspace.jd.com'))
        self.assertTrue(allowed_host('api.lts4ai.com'))
        self.assertTrue(allowed_host('mcp-open.jd.com'))
        self.assertTrue(allowed_host('passport.shop.jd.com'))

    def test_installed_package_can_verify_and_repeat_offline_install(self):
        from heideng_merchant.distribution import install_archive
        from heideng_merchant.safety import file_sha
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            import shutil
            source = base/'own-source'
            declaration = json.loads((ROOT/'package-files.json').read_text())
            for name in [*declaration['files'], 'package-files.json']:
                destination = source/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/name, destination)
            bundle = build_bundle(source, base/'merchant.zip', (ROOT/'VERSION').read_text().strip())
            target = base/'skills'/'heideng-ops-agent-merchant'
            install_archive(bundle, target, base/'state', expected_sha=file_sha(bundle))
            result = subprocess.run([sys.executable, str(target/'install.py'), '--skills-dir', str(base/'skills'), '--home', str(base/'home'), '--offline'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr[-1200:])
            self.assertEqual(json.loads(result.stdout)['status'], 'unchanged')

    def test_cancelled_key_dialog_never_runs_business(self):
        from unittest.mock import patch
        from heideng_merchant.merchant_key_ui import with_key
        ran = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), patch(
                'heideng_merchant.merchant_key_ui.read_key', return_value=None), patch(
                'heideng_merchant.merchant_key_ui.prompt_key', return_value=None):
            self.assertEqual(with_key(lambda: ran.append('business'), state=Path(directory)), 2)
        self.assertEqual(ran, [])

    def test_key_wrapper_restores_environment_after_child(self):
        from unittest.mock import patch
        from heideng_merchant.merchant_key_ui import with_key
        observed = []
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True), patch('heideng_merchant.merchant_key_ui.read_key',return_value=None), patch('heideng_merchant.merchant_key_ui.prompt_key', return_value='synthetic-merchant-marker'):
            self.assertEqual(with_key(lambda: observed.append(bool(os.environ.get('HEIDENG_MERCHANT_LTS4AI_API_KEY'))) or 0,state=Path(d)), 0)
            self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY', os.environ)
        self.assertEqual(observed, [True])

    def test_source_shadow_module_is_rejected_before_execution(self):
        import hashlib
        from heideng_merchant.mature_runtime import source_path
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root/'mature'/'listing'
            script = source/'scripts'/'jd_product_pipeline.py'
            script.parent.mkdir(parents=True)
            script.write_text('print("synthetic source fixture")')
            sha = hashlib.sha256(script.read_bytes()).hexdigest()
            meta = {'files':{'scripts/jd_product_pipeline.py':{'sha256':sha}},'entrypoints':['scripts/jd_product_pipeline.py']}
            (source/'provenance.json').write_text(json.dumps(meta))
            self.assertEqual(source_path('listing', package_root=root)[0], script)
            (script.parent/'shadow.py').write_text('raise RuntimeError("never execute")')
            with self.assertRaisesRegex(Exception, 'unregistered-mature-source-file'):
                source_path('listing', package_root=root)

    def test_company_cli_is_blocked_without_reintroducing_obsolete_os_business_gate(self):
        from heideng_merchant.mature_runtime import checked_command
        for command in (['o2', 'launch', 'lingjing'], ['lingjing', 'login'], ['oxygen.exe', 'login']):
            with self.assertRaisesRegex(Exception, 'company-tool-forbidden'):
                checked_command(command, system='Windows')
        # HEAD 0.4.0 already delegated account transport to mature connector; no extra OS gate.
        # Permitting a command is NOT a claim of macOS shop authentication verification.
        checked_command(['jdo-cli', 'status'], system='Darwin')
        checked_command(['python', 'source.py', '--help'], system='Darwin')
        checked_command(['jdo-cli.exe', 'status'], system='Windows')

    def test_audited_chinese_template_survives_bundle_byte_for_byte(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'source'
            declaration = json.loads((ROOT/'package-files.json').read_text())
            for name in [*declaration['files'], 'package-files.json']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/name, path)
            shutil.copytree(ROOT/'mature'/'comparison', root/'mature'/'comparison')
            bundle = build_bundle(root, Path(d)/'template.zip', (ROOT/'VERSION').read_text().strip())
            _, files = validate_archive(bundle)
            name = 'mature/comparison/assets/商品导入价格模板.xlsx'
            self.assertEqual(files[name], (ROOT/name).read_bytes())

    def test_isolated_mature_child_emits_utf8_chinese(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            declaration = json.loads((ROOT/'package-files.json').read_text())
            for name in [*declaration['files'], 'package-files.json']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/name,path)
            script = root/'mature'/'listing'/'scripts'/'stdio_fixture.py'
            script.parent.mkdir(parents=True)
            script.write_text('print("商品主图迁移")',encoding='utf-8')
            result = subprocess.run([sys.executable,'-I',str(root/'scripts/mature_entry.py'),str(script)],capture_output=True)
            self.assertEqual(result.returncode,0)
            self.assertEqual(result.stdout.decode('utf-8').strip(),'商品主图迁移')

    def test_mature_image_does_not_read_company_or_personal_credential_sources(self):
        from unittest.mock import patch
        from heideng_merchant.mature_image import merchant_key
        with patch.dict(os.environ, {'JD_LLM_API_KEY':'company-marker','LTS4AI_API_KEY':'personal-marker'}, clear=True):
            with self.assertRaisesRegex(Exception, 'merchant-lts4ai-key-required'):
                merchant_key()
        with patch.dict(os.environ, {'HEIDENG_MERCHANT_LTS4AI_API_KEY':'merchant-marker'}, clear=True):
            self.assertEqual(merchant_key(), 'merchant-marker')

if __name__ == '__main__': unittest.main()
