import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from heideng_merchant.safety import atomic_json
from heideng_merchant.shop_locations import locate_shops
from tests.test_mature_connection import SOURCE, load


class ShopLocationTests(unittest.TestCase):
    def test_registered_and_live_are_separate_and_previous_expert_is_only_located(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home/'current'
            row = {'shopName':'样例店','shopId':'101','venderId':'211','status':'ok','companyName':'private'}
            atomic_json(state/'linker/shops.json', {'profiles':{'a':row, 'b':row, 'c':{'shopName':'未确认'}}})
            expert = home/'.heideng-wb-beta'
            atomic_json(expert/'linker/shops.json', {'profiles':{'unused':{'shopName':'not-to-be-exported'}}})
            result = locate_shops(state, home=home)
            current, other = result['locations']
            self.assertEqual([s['shopName'] for s in current['registeredShops']], ['样例店'])
            self.assertEqual(current['incompleteRecords'], 1)
            self.assertFalse(current['liveIdentityChecked'])
            self.assertEqual(other['channel'], 'workbuddy-expert')
            self.assertNotIn('registeredShops', other)
            self.assertNotIn('private', str(result))
            self.assertNotIn('not-to-be-exported', str(result))

    def test_no_write_audit_keeps_registry_and_proof_and_counts_distinct_shops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {'JDO_HOME':str(root/'cli'),'JINGMAI_LINKER_HOME':str(root/'linker')}), patch.object(
                    sys,'path',[str(SOURCE/'app'), *sys.path]):
                lib = load('test_nowrite_shoplib',SOURCE/'app/shoplib.py')
                identities = {name:{'venderId':'77','shopId':sid,'shopName':name} for name,sid in
                              [('shop-first','850'),('shop-second','851')]}
                for name in identities:
                    atomic_json(lib.profiles_dir()/(name+'.json'),{})
                registry = {'profiles':{n:dict(v) for n,v in identities.items()}}
                atomic_json(lib.registry_path(),registry)
                proof_path = lib.linker_home()/'authorization-proof.json'
                atomic_json(proof_path,{'profiles':{n:{'slotVerified':True,'venderId':'77','jobId':n,'status':'pending'}
                                                    for n in identities}})
                before = [p.read_bytes() for p in (lib.registry_path(),proof_path)]
                result = lib.audit(verify=lambda p:identities[p], apply_aliases=False)
                self.assertEqual(result['verifiedShopCount'],2)
                self.assertEqual(result['duplicates'],[])
                self.assertEqual(result['webLoginStatus'],'not-checked')
                self.assertEqual(before,[p.read_bytes() for p in (lib.registry_path(),proof_path)])
