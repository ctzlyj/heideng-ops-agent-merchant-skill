import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from heideng_merchant.fee_consent import confirm_fee
from heideng_merchant.image_budget import reserve_request, validate_approval


class CategoryFeeTests(unittest.TestCase):
    def test_selected_batch_has_a_single_credit_ceiling_across_both_models(self):
        from heideng_merchant.image_models import image_credit_quote, model_scope
        scope = {'task':'catalogue', **model_scope()}
        units = ['front','detail','variant','side','back']
        sizes = dict(zip(units,['1024x1536','2048x1536','2880x2880','1024x1024','1536x1024']))
        scope['imageSizes'] = sizes
        quote = {'scope':scope, 'units':units, **image_credit_quote(sizes)}
        self.assertEqual(quote['maxCredits'],18)
        with TemporaryDirectory() as tmp, patch('heideng_merchant.fee_consent._ask_merchant',return_value=True) as ask:
            root = Path(tmp)
            grant = confirm_fee(quote,root,root/'grant.json',max_requests=5)
            self.assertEqual((grant['billing'],grant['maxCredits']),('credits',18))
            self.assertNotIn('¥',ask.call_args.args[0])
            self.assertIn('18 积分',ask.call_args.args[0])
            with patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':tmp}):
                for unit in units:
                    reserve_request(root,grant,scope=scope,units=units,request_id=unit)
                with self.assertRaisesRegex(ValueError,'上限'):
                    reserve_request(root,grant,scope=scope,units=units,request_id='front',
                                    previous_receipt={'status':'SUCCEEDED','sha256':'old'})
                with self.assertRaises(ValueError):
                    validate_approval(dict(grant,maxCredits=30),scope=scope,units=units)
            ask.assert_called_once()

    def test_another_chat_reuses_decision_for_same_quote_even_with_a_new_export_name(self):
        quote = {'scope':{'task':'same-photo-task','shop':'shop-one'}, 'units':['cover']}
        with TemporaryDirectory() as tmp, patch('heideng_merchant.fee_consent._ask_merchant',return_value=True) as ask:
            root = Path(tmp)
            first = confirm_fee(quote,root,root/'first/approval.json',max_requests=1,quote_path=root/'quote.json')
            second = confirm_fee(quote,root,root/'second/approval.json',max_requests=1,quote_path=root/'quote.json')
            self.assertEqual(first,second)
            ask.assert_called_once()
            third = confirm_fee(quote,root,root/'third/approval.json',max_requests=2,quote_path=root/'quote.json')
            self.assertNotEqual(first['approvalRef'],third['approvalRef'])
            self.assertEqual(ask.call_count,2)

    def test_one_decision_five_attempts_and_no_sixth_even_in_another_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            units = [f'variant-{n}' for n in range(6)]
            scope = {'shop':'fixture', 'products':['apparel-set'], 'model':'fixture'}
            quote = {'scope':scope, 'units':units, 'canSelectUnits': True}
            with patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':directory}), patch(
                    'heideng_merchant.fee_consent._ask_merchant', return_value=True) as decision:
                grant = confirm_fee(quote, root, root/'approval.json', max_requests=5, selected_units=units[:5])
                self.assertEqual(confirm_fee(quote, root, root/'approval.json', max_requests=5, selected_units=units[:5]), grant)
                decision.assert_called_once()
                calls = []
                for n in range(5):
                    reserve_request(root/'task', grant, scope=scope, units=grant['units'], request_id=units[n])
                    calls.append(n)
                with self.assertRaisesRegex(ValueError, '上限'):
                    reserve_request(root/'copy', grant, scope=scope, units=grant['units'], request_id=units[0],
                                    previous_receipt={'status':'SUCCEEDED','sha256':'original-image'})
                    calls.append(5)
                self.assertEqual(len(calls), 5)
                with self.assertRaises(ValueError):
                    validate_approval(dict(grant,maxRequests=8), scope=scope,units=grant['units'])
                with self.assertRaises(ValueError):
                    validate_approval(dict(grant,approvalRef='商家说去吧'),scope=scope,units=grant['units'])

    def test_unknown_and_cancel(self):
        quote = {'scope':{'task':'sample','possibleDuplicateCharge':True}, 'units':['sample']}
        with TemporaryDirectory() as tmp, patch('heideng_merchant.fee_consent._ask_merchant',return_value=False) as ask:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, '未批准'):
                confirm_fee({'replacementQuote':quote},root,root/'approval.json',max_requests=1)
            self.assertIn('可能再次计费', ask.call_args.args[0])
            self.assertFalse((root/'approval.json').exists())
            self.assertFalse((root/'fee-consents').exists())
