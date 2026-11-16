"""Rewrite detail-page images in place (gated write).

usage:
  python patch_detail.py <run_dir> [--write --confirm DETAIL_PATCH] [productId ...]

Without --write the script only builds and prints patch bodies (dry run).
A real write additionally requires job.json "detailWrite": true; the gate
exists because the detail-page PATCH path has not yet been live-piloted on a
shop, while the main-image PATCH path has three verified runs.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
import detail_patch_update as detail_patch

CONFIRM_WORD = "DETAIL_PATCH"


def split_args(argv):
    write = "--write" in argv
    confirm = None
    rest = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--write":
            index += 1
            continue
        if item == "--confirm":
            confirm = argv[index + 1] if index + 1 < len(argv) else ""
            index += 2
            continue
        rest.append(item)
        index += 1
    return write, confirm, rest


def detail_url_map(product, uploads):
    url_map, missing = {}, []
    for image in product.get("detailImages") or []:
        record = uploads.get(image["key"]) or {}
        if record.get("status") == "succeeded":
            url_map[image["currentUrl"]] = common.clean_url(record["imgUrl"])
        else:
            missing.append(image["key"])
    return url_map, missing


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: patch_detail.py <run_dir> [--write --confirm DETAIL_PATCH] [productId ...]")
    write, confirm, rest = split_args(argv[1:])
    run = Path(rest[0]).resolve()
    pids = rest[1:]
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    uploads = common.load_json(run / "uploads.json") or {}
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    if "detail" not in (plan.get("scopes") or []):
        raise SystemExit("plan has no detail scope; rebuild with --scope both")
    if write:
        if str(confirm or "") != CONFIRM_WORD:
            raise SystemExit("refusing to write: pass --confirm %s" % CONFIRM_WORD)
        if not job.get("detailWrite"):
            raise SystemExit("refusing to write: set detailWrite=true in job.json after a pilot")

    selected = [
        product
        for product in common.plan_products(plan, pids)
        if product.get("detailImages")
    ]
    if not selected:
        raise SystemExit("no detail images planned for the requested products")

    results_path = run / "detail-patch-results.json"
    results = common.load_json(results_path) or {}
    bodies = run / "patch-bodies"
    bodies.mkdir(exist_ok=True)
    cli = common.connect(job)
    common.verify_identity(cli, job, run)

    for product in selected:
        pid = int(product["productId"])
        url_map, missing = detail_url_map(product, uploads)
        if not url_map:
            results[str(pid)] = {"ok": False, "reason": "no uploaded detail images", "missingKeys": missing}
            common.save_json(results_path, results)
            print(pid, "skipped: no uploads", flush=True)
            continue
        live = common.apply_detail(cli, pid)
        body, summary = detail_patch.build_detail_patch_payload(live, url_map)
        body_path = bodies / ("patch_detail_%d.json" % pid)
        body_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        print(pid, "planned images", len(url_map), "replaced per field",
              summary["replacedPerField"], "body", body_path.name, flush=True)
        if not write:
            results[str(pid)] = {
                "ok": False,
                "dryRun": True,
                "plannedImages": len(url_map),
                "missingKeys": missing,
                "body": body_path.name,
            }
            common.save_json(results_path, results)
            continue

        problems = None
        last_error = None
        for attempt in range(3):
            try:
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
                problems = detail_patch.verify_detail_patch(live, after, url_map)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(15 + attempt * 15)
        if problems is None:
            results[str(pid)] = {
                "ok": False,
                "error": str(last_error)[:300],
                "missingKeys": missing,
            }
        else:
            results[str(pid)] = {
                "ok": not problems,
                "problems": problems,
                "replaced": len(url_map),
                "missingKeys": missing,
                "replacedPerField": summary["replacedPerField"],
            }
        common.save_json(results_path, results)
        print(pid, "ok" if results[str(pid)]["ok"] else "FAILED",
              "; ".join(results[str(pid)].get("problems") or []), flush=True)

    common.save_json(results_path, results)
    if not write:
        print("dry run only: nothing written. Review patch-bodies/*.json, then rerun with --write --confirm %s"
              % CONFIRM_WORD, flush=True)
        return
    ok = sum(1 for product in selected if (results.get(str(product["productId"])) or {}).get("ok"))
    print("done: detail products ok=%d of %d" % (ok, len(selected)), flush=True)
    if ok < len(selected):
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
