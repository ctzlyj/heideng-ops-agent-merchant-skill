import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from heideng_merchant.fee_consent import confirm_fee
from heideng_merchant.image_budget import reserve_request, validate_approval


class CategoryFeeTests(unittest.TestCase):
    def test_one_decision_five_attempts_and_no_sixth_even_in_another_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            units = [f'variant-{n}' for n in range(6)]
            scope = {'shop':'fixture', 'products':['apparel-set'], 'model':'fixture'}
            quote = {'scope':scope, 'units':units}
            with patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':directory}), patch(
                    'heideng_merchant.fee_consent._ask_merchant', return_value=True) as decision:
                grant = confirm_fee(quote, root, root/'approval.json', max_requests=5)
                self.assertEqual(confirm_fee(quote, root, root/'approval.json', max_requests=5), grant)
                decision.assert_called_once()
                calls = []
                for n in range(5):
                    reserve_request(root/'task', grant, scope=scope, units=units, request_id=units[n])
                    calls.append(n)
                with self.assertRaisesRegex(ValueError, '上限'):
                    reserve_request(root/'copy', grant, scope=scope, units=units, request_id=units[5])
                    calls.append(5)
                self.assertEqual(len(calls), 5)
                with self.assertRaises(ValueError):
                    validate_approval(dict(grant,maxRequests=8), scope=scope,units=units)
                with self.assertRaises(ValueError):
                    validate_approval(dict(grant,approvalRef='商家说去吧'),scope=scope,units=units)

    def test_unknown_and_cancel(self):
        quote = {'scope':{'task':'sample','possibleDuplicateCharge':True}, 'units':['sample']}
        with TemporaryDirectory() as tmp, patch('heideng_merchant.fee_consent._ask_merchant',return_value=False) as ask:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, '未批准'):
                confirm_fee({'replacementQuote':quote},root,root/'approval.json',max_requests=1)
            self.assertIn('可能再次计费', ask.call_args.args[0])
            self.assertFalse((root/'approval.json').exists())
            self.assertFalse((root/'fee-consents').exists())
