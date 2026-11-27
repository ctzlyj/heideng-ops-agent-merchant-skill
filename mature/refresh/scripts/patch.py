"""Replace main images in place with the image-only PATCH endpoint.

usage: python patch.py <run_dir> [productId ...]

Groups and slot order come from the live apply body, so colour bindings are
preserved and only imgUrl values change. Before every attempt the live body is
re-read: when the planned mapping is already online the product is marked
reconciled instead of being PATCHed again. Products run in parallel.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
from refresh_runtime import frozen_patch, file_sha, refresh_selection
verify_frozen = refresh_selection.verify_frozen

LOCK = threading.RLock()


def position_index(value):
    return int(str(value).replace("pos", "").replace("front", "1"))


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: patch.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    uploads = common.load_json(run / "uploads.json") or {}
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    verify_frozen(job, plan, run)

    cli = common.connect(job)
    identity = common.verify_identity(cli, job, run)

    results_path = run / "patch-results.json"
    results = common.load_json(results_path) or {}
    bodies = run / "patch-bodies"
    bodies.mkdir(exist_ok=True)
    scopes = plan.get("scopes") or ["main"]
    selected = [item for item in common.plan_products(plan, argv[2:]) if item.get("positions")]
    if "main" not in scopes:
        print("plan scope has no main images; use patch_detail.py for detail pages", flush=True)
        return
    if not selected:
        print("no main-image work for the requested products", flush=True)
        return
    max_position = int(job.get("maxPosition") or common.DEFAULT_MAX_POSITION)

    def patch_one(product):
        pid = int(product["productId"])
        url_map, missing, capped = {}, [], 0
        for position in product["positions"]:
            if position_index(position["position"]) > max_position:
                capped += 1
                continue
            record = uploads.get(position["key"]) or {}
            if record.get("status") == "succeeded":
                local = run / "generated" / (position["key"] + ".png")
                if local.is_file() and file_sha(local) != record.get("sha256"):
                    raise ValueError("本地成图已变更，请先核验本次修订的实际上传回执：" + position["key"])
                url_map[position["url"]] = common.clean_url(record["imgUrl"])
            else:
                missing.append(position["key"])
        if not url_map:
            gen = common.load_json(run / "internal-generation.json") or {}
            all_rejected = missing and all(
                (gen.get(key) or {}).get("status") == "rejected" for key in missing
            )
            if all_rejected:
                # Nothing left to patch: every planned image was refused by the
                # model, so the product keeps its original images by design.
                return pid, {
                    "ok": True,
                    "skipped": "moderation_rejected",
                    "replaced": 0,
                    "missingKeys": missing,
                    "cappedPositions": capped,
                }
            return pid, {"ok": False, "reason": "no uploaded images", "missingKeys": missing}

        baseline = common.load_json(run / "products" / str(pid) / "before-apply.json")
        if not baseline:
            raise ValueError("缺少原任务冻结的图组快照，无法定位上传素材对应的图位")
        slots = None
        if "selectedSlots" in product:
            slots = [slot for slot in product["selectedSlots"] if slot["key"] not in missing]
        record = frozen_patch(cli, lambda product_id: common.apply_detail(cli, product_id),
                              identity, pid, baseline, url_map, plan.get("positionFilter") or [],
                              max_position, bodies, common.clean_url, selected_slots=slots)
        return pid, {**record, "missingKeys": missing, "cappedPositions": capped}

    workers = int(job.get("patchConcurrency") or 3)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(patch_one, product): product for product in selected}
        for index, future in enumerate(as_completed(futures), 1):
            product = futures[future]
            try:
                pid, record = future.result()
            except Exception as exc:  # noqa: BLE001
                pid = int(product["productId"])
                record = {"ok": False, "error": str(exc)[:300]}
            with LOCK:
                results[str(pid)] = record
                common.save_json(results_path, results)
            status = "ok" if record.get("ok") else "FAILED"
            if record.get("skipped"):
                status = "skipped(%s)" % record["skipped"]
            print("%d/%d %s %s replaced=%s %s" % (
                index, len(selected), pid, status, record.get("replaced"),
                "; ".join(record.get("problems") or []) or record.get("error", "")), flush=True)

    common.save_json(results_path, results)
    ok = sum(1 for product in selected if (results.get(str(product["productId"])) or {}).get("ok"))
    skipped = sum(1 for product in selected
                  if (results.get(str(product["productId"])) or {}).get("skipped"))
    print("done: products ok=%d of %d" % (ok, len(selected)), flush=True)
    if skipped:
        print("of which skipped (all planned images rejected, kept original): %d" % skipped,
              flush=True)
    if ok < len(selected):
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
