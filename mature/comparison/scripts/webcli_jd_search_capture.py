#!/usr/bin/env python3
"""Capture sanitized JD title-search product cards through one WebCLI profile."""

from __future__ import annotations

import argparse
import base64
import json
import re
import tempfile
from browser_runtime import BrowserRuntimeError, invoke_webcli, session_name
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit


SKU_PATTERN = re.compile(r"\d{5,20}")
SALES_PATTERNS = (
    re.compile(r"已售\s*(\d+(?:\.\d+)?)(万|亿|千)?\+?"),
    re.compile(r"(\d+(?:\.\d+)?)(万|亿|千)?\+?\s*件已售"),
    re.compile(r"sold\s*(\d+(?:\.\d+)?)(w|k|m|b)?\+?", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)(w|k|m|b)?\+?\s*sold", re.IGNORECASE),
)
COUNT_MULTIPLIERS = {
    "": 1,
    "千": 1_000,
    "万": 10_000,
    "亿": 100_000_000,
    "k": 1_000,
    "w": 10_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}
ALLOWED_DEGRADATION_CODES = {"VISIBLE_IMAGE_SEARCH_UNAVAILABLE"}
ALLOWED_DEGRADATION_OBSERVATIONS = {
    "IMAGE_SEARCH_ENTRY_ABSENT",
    "JD_ASSISTANT_DOWNLOAD_INTRO_ONLY",
}
ALLOWED_SEARCH_ROLES = {"fallback", "supplement", "independent"}
DEFAULT_WAIT_SECONDS = 5
DEFAULT_MAX_SCROLLS = 30


class SearchCaptureError(RuntimeError):
    pass


def _clean_text(value: Any, maximum: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _sku_id(value: Any) -> str:
    text = _clean_text(value, 32)
    if not SKU_PATTERN.fullmatch(text):
        raise SearchCaptureError("SKU_INVALID")
    return text


def _canonical_item_url(sku_id: str) -> str:
    return f"https://item.jd.com/{_sku_id(sku_id)}.html"


def _safe_image_url(value: Any) -> str:
    text = _clean_text(value, 2000)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def parse_display_count_lower_bound(value: Any) -> int | None:
    text = _clean_text(value, 120)
    for pattern in SALES_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        amount = float(match.group(1))
        unit = (match.group(2) or "").lower()
        return int(amount * COUNT_MULTIPLIERS[unit])
    return None


def _display_price(value: Any) -> str:
    text = _clean_text(value, 120)
    match = re.search(r"(?<!\d)(\d{1,9}(?:\.\d{1,2})?)(?!\d)", text)
    return match.group(1) if match else ""


def _review_lower_bound(value: Any) -> int | None:
    text = _clean_text(value, 120)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿|千)?\+?\s*(?:条)?评价", text)
    if not match:
        return None
    return int(float(match.group(1)) * COUNT_MULTIPLIERS[match.group(2) or ""])


