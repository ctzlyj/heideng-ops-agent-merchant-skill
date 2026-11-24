"""Public Git installs and verified transitions with the existing archive format."""
import hashlib
from contextlib import contextmanager,redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from heideng_merchant import SKILL_NAME, VERSION
from heideng_merchant import distribution, update_client
from heideng_merchant.safety import SafetyError, file_sha
from scripts.audit_release import audit_payload

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def mac_placeholder(path):
    """Inject Darwin metadata only; catch any premature read on any CI host."""
    import heideng_merchant
    path = Path(path).absolute()
    stat_before, open_before = Path.stat, Path.open

    class Flagged:
        st_flags = 0x40000000

        def __init__(self, metadata):
            self.metadata = metadata

        def __getattr__(self, key):
            return getattr(self.metadata,key)

    def metadata(item, *args, **kwargs):
        result = stat_before(item,*args,**kwargs)
        return Flagged(result) if item.absolute()==path else result

    def checked_open(item, *args, **kwargs):
        if item.absolute()==path:
            raise AssertionError('attempted to read or overwrite a dataless file')
        return open_before(item,*args,**kwargs)

    with patch.object(heideng_merchant,'MACOS',True), patch.object(Path,'stat',metadata), patch.object(Path,'open',checked_open):
        yield


class MacPlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def assert_blocked(self, command, placeholder):
        output = io.StringIO()
        with mac_placeholder(placeholder), redirect_stdout(output):
            self.assertEqual(command(),2)
        receipt=json.loads(output.getvalue())
        self.assertEqual(receipt['error'],'macos-cloud-file-not-local')
        self.assertEqual(Path(receipt['path']),placeholder)
        self.assertIn('现在下载',receipt['nextAction'])

    def test_source_entry_checks_before_state_or_install_write(self):
        import install
        state = self.home/'原店 状态'
        self.assert_blocked(lambda:install.main(['--host','workbuddy','--home',str(self.home),
                            '--state',str(state),'--offline']), ROOT/'SKILL.md')
        self.assertFalse(state.exists())
        self.assertFalse((self.home/'.workbuddy').exists())

    def test_installed_entry_checks_source_before_cli_import(self):
        from scripts import merchant
        self.assert_blocked(lambda:merchant.main(['--state',str(self.home),'status']),
                            ROOT/'heideng_merchant/cli.py')

    def test_existing_runtime_config_and_original_state_remain_reusable(self):
        import install
        import os
        from heideng_merchant import CloudFileUnavailable
        from heideng_merchant.runtime_dependencies import runtime_python
        from heideng_merchant.state import install_state
        target = (self.home/'skills'/SKILL_NAME).resolve()
        state = self.home/'自定义状态'
        cfg=state/'runtime-venv/pyvenv.cfg'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('include-system-site-packages = false')
        archived=state/'unknown.json'
        archived.write_bytes(b'{"original":"unknown"}')
        with patch.dict(os.environ,HEIDENG_MERCHANT_HOME=str(state)):
            with patch('heideng_merchant.runtime_dependencies.prepare_runtime',side_effect=AssertionError('must stop before network setup')):
                self.assert_blocked(lambda:install.main(['--host','workbuddy','--skills-dir',str(target.parent)]),cfg)
            with mac_placeholder(cfg), self.assertRaises(CloudFileUnavailable):
                runtime_python(state)
            self.assertFalse(target.exists())
            self.assertFalse((state/'installation-target.json').exists())
            self.assertEqual(install_state(target),state)
        self.assertEqual(archived.read_bytes(),b'{"original":"unknown"}')

    def test_original_receipt_and_snapshot_are_never_treated_as_missing_or_modified(self):
        from heideng_merchant import CloudFileUnavailable,cli
        from heideng_merchant.safety import atomic_json
        record=self.home/'merchant-tasks/fixture.json'
        atomic_json(record,{'taskId':'fixture'})
        with patch('heideng_merchant.update_client.maybe_schedule') as schedule:
            self.assert_blocked(lambda:cli.main(['--state',str(self.home),'task-context','--shop-id','4','--vender-id','5']),record)
            self.assert_blocked(lambda:cli.main(['--state',str(self.home),'task-context','--shop-id','4','--vender-id','5']),record.parent)
            schedule.assert_not_called()
        with mac_placeholder(record), self.assertRaises(CloudFileUnavailable):
            atomic_json(record,{})
        self.assertEqual(json.loads(record.read_bytes()),{'taskId':'fixture'})
        source=self.home/'source'
        source.mkdir()
        (source/'VERSION').write_text('1.0.0')
        (source/'SKILL.md').write_text('---\nname: '+SKILL_NAME+'\n---\n')
        target=self.home/'versions/1.0.0-fixture'/SKILL_NAME
        distribution.install_source(source,target,self.home/'state')
        with mac_placeholder(target/'SKILL.md'), self.assertRaises(CloudFileUnavailable):
            distribution.verify_install(target)
        self.assertTrue(distribution.verify_install(target)['valid'])


class SourceInstallTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.state = self.home/'store'
        self.target = self.home/'skills'/SKILL_NAME

    def test_verified_source_and_task_snapshot_without_archiving(self):
        with patch('zipfile.ZipFile', side_effect=AssertionError('source install opened a ZIP')):
            self.assertEqual(distribution.install_source(ROOT,self.target,self.state)['status'], 'installed')
            self.assertEqual(distribution.install_source(self.target,self.target,self.state)['status'], 'unchanged')
            checked = distribution.verify_install(self.target)
            self.assertTrue(checked['valid'])
            receipt = checked['receipt']
            self.assertNotIn('archiveSha256',receipt)
            expected_digest = file_sha(self.target/distribution.MANIFEST)
            self.assertEqual(receipt['sourceManifestSha256'],expected_digest)
            manifest, contents = distribution.source_payload(self.target,VERSION)
            self.assertEqual(audit_payload(manifest,contents)['releaseAudit'],'passed')
            self.assertEqual(receipt['files'],{name: hashlib.sha256(data).hexdigest() for name,data in contents.items()})
            trust = json.loads((ROOT/'updates/trust.json').read_bytes())
            update_client.configure(self.state,self.target,trust,host='workbuddy')
            lease = update_client.usage(self.state,'begin','new-source-task')
            self.assertEqual(distribution.verify_install(Path(lease['packageRoot']))['receipt'],receipt)
            self.assertTrue(update_client.release_matches(receipt,{'version':VERSION,'manifestSha256':expected_digest}))
            self.assertFalse(update_client.release_matches(receipt,{'version':VERSION,'sha256':expected_digest}))
            from heideng_merchant.short_title_worker_state import runtime_binding
            self.assertEqual(runtime_binding(self.target)['sourceManifestSha256'],expected_digest)

    def test_same_version_across_formats_and_upgrade_from_real_old_receipt(self):
        legacy = next((ROOT/'updates/artifacts').glob('*-0.4.10-*.zip'))
        archive_digest = file_sha(legacy)
        distribution.install_archive(legacy,self.target,self.state,expected_sha=archive_digest)
        original = distribution.verify_install(self.target)['receipt']
        source = self.home/'legacy-source'
        shutil.copytree(self.target,source)
        self.assertEqual(distribution.install_source(source,self.target,self.state)['status'],'unchanged')
        self.assertEqual(distribution.verify_install(self.target)['receipt'],original)

        from_source = self.home/'other-host'/SKILL_NAME
        other_state = self.home/'other-state'
        distribution.install_source(source,from_source,other_state)
        self.assertEqual(distribution.install_archive(legacy,from_source,other_state,expected_sha=archive_digest)['status'],'unchanged')
        (source/'README.md').write_text('different content at the same version',encoding='utf-8')
        with self.assertRaisesRegex(SafetyError,'same-version-different-artifact'):
            distribution.install_source(source,self.target,self.state)

        unknown = self.state/'pending-write.json'
        unknown.write_bytes(b'{"status":"unknown"}')
        trust = json.loads((ROOT/'updates/trust.json').read_bytes())
        update_client.configure(self.state,self.target,trust,host='workbuddy')
        self.assertEqual(distribution.install_source(ROOT,self.target,self.state)['version'],VERSION)
        update_client.configure(self.state,self.target,trust,host='workbuddy')
        old = update_client.usage(self.state,'begin','resume-old',loaded_version='0.4.10')
        self.assertEqual(distribution.verify_install(Path(old['packageRoot']))['receipt'],original)
        self.assertEqual(unknown.read_bytes(),b'{"status":"unknown"}')
        self.assertEqual(distribution.rollback(self.target,self.state)['version'],'0.4.10')
        self.assertEqual(distribution.verify_install(self.target)['receipt'],original)

    def test_source_install_enforces_identity_file_bounds_and_provenance(self):
        source = self.home/'source'
        source.mkdir()
        (source/'VERSION').write_text('1.0.0',encoding='utf-8')
        (source/'SKILL.md').write_text('---\nname: other\n---\n',encoding='utf-8')
        (source/'package-files.json').write_text('{"schemaVersion":1,"files":["VERSION","SKILL.md"]}',encoding='utf-8')
        with self.assertRaisesRegex(SafetyError,'wrong-skill-identity'):
            distribution.install_source(source,self.target,self.state)
        (source/'SKILL.md').write_text('---\nname: '+SKILL_NAME+'\n---\n',encoding='utf-8')
        with patch.object(distribution,'MAX_BYTES',8), self.assertRaisesRegex(SafetyError,'expanded-package-too-large'):
            distribution.install_source(source,self.target,self.state)
        component=source/'mature/materials'
        component.mkdir(parents=True)
        (component/'example.py').write_bytes(b'changed')
        (component/'provenance.json').write_text(json.dumps({'license':'MIT','files':{'example.py':{'sha256':'1'*64}}}))
        with self.assertRaisesRegex(SafetyError,'mature-source-modified'):
            distribution.install_source(source,self.target,self.state)
        self.assertFalse(self.target.exists())

    def test_interrupted_source_upgrade_resumes_from_verified_journal(self):
        source = self.home/'source'
        source.mkdir()
        (source/'SKILL.md').write_text('---\nname: '+SKILL_NAME+'\n---\n',encoding='utf-8')
        version = source/'VERSION'
        version.write_text('1.0.0')
        distribution.install_source(source,self.target,self.state)
        version.write_text('1.0.1')
        switch = distribution._replace_directory

        def interrupt(origin, target):
            if '.stage-' in origin.name:
                raise SystemExit('interrupted between directory switches')
            switch(origin,target)

        with patch.object(distribution,'_replace_directory',side_effect=interrupt), self.assertRaises(SystemExit):
            distribution.install_source(source,self.target,self.state)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.state/'install-journal.json').is_file())
        self.assertEqual(distribution.install_source(source,self.target,self.state)['version'],'1.0.1')
        (self.target/'SKILL.md').write_text('local merchant edit',encoding='utf-8')
        version.write_text('1.0.2')
        with self.assertRaisesRegex(SafetyError,'locally-modified'):
            distribution.install_source(source,self.target,self.state)
        self.assertEqual((self.target/'SKILL.md').read_text(),'local merchant edit')
