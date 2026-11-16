import argparse
import json
import re
import tempfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from competitor_discovery import DiscoveryValidationError, normalize_jd_item_url


class MarketAnalysisError(ValueError):
    pass


VERIFICATION_STATUSES = {"verified", "no_exact_size", "blocked", "ambiguous"}
SALES_EVIDENCE_SOURCE = "jd_visible_product_card"
OFFICIAL_RANKING_BASIS = "jd_official_sales_sort_rank_psort_3"
OFFICIAL_RANKING_LABEL = "京东官方销量排序位次（psort=3）"
VISIBLE_SALES_RANKING_BASIS = "jd_visible_sales_lower_bound"
VISIBLE_SALES_RANKING_LABEL = "京东页面可见销量下限"


def _add_issue(issues: list[dict[str, Any]], code: str, **details: Any) -> None:
    if any(issue.get("code") == code for issue in issues):
        return
    issues.append({"code": code, **details})


def _explicit_rules(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rules = []
    for item in value:
        rule = str(item).strip()
        if rule and rule not in rules:
            rules.append(rule)
    return rules


def _valid_sales_evidence(observation: dict[str, Any]) -> bool:
    evidence = observation.get("sales_evidence")
    if not isinstance(evidence, dict):
        return False
    sku_id = str(observation.get("sku_id", "")).strip()
    if str(evidence.get("source", "")).strip() != SALES_EVIDENCE_SOURCE:
        return False
    if str(evidence.get("sku_id", "")).strip() != sku_id:
        return False
    if not str(evidence.get("captured_at", "")).strip():
        return False
    try:
        url_sku, _ = normalize_jd_item_url(evidence.get("product_url", ""))
    except DiscoveryValidationError:
        return False
    return url_sku == sku_id


def _sales_evidence(
    observations: list[dict[str, Any]],
) -> tuple[int | None, str, dict[str, Any] | None]:
    declared = [
        observation
        for observation in observations
        if isinstance(observation.get("sales_lower_bound"), int)
        and not isinstance(observation.get("sales_lower_bound"), bool)
        and observation["sales_lower_bound"] >= 0
    ]
    if any(not _valid_sales_evidence(observation) for observation in declared):
        return None, "", None
    usable = [observation for observation in declared if _valid_sales_evidence(observation)]
    if not usable:
        return None, "", None
    best = max(usable, key=lambda item: item["sales_lower_bound"])
    return (
        best["sales_lower_bound"],
        str(best.get("sales_text", "")),
        dict(best["sales_evidence"]),
    )


def _has_invalid_declared_sales(observations: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(observation.get("sales_lower_bound"), int)
        and not isinstance(observation.get("sales_lower_bound"), bool)
        and observation["sales_lower_bound"] >= 0
        and not _valid_sales_evidence(observation)
        for observation in observations
        if isinstance(observation, dict)
    )


def _review_has_explicit_evidence(review: dict[str, Any]) -> bool:
    return len(_explicit_rules(review.get("evidence_rules"))) >= 2 and bool(
        str(review.get("verification_ref", "")).strip()
    )


def _same_product_decision(group: dict[str, Any], verification: dict[str, Any]) -> str:
    if verification.get("confirmed_by") == "user" and isinstance(
        verification.get("same_product"), bool
    ):
        if not verification["same_product"]:
            return "different"
        if len(_explicit_rules(verification.get("confirmation_rules"))) < 2 or not str(
            verification.get("verification_ref", "")
        ).strip():
            return "insufficient"
        return "same"
    high_decisions = {
        review.get("decision")
        for review in group["ai_reviews"]
        if isinstance(review, dict) and review.get("confidence") == "high"
    }
    if high_decisions == {"same"}:
        return (
            "same"
            if any(
                _review_has_explicit_evidence(review)
                for review in group["ai_reviews"]
                if isinstance(review, dict)
                and review.get("decision") == "same"
                and review.get("confidence") == "high"
            )
            else "insufficient"
        )
    if high_decisions == {"different"}:
        return "different"
    return "unresolved"


def _merge_by_spu(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    sku_to_spu: dict[str, str] = {}
    for row in candidates:
        if not isinstance(row, dict):
            raise MarketAnalysisError("Each discovery candidate must be an object.")
        sku_id = str(row.get("sku_id", "")).strip()
        spu_id = str(row.get("spu_id", "")).strip()
        if not sku_id:
            raise MarketAnalysisError("Each market candidate requires a SKU ID.")
        if not spu_id:
            review = row.get("ai_review") or {}
            if review.get("decision") == "different" and review.get("confidence") == "high":
                continue
            spu_id = f"missing-spu:{sku_id}"
        previous_spu = sku_to_spu.get(sku_id)
        if previous_spu is not None and previous_spu != spu_id:
            raise MarketAnalysisError(f"Candidate SKU {sku_id} belongs to conflicting SPUs.")
        sku_to_spu[sku_id] = spu_id
        if spu_id not in grouped:
            grouped[spu_id] = {
                "spu_id": "" if spu_id.startswith("missing-spu:") else spu_id,
                "missing_spu": spu_id.startswith("missing-spu:"),
                "entry_sku_ids": [],
                "title": str(row.get("title", "")),
                "shop_name": str(row.get("shop_name", "")),
                "product_url": str(row.get("product_url", "")),
                "source_channels": [],
                "observations": [],
                "display_price_observations": [],
                "image_scores": [],
                "ai_reviews": [],
            }
        group = grouped[spu_id]
        group["entry_sku_ids"].append(sku_id)
        group["source_channels"].extend(row.get("source_channels", []))
        group["observations"].extend(row.get("observations", []))
        group["display_price_observations"].extend(
            row.get("display_price_observations", [])
        )
        if isinstance(row.get("image_score"), dict):
            group["image_scores"].append(row["image_score"])
        if isinstance(row.get("ai_review"), dict):
            group["ai_reviews"].append(row["ai_review"])
    merged = []
    for group in grouped.values():
        group["entry_sku_ids"] = sorted(set(group["entry_sku_ids"]))
        group["source_channels"] = sorted(set(group["source_channels"]))
        (
            group["sales_lower_bound"],
            group["sales_text"],
            group["sales_evidence"],
        ) = _sales_evidence(group["observations"])
        group["sales_evidence_invalid"] = _has_invalid_declared_sales(
            group["observations"]
        )
        official_api_ranks = [
            observation.get("api_rank")
            for observation in group["observations"]
            if isinstance(observation, dict)
            and observation.get("channel") == "jd_visible_image_search"
            and isinstance(observation.get("api_rank"), int)
            and not isinstance(observation.get("api_rank"), bool)
            and observation["api_rank"] > 0
        ]
        group["official_api_rank"] = min(official_api_ranks, default=None)
        group["image_score"] = max(
            group["image_scores"],
            key=lambda value: float(value.get("combined_similarity", -1)),
            default=None,
        )
        group["ai_review"] = next(
            (
                review
                for review in group["ai_reviews"]
                if review.get("decision") == "same"
                and review.get("confidence") == "high"
            ),
            group["ai_reviews"][0] if group["ai_reviews"] else None,
        )
        merged.append(group)
    merged.sort(
        key=lambda group: (
            group["sales_lower_bound"] is None,
            -(group["sales_lower_bound"] or 0),
            group["entry_sku_ids"][0],
        )
    )
    return merged


def _has_trusted_official_rank_window(
    discovery_report: dict[str, Any], top_limit: int
) -> bool:
    for audit in discovery_report.get("capture_audits", []):
        if not isinstance(audit, dict):
            continue
        required_rank_window = audit.get("required_rank_window")
        if (
            audit.get("channel") == "jd_visible_image_search"
            and str(audit.get("active_sort", "")).strip().casefold() == "sales"
            and str(audit.get("sort_code", "")).strip() == "3"
            and audit.get("result_set_complete") is True
            and audit.get("rank_window_complete") is True
            and isinstance(required_rank_window, int)
            and not isinstance(required_rank_window, bool)
            and required_rank_window >= top_limit
        ):
            return True
    return False


def _validate_verified(
    source_spec: str, spu_id: str, verification: dict[str, Any]
) -> dict[str, Any]:
    selected_sku = str(verification.get("selected_sku_id", "")).strip()
    normalized_spec = str(verification.get("normalized_spec", "")).strip()
    if not selected_sku or normalized_spec != source_spec:
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} does not contain an exact source specification."
        )
    price_text = str(verification.get("final_price", "")).strip()
    if not re.fullmatch(r"\d+\.\d{2}", price_text):
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} requires a positive two-decimal final_price."
        )
    try:
        price = Decimal(price_text)
    except InvalidOperation as error:
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} has invalid final_price."
        ) from error
    if price <= 0:
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} requires a positive final_price."
        )
    evidence = verification.get("price_evidence")
    if not isinstance(evidence, dict):
        raise MarketAnalysisError(f"Verified SPU {spu_id} is missing price evidence.")
    if not str(evidence.get("source", "")).strip() or not str(
        evidence.get("captured_at", "")
    ).strip():
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} has incomplete price evidence."
        )
    try:
        url_sku, normalized_url = normalize_jd_item_url(
            evidence.get("product_url", "")
        )
    except DiscoveryValidationError as error:
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} has an invalid price evidence URL."
        ) from error
    if url_sku != selected_sku:
        raise MarketAnalysisError(
            f"Verified SPU {spu_id} selected SKU does not match its evidence URL."
        )
    result = dict(verification)
    result["final_price"] = format(price, ".2f")
    result["price_evidence"] = dict(evidence)
    result["price_evidence"]["product_url"] = normalized_url
    return result


