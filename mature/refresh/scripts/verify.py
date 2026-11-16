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


def capped_urls(plan, pid):
    result = set()
    for item in plan.get("capped") or []:
        if int(item["productId"]) == int(pid):
            result.add(item["url"])
    return result


def evaluate_product(
    before, after, plan_product, plan, patches, new_urls, before_status, list_status
):
    """Per-product main-image decision function."""
    problems = []
    pid = int(plan_product["productId"])
    before_groups = common.main_groups(before)
    after_groups = common.main_groups(after)
    if len(before_groups) != len(after_groups):
        problems.append("group count %d -> %d" % (len(before_groups), len(after_groups)))
    before_slots = sum(len(urls) for urls in before_groups.values())
    after_urls = [url for urls in after_groups.values() for url in urls]
    if before_slots != len(after_urls):
        problems.append("slot count %d -> %d" % (before_slots, len(after_urls)))
    if len(before_groups) != len(after_groups) or before_slots != len(after_urls):
        problems.append(
            "外部改动：改前快照与线上不一致，先确认是否有同事在改这条商品；"
            "确认后运行 python scripts\\repair_one.py <run> %d 重建该商品再单独 patch/verify" % pid
        )

    retained_keys = set((patches.get(str(pid)) or {}).get("missingKeys") or [])
    allowed_old = capped_urls(plan, pid)
    for key in retained_keys:
        allowed_old.add(plan["tasks"][key]["currentUrl"])
    position_filter = set(plan.get("positionFilter") or [])
    if position_filter:
        # Positions outside the requested filter must stay exactly as they were.
        for group_id, urls in before_groups.items():
            for index, url in enumerate(urls, 1):
                if index not in position_filter:
                    allowed_old.add(url)

    bad_old = sorted({url for url in after_urls if url not in new_urls and url not in allowed_old})
    if bad_old:
        problems.append("%d unplanned old images kept" % len(bad_old))

    new_count = sum(1 for url in after_urls if url in new_urls)
    planned_sources = {position["url"] for position in plan_product["positions"]}
    retained_sources = {plan["tasks"][key]["currentUrl"] for key in retained_keys}
    remaining_sources = (planned_sources - retained_sources) & set(after_urls)
    if remaining_sources:
        problems.append("%d planned source images still online" % len(remaining_sources))
    distinct_new = {url for url in after_urls if url in new_urls}
    expected_distinct = len(planned_sources - retained_sources)
    if len(distinct_new) != expected_distinct:
        problems.append("distinct new urls %d, expected %d" % (len(distinct_new), expected_distinct))

    # Only groups that were planned are judged, and a group whose planned slots
    # were all kept old on purpose (model rejection / filtered position) is fine.
    planned_groups = {}
    for item in plan_product["positions"]:
        planned_groups.setdefault(item["group"], []).append(item)
    groups_without_new = []
    for gid, planned in planned_groups.items():
        urls = after_groups.get(gid) or []
        if any(url in new_urls for url in urls):
            continue
        kept_on_purpose = planned and all(item["key"] in retained_keys for item in planned)
        if not kept_on_purpose:
            groups_without_new.append(gid)
    if groups_without_new:
        problems.append("groups without new image: %s" % ",".join(groups_without_new[:3]))

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

    if (after.get("material") or {}).get("rectangleImages"):
        problems.append("rectangle images present")

    after_status = common.status_int((after.get("productInfo") or {}).get("productStatus"))
    raw_status = list_status if list_status is not None else after_status
    planned_status = plan_product.get("listStatus")
    if planned_status is not None and list_status is not None and int(planned_status) != int(list_status):
        problems.append("list status changed %s -> %s" % (planned_status, list_status))

    return {
        "ok": not problems,
        "problems": problems,
        "groupCount": len(after_groups),
        "images": len(after_urls),
        "newImages": new_count,
        "oldKept": len(after_urls) - new_count,
        "retainedKeys": sorted(retained_keys),
        "pricesUnchanged": before_prices == after_prices,
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
    new_urls = {
        common.clean_url(record["imgUrl"])
        for record in uploads.values()
        if record.get("status") == "succeeded"
    }
    selected = common.plan_products(plan, argv[2:])

    cli = common.connect(job)
    common.verify_identity(cli, job, run)
    statuses = list_status_map(cli)
    print("listed products:", len(statuses), "scope:", "+".join(scopes), flush=True)

    def fetch(pid):
        return pid, common.apply_detail(cli, pid)

    after_details = {}
    workers = int(job.get("fetchConcurrency") or 6)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch, int(product["productId"])): product for product in selected
        }
        for index, future in enumerate(as_completed(futures), 1):
            pid, detail = future.result()
            after_details[pid] = detail
            if index % 25 == 0 or index == len(selected):
                print("readback %d/%d" % (index, len(selected)), flush=True)

    report = {}
    for product in selected:
        pid = int(product["productId"])
        before = common.load_json(run / "products" / str(pid) / "before-apply.json")
        if not before:
            raise SystemExit("missing before-apply.json for %s" % pid)
        after = after_details[pid]
        before_status = common.status_int((before.get("productInfo") or {}).get("productStatus"))
        entry = {"title": product["title"]}
        problems = []

        if product.get("positions"):
            main_entry = evaluate_product(
                before, after, product, plan, patches, new_urls, before_status, statuses.get(pid)
            )
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

    common.save_json(run / "final-verification.json", report)
    ok = sum(1 for entry in report.values() if entry["ok"])
    print("final: ok=%d of %d" % (ok, len(report)), flush=True)
    if ok < len(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
