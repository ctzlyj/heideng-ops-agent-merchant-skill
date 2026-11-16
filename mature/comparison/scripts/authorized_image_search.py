import json
import os
from urllib.parse import urlsplit
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from competitor_discovery import DiscoveryValidationError, normalize_jd_item_url


BRIDGE_ORIGIN = None  # No implicit employee service; explicit merchant bridge only.


class AuthorizedSearchError(ValueError):
    pass


def _request_json(path: str, payload: dict[str, Any] | None = None) -> Any:
    origin = BRIDGE_ORIGIN or os.environ.get("HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN", "")
    parsed = urlsplit(origin)
    if not origin:
        raise AuthorizedSearchError("AUTHORIZED_IMAGE_SEARCH_UNCONFIGURED")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AuthorizedSearchError("AUTHORIZED_IMAGE_SEARCH_ORIGIN_INVALID")
    url = f"{origin.rstrip('/')}{path}"
    if payload is None:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthorizedSearchError(
            f"Authorized image-search bridge request failed: {error}"
        ) from error


def require_upstream_health(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise AuthorizedSearchError("Authorized image-search bridge is not healthy.")
    if payload.get("mode") != "upstream" or payload.get("upstreamConfigured") is not True:
        raise AuthorizedSearchError("Authorized image-search upstream is not configured.")
    return payload


def validate_search_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("mode") != "upstream":
        raise AuthorizedSearchError(
            "Authorized image-search response is not upstream data."
        )
    source = payload.get("source")
    if not isinstance(source, dict) or not str(
        source.get("normalizedSpecKey", "")
    ).strip():
        raise AuthorizedSearchError(
            "Authorized response is missing source.normalizedSpecKey."
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise AuthorizedSearchError("Authorized response is missing candidates.")
    source_spec = str(source["normalizedSpecKey"]).strip()
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise AuthorizedSearchError(
                f"Authorized candidate {index} is not an object."
            )
        sku_id = str(candidate.get("skuId", "")).strip()
        try:
            url_sku, normalized_url = normalize_jd_item_url(
                candidate.get("productUrl", "")
            )
        except DiscoveryValidationError as error:
            raise AuthorizedSearchError(
                f"Authorized candidate {index} has invalid productUrl."
            ) from error
        if not sku_id or sku_id != url_sku:
            raise AuthorizedSearchError(
                f"Authorized candidate {index} has inconsistent SKU evidence."
            )
        candidate["productUrl"] = normalized_url
        if not str(candidate.get("normalizedSpecKey", "")).strip():
            raise AuthorizedSearchError(
                f"Authorized candidate {index} is missing normalizedSpecKey."
            )
        sales = candidate.get("salesCount")
        if not isinstance(sales, int) or isinstance(sales, bool) or sales < 0:
            raise AuthorizedSearchError(
                f"Authorized candidate {index} has invalid salesCount."
            )
        price = candidate.get("priceCents")
        if price is not None and (
            not isinstance(price, int) or isinstance(price, bool) or price < 0
        ):
            raise AuthorizedSearchError(
                f"Authorized candidate {index} has invalid priceCents."
            )
        candidate["authorizedSpecMatchesSource"] = (
            str(candidate["normalizedSpecKey"]).strip() == source_spec
        )
    return payload


def search_authorized(request_payload: dict[str, Any]) -> dict[str, Any]:
    require_upstream_health(_request_json("/health"))
    return validate_search_response(
        _request_json("/api/similar-search", request_payload)
    )


def to_discovery_capture(
    payload: dict[str, Any], captured_at: str
) -> dict[str, Any]:
    validated = validate_search_response(payload)
    candidates = []
    for candidate in validated["candidates"]:
        if candidate["authorizedSpecMatchesSource"] is not True:
            continue
        candidates.append(
            {
                "sku_id": candidate["skuId"],
                "spu_id": str(candidate.get("spuId", "")),
                "title": str(candidate.get("title", "")),
                "shop_name": str(candidate.get("shopName", "")),
                "product_url": candidate["productUrl"],
                "image_url": str(candidate.get("image", "")),
                "authorized_spec_key": candidate["normalizedSpecKey"],
                "authorized_sales_count": candidate["salesCount"],
                "authorized_price_cents": candidate.get("priceCents"),
                "match_method": candidate.get("matchMethod"),
                "match_confidence": candidate.get("matchConfidence"),
                "model_version": candidate.get("modelVersion"),
                "fetched_at": candidate.get("fetchedAt"),
                "is_ad": False,
            }
        )
    return {
        "channel": "authorized_visual_service",
        "captured_at": str(captured_at).strip(),
        "page_url": f"{BRIDGE_ORIGIN}/api/similar-search",
        "candidates": candidates,
    }
