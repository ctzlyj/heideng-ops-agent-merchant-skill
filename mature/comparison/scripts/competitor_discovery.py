import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any


class DiscoveryValidationError(ValueError):
    pass


JD_ITEM_PATTERN = re.compile(r"^https://item\.jd\.com/(\d+)\.html(?:[?#].*)?$")
ALLOWED_CHANNELS = {
    "jd_visible_image_search",
    "jd_title_search",
    "authorized_visual_service",
}
ALLOWED_SOURCE_SPU_EVIDENCE = {"jd_visible_page", "jd_detail_network"}


def normalize_jd_item_url(value: str) -> tuple[str, str]:
    match = JD_ITEM_PATTERN.match(str(value).strip())
    if not match:
        raise DiscoveryValidationError(f"Not a JD item URL: {value!r}")
    sku_id = match.group(1)
    return sku_id, f"https://item.jd.com/{sku_id}.html"


def _explicit_rules(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rules = []
    for item in value:
        rule = str(item).strip()
        if rule and rule not in rules:
            rules.append(rule)
    return rules


def _source_spu_evidence(source: dict[str, Any]) -> dict[str, Any]:
    evidence = source.get("spu_evidence")
    source_sku = str(source.get("sku_id", "")).strip()
    source_spu = str(source.get("spu_id", "")).strip()
    proven = (
        isinstance(evidence, dict)
        and str(evidence.get("source", "")).strip() in ALLOWED_SOURCE_SPU_EVIDENCE
        and str(evidence.get("sku_id", "")).strip() == source_sku
        and str(evidence.get("spu_id", "")).strip() == source_spu
        and bool(str(evidence.get("captured_at", "")).strip())
        and bool(source_spu)
    )
    return {
        "proven": proven,
        "source": str(evidence.get("source", "")).strip()
        if isinstance(evidence, dict)
        else "",
    }


def validate_capture_document(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or not isinstance(document.get("source"), dict):
        raise DiscoveryValidationError("Discovery input requires a source object.")
    source = document["source"]
    for field in ("spu_id", "sku_id", "title", "shop_name"):
        if not str(source.get(field, "")).strip():
            raise DiscoveryValidationError(f"Source is missing {field}.")
    source_sku, _ = normalize_jd_item_url(source.get("product_url", ""))
    if source_sku != str(source["sku_id"]).strip():
        raise DiscoveryValidationError(
            f"Source SKU/URL mismatch: {source['sku_id']} != {source_sku}"
        )
    if not isinstance(document.get("captures"), list) or not document["captures"]:
        raise DiscoveryValidationError("Discovery input requires at least one capture.")


def _exclusion_reason(
    source: dict[str, Any], own_shops: set[str], candidate: dict[str, Any]
) -> str | None:
    if candidate.get("is_ad") is True:
        return "advertisement"
    candidate_sku = str(candidate.get("sku_id", "")).strip()
    candidate_spu = str(candidate.get("spu_id", "")).strip()
    if candidate_sku == str(source["sku_id"]) or candidate_spu == str(source["spu_id"]):
        return "source_product"
    if str(candidate.get("shop_name", "")).strip().casefold() in own_shops:
        return "own_shop"
    return None


def _merge_candidate(
    current: dict[str, Any] | None, observation: dict[str, Any]
) -> dict[str, Any]:
    if current is None:
        display_prices = []
        if observation.get("display_price") not in (None, ""):
            display_prices.append(
                {
                    "value": observation["display_price"],
                    "captured_at": observation["captured_at"],
                    "channel": observation["channel"],
                }
            )
        return {
            "sku_id": observation["sku_id"],
            "spu_id": observation.get("spu_id", ""),
            "title": observation.get("title", ""),
            "shop_name": observation.get("shop_name", ""),
            "product_url": observation["product_url"],
            "image_url": observation.get("image_url", ""),
            "local_image_path": observation.get("local_image_path", ""),
            "source_channels": [observation["channel"]],
            "observations": [observation],
            "display_price_observations": display_prices,
        }
    current["observations"].append(observation)
    current["source_channels"] = sorted(
        set(current["source_channels"] + [observation["channel"]])
    )
    if observation.get("display_price") not in (None, ""):
        current["display_price_observations"].append(
            {
                "value": observation["display_price"],
                "captured_at": observation["captured_at"],
                "channel": observation["channel"],
            }
        )
    return current


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
    review = row.get("ai_review") or {}
    ai_priority = (
        0
        if review.get("decision") == "same" and review.get("confidence") == "high"
        else 1
    )
    image_score = row.get("image_score") or {}
    similarity = float(image_score.get("combined_similarity", -1))
    sales_values = [
        int(observation["sales_lower_bound"])
        for observation in row.get("observations", [])
        if isinstance(observation.get("sales_lower_bound"), int)
        and observation["sales_lower_bound"] >= 0
    ]
    maximum_sales_lower_bound = max(sales_values, default=-1)
    return ai_priority, -similarity, -maximum_sales_lower_bound, str(row["sku_id"])


def build_candidate_report(
    document: dict[str, Any],
    image_scores: dict[str, dict[str, Any]],
    ai_reviews: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    validate_capture_document(document)
    source = document["source"]
    configured_own_shop_names = [
        str(value).strip()
        for value in document.get("own_shop_names", [])
        if str(value).strip()
    ]
    own_shops = {
        str(value).strip().casefold()
        for value in configured_own_shop_names + [source["shop_name"]]
        if str(value).strip()
    }
    eligible_by_sku: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    capture_audits: list[dict[str, Any]] = []
    for capture in document["captures"]:
        if not isinstance(capture, dict):
            raise DiscoveryValidationError("Each discovery capture must be an object.")
        channel = str(capture.get("channel", "")).strip()
        if channel not in ALLOWED_CHANNELS:
            raise DiscoveryValidationError(f"Unsupported discovery channel: {channel!r}")
        captured_at = str(capture.get("captured_at", "")).strip()
        page_url = str(capture.get("page_url", "")).strip()
        candidates = capture.get("candidates", [])
        if not isinstance(candidates, list):
            raise DiscoveryValidationError("Capture candidates must be a list.")
        capture_audit = capture.get("capture_audit")
        if capture_audit is not None:
            if not isinstance(capture_audit, dict):
                raise DiscoveryValidationError("capture_audit must be an object.")
            capture_audits.append(
                {
                    "channel": channel,
                    "captured_at": captured_at,
                    "page_url": page_url,
                    **capture_audit,
                }
            )
        for raw in candidates:
            if not isinstance(raw, dict):
                raise DiscoveryValidationError("Each candidate must be an object.")
            declared_sku = str(raw.get("sku_id", "")).strip()
            url_sku, normalized_url = normalize_jd_item_url(raw.get("product_url", ""))
            if declared_sku != url_sku:
                raise DiscoveryValidationError(
                    f"Candidate SKU/URL mismatch: {declared_sku} != {url_sku}"
                )
            observation = dict(raw)
            observation.update(
                {
                    "product_url": normalized_url,
                    "channel": channel,
                    "captured_at": captured_at,
                    "page_url": page_url,
                }
            )
            reason = _exclusion_reason(source, own_shops, observation)
            if reason:
                rejected.append(
                    {
                        "sku_id": declared_sku,
                        "reason": reason,
                        "observation": observation,
                    }
                )
                continue
            eligible_by_sku[declared_sku] = _merge_candidate(
                eligible_by_sku.get(declared_sku), observation
            )
    eligible = []
    for sku_id, row in eligible_by_sku.items():
        row["image_score"] = image_scores.get(sku_id)
        row["ai_review"] = ai_reviews.get(sku_id)
        eligible.append(row)
    eligible.sort(key=_candidate_sort_key)
    return {
        "source": source,
        "own_shop_filter": {
            "configured": bool(configured_own_shop_names),
            "shop_name_count": len(set(configured_own_shop_names)),
        },
        "source_spu_evidence": _source_spu_evidence(source),
        "capture_audits": capture_audits,
        "eligible_candidates": eligible,
        "rejected_candidates": rejected,
    }


def validate_selection(
    report: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    source = report["source"]
    if str(selection.get("own_spu_id", "")) != str(source["spu_id"]):
        raise DiscoveryValidationError(
            "Selection own_spu_id does not match the discovery source."
        )
    selected_sku = str(selection.get("competitor_sku_id", "")).strip()
    selected = next(
        (
            row
            for row in report["eligible_candidates"]
            if row["sku_id"] == selected_sku
        ),
        None,
    )
    if selected is None:
        raise DiscoveryValidationError("Selected competitor is not an eligible candidate.")
    if str(selection.get("competitor_spu_id", "")) != str(selected.get("spu_id", "")):
        raise DiscoveryValidationError(
            "Selected competitor SPU does not match candidate evidence."
        )
    confirmed_by = str(selection.get("confirmed_by", "")).strip()
    if confirmed_by not in {"user", "ai"}:
        raise DiscoveryValidationError("confirmed_by must be user or ai.")
    if confirmed_by == "ai":
        review = selected.get("ai_review") or {}
        if review.get("decision") != "same" or review.get("confidence") != "high":
            raise DiscoveryValidationError(
                "AI-only selection requires a high-confidence same-product review."
            )
        rules = _explicit_rules(review.get("evidence_rules"))
        verification_ref = str(review.get("verification_ref", "")).strip()
    else:
        rules = _explicit_rules(selection.get("confirmation_rules"))
        verification_ref = str(selection.get("verification_ref", "")).strip()
    if len(rules) < 2:
        raise DiscoveryValidationError(
            "Same-product selection requires at least two explicit evidence rules."
        )
    if not verification_ref:
        raise DiscoveryValidationError(
            "Same-product selection requires a non-sensitive verification_ref."
        )
    return {
        "own_spu_id": str(source["spu_id"]),
        "competitor_spu_id": str(selected.get("spu_id", "")),
        "competitor_sku_id": selected["sku_id"],
        "competitor_url": selected["product_url"],
        "confirmed_by": confirmed_by,
        "confirmation_note": str(selection.get("confirmation_note", "")).strip(),
        "confirmation_rules": rules,
        "verification_ref": verification_ref,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
    parser = argparse.ArgumentParser(description="Validate JD competitor discovery evidence.")
    commands = parser.add_subparsers(dest="command", required=True)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("--captures", required=True)
    report_parser.add_argument("--image-scores", required=True)
    report_parser.add_argument("--ai-reviews", required=True)
    report_parser.add_argument("--output", required=True)
    select_parser = commands.add_parser("select")
    select_parser.add_argument("--report", required=True)
    select_parser.add_argument("--selection", required=True)
    select_parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "report":
            result = build_candidate_report(
                _load_json(Path(arguments.captures)),
                _load_json(Path(arguments.image_scores)),
                _load_json(Path(arguments.ai_reviews)),
            )
        else:
            result = validate_selection(
                _load_json(Path(arguments.report)),
                _load_json(Path(arguments.selection)),
            )
        _write_json_atomic(Path(arguments.output), result)
    except (
        DiscoveryValidationError,
        FileNotFoundError,
        OSError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
