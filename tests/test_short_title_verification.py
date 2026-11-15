"""Original native title field; no real merchant reads."""
import copy, hashlib, importlib.util, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heideng_merchant.safety import SafetyError
from heideng_merchant.operations import digest

class OriginalTitleFieldTests(unittest.TestCase):
    def extract(self, value, original=('101', '102'), product='11'):
        spec = importlib.util.find_spec('heideng_merchant.short_title_verification')
        self.assertIsNotNone(spec, 'C3 native title-field extractor is not implemented')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.title_detail_observation(value, product, list(original))

    def detail(self):
        return {'productId': '11', 'skuList': [
            {'skuId': '102', 'productId': '11', 'skuName': 'Long B', 'features': {'shortTitle': 'Short B'}},
            {'skuId': '101', 'productId': '11', 'skuName': 'Long A', 'features': {'shortTitle': 'Short A'}}]}

    def test_exact_detail_field_and_original_order_without_raw_response(self):
        source = self.detail(); result = self.extract(source)
        self.assertEqual([r['skuId'] for r in result['rows']], ['101', '102'])
        self.assertEqual([r['actualShortTitle'] for r in result['rows']], ['Short A', 'Short B'])
        self.assertTrue(result['originalSkuCoverageComplete'])
        self.assertEqual(result['detailSha256'], digest(source))
        self.assertEqual(result['field'], 'skuList[].features.shortTitle')
        self.assertNotIn('skuName', json.dumps(result))
        self.assertFalse(result['formalAuditVerified'])
        self.assertFalse(result['healthVerified'])
        self.assertFalse(result['imported'])
        self.assertFalse(result['retryAuthorized'])

    def test_no_long_title_or_health_flag_fallback(self):
        source = self.detail(); source['skuList'][0].pop('features')
        source['skuList'][0]['shortTitle'] = 'not the audited field'
        source['skuList'][0]['hasShortTitle'] = True
        result = self.extract(source)['rows'][1]
        self.assertFalse(result['fieldObserved']); self.assertIsNone(result['actualShortTitle'])
        self.assertEqual(result['reason'], 'exact-short-title-field-missing')

    def test_empty_short_title_is_observed_empty_not_missing(self):
        source = self.detail(); source['skuList'][0]['features']['shortTitle'] = ''
        result = self.extract(source)['rows'][1]
        self.assertTrue(result['fieldObserved']); self.assertEqual(result['actualShortTitle'], '')

    def test_missing_original_row_preserved_unknown(self):
        source = self.detail(); source['skuList'] = source['skuList'][1:]
        result = self.extract(source)
        self.assertEqual(len(result['rows']), 2); self.assertFalse(result['originalSkuCoverageComplete'])
        self.assertEqual(result['missingOriginalSkuIds'], ['102'])
        self.assertIsNone(result['rows'][1]['actualShortTitle']); self.assertFalse(result['rows'][1]['fieldObserved'])
        self.assertEqual(result['rows'][1]['reason'], 'original-sku-not-in-current-detail')

    def test_added_current_sku_not_injected_into_original_rows(self):
        source = self.detail(); source['skuList'].append({'skuId': '103', 'features': {'shortTitle': 'New'}})
        result = self.extract(source)
        self.assertEqual(result['additionalCurrentSkuIds'], ['103'])
        self.assertEqual(len(result['rows']), 2); self.assertFalse(result['originalSkuCoverageComplete'])

    def test_current_offsale_sku_remains_original_row(self):
        source = self.detail(); source['skuList'][0]['status'] = 0
        result = self.extract(source)
        self.assertEqual(result['rows'][1]['skuId'], '102'); self.assertTrue(result['rows'][1]['fieldObserved'])

    def test_duplicate_current_sku_refused_even_if_equal(self):
        source = self.detail(); source['skuList'].append(copy.deepcopy(source['skuList'][0]))
        with self.assertRaises(SafetyError): self.extract(source)

    def test_duplicate_or_noncanonical_original_scope_refused(self):
        for original in [('101', '101'), ('0101', '102'), (True, '102'), ('101', 102.0), ()]:
            with self.subTest(original=original), self.assertRaises(SafetyError): self.extract(self.detail(), original)

    def test_wrong_parent_or_product_identity_refused(self):
        source = self.detail(); source['skuList'][0]['productId'] = '22'
        with self.assertRaises(SafetyError): self.extract(source)
        source = self.detail(); source['productId'] = '22'
        with self.assertRaises(SafetyError): self.extract(source)

    def test_malformed_title_value_not_coerced(self):
        for value in [None, 3, True, {}, [], 'A\u0000B', 'A\nB']:
            source = self.detail(); source['skuList'][0]['features']['shortTitle'] = value
            with self.subTest(value=value), self.assertRaises(SafetyError): self.extract(source)

    def test_sensitive_title_and_unknown_body_fields_refused(self):
        for change in ('title', 'body'):
            source = self.detail()
            if change == 'title': source['skuList'][0]['features']['shortTitle'] = 'Bearer synthetic-secret-only'
            else: source['authorization'] = 'Bearer synthetic-secret-only'
            with self.subTest(change=change), self.assertRaises(SafetyError): self.extract(source)

    def test_detail_wrappers_consistent_or_conflicting(self):
        source = self.detail(); rows = source.pop('skuList'); source['productInfo'] = {'productId': '11', 'skuList': rows}
        result = self.extract(source); self.assertEqual(result['rows'][0]['actualShortTitle'], 'Short A')
        source['skuList'] = copy.deepcopy(rows)
        self.assertEqual(self.extract(source)['rows'], result['rows'])
        source['skuList'][0]['features']['shortTitle'] = 'Other'
        with self.assertRaises(SafetyError): self.extract(source)

    def test_missing_or_nonlist_native_sku_list_refused(self):
        for source in [{'productId': '11'}, {'productId': '11', 'skuList': {}}, {'productId': '11', 'skuList': [True]}]:
            with self.subTest(source=source), self.assertRaises(SafetyError): self.extract(source)

if __name__ == '__main__': unittest.main(verbosity=2)
