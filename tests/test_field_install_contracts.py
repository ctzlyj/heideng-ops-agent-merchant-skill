"""Managed backup discovery regression using synthetic packages, never personal Skills."""
import json,unittest
from pathlib import Path
import tests.test_distribution as helpers
from heideng_merchant.distribution import rollback

class BackupDiscoveryTests(unittest.TestCase):
    setUp=helpers.DistributionTests.setUp
    tearDown=helpers.DistributionTests.tearDown
    bundle=helpers.DistributionTests.bundle
    install=helpers.DistributionTests.install
    def test_future_installer_backups_are_outside_host_skill_scan_and_can_rollback(self):
        self.install(self.bundle());self.install(self.bundle('0.2.0'))
        previous=Path(json.loads((self.state/'install-history.json').read_text())['previous'])
        self.assertFalse(previous.is_relative_to(self.target.parent))
        self.assertEqual(len(list(self.target.parent.glob('*/SKILL.md'))),1)
        self.assertEqual(rollback(self.target,self.state)['version'],'0.1.0')

if __name__=='__main__':unittest.main()
