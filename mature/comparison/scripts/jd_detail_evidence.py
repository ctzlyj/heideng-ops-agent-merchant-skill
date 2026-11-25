import argparse
import json
import re
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from jd_price_adjustment import CatalogValidationError, normalize_size


class DetailEvidenceError(ValueError):
    pass


SKU_PATTERN = re.compile(r"\d{5,20}")
ALLOWED_DIMENSION_EVIDENCE = {
    "jd_visible_product_image",
    "jd_detail_specification",
    "user_confirmed_image",
}
ACCESSORY_ONLY_PATTERN = re.compile(r"^(?:密封圈)$")
JD_IMAGE_HOST_PATTERN = re.compile(r"img\d*\.(?:jd\.com|360buyimg\.com)")
NON_COMPARABLE_VARIANT_PATTERN = re.compile(r"(?:摆台|桌面摆件)")


def _sku_id(value: Any, field: str) -> str:
    text = str(value).strip()
    if not SKU_PATTERN.fullmatch(text):
        raise DetailEvidenceError(f"{field} must be a numeric JD SKU ID.")
    return text


def _timestamp(value: Any, field: str) -> str:
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise DetailEvidenceError(f"{field} must be an ISO-8601 timestamp.") from error
    return text


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise DetailEvidenceError("Detail response requires a real final price.") from error
    if amount <= 0 or amount.as_tuple().exponent < -2:
        raise DetailEvidenceError("Detail final price must be positive with at most two decimals.")
    return f"{amount:.2f}"


def normalize_dimensions(value: Any) -> str:
    try:
        return normalize_size(str(value))
    except CatalogValidationError as exc:
        raise DetailEvidenceError(f"Cannot normalize dimensions from {value!r}.") from exc


