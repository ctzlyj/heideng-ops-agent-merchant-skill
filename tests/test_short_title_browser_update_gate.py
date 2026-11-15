"""Synthetic browser lifecycle at installation, rollback and recovery gates."""
import tempfile,unittest
from pathlib import Path
from tests import test_short_title_browser as fixtures,test_distribution as installs
from heideng_merchant import distribution
from heideng_merchant.safety import SafetyError,read_json,atomic_json

class ShortTitleBrowserGateTests(unittest.TestCase):
 def test_active_closed_and_complete_source_lifecycle(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(d);b.open()
   try:self.assertTrue(distribution.busy(d));r=b.capture();self.assertTrue(distribution.busy(d))
   finally:b.close()
   self.assertFalse(distribution.busy(d))
 def test_uncertain_close_and_orphan_originals_block_updates(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(d);b.open();f.driver.context.fail_close=True
   with self.assertRaises(SafetyError):b.close()
   self.assertTrue(distribution.busy(d));f.driver.context.fail_close=False;b.close();self.assertFalse(distribution.busy(d))
   folder=Path(d)/'short-title-browser-observations';folder.mkdir();atomic_json(folder/('a'*24+'.json'),{});self.assertTrue(distribution.busy(d))
 def test_tampered_or_missing_owner_and_lifecycle_cannot_clear_busy(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(d);b.open();b.capture();b.close();saved=read_json(b.lifecycle_path)
   for value in ({**saved,'sessionId':'a'*24},{**saved,'status':'unknown'},{}):
    atomic_json(b.lifecycle_path,value);self.assertTrue(distribution.busy(d))
   atomic_json(b.lifecycle_path,saved);self.assertFalse(distribution.busy(d));b.owner_path.unlink();self.assertTrue(distribution.busy(d))
 def test_install_and_rollback_refuse_before_existing_recovery_is_changed(self):
  h=installs.DistributionTests();h.setUp();b=None
  try:
   h.install(h.bundle());h.install(h.bundle('0.2.0'));c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(h.state);b.open();target=h.target;stage=target.parent/'.heideng-ops-agent-merchant.stage-synthetic';backup=target.parent/'.heideng-ops-agent-merchant.backup-synthetic';stage.mkdir();(stage/'marker').write_text('preserve');journal=h.state/'install-journal.json';atomic_json(journal,{'target':str(target),'stage':str(stage),'backup':str(backup)});before=journal.read_bytes()
   with self.assertRaises(SafetyError):h.install(h.bundle('0.3.0'))
   self.assertEqual(journal.read_bytes(),before);self.assertTrue((stage/'marker').is_file());self.assertEqual((target/'VERSION').read_text(),'0.2.0')
   with self.assertRaises(SafetyError):distribution.rollback(target,h.state)
   self.assertEqual(journal.read_bytes(),before);self.assertTrue((stage/'marker').is_file());self.assertEqual((target/'VERSION').read_text(),'0.2.0')
  finally:
   if b:b.close()
   h.tearDown()

 def test_update_and_rollback_interlock_blocks_reopen_during_final_probe(self):
  from unittest.mock import patch
  from heideng_merchant import short_title_browser_gate as gate,short_title_browser as browser
  for operation in ('install','rollback'):
   with self.subTest(operation=operation):
    h=installs.DistributionTests();h.setUp();other=None
    try:
     h.install(h.bundle());h.install(h.bundle('0.2.0'));c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(h.state);b.open();b.close();fresh=fixtures.Factory(h.state);other=browser.ShortTitleSourceBrowser(h.state,c,p['planId'],session_id=b.session_id,factory=lambda:fresh);original=gate._entries;seen=0;blocked=False
     def entries(state,relative):
      nonlocal seen,blocked
      if relative=='short-title-browser-sources':
       seen+=1
       if seen==2:
        try:other.open()
        except SafetyError:blocked=True
      return original(state,relative)
     with patch.object(gate,'_entries',entries):
      if operation=='install':h.install(h.bundle('0.3.0'))
      else:distribution.rollback(h.target,h.state)
     self.assertTrue(blocked);self.assertFalse(fresh.driver.launches);self.assertEqual((h.target/'VERSION').read_text(),'0.3.0' if operation=='install' else '0.1.0')
    finally:
     if other:other.close()
     h.tearDown()

if __name__=='__main__':unittest.main()
