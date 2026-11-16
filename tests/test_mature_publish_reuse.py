"""Generic publish must retain the mature matrix unknown-submission guard."""
import importlib.util,json,sys,tempfile,unittest
from argparse import Namespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'mature/listing/scripts'
class MaturePublishReuseTests(unittest.TestCase):
 def setUp(self):
  self.paths=list(sys.path);sys.path.insert(0,str(SCRIPTS))
  import jd_product_pipeline,matrix_listing
  self.pipe=jd_product_pipeline;self.matrix=matrix_listing
 def tearDown(self):sys.path[:]=self.paths
 def test_unknown_publish_error_preserves_original_matrix_stage(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'state.json';original={'stage':'SUBMITTING','payloadSha256':'synthetic-payload-fingerprint'};path.write_text(json.dumps(original))
   state=self.pipe.record_pipeline_exception(path,RuntimeError('synthetic lost response'))
   self.assertEqual(state['stage'],'SUBMITTING')
   self.assertEqual(json.loads(path.read_text()),original)
 def test_generic_resume_reaches_mature_guard_before_overwriting_state(self):
  with tempfile.TemporaryDirectory() as d:
   output=Path(d);state=output/'state/1000000001.json';state.parent.mkdir();original={'stage':'SUBMITTING','sourceSku':'1000000001','payloadSha256':'synthetic-payload-fingerprint'};state.write_text(json.dumps(original))
   with self.assertRaises(self.matrix.MatrixError):self.pipe.run_pipeline(Namespace(url='https://item.jd.com/1000000001.html',output=output))
   self.assertEqual(json.loads(state.read_text()),original)
if __name__=='__main__':unittest.main()
