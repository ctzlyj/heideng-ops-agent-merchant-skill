"""Normal connector registration after a renewal. Uses only a synthetic local registry."""
from importlib import util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class RenewalRegistrationTests(unittest.TestCase):
    def test_previous_official_identity_survives_an_unrelated_observation(self):
        root = Path(__file__).resolve().parents[1]
        app = root / 'app'
        if (root / 'mature/connection/app').is_dir():
            app = root / 'mature/connection/app'
        self.enterContext(patch.object(sys, 'path', [str(app), str(root), *sys.path]))
        spec = util.spec_from_file_location('renewal_shoplib', app / 'shoplib.py')
        sl = util.module_from_spec(spec)
        spec.loader.exec_module(sl)
        profile = 'fixture-renewal'
        shop = {'shopId':'801', 'venderId':'11', 'shopName':'Fixture POP'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(sl, 'linker_home', return_value=Path(tmp)):
            sl.write_json(sl.registry_path(), {'version':2, 'profiles':{profile:{'shopName':'working name'}}})
            sl.update_registry(profile, shop)
            sl.update_registry(profile, {**shop, 'shopId':801})
            original = sl.registry_path().read_bytes()
            for field, changed in [('shopId','802'), ('venderId','12'), ('shopName','Other shop')]:
                with self.subTest(field=field), self.assertRaises(sl.VerifyError):
                    sl.update_registry(profile, {**shop, field:changed})
                self.assertEqual(sl.registry_path().read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
