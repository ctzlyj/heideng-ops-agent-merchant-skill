"""Synthetic contract for the real refresh CLI stages in both installed layouts."""
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


def contract(scripts):
    sys.path.insert(0, str(scripts))
    import _common as common
    import build_plan
    import generate
    from PIL import Image
    import new_job
    import upload
    import verify

    def detail(blue, red):
        return {
            "productInfo": {"productId": 41, "productName": "Fixture product", "productStatus": 103,
                            "categoryDetail": {"lastCategoryId": 7}},
            "skuList": [{"skuId": sku, "saleAttrs": [{"dim": 1, "attrValues": group}],
                         "priceInfo": {"jdPrice": 10}} for sku, group in [(71, "blue"), (72, "red")]],
            "material": {"mainImages": [{"uuid": group, "imageInfoList": [{"orderSort": 1, "imgUrl": url}]}
                                        for group, url in [("blue", blue), ("red", red)]]},
        }

    def expect_failure(fn, *args):
        try:
            fn(*args)
        except SystemExit as exc:
            assert exc.code == 1, exc.code
        else:
            raise AssertionError("an unresolved operation was reported as complete")

    shop = {"profile": "fixture", "venderId": 1, "shopName": "fixture"}
    with tempfile.TemporaryDirectory() as temp:
        run = Path(temp)
        before = detail("blue-old", "red-old")
        report = {"status": "batch-status", "targetShop": shop,
                  "rows": [{"sourceProductId": "8", "targetProductId": t,
                            "comparison": {"readbackView": "product"}} for t in ["41", "42"]]}
        common.save_json(run / "batch.json", report)
        new_job.main(["new_job.py", str(run / "two"), "--profile", "fixture", "--vender-id", "1",
                      "--shop-name", "fixture", "--main-selection", "per-link", "--copy-batch-report",
                      str(run / "batch.json")])
        assert common.load_job(run / "two")["mainSelection"]["sourceByProduct"] == {"41": "8", "42": "8"}

        common.save_json(run / "job.json", {**shop, "productIds": [41]})
        plan = common.build_plan({41: before}, order=[41], scopes=["main"])
        common.save_json(run / "plan-batch.json", plan)
        common.save_json(run / "products/41/before-apply.json", before)
        keys = list(plan["tasks"])
        common.save_json(run / "uploads.json", {k: {"status": "succeeded", "imgUrl": url}
                                                for k, url in zip(keys, ["blue-new", "red-new"])})
        cli = Mock()
        cli.get.return_value = {"data": [{"productId": 41, "productStatus": 103}],
                                "paginationData": {"totalItems": 32000}}
        with patch.object(common, "connect", return_value=cli), patch.object(common, "verify_identity"), \
                patch.object(common, "apply_detail", return_value=detail("red-new", "blue-new")):
            expect_failure(verify.main, ["verify.py", str(run)])
            assert cli.get.call_count == 1
        assert common.load_json(run / "final-verification.json")["41"]["fieldDifferences"]["gallerySlot"]["count"] == 2
        with patch.object(common, "connect", return_value=cli), patch.object(common, "verify_identity"), \
                patch.object(common, "apply_detail", return_value=detail("blue-new", "red-new")):
            verify.main(["verify.py", str(run)])
        assert common.load_json(run / "final-verification.json")["41"]["ok"]

        # The original reviewed output stays byte-identical; neither host needs a gateway key.
        old = run / "pilot"
        old_task = plan["tasks"][keys[0]]
        for directory in ("sources", "generated"):
            (old / directory).mkdir(parents=True, exist_ok=True)
        source_file = old_task["sourceKey"] + ".img"
        reference_file = old / "sources" / source_file
        Image.new("RGB", (72, 48), "lightblue").save(reference_file, format="PNG")
        reference = reference_file.read_bytes()
        sample = old / "generated" / (keys[0] + ".png")
        Image.new("RGB", (1024, 1024), "blue").save(sample)
        old_hash = sha256(sample.read_bytes()).hexdigest()
        common.save_json(old / "identity.json", shop)
        common.save_json(old / "plan-batch.json", plan)
        common.save_json(old / "internal-generation.json", {keys[0]: {
            "status": "succeeded", "sourceSha256": sha256(reference).hexdigest(), "productId": 41,
            "prompt": "User approved design", "role": "main", "url": old_task["currentUrl"],
            "size": "1024x1024", "outputSha256": old_hash}})
        bulk = run / "bulk"
        new_job.main(["new_job", str(bulk), "--products", "41", "--profile", "fixture", "--shop-name",
                      "fixture", "--vender-id", "1", "--main-selection", "per-link", "--approved-sample", str(sample)])
        with patch.object(common, "connect", return_value=cli), patch.object(common, "verify_identity", return_value=shop), \
                patch.object(common, "apply_detail", return_value=before):
            build_plan.main(["build_plan", str(bulk)])
        (bulk / "sources" / source_file).write_bytes(reference)
        with patch.object(common, "resolve_api_key", side_effect=AssertionError("unnecessary gateway request")):
            generate.main(["generate", str(bulk)])
        reused = common.load_json(bulk / "internal-generation.json")[keys[0]]
        assert reused["attempts"] == 0 and reused["outputSha256"] == old_hash

        original = b"synthetic PNG payload used by the fixture transport"
        (run / "generated").mkdir()
        (run / "generated" / (keys[0] + ".png")).write_bytes(original)
        common.save_json(run / "uploads.json", {})
        common.save_json(run / "internal-generation.json", {keys[0]: {"status": "succeeded"},
                                                            keys[1]: {"status": "rejected"}})
        cli.upload.side_effect = TimeoutError("lost accepted upload receipt")
        with patch.object(common, "connect", return_value=cli), patch.object(common, "verify_identity"), \
                patch.object(upload, "media_space", return_value=("zone", 6)):
            expect_failure(upload.main, ["upload.py", str(run)])
            old = common.load_json(run / "uploads.json")[keys[0]]
            assert old["status"] == "unknown" and cli.upload.call_count == 1
            cli.get.return_value = {"data": [{"imgId": "1", "imgName": old["platformName"], "imgSize": len(original),
                                              "categoryId": 6, "imgUrl": "jfs/test/received"}]}
            module = sys.modules[upload.reconcile_image.__module__]
            with patch.object(module, "matching_original", return_value=True):
                upload.main(["upload.py", str(run), "--reconcile-uploads"])
            recovered = common.load_json(run / "uploads.json")[keys[0]]
            assert recovered["reconciled"] and recovered["uploadSha256"] == sha256(original).hexdigest()
            assert cli.upload.call_count == 1


class SharedRefreshEntry(unittest.TestCase):
    def test_cli_scope_and_unfinished_receipt(self):
        subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).with_name("pop_refresh_cli_contract.py"))],
                       check=True)

    def test_normal_refresh_entry(self):
        root = Path(__file__).resolve().parents[1]
        scripts = root / "mature/refresh/scripts" if (root / "mature/refresh").is_dir() else root / "scripts"
        subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), str(scripts), str(root)],
                       check=True)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        sys.path.insert(0, sys.argv[2])
        contract(Path(sys.argv[1]))
    else:
        unittest.main()
