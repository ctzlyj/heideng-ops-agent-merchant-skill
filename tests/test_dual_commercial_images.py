"""Exercise each commercial image route at the same provider boundary without charging a Key."""
from collections import Counter
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heideng_merchant.image_models import MODELS
from heideng_merchant import mature_image
from tests.fee_consent import isolated_fees, signed_fixture
from tests.test_mature_listing import jpeg, module
from tests.test_mature_refresh import load as load_refresh, SOURCE as REFRESH


class CommercialModelsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.photo = self.root/'original.jpg'
        self.photo.write_bytes(jpeg())
        self.calls = []
        self.sizes = {}
        self.sync = threading.Barrier(2, timeout=8)
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_LTS4AI_API_KEY':'fixture'}))
        self.enterContext(redirect_stdout(io.StringIO()))

        class Transport:
            def __init__(inner, key, *, model, base_url, retries):
                self.assertEqual(base_url, 'https://api.lts4ai.com/v1')
                self.assertEqual(retries, 0)
                inner.model = model

            def edit(inner, prompt, references, size, directory):
                self.calls.append((prompt, inner.model))
                self.sizes[prompt] = size
                if self.sync is not None:
                    self.sync.wait()
                path = Path(directory)/'result.jpg'
                path.write_bytes(self.photo.read_bytes())
                return SimpleNamespace(path=path)

        self.enterContext(patch.object(mature_image.lts4ai_client,'SfImage2Client',Transport))

    def consent(self, directory):
        quote = json.loads((directory/'image-quote.json').read_bytes())
        self.assertEqual(quote['maxCredits'],6)
        self.assertEqual(quote['scope']['models'], list(MODELS))
        approval = signed_fixture(dict(quote,billing='requests',maxRequests=2))
        (directory/'fee-approval.json').write_text(json.dumps(approval),encoding='utf-8')
        return approval

    def check_two(self, receipt):
        self.assertCountEqual(self.calls,[('front',MODELS[0]),('back',MODELS[1])])
        self.assertEqual({key:row['model'] for key,row in receipt.items()}, dict(self.calls))

    @isolated_fees
    def test_photo_parallel_and_old_plan_model(self):
        pg = module('photo_generation')
        pl = module('photo_listing')
        manifest = {'store':{'venderId':'42','profile':'fixture'}, 'packageId':'photo-fixture'}
        tasks = [{'id':name,'prompt':name,'photos':[str(self.photo)],'size':'1024x1024',
                  'role':'main','sourceSha256':[pg.sha(self.photo)]} for name in ('front','back')]
        quote = pl.generation_quote(self.root,manifest,tasks)
        pg.atomic_json(self.root/'image-quote.json',quote)
        approval = self.consent(self.root)
        result = pg.generate_tasks(tasks,self.root/'.generation',approval=approval,scope=quote['scope'])
        self.check_two(result['ledger'])
        self.assertEqual(result['submittedCount'],2)
        self.assertCountEqual(result['modelsSubmitted'],MODELS)
        resumed = pg.generate_tasks(tasks,self.root/'.generation',scope=quote['scope'])
        self.assertEqual(resumed['submittedCount'],0)

        legacy = self.root/'old'
        scope = {key:value for key,value in quote['scope'].items() if key not in ('models','imageSizes')}
        scope['model'] = 'gpt-image-2.5'
        pg.atomic_json(legacy/'image-quote.json',dict(quote,scope=scope))
        legacy_quote = pl.generation_quote(legacy,manifest,tasks)
        self.assertEqual(legacy_quote['scope'],scope)
        self.calls.clear()
        self.sync = None
        approval = signed_fixture(dict(legacy_quote,billing='requests',maxRequests=2))
        pg.generate_tasks(tasks,legacy/'.generation',approval=approval,scope=scope)
        self.assertEqual(Counter(model for _,model in self.calls),{'gpt-image-2.5':2})

    @isolated_fees
    def test_matrix_parallel_with_per_slot_receipts(self):
        mx = module('matrix_listing')
        (self.root/'source-main').mkdir()
        items = []
        for name in ('front','back'):
            path = self.root/'source-main'/(name+'.jpg')
            path.write_bytes(self.photo.read_bytes())
            items.append(dict(stem=name,file=path.name,sha256=sha256(path.read_bytes()).hexdigest(),url='jfs/'+name))
        mx.save_json_atomic(self.root/'source-main-manifest.json',items)
        mx.save_json_atomic(self.root/'source-apply.json',{'productInfo':{'productName':'notebook'}})
        mx.save_json_atomic(self.root/'snapshot-scope.json',{'shop':{'venderId':'22','profile':'test'},'productId':'31'})
        mx.save_json_atomic(self.root/'variants.json',{'variants':{'a':{'prompts':{name:name for name in ('front','back')}}}})
        args=SimpleNamespace(run=str(self.root),variants=None,variant='a',only=None,redo=False,
                             fee_approval_file=None,quote_only=True)
        self.assertEqual(mx.generate_variant(args,self.root),0)
        out = self.root/'generated/a'
        self.consent(out)
        args.quote_only = False
        self.assertEqual(mx.generate_variant(args,self.root),0)
        self.check_two(json.loads((out/'ledger.json').read_bytes()))

    @isolated_fees
    def test_single_unknown_image_has_one_request_and_no_automatic_switch(self):
        pg = module('photo_generation')
        pl = module('photo_listing')
        task = {'id':'sample','role':'main','size':'1024x1024','prompt':'sample',
                'photos':[str(self.photo)],'sourceSha256':[pg.sha(self.photo)]}
        manifest = {'store':{'venderId':'41','profile':'fixture'}, 'packageId':'screen-fixture'}
        quote = pl.generation_quote(self.root,manifest,[task])
        grant = signed_fixture(dict(quote,billing='requests',maxRequests=1))
        with patch.object(pg.CompanyPhotoClient,'edit',side_effect=TimeoutError()) as call:
            result = pg.generate_tasks([task],self.root/'.generation',scope=quote['scope'],approval=grant)
            self.assertEqual((result['unknownCount'],result['submittedCount'],result['modelsSubmitted']), (1,1,[MODELS[0]]))
            with self.assertRaises(pg.GenerationUnknown):
                pg.generate_tasks([task],self.root/'.generation',scope=quote['scope'],approval=grant)
            call.assert_called_once()
        recovery = pg.inspect_attempts([task],self.root/'.generation',quote['scope'])['replacementQuote']
        self.assertEqual(recovery['creditCostsByUnit'],{'sample':3})

    @isolated_fees
    def test_replica_parallel_with_preserved_dimensions(self):
        company = module('company_jpeg_edits')
        from heideng_merchant.fee_consent import confirm_fee
        from heideng_merchant.state import merchant_home
        sizes = {'front':'2048x1536', 'back':'3840x2160', 'side':'1024x1024'}
        plan={'shop':{'venderId':'42','profile':'fixture'},'sourceProduct':'camera',
              'sources':[dict(imageKey=name,source=str(self.photo),sha=sha256(self.photo.read_bytes()).hexdigest(),
                              prompt=name,size=size) for name,size in sizes.items()]}
        company.generate_plan(plan,self.root,quote_only=True)
        quote_file = self.root/'image-quote.json'
        grant = self.root/'fee-approval.json'
        quote = json.loads(quote_file.read_bytes())
        self.assertEqual(quote['scope']['imageSizes'],sizes)
        self.assertEqual(quote['creditCostsByUnit'],{'front':4,'back':5,'side':3})
        self.assertEqual(quote['estimatedCredits'],12)
        with patch('heideng_merchant.fee_consent._ask_merchant',return_value=True):
            confirm_fee(quote,merchant_home(),grant,max_requests=2,selected_units=['front','back'])
        result = company.generate_plan(plan,self.root)
        self.assertEqual(result['deferredUnits'],['side'])
        selected = json.loads(quote_file.read_bytes())
        self.assertEqual((selected['selectedCredits'],selected['deferredCredits']), (9,3))
        self.check_two(json.loads((self.root/'generation.json').read_bytes()))
        company.generate_plan(plan,self.root,quote_only=True)
        remainder = json.loads(quote_file.read_bytes())
        self.assertEqual(remainder['creditCostsByUnit'],{'side':3})
        self.assertEqual(remainder['estimatedCredits'],3)
        self.sync = None
        with patch('heideng_merchant.fee_consent._ask_merchant',return_value=True):
            confirm_fee(remainder,merchant_home(),grant,max_requests=1,selected_units=['side'])
        company.generate_plan(plan,self.root)
        self.assertEqual(self.calls[-1],('side',MODELS[0]))
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.sizes,sizes)

    @isolated_fees
    def test_refresh_starts_both_models_without_waiting_for_first_image(self):
        common = load_refresh('_common',REFRESH/'scripts/_common.py')
        gen = load_refresh('merchant_dual_refresh',REFRESH/'scripts/generate.py')
        (self.root/'sources').mkdir()
        tasks = {}
        for name in ('front','back'):
            (self.root/'sources'/(name+'.img')).write_bytes(self.photo.read_bytes())
            tasks[name] = {'key':name,'productId':123}
        common.save_json(self.root/'job.json',{'profile':'fixture','venderId':42,'shopName':'fixture','productIds':[123]})
        common.save_json(self.root/'plan-batch.json',{'tasks':tasks,'products':[]})
        common.save_json(self.root/'host-prompts.json',{name:name for name in tasks})
        gen.main(['generate.py',str(self.root),'--quote-only'])
        self.consent(self.root)
        gen.main(['generate.py',str(self.root)])
        self.check_two(common.load_json(self.root/'internal-generation.json'))
