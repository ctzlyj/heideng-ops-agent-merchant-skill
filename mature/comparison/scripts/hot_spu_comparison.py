#!/usr/bin/env python3
"""Compare every SKU in one own SPU with one fixed hot competitor SPU."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

try:
    from .jd_price_adjustment import TARGET_GAP, parse_target_gap
except ImportError:
    from jd_price_adjustment import TARGET_GAP, parse_target_gap


SKU_PATTERN = re.compile(r"\d{5,20}")
PRICE_QUANTUM = Decimal("0.01")

COMPARISON_HEADERS = [
    "自有SPU",
    "自有SKU",
    "自有规格",
    "自有标准化尺寸",
    "自有当前到手价",
    "热卖竞品官方销量位次",
    "热卖竞品SPU",
    "热卖同款对应SKU",
    "热卖同款对应规格",
    "热卖同款对应SKU到手价",
    "本轮目标差价",
    "建议目标到手价",
    "自有价-热卖同款价",
    "匹配状态",
    "匹配方式",
    "自有商品链接",
    "热卖同款商品链接",
    "自有价格证据时间",
    "竞品价格证据时间",
]

COMPETITOR_HEADERS = [
    "热卖竞品SPU",
    "竞品SKU",
    "竞品规格",
    "标准化尺寸",
    "真实到手价",
    "商品链接",
    "图片链接",
    "价格证据来源",
    "价格证据时间",
]


class ComparisonError(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _price(value: Any) -> Decimal:
    try:
        price = Decimal(_text(value)).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as error:
        raise ComparisonError("CATALOG_PRICE_INVALID") from error
    if price < 0:
        raise ComparisonError("CATALOG_PRICE_INVALID")
    return price


def _price_text(value: Decimal) -> str:
    return f"{value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP):.2f}"


def _validate_catalog(catalog: Any) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("status") != "READY":
        raise ComparisonError("CATALOG_NOT_READY")
    if catalog.get("capture_context_consistent") is False:
        raise ComparisonError("CATALOG_CONTEXT_INCONSISTENT")
    spu_id = _text(catalog.get("spu_id"))
    expected = catalog.get("expected_sku_ids")
    records = catalog.get("sku_records")
    if not spu_id or not isinstance(expected, list) or not expected or not isinstance(records, list):
        raise ComparisonError("CATALOG_INCOMPLETE")
    expected_ids = [_text(value) for value in expected]
    if any(not SKU_PATTERN.fullmatch(value) for value in expected_ids):
        raise ComparisonError("CATALOG_INCOMPLETE")
    if len(expected_ids) != len(set(expected_ids)):
        raise ComparisonError("CATALOG_INCOMPLETE")

    clean_records: list[dict[str, Any]] = []
    observed_ids: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise ComparisonError("CATALOG_INCOMPLETE")
        sku_id = _text(record.get("sku_id"))
        normalized_spec = _text(record.get("normalized_spec"))
        product_url = _text(record.get("product_url"))
        evidence = record.get("price_evidence")
        if (
            not SKU_PATTERN.fullmatch(sku_id)
            or not normalized_spec
            or product_url != f"https://item.jd.com/{sku_id}.html"
            or not isinstance(evidence, dict)
            or evidence.get("source") != "jd_detail_network"
        ):
            raise ComparisonError("CATALOG_INCOMPLETE")
        price = _price(record.get("final_price"))
        observed_ids.append(sku_id)
        clean_records.append(
            {
                **record,
                "sku_id": sku_id,
                "normalized_spec": normalized_spec,
                "final_price": _price_text(price),
                "product_url": product_url,
                "captured_at": _text(record.get("captured_at") or evidence.get("captured_at")),
            }
        )
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != set(expected_ids):
        raise ComparisonError("CATALOG_INCOMPLETE")
    by_id = {record["sku_id"]: record for record in clean_records}
    return {
        "spu_id": spu_id,
        "expected_sku_ids": expected_ids,
        "sku_records": [by_id[sku_id] for sku_id in expected_ids],
    }


def build_comparison(
    source_catalog: dict[str, Any],
    competitor_catalog: dict[str, Any],
    official_rank: int,
    overrides: dict[str, str] | None = None,
    target_gap: Decimal = TARGET_GAP,
) -> dict[str, Any]:
    source = _validate_catalog(source_catalog)
    competitor = _validate_catalog(competitor_catalog)
    if not isinstance(official_rank, int) or isinstance(official_rank, bool) or official_rank < 1:
        raise ComparisonError("OFFICIAL_RANK_INVALID")
    try:
        target_gap = parse_target_gap(target_gap)
    except ValueError as error:
        raise ComparisonError("TARGET_GAP_INVALID") from error
    clean_overrides = {_text(key): _text(value) for key, value in (overrides or {}).items()}
    competitor_by_id = {row["sku_id"]: row for row in competitor["sku_records"]}
    competitor_by_spec: dict[str, list[dict[str, Any]]] = {}
    for row in competitor["sku_records"]:
        competitor_by_spec.setdefault(row["normalized_spec"], []).append(row)

    rows: list[dict[str, Any]] = []
    for own in source["sku_records"]:
        matches = competitor_by_spec.get(own["normalized_spec"], [])
        selected: dict[str, Any] | None = None
        match_status = "NO_EXACT_SIZE"
        match_method = "strict_dimension_no_match"
        override_sku = clean_overrides.get(own["sku_id"])
        if override_sku:
            selected = competitor_by_id.get(override_sku)
            if selected is None or selected["normalized_spec"] != own["normalized_spec"]:
                raise ComparisonError("SKU_OVERRIDE_INVALID")
            match_status = "MATCHED"
            match_method = "explicit_own_to_competitor_override"
        elif len(matches) == 1:
            selected = matches[0]
            match_status = "MATCHED"
            match_method = "strict_dimension_unique"
        elif len(matches) > 1:
            prices = {row["final_price"] for row in matches}
            if len(prices) > 1:
                raise ComparisonError("SKU_OVERRIDE_REQUIRED")
            selected = sorted(matches, key=lambda row: row["sku_id"])[0]
            match_status = "MATCHED"
            match_method = "strict_dimension_same_price"

        own_price = _price(own["final_price"])
        competitor_price = _price(selected["final_price"]) if selected else None
        suggested_target = competitor_price - target_gap if competitor_price is not None else None
        if suggested_target is not None and suggested_target <= 0:
            raise ComparisonError("TARGET_GAP_EXCEEDS_PRICE")
        difference = own_price - competitor_price if competitor_price is not None else None
        rows.append(
            {
                "own_spu_id": source["spu_id"],
                "own_sku_id": own["sku_id"],
                "own_design": _text(own.get("raw_spec") or own.get("design")),
                "own_normalized_spec": own["normalized_spec"],
                "own_final_price": _price_text(own_price),
                "official_sales_rank": official_rank,
                "hot_competitor_spu_id": competitor["spu_id"],
                "hot_competitor_sku_id": selected["sku_id"] if selected else "",
                "hot_competitor_design": _text(selected.get("raw_spec") or selected.get("design")) if selected else "",
                "hot_competitor_normalized_spec": selected["normalized_spec"] if selected else "",
                "hot_competitor_final_price": _price_text(competitor_price) if competitor_price is not None else "",
                "target_gap": _price_text(target_gap),
                "suggested_target_final_price": _price_text(suggested_target) if suggested_target is not None else "",
                "final_price_difference": _price_text(difference) if difference is not None else "",
                "match_status": match_status,
                "match_method": match_method,
                "own_product_url": own["product_url"],
                "hot_competitor_product_url": selected["product_url"] if selected else "",
                "own_price_captured_at": own["captured_at"],
                "hot_competitor_price_captured_at": selected["captured_at"] if selected else "",
            }
        )

    capture_times = [
        row["captured_at"]
        for row in source["sku_records"] + competitor["sku_records"]
        if row["captured_at"]
    ]
    return {
        "status": "READY",
        "mode": "hot_spu_comparison",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_spu_id": source["spu_id"],
        "hot_competitor_spu_id": competitor["spu_id"],
        "official_sales_rank": official_rank,
        "target_gap": _price_text(target_gap),
        "source_sku_count": len(source["sku_records"]),
        "hot_competitor_sku_count": len(competitor["sku_records"]),
        "matched_count": sum(row["match_status"] == "MATCHED" for row in rows),
        "unmatched_count": sum(row["match_status"] != "MATCHED" for row in rows),
        "evidence_captured_at": max(capture_times) if capture_times else "",
        "evidence_source": "jd_detail_network",
        "rows": rows,
        "hot_competitor_sku_records": competitor["sku_records"],
        "upload_workbook_generated": False,
    }


def _style_sheet(sheet: Any) -> None:
    header_fill = PatternFill("solid", fgColor="E1251B")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in range(1, sheet.max_column + 1):
        width = min(
            50,
            max(12, max(len(str(sheet.cell(row=row, column=column).value or "")) for row in range(1, sheet.max_row + 1)) + 2),
        )
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _as_number(value: Any) -> float | None:
    return float(value) if _text(value) else None


def build_workbook(comparison: dict[str, Any], output: Path | str) -> None:
    if not isinstance(comparison, dict) or comparison.get("status") != "READY":
        raise ComparisonError("COMPARISON_NOT_READY")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()

    sheet = workbook.active
    sheet.title = "SKU比价"
    sheet.append(COMPARISON_HEADERS)
    for row in comparison.get("rows", []):
        sheet.append(
            [
                row.get("own_spu_id"),
                row.get("own_sku_id"),
                row.get("own_design"),
                row.get("own_normalized_spec"),
                _as_number(row.get("own_final_price")),
                row.get("official_sales_rank"),
                row.get("hot_competitor_spu_id"),
                row.get("hot_competitor_sku_id"),
                row.get("hot_competitor_design"),
                _as_number(row.get("hot_competitor_final_price")),
                _as_number(row.get("target_gap")),
                _as_number(row.get("suggested_target_final_price")),
                _as_number(row.get("final_price_difference")),
                row.get("match_status"),
                row.get("match_method"),
                row.get("own_product_url"),
                row.get("hot_competitor_product_url"),
                row.get("own_price_captured_at"),
                row.get("hot_competitor_price_captured_at"),
            ]
        )
        for column, label in ((16, "查看自有商品"), (17, "查看热卖同款")):
            cell = sheet.cell(sheet.max_row, column)
            if cell.value:
                target = cell.value
                cell.value = label
                cell.hyperlink = target
                cell.style = "Hyperlink"
        for column in (5, 10, 11, 12, 13):
            sheet.cell(sheet.max_row, column).number_format = "0.00"
    _style_sheet(sheet)

    competitor_sheet = workbook.create_sheet("热卖竞品完整SKU")
    competitor_sheet.append(COMPETITOR_HEADERS)
    for row in comparison.get("hot_competitor_sku_records", []):
        evidence = row.get("price_evidence") or {}
        competitor_sheet.append(
            [
                comparison.get("hot_competitor_spu_id"),
                row.get("sku_id"),
                row.get("raw_spec") or row.get("design"),
                row.get("normalized_spec"),
                _as_number(row.get("final_price")),
                row.get("product_url"),
                row.get("image_url"),
                evidence.get("source"),
                row.get("captured_at") or evidence.get("captured_at"),
            ]
        )
        competitor_sheet.cell(competitor_sheet.max_row, 5).number_format = "0.00"
        for column, label in ((6, "查看商品"), (7, "查看图片")):
            cell = competitor_sheet.cell(competitor_sheet.max_row, column)
            if cell.value:
                target = cell.value
                cell.value = label
                cell.hyperlink = target
                cell.style = "Hyperlink"
    _style_sheet(competitor_sheet)

    summary_sheet = workbook.create_sheet("核验摘要")
    summary_sheet.append(["核验项", "结果"])
    for label, value in [
        ("运行状态", comparison.get("status")),
        ("运行模式", "热卖单款SPU比价"),
        ("自有SPU", comparison.get("source_spu_id")),
        ("自有SKU数", comparison.get("source_sku_count")),
        ("热卖竞品SPU", comparison.get("hot_competitor_spu_id")),
        ("热卖竞品官方销量位次", comparison.get("official_sales_rank")),
        ("默认/本轮目标差价", comparison.get("target_gap")),
        ("改价状态", "仅给出建议目标价；未进入改价阶段"),
        ("热卖竞品完整SKU数", comparison.get("hot_competitor_sku_count")),
        ("严格尺寸匹配数", comparison.get("matched_count")),
        ("无相同尺寸数", comparison.get("unmatched_count")),
        ("价格证据来源", comparison.get("evidence_source")),
        ("最新证据时间", comparison.get("evidence_captured_at")),
        ("后台上传表", "未生成；本模式只做比价核验"),
    ]:
        summary_sheet.append([label, value])
    _style_sheet(summary_sheet)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=output_path.parent) as temporary:
            temporary_path = Path(temporary.name)
        workbook.save(temporary_path)
        verified = load_workbook(temporary_path, data_only=False)
        if verified.sheetnames != ["SKU比价", "热卖竞品完整SKU", "核验摘要"]:
            raise ComparisonError("WORKBOOK_SHEETS_INVALID")
        if verified["SKU比价"].max_row != len(comparison.get("rows", [])) + 1:
            raise ComparisonError("WORKBOOK_ROW_COUNT_INVALID")
        if verified["热卖竞品完整SKU"].max_row != len(comparison.get("hot_competitor_sku_records", [])) + 1:
            raise ComparisonError("WORKBOOK_ROW_COUNT_INVALID")
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a strict own-SPU versus fixed hot-SPU comparison workbook.")
    parser.add_argument("--source-catalog", required=True)
    parser.add_argument("--competitor-catalog", required=True)
    parser.add_argument("--official-rank", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--overrides")
    parser.add_argument("--target-gap", default="0.10")
    arguments = parser.parse_args()
    try:
        source = json.loads(Path(arguments.source_catalog).read_text(encoding="utf-8"))
        competitor = json.loads(Path(arguments.competitor_catalog).read_text(encoding="utf-8"))
        overrides = json.loads(Path(arguments.overrides).read_text(encoding="utf-8")) if arguments.overrides else None
        comparison = build_comparison(
            source,
            competitor,
            arguments.official_rank,
            overrides,
            target_gap=arguments.target_gap,
        )
        build_workbook(comparison, arguments.output)
        if arguments.json_output:
            json_path = Path(arguments.json_output)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ComparisonError, FileNotFoundError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"status": "READY", "output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
