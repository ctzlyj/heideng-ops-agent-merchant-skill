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
from refresh_runtime import gallery_readback, snapshot, refresh_selection
import detail_patch_update as detail_patch


def _rectangle_slots(detail):
    """Use the observed group, order and original asset URL; absent/malformed data is unknown."""
    if not isinstance(detail, dict) or not isinstance(detail.get("material"), dict):
        return None
    groups = detail["material"].get("rectangleImages")
    if not isinstance(groups, list):
        return None
    slots = {}
    seen_groups = set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("imageInfoList"), list):
            return None
        group_id = group.get("uuid")
        if not isinstance(group_id, (str, int)) or isinstance(group_id, bool) or not str(group_id).strip():
            return None
        gid = str(group_id)
        if gid in seen_groups:
            return None
        seen_groups.add(gid)
        for image in group["imageInfoList"]:
            if not isinstance(image, dict):
                return None
            ordinal = str(image.get("orderSort", ""))
            url = image.get("imgUrl")
            if not ordinal.isascii() or not ordinal.isdigit() or not isinstance(url, str) or not url.strip():
                return None
            pos = int(ordinal)
            if pos < 1 or (gid, pos) in slots:
                return None
            slots[gid, pos] = common.clean_url(url.strip())
    return slots


def rectangle_readback(before, after):
    old, live = _rectangle_slots(before), _rectangle_slots(after)
    result = {
        "status": "unverified",
        "beforeSlots": len(old) if old is not None else None,
        "afterSlots": len(live) if live is not None else None,
    }
    if old is not None and live is not None:
        changes = sorted(slot for slot in old.keys() | live.keys() if old.get(slot) != live.get(slot))
        result.update(status="changed" if changes else "unchanged", changedSlots=len(changes),
                      examples=[{"group": gid, "position": pos} for gid, pos in changes[:5]])
    return result


def _main_targets(groups, product, plan, max_position=None):
    """Expand the plan's deduplicated assets onto its authorized physical slots."""
    pid = int(product["productId"])
    capped = {(str(row["group"]), int(row["position"])) for row in plan.get("capped") or []
              if int(row["productId"]) == pid}
    limit = min(9, int(max_position or plan.get("maxPosition") or common.DEFAULT_MAX_POSITION))
    position_filter = set(plan.get("positionFilter") or [])

    def allowed(gid, pos):
        return 1 <= pos <= limit and (not position_filter or pos in position_filter) and (gid, pos) not in capped

    by_url = {}
    planned_positions = {}
    for row in product["positions"]:
        gid, pos = str(row["group"]), int(row["position"])
        url, key = common.clean_url(row["url"]), row["key"]
        if not url or not key or (gid, pos) in planned_positions:
            raise ValueError(f"主图计划地址重复或缺少原图及素材标识：{gid}/{pos}")
        by_url.setdefault(url, set()).add(key)
        planned_positions[gid, pos] = (url, key)

    targets = {}
    if "selectedSlots" in product:
        for row in product["selectedSlots"]:
            gid, pos = str(row["group"]), int(row["position"])
            url, key = common.clean_url(row["url"]), row["key"]
            urls = groups.get(gid, [])
            if ((gid, pos) in targets or not allowed(gid, pos) or pos > len(urls)
                    or urls[pos - 1] != url or key not in by_url.get(url, set())):
                raise ValueError(f"冻结图位与批准的原图不符：{gid}/{pos}")
            targets[gid, pos] = (url, key)
    else:
        for gid, urls in groups.items():
            for pos, url in enumerate(urls, 1):
                if not allowed(gid, pos) or url not in by_url:
                    continue
                if (gid, pos) in planned_positions:
                    targets[gid, pos] = planned_positions[gid, pos]
                elif len(by_url[url]) == 1:
                    # Legacy plans recorded the first physical position of each source URL.
                    targets[gid, pos] = (url, next(iter(by_url[url])))
                else:
                    raise ValueError(f"同一原图对应多个素材任务，无法确定图位：{gid}/{pos}")
                if targets[gid, pos][0] != url:
                    raise ValueError(f"冻结图位与原图不符：{gid}/{pos}")
        if not planned_positions.items() <= targets.items():
            raise ValueError("主图计划的素材任务在授权图位内找不到对应原图")
    if not set(planned_positions.values()) <= set(targets.values()):
        raise ValueError("主图计划的素材任务在授权图位内找不到对应原图")
    return targets


