#!/usr/bin/env python3
"""Validate JD SKU evidence, match catalogs, and invert promotional prices."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


CENT = Decimal("0.01")
TARGET_GAP = Decimal("0.10")


class CatalogValidationError(ValueError):
    pass


class MatchReviewRequiredError(ValueError):
    pass


class PriceInversionError(ValueError):
    pass


@dataclass(frozen=True)
class FinalPriceCalculation:
    jd_price: Decimal
    direct_reduction: Decimal
    government_subsidy: Decimal
    final_price: Decimal


@dataclass(frozen=True)
class PricePlan:
    competitor_price: Decimal
    target_gap: Decimal
    target_final_price: Decimal
    jd_price: Decimal
    direct_reduction: Decimal
    government_subsidy: Decimal
    final_price: Decimal
    final_difference: Decimal


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_rate(value: str | Decimal) -> Decimal:
    rate = Decimal(str(value))
    if rate > 1:
        rate /= 100
    if rate < 0 or rate >= 1:
        raise ValueError("Rates must be at least 0 and less than 100 percent.")
    return rate


def parse_target_gap(value: str | Decimal) -> Decimal:
    try:
        target_gap = round_money(Decimal(str(value)))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Target gap must be a non-negative money amount.") from error
    if target_gap < 0:
        raise ValueError("Target gap must be a non-negative money amount.")
    return target_gap


def normalize_size(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).lower()
    patterns = (
        r"宽\s*(\d+)\s*(?:厘米|cm)?\s*(?:[x×*]|[-_/，, ])*\s*高?\s*(\d+)\s*(?:厘米|cm)?",
        r"(\d+)\s*[x×*]\s*(\d+)\s*(?:厘米|cm)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return f"{int(match.group(1))}x{int(match.group(2))}"
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:厘米|cm)", text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}cm"
    match = re.search(r"(\d+(?:\.\d+)?)\s*件套", text)
    if match:
        return f"{match.group(1)}件套"
    match = re.search(r"(\d+(?:\.\d+)?)\s*支", text)
    if match:
        return f"{match.group(1)}支"
    raise CatalogValidationError(f"Cannot normalize size: {value!r}")


def exact_dimensions(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"\s+", "", text).replace("毫米", "mm").replace("厘米", "cm")
    match = re.fullmatch(r"宽(\d+(?:\.\d+)?(?:cm|mm)?)\s*[-×x*]?高(\d+(?:\.\d+)?(?:cm|mm)?)", text)
    if match:
        text = "x".join(match.groups())
    parts = re.split(r"[x×*]", text)
    axes = [re.fullmatch(r"(\d+(?:\.\d+)?)(mm|cm|m|寸|件套|支)?", part) for part in parts]
    if not all(axes) or (len(parts) == 1 and not axes[0].group(2)):
        raise CatalogValidationError(f"Cannot normalize size: {value!r}")
    numbers = [format(Decimal(axis.group(1)).normalize(), 'f') for axis in axes]
    units = [axis.group(2) or '' for axis in axes]
    # Only a trailing unit applies to the complete tuple. Never assume cm.
    if all(unit in ('', units[-1]) for unit in units) and (all(units) or not any(units[:-1])):
        return 'x'.join(numbers) + units[-1]
    return 'x'.join(number + unit for number, unit in zip(numbers, units))


def canonical_spec(value: str) -> str:
    """Total spec-grouping key: parsed dimension when possible, exact variant value otherwise."""

    text = '' if value is None else str(value).strip()
    if not text:
        raise CatalogValidationError("Missing sale specification")
    if text.startswith("variant:"):
        return text
    try:
        return exact_dimensions(text)
    except CatalogValidationError:
        return "variant:" + text


def normalize_design(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"^\s*\d+\s*[.、:_-]?\s*", "", text)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()


def design_similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, normalize_design(left), normalize_design(right)).ratio(), 4)


def calculate_final_price(jd_price: Decimal, direct_rate: Decimal, subsidy_rate: Decimal) -> FinalPriceCalculation:
    jd_price = round_money(Decimal(jd_price))
    direct_rate = parse_rate(direct_rate)
    subsidy_rate = parse_rate(subsidy_rate)
    direct_reduction = round_money(jd_price * direct_rate)
    government_subsidy = round_money(jd_price * (Decimal("1") - direct_rate) * subsidy_rate)
    final_price = round_money(jd_price - direct_reduction - government_subsidy)
    return FinalPriceCalculation(jd_price, direct_reduction, government_subsidy, final_price)


def create_price_plan(
    competitor_price: Decimal,
    direct_rate: Decimal,
    subsidy_rate: Decimal,
    target_gap: Decimal = TARGET_GAP,
) -> PricePlan:
    competitor_price = round_money(Decimal(competitor_price))
    direct_rate = parse_rate(direct_rate)
    subsidy_rate = parse_rate(subsidy_rate)
    target_gap = parse_target_gap(target_gap)
    target = round_money(competitor_price - target_gap)
    if target <= 0:
        raise PriceInversionError("Target gap leaves no positive target final price.")
    net_rate = Decimal("1") - direct_rate - ((Decimal("1") - direct_rate) * subsidy_rate)
    if net_rate <= 0:
        raise PriceInversionError("Combined discount rates leave no positive payable rate.")

    center_cents = int((target / net_rate * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    solutions: list[FinalPriceCalculation] = []
    for cents in range(max(1, center_cents - 1000), center_cents + 1001):
        calculation = calculate_final_price(Decimal(cents) / 100, direct_rate, subsidy_rate)
        if calculation.final_price == target:
            solutions.append(calculation)
    if not solutions:
        raise PriceInversionError(f"No two-decimal JD price produces target final price {target}.")

    best = max(solutions, key=lambda item: item.jd_price)
    return PricePlan(
        competitor_price=competitor_price,
        target_gap=target_gap,
        target_final_price=target,
        jd_price=best.jd_price,
        direct_reduction=best.direct_reduction,
        government_subsidy=best.government_subsidy,
        final_price=best.final_price,
        final_difference=round_money(best.final_price - competitor_price),
    )


def validate_competitor_catalog(expected_sku_ids: list[str], competitor_skus: list[dict[str, Any]]) -> None:
    expected = [str(value).strip() for value in expected_sku_ids]
    actual = [str(row.get("sku_id", "")).strip() for row in competitor_skus]
    if not expected:
        raise CatalogValidationError("The competitor page SKU list is empty.")
    if len(expected) != len(set(expected)):
        raise CatalogValidationError("The expected competitor SKU list contains duplicates.")
    if len(actual) != len(set(actual)):
        raise CatalogValidationError("Fetched competitor SKU records contain duplicates.")
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise CatalogValidationError(f"Competitor SKU evidence is incomplete. missing={missing}, extra={extra}")

    for row in competitor_skus:
        sku_id = str(row.get("sku_id", "")).strip()
        for field in ("design", "size", "price", "url"):
            if row.get(field) in (None, ""):
                raise CatalogValidationError(f"Competitor SKU {sku_id} is missing {field}.")
        canonical_spec(str(row["size"]))
        if Decimal(str(row["price"])) <= 0:
            raise CatalogValidationError(f"Competitor SKU {sku_id} has a non-positive price.")


def _select_candidate(
    own: dict[str, Any], candidates: list[dict[str, Any]], overrides: dict[str, str]
) -> tuple[dict[str, Any], str, float]:
    prices = {round_money(Decimal(str(candidate["price"]))) for candidate in candidates}
    ranked = sorted(
        candidates,
        key=lambda candidate: (-design_similarity(str(own.get("design", "")), str(candidate.get("design", ""))), str(candidate["sku_id"])),
    )
    if len(prices) == 1:
        selected = ranked[0]
        return selected, "exact_size_uniform_price", design_similarity(str(own.get("design", "")), str(selected.get("design", "")))

    own_sku = str(own["sku_id"])
    selected_sku = str(overrides.get(own_sku, "")).strip()
    if not selected_sku:
        options = [
            {
                "sku_id": str(candidate["sku_id"]),
                "design": str(candidate["design"]),
                "price": format(round_money(Decimal(str(candidate["price"]))), ".2f"),
                "similarity": design_similarity(str(own.get("design", "")), str(candidate.get("design", ""))),
            }
            for candidate in ranked
        ]
        raise MatchReviewRequiredError(
            f"AI review is required for own SKU {own_sku}; same-size candidates have different prices: "
            + json.dumps(options, ensure_ascii=False)
        )
    selected = next((candidate for candidate in candidates if str(candidate["sku_id"]) == selected_sku), None)
    if selected is None:
        raise MatchReviewRequiredError(f"Override {selected_sku} is not an exact-size candidate for own SKU {own_sku}.")
    return selected, "ai_reviewed_design_match", design_similarity(str(own.get("design", "")), str(selected.get("design", "")))


def plan_catalog(
    own_skus: list[dict[str, Any]],
    competitor_skus: list[dict[str, Any]],
    direct_rate: Decimal,
    subsidy_rate: Decimal,
    overrides: dict[str, str],
    target_gap: Decimal = TARGET_GAP,
) -> list[dict[str, Any]]:
    if not own_skus:
        raise CatalogValidationError("The merchant SKU list is empty.")
    own_ids = [str(row.get("sku_id", "")).strip() for row in own_skus]
    if any(not sku_id for sku_id in own_ids) or len(own_ids) != len(set(own_ids)):
        raise CatalogValidationError("Merchant SKUID values must be present and unique.")

    by_size: dict[str, list[dict[str, Any]]] = {}
    for competitor in competitor_skus:
        by_size.setdefault(canonical_spec(competitor["size"]), []).append(competitor)

    output: list[dict[str, Any]] = []
    for own in own_skus:
        own_size = canonical_spec(own.get("size", ""))
        candidates = by_size.get(own_size, [])
        if not candidates:
            raise CatalogValidationError(f"No exact-size competitor candidate for own SKU {own['sku_id']} ({own_size}).")
        selected, match_method, similarity = _select_candidate(own, candidates, overrides)
        price_plan = create_price_plan(
            Decimal(str(selected["price"])),
            direct_rate,
            subsidy_rate,
            target_gap=target_gap,
        )
        current_price = round_money(Decimal(str(own["current_final_price"])))
        output.append(
            {
                "my_sku": str(own["sku_id"]),
                "my_design": str(own.get("design", "")),
                "my_size": own_size,
                "current_final_price": format(current_price, ".2f"),
                "competitor_sku": str(selected["sku_id"]),
                "competitor_design": str(selected.get("design", "")),
                "competitor_size": canonical_spec(selected["size"]),
                "competitor_price": format(price_plan.competitor_price, ".2f"),
                "target_gap": format(price_plan.target_gap, ".2f"),
                "competitor_url": str(selected["url"]),
                "match_method": match_method,
                "design_similarity": f"{similarity:.4f}",
                "direct_rate": format(parse_rate(direct_rate), ".4f"),
                "subsidy_rate": format(parse_rate(subsidy_rate), ".4f"),
                "target_final_price": format(price_plan.target_final_price, ".2f"),
                "recommended_jd_price": format(price_plan.jd_price, ".2f"),
                "direct_reduction_amount": format(price_plan.direct_reduction, ".2f"),
                "government_subsidy_amount": format(price_plan.government_subsidy, ".2f"),
                "calculated_final_price": format(price_plan.final_price, ".2f"),
                "final_difference": format(price_plan.final_difference, ".2f"),
            }
        )
    return output


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command_plan(arguments: argparse.Namespace) -> int:
    source = _load_json(Path(arguments.input))
    overrides = _load_json(Path(arguments.overrides)) if arguments.overrides else {}
    validate_competitor_catalog(source.get("expected_competitor_sku_ids", []), source.get("competitor_skus", []))
    plans = plan_catalog(
        source.get("own_skus", []),
        source.get("competitor_skus", []),
        parse_rate(arguments.direct_rate),
        parse_rate(arguments.subsidy_rate),
        overrides,
        parse_target_gap(arguments.target_gap),
    )
    output_dir = Path(arguments.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "comparison_rows.json", plans)
    _write_json(
        output_dir / "upload_rows.json",
        [{"SKUID": row["my_sku"], "京东价": row["recommended_jd_price"]} for row in plans],
    )
    print(json.dumps({"rows": len(plans), "output_dir": str(output_dir)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Validate evidence and generate comparison/upload JSON rows.")
    plan.add_argument("--input", required=True, help="Input catalog JSON path.")
    plan.add_argument("--direct-rate", required=True, help="Direct reduction rate, e.g. 15 or 0.15.")
    plan.add_argument("--subsidy-rate", required=True, help="Government subsidy rate, e.g. 15 or 0.15.")
    plan.add_argument("--target-gap", default="0.10", help="Current-run final-price gap below the competitor; defaults to 0.10.")
    plan.add_argument("--overrides", help="AI-reviewed own-SKU to competitor-SKU mapping JSON.")
    plan.add_argument("--output-dir", required=True, help="Directory for validated JSON outputs.")
    plan.set_defaults(handler=command_plan)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        return arguments.handler(arguments)
    except (CatalogValidationError, MatchReviewRequiredError, PriceInversionError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