def normalize_jd_image_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("jfs/"):
        text = "https://img14.360buyimg.com/n1/" + text
    try:
        parsed = urlparse(text)
        _ = parsed.port
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not JD_IMAGE_HOST_PATTERN.fullmatch(hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return parsed.geturl()


def _request_context(envelope: dict[str, Any]) -> tuple[str, dict[str, str]]:
    url = str(envelope.get("url", ""))
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.hostname != "api.m.jd.com" or query.get("functionId") != [
        "pc_detailpage_wareBusiness"
    ]:
        raise DetailEvidenceError("Evidence is not pc_detailpage_wareBusiness.")
    try:
        request_body = json.loads(query["body"][0])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise DetailEvidenceError("Detail request body is missing or invalid.") from error
    requested_sku = _sku_id(request_body.get("skuId"), "request skuId")
    area = str(request_body.get("area", "")).strip()
    if not area:
        raise DetailEvidenceError("Detail request area is missing.")
    return requested_sku, {"area": area}


def _sku_matrix(color_size: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    groups = color_size.get("colorSizeList")
    if not isinstance(groups, list) or not groups:
        raise DetailEvidenceError("colorSizeList is missing or empty.")
    variants: dict[str, dict[str, Any]] = {}
    expected: set[str] = set()
    for group in groups:
        buttons = group.get("buttons") if isinstance(group, dict) else None
        if not isinstance(buttons, list) or not buttons:
            raise DetailEvidenceError("Each colorSizeList group requires buttons.")
        for button in buttons:
            if not isinstance(button, dict):
                raise DetailEvidenceError("Each specification button must be an object.")
            button_sku = _sku_id(button.get("skuId"), "button skuId")
            sku_list = button.get("skuList")
            if not isinstance(sku_list, list) or not sku_list:
                raise DetailEvidenceError(f"SKU button {button_sku} has no skuList.")
            members = {_sku_id(value, "button skuList") for value in sku_list}
            if button_sku not in members:
                raise DetailEvidenceError(f"SKU button {button_sku} is absent from its skuList.")
            expected.update(members)
            variants.setdefault(
                button_sku,
                {
                    "sku_id": button_sku,
                    "option_text": str(button.get("text", "")).strip(),
                    "image_path": str(button.get("fullImageUrl", "")).strip(),
                },
            )
    if not expected:
        raise DetailEvidenceError("No SKU IDs were enumerated from colorSizeList.")
    expected_ids = sorted(expected)
    for map_name in ("canAddCartMap", "stockInfo", "skuBatchPurchaseMap"):
        mapping = color_size.get(map_name)
        if not isinstance(mapping, dict):
            raise DetailEvidenceError(f"{map_name} is missing from detail evidence.")
        mapped_ids = {_sku_id(value, map_name) for value in mapping}
        if not set(expected_ids).issubset(mapped_ids):
            raise DetailEvidenceError(f"{map_name} disagrees with the SKU matrix.")
    return expected_ids, variants


def _raw_spec(ware: dict[str, Any]) -> str:
    raw_attributes = ware.get("sale_attributes")
    try:
        attributes = json.loads(raw_attributes) if isinstance(raw_attributes, str) else raw_attributes
    except json.JSONDecodeError as error:
        raise DetailEvidenceError("sale_attributes is invalid JSON.") from error
    values = []
    if isinstance(attributes, list):
        values = [
            str(item.get("saleValue", "")).strip()
            for item in attributes
            if isinstance(item, dict) and str(item.get("saleValue", "")).strip()
        ]
    raw_spec = " / ".join(values) or str(ware.get("color", "")).strip()
    if not raw_spec:
        raise DetailEvidenceError("Current SKU specification is missing.")
    return raw_spec


def _final_price(body: dict[str, Any]) -> tuple[str, str]:
    price_block = body.get("price")
    gather = body.get("warePriceGatherVO")
    if not isinstance(price_block, dict) or not isinstance(gather, dict):
        raise DetailEvidenceError("Detail response requires price evidence.")
    items = gather.get("priceItemList")
    if not isinstance(items, list):
        raise DetailEvidenceError("Detail price item list is missing.")
    final_value = price_block.get("finalPrice")
    if isinstance(final_value, dict) and final_value.get("price") not in (None, ""):
        price = _money(final_value["price"])
        matching = [
            _money(item.get("price"))
            for item in items
            if isinstance(item, dict) and item.get("priceType") == "finalPrice"
        ]
        if matching != [price]:
            raise DetailEvidenceError("Final-price fields are missing or contradictory.")
        return price, "finalPrice"
    subsidy_items = [
        item
        for item in items
        if isinstance(item, dict) and item.get("priceType") == "bybtPrice"
    ]
    if not subsidy_items:
        jd_items = [
            item
            for item in items
            if isinstance(item, dict) and item.get("priceType") == "jdPrice"
        ]
        promotion = body.get("promotion")
        government = body.get("govSupportInfo")
        best_promotion = body.get("bestPromotion")
        has_purchase_price = isinstance(best_promotion, dict) and best_promotion.get(
            "purchasePrice"
        ) not in (None, "")
        no_discount_scene = (
            len(items) == 1
            and len(jd_items) == 1
            and isinstance(promotion, dict)
            and not promotion.get("isBargain")
            and not str(promotion.get("prompt", "")).strip()
            and isinstance(government, dict)
            and not government.get("govSupport")
            and not government.get("govSubsidy")
            and not has_purchase_price
        )
        if not no_discount_scene:
            raise DetailEvidenceError("Detail response requires a real final price.")
        jd_price = _money(jd_items[0].get("price"))
        if _money(price_block.get("p")) != jd_price:
            raise DetailEvidenceError("JD-price fields are contradictory.")
        return jd_price, "jdPrice_no_discount"
    if len(subsidy_items) != 1:
        raise DetailEvidenceError("Detail response requires a real final price.")
    labels = subsidy_items[0].get("priceLabelList")
    label_text = " ".join(
        str(label.get("labelTxt", ""))
        for label in labels or []
        if isinstance(label, dict)
    )
    if "补贴价" not in label_text:
        raise DetailEvidenceError("Subsidy price lacks a visible price label.")
    subsidy_price = _money(subsidy_items[0].get("price"))
    if _money(price_block.get("p")) != subsidy_price:
        raise DetailEvidenceError("Visible subsidy-price fields are contradictory.")
    return subsidy_price, "bybtPrice"


def _dimension_record(
    sku_id: str, raw_spec: str, dimension_evidence: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    evidence = dimension_evidence.get(sku_id)
    if isinstance(evidence, dict) and evidence.get("classification") == "non_product_accessory":
        source = str(evidence.get("source", "")).strip()
        if source != "jd_sku_text" or not ACCESSORY_ONLY_PATTERN.fullmatch(
            raw_spec.strip()
        ):
            raise DetailEvidenceError(
                f"SKU {sku_id} accessory-only evidence contradicts its specification text."
            )
        return "", {
            "source": source,
            "classification": "non_product_accessory",
            "raw_spec": raw_spec,
            "captured_at": _timestamp(
                evidence.get("captured_at"), "accessory captured_at"
            ),
        }
    if isinstance(evidence, dict) and evidence.get("classification") == "non_comparable_variant":
        source = str(evidence.get("source", "")).strip()
        if source != "jd_sku_text" or not NON_COMPARABLE_VARIANT_PATTERN.search(
            raw_spec
        ):
            raise DetailEvidenceError(
                f"SKU {sku_id} non-comparable evidence contradicts its specification text."
            )
        record = {
            "source": source,
            "classification": "non_comparable_variant",
            "raw_spec": raw_spec,
            "captured_at": _timestamp(
                evidence.get("captured_at"), "non-comparable captured_at"
            ),
        }
        if str(evidence.get("note", "")).strip():
            record["note"] = str(evidence["note"]).strip()
        return "", record
    try:
        normalized = normalize_dimensions(raw_spec)
        return normalized, {"source": "jd_sku_text", "raw_spec": raw_spec}
    except DetailEvidenceError:
        if not isinstance(evidence, dict):
            raise DetailEvidenceError(
                f"SKU {sku_id} needs explicit dimension evidence because text has no size."
            )
        source = str(evidence.get("source", "")).strip()
        if source not in ALLOWED_DIMENSION_EVIDENCE:
            raise DetailEvidenceError(f"SKU {sku_id} has unsupported dimension evidence.")
        normalized = normalize_dimensions(evidence.get("normalized_spec", ""))
        captured_at = _timestamp(evidence.get("captured_at"), "dimension captured_at")
        record = {
            "source": source,
            "normalized_spec": normalized,
            "captured_at": captured_at,
        }
        for key in ("image_url", "local_image_path", "note"):
            if str(evidence.get(key, "")).strip():
                record[key] = str(evidence[key]).strip()
        return normalized, record


def parse_ware_business_envelope(
    envelope: dict[str, Any], dimension_evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise DetailEvidenceError("WebCLI detail evidence must be an object.")
    if envelope.get("method") != "GET" or envelope.get("status") != 200:
        raise DetailEvidenceError("Detail request did not complete with HTTP 200.")
    if "json" not in str(envelope.get("ct", "")).lower():
        raise DetailEvidenceError("Detail response is not JSON.")
    requested_sku, request_context = _request_context(envelope)
    body = envelope.get("body")
    if not isinstance(body, dict):
        raise DetailEvidenceError("Detail response body is missing.")
    page_config = body.get("pageConfigVO")
    ware = body.get("wareInfoReadMap")
    color_size = body.get("colorSizeVO")
    if not all(isinstance(value, dict) for value in (page_config, ware, color_size)):
        raise DetailEvidenceError("Detail response lacks SKU identity or matrix data.")
    current_sku = _sku_id(page_config.get("skuid"), "pageConfigVO.skuid")
    if requested_sku != current_sku:
        raise DetailEvidenceError("Requested SKU does not match the response SKU.")
    spu_id = str(ware.get("realSpuId", "")).strip()
    if not spu_id:
        raise DetailEvidenceError("Detail response has no proven SPU ID.")
    expected_sku_ids, variants = _sku_matrix(color_size)
    if current_sku not in expected_sku_ids:
        raise DetailEvidenceError("Current SKU is absent from the complete SKU matrix.")
    raw_spec = _raw_spec(ware)
    normalized_spec, dimension_record = _dimension_record(
        current_sku, raw_spec, dimension_evidence or {}
    )
    final_price, price_type = _final_price(body)
    captured_at = _timestamp(envelope.get("timestamp"), "detail timestamp")
    variant_evidence = variants.get(current_sku, {})
    variant_evidence = {**variant_evidence, "image_path": normalize_jd_image_url(variant_evidence.get("image_path"))}
    return {
        "spu_id": spu_id,
        "current_sku_id": current_sku,
        "main_sku_id": _sku_id(ware.get("main_sku_id"), "main_sku_id"),
        "expected_sku_ids": expected_sku_ids,
        "raw_spec": raw_spec,
        "normalized_spec": normalized_spec,
        "design": raw_spec,
        "title": str(ware.get("sku_name", "")).strip(),
        "final_price": final_price,
        "product_url": f"https://item.jd.com/{current_sku}.html",
        "captured_at": captured_at,
        "request_context": request_context,
        "price_scene": str(
            body.get("warePriceGatherVO", {})
            .get("priceScene", {})
            .get("priceScene", "")
        ).strip(),
        "dimension_evidence": dimension_record,
        "variant_evidence": variant_evidence,
        "image_url": normalize_jd_image_url(variant_evidence.get("image_path")),
        "price_evidence": {
            "source": "jd_detail_network",
            "price_type": price_type,
            "captured_at": captured_at,
            "product_url": f"https://item.jd.com/{current_sku}.html",
        },
    }


def build_product_catalog(
    envelopes: list[dict[str, Any]], dimension_evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(envelopes, list) or not envelopes:
        raise DetailEvidenceError("At least one SKU detail response is required.")
    records = [
        parse_ware_business_envelope(envelope, dimension_evidence)
        for envelope in envelopes
    ]
    first = records[0]
    expected = first["expected_sku_ids"]
    for record in records[1:]:
        if record["spu_id"] != first["spu_id"]:
            raise DetailEvidenceError("SKU responses belong to different SPUs.")
        if record["expected_sku_ids"] != expected:
            raise DetailEvidenceError("SKU responses disagree on the complete SKU set.")
        if record["request_context"] != first["request_context"]:
            raise DetailEvidenceError("SKU responses use different request contexts.")
        if record["price_scene"] != first["price_scene"]:
            raise DetailEvidenceError("SKU responses use different price scenes.")
    seen = [record["current_sku_id"] for record in records]
    duplicates = sorted({sku_id for sku_id in seen if seen.count(sku_id) > 1})
    if duplicates:
        raise DetailEvidenceError(f"Duplicate SKU responses: {', '.join(duplicates)}")
    missing = sorted(set(expected) - set(seen))
    extra = sorted(set(seen) - set(expected))
    if missing:
        raise DetailEvidenceError(f"Missing SKU responses: {', '.join(missing)}")
    if extra:
        raise DetailEvidenceError(f"Unexpected SKU responses: {', '.join(extra)}")
    indexed = {record["current_sku_id"]: record for record in records}
    sku_records = []
    for sku_id in expected:
        record = indexed[sku_id]
        sku_records.append(
            {
                "sku_id": sku_id,
                "design": record["design"],
                "raw_spec": record["raw_spec"],
                "normalized_spec": record["normalized_spec"],
                "final_price": record["final_price"],
                "product_url": record["product_url"],
                "captured_at": record["captured_at"],
                "dimension_evidence": record["dimension_evidence"],
                "price_evidence": record["price_evidence"],
            }
        )
    return {
        "status": "READY",
        "spu_id": first["spu_id"],
        "main_sku_id": first["main_sku_id"],
        "expected_sku_ids": expected,
        "request_context": first["request_context"],
        "price_scene": first["price_scene"],
        "sku_records": sku_records,
    }


def build_exact_spec_verification(
    catalog: dict[str, Any],
    source_spec: str,
    entry_sku_ids: list[str],
    selected_sku_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("status") != "READY":
        raise DetailEvidenceError("Only a READY complete catalog can be verified.")
    normalized_source = normalize_dimensions(source_spec)
    exact = [
        row
        for row in catalog.get("sku_records", [])
        if row.get("normalized_spec") == normalized_source
    ]
    if not exact:
        return {
            "status": "no_exact_size",
            "entry_sku_ids": sorted({_sku_id(value, "entry SKU") for value in entry_sku_ids}),
            "reason": f"No SKU has exact specification {normalized_source}.",
        }
    prices = {row["final_price"] for row in exact}
    selected = None
    if selected_sku_id is not None:
        selected_id = _sku_id(selected_sku_id, "selected SKU")
        selected = next((row for row in exact if row["sku_id"] == selected_id), None)
        if selected is None:
            raise DetailEvidenceError("Selected SKU is not an exact-spec candidate.")
    elif len(prices) > 1:
        return {
            "status": "ambiguous",
            "entry_sku_ids": sorted({_sku_id(value, "entry SKU") for value in entry_sku_ids}),
            "reason": "Exact-size SKUs have different prices; explicit AI selection is required.",
            "candidate_sku_ids": [row["sku_id"] for row in exact],
        }
    else:
        selected = exact[0]
    match_method = (
        "exact_size_explicit_override" if selected_sku_id is not None else "exact_size_uniform_price"
    )
    return {
        "status": "verified",
        "entry_sku_ids": sorted({_sku_id(value, "entry SKU") for value in entry_sku_ids}),
        "selected_sku_id": selected["sku_id"],
        "raw_spec": selected["raw_spec"],
        "normalized_spec": selected["normalized_spec"],
        "final_price": selected["final_price"],
        "match_method": match_method,
        "price_evidence": selected["price_evidence"],
    }


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _atomic_write_json(path: str, value: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            suffix=".json",
            dir=output.parent,
        ) as temporary:
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate JD pc_detailpage_wareBusiness SKU evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    catalog_parser = subparsers.add_parser("catalog")
    catalog_parser.add_argument("--responses", nargs="+", required=True)
    catalog_parser.add_argument("--dimension-evidence")
    catalog_parser.add_argument("--output", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--catalog", required=True)
    verify_parser.add_argument("--source-spec", required=True)
    verify_parser.add_argument("--entry-sku", action="append", required=True)
    verify_parser.add_argument("--selected-sku")
    verify_parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "catalog":
            evidence = (
                _read_json(arguments.dimension_evidence)
                if arguments.dimension_evidence
                else {}
            )
            result = build_product_catalog(
                [_read_json(path) for path in arguments.responses], evidence
            )
        else:
            result = build_exact_spec_verification(
                _read_json(arguments.catalog),
                arguments.source_spec,
                arguments.entry_sku,
                arguments.selected_sku,
            )
        _atomic_write_json(arguments.output, result)
    except (
        DetailEvidenceError,
        FileNotFoundError,
        OSError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"status": result["status"], "output": arguments.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