def _read_main_slots(targets, groups, live_groups, retained_keys, uploads, generation, problems):
    slots = []
    expected = {gid: list(urls) for gid, urls in groups.items()}
    for (gid, pos), (original, key) in targets.items():
        live = live_groups.get(gid, [])
        actual = live[pos - 1] if pos <= len(live) else None
        state = "unverified"
        wanted = None
        if key in retained_keys:
            if (generation.get(key) or {}).get("status") == "rejected":
                wanted = original
                if actual == original:
                    state = "retained"
            else:
                problems.append("待核对的图片缺少成功上传回执：" + key)
        else:
            receipt = uploads.get(key) or {}
            url = receipt.get("imgUrl")
            if receipt.get("status") != "succeeded" or not isinstance(url, str) or not url.strip():
                problems.append("missing accepted upload: " + key)
            else:
                wanted = common.clean_url(url.strip())
                expected[gid][pos - 1] = wanted
                if wanted == original:
                    problems.append(f"目标图位 {gid}/{pos} 的回读只证明了原图")
                elif actual == wanted:
                    state = "verified"
        slots.append({"group": gid, "position": pos, "key": key, "status": state,
                      "beforeUrl": original, "expectedUrl": wanted, "observedUrl": actual})
    verified = sum(x["status"] == "verified" for x in slots)
    retained = sum(x["status"] == "retained" for x in slots)
    return expected, {"requested": len(slots), "verified": verified, "retained": retained,
                      "unresolved": len(slots) - verified - retained, "slots": slots}


def evaluate_product(
    before, after, plan_product, plan, patches, uploads, before_status, list_status, generation=None, max_position=None
):
    """Verify authorized physical slots and separately check the out-of-scope rectangle gallery."""
    problems = []
    pid = int(plan_product["productId"])
    before_groups = common.main_groups(before)
    after_groups = common.main_groups(after)
    after_urls = [url for urls in after_groups.values() for url in urls]
    retained_keys = set((patches.get(str(pid)) or {}).get("missingKeys") or [])
    targets = _main_targets(before_groups, plan_product, plan, max_position)
    expected_groups, slot_evidence = _read_main_slots(
        targets, before_groups, after_groups, retained_keys, uploads, generation or {}, problems
    )
    new_count = slot_evidence["verified"]
    before_state, after_state = snapshot(before, pid), snapshot(after, pid)
    before_state["groups"], after_state["groups"] = expected_groups, after_groups
    evidence = gallery_readback(before_state, after_state)
    problems.extend(evidence["problems"])

    rectangles = rectangle_readback(before, after)
    if rectangles["status"] == "changed":
        problems.append("范围外 3:4 长图的图组、图位或原图发生变化")
    elif rectangles["status"] == "unverified" and (rectangles["beforeSlots"] or rectangles["afterSlots"]):
        problems.append("范围外 3:4 长图回读不完整，变化待核对")

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
        "mainSlotReadback": slot_evidence,
        "rectangleReadback": rectangles,
        "oldKept": sum(old == actual for gid, urls in before_groups.items()
                       for old, actual in zip(urls, after_groups.get(gid, []))),
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


def _unavailable_main_readback(before, after, product, plan, max_position):
    result = {"rectangleReadback": rectangle_readback(before, after)}
    if before and product.get("positions"):
        try:
            snapshot(before, int(product["productId"]))
            groups = common.main_groups(before)
            targets = _main_targets(groups, product, plan, max_position)
        except (AttributeError, ValueError, TypeError, KeyError):
            return result
        slots = [{"group": gid, "position": pos, "key": key, "status": "unverified",
                  "beforeUrl": url, "expectedUrl": None, "observedUrl": None}
                 for (gid, pos), (url, key) in targets.items()]
        result["mainSlotReadback"] = {"requested": len(slots), "verified": 0, "retained": 0,
                                      "unresolved": len(slots), "slots": slots}
    return result


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


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: verify.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    refresh_selection.verify_frozen(job, plan, run)
    scopes = plan.get("scopes") or ["main"]
    uploads = common.load_json(run / "uploads.json") or {}
    patches = common.load_json(run / "patch-results.json") or {}
    generation = common.load_json(run / "internal-generation.json") or {}
    selected = common.plan_products(plan, argv[2:])

    cli = common.connect(job)
    common.verify_identity(cli, job, run)
    statuses = refresh_selection.listed_products(cli, [p["productId"] for p in selected])
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
        after = after_details.get(pid)
        if not before or pid in read_errors:
            entry = {"title": product["title"], "ok": False, "consumerPageStatus": "unchecked",
                     "problems": [read_errors.get(pid) or "missing before-apply.json"]}
            if product.get("positions"):
                entry.update(_unavailable_main_readback(before, after, product, plan, job.get("maxPosition")))
            report[str(pid)] = entry
            continue
        before_status = common.status_int((before.get("productInfo") or {}).get("productStatus"))
        entry = {"title": product["title"]}
        problems = []

        if product.get("positions"):
            try:
                main_entry = evaluate_product(
                    before, after, product, plan, patches, uploads, before_status, statuses.get(pid), generation,
                    job.get("maxPosition")
                )
            except (AttributeError, ValueError, KeyError, TypeError) as exc:
                main_entry = _unavailable_main_readback(before, after, product, plan, job.get("maxPosition"))
                main_entry.update(ok=False, consumerPageStatus="unchecked", problems=[str(exc)[:300]])
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
