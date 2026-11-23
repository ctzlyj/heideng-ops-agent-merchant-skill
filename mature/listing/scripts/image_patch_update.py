"""Image-only PATCH updates for products that cannot pass a full edit.

A synced copy lives in jd-jingmai-batch-main-image-refresh/scripts/; keep the
two identical so both the 搬运 flow and the standalone refresh skill behave
the same way.

Some legacy products carry structured sale attributes whose aliases no longer
pass platform revalidation (1010300506). Any full product-applies edit
rebuilds those attributes and is rejected. The PATCH endpoint
/rest/sp-product/v0/product-applies/{applyId} (opType 3, shared-image flow)
only updates WareSkuImg components, so sale attributes are never revalidated.

Verified 2026-10-10 on a live POP store: 7/7 structured-attribute products updated
and apply-detail rechecks matched every swapped URL.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jdo_listing_mvp as cli  # isolated, bundled mature listing dependency


def build_image_patch_payload(detail: dict[str, Any], url_map: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a PATCH body replacing every main-image URL found in url_map.

    Groups and positions come from live apply-detail, so color bindings and
    order are preserved; only imgUrl values change. Returns (body, summary).
    Unmapped URLs are kept unchanged and reported.
    """
    operations: list[dict[str, Any]] = []
    replaced: dict[str, str] = {}
    unchanged: list[str] = []
    for group in (detail.get("material") or {}).get("mainImages") or []:
        color_id = str(group.get("uuid") or "")
        image_values = []
        images = sorted(group.get("imageInfoList") or [], key=lambda i: int(i.get("orderSort") or 0))
        for position, image in enumerate(images, 1):
            old = str(image.get("imgUrl") or "")
            if old in url_map:
                new = str(url_map[old])
                replaced[old] = new
                target = new
            else:
                if old:
                    unchanged.append(old)
                target = old
            image_values.append({
                "componentCode": "img",
                "inputType": "multiText",
                "properties": [
                    {"key": "colorId", "value": color_id},
                    {"key": "imgUrl", "value": target},
                    {"key": "imgRefId", "value": color_id},
                    {"key": "orderSort", "value": str(position)},
                ],
            })
        operations.append({
            "path": "product",
            "value": json.dumps({
                "componentCode": "WareSkuImg",
                "inputType": "multiText",
                "value": image_values,
            }, ensure_ascii=False, separators=(",", ":")),
        })
    product_info = detail.get("productInfo") or {}
    category_id = int((product_info.get("categoryDetail") or {}).get("lastCategoryId") or 0)
    product_id = int(product_info.get("productId") or detail.get("productId") or 0)
    body = {
        "applyId": str(product_id),
        "opType": 3,
        "scene": "pop",
        "productInfo": {
            "productId": product_id,
            "categoryDetail": {"lastCategoryId": category_id},
        },
        "productApplyDTO": {"id": str(product_id)},
        "patchOperationList": operations,
    }
    summary = {
        "productId": product_id,
        "groups": len(operations),
        "replaced": len(replaced),
        "mapping": replaced,
        "unchangedUrls": sorted(set(unchanged)),
    }
    return body, summary


