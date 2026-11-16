"""Detail-page (详情页) image rewrite, built on the same image-only PATCH flow.

The detail page is stored in productInfo.productDetailDesc:

  {"desc": "<img ... src=.../>...", "mobileDesc": "...", "zhuangBaUseFlag": "0",
   "mobileZhuangBaUseFlag": false}

Only the src values of planned images change; every other byte of the HTML is
preserved. The component is the same WareEditor/detail pair the publish flow
submits. material.ggtImages is the SKU spec-image echo and is never touched.

Status: code complete, needs one live pilot per shop before being reported as
verified. patch_detail.py refuses to write unless job.json sets
detailWrite: true and the caller passes the explicit confirmation word.
"""

import json
from typing import Any


def _properties(desc_html: str, flag: Any, user_agent: str) -> list[dict[str, Any]]:
    return [
        {"key": "desc", "value": desc_html},
        {"key": "zhuangBaUseFlag", "value": "0" if flag is None else str(flag)},
        {"key": "userAgent", "value": user_agent},
    ]


def build_detail_component(detail: dict[str, Any], desc_html: str, mobile_html: str) -> dict[str, Any]:
    raw = (detail.get("productInfo") or {}).get("productDetailDesc") or {}
    if not isinstance(raw, dict):
        raw = {}
    entries = [
        {
            "componentCode": "detail",
            "properties": _properties(desc_html, raw.get("zhuangBaUseFlag"), "pc"),
        }
    ]
    if mobile_html:
        entries.append(
            {
                "componentCode": "detail",
                "properties": _properties(
                    mobile_html, raw.get("mobileZhuangBaUseFlag"), "mobile"
                ),
            }
        )
    return {"componentCode": "WareEditor", "inputType": "multiText", "value": entries}


def build_detail_patch_payload(detail: dict[str, Any], url_map: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rewrite every planned detail image in desc and mobileDesc."""
    import _common as common

    htmls = common.detail_htmls(detail)
    new_htmls, replaced = {}, {}
    for field, html in htmls.items():
        if not html:
            continue
        rewritten, count = common.rewrite_detail_html(html, url_map)
        new_htmls[field] = rewritten
        replaced[field] = count
    if not new_htmls:
        raise ValueError("product has no detail HTML to patch")

    component = build_detail_component(detail, new_htmls.get("desc", ""), new_htmls.get("mobileDesc", ""))
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
        "patchOperationList": [
            {
                "path": "product",
                "value": json.dumps(component, ensure_ascii=False, separators=(",", ":")),
            }
        ],
    }
    summary = {
        "productId": product_id,
        "mapping": {key: value for key, value in url_map.items()},
        "replacedPerField": replaced,
        "newHtml": new_htmls,
    }
    return body, summary


def verify_detail_patch(before: dict[str, Any], after: dict[str, Any], url_map: dict[str, str]) -> list[str]:
    import _common as common

    problems: list[str] = []
    before_htmls = common.detail_htmls(before)
    after_htmls = common.detail_htmls(after)
    for field, before_html in before_htmls.items():
        if not before_html:
            continue
        after_html = after_htmls.get(field) or ""
        if not after_html:
            problems.append("%s disappeared" % field)
            continue
        expected_urls = [url_map.get(common.clean_url(url), common.clean_url(url))
                         for url in common.detail_src_urls(before_html)]
        actual_urls = [common.clean_url(url) for url in common.detail_src_urls(after_html)]
        if len(expected_urls) != len(actual_urls):
            problems.append("%s image count %d -> %d" % (field, len(expected_urls), len(actual_urls)))
            continue
        if expected_urls != actual_urls:
            mismatched = [index for index, (want, got) in enumerate(zip(expected_urls, actual_urls))
                          if want != got]
            problems.append("%s urls mismatch at %s" % (field, mismatched[:5]))
        if common.strip_src_values(before_html) != common.strip_src_values(after_html):
            problems.append("%s markup changed beyond image urls" % field)
    untouched = [url for url in common.detail_src_urls(before_htmls.get("desc", ""))
                 if common.clean_url(url) in url_map]
    after_all = set(common.clean_url(url) for url in common.detail_src_urls(after_htmls.get("desc", "")))
    remaining = [url for url in untouched if common.clean_url(url) in after_all]
    if remaining:
        problems.append("%d planned detail images still online" % len(remaining))
    return problems
