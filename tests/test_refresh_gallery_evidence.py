"""Independent edit-detail evidence and offline merchant progress for batched first images."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from heideng_merchant import gallery_patch as gallery
from tests.gallery_fixture import apply_patch, detail
from tests.test_mature_refresh import load, SOURCE


class GalleryEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.run = Path(temp.name)
        env = patch.dict(os.environ, {"HEIDENG_MERCHANT_HOME": str(self.run)})
        env.start()
        self.addCleanup(env.stop)
        path = patch.object(sys, "path", [str(SOURCE / "scripts"), *sys.path])
        path.start()
        self.addCleanup(path.stop)
        modules = {name: sys.modules.pop(name, None) for name in ("_common", "no_window", "detail_patch_update")}
        def restore():
            for name, original in modules.items():
                sys.modules.pop(name, None)
                if original is not None:
                    sys.modules[name] = original
        self.addCleanup(restore)
        self.common = load("_common", SOURCE / "scripts/_common.py")
        self.shop = {"profile": "fixture", "shopId": 6, "venderId": 5, "shopName": "玻璃杯店"}
        self.cli = Mock(STATE_ROOT=self.run)
        self.cli.JdoError = ValueError
        self.live = detail()
        self.live["skuList"][0]["saleAttrs"][0]["mappingId"] = "blue-edit-id"
        self.original = deepcopy(self.live)
        self.selected = [{"group": "blue", "key": "asset", "url": "shared", "position": 1}]
        self.product = {"productId": 41, "title": "海蓝杯", "positions": self.selected, "selectedSlots": self.selected}

    def publish(self, baseline, slots, mapping, directory):
        return gallery.frozen_patch(self.cli, lambda pid: deepcopy(self.live), self.shop, 41,
                                    baseline, mapping, [1], 9, self.run / directory, str, slots)

    def test_prior_unknown_recovers_exact_slots_with_omitted_mapping_then_applies_next_batch_once(self):
        def first_dispatch(**kwargs):
            apply_patch(self.live, kwargs["body_path"])
            del self.live["skuList"][0]["saleAttrs"][0]["mappingId"]
            raise TimeoutError("receipt lost")
        self.cli.run_jdo_large.side_effect = first_dispatch
        with self.assertRaises(TimeoutError):
            self.publish(self.original, self.selected, {"shared": "A"}, "first")
        second_original = deepcopy(self.live)
        self.cli.run_jdo_large.side_effect = lambda **kw: apply_patch(self.live, kw["body_path"])
        red = [{**self.selected[0], "group": "red"}]
        result = self.publish(second_original, red, {"shared": "B"}, "rest")
        self.assertEqual(result["changedSlots"], 1)
        self.assertEqual(result["consumerPageStatus"], "unchecked")
        self.assertTrue(self.publish(second_original, red, {"shared": "B"}, "rest")["ok"])
        self.assertEqual(self.cli.run_jdo_large.call_count, 2)
        groups = gallery.snapshot(self.live, 41)["groups"]
        self.assertEqual(groups["blue"], ["A", "b-detail", "shared"])
        self.assertEqual(groups["red"], ["B", "r-detail"])
        self.assertEqual(groups[gallery.PUBLIC_GROUP], ["shared"])

    def test_changed_nonempty_mapping_price_and_wrong_slot_remain_unverified(self):
        before = gallery.snapshot(self.original, 41)
        after = deepcopy(before)
        after["skus"]["301"]["attributes"][0]["mappingId"] = "different-edit-id"
        after["skus"]["302"]["price"] = 20
        after["groups"]["blue"][2] = "unexpected"
        self.assertEqual(set(gallery.gallery_readback(before, after)["fieldDifferences"]),
                         {"saleAttrs.mappingId", "price", "gallerySlot"})
        before["skus"]["301"]["attributes"][0]["attrValues"] = "unmatched"
        after = deepcopy(before)
        after["skus"]["301"]["attributes"][0]["mappingId"] = ""
        self.assertIn("saleAttrs.mappingId/owner-unverified", gallery.gallery_readback(before, after)["fieldDifferences"])

    def test_unknown_first_request_without_landing_proof_never_dispatches_another(self):
        self.cli.run_jdo_large.side_effect = TimeoutError("unknown")
        with self.assertRaises(TimeoutError):
            self.publish(self.original, self.selected, {"shared": "A"}, "first")
        red = [{**self.selected[0], "group": "red"}]
        pending = self.publish(self.original, red, {"shared": "B"}, "rest")
        self.assertEqual(pending["status"], "prior-edit-pending")
        self.assertFalse(pending["newRequestApplied"])
        self.cli.run_jdo_large.assert_called_once()

    def test_verify_checks_selected_group_and_proves_stable_sku_owner_on_omission(self):
        verify = load("refresh_gallery_evidence_verify", SOURCE / "scripts/verify.py")
        upload = {"asset": {"status": "succeeded", "imgUrl": "new", "sha256": "fixture-digest"}}
        self.live["skuList"][0]["saleAttrs"][0]["mappingId"] = ""
        images = self.live["material"]["mainImages"]
        images[0]["imageInfoList"][0]["imgUrl"] = "new"
        args = (self.original, self.live, self.product, {"positionFilter": [1]}, {}, upload, 0, None)
        result = verify.evaluate_product(*args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["newImages"], 1)
        self.assertEqual(result["mappingIdOmittedSkuCount"], 1)
        self.assertEqual(result["verifiedAssets"]["asset"]["imgUrl"], "new")
        images[1]["imageInfoList"][0]["imgUrl"] = "new"
        self.assertFalse(verify.evaluate_product(*args)["ok"])
        self.assertEqual(verify.evaluate_product(*args)["verifiedAssets"], {})

    def test_progress_and_sample_ten_distinct_products_offline(self):
        report = load("refresh_gallery_evidence_report", SOURCE / "scripts/report.py")
        compare = load("refresh_gallery_evidence_compare", SOURCE / "scripts/compare.py")
        (self.run / "sources").mkdir()
        (self.run / "generated").mkdir()
        products, tasks = [], {}
        for i in range(12):
            pid, key = 100 + i, str(i)
            slot = {"group": "blue", "key": key, "position": 1, "sourceKey": key, "url": key}
            products.append({"productId": pid, "title": "玻璃杯", "positions": [slot], "selectedSlots": [slot]})
            tasks[key] = {"productId": pid}
            for path in (self.run / "sources" / (key + ".img"), self.run / "generated" / (key + ".png")):
                Image.new("RGB", (32, 32), (10 + i, 20, 30)).save(path, format="PNG")
        for name, payload in {
            "job": self.shop, "plan-batch": {"products": products, "tasks": tasks},
            "internal-generation": {"0": {"status": "succeeded", "reusedSample": {"key": "sample"}},
                                    "1": {"status": "succeeded"}},
            "uploads": {"0": {"status": "unknown"}},
            "patch-results": {"999": {"ok": True, "status": "verified-in-edit-detail"}},
        }.items():
            self.common.save_json(self.run / (name + ".json"), payload)
        stream = StringIO()
        with redirect_stdout(stream):
            report.main(["report.py", str(self.run), "--progress"])
        counts = json.loads(stream.getvalue())
        self.assertEqual((counts["targetProducts"], counts["plannedAssets"]), (12, 12))
        self.assertEqual((counts["newImagesSucceeded"], counts["approvedSamplesReused"]), (1, 1))
        self.assertEqual((counts["unresolvedUploads"], counts["patchVerifiedProducts"]), (1, 0))
        compare.main(["compare.py", str(self.run), "--sample", "10"])
        image = self.run / "sample-10-products.png"
        self.assertTrue(image.is_file())
        with Image.open(image) as opened:
            self.assertEqual(opened.height, 46 + 10 * 60)
        self.assertFalse(any((self.run / "comparisons").iterdir()))


if __name__ == "__main__":
    unittest.main()
