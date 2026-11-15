import tempfile,unittest
from pathlib import Path
from tests import test_short_title_browser as fixture
from heideng_merchant import VERSION
from heideng_merchant import short_title_worker_state as original
from heideng_merchant.operations import Operations
from heideng_merchant.update_gate import busy
from heideng_merchant.safety import SafetyError,atomic_json

class WorkerWriteGateTests(unittest.TestCase):
 def setup(self,d):
  c,s,p,f,b=fixture.ShortTitleBrowserTests().make(d)
  j=original.create_job(d,p['planId'],c,{'version':VERSION,'archiveSha256':'a'*64,'filesSha256':'b'*64},source_id=b.session_id)
  r=original.begin_run(d,j);return c,j,r
 def test_active_worker_blocks_update_and_same_shop_write(self):
  with tempfile.TemporaryDirectory() as d:
   c,j,r=self.setup(d);self.assertTrue(busy(d))
   with self.assertRaises(SafetyError):Operations(d,c)._assert_resolved(j['scope']['shop'])
 def test_unknown_actor_cannot_be_bypassed_by_fake_witness(self):
  with tempfile.TemporaryDirectory() as d:
   c,j,r=self.setup(d);ops=Operations(d,c);ops.worker_witness={'workerId':j['workerId'],'runId':r['runId']}
   with self.assertRaises(SafetyError):ops._assert_resolved(j['scope']['shop'])
 def test_closed_unattempted_worker_is_idle(self):
  with tempfile.TemporaryDirectory() as d:
   c,j,r=self.setup(d);original.finish_run(d,j,r,broker_stopped=True,browser_closed=True,guard_owned=True)
   self.assertFalse(busy(d));Operations(d,c)._assert_resolved(j['scope']['shop'])
 def test_orphan_worker_evidence_blocks_write_and_update(self):
  for folder in ('short-title-worker-runs','short-title-worker-claims','short-title-worker-endpoints','short-title-worker-results','short-title-worker-prefixes','short-title-worker-prefix-receipts','short-title-worker-launches'):
   with self.subTest(folder=folder),tempfile.TemporaryDirectory() as d:
    c,j,r=self.setup(d);original.finish_run(d,j,r,broker_stopped=True,browser_closed=True,guard_owned=True)
    atomic_json(Path(d)/folder/('f'*24)/('e'*24+'.json'),{'status':'closed'})
    self.assertTrue(busy(d))
    with self.assertRaises(SafetyError):Operations(d,c)._assert_resolved(j['scope']['shop'])
