"""Upload generated images to the shop material centre.

usage: python upload.py <run_dir> [productId ...]

Each upload records the returned imgUrl plus the local sha256, so a rerun
skips finished keys and the PATCH step never guesses which file went up.
"""

import sys
from hashlib import sha256
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
from refresh_runtime import (atomic_json, FileLock, UploadImage, platform_image_name, reconcile_image, media_space, refresh_selection)
same_shop, verify_frozen = refresh_selection.same_shop, refresh_selection.verify_frozen

LIMIT = 3 * 1024 * 1024


def prepare_image(source):
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    if len(raw) <= LIMIT:
        return digest, UploadImage(digest + source.suffix, raw)
    with Image.open(io.BytesIO(raw)) as original:
        image = original.convert("RGB")
        for quality in (90, 80):
            converted = io.BytesIO()
            image.save(converted, "JPEG", quality=quality)
            if converted.tell() <= LIMIT:
                return digest, UploadImage(digest + ".upload.jpg", converted.getvalue())
    raise RuntimeError("still >3MB after re-encode: %s" % source)


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: upload.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    verify_frozen(job, plan, run)
    replace_changed = "--replace-changed-images" in argv[2:]
    check_only = "--reconcile-uploads" in argv[2:]
    keys = list(common.plan_tasks(plan, [arg for arg in argv[2:] if arg not in ("--replace-changed-images", "--reconcile-uploads")]))
    if not keys:
        raise SystemExit("no planned images for the requested products")
    generated = common.load_json(run / "internal-generation.json") or {}
    ledger_path = run / "uploads.json"

    cli = common.connect(job)
    shop = {k: str(job[k]) for k in ("profile", "venderId", "shopName", "shopId") if job.get(k)}
    former = common.load_json(run / "identity.json")
    if former:
        same_shop(shop, former)
    common.verify_identity(cli, job, run)

    zone_id, category_id = media_space(cli)

    pending = [key for key in keys if (generated.get(key) or {}).get("status") == "succeeded"]
    print("images to check:", len(pending), flush=True)

    def upload_one(key):
        source = run / "generated" / (key + ".png")
        if not source.is_file():
            original = (common.load_json(ledger_path) or {}).get(key) or {}
            if original.get("status") == "succeeded" and original.get("imgUrl"):
                if original.get("shopIdentity") and original["shopIdentity"] != shop:
                    raise ValueError("原素材上传回执店铺不同：" + key)
                print("reused original upload receipt (source archived):", key, flush=True)
                return original
        source_hash, image = prepare_image(source)
        intent = {"status": "uploading", "sha256": source_hash, "uploadSha256": sha256(image.read_bytes()).hexdigest(),
                  "name": image.name, "platformName": platform_image_name(image.name), "uploadBytes": len(image.read_bytes()),
                  "shopIdentity": shop, "zoneId": zone_id, "categoryId": category_id}
        with FileLock(run / "uploads.lock"):
            records = common.load_json(ledger_path) or {}
            previous = records.get(key)
            unresolved = previous and (previous.get("status") != "succeeded" or not previous.get("imgUrl"))
            if previous and not unresolved:
                if previous.get("shopIdentity") and previous["shopIdentity"] != shop:
                    raise ValueError("原素材上传回执店铺不同：" + key)
                prior_hash = previous.get("uploadSha256")
                if not prior_hash and intent["uploadSha256"] == source_hash:
                    prior_hash = previous.get("sha256")
                if previous.get("sha256") == source_hash and prior_hash == intent["uploadSha256"]:
                    return previous
                if not replace_changed:
                    raise RuntimeError("成图或实际上传文件与原成功回执不同。核对本次修订后可传 --replace-changed-images：" + key)
                intent["previous"] = [*previous.get("previous", []), {k: v for k, v in previous.items() if k != "previous"}]
            if not unresolved:
                if check_only:
                    return previous or {"status": "not-submitted"}
                records[key] = intent
                atomic_json(ledger_path, records)
        if unresolved:
            outcome = reconcile_image(cli, previous, intent, shop)
            if not outcome:
                raise RuntimeError("原素材上传回执尚需核对，图片空间未能唯一证实实际上传内容：" + key)
        else:
            try:
                result = cli.upload(zone_id, category_id, image)
                detail = result.get("data") or result
                img_url = str(detail.get("imgUrl") or "")
                if not img_url:
                    raise RuntimeError("empty imgUrl")
                outcome = {**intent, "status": "succeeded", "imgUrl": common.clean_url(img_url), "imgId": detail.get("imgId")}
            except Exception as exc:
                outcome = {**intent, "status": "unknown", "error": str(exc)[:300]}
        with FileLock(run / "uploads.lock"):
            records = common.load_json(ledger_path) or {}
            # A parallel worker may have already reconciled the original dispatch.
            if records.get(key) != (previous if unresolved else intent):
                return records.get(key, {"status": "unknown"})
            records[key] = outcome
            atomic_json(ledger_path, records)
        return outcome

    workers = int(job.get("uploadConcurrency") or 4)
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(upload_one, key): key for key in pending}
        for index, future in enumerate(as_completed(futures), 1):
            key = futures[future]
            try:
                record = future.result()
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append(exc)
                print("upload", key, str(exc)[:220], flush=True)
                continue
            if index % 20 == 0 or record["status"] != "succeeded":
                print("upload %d/%d %s %s" % (index, len(pending), key, record["status"]), flush=True)

    ledger = common.load_json(ledger_path) or {}
    # Images refused by content moderation never reach upload; they keep the
    # original picture, so they must not make this step look unfinished.
    expected = [key for key in keys
                if (generated.get(key) or {}).get("status") != "rejected"]
    ok = sum(1 for key in expected if (ledger.get(key) or {}).get("status") == "succeeded")
    failed = [key for key in expected if (ledger.get(key) or {}).get("status") == "failed"]
    missing = [key for key in expected if (ledger.get(key) or {}).get("status") != "succeeded"]
    skipped = len(keys) - len(expected)
    print("done: uploaded=%d expected=%d rejected-skipped=%d failed=%d total=%d"
          % (ok, len(expected), skipped, len(failed), len(keys)), flush=True)
    if missing:
        print("incomplete keys:", missing[:10])
        if errors:
            raise errors[0]
        raise SystemExit(1)
    if errors:
        raise errors[0]


if __name__ == "__main__":
    main(sys.argv)
