"""Independent final verification for main images and detail pages.

usage: python verify.py <run_dir> [productId ...]

Nothing here trusts a PATCH response: every product is re-read from the live
platform. Main images keep group/slot counts, planned images must be replaced,
only allowed old images may remain, SKU prices and status must not move.
Detail pages keep their image count and markup, and only planned src values
may change.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common
import detail_patch_update as detail_patch
from heideng_merchant.gallery_patch import gallery_readback, snapshot


def evaluate_product(
    before, after, plan_product, plan, patches, uploads, before_status, list_status, generation=None
):
    """Per-product main-image decision function."""
    problems = []
    pid = int(plan_product["productId"])
    before_groups = common.main_groups(before)
    after_groups = common.main_groups(after)
    after_urls = [url for urls in after_groups.values() for url in urls]
    retained_keys = set((patches.get(str(pid)) or {}).get("missingKeys") or [])
    mapping = {}
    for item in plan_product["positions"]:
        if item["key"] in retained_keys:
            if ((generation or {}).get(item["key"]) or {}).get("status") != "rejected":
                problems.append("待核对的图片缺少成功上传回执：" + item["key"])
            continue
        receipt = uploads.get(item["key"]) or {}
        if receipt.get("status") != "succeeded" or not receipt.get("imgUrl"):
            problems.append("missing accepted upload: " + item["key"])
            continue
        mapping[item["url"]] = common.clean_url(receipt["imgUrl"])
    capped = {(str(item["group"]), int(item["position"])) for item in plan.get("capped") or []
              if int(item["productId"]) == pid}
    position_filter = set(plan.get("positionFilter") or [])
    selected = None
    if "selectedSlots" in plan_product:
        selected = {}
        for slot in plan_product["selectedSlots"]:
            gid, pos = str(slot["group"]), int(slot["position"])
            urls = before_groups.get(gid, [])
            if ((gid, pos) in selected or not 1 <= pos <= min(9, len(urls))
                    or urls[pos - 1] != common.clean_url(slot["url"])):
                problems.append(f"冻结图位与批准的原图不符：{gid}/{pos}")
            selected[gid, pos] = common.clean_url(slot["url"])
    new_count = 0
    expected_groups = {}
    for gid, urls in before_groups.items():
        actual = after_groups.get(gid) or []
        expected_groups[gid] = []
        for index, old in enumerate(urls, 1):
            allowed = index <= 9 and (not position_filter or index in position_filter) and (gid, index) not in capped
            if selected is not None:
                allowed = allowed and selected.get((gid, index)) == old
            expected = mapping.get(old, old) if allowed else old
            expected_groups[gid].append(expected)
            if index <= len(actual) and actual[index - 1] == expected and expected != old:
                new_count += 1
    before_state, after_state = snapshot(before, pid), snapshot(after, pid)
    before_state["groups"], after_state["groups"] = expected_groups, after_groups
    evidence = gallery_readback(before_state, after_state)
    problems.extend(evidence["problems"])

    if (after.get("material") or {}).get("rectangleImages") != (before.get("material") or {}).get("rectangleImages"):
        problems.append("rectangle images changed")

    after_status = common.status_int((after.get("productInfo") or {}).get("productStatus"))
    raw_status = list_status if list_status is not None else after_status
    planned_status = plan_product.get("listStatus")
    if planned_status is not None and (list_status is None or int(planned_status) != int(list_status)):
        problems.append("list status changed %s -> %s" % (planned_status, list_status))

    return {
        **evidence,
        "ok": not problems,
        "problems": problems,
        "groupCount": len(after_groups),
        "images": len(after_urls),
        "newImages": new_count,
        "oldKept": len(after_urls) - new_count,
        "retainedKeys": sorted(retained_keys),
        "pricesUnchanged": not ({"skuId", "price"} & evidence["fieldDifferences"].keys()),
        "consumerPageStatus": "unchecked",
        "verifiedAssets": {
            item["key"]: {"imgUrl": common.clean_url(uploads[item["key"]]["imgUrl"]),
                          "sha256": uploads[item["key"]].get("sha256")}
            for item in plan_product["positions"] if not problems and item["key"] not in retained_keys
        },
        "status": int(raw_status or 0),
        "applyStatus": int(after_status or 0),
        "applyStatusBefore": int(before_status or 0),
        "title": plan_product["title"],
    }


def detail_url_map(detail_images, uploads):
    url_map, missing = {}, []
    for image in detail_images or []:
        record = uploads.get(image["key"]) or {}
        if record.get("status") == "succeeded":
            url_map[image["currentUrl"]] = common.clean_url(record["imgUrl"])
        else:
            missing.append(image["key"])
    return url_map, missing


def evaluate_detail(before, after, detail_images, uploads):
    """Per-product detail-page decision function."""
    url_map, missing = detail_url_map(detail_images, uploads)
    problems = detail_patch.verify_detail_patch(before, after, url_map)
    before_urls = common.detail_src_urls(common.detail_htmls(before).get("desc", ""))
    after_urls = [common.clean_url(url) for url in
                  common.detail_src_urls(common.detail_htmls(after).get("desc", ""))]
    new_values = set(url_map.values())
    return {
        "ok": not problems,
        "problems": problems,
        "images": len(before_urls),
        "newImages": sum(1 for url in after_urls if url in new_values),
        "missingKeys": missing,
    }


def list_status_map(cli):
    result = {}
    page = 1
    while True:
        response = cli.get(
            "jdo-product-status",
            "/rest/sp-product/v0/products",
            {
                "scopeSet": "productId,productStatus",
                "page": page,
                "pageSize": 50,
                "sortBy": "created",
                "sortType": "desc",
            },
        )
        rows = response.get("data") or []
        for row in rows:
            result[int(row["productId"])] = row.get("productStatus")
        total = int((response.get("paginationData") or {}).get("totalItems") or 0)
        if not rows or len(result) >= total:
            break
        page += 1
    return result


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: verify.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    scopes = plan.get("scopes") or ["main"]
    uploads = common.load_json(run / "uploads.json") or {}
    patches = common.load_json(run / "patch-results.json") or {}
    generation = common.load_json(run / "internal-generation.json") or {}
    selected = common.plan_products(plan, argv[2:])

    cli = common.connect(job)
    common.verify_identity(cli, job, run)
    statuses = list_status_map(cli)
    print("listed products:", len(statuses), "scope:", "+".join(scopes), flush=True)

    def fetch(pid):
        return pid, common.apply_detail(cli, pid)

    after_details = {}
    read_errors = {}
    workers = int(job.get("fetchConcurrency") or 6)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch, int(product["productId"])): product for product in selected
        }
        for index, future in enumerate(as_completed(futures), 1):
            try:
                pid, detail = future.result()
                after_details[pid] = detail
            except Exception as exc:
                read_errors[int(futures[future]["productId"])] = str(exc)[:300]
            if index % 25 == 0 or index == len(selected):
                print("readback %d/%d" % (index, len(selected)), flush=True)

    report = {}
    for product in selected:
        pid = int(product["productId"])
        before = common.load_json(run / "products" / str(pid) / "before-apply.json")
        if not before or pid in read_errors:
            report[str(pid)] = {"title": product["title"], "ok": False, "consumerPageStatus": "unchecked",
                                "problems": [read_errors.get(pid) or "missing before-apply.json"]}
            continue
        after = after_details[pid]
        before_status = common.status_int((before.get("productInfo") or {}).get("productStatus"))
        entry = {"title": product["title"]}
        problems = []

        if product.get("positions"):
            try:
                main_entry = evaluate_product(
                    before, after, product, plan, patches, uploads, before_status, statuses.get(pid), generation
                )
            except (ValueError, KeyError, TypeError) as exc:
                main_entry = {"ok": False, "consumerPageStatus": "unchecked", "problems": [str(exc)[:300]]}
            entry.update(main_entry)
            problems.extend(main_entry["problems"])
        else:
            entry.update(
                {
                    "groupCount": len(common.main_groups(after)),
                    "images": sum(len(urls) for urls in common.main_groups(after).values()),
                    "newImages": 0,
                    "oldKept": sum(len(urls) for urls in common.main_groups(after).values()),
                    "pricesUnchanged": True,
                    "status": int(statuses.get(pid) or 0),
                    "applyStatus": common.status_int(
                        (after.get("productInfo") or {}).get("productStatus")
                    ),
                }
            )
            if common.main_groups(before) != common.main_groups(after):
                problems.append("main images changed while out of scope")

        detail_images = product.get("detailImages") or []
        if "detail" in scopes and detail_images:
            detail_entry = evaluate_detail(before, after, detail_images, uploads)
            entry["detailImages"] = detail_entry["images"]
            entry["detailNewImages"] = detail_entry["newImages"]
            entry["detailMissingKeys"] = detail_entry["missingKeys"]
            entry["detailProblems"] = detail_entry["problems"]
            problems.extend(detail_entry["problems"])
        elif "detail" in scopes and not detail_images:
            entry["detailImages"] = 0
            entry["detailNewImages"] = 0
            if (before.get("productInfo") or {}).get("productDetailDesc"):
                problems.append("detail scope requested but nothing planned")

        entry["problems"] = problems
        entry["ok"] = not problems
        report[str(pid)] = entry
        print(
            pid,
            "OK" if entry["ok"] else "FAIL",
            "groups=%d images=%d new=%d detail=%s/%s status=%s %s"
            % (
                entry.get("groupCount", 0),
                entry.get("images", 0),
                entry.get("newImages", 0),
                entry.get("detailNewImages", "-"),
                entry.get("detailImages", "-"),
                entry.get("status", 0),
                "; ".join(problems),
            ),
            flush=True,
        )

    output = run / "final-verification.json"
    previous = common.load_json(output) or {}
    common.save_json(output, {**previous, **report})
    ok = sum(1 for entry in report.values() if entry["ok"])
    print("final: ok=%d of %d" % (ok, len(report)), flush=True)
    if ok < len(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
