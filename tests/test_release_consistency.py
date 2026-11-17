"""Final source tree and fixed artifact must converge before publication."""
import json, tempfile, unittest
from pathlib import Path
from heideng_merchant.distribution import build_bundle,validate_archive
from heideng_merchant.update_catalog import digest
ROOT=Path(__file__).resolve().parents[1]
class ReleaseConsistencyTests(unittest.TestCase):
 def test_release_source_rebuild_matches_fixed_artifact(self):
  with tempfile.TemporaryDirectory() as d:
   actual=build_bundle(ROOT,Path(d)/'rebuild.zip',(ROOT/'VERSION').read_text().strip())
   expected=next((ROOT/'updates/artifacts').glob('heideng-ops-agent-merchant-'+(ROOT/'VERSION').read_text().strip()+'-*.zip'))
   self.assertEqual(digest(actual),digest(expected))
   self.assertEqual(validate_archive(actual)[1],validate_archive(expected)[1])

if __name__=='__main__':unittest.main()
