"""Upload generated images to the shop material centre.

usage: python upload.py <run_dir> [productId ...]

Each upload records the returned imgUrl plus the local sha256, so a rerun
skips finished keys and the PATCH step never guesses which file went up.
"""

import hashlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common

LIMIT = 3 * 1024 * 1024
LOCK = threading.RLock()


def prepare_file(path: Path) -> Path:
    if path.stat().st_size <= LIMIT:
        return path
    converted = path.with_suffix(".upload.jpg")
    if not converted.exists():
        with Image.open(path) as image:
            image.convert("RGB").save(converted, "JPEG", quality=90)
    if converted.stat().st_size > LIMIT:
        with Image.open(path) as image:
            image.convert("RGB").save(converted, "JPEG", quality=80)
    if converted.stat().st_size > LIMIT:
        raise RuntimeError("still >3MB after re-encode: %s" % path)
    return converted


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: upload.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    keys = list(common.plan_tasks(plan, argv[2:]))
    if not keys:
        raise SystemExit("no planned images for the requested products")
    generated = common.load_json(run / "internal-generation.json") or {}
    ledger_path = run / "uploads.json"
    ledger = common.load_json(ledger_path) or {}

    cli = common.connect(job)
    common.verify_identity(cli, job, run)

    zones = cli.get("jdo-product-material", "/rest/sp-product/v0/media-zones").get("data") or []
    image_zone = next(zone for zone in zones if zone.get("zoneType") == 1)
    categories = cli.get(
        "jdo-product-material",
        "/rest/sp-product/v0/media-zones/{zoneId}/categories",
        {"zoneId": image_zone["zoneId"], "page": 1, "pageSize": 100},
    ).get("data") or []
    category = next(
        (item for item in categories if item.get("categoryName") == "我的本地文件"),
        next(item for item in categories if item.get("status") == 1),
    )
    zone_id = str(image_zone["zoneId"])
    category_id = int(category["categoryId"])
    print("zone:", zone_id, "category:", category.get("categoryName"), flush=True)

    pending = [
        key
        for key in keys
        if (generated.get(key) or {}).get("status") == "succeeded"
        and (ledger.get(key) or {}).get("status") != "succeeded"
    ]
    print("pending uploads:", len(pending), flush=True)

    def upload_one(key):
        source = run / "generated" / (key + ".png")
        last_error = None
        for attempt in range(4):
            try:
                upload_path = prepare_file(source)
                result = cli.upload(zone_id, category_id, upload_path)
                img_url = str(
                    result.get("imgUrl") or (result.get("data") or {}).get("imgUrl") or ""
                )
                if not img_url:
                    raise RuntimeError("empty imgUrl")
                return {
                    "status": "succeeded",
                    "imgUrl": common.clean_url(img_url),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "attempts": attempt + 1,
                }
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(5 + attempt * 5)
        return {"status": "failed", "error": str(last_error)[:300], "attempts": 4}

    workers = int(job.get("uploadConcurrency") or 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(upload_one, key): key for key in pending}
        for index, future in enumerate(as_completed(futures), 1):
            key = futures[future]
            record = future.result()
            with LOCK:
                ledger[key] = record
                common.save_json(ledger_path, ledger)
            if index % 20 == 0 or record["status"] != "succeeded":
                print("upload %d/%d %s %s" % (index, len(pending), key, record["status"]), flush=True)

    common.save_json(ledger_path, ledger)
    # Images refused by content moderation never reach upload; they keep the
    # original picture, so they must not make this step look unfinished.
    expected = [key for key in keys
                if (generated.get(key) or {}).get("status") == "succeeded"]
    ok = sum(1 for key in expected if (ledger.get(key) or {}).get("status") == "succeeded")
    failed = [key for key in expected if (ledger.get(key) or {}).get("status") == "failed"]
    missing = [key for key in expected if (ledger.get(key) or {}).get("status") != "succeeded"]
    skipped = len(keys) - len(expected)
    print("done: uploaded=%d expected=%d rejected-skipped=%d failed=%d total=%d"
          % (ok, len(expected), skipped, len(failed), len(keys)), flush=True)
    if missing:
        print("incomplete keys:", missing[:10])
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
