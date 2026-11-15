"""Main-owned original C3 findings, synthetic sources only."""
import sys, pathlib, tempfile, unittest, socket, subprocess
r=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(r))
from tests import test_short_title_result_observation as c2_fixture
from tests import test_short_title_effect_sources as c3_fixture
from heideng_merchant.safety import SafetyError
from heideng_merchant.short_title_import_gate import busy
from heideng_merchant.distribution import busy as install_busy
base=r/'.agent-work/short-title-c3/owned-finding-tmp';base.mkdir(parents=True,exist_ok=True)
class OwnedC3ReviewRegressions(unittest.TestCase):
 def test_valid_prewrite_partial_c3_is_not_idle_or_permission_to_other_writes(self):
  with tempfile.TemporaryDirectory(dir=base) as d:
   pathlib.Path(d).resolve().relative_to(base.resolve())
   c,m,root,b,p,_=c2_fixture.ShortTitleResultObservationTests().setup(d,execute=False)
   try:
    out=m.collect_effects(root['importId'],b);self.assertTrue(out['C3ReceiptPersisted']);self.assertEqual(out['originalResultSequence'],0);self.assertEqual((p.uploads,p.creates),(0,0))
   finally:b.close()
   blocked=False
   try:m.plans.ops._assert_resolved(m.record(root['importId'])['scope']['shop'])
   except SafetyError:blocked=True
   self.assertEqual((blocked,busy(d),install_busy(d)),(True,True,True))
 def test_midread_close_or_guard_loss_refuses_new_current_effect_observation(self):
  for kind in ('close','guard-loss'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory(dir=base) as d:
    pathlib.Path(d).resolve().relative_to(base.resolve())
    c,m,root,b,p,calls,_=c3_fixture.OwnedOriginalEffectReadTests().setup(d);original=c.invoke;changed=[False]
    def invoke(profile,url,**kw):
     data=original(profile,url,**kw)
     if not changed[0] and url.endswith('/products/{productId}'):
      changed[0]=True
      if kind=='close':b.close()
      else:b.install_lock.__exit__(None,None,None)
     return data
    c.invoke=invoke
    try:
     with self.assertRaises(SafetyError):m.collect_effects(root['importId'],b)
     self.assertFalse(list((pathlib.Path(d)/'short-title-effect-observations').glob('*/*.json')));self.assertEqual((p.uploads,p.creates),(1,1))
    finally:
     # Clear only an already released synthetic witness during fixture cleanup.
     if b.install_lock is not None and not b.install_lock.acquired:b.install_lock=None
     b.close()
if __name__=='__main__':unittest.main(verbosity=2)