def _validate_source(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise SearchCaptureError("SOURCE_INVALID")
    sanitized = dict(source)
    source_sku = _sku_id(sanitized.get("sku_id"))
    if _clean_text(sanitized.get("product_url"), 300) != _canonical_item_url(source_sku):
        raise SearchCaptureError("SOURCE_SKU_URL_MISMATCH")
    for field in ("spu_id", "title", "shop_name", "normalized_spec"):
        if not _clean_text(sanitized.get(field), 500):
            raise SearchCaptureError(f"SOURCE_{field.upper()}_REQUIRED")
    evidence = sanitized.get("spu_evidence")
    if (
        not isinstance(evidence, dict)
        or _clean_text(evidence.get("sku_id"), 32) != source_sku
        or _clean_text(evidence.get("spu_id"), 120) != _clean_text(sanitized["spu_id"], 120)
        or not _clean_text(evidence.get("captured_at"), 80)
    ):
        raise SearchCaptureError("SOURCE_SPU_EVIDENCE_INVALID")
    return sanitized


def _sanitize_candidate(raw: Any, captured_at: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("is_ad") is True:
        return None
    try:
        sku_id = _sku_id(raw.get("sku_id"))
    except SearchCaptureError:
        return None
    title = _clean_text(raw.get("title"), 500)
    if not title:
        return None
    candidate = {
        "sku_id": sku_id,
        "spu_id": _clean_text(raw.get("spu_id"), 120),
        "title": title,
        "shop_name": _clean_text(raw.get("shop_name"), 300),
        "product_url": _canonical_item_url(sku_id),
        "image_url": _safe_image_url(raw.get("image_url")),
        "is_ad": False,
    }
    display_price = _display_price(raw.get("display_price"))
    if display_price:
        candidate["display_price"] = display_price
    sales_text = _clean_text(raw.get("sales_text"), 120)
    sales_lower_bound = parse_display_count_lower_bound(sales_text)
    if sales_lower_bound is not None:
        candidate.update(
            {
                "sales_text": sales_text,
                "sales_lower_bound": sales_lower_bound,
                "sales_evidence": {
                    "source": "jd_visible_product_card",
                    "sku_id": sku_id,
                    "product_url": candidate["product_url"],
                    "captured_at": captured_at,
                },
            }
        )
    review_text = _clean_text(raw.get("review_text"), 120)
    review_lower_bound = _review_lower_bound(review_text)
    if review_lower_bound is not None:
        candidate["review_text"] = review_text
        candidate["review_lower_bound"] = review_lower_bound
    return candidate


def _merge_candidate(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    merged = dict(existing)
    for field in ("title", "shop_name", "image_url", "display_price"):
        if candidate.get(field):
            merged[field] = candidate[field]
    if candidate.get("sales_lower_bound", -1) > existing.get("sales_lower_bound", -1):
        for field in ("sales_text", "sales_lower_bound", "sales_evidence"):
            merged[field] = candidate[field]
    if candidate.get("review_lower_bound", -1) > existing.get("review_lower_bound", -1):
        merged["review_text"] = candidate["review_text"]
        merged["review_lower_bound"] = candidate["review_lower_bound"]
    return merged


def _canonical_search_page(value: Any) -> str:
    try:
        parsed = urlsplit(_clean_text(value, 2000))
    except ValueError as error:
        raise SearchCaptureError("SEARCH_PAGE_INVALID") from error
    if parsed.scheme != "https" or parsed.hostname != "search.jd.com":
        raise SearchCaptureError("SEARCH_PAGE_INVALID")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/Search", "", ""))


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, str]:
    return (-int(candidate.get("sales_lower_bound", -1)), candidate["sku_id"])


def capture_title_search(
    client: Any,
    *,
    keyword: str,
    source: dict[str, Any],
    own_shop_names: list[str],
    search_role: str = "fallback",
    image_search_issue_code: str = "",
    image_search_observation: str = "",
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
) -> dict[str, Any]:
    try:
        clean_keyword = _clean_text(keyword, 300)
        if not clean_keyword:
            raise SearchCaptureError("SEARCH_KEYWORD_REQUIRED")
        clean_source = _validate_source(source)
        own_shops = sorted({_clean_text(value, 300) for value in own_shop_names if _clean_text(value, 300)})
        if not own_shops:
            raise SearchCaptureError("OWN_SHOP_FILTER_REQUIRED")
        clean_search_role = _clean_text(search_role, 40)
        if clean_search_role not in ALLOWED_SEARCH_ROLES:
            raise SearchCaptureError("SEARCH_ROLE_INVALID")
        if clean_search_role == "fallback":
            if (
                image_search_issue_code not in ALLOWED_DEGRADATION_CODES
                or image_search_observation not in ALLOWED_DEGRADATION_OBSERVATIONS
            ):
                raise SearchCaptureError("IMAGE_SEARCH_DEGRADATION_REQUIRED")
        elif image_search_issue_code or image_search_observation:
            raise SearchCaptureError("IMAGE_SEARCH_DEGRADATION_NOT_APPLICABLE")
        if not isinstance(max_scrolls, int) or isinstance(max_scrolls, bool) or max_scrolls < 0 or max_scrolls > 100:
            raise SearchCaptureError("MAX_SCROLLS_INVALID")

        client.ensure_profile_ready()
        client.open_search(clean_keyword)
        client.wait_for_page()
        blocker = _clean_text(client.page_blocker(), 120)
        if blocker:
            raise SearchCaptureError(blocker)

        captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
        by_sku: dict[str, dict[str, Any]] = {}
        observed_skus: set[str] = set()
        filtered_counts = {"advertisement_or_invalid": 0, "source_product": 0, "own_shop": 0}
        page_url = ""
        reached_end = False
        scrolls = 0
        own_shop_keys = {value.casefold() for value in own_shops}
        own_shop_keys.add(_clean_text(clean_source["shop_name"], 300).casefold())

        while True:
            snapshot = client.snapshot_cards()
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("cards"), list):
                raise SearchCaptureError("SEARCH_SNAPSHOT_INVALID")
            page_url = _canonical_search_page(snapshot.get("page_url"))
            for raw in snapshot["cards"]:
                candidate = _sanitize_candidate(raw, captured_at)
                if candidate is None:
                    filtered_counts["advertisement_or_invalid"] += 1
                    continue
                observed_skus.add(candidate["sku_id"])
                if (
                    candidate["sku_id"] == clean_source["sku_id"]
                    or candidate.get("spu_id") == clean_source["spu_id"]
                ):
                    filtered_counts["source_product"] += 1
                    continue
                if candidate["shop_name"].casefold() in own_shop_keys:
                    filtered_counts["own_shop"] += 1
                    continue
                by_sku[candidate["sku_id"]] = _merge_candidate(
                    by_sku.get(candidate["sku_id"]), candidate
                )
            reached_end = snapshot.get("at_end") is True
            if reached_end or scrolls >= max_scrolls:
                break
            client.scroll_down()
            scrolls += 1
            blocker = _clean_text(client.page_blocker(), 120)
            if blocker:
                raise SearchCaptureError(blocker)

        candidates = sorted(by_sku.values(), key=_candidate_sort_key)
        capture_audit = {
            "discovery_mode": "title_spec_search",
            "search_role": clean_search_role,
            "virtual_scroll_complete": reached_end,
            "scroll_count": scrolls,
            "observed_unique_sku_count": len(observed_skus),
            "eligible_candidate_count": len(candidates),
            "filtered_counts": filtered_counts,
        }
        if clean_search_role == "fallback":
            capture_audit.update(
                {
                    "degraded_from": "jd_visible_image_search",
                    "degradation_code": image_search_issue_code,
                    "degradation_observation": image_search_observation,
                }
            )
        elif clean_search_role == "supplement":
            capture_audit["supplements"] = "jd_visible_image_search"

        return {
            "source": clean_source,
            "own_shop_names": own_shops,
            "captures": [
                {
                    "channel": "jd_title_search",
                    "captured_at": captured_at,
                    "page_url": page_url,
                    "capture_audit": capture_audit,
                    "candidates": candidates,
                }
            ],
        }
    finally:
        client.close()


def _snapshot_script() -> str:
    return r"""(() => {
const clean = value => String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
const rendered = node => Boolean(node && node.isConnected && node.getClientRects().length && getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden');
const first = (root, selectors) => { for (const selector of selectors) { const node = root.querySelector(selector); if (node) return node; } return null; };
const safeImage = value => { try { const url = new URL(value || '', location.href); return /^https?:$/.test(url.protocol) ? url.href : ''; } catch (_) { return ''; } };
const matchText = (root, selectors, patterns) => { const seen = new Set(); for (const selector of selectors) { for (const node of root.querySelectorAll(selector)) { if (seen.has(node) || !rendered(node)) continue; seen.add(node); const text = clean(node.textContent); for (const pattern of patterns) { const match = text.match(pattern); if (match) return clean(match[0]); } } } return ''; };
const selectors = ["#J_goodsList .gl-item[data-sku]", ".gl-warp .gl-item[data-sku]", "[class*='goodsCardWrapper'][data-sku]", "[data-sku]"];
const cards = [];
const seen = new Set();
for (const selector of selectors) {
  for (const card of document.querySelectorAll(selector)) {
    if (seen.has(card) || !rendered(card)) continue;
    seen.add(card);
    const skuId = clean(card.getAttribute('data-sku'));
    const titleNode = first(card, ["[class*='goods_title_container'] [title]", ".p-name a[title]", ".p-name a", "[class*='title'] a[title]", "[class*='title'] a", "a[title]"]);
    const title = titleNode ? clean(titleNode.getAttribute('title') || titleNode.textContent) : '';
    if (!/^\d{5,20}$/.test(skuId) || !title) continue;
    const image = first(card, ["img[data-lazy-img]", "img[data-src]", "img[src]"]);
    const shop = first(card, [".p-shop a", "[class*='shop'] a", "[class*='shop']", "[class*='_newStyle_'] [class*='_name_']"]);
    const shopServiceIcon = first(card, ["[class*='customer_service_icon']"]);
    const shopNode = shop || (shopServiceIcon ? shopServiceIcon.parentElement : null);
    const salesText = matchText(card, ["[class*='sales']", "[class*='sold']", "[class*='volume']", "[class*='commit']", ".p-commit", "[class*='deal']", "[data-testid*='sales']"], [/已售\s*\d+(?:\.\d+)?(?:[万亿千])?\+?/, /\d+(?:\.\d+)?(?:[万亿千])?\+?\s*件已售/]);
    const reviewText = matchText(card, ["[class*='commit']", ".p-commit", "[class*='review']"], [/\d+(?:\.\d+)?(?:[万亿千])?\+?\s*(?:条)?评价/, /累计评价\s*\d+(?:\.\d+)?(?:[万亿千])?\+?/]);
    const priceNode = first(card, ["[class*='price_'] [class*='price']", "[class*='price_']", ".p-price i", ".p-price", "[class*='price']"]);
    const labels = Array.from(card.querySelectorAll("[class*='ad'], [class*='Ad'], [class*='promo']")).map(node => clean(node.textContent)).join(' ');
    cards.push({
      sku_id: skuId,
      title,
      shop_name: shopNode ? clean(shopNode.textContent) : '',
      image_url: image ? safeImage(image.getAttribute('data-lazy-img') || image.getAttribute('data-src') || image.currentSrc || image.src) : '',
      display_price: priceNode ? clean(priceNode.textContent) : '',
      sales_text: salesText,
      review_text: reviewText,
      is_ad: /(?:广告|推广|赞助|sponsored|advertisement)/i.test(labels + ' ' + clean(card.textContent))
    });
  }
}
const root = document.documentElement;
return {
  page_url: location.origin + location.pathname,
  at_end: Math.ceil(window.scrollY + window.innerHeight) >= root.scrollHeight - 20,
  cards
};
})()"""


def _batch_safe_eval_script(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return (
        "(() => {"
        f"const bytes=Uint8Array.from(atob('{encoded}'),value=>value.charCodeAt(0));"
        "return (0,eval)(new TextDecoder().decode(bytes));"
        "})()"
    )


class SubprocessWebCliSearchClient:
    def __init__(
        self,
        profile: str,
        session: str,
        wait_seconds: int = DEFAULT_WAIT_SECONDS,
        timeout_seconds: int = 150,
    ) -> None:
        self.profile = _clean_text(profile, 200)
        self.session = _clean_text(session, 200)
        self.wait_seconds = int(wait_seconds)
        self.timeout_seconds = int(timeout_seconds)
        if not self.profile or not self.session:
            raise SearchCaptureError("WEBCLI_PROFILE_REQUIRED")
        if self.wait_seconds < 1 or self.wait_seconds > 30:
            raise SearchCaptureError("WAIT_SECONDS_INVALID")

    def _invoke(self, arguments: list[str]) -> str:
        try:
            return invoke_webcli(arguments, timeout=self.timeout_seconds)
        except BrowserRuntimeError as error:
            raise SearchCaptureError(str(error)) from error

    def _invoke_json(self, arguments: list[str]) -> Any:
        try:
            payload = json.loads(self._invoke(arguments))
        except json.JSONDecodeError as error:
            raise SearchCaptureError("WEBCLI_JSON_INVALID") from error
        if isinstance(payload, dict) and payload.get("error"):
            raise SearchCaptureError("WEBCLI_COMMAND_FAILED")
        return payload

    def _browser(self, *arguments: str) -> list[str]:
        return [
            "webcli",
            "--profile",
            self.profile,
            "browser",
            self.session,
            "--window",
            "background",
            *arguments,
        ]

    def ensure_profile_ready(self) -> None:
        doctor = self._invoke_json(["webcli", "--json", "doctor"])
        profiles = doctor.get("profiles") if isinstance(doctor, dict) else None
        matched = next(
            (
                item
                for item in profiles or []
                if isinstance(item, dict) and item.get("contextId") == self.profile
            ),
            None,
        )
        if not matched or matched.get("extensionConnected") is not True:
            raise SearchCaptureError("BROWSER_BRIDGE_NOT_READY")

    def open_search(self, keyword: str) -> None:
        query = urlencode({"keyword": keyword})
        self._invoke_json(self._browser("open", f"https://search.jd.com/Search?{query}"))

    def wait_for_page(self) -> None:
        self._invoke(self._browser("wait", "time", str(self.wait_seconds)))

    def page_blocker(self) -> str:
        script = (
            "(() => {"
            "const url=new URL(location.href);"
            "const text=(document.body&&document.body.innerText||'').slice(0,200000);"
            "let code='';"
            "if(/captcha|verifycode|slider/i.test(url.href)||/验证码|滑块验证|完成验证/.test(text))code='CAPTCHA_REQUIRED';"
            "else if(/safe\\.jd\\.com|risk|security/i.test(url.href)||/账号存在风险|安全验证|风险校验/.test(text))code='RISK_CONTROL';"
            "else if(/passport\\.jd\\.com|login\\.jd\\.com/i.test(url.href)||/你好，请登录|请登录后/.test(text))code='LOGIN_REQUIRED';"
            "else if(url.hostname!=='search.jd.com')code='SEARCH_PAGE_INVALID';"
            "return {code};"
            "})()"
        )
        result = self._invoke_json(self._browser("eval", _batch_safe_eval_script(script)))
        if not isinstance(result, dict):
            return "SEARCH_PAGE_INVALID"
        return _clean_text(result.get("code"), 120)

    def snapshot_cards(self) -> dict[str, Any]:
        result = self._invoke_json(
            self._browser("eval", _batch_safe_eval_script(_snapshot_script()))
        )
        if not isinstance(result, dict):
            raise SearchCaptureError("SEARCH_SNAPSHOT_INVALID")
        return result

    def scroll_down(self) -> None:
        self._invoke(self._browser("scroll", "down", "--amount", "1200"))
        self._invoke(self._browser("wait", "time", "1"))

    def close(self) -> None:
        self.cleanup_verified = False
        try:
            self._invoke(self._browser("close"))
            self.cleanup_verified = True
        except SearchCaptureError:
            return


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            suffix=".json",
            dir=path.parent,
        ) as temporary:
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture sanitized JD title-search cards through one WebCLI profile."
    )
    parser.add_argument("--profile", required=True, help="Connected Browser Bridge context ID or alias.")
    parser.add_argument("--keyword", required=True, help="JD title/specification search query.")
    parser.add_argument("--source", type=Path, required=True, help="Sanitized source product JSON object.")
    parser.add_argument("--own-shop", action="append", required=True, help="Own shop name; repeat when needed.")
    parser.add_argument("--search-role", default="fallback", choices=sorted(ALLOWED_SEARCH_ROLES))
    parser.add_argument("--image-search-issue", default="", choices=["", *sorted(ALLOWED_DEGRADATION_CODES)])
    parser.add_argument("--image-search-observation", default="", choices=["", *sorted(ALLOWED_DEGRADATION_OBSERVATIONS)])
    parser.add_argument("--output", type=Path, required=True, help="Sanitized discovery capture JSON path.")
    parser.add_argument("--session", default=None, help="Dedicated browser session; otherwise generated per task.")
    parser.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument("--max-scrolls", type=int, default=DEFAULT_MAX_SCROLLS)
    arguments = parser.parse_args()
    client = SubprocessWebCliSearchClient(
        profile=arguments.profile,
        session=arguments.session or session_name("search"),
        wait_seconds=arguments.wait_seconds,
    )
    try:
        source = json.loads(arguments.source.read_text(encoding="utf-8-sig"))
        result = capture_title_search(
            client,
            keyword=arguments.keyword,
            source=source,
            own_shop_names=arguments.own_shop,
            search_role=arguments.search_role,
            image_search_issue_code=arguments.image_search_issue,
            image_search_observation=arguments.image_search_observation,
            max_scrolls=arguments.max_scrolls,
        )
        _atomic_write_json(arguments.output, result)
    except (SearchCaptureError, FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    capture = result["captures"][0]
    print(
        json.dumps(
            {
                "status": "READY" if capture["capture_audit"]["virtual_scroll_complete"] else "PARTIAL",
                "candidate_count": len(capture["candidates"]),
                "output": str(arguments.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
