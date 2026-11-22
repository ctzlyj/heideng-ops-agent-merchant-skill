"""Exercise the actual photo CLI with a synthetic provider and a fresh process per batch."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from unittest.mock import Mock, patch

from heideng_merchant.fee_consent import confirm_fee
from tests.test_mature_listing import ROOT, jpeg, module


class ExecutableBudgetTests(unittest.TestCase):
    def test_replica_subset_calls_the_selected_model_and_preserves_free_reuse(self):
        replica = module('company_jpeg_edits')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':directory}):
            root = Path(directory)
            path = root/'source.jpg'
            raw = jpeg()
            path.write_bytes(raw)
            base = {'sha':sha256(raw).hexdigest(), 'source':str(path), 'model':replica.MODELS[0]}
            plan = {'shop':{'profile':'fixture-shop','venderId':123}, 'sourceProduct':'book',
                    'sources':[{**base,'imageKey':'cover','prompt':'cover'}, {**base,'imageKey':'inside','prompt':'inside'},
                               {**base,'imageKey':'back','reuse':True}]}
            provider = Mock()
            provider.edit.return_value = raw, {}
            replica.generate_plan(plan, root, client=provider, quote_only=True)
            get_quote = lambda: json.loads((root/'image-quote.json').read_bytes())
            approval = root/'fee-approval.json'
            with patch('heideng_merchant.fee_consent._ask_merchant', return_value=True):
                confirm_fee(get_quote(),root,approval,max_requests=1,selected_units=['inside'])
            result = replica.generate_plan(plan,root,client=provider)
            self.assertEqual(result['deferredUnits'], ['cover'])
            replica.generate_plan(plan, root, client=provider)
            self.assertEqual(provider.edit.call_count,1)
            self.assertEqual(provider.edit.call_args.kwargs['prompt'],'inside')
            replica.generate_plan(plan, root, client=provider, quote_only=True)
            self.assertEqual(get_quote()['pendingUnits'],['cover'])
            with patch('heideng_merchant.fee_consent._ask_merchant',return_value=True):
                confirm_fee(get_quote(),root,approval,max_requests=1,selected_units=['cover'])
            replica.generate_plan(plan,root,client=provider)
            self.assertEqual([c.kwargs['prompt'] for c in provider.edit.call_args_list], ['inside','cover'])

    def test_selected_commercial_slots_and_resume_after_new_process(self):
        listing = module('photo_listing')
        for title in ('围巾', '镜头座'):
            with self.subTest(product=title), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state = root/'state'
                package = root/'package'
                source = root/'photo.jpg'
                source.write_bytes(jpeg((100, 100)))
                store = {'profile':'fixture-store', 'shopName':'合成店', 'venderId':34}
                with patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(state)}):
                    m = listing.create_package(package, store, [source], title, reference_answered=True)
                units = ['view-' + str(i) for i in range(6)]
                selected = [units[i] for i in (5, 2, 3, 0, 4)]
                design = {'images': [dict(id=u, role='main', photos=m['sourcePhotos'], prompt=u) for u in units]}
                quote = listing.make_plan(package, preview=True, design=design)['quote']
                with patch('heideng_merchant.fee_consent._ask_merchant',return_value=True) as dialog:
                    with self.assertRaisesRegex(ValueError,'超过请求上限'):
                        confirm_fee(quote,state,root/'decision.json',max_requests=5)
                    dialog.assert_not_called()
                    confirm_fee(quote,state,root/'decision.json',max_requests=5,selected_units=selected)
                    self.assertIn('其余 1 张', dialog.call_args.args[0])
                first = self.generate(package,state,root/'decision.json',source)
                self.assertEqual(first['submittedCount'],5)
                self.assertCountEqual(first['selectedUnits'],selected)
                self.assertEqual(first['deferredUnits'],[units[1]])
                self.assertCountEqual([p.stem for p in (package/'.generation/generated').glob('*.jpg')], selected)
                again = self.generate(package,state,root/'decision.json',source)
                self.assertEqual(again['submittedCount'],0)
                remainder = json.loads((package/'image-quote.json').read_bytes())
                self.assertEqual(remainder['units'],[units[1]])
                with patch('heideng_merchant.fee_consent._ask_merchant',return_value=True):
                    confirm_fee(remainder,state,root/'next.json',max_requests=1)
                last = self.generate(package,state,root/'next.json',source)
                self.assertEqual((last['submittedCount'],last['successCount'],last['deferredUnits']),(1,6,[]))

    def generate(self, package, state, approval, source):
        runner = """
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from tests.test_mature_listing import module
pl = module('photo_listing')
pg = module('photo_generation')
class Client:
    capacity=1
    def __init__(self,key): pass
    def edit(self,**options): return Path(sys.argv[4]).read_bytes()
with patch.object(pg,'CompanyPhotoClient',Client),patch.object(pg,'key_from_environment',return_value='fixture'):
    raise SystemExit(pl.main(['generate','--package',sys.argv[2],'--approval-file',sys.argv[3]]))
"""
        env = dict(os.environ, HEIDENG_MERCHANT_HOME=str(state), PYTHONIOENCODING='utf-8')
        run = subprocess.run([sys.executable,'-I','-B','-X','utf8','-c',runner,str(ROOT),str(package),str(approval),str(source)],
                             capture_output=True,text=True,encoding='utf-8',env=env,timeout=35)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        return json.loads(run.stdout)
