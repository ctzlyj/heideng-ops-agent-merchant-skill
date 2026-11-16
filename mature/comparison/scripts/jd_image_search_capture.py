import argparse
import json
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from competitor_discovery import DiscoveryValidationError, normalize_jd_item_url


class ImageSearchCaptureError(ValueError):
    pass


RESULT_COUNT_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*(?:个商品)?\s*$")
SALES_PATTERN = re.compile(r"^\s*已售\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*$")


def _parse_count(value: Any, pattern: re.Pattern[str]) -> int | None:
    match = pattern.fullmatch(str(value or "").strip())
    if not match:
        return None
    try:
        amount = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if match.group(2):
        amount *= Decimal("10000")
    if amount < 0 or amount != amount.to_integral_value():
        return None
    return int(amount)


def parse_visible_sales(value: Any) -> int | None:
    return _parse_count(value, SALES_PATTERN)


def parse_declared_result_count(value: Any) -> int | None:
    return _parse_count(value, RESULT_COUNT_PATTERN)


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ImageSearchCaptureError(f"{field} must be a positive integer.")
    return value


def _captured_pages(value: Any, page_count: int) -> list[int]:
    if not isinstance(value, list):
        raise ImageSearchCaptureError("captured_pages must be a list.")
    pages = sorted(set(value))
    if any(not isinstance(page, int) or isinstance(page, bool) for page in pages):
        raise ImageSearchCaptureError("captured_pages must contain integers.")
    if any(page < 1 or page > page_count for page in pages):
        raise ImageSearchCaptureError("captured_pages contains an invalid page number.")
    return pages


def _candidate(card: dict[str, Any], captured_at: str) -> dict[str, Any]:
    sku_id = str(card.get("sku_id", "")).strip()
    if not sku_id.isdigit():
        raise ImageSearchCaptureError("Every image-search card requires a numeric SKU ID.")
    try:
        url_sku, product_url = normalize_jd_item_url(card.get("product_url", ""))
    except DiscoveryValidationError as error:
        raise ImageSearchCaptureError(str(error)) from error
    if url_sku != sku_id:
        raise ImageSearchCaptureError(
            f"Image-search card SKU/URL mismatch: {sku_id} != {url_sku}"
        )
    sales_text = str(card.get("sales_text", "")).strip()
    sales_lower_bound = parse_visible_sales(sales_text)
    if sales_text and sales_lower_bound is None:
        raise ImageSearchCaptureError(f"Unsupported visible sales text: {sales_text!r}")
    candidate = {
        "sku_id": sku_id,
        "spu_id": str(card.get("spu_id", "")).strip(),
        "title": str(card.get("title", "")).strip(),
        "shop_name": str(card.get("shop_name", "")).strip(),
        "product_url": product_url,
        "image_url": str(card.get("image_url", "")).strip(),
        "display_price": str(card.get("display_price", "")).strip(),
        "sales_text": sales_text,
        "views_text": str(card.get("views_text", "")).strip(),
        "is_ad": card.get("is_ad") is True,
        "page_number": _positive_integer(card.get("page_number"), "page_number"),
        "page_rank": _positive_integer(card.get("page_rank"), "page_rank"),
    }
    if sales_lower_bound is not None:
        candidate["sales_lower_bound"] = sales_lower_bound
        candidate["sales_evidence"] = {
            "source": "jd_visible_product_card",
            "sku_id": sku_id,
            "product_url": product_url,
            "captured_at": captured_at,
        }
    return candidate


