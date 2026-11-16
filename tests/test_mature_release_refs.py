"""Nested mature references must be audited by their actual package path."""
import tempfile,unittest
from pathlib import Path
from heideng_merchant.distribution import build_bundle
from scripts.audit_release import audit
ROOT=Path(__file__).resolve().parents[1]
class MatureReleaseReferenceTests(unittest.TestCase):
 def test_nested_mature_reference_is_not_truncated_to_root_reference(self):
  with tempfile.TemporaryDirectory() as d:
   archive=build_bundle(ROOT,Path(d)/'source.zip',(ROOT/'VERSION').read_text().strip())
   self.assertEqual(audit(archive)['releaseAudit'],'passed')
if __name__=='__main__':unittest.main()
