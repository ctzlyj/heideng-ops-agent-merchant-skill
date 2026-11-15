"""Synthetic original import state at actual update/rollback and CLI boundaries."""
import tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from tests import test_short_title_imports as fixtures,test_distribution as installs
from heideng_merchant import distribution,cli
from heideng_merchant.safety import SafetyError,atomic_json

class ShortTitleImportBoundaryTests(unittest.TestCase):
 def test_cli_root_prepare_approval_status_and_rows_do_not_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);state=home/'.heideng-merchant';c,s,p,src,m,r=fixtures.ShortTitleImportsTests().make(state)
   def command(name,*args):return cli.run(cli.parser().parse_args(['--home',d,name,*map(str,args)]))
   with patch('heideng_merchant.cli.OfficialClient',return_value=c):
    root=command('short-title-import-plan','--plan-id',p['planId'],'--source-id',src['sourceId']);self.assertEqual(root['importId'],r['importId']);self.assertFalse(root['imported']);a=command('short-title-import-approve','--import-id',r['importId'],'--fingerprint',r['fingerprint'],'--confirm');self.assertTrue(a['approvalCurrentlyValid']);self.assertFalse(a['CLIWorkerIntegrated']);self.assertEqual(command('short-title-import-status','--import-id',r['importId'])['proposedRowCount'],1);self.assertEqual(command('short-title-import-rows','--import-id',r['importId'])['total'],1)
   self.assertFalse(c.posts)
 def test_prepared_root_idle_but_unknown_submitted_and_orphans_block_updates(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=fixtures.ShortTitleImportsTests().make(d);self.assertFalse(distribution.busy(d));m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=fixtures.ShortTitleImportsTests().browser(d,m,r);f.driver.context.page.fault='create-timeout'
   try:self.assertEqual(m.execute(r['importId'],b)['status'],'unknown')
   finally:b.close()
   self.assertTrue(distribution.busy(d));(Path(d)/'short-title-imports'/ (r['importId']+'.json')).unlink();self.assertTrue(distribution.busy(d))
 def test_complete_submitted_originals_not_title_verification_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,src,m,r=fixtures.ShortTitleImportsTests().make(d);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=fixtures.ShortTitleImportsTests().browser(d,m,r)
   try:self.assertEqual(m.execute(r['importId'],b)['submittedBatchCount'],1)
   finally:b.close()
   self.assertTrue(distribution.busy(d))
 def test_unknown_import_blocks_install_and_rollback_before_recovery_mutation(self):
  h=installs.DistributionTests();h.setUp();b=None
  try:
   h.install(h.bundle());h.install(h.bundle('0.2.0'));c,s,p,src,m,r=fixtures.ShortTitleImportsTests().make(h.state);m.approve(r['importId'],r['fingerprint'],confirmed=True);f,b=fixtures.ShortTitleImportsTests().browser(h.state,m,r);f.driver.context.page.fault='upload-timeout';self.assertEqual(m.execute(r['importId'],b)['status'],'unknown');b.close();b=None;stage=h.target.parent/('.heideng-ops-agent-merchant.stage-'+uuid.uuid4().hex);backup=h.target.parent/('.heideng-ops-agent-merchant.backup-'+uuid.uuid4().hex);stage.mkdir();(stage/'marker').write_text('preserve');journal=h.state/'install-journal.json';atomic_json(journal,{'target':str(h.target),'stage':str(stage),'backup':str(backup)});before=journal.read_bytes()
   with self.assertRaises(SafetyError):h.install(h.bundle('0.3.0'))
   self.assertEqual(journal.read_bytes(),before);self.assertTrue((stage/'marker').is_file())
   with self.assertRaises(SafetyError):distribution.rollback(h.target,h.state)
   self.assertEqual(journal.read_bytes(),before);self.assertEqual((h.target/'VERSION').read_text(),'0.2.0')
  finally:
   if b:b.close()
   h.tearDown()

if __name__=='__main__':unittest.main()