def build_visible_search_capture(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ImageSearchCaptureError("Image-search capture input must be an object.")
    captured_at = str(document.get("captured_at", "")).strip()
    page_url = str(document.get("page_url", "")).strip()
    if not captured_at:
        raise ImageSearchCaptureError("captured_at is required.")
    if not page_url.startswith("https://jd-pc-search-image-pro.pf.jd.com/"):
        raise ImageSearchCaptureError("page_url must be the official JD image-search page.")
    if str(document.get("active_sort", "")).strip().casefold() != "sales":
        raise ImageSearchCaptureError("Confirmed sales sort is required.")

    page_count = _positive_integer(document.get("page_count"), "page_count")
    required_rank_window = _positive_integer(
        document.get("required_rank_window", 10), "required_rank_window"
    )
    captured_pages = _captured_pages(document.get("captured_pages"), page_count)
    cards = document.get("cards")
    if not isinstance(cards, list):
        raise ImageSearchCaptureError("cards must be a list.")

    candidates = []
    duplicate_sku_ids = []
    seen_sku_ids = set()
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            raise ImageSearchCaptureError("Every image-search card must be an object.")
        candidate = _candidate(raw_card, captured_at)
        if candidate["page_number"] not in captured_pages:
            raise ImageSearchCaptureError(
                f"Card page {candidate['page_number']} was not declared as captured."
            )
        if candidate["sku_id"] in seen_sku_ids:
            duplicate_sku_ids.append(candidate["sku_id"])
            continue
        seen_sku_ids.add(candidate["sku_id"])
        candidates.append(candidate)

    candidates.sort(key=lambda item: (item["page_number"], item["page_rank"]))
    all_pages_captured = captured_pages == list(range(1, page_count + 1))
    visible_sales_count = sum(
        1 for candidate in candidates if "sales_lower_bound" in candidate
    )
    missing_sales_sku_ids = [
        candidate["sku_id"]
        for candidate in candidates
        if "sales_lower_bound" not in candidate
    ]
    rank_window_complete = (
        len(candidates) >= required_rank_window and not duplicate_sku_ids
    )
    declared_result_text = str(document.get("declared_result_text", "")).strip()
    declared_result_lower_bound = parse_declared_result_count(declared_result_text)
    declared_result_is_exact = bool(declared_result_text) and "+" not in declared_result_text
    result_set_complete = (
        all_pages_captured
        and declared_result_is_exact
        and declared_result_lower_bound == len(candidates)
        and not duplicate_sku_ids
    )
    return {
        "channel": "jd_visible_image_search",
        "captured_at": captured_at,
        "page_url": page_url,
        "capture_audit": {
            "active_sort": "sales",
            "declared_result_text": declared_result_text,
            "declared_result_lower_bound": declared_result_lower_bound,
            "page_count": page_count,
            "captured_pages": captured_pages,
            "all_pages_captured": all_pages_captured,
            "result_set_complete": result_set_complete,
            "visible_candidate_count": len(candidates),
            "visible_sales_count": visible_sales_count,
            "required_rank_window": required_rank_window,
            "rank_window_complete": rank_window_complete,
            "sales_evidence_complete": not missing_sales_sku_ids,
            "missing_sales_sku_ids": missing_sales_sku_ids,
            "duplicate_sku_ids": sorted(set(duplicate_sku_ids)),
        },
        "candidates": candidates,
    }


def _response_sales_text(ware: dict[str, Any]) -> str:
    floor = ware.get("commentSalesFloor")
    if not isinstance(floor, list):
        raise ImageSearchCaptureError("commentSalesFloor must be a list.")
    visible = [
        str(item.get("text", "")).strip()
        for item in floor
        if isinstance(item, dict)
        and str(item.get("attr", "")).strip() == "totalSales"
        and str(item.get("text", "")).strip()
    ]
    if len(visible) > 1:
        raise ImageSearchCaptureError("A card contains duplicate totalSales floors.")
    total_sales = str(ware.get("totalSales", "")).strip()
    sales_text = visible[0] if visible else ""
    if bool(total_sales) != bool(sales_text):
        raise ImageSearchCaptureError(
            "totalSales and the visible totalSales floor must appear together."
        )
    if total_sales and sales_text != f"已售{total_sales}":
        raise ImageSearchCaptureError(
            "totalSales does not match the visible product-card sales text."
        )
    return sales_text


def _response_candidate(
    ware: dict[str, Any],
    captured_at: str,
    api_page: int,
    api_page_rank: int,
    api_rank: int,
) -> dict[str, Any]:
    sku_id = str(ware.get("skuId", "")).strip()
    sales_text = _response_sales_text(ware)
    card = {
        "sku_id": sku_id,
        "spu_id": "",
        "title": str(ware.get("wareName", "")).strip(),
        "shop_name": str(ware.get("shopName", "")).strip(),
        "product_url": f"https://item.jd.com/{sku_id}.html",
        "image_url": (
            f"https://img10.360buyimg.com/n2/s480x480_{str(ware.get('imageurl', '')).strip()}"
            if str(ware.get("imageurl", "")).strip()
            else ""
        ),
        "display_price": str(ware.get("jdPrice", "")).strip(),
        "sales_text": sales_text,
        "views_text": next(
            (
                str(item.get("text", "")).strip()
                for item in ware.get("commentSalesFloor", [])
                if isinstance(item, dict)
                and str(item.get("attr", "")).strip() == "d30ItemUvDesc"
            ),
            "",
        ),
        "is_ad": str(ware.get("isAdv", "0")).strip() not in {"", "0"},
        "page_number": api_page,
        "page_rank": api_page_rank,
    }
    candidate = _candidate(card, captured_at)
    candidate["api_page"] = api_page
    candidate["api_page_rank"] = api_page_rank
    candidate["api_rank"] = api_rank
    return candidate


def build_visible_search_capture_from_responses(
    document: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ImageSearchCaptureError("Image-search response input must be an object.")
    captured_at = str(document.get("captured_at", "")).strip()
    page_url = str(document.get("page_url", "")).strip()
    function_id = str(document.get("function_id", "")).strip()
    if not captured_at:
        raise ImageSearchCaptureError("captured_at is required.")
    if not page_url.startswith("https://jd-pc-search-image-pro.pf.jd.com/"):
        raise ImageSearchCaptureError("page_url must be the official JD image-search page.")
    if function_id != "pc_search_image_search":
        raise ImageSearchCaptureError("Unsupported image-search function_id.")
    required_rank_window = _positive_integer(
        document.get("required_rank_window", 10), "required_rank_window"
    )
    request_responses = document.get("request_responses")
    if not isinstance(request_responses, list) or not request_responses:
        raise ImageSearchCaptureError("request_responses must be a non-empty list.")

    page_records: dict[int, dict[str, Any]] = {}
    expected_contract: tuple[int, int, str] | None = None
    for envelope in request_responses:
        if not isinstance(envelope, dict):
            raise ImageSearchCaptureError("Each response envelope must be an object.")
        request_body = envelope.get("request_body")
        response = envelope.get("response")
        if not isinstance(request_body, dict) or not isinstance(response, dict):
            raise ImageSearchCaptureError(
                "Each response envelope requires request_body and response objects."
            )
        if str(request_body.get("psort", "")).strip() != "3":
            raise ImageSearchCaptureError("Every response must use sales sort psort=3.")
        if response.get("code") != 0:
            raise ImageSearchCaptureError("Image-search response code must be 0.")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ImageSearchCaptureError("Image-search response data must be an object.")
        page_info = data.get("pageInfo")
        ware_list = data.get("wareList")
        if not isinstance(page_info, dict) or not isinstance(ware_list, list):
            raise ImageSearchCaptureError(
                "Image-search response requires pageInfo and wareList."
            )
        if str((data.get("selceted") or {}).get("sort", "")).strip() != "3":
            raise ImageSearchCaptureError("Response does not confirm sales sort.")
        page = _positive_integer(request_body.get("page"), "request page")
        response_page = _positive_integer(page_info.get("page"), "response page")
        if page != response_page or page != _positive_integer(data.get("page"), "data page"):
            raise ImageSearchCaptureError("Request and response page numbers disagree.")
        if page in page_records:
            raise ImageSearchCaptureError(f"Duplicate response for API page {page}.")
        page_count = _positive_integer(page_info.get("pageCount"), "pageCount")
        page_size = _positive_integer(page_info.get("pageSize"), "pageSize")
        result_count = _positive_integer(page_info.get("resultCount"), "resultCount")
        result_fuzzy_count = str(page_info.get("resultFuzzyCount", "")).strip()
        contract = (page_count, page_size, result_fuzzy_count)
        if expected_contract is None:
            expected_contract = contract
        elif contract != expected_contract:
            raise ImageSearchCaptureError("Image-search page contracts disagree.")
        expected_start = 1 + (page - 1) * page_size
        if request_body.get("s") != expected_start:
            raise ImageSearchCaptureError(
                f"API page {page} must start at result position {expected_start}."
            )
        page_records[page] = {
            "ware_list": ware_list,
            "page_count": page_count,
            "page_size": page_size,
            "result_count": result_count,
            "result_fuzzy_count": result_fuzzy_count,
        }

    first_record = next(iter(page_records.values()))
    page_count = first_record["page_count"]
    page_size = first_record["page_size"]
    result_count = first_record["result_count"]
    if any(record["result_count"] != result_count for record in page_records.values()):
        raise ImageSearchCaptureError("Image-search result counts disagree.")
    captured_api_pages = sorted(page_records)
    all_api_pages_captured = captured_api_pages == list(range(1, page_count + 1))

    candidates = []
    duplicate_sku_ids = []
    seen_sku_ids = set()
    for page in captured_api_pages:
        ware_list = page_records[page]["ware_list"]
        expected_rows = min(page_size, max(result_count - (page - 1) * page_size, 0))
        if len(ware_list) != expected_rows:
            all_api_pages_captured = False
        for page_index, ware in enumerate(ware_list, start=1):
            if not isinstance(ware, dict):
                raise ImageSearchCaptureError("Every wareList item must be an object.")
            api_rank = (page - 1) * page_size + page_index
            candidate = _response_candidate(
                ware, captured_at, page, page_index, api_rank
            )
            if candidate["sku_id"] in seen_sku_ids:
                duplicate_sku_ids.append(candidate["sku_id"])
                continue
            seen_sku_ids.add(candidate["sku_id"])
            candidates.append(candidate)

    result_set_complete = (
        all_api_pages_captured
        and not duplicate_sku_ids
        and len(candidates) == result_count
    )
    missing_sales_sku_ids = [
        candidate["sku_id"]
        for candidate in candidates
        if "sales_lower_bound" not in candidate
    ]
    return {
        "channel": "jd_visible_image_search",
        "captured_at": captured_at,
        "page_url": page_url,
        "capture_audit": {
            "active_sort": "sales",
            "sort_code": "3",
            "function_id": function_id,
            "declared_result_text": first_record["result_fuzzy_count"],
            "declared_result_lower_bound": parse_declared_result_count(
                first_record["result_fuzzy_count"]
            ),
            "result_count": result_count,
            "api_page_count": page_count,
            "api_page_size": page_size,
            "captured_api_pages": captured_api_pages,
            "all_api_pages_captured": all_api_pages_captured,
            "result_set_complete": result_set_complete,
            "visible_candidate_count": len(candidates),
            "visible_sales_count": len(candidates) - len(missing_sales_sku_ids),
            "required_rank_window": required_rank_window,
            "rank_window_complete": (
                result_set_complete and len(candidates) >= required_rank_window
            ),
            "sales_evidence_complete": not missing_sales_sku_ids,
            "missing_sales_sku_ids": missing_sales_sku_ids,
            "duplicate_sku_ids": sorted(set(duplicate_sku_ids)),
        },
        "candidates": candidates,
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            suffix=".json",
            dir=path.parent,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize and audit visible JD image-search cards."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--input", required=True)
    build_parser.add_argument("--output", required=True)
    response_parser = commands.add_parser("build-responses")
    response_parser.add_argument("--input", required=True)
    response_parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        document = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        capture = (
            build_visible_search_capture_from_responses(document)
            if arguments.command == "build-responses"
            else build_visible_search_capture(document)
        )
        _write_json_atomic(Path(arguments.output), capture)
    except (
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
