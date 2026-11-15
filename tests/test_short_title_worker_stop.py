"""Stopping between upload and create never retries the uploaded object."""
import tempfile,unittest
from pathlib import Path
from tests import test_short_title_browser as fixture
from tests.short_title_import_fixtures import ImportFactory
from heideng_merchant.short_title_imports import ShortTitleImports
from heideng_merchant.short_title_import_browser import ShortTitleImportBrowser
from heideng_merchant.state import FileLock

class WorkerStopBoundaryTests(unittest.TestCase):
 def test_stop_after_upload_prevents_create_and_preserves_original_binding_evidence(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixture.ShortTitleBrowserTests().make(d)
   with FileLock(Path(d)/'install.lock',timeout=0) as guard:
    b.open(install_guard=guard);source=b.capture();b.close();m=ShortTitleImports(d,c,clock=lambda:1000);root=m.prepare(p['planId'],source['sourceId']);factory=ImportFactory(d);live=ShortTitleImportBrowser(m,root['importId'],factory=lambda:factory,headless=True);live.open(install_guard=guard)
    try:
     m.approve(root['importId'],root['fingerprint'],confirmed=True);out=m.execute(root['importId'],live,stop_requested=lambda:factory.driver.context.page.uploads==1)
     self.assertEqual((factory.driver.context.page.uploads,factory.driver.context.page.creates),(1,0));self.assertEqual(out['stoppedReason'],'worker-stop-requested-no-next-native-action');self.assertEqual(out['status'],'uploaded-awaiting-create')
    finally:live.close()

 def test_stop_returning_from_preflight_or_create_health_blocks_actual_dispatch(self):
  for phase in ('preflight','create-health','dispatch-current'):
   with self.subTest(phase=phase),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=fixture.ShortTitleBrowserTests().make(d);stopped=[False]
    with FileLock(Path(d)/'install.lock',timeout=0) as guard:
     b.open(install_guard=guard);source=b.capture();b.close();m=ShortTitleImports(d,c,clock=lambda:1000);root=m.prepare(p['planId'],source['sourceId']);factory=ImportFactory(d);live=ShortTitleImportBrowser(m,root['importId'],factory=lambda:factory,headless=True);live.open(install_guard=guard)
     try:
      m.approve(root['importId'],root['fingerprint'],confirmed=True)
      if phase=='preflight':
       old=live.preflight
       def preflight():out=old();stopped[0]=True;return out
       live.preflight=preflight
      elif phase=='create-health':
       old=m._attempt
       def attempt(*args,**kwargs):
        out=old(*args,**kwargs)
        if args[2]=='create':stopped[0]=True
        return out
       m._attempt=attempt
      else:
       old=m._current
       def current(*args,**kwargs):
        out=old(*args,**kwargs)
        if live.pending_attempt is None and live.phase=='upload' and not factory.driver.context.page.uploads:stopped[0]=True
        return out
       m._current=current
      out=m.execute(root['importId'],live,stop_requested=lambda:stopped[0])
      self.assertEqual(factory.driver.context.page.uploads,0 if phase in ('preflight','dispatch-current') else 1);self.assertEqual(factory.driver.context.page.creates,0)
      self.assertEqual(out['stoppedReason'],'worker-stop-requested-no-next-native-action')
     finally:live.close()
