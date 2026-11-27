import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_shared_pop

ROOT = Path(__file__).resolve().parents[1]


class SharedPopTests(unittest.TestCase):
    def test_status_aliases_share_one_check_and_the_next_call_observes_edits(self):
        from heideng_merchant import mature_runtime as runtime
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'mature/materials'
            entry = source / runtime.ROUTES['materials'][1]
            entry.parent.mkdir(parents=True)
            entry.write_bytes(b'example')
            name = entry.relative_to(source).as_posix()
            metadata = {'entrypoints': [name], 'upstreamVersion': 'test', 'repository': 'fixture',
                        'upstreamCommit': 'fixture', 'files': {name: {'sha256': hashlib.sha256(b'example').hexdigest()}}}
            (source / 'provenance.json').write_text(json.dumps(metadata), encoding='utf-8')
            with patch.object(runtime, 'file_sha', wraps=runtime.file_sha) as digest:
                rows = runtime.status(root)['capabilities']
                self.assertEqual(digest.call_count, 1)
            self.assertEqual({r['capability'] for r in rows if r['matureImplementationReused']},
                             {'materials', 'short-title'})
            entry.write_bytes(b'changed')
            rows = runtime.status(root)['capabilities']
            self.assertEqual([r['status'] for r in rows if r['capability'] in ('materials', 'short-title')],
                             ['mature-source-modified', 'mature-source-modified'])

    def test_recorded_blobs_and_runtime_provenance_agree(self):
        self.assertGreater(sync_shared_pop.verify(json.loads(sync_shared_pop.LOCK.read_bytes())), 0)

    def test_installed_top_sku_build_preserves_source_prices_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            skill = root / '.workbuddy/skills/heideng-ops-agent-merchant'
            state = root / 'merchant'
            subprocess.run([sys.executable, '-B', str(ROOT / 'install.py'), '--home', str(root),
                            '--host', 'workbuddy', '--state', str(state), '--offline', '--no-auto-update'],
                           capture_output=True, check=True, timeout=60)
            from tests.pop_top_sku_contract import run
            run([sys.executable, '-B', str(skill/'scripts/merchant.py'), '--state', str(state),
                 'run', '--entry', 'scripts/top_sku_aggregation.py', 'listing', '--'])
            usage = [json.loads(p.read_bytes()) for p in (state / 'updates/usage').glob('*.json')]
            locked = json.loads(sync_shared_pop.LOCK.read_bytes())['groups']
            self.assertIn(locked['top-sku']['commit'], [r['sharedPopCommits']['top-sku'] for r in usage])
