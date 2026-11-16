#!/usr/bin/env python3
"""Append verified hot-SPU SKU prices to a merchant SKU workbook."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

try:
    from .hot_spu_comparison import ComparisonError, _price, _price_text, _validate_catalog
    from .jd_detail_evidence import DetailEvidenceError, normalize_dimensions
    from .jd_price_adjustment import TARGET_GAP, parse_target_gap
except ImportError:
    from hot_spu_comparison import ComparisonError, _price, _price_text, _validate_catalog
    from jd_detail_evidence import DetailEvidenceError, normalize_dimensions
    from jd_price_adjustment import TARGET_GAP, parse_target_gap


REQUIRED_HEADERS = ("SKUID", "商品编码", "商品名称")
OUTPUT_HEADERS = (
    "热卖竞品SPU",
    "热卖同款对应SKU",
    "热卖同款对应SKU到手价",
    "本轮目标差价",
    "建议目标到手价",
    "自有标准化尺寸",
    "热卖同款标准化尺寸",
    "匹配图案",
    "匹配状态",
    "匹配方式",
    "热卖同款商品链接",
    "竞品价格证据时间",
)
GENERIC_DESIGN_PARTS = {
    "打印边框",
    "印制边框",
    "自带背胶",
    "背面带胶",
    "独立",
}


class WorkbookComparisonError(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _text(value).casefold())


def _optional_dimensions(value: Any) -> str:
    try:
        return normalize_dimensions(value)
    except DetailEvidenceError:
        return ""


def _design_label(record: dict[str, Any]) -> str:
    raw = _text(record.get("raw_spec") or record.get("design"))
    parts = [part.strip() for part in re.split(r"\s*/\s*", raw) if part.strip()]
    for part in parts:
        if _optional_dimensions(part) or _key(part) in {_key(value) for value in GENERIC_DESIGN_PARTS}:
            continue
        return part
    without_size = re.sub(
        r"(?<!\d)\d+(?:\.\d+)?\s*(?:cm|厘米)?\s*[xX*×]\s*\d+(?:\.\d+)?\s*(?:cm|厘米)?",
        " ",
        raw,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", without_size).strip(" /-")


def _load_source_rows(path: Path) -> tuple[Any, Any, list[dict[str, Any]], str]:
    if not path.is_file() or path.suffix.casefold() != ".xlsx":
        raise WorkbookComparisonError("SOURCE_WORKBOOK_INVALID")
    workbook = load_workbook(path)
    sheet = workbook.active
    headers = [_text(cell.value) for cell in sheet[1]]
    missing = [header for header in REQUIRED_HEADERS if header not in headers]
    if missing:
        raise WorkbookComparisonError("SOURCE_HEADERS_INVALID")
    indexes = {header: headers.index(header) + 1 for header in REQUIRED_HEADERS}
    rows: list[dict[str, Any]] = []
    for excel_row in range(2, sheet.max_row + 1):
        sku_id = _text(sheet.cell(excel_row, indexes["SKUID"]).value)
        spu_id = _text(sheet.cell(excel_row, indexes["商品编码"]).value)
        title = _text(sheet.cell(excel_row, indexes["商品名称"]).value)
        if not sku_id and not spu_id and not title:
            continue
        if not re.fullmatch(r"\d{5,20}", sku_id) or not spu_id or not title:
            raise WorkbookComparisonError("SOURCE_ROW_INCOMPLETE")
        normalized_spec = _optional_dimensions(title)
        if not normalized_spec:
            raise WorkbookComparisonError("SOURCE_SIZE_UNCERTAIN")
        rows.append(
            {
                "excel_row": excel_row,
                "sku_id": sku_id,
                "spu_id": spu_id,
                "title": title,
                "normalized_spec": normalized_spec,
            }
        )
    if not rows or len({row["sku_id"] for row in rows}) != len(rows):
        raise WorkbookComparisonError("SOURCE_SKU_INVALID")
    spu_ids = {row["spu_id"] for row in rows}
    if len(spu_ids) != 1:
        raise WorkbookComparisonError("SOURCE_SPU_AMBIGUOUS")
    return workbook, sheet, rows, next(iter(spu_ids))


def _select_competitor(
    own: dict[str, Any],
    by_spec: dict[str, list[dict[str, Any]]],
    labels: dict[str, str],
    overrides: dict[str, str],
) -> tuple[dict[str, Any] | None, str, str, str]:
    candidates = by_spec.get(own["normalized_spec"], [])
    if not candidates:
        return None, "NO_EXACT_SIZE", "strict_dimension_no_match", ""
    override_sku = overrides.get(own["sku_id"])
    if override_sku:
        selected = next((row for row in candidates if row["sku_id"] == override_sku), None)
        if selected is None:
            raise WorkbookComparisonError("SKU_OVERRIDE_INVALID")
        return selected, "MATCHED", "explicit_own_to_competitor_override", labels[selected["sku_id"]]

    own_key = _key(own["title"])
    matching_positions = {
        labels[row["sku_id"]]: own_key.rfind(_key(labels[row["sku_id"]]))
        for row in candidates
        if labels[row["sku_id"]] and own_key.rfind(_key(labels[row["sku_id"]])) >= 0
    }
    if matching_positions:
        nearest = max(matching_positions.values())
        nearest_labels = {label for label, position in matching_positions.items() if position == nearest}
        longest = max(len(_key(value)) for value in nearest_labels)
        best_labels = {value for value in nearest_labels if len(_key(value)) == longest}
        if len(best_labels) != 1:
            raise WorkbookComparisonError("DESIGN_MATCH_AMBIGUOUS")
        design = next(iter(best_labels))
        design_candidates = [row for row in candidates if labels[row["sku_id"]] == design]
        prices = {row["final_price"] for row in design_candidates}
        if len(prices) > 1:
            raise WorkbookComparisonError("SKU_OVERRIDE_REQUIRED")
        selected = sorted(design_candidates, key=lambda row: row["sku_id"])[0]
        return selected, "MATCHED", "strict_dimension_exact_design", design

    prices = {row["final_price"] for row in candidates}
    if len(prices) > 1:
        raise WorkbookComparisonError("SKU_OVERRIDE_REQUIRED")
    selected = sorted(candidates, key=lambda row: row["sku_id"])[0]
    return selected, "MATCHED", "strict_dimension_same_price_design_unresolved", labels[selected["sku_id"]]


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
        values = [len(_text(sheet.cell(row, column).value)) for row in range(1, min(sheet.max_row, 200) + 1)]
        sheet.column_dimensions[get_column_letter(column)].width = min(48, max(12, max(values, default=10) + 2))
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def build_workbook_comparison(
    source_path: Path | str,
    competitor_catalog: dict[str, Any],
    output_path: Path | str,
    *,
    selection_evidence: dict[str, Any] | None = None,
    overrides: dict[str, str] | None = None,
    target_gap: Decimal = TARGET_GAP,
) -> dict[str, Any]:
    source = Path(source_path)
    output = Path(output_path)
    if source.resolve() == output.resolve():
        raise WorkbookComparisonError("OUTPUT_MUST_BE_NEW_FILE")
    workbook, sheet, own_rows, source_spu_id = _load_source_rows(source)
    try:
        competitor = _validate_catalog(competitor_catalog)
    except ComparisonError as error:
        raise WorkbookComparisonError(str(error)) from error
    try:
        target_gap = parse_target_gap(target_gap)
    except ValueError as error:
        raise WorkbookComparisonError("TARGET_GAP_INVALID") from error
    clean_overrides = {_text(key): _text(value) for key, value in (overrides or {}).items()}
    labels = {row["sku_id"]: _design_label(row) for row in competitor["sku_records"]}
    if any(not label for label in labels.values()):
        raise WorkbookComparisonError("COMPETITOR_DESIGN_UNCERTAIN")
    by_spec: dict[str, list[dict[str, Any]]] = {}
    for row in competitor["sku_records"]:
        by_spec.setdefault(row["normalized_spec"], []).append(row)

    start_column = sheet.max_column + 1
    for offset, header in enumerate(OUTPUT_HEADERS):
        sheet.cell(1, start_column + offset, header)
    result_rows: list[dict[str, Any]] = []
    for own in own_rows:
        selected, status, method, design = _select_competitor(own, by_spec, labels, clean_overrides)
        competitor_price = _price(selected["final_price"]) if selected else None
        suggested_target = competitor_price - target_gap if competitor_price is not None else None
        if suggested_target is not None and suggested_target <= 0:
            raise WorkbookComparisonError("TARGET_GAP_EXCEEDS_PRICE")
        values = [
            competitor["spu_id"],
            selected["sku_id"] if selected else "",
            float(competitor_price) if competitor_price is not None else None,
            float(target_gap),
            float(suggested_target) if suggested_target is not None else None,
            own["normalized_spec"],
            selected["normalized_spec"] if selected else "",
            design,
            status,
            method,
            "查看热卖同款" if selected else "",
            selected["captured_at"] if selected else "",
        ]
        for offset, value in enumerate(values):
            sheet.cell(own["excel_row"], start_column + offset, value)
        for price_offset in (2, 3, 4):
            sheet.cell(own["excel_row"], start_column + price_offset).number_format = "0.00"
        link_cell = sheet.cell(own["excel_row"], start_column + 10)
        if selected:
            link_cell.hyperlink = selected["product_url"]
            link_cell.style = "Hyperlink"
        result_rows.append(
            {
                "own_sku_id": own["sku_id"],
                "own_spu_id": source_spu_id,
                "own_normalized_spec": own["normalized_spec"],
                "matched_design": design,
                "hot_competitor_sku_id": selected["sku_id"] if selected else "",
                "hot_competitor_final_price": _price_text(_price(selected["final_price"])) if selected else "",
                "target_gap": _price_text(target_gap),
                "suggested_target_final_price": _price_text(suggested_target) if suggested_target is not None else "",
                "match_status": status,
                "match_method": method,
            }
        )
    _style_sheet(sheet)

    competitor_sheet = workbook.create_sheet("热卖竞品完整SKU")
    competitor_sheet.append(["热卖竞品SPU", "竞品SKU", "图案", "规格", "标准化尺寸", "真实到手价", "商品链接", "价格证据时间"])
    for row in competitor["sku_records"]:
        competitor_sheet.append([
            competitor["spu_id"], row["sku_id"], labels[row["sku_id"]], row.get("raw_spec") or row.get("design"),
            row["normalized_spec"], float(_price(row["final_price"])), "查看商品", row["captured_at"],
        ])
        competitor_sheet.cell(competitor_sheet.max_row, 6).number_format = "0.00"
        link_cell = competitor_sheet.cell(competitor_sheet.max_row, 7)
        link_cell.hyperlink = row["product_url"]
        link_cell.style = "Hyperlink"
    _style_sheet(competitor_sheet)

    evidence = selection_evidence or {}
    summary = workbook.create_sheet("核验摘要")
    summary.append(["核验项", "结果"])
    for label, value in [
        ("运行状态", "READY"),
        ("自有SPU", source_spu_id),
        ("自有SKU数", len(own_rows)),
        ("热卖竞品SPU", competitor["spu_id"]),
        ("热卖竞品完整SKU数", len(competitor["sku_records"])),
        ("默认/本轮目标差价", _price_text(target_gap)),
        ("改价状态", "仅给出建议目标价；未进入改价阶段"),
        ("严格匹配数", sum(row["match_status"] == "MATCHED" for row in result_rows)),
        ("未匹配数", sum(row["match_status"] != "MATCHED" for row in result_rows)),
        ("候选发现通道", evidence.get("discovery_channel", "")),
        ("页面可见销量", evidence.get("sales_text", "")),
        ("页面销量下限", evidence.get("sales_lower_bound", "")),
        ("主图核验", evidence.get("image_review", "")),
        ("后台上传表", "未生成；本模式只做热卖同款比价"),
    ]:
        summary.append([label, value])
    _style_sheet(summary)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=output.parent) as temporary:
            temporary_path = Path(temporary.name)
        workbook.save(temporary_path)
        verified = load_workbook(temporary_path, data_only=False)
        if verified[sheet.title].max_row != sheet.max_row:
            raise WorkbookComparisonError("WORKBOOK_ROW_COUNT_INVALID")
        if verified["热卖竞品完整SKU"].max_row != len(competitor["sku_records"]) + 1:
            raise WorkbookComparisonError("WORKBOOK_ROW_COUNT_INVALID")
        temporary_path.replace(output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return {
        "status": "READY",
        "source_spu_id": source_spu_id,
        "source_sku_count": len(own_rows),
        "hot_competitor_spu_id": competitor["spu_id"],
        "hot_competitor_sku_count": len(competitor["sku_records"]),
        "target_gap": _price_text(target_gap),
        "matched_count": sum(row["match_status"] == "MATCHED" for row in result_rows),
        "unmatched_count": sum(row["match_status"] != "MATCHED" for row in result_rows),
        "rows": result_rows,
        "selection_evidence": evidence,
        "upload_workbook_generated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a verified hot-SPU price mapping to a merchant SKU workbook.")
    parser.add_argument("--source-workbook", required=True)
    parser.add_argument("--competitor-catalog", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--selection-evidence")
    parser.add_argument("--overrides")
    parser.add_argument("--target-gap", default="0.10")
    arguments = parser.parse_args()
    try:
        catalog = json.loads(Path(arguments.competitor_catalog).read_text(encoding="utf-8"))
        evidence = json.loads(Path(arguments.selection_evidence).read_text(encoding="utf-8")) if arguments.selection_evidence else None
        overrides = json.loads(Path(arguments.overrides).read_text(encoding="utf-8")) if arguments.overrides else None
        result = build_workbook_comparison(
            arguments.source_workbook,
            catalog,
            arguments.output,
            selection_evidence=evidence,
            overrides=overrides,
            target_gap=arguments.target_gap,
        )
        if arguments.json_output:
            path = Path(arguments.json_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (WorkbookComparisonError, FileNotFoundError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"status": "READY", "output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