def group_urls(detail: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for group in (detail.get("material") or {}).get("mainImages") or []:
        result[str(group.get("uuid"))] = [
            str(i.get("imgUrl") or "")
            for i in sorted(group.get("imageInfoList") or [], key=lambda x: int(x.get("orderSort") or 0))
        ]
    return result


def verify_patch(before: dict[str, Any], after: dict[str, Any], replaced: dict[str, str]) -> list[str]:
    problems: list[str] = []
    before_groups, after_groups = group_urls(before), group_urls(after)
    if set(before_groups) != set(after_groups):
        return [f"groups changed: {sorted(before_groups)} -> {sorted(after_groups)}"]
    for uuid_key, urls in before_groups.items():
        expected = [replaced.get(url, url) for url in urls]
        actual = after_groups.get(uuid_key) or []
        extra = actual[len(expected):]
        if actual[: len(expected)] != expected:
            problems.append(f"group {uuid_key} urls mismatch")
        elif extra and any(url != expected[-1] for url in extra):
            problems.append(f"group {uuid_key} unexpected trailing urls")
    before_skus = {str(s.get("skuId")): s for s in before.get("skuList") or []}
    after_skus = {str(s.get("skuId")): s for s in after.get("skuList") or []}
    if set(before_skus) != set(after_skus):
        problems.append("sku set changed")
    for sku_id, sku in before_skus.items():
        other = after_skus.get(sku_id)
        if other and (sku.get("priceInfo") or {}).get("jdPrice") != (other.get("priceInfo") or {}).get("jdPrice"):
            problems.append(f"sku {sku_id} price changed")
    return problems


def apply_detail(product_id: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            return (
                cli.get(
                    "jdo-product-update",
                    "/rest/sp-product/v0/product-apply/{applyId}",
                    {"applyId": product_id, "scene": "pop"},
                ).get("data")
                or {}
            )
        except Exception as exc:  # transient gateway errors
            last_error = exc
            time.sleep(5 + attempt * 5)
    raise RuntimeError(f"apply-detail {product_id} failed: {last_error}")


def patch_product(product_id: int, url_map: dict[str, str], confirm: str, body_dir: Path | None = None,
                  all_matching_slots: bool = False) -> dict[str, Any]:
    if confirm != "PATCH_PRODUCT_IMAGES":
        raise cli.JdoError("image-only patch requires --confirm PATCH_PRODUCT_IMAGES")
    from heideng_merchant.gallery_patch import mapped_patch
    return mapped_patch(cli, apply_detail, cli.require_verified_jdo_store(), product_id, url_map,
                        allow_shared=all_matching_slots, body_dir=body_dir)


def main() -> int:
    if sys.argv[1:2] == ['pilot-main-image']:
        from heideng_merchant.gallery_patch import pilot
        parser = argparse.ArgumentParser(description='核验一个 SKU 的首图，按商家交办试发一张本地成图')
        parser.add_argument('--profile', required=True)
        parser.add_argument('--store-config', type=Path, default=cli.STORE_CONFIG)
        parser.add_argument('--product-id', type=int, required=True)
        parser.add_argument('--sku-id', required=True)
        parser.add_argument('--image', type=Path)
        parser.add_argument('--expected-url', help='制作样张时从目标 SKU 读到的首图地址')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--check-only', action='store_true')
        mode.add_argument('--reconcile', action='store_true')
        mode.add_argument('--confirm', choices=['PUBLISH_ONE_SKU_FIRST_IMAGE'])
        args = parser.parse_args(sys.argv[2:])
        identity = cli.verify_configured_store_identity(args.store_config, args.profile)
        result = pilot(cli, apply_detail, identity, args.product_id, args.sku_id, args.image, args.expected_url,
                       publish=bool(args.confirm), reconcile=args.reconcile)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['ok'] else 2
    if sys.argv[1:2] == ['replace-sku-images']:
        from heideng_merchant.sku_image_edit import run, unique
        parser = argparse.ArgumentParser(description='在原商品按 SKU 替换规格图')
        parser.add_argument('--profile', required=True)
        parser.add_argument('--store-config', type=Path, default=cli.STORE_CONFIG)
        parser.add_argument('--product-id', type=int, required=True)
        parser.add_argument('--package', type=Path, help='原发布包；省略时读取本商品实时编辑模板')
        parser.add_argument('--images', type=Path, help='SKU ID 到本地图片路径的 JSON 映射')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--check-only', action='store_true')
        mode.add_argument('--reconcile', action='store_true')
        mode.add_argument('--confirm', choices=['REPLACE_SKU_IMAGES'])
        args = parser.parse_args(sys.argv[2:])
        mapping = {}
        if args.images is not None:
            values = json.loads(args.images.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)
            mapping = {key: args.images.parent / path for key, path in values.items()}
        identity = cli.verify_configured_store_identity(args.store_config, args.profile)
        result = run(cli, apply_detail, identity, args.product_id, mapping, args.package,
                     check_only=args.check_only, reconcile=args.reconcile)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] in ('verified', 'eligible') else 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--store-config", type=Path, default=cli.STORE_CONFIG)
    parser.add_argument("--product-ids", required=True, help="comma-separated product ids")
    parser.add_argument("--url-map", type=Path, required=True, help="JSON file {oldUrl: newUrl}")
    parser.add_argument("--bodies-dir", type=Path)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--all-matching-slots", action="store_true",
                        help="整商品换图已获准覆盖同一 URL 命中的全部分组与图位")
    args = parser.parse_args()
    cli.verify_configured_store_identity(args.store_config, args.profile)
    url_map = json.loads(args.url_map.read_text(encoding="utf-8"))
    results = []
    for pid_text in [x for x in args.product_ids.split(",") if x.strip()]:
        results.append(patch_product(int(pid_text), url_map, args.confirm, args.bodies_dir, args.all_matching_slots))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    failed = [r for r in results if not r.get("ok")]
    print(json.dumps({"ok": not failed, "count": len(results), "failed": len(failed)}, ensure_ascii=False))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
