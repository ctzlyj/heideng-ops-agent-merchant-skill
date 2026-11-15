"""A worker's real install witness survives native source/import transitions."""
import inspect,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError
from heideng_merchant.state import FileLock
from heideng_merchant.short_title_imports import ShortTitleImports
from heideng_merchant.short_title_import_browser import ShortTitleImportBrowser
from tests import test_short_title_browser as source_fixture
from tests import test_short_title_imports as import_fixture
from tests.short_title_import_fixtures import ImportFactory

class BorrowedInstallWitnessTests(unittest.TestCase):
 def open(self,browser,guard):
  self.assertIn('install_guard',inspect.signature(browser.open).parameters,'native browser cannot yet reuse the real worker guard')
  return browser.open(install_guard=guard)
 def test_source_to_import_approve_execute_one_parent_guard_no_second_lock(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d)
   with FileLock(Path(d)/'install.lock',timeout=0) as guard:
    self.open(b,guard);src=b.capture();b.close();guard.require_owned(Path(d)/'install.lock')
    m=ShortTitleImports(d,c,clock=lambda:1000);root=m.prepare(p['planId'],src['sourceId']);factory=ImportFactory(d)
    live=ShortTitleImportBrowser(m,root['importId'],factory=lambda:factory,headless=True)
    try:
     self.open(live,guard);self.assertIs(live.install_lock,guard);m.approve(root['importId'],root['fingerprint'],confirmed=True)
     out=m.execute(root['importId'],live);self.assertEqual(out['submittedBatchCount'],1);self.assertEqual((factory.driver.context.page.uploads,factory.driver.context.page.creates),(1,1))
    finally:live.close()
    guard.require_owned(Path(d)/'install.lock');self.assertFalse(c.posts)
   self.assertFalse(guard.acquired)
 def test_unowned_fake_or_wrong_path_guard_refused_without_browser_launch(self):
  for kind in ('fake','unowned','wrong-path'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d)
    if kind=='wrong-path':
     with FileLock(Path(d)/'other.lock') as guard:
      with self.assertRaises(SafetyError):self.open(b,guard)
      guard.require_owned(Path(d)/'other.lock')
    else:
     guard=object() if kind=='fake' else FileLock(Path(d)/'install.lock')
     with self.assertRaises(SafetyError):self.open(b,guard)
    self.assertFalse(f.driver.launches)
 def test_other_thread_cannot_borrow_owner_witness(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d);errors=[]
   self.assertIn('install_guard',inspect.signature(b.open).parameters)
   with FileLock(Path(d)/'install.lock') as guard:
    def attempt():
     try:b.open(install_guard=guard)
     except Exception as error:errors.append(type(error))
    thread=threading.Thread(target=attempt);thread.start();thread.join(5)
    self.assertFalse(thread.is_alive());self.assertEqual(errors,[SafetyError]);self.assertFalse(f.driver.launches);guard.require_owned(Path(d)/'install.lock')
 def test_unknown_close_keeps_borrowed_parent_guard_until_actual_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d)
   with FileLock(Path(d)/'install.lock') as guard:
    self.open(b,guard);f.driver.context.fail_close=True
    with self.assertRaises(SafetyError):b.close()
    guard.require_owned(Path(d)/'install.lock');self.assertIs(b.install_lock,guard)
    f.driver.context.fail_close=False;b.close();guard.require_owned(Path(d)/'install.lock')
 def test_legacy_browser_still_owns_and_releases_its_separate_guard(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d);b.open();guard=b.install_lock
   try:guard.require_owned(Path(d)/'install.lock')
   finally:b.close()
   self.assertFalse(guard.acquired)
   with FileLock(Path(d)/'install.lock',timeout=0) as reopened:reopened.require_owned(Path(d)/'install.lock')

if __name__=='__main__':unittest.main(verbosity=2)