def build_market_report(
    discovery_report: dict[str, Any],
    verifications: dict[str, dict[str, Any]],
    top_limit: int = 10,
) -> dict[str, Any]:
    if not isinstance(discovery_report, dict) or not isinstance(
        discovery_report.get("source"), dict
    ):
        raise MarketAnalysisError("Market analysis requires a discovery source.")
    if not isinstance(verifications, dict):
        raise MarketAnalysisError("Product verifications must be an object.")
    if not isinstance(top_limit, int) or isinstance(top_limit, bool) or top_limit <= 0:
        raise MarketAnalysisError("top_limit must be a positive integer.")
    source = discovery_report["source"]
    source_spec = str(source.get("normalized_spec", "")).strip()
    if not source_spec:
        raise MarketAnalysisError("Discovery source is missing normalized_spec.")
    candidates = discovery_report.get("eligible_candidates")
    if not isinstance(candidates, list):
        raise MarketAnalysisError("Discovery report is missing eligible_candidates.")

    issues: list[dict[str, Any]] = []
    preflight_blocking_reasons: list[dict[str, Any]] = []
    for audit in discovery_report.get("capture_audits", []):
        if not isinstance(audit, dict):
            raise MarketAnalysisError("Each capture audit must be an object.")
        if str(audit.get("channel", "")).strip() != "jd_visible_image_search":
            continue
        if audit.get("result_set_complete") is False:
            _add_issue(
                issues,
                "DISCOVERY_RESULT_SET_INCOMPLETE",
                declared_result_text=audit.get("declared_result_text"),
                visible_candidate_count=audit.get("visible_candidate_count"),
            )
            preflight_blocking_reasons.append(
                {
                    "spu_id": "",
                    "status": "partial",
                    "reason": "discovery_result_set_incomplete",
                }
            )
        if audit.get("rank_window_complete") is not True:
            _add_issue(
                issues,
                "DISCOVERY_RANK_WINDOW_INCOMPLETE",
                required_rank_window=audit.get("required_rank_window"),
                visible_candidate_count=audit.get("visible_candidate_count"),
            )
            preflight_blocking_reasons.append(
                {
                    "spu_id": "",
                    "status": "partial",
                    "reason": "discovery_rank_window_incomplete",
                }
            )
    own_shop_filter = discovery_report.get("own_shop_filter")
    if not isinstance(own_shop_filter, dict) or own_shop_filter.get("configured") is not True:
        _add_issue(issues, "OWN_SHOP_FILTER_NOT_CONFIGURED")
        preflight_blocking_reasons.append(
            {
                "spu_id": "",
                "status": "action_required",
                "reason": "own_shop_filter_not_configured",
            }
        )
    source_spu_evidence = discovery_report.get("source_spu_evidence")
    if (
        not str(source.get("spu_id", "")).strip()
        or not isinstance(source_spu_evidence, dict)
        or source_spu_evidence.get("proven") is not True
    ):
        _add_issue(issues, "SOURCE_SPU_UNPROVEN")
        preflight_blocking_reasons.append(
            {
                "spu_id": str(source.get("spu_id", "")).strip(),
                "status": "blocked",
                "reason": "source_spu_unproven",
            }
        )

    grouped = _merge_by_spu(candidates)
    same_products = []
    ranked_decisions = []
    for group in grouped:
        if group.get("missing_spu"):
            ranked_decisions.append(("missing_spu", group))
            continue
        verification = verifications.get(group["spu_id"], {})
        if not isinstance(verification, dict):
            raise MarketAnalysisError(
                f"Verification for SPU {group['spu_id']} must be an object."
            )
        decision = _same_product_decision(group, verification)
        if decision == "different":
            continue
        if decision == "unresolved":
            ranked_decisions.append((decision, group))
            continue
        if decision == "insufficient":
            ranked_decisions.append((decision, group))
            continue
        status = str(verification.get("status", "missing")).strip() or "missing"
        if status not in VERIFICATION_STATUSES and status != "missing":
            raise MarketAnalysisError(
                f"Unsupported verification status for SPU {group['spu_id']}: {status}"
            )
        item = {
            "spu_id": group["spu_id"],
            "entry_sku_ids": group["entry_sku_ids"],
            "representative_sku_id": group["entry_sku_ids"][0],
            "title": group["title"],
            "shop_name": group["shop_name"],
            "product_url": group["product_url"],
            "sales_text": group["sales_text"] or "京东未展示",
            "sales_lower_bound": group["sales_lower_bound"],
            "sales_evidence": group["sales_evidence"],
            "sales_evidence_invalid": group["sales_evidence_invalid"],
            "official_api_rank": group["official_api_rank"],
            "source_channels": group["source_channels"],
            "display_price_observations": group["display_price_observations"],
            "image_score": group["image_score"],
            "ai_review": group["ai_review"],
            "verification_status": status,
            "failure_reason": str(verification.get("reason", "")).strip(),
        }
        same_products.append(item)
        ranked_decisions.append((decision, item))

    top_rows = []
    blocking_reasons = list(preflight_blocking_reasons)
    trusted_rank_window = _has_trusted_official_rank_window(
        discovery_report, top_limit
    )
    if trusted_rank_window:
        ranked_decisions = [
            (decision, item)
            for decision, item in ranked_decisions
            if isinstance(item.get("official_api_rank"), int)
        ]
        ranked_decisions.sort(key=lambda row: row[1]["official_api_rank"])
        same_products.sort(
            key=lambda item: (
                not isinstance(item.get("official_api_rank"), int),
                item.get("official_api_rank") or 0,
            )
        )
        ranking_basis = OFFICIAL_RANKING_BASIS
        ranking_label = OFFICIAL_RANKING_LABEL
    else:
        ranking_basis = VISIBLE_SALES_RANKING_BASIS
        ranking_label = VISIBLE_SALES_RANKING_LABEL
        for decision, item in ranked_decisions:
            if decision == "same" and item.get("verification_status") == "no_exact_size":
                continue
            if item["sales_lower_bound"] is None or item["sales_evidence"] is None:
                _add_issue(
                    issues,
                    "PAGE_SALES_EVIDENCE_REQUIRED",
                    spu_id=item.get("spu_id", ""),
                )
                blocking_reasons.append(
                    {
                        "spu_id": item.get("spu_id", ""),
                        "status": "partial",
                        "reason": "page_sales_evidence_required",
                    }
                )
                break

    for decision, item in ranked_decisions:
        if len(top_rows) >= top_limit:
            break
        if decision == "missing_spu":
            _add_issue(issues, "SPU_EVIDENCE_MISSING")
            blocking_reasons.append(
                {
                    "spu_id": "",
                    "entry_sku_ids": item["entry_sku_ids"],
                    "status": "unresolved",
                    "reason": "spu_evidence_missing",
                }
            )
            break
        if decision == "insufficient":
            _add_issue(issues, "SAME_PRODUCT_EVIDENCE_INSUFFICIENT")
            blocking_reasons.append(
                {
                    "spu_id": item["spu_id"],
                    "status": "unresolved",
                    "reason": "same_product_evidence_insufficient",
                }
            )
            break
        if decision == "unresolved":
            _add_issue(issues, "SAME_PRODUCT_DECISION_UNRESOLVED")
            blocking_reasons.append(
                {
                    "spu_id": item["spu_id"],
                    "status": "unresolved",
                    "reason": "same_product_decision_unresolved",
                }
            )
            break
        verification = verifications.get(item["spu_id"], {})
        status = item["verification_status"]
        if status == "no_exact_size":
            continue
        if status != "verified":
            _add_issue(
                issues,
                "SKU_VERIFICATION_INCOMPLETE",
                spu_id=item["spu_id"],
                verification_status=status,
            )
            blocking_reasons.append(
                {
                    "spu_id": item["spu_id"],
                    "status": status,
                    "reason": item["failure_reason"] or "verification_incomplete",
                }
            )
            break
        if (
            item["sales_evidence_invalid"]
            or (
                not trusted_rank_window
                and (item["sales_lower_bound"] is None or item["sales_evidence"] is None)
            )
        ):
            _add_issue(
                issues,
                "PAGE_SALES_EVIDENCE_REQUIRED",
                spu_id=item["spu_id"],
            )
            blocking_reasons.append(
                {
                    "spu_id": item["spu_id"],
                    "status": "partial",
                    "reason": "page_sales_evidence_required",
                }
            )
            break
        verified = _validate_verified(source_spec, item["spu_id"], verification)
        top_rows.append(
            {
                "rank": len(top_rows) + 1,
                "spu_id": item["spu_id"],
                "entry_sku_ids": item["entry_sku_ids"],
                "selected_sku_id": verified["selected_sku_id"],
                "raw_spec": str(verified.get("raw_spec", "")),
                "normalized_spec": verified["normalized_spec"],
                "final_price": verified["final_price"],
                "sales_text": item["sales_text"],
                "sales_lower_bound": item["sales_lower_bound"],
                "sales_evidence": item["sales_evidence"],
                "official_api_rank": item["official_api_rank"],
                "ranking_basis": ranking_basis,
                "ranking_label": ranking_label,
                "match_method": str(verified.get("match_method", "")),
                "price_evidence": verified["price_evidence"],
                "product_url": verified["price_evidence"]["product_url"],
            }
        )

    issue_codes = {issue["code"] for issue in issues}
    if "OWN_SHOP_FILTER_NOT_CONFIGURED" in issue_codes:
        status = "ACTION_REQUIRED"
        minimum = None
        average = None
    elif issue_codes and issue_codes <= {
        "DISCOVERY_RESULT_SET_INCOMPLETE",
        "DISCOVERY_RANK_WINDOW_INCOMPLETE",
        "PAGE_SALES_EVIDENCE_REQUIRED",
    }:
        status = "PARTIAL"
        minimum = None
        average = None
    elif blocking_reasons:
        status = "BLOCKED"
        minimum = None
        average = None
    elif not top_rows:
        status = "PARTIAL"
        minimum = None
        average = None
    else:
        status = "READY"
        prices = [Decimal(row["final_price"]) for row in top_rows]
        minimum = format(
            min(prices).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"
        )
        average = format(
            (sum(prices) / Decimal(len(prices))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            ".2f",
        )

    if status != "READY":
        top_rows = []

    return {
        "status": status,
        "ranking_basis": ranking_basis,
        "ranking_label": ranking_label,
        "source": source,
        "same_product_list": same_products,
        "top_same_spec": top_rows,
        "statistics": {
            "candidate_count": len(candidates),
            "same_product_count": len(same_products),
            "sample_count": len(top_rows),
            "top_limit": top_limit,
            "minimum_final_price": minimum,
            "average_final_price": average,
        },
        "blocking_reasons": blocking_reasons,
        "issues": issues,
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
    parser = argparse.ArgumentParser(description="Build an exact-spec JD market report.")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--discovery", required=True)
    build_parser.add_argument("--verifications", required=True)
    build_parser.add_argument("--top-limit", type=int, default=10)
    build_parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        discovery = json.loads(Path(arguments.discovery).read_text(encoding="utf-8"))
        verifications = json.loads(
            Path(arguments.verifications).read_text(encoding="utf-8")
        )
        report = build_market_report(discovery, verifications, arguments.top_limit)
        _write_json_atomic(Path(arguments.output), report)
    except (
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output, "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
