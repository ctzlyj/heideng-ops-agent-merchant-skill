"""Upload generated images to the shop material centre.

usage: python upload.py <run_dir> [productId ...]

Each upload records the returned imgUrl plus the local sha256, so a rerun
skips finished keys and the PATCH step never guesses which file went up.
"""

import sys
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
from heideng_merchant.safety import atomic_json, file_sha
from heideng_merchant.sku_image_edit import media_space
from heideng_merchant.state import FileLock

LIMIT = 3 * 1024 * 1024


def prepare_file(path: Path) -> Path:
    if path.stat().st_size <= LIMIT:
        return path
    converted = path.with_suffix(".upload.jpg")
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
    replace_changed = "--replace-changed-images" in argv[2:]
    keys = list(common.plan_tasks(plan, [arg for arg in argv[2:] if arg != "--replace-changed-images"]))
    if not keys:
        raise SystemExit("no planned images for the requested products")
    generated = common.load_json(run / "internal-generation.json") or {}
    ledger_path = run / "uploads.json"

    cli = common.connect(job)
    common.verify_identity(cli, job, run)

    zone_id, category_id = media_space(cli)

    pending = [key for key in keys if (generated.get(key) or {}).get("status") == "succeeded"]
    print("images to check:", len(pending), flush=True)

    def upload_one(key):
        source = run / "generated" / (key + ".png")
        if not source.is_file():
            original = (common.load_json(ledger_path) or {}).get(key) or {}
            if original.get("status") == "succeeded" and original.get("imgUrl"):
                print("reused original upload receipt (source archived):", key, flush=True)
                return original
        source_hash = file_sha(source)
        with tempfile.TemporaryDirectory(prefix="gallery-upload-") as temporary:
            staged = Path(temporary) / (source_hash + source.suffix)
            shutil.copyfile(source, staged)
            if file_sha(staged) != source_hash:
                raise RuntimeError("准备上传时成图已改变：" + key)
            upload_path = prepare_file(staged)
            intent = {"status": "uploading", "sha256": source_hash, "uploadSha256": file_sha(upload_path),
                      "name": upload_path.name, "zoneId": zone_id, "categoryId": category_id}
            with FileLock(run / "uploads.lock"):
                records = common.load_json(ledger_path) or {}
                previous = records.get(key)
                if previous:
                    if previous.get("status") != "succeeded" or not previous.get("imgUrl"):
                        raise RuntimeError("原素材上传回执尚需核对，请按图片键查询本店图片空间：" + key)
                    prior_hash = previous.get("uploadSha256")
                    # Older receipts only hash the source. For an unconverted file this also hashes the bytes sent.
                    if not prior_hash and staged == upload_path:
                        prior_hash = previous.get("sha256")
                    if previous.get("sha256") == source_hash and prior_hash == intent["uploadSha256"]:
                        return previous
                    if not replace_changed:
                        raise RuntimeError("成图或实际上传文件与原成功回执不同。核对本次修订后可传 --replace-changed-images：" + key)
                    intent["previous"] = [*previous.get("previous", []),
                                          {k: v for k, v in previous.items() if k != "previous"}]
                records[key] = intent
                atomic_json(ledger_path, records)
            try:
                result = cli.upload(zone_id, category_id, upload_path)
                img_url = str(result.get("imgUrl") or (result.get("data") or {}).get("imgUrl") or "")
                if not img_url:
                    raise RuntimeError("empty imgUrl")
                outcome = {**intent, "status": "succeeded", "imgUrl": common.clean_url(img_url)}
            except Exception as exc:
                outcome = {**intent, "status": "unknown", "error": str(exc)[:300]}
        with FileLock(run / "uploads.lock"):
            records = common.load_json(ledger_path) or {}
            records[key] = outcome
            atomic_json(ledger_path, records)
        return outcome

    workers = int(job.get("uploadConcurrency") or 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(upload_one, key): key for key in pending}
        for index, future in enumerate(as_completed(futures), 1):
            key = futures[future]
            record = future.result()
            if index % 20 == 0 or record["status"] != "succeeded":
                print("upload %d/%d %s %s" % (index, len(pending), key, record["status"]), flush=True)

    ledger = common.load_json(ledger_path) or {}
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
