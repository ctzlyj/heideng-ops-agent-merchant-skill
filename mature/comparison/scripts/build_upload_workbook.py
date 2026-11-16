#!/usr/bin/env python3
"""Fill the bundled two-column JD upload template without third-party packages."""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
import re


def validate_rows(rows: object) -> list[dict[str, str]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Upload rows must be a non-empty JSON list.")
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or set(row) != {"SKUID", "京东价"}:
            raise ValueError(f"Row {index} must contain exactly SKUID and 京东价.")
        sku_id = str(row["SKUID"]).strip()
        if not sku_id or sku_id in seen:
            raise ValueError(f"Row {index} has a blank or duplicate SKUID.")
        try:
            price = Decimal(str(row["京东价"])).quantize(Decimal("0.01"))
        except InvalidOperation as error:
            raise ValueError(f"Row {index} has an invalid 京东价.") from error
        if price <= 0:
            raise ValueError(f"Row {index} has a non-positive 京东价.")
        seen.add(sku_id)
        validated.append({"SKUID": sku_id, "京东价": format(price, ".2f")})
    return validated


def build_upload_workbook(template: Path, rows_path: Path, output: Path) -> None:
    rows = validate_rows(json.loads(rows_path.read_text(encoding="utf-8")))
    if not template.is_file():
        raise FileNotFoundError(f"Template not found: {template}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template, "r") as source:
        sheet_text = source.read("xl/worksheets/sheet1.xml").decode("utf-8")
        if "</sheetData>" not in sheet_text:
            raise ValueError("Template sheetData is missing.")
        if re.search(r'<row\s+[^>]*r="(?:[3-9]|\d{2,})"', sheet_text):
            raise ValueError("Bundled template must not contain data rows below the header.")
        row_xml: list[str] = []
        for offset, record in enumerate(rows, start=3):
            row_xml.append(
                f'<row r="{offset}" spans="1:2">'
                f'<c r="A{offset}" t="inlineStr"><is><t>{escape(record["SKUID"])}</t></is></c>'
                f'<c r="B{offset}"><v>{record["京东价"]}</v></c>'
                "</row>"
            )
        sheet_text = re.sub(r'<dimension\s+ref="[^"]+"\s*/>', f'<dimension ref="A1:B{len(rows) + 2}"/>', sheet_text, count=1)
        sheet_text = sheet_text.replace("</sheetData>", "".join(row_xml) + "</sheetData>", 1)
        updated_sheet = sheet_text.encode("utf-8")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=output.parent) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as destination:
                for item in source.infolist():
                    payload = updated_sheet if item.filename == "xl/worksheets/sheet1.xml" else source.read(item.filename)
                    destination.writestr(item, payload)
            temporary_path.replace(output)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, help="upload_rows.json path")
    parser.add_argument("--output", required=True, help="Output .xlsx path")
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parents[1] / "assets" / "商品导入价格模板.xlsx"),
        help="Optional replacement template path.",
    )
    arguments = parser.parse_args()
    try:
        build_upload_workbook(Path(arguments.template), Path(arguments.rows), Path(arguments.output))
    except (FileNotFoundError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
