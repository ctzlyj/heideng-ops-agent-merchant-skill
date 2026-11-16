import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


LIST_HEADERS = [
    "销量排名",
    "官方销量排序位次",
    "排序依据",
    "候选SPU",
    "入口SKUs",
    "商品标题",
    "店铺",
    "销量文本",
    "销量下限",
    "识别通道",
    "图片相似度",
    "AI结论",
    "核验状态",
    "失败原因",
    "候选链接",
    "搜索展示价（不参与统计）",
]
TOP_HEADERS = [
    "有效排名",
    "官方销量排序位次",
    "排序依据",
    "候选SPU",
    "入口SKUs",
    "匹配SKU",
    "原始规格",
    "标准化规格",
    "真实到手价",
    "销量文本",
    "销量下限",
    "价格证据来源",
    "价格证据时间",
    "商品链接",
    "匹配方式",
]


def _join(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return " | ".join(str(value) for value in values)


def _display_prices(row: dict[str, Any]) -> str:
    values = []
    for observation in row.get("display_price_observations", []):
        value = str(observation.get("value", "")).strip()
        if value and value not in values:
            values.append(value)
    return " | ".join(values)


def _style_sheet(sheet) -> None:
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
            max(
                12,
                max(
                    len(str(sheet.cell(row=row, column=column).value or ""))
                    for row in range(1, sheet.max_row + 1)
                )
                + 2,
            ),
        )
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _build_list_sheet(workbook: Workbook, report: dict[str, Any]) -> None:
    sheet = workbook.active
    sheet.title = "同品列表"
    sheet.append(LIST_HEADERS)
    failed_fill = PatternFill("solid", fgColor="FCE8E6")
    no_size_fill = PatternFill("solid", fgColor="FFF4CE")
    for rank, row in enumerate(report["same_product_list"], start=1):
        image_score = row.get("image_score") or {}
        review = row.get("ai_review") or {}
        sheet.append(
            [
                rank,
                row.get("official_api_rank"),
                report.get("ranking_label"),
                row.get("spu_id"),
                _join(row.get("entry_sku_ids")),
                row.get("title"),
                row.get("shop_name"),
                row.get("sales_text"),
                row.get("sales_lower_bound"),
                _join(row.get("source_channels")),
                image_score.get("combined_similarity"),
                "/".join(
                    value
                    for value in (
                        str(review.get("decision", "")),
                        str(review.get("confidence", "")),
                    )
                    if value
                ),
                row.get("verification_status"),
                row.get("failure_reason"),
                row.get("product_url"),
                _display_prices(row),
            ]
        )
        link_cell = sheet.cell(row=sheet.max_row, column=15)
        if link_cell.value:
            link_cell.hyperlink = link_cell.value
            link_cell.style = "Hyperlink"
        status = row.get("verification_status")
        fill = no_size_fill if status == "no_exact_size" else failed_fill
        if status not in {"verified", "no_exact_size"}:
            for cell in sheet[sheet.max_row]:
                cell.fill = fill
        elif status == "no_exact_size":
            for cell in sheet[sheet.max_row]:
                cell.fill = fill
    _style_sheet(sheet)


def _build_top_sheet(workbook: Workbook, report: dict[str, Any]) -> None:
    top_limit = int(report["statistics"]["top_limit"])
    sheet = workbook.create_sheet(f"同规格TOP{top_limit}")
    sheet.append(TOP_HEADERS)
    for row in report["top_same_spec"]:
        evidence = row["price_evidence"]
        sheet.append(
            [
                row.get("rank"),
                row.get("official_api_rank"),
                row.get("ranking_label") or report.get("ranking_label"),
                row.get("spu_id"),
                _join(row.get("entry_sku_ids")),
                row.get("selected_sku_id"),
                row.get("raw_spec"),
                row.get("normalized_spec"),
                float(row["final_price"]),
                row.get("sales_text"),
                row.get("sales_lower_bound"),
                evidence.get("source"),
                evidence.get("captured_at"),
                row.get("product_url"),
                row.get("match_method"),
            ]
        )
        sheet.cell(row=sheet.max_row, column=9).number_format = "0.00"
        link_cell = sheet.cell(row=sheet.max_row, column=14)
        if link_cell.value:
            link_cell.hyperlink = link_cell.value
            link_cell.style = "Hyperlink"
    _style_sheet(sheet)


def _build_summary_sheet(workbook: Workbook, report: dict[str, Any]) -> None:
    sheet = workbook.create_sheet("统计摘要")
    sheet.append(["项目", "值"])
    source = report["source"]
    statistics = report["statistics"]
    rows = [
        ("统计状态", report["status"]),
        ("来源SKU", source.get("sku_id")),
        ("来源规格", source.get("normalized_spec")),
        ("发现候选数", statistics.get("candidate_count")),
        ("确认同品数", statistics.get("same_product_count")),
        ("有效样本数", statistics.get("sample_count")),
        ("TOP上限", statistics.get("top_limit")),
        ("排序依据", report.get("ranking_label")),
        (
            "最低真实到手价",
            float(statistics["minimum_final_price"])
            if statistics.get("minimum_final_price") is not None
            else None,
        ),
        (
            "平均真实到手价",
            float(statistics["average_final_price"])
            if statistics.get("average_final_price") is not None
            else None,
        ),
        (
            "阻断原因",
            json.dumps(report.get("blocking_reasons", []), ensure_ascii=False),
        ),
    ]
    for label, value in rows:
        sheet.append([label, value])
    sheet["B10"].number_format = "0.00"
    sheet["B11"].number_format = "0.00"
    _style_sheet(sheet)


def build_market_workbook(report: dict[str, Any], output: Path) -> None:
    if not isinstance(report, dict) or report.get("status") not in {"READY", "PARTIAL"}:
        raise ValueError("Only READY or PARTIAL market reports can create a workbook.")
    for key in ("source", "same_product_list", "top_same_spec", "statistics"):
        if key not in report:
            raise ValueError(f"Market report is missing {key}.")
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    _build_list_sheet(workbook, report)
    _build_top_sheet(workbook, report)
    _build_summary_sheet(workbook, report)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".xlsx", dir=output.parent
        ) as temporary:
            temporary_path = Path(temporary.name)
        workbook.save(temporary_path)
        verified = load_workbook(temporary_path, data_only=False)
        top_sheet_name = f"同规格TOP{int(report['statistics']['top_limit'])}"
        if verified.sheetnames != ["同品列表", top_sheet_name, "统计摘要"]:
            raise ValueError("Generated market workbook has unexpected sheets.")
        expected_top_rows = len(report["top_same_spec"]) + 1
        if verified[top_sheet_name].max_row != expected_top_rows:
            raise ValueError("Generated market workbook has an incorrect TOP row count.")
        temporary_path.replace(output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the JD same-product market workbook.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        report = json.loads(Path(arguments.report).read_text(encoding="utf-8"))
        build_market_workbook(report, Path(arguments.output))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
