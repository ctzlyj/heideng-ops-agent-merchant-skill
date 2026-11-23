"""Public Git installs and verified transitions with the existing archive format."""
import hashlib
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
