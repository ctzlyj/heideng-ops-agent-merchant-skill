"""Offline acceptance for a nickname, cross-domain evidence and a paid request cap."""
from tests.fee_consent import isolated_fees, signed_fixture
import concurrent.futures
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from heideng_merchant.commerce_evidence import compare_evidence
from heideng_merchant.image_budget import reserve_request, validate_approval


class CommerceTests(unittest.TestCase):
    @isolated_fees
    def test_amount_and_concurrent_last_request(self):
        scope = {'shop': '101', 'task': 'revision'}
        units = ['main-1', 'main-2']
        approval = signed_fixture(dict(scope=scope, units=units, approvalRef='message-8', billing='amount',
                        maxRequests=2, unitPriceUpperBound='0.75', maxAmount='1.50',
                        priceEvidence='fixture rate', currency='CNY'))
        with self.assertRaises(ValueError):
            validate_approval(dict(approval, maxAmount='0.74'), scope=scope, units=units)
        with tempfile.TemporaryDirectory() as tmp:
            reserve_request(tmp, approval, scope=scope, units=units, request_id=units[0])
            def reserve(key):
                try:
                    prior = {'status':'SUCCEEDED', 'sha256':'initial'} if key == units[0] else None
                    reserve_request(tmp, approval, scope=scope, units=units, request_id=key, previous_receipt=prior)
                    return True
                except ValueError:
                    return False
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(reserve, units))
            self.assertEqual(sum(results), 1)
            used = units[results.index(True)]
            with self.assertRaisesRegex(ValueError, '原生图请求'):
                reserve_request(tmp, signed_fixture(dict(approval, approvalRef='new-message')), scope=scope,
                                units=units, request_id=used,
                                previous_receipt={'status':'SUCCEEDED', 'sha256':'initial'} if used == units[0] else None)

    def test_aligned_funnel_and_incomplete_sources(self):
        periods = {'baseline': ['2026-10-01', '2026-10-07'], 'current': ['2026-10-08', '2026-10-14']}
        rows = []
        for period, clicks, orders in [('baseline', 100, 8), ('current', 150, 6)]:
            for domain, basis, metrics in [
                ('ads', 'click attribution 7d CNY', {'clicks': clicks, 'attributedOrders': orders}),
                ('sales', 'effective paid orders', {'orders': orders + 4}),
                ('service', 'all consultations re size', {'consultations': 12, 'concernSamples': 3}),
                ('returns', 'completed return date, size', {'returns': 3, 'reasonSamples': 2}),
            ]:
                rows.append(dict(shopId='101', venderId='202', spuId='303', domain=domain, period=period,
                                 window=periods[period], source='fixture-'+period, channel='POP', basis=basis, metrics=metrics))
        def compare():
            return compare_evidence(dict(periods=periods, rows=rows), '101', '202', '303')
        report = compare()
        self.assertEqual(len(report['observations']), 4)
        self.assertEqual(report['observations']['ads']['baseline']['attributedOrdersPerClick'], 0.08)
        self.assertEqual(report['observations']['ads']['current']['attributedOrdersPerClick'], 0.04)
        rows.pop()
        rows[-1]['window'] = periods['baseline']
        report = compare()
        self.assertSetEqual(set(report['observations']), {'ads', 'sales', 'service','returns'})
        self.assertNotIn('current', report['observations']['service'])
        self.assertFalse(report['observations']['returns']['comparable'])
        self.assertTrue(report['gaps'])
        rows[-1]['shopId'] = '102'
        with self.assertRaises(ValueError):
            compare()

    def test_calendar_month_totals_daily_averages_and_current_only(self):
        periods = {'baseline':['2026-09-01','2026-09-30'], 'current':['2026-10-01','2026-10-31']}
        rows = [dict(shopId='101',venderId='202',spuId='303',domain='ads',period=p,window=w,
                     basis='7d click CNY',channel='ads',source=p,metrics={'spend':v})
                for (p,w),v in zip(periods.items(), [300,620])]
        result = compare_evidence({'periods':periods,'rows':rows}, '101','202','303')
        self.assertEqual(result['days'], {'baseline':30,'current':31})
        ads = result['observations']['ads']
        self.assertTrue(ads['comparable'])
        self.assertEqual(ads['baseline']['spend'],300)
        self.assertEqual(ads['perDay']['current']['spend'],20)
        rows[-1]['metrics'] = {'spend':200}
        result = compare_evidence({'periods':{'current':periods['current']},'rows':rows[-1:]},'101','202','303')
        ads = result['observations']['ads']
        self.assertEqual(ads['current']['spend'],200)
        self.assertIsNone(ads['current']['attributedOrdersPerClick'])
        self.assertFalse(ads['comparable'])
        self.assertNotIn('baseline',ads)

    def test_alias_survives_new_view_and_conflict(self):
        app = Path(__file__).resolve().parents[1] / 'mature/connection/app'
        with patch.object(sys, 'path', [str(app), *sys.path]):
            spec = importlib.util.spec_from_file_location('field_alias_shoplib', app/'shoplib.py')
            shoplib = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shoplib)
        official = dict(ok=True, status='ready', shopId='100', venderId='701', shopName='川品牌店')
        reg = {'profiles': {'hm-a': dict(official), 'hm-b': dict(official, shopId='200', venderId='702', shopName='川优选店')}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'JINGMAI_LINKER_HOME': tmp,
                'JDO_HOME': str(Path(tmp)/'cli')}), patch.object(shoplib, '_proof_data', return_value={}):
            with patch.object(shoplib, 'resolve', return_value=official):
                self.assertEqual(shoplib.remember_confirmed_alias('701', '川马桶')['status'], 'ready')
            view = shoplib.build_view(reg)
            self.assertEqual(shoplib.match_groups(view, '川马桶')[0]['profiles'], ['hm-a'])
            with patch.object(shoplib, 'resolve', return_value=dict(official, venderId='702', shopId='200')):
                self.assertEqual(shoplib.remember_confirmed_alias('702', '川马桶')['status'], 'ambiguous')
