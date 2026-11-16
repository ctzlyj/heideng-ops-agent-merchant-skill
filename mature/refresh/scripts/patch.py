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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
import image_patch_update as image_patch

LOCK = threading.RLock()


def position_index(value):
    return int(str(value).replace("pos", "").replace("front", "1"))


def already_current(detail, url_map):
    live = {url for urls in common.main_groups(detail).values() for url in urls}
    remaining = set(url_map) & live
    applied = set(url_map.values()) & live
    return not remaining and bool(applied)


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: patch.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    uploads = common.load_json(run / "uploads.json") or {}
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")

    cli = common.connect(job)
    common.verify_identity(cli, job, run)

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
        if (results.get(str(pid)) or {}).get("ok"):
            return pid, results[str(pid)]
        url_map, missing, capped = {}, [], 0
        for position in product["positions"]:
            if position_index(position["position"]) > max_position:
                capped += 1
                continue
            record = uploads.get(position["key"]) or {}
            if record.get("status") == "succeeded":
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

        last_error = None
        for attempt in range(4):
            try:
                before = common.apply_detail(cli, pid)
                if already_current(before, url_map):
                    return pid, {
                        "ok": True,
                        "problems": [],
                        "replaced": len(url_map),
                        "missingKeys": missing,
                        "cappedPositions": capped,
                        "reconciled": True,
                    }
                body, summary = image_patch.build_image_patch_payload(before, url_map)
                if set(summary["mapping"]) != set(url_map):
                    raise RuntimeError("planned images not fully replaced")
                body_path = bodies / ("patch_%d.json" % pid)
                body_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
                cli.run_jdo_large(
                    url="/rest/sp-product/v0/product-applies/{applyId}",
                    method="PATCH",
                    body_path=body_path,
                    params={"applyId": str(pid)},
                    skill_id="jdo-product-update",
                    yes=True,
                )
                time.sleep(8)
                after = common.apply_detail(cli, pid)
                problems = image_patch.verify_patch(before, after, summary["mapping"])
                expected_groups = {
                    gid: [url_map.get(url, url) for url in urls]
                    for gid, urls in common.main_groups(before).items()
                }
                after_groups = common.main_groups(after)
                for gid, expected in expected_groups.items():
                    if after_groups.get(gid) != expected:
                        problems.append("group %s not fully new" % gid)
                before_prices = {
                    str(sku["skuId"]): (sku.get("priceInfo") or {}).get("jdPrice")
                    for sku in before.get("skuList") or []
                }
                after_prices = {
                    str(sku["skuId"]): (sku.get("priceInfo") or {}).get("jdPrice")
                    for sku in after.get("skuList") or []
                }
                if before_prices != after_prices:
                    problems.append("sku prices changed")
                return pid, {
                    "ok": not problems,
                    "problems": problems,
                    "replaced": len(summary["mapping"]),
                    "missingKeys": missing,
                    "cappedPositions": capped,
                }
            except Exception as exc:  # noqa: BLE001 - retry after reconcile
                last_error = exc
                time.sleep(15 + attempt * 15)
        return pid, {"ok": False, "error": str(last_error)[:300], "missingKeys": missing}

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
