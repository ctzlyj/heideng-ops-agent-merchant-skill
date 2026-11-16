"""HD-014 pagination diagnostics, using only synthetic native page responses."""
import unittest
from pathlib import Path
from unittest.mock import patch

from heideng_merchant.operations import digest
from heideng_merchant.products import ProductService
from heideng_merchant.safety import SafetyError


class FeedbackPaginationTests(unittest.TestCase):
    def page(self, ids, total=None, kind="products"):
        field = "productId" if kind == "products" else "skuId"
        rows = [{field: value} for value in ids]
        if kind == "skus":
            for row in rows:
                row["productId"] = 100
        result = {"data": rows}
        if total is not None:
            result["paginationData"] = {"totalItems": total}
        return result

    def listing(self, kind, pages, **kwargs):
        # Stub only the read boundary: no official client, account or state files.
        service = ProductService(Path.cwd(), object())
        with patch.object(service, "_read", side_effect=pages) as read:
            if kind == "skus":
                result = service.list_skus("merchant-synthetic", "100", **kwargs)
            else:
                result = getattr(service, "list_" + kind)("merchant-synthetic", **kwargs)
        self.assertEqual([call.args[2]["page"] for call in read.call_args_list],
                         list(range(kwargs.get("start_page", 1),
                                    kwargs.get("start_page", 1) + len(pages))))
        return result

    def diagnostics(self, result, *, returned, observed, unique, duplicates,
                    totals, unobserved, unreturned, complete=False):
        # These gaps compare against reported metadata, not a verified population.
        self.assertEqual(result.get("paginationDiagnostics"), {
            "statisticsScope": "complete-result" if complete else "partial-result",
            "returnedRowCount": returned,
            "returnedUniqueCount": returned,
            "observedRowCount": observed,
            "observedUniqueCount": unique,
            "duplicateRowCount": duplicates,
            "unreturnedObservedUniqueCount": unique - returned,
            "reportedTotals": totals,
            "totalStable": len(totals) == 1 if totals else None,
            "unobservedReportedCount": unobserved,
            "unreturnedReportedCount": unreturned,
        })

    def test_50_plus_14_with_11_repeats_reports_observation_not_a_deduped_census(self):
        for kind in ("products", "skus", "health"):
            with self.subTest(kind=kind):
                first = self.page(range(1, 51), 64, kind)
                second = self.page(list(range(1, 12)) + [51, 52, 53], 64, kind)
                result = self.listing(kind, [first, second], page_size=50, max_pages=10)
                self.assertEqual(result["items"], first["data"])
                self.assertFalse(result["complete"])
                self.assertFalse(result["segmentComplete"])
                self.assertEqual(result["reason"], "pagination-identity-repeat")
                self.assertEqual(result["nextPage"], 2)
                self.assertEqual(result["reportedTotal"], 64)
                self.assertEqual(result["sourcePageHashes"], [digest(first)])
                self.diagnostics(result, returned=50, observed=64, unique=53,
                                 duplicates=11, totals=[64], unobserved=11, unreturned=14)

    def test_within_first_page_repeat_rejects_the_whole_page(self):
        result = self.listing("products", [self.page([1, 1, 2], 3)], page_size=3)
        self.assertEqual(result["items"], [])
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "pagination-identity-repeat")
        self.assertEqual(result["nextPage"], 1)
        # Preserve the existing metadata/hash semantics for a rejected first page.
        self.assertIsNone(result["reportedTotal"])
        self.assertEqual(result["sourcePageHashes"], [])
        self.diagnostics(result, returned=0, observed=3, unique=2,
                         duplicates=1, totals=[3], unobserved=1, unreturned=3)

    def test_within_later_page_repeat_counts_extra_occurrences_not_repeated_ids(self):
        result = self.listing("products", [self.page([1, 2], 6),
                               self.page([3, "3", 3, 4], 6)], page_size=4)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["reason"], "pagination-identity-repeat")
        self.assertEqual(result["nextPage"], 2)
        self.diagnostics(result, returned=2, observed=6, unique=4,
                         duplicates=2, totals=[6], unobserved=2, unreturned=4)

    def test_numeric_and_string_ids_are_the_same_across_pages(self):
        result = self.listing("products", [self.page([1, 2], 4),
                               self.page(["1", 3], 4)], page_size=2)
        self.assertFalse(result["complete"])
        self.assertEqual(result["nextPage"], 2)
        self.assertEqual(result["reason"], "pagination-identity-repeat")
        self.diagnostics(result, returned=2, observed=4, unique=3,
                         duplicates=1, totals=[4], unobserved=1, unreturned=2)

    def test_numeric_and_string_ids_are_the_same_within_a_page(self):
        result = self.listing("products", [self.page([1, "1"], 2)], page_size=2)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["reason"], "pagination-identity-repeat")
        self.diagnostics(result, returned=0, observed=2, unique=1,
                         duplicates=1, totals=[2], unobserved=1, unreturned=2)

    def test_dynamic_total_rejects_changed_page_and_does_not_claim_a_known_gap(self):
        for new_total in (3, 5):
            with self.subTest(new_total=new_total):
                first = self.page([1, 2], 4)
                result = self.listing("products", [first, self.page([3, 4], new_total)],
                                      page_size=2, max_pages=10)
                self.assertEqual(result["items"], first["data"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["nextPage"], 2)
                self.assertEqual(result["reason"], "pagination-total-changed")
                self.assertEqual(result["reportedTotal"], 4)
                self.assertEqual(result["sourcePageHashes"], [digest(first)])
                self.diagnostics(result, returned=2, observed=4, unique=4,
                                 duplicates=0, totals=[4, new_total],
                                 unobserved=None, unreturned=None)

    def test_repeat_reason_keeps_priority_but_changed_total_is_still_diagnosed(self):
        result = self.listing("products", [self.page([1, 2], 4),
                               self.page(["1", 3], 5)], page_size=2)
        self.assertEqual(result["reason"], "pagination-identity-repeat")
        self.assertEqual(result["nextPage"], 2)
        self.diagnostics(result, returned=2, observed=4, unique=3,
                         duplicates=1, totals=[4, 5], unobserved=None, unreturned=None)

    def test_page_budget_leaves_statistics_partial_with_a_reported_gap(self):
        result = self.listing("products", [self.page(range(1, 51), 64)],
                              page_size=50, max_pages=1)
        self.assertFalse(result["complete"])
        self.assertFalse(result["segmentComplete"])
        self.assertEqual(result["reason"], "page-budget-reached")
        self.assertEqual(result["nextPage"], 2)
        self.diagnostics(result, returned=50, observed=50, unique=50,
                         duplicates=0, totals=[64], unobserved=14, unreturned=14)

    def test_budget_without_a_reported_total_keeps_gap_unknown(self):
        result = self.listing("products", [self.page([1, 2])], page_size=2, max_pages=1)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "page-budget-reached")
        self.diagnostics(result, returned=2, observed=2, unique=2,
                         duplicates=0, totals=[], unobserved=None, unreturned=None)

    def test_earlier_unread_pages_are_not_a_full_population_even_if_segment_finished(self):
        result = self.listing("products", [self.page([3, 4], 4)],
                              page_size=2, start_page=2)
        self.assertFalse(result["complete"])
        self.assertTrue(result["segmentComplete"])
        self.assertEqual(result["reason"], "earlier-pages-not-in-this-result")
        self.assertIsNone(result["nextPage"])
        self.diagnostics(result, returned=2, observed=2, unique=2,
                         duplicates=0, totals=[4], unobserved=2, unreturned=2)

    def test_native_read_failure_stops_without_retry_or_invented_observations(self):
        result = self.listing("products", [self.page([1, 2], 4),
                               TimeoutError("synthetic-timeout")], page_size=2)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "native-product-read-incomplete")
        self.assertEqual(result["nextPage"], 2)
        self.diagnostics(result, returned=2, observed=2, unique=2,
                         duplicates=0, totals=[4], unobserved=2, unreturned=2)

    def test_total_mismatch_remains_partial_even_with_no_positive_reported_gap(self):
        result = self.listing("products", [self.page([1, 2], 3),
                               self.page([3, 4], 3)], page_size=2)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "pagination-total-mismatch")
        self.diagnostics(result, returned=4, observed=4, unique=4,
                         duplicates=0, totals=[3], unobserved=0, unreturned=0)

    def test_nonoverlapping_50_plus_14_retains_the_existing_complete_semantics(self):
        result = self.listing("products", [self.page(range(1, 51), 64),
                               self.page(range(51, 65), 64)], page_size=50)
        self.assertTrue(result["complete"])
        self.assertTrue(result["segmentComplete"])
        self.assertIsNone(result["reason"])
        self.assertIsNone(result["nextPage"])
        self.assertEqual(len(result["sourcePageHashes"]), 2)
        self.diagnostics(result, returned=64, observed=64, unique=64,
                         duplicates=0, totals=[64], unobserved=0, unreturned=0, complete=True)

    def test_empty_total_and_short_page_without_total_keep_existing_end_rules(self):
        for ids, total in (([], 0), ([1], None)):
            with self.subTest(ids=ids, total=total):
                result = self.listing("products", [self.page(ids, total)], page_size=2)
                self.assertTrue(result["complete"])
                self.diagnostics(result, returned=len(ids), observed=len(ids), unique=len(ids),
                                 duplicates=0, totals=[] if total is None else [total],
                                 unobserved=None if total is None else 0,
                                 unreturned=None if total is None else 0, complete=True)

    def test_page_size_limit_error_names_actual_endpoint_limit_before_any_read(self):
        service = ProductService(Path.cwd(), object())
        for kind, maximum in (("products", 50), ("skus", 50), ("health", 100)):
            with self.subTest(kind=kind), patch.object(service, "_read") as read:
                with self.assertRaises(SafetyError) as caught:
                    if kind == "skus":
                        service.list_skus("merchant-synthetic", "100", page_size=maximum + 1)
                    else:
                        getattr(service, "list_" + kind)("merchant-synthetic", page_size=maximum + 1)
                self.assertIn("bounded-pagination-required", str(caught.exception))
                self.assertIn("pageSize must be 1.." + str(maximum), str(caught.exception))
                read.assert_not_called()

    def test_actual_page_size_limits_are_accepted(self):
        for kind, maximum in (("products", 50), ("skus", 50), ("health", 100)):
            with self.subTest(kind=kind):
                result = self.listing(kind, [self.page([], 0, kind)], page_size=maximum)
                self.assertTrue(result["complete"])

    def test_other_invalid_pagination_arguments_keep_error_root_and_do_not_read(self):
        service = ProductService(Path.cwd(), object())
        for kwargs in ({"page_size": True}, {"page_size": 0}, {"page_size": "50"},
                       {"max_pages": 0}, {"max_pages": 1001}, {"max_pages": True},
                       {"start_page": 0}, {"start_page": True}):
            with self.subTest(kwargs=kwargs), patch.object(service, "_read") as read:
                with self.assertRaisesRegex(SafetyError, "bounded-pagination-required"):
                    service.list_products("merchant-synthetic", **kwargs)
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
