"""Authorized private-distribution check, never a merchant business action."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from heideng_merchant.update_catalog import GitSource,digest
from heideng_merchant.update_client import check
from heideng_merchant.safety import clean_environment
ROOT=Path(__file__).resolve().parents[1]
class RemoteStableTests(unittest.TestCase):
    def test_old_package_can_discover_and_fetch_actual_published_fixed_blob(self):
        old=next((ROOT/'updates/artifacts').glob('*-0.4.0-*.zip'))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'target/heideng-ops-agent-merchant';target.parent.mkdir()
            from heideng_merchant.distribution import install_archive
            from heideng_merchant.update_client import configure
            install_archive(old,target,root/'state',expected_sha=digest(old))
            trust=json.loads((ROOT/'updates/trust.json').read_text(encoding='utf-8'));configure(root/'state',target,trust,host='workbuddy')
            old_mod=__import__('zipfile').ZipFile(old).read('heideng_merchant/update_catalog.py').decode('utf-8')
            old_root=root/'old-source';old_root.mkdir();(old_root/'update_catalog.py').write_text(old_mod)
            import importlib.util
            old_root.rename(old_root.parent/'heideng_merchant');(old_root.parent/'heideng_merchant'/'__init__.py').write_text('')
            spec=importlib.util.spec_from_file_location('heideng_merchant.update_catalog',old_root.parent/'heideng_merchant'/'update_catalog.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            mod.SafetyError=__import__('heideng_merchant.safety',fromlist=['SafetyError']).SafetyError
            mod.atomic_json=__import__('heideng_merchant.safety',fromlist=['atomic_json']).atomic_json
            mod.is_linked=lambda p:False
            source=mod.GitSource(root/'git-cache',trust['repository'],trust['ref'])
            payload=source.read_index()
            from heideng_merchant.update_catalog import verify
            releases=verify(payload,trust)['releases'];release=next(x for x in releases if x['version']=='0.4.2')
            artifact=root/'downloaded.zip';artifact.write_bytes(source.read_blob(release['gitBlob']))
            self.assertEqual(digest(artifact),release['sha256'])
            self.assertEqual(artifact.stat().st_size,release['sizeBytes'])
            self.assertEqual(release['compatibility']['hosts'],['codex','workbuddy','joycode','claude','universal','explicit-skills-dir'])

if __name__=='__main__':unittest.main()
