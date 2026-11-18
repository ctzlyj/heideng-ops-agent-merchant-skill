"""Installation adapter: use isolated interpreter and reviewed public requirements."""
import hashlib, json, os, subprocess, sys, tempfile, unittest, venv
from pathlib import Path
from unittest.mock import patch

class RuntimeDependencyTests(unittest.TestCase):
    def test_prepared_venv_is_selected_and_ignores_host_site(self):
        from heideng_merchant.runtime_dependencies import runtime_python
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.assertEqual(runtime_python(state), Path(sys.executable))
            venv.EnvBuilder(with_pip=False).create(state/'runtime-venv')
            interpreter = runtime_python(state)
            self.assertNotEqual(interpreter, Path(sys.executable))
            result = subprocess.run([str(interpreter), '-I', '-c', 'import sys,json;print(json.dumps({"prefix":sys.prefix,"base":sys.base_prefix}))'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(Path(data['prefix']).resolve(), (state/'runtime-venv').resolve())
            self.assertNotEqual(data['prefix'], data['base'])

    def test_invalid_existing_runtime_never_falls_back_to_global_python(self):
        from heideng_merchant.runtime_dependencies import runtime_python
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            (state/'runtime-venv').mkdir()
            with self.assertRaisesRegex(Exception,'merchant-runtime-invalid'):
                runtime_python(state)

    def test_vendored_requirements_cannot_add_index_or_private_dependency_url(self):
        from heideng_merchant.runtime_dependencies import requirements_for_sources
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root/'mature'/'listing'
            source.mkdir(parents=True)
            req = source/'requirements.txt'
            for content in ('--index-url https://company.invalid/simple\n', 'requests @ https://company.invalid/x.whl\n'):
                req.write_text(content)
                sha=hashlib.sha256(req.read_bytes()).hexdigest()
                (source/'provenance.json').write_text(json.dumps({'files':{'requirements.txt':{'sha256':sha}}}))
                with self.assertRaisesRegex(Exception,'standard-public-package-requirement-required'):
                    requirements_for_sources(root)
            req.write_text('requests>=2.32,<3\nPillow>=10,<13\n')
            sha=hashlib.sha256(req.read_bytes()).hexdigest()
            (source/'provenance.json').write_text(json.dumps({'files':{'requirements.txt':{'sha256':sha}}}))
            self.assertEqual(requirements_for_sources(root), ['Pillow>=10,<13', 'requests>=2.32,<3'])

    def test_standard_public_cpu_extra_is_supported_without_arbitrary_install_flags(self):
        from heideng_merchant.runtime_dependencies import requirements_for_sources
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'mature/materials';source.mkdir(parents=True)
            path=source/'requirements.txt';path.write_text('rembg[cpu]==2.0.85\n')
            (source/'provenance.json').write_text(json.dumps({'files':{'requirements.txt':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}}))
            self.assertEqual(requirements_for_sources(root),['rembg[cpu]==2.0.85'])

    def test_cutout_weight_preparation_uses_existing_offline_business_free_entry(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'state';target=Path(d)/'package'
            completed=SimpleNamespace(returncode=0,stdout='{"status":"prepared","model":"birefnet-general-lite"}',stderr='')
            try:
                from heideng_merchant.runtime_dependencies import prepare_cutout_weights
                with patch('heideng_merchant.runtime_dependencies.runtime_python',return_value=Path(sys.executable)),patch('heideng_merchant.runtime_dependencies.subprocess.run',return_value=completed) as run:
                    result=prepare_cutout_weights(state,target)
            except (ImportError,AttributeError) as error:self.fail(f'安装期需要复用现有权重准备入口：{error}')
            command=run.call_args.args[0]
            self.assertIn('prepare-cutout',command);self.assertIn('--download',command)
            self.assertIn(str(target/'mature/materials/scripts/jd_material_agent.py'),command)
            self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',run.call_args.kwargs['env'])
            self.assertEqual(result['status'],'prepared');self.assertEqual(result['model'],'birefnet-general-lite')


    def test_core_install_does_not_force_optional_neural_cutout_stack(self):
        from heideng_merchant.runtime_dependencies import requirements_for_sources
        root=Path(__file__).resolve().parents[1]
        self.assertFalse(any(x.startswith('rembg') for x in requirements_for_sources(root)))
        self.assertIn('rembg[cpu]==2.0.85',requirements_for_sources(root,optional='cutout'))
        self.assertEqual((root/'mature/materials/requirements-cutout.txt').read_text(encoding='utf-8').strip(),'rembg[cpu]==2.0.85')

if __name__=='__main__':unittest.main()
