"""C1 RED contract tests: synthetic files and task metadata, no network."""
import importlib
import io
import unittest
import zipfile
import xml.etree.ElementTree as ET
from heideng_merchant.safety import SafetyError
from tests.short_title_fixtures import template, NS


def workbook(rows, headers=("SKUID", "执行结果", "失败原因"), mutate=None):
    with zipfile.ZipFile(io.BytesIO(template())) as original:
        parts = {name: original.read(name) for name in original.namelist()}
    root = ET.Element("{" + NS + "}worksheet")
    data = ET.SubElement(root, "{" + NS + "}sheetData")
    for number, values in enumerate((headers, *rows), 1):
        row = ET.SubElement(data, "{" + NS + "}row", r=str(number))
        for column, value in enumerate(values):
            cell = ET.SubElement(row, "{" + NS + "}c", r=chr(65 + column) + str(number), t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "{" + NS + "}is"), "{" + NS + "}t").text = str(value)
    if mutate:
        mutate(root)
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root, encoding="utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    return out.getvalue()


class ShortTitleResultContractTests(unittest.TestCase):
    def parse(self, raw, expected=("1001", "1002"), success=1, failed=1):
        module = importlib.import_module("heideng_merchant.short_title_results")
        return module.parse_result_workbook(raw, expected, success_rows=success, failed_rows=failed)

    def test_complete_mixed_result_is_original_order_and_not_effectiveness(self):
        result = self.parse(workbook([("1002", "失败", "标题不合规则"), ("1001", "成功", "")]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["verifiedFailureSkuIds"], ["1002"])
        self.assertEqual([r["skuId"] for r in result["rows"]], ["1001", "1002"])
        self.assertFalse(result["actualTitlesVerified"])
        self.assertFalse(result["healthVerified"])
        self.assertFalse(result["retryAuthorized"])

    def test_complete_all_success_has_no_retry_candidates(self):
        result = self.parse(workbook([("1001", "成功", ""), ("1002", "成功", "")]), success=2, failed=0)
        self.assertTrue(result["complete"])
        self.assertEqual(result["verifiedFailureSkuIds"], [])

    def test_unknown_status_is_not_failed_or_inferred_from_counts(self):
        result = self.parse(workbook([("1001", "处理中", ""), ("1002", "失败", "待核实")]))
        self.assertFalse(result["complete"])
        self.assertEqual(result["verifiedFailureSkuIds"], [])
        self.assertEqual(result["rows"][0]["outcome"], "unknown")

    def test_missing_duplicate_and_unrelated_sku_refused(self):
        for rows in ([("1001", "成功", "")], [("1001", "成功", ""), ("1001", "失败", "x")], [("1001", "成功", ""), ("9002", "失败", "x")]):
            with self.subTest(rows=rows), self.assertRaises(SafetyError):
                self.parse(workbook(rows))

    def test_header_missing_duplicate_or_unreviewed_column_refused(self):
        for headers in (("SKUID", "状态", "失败原因"), ("SKUID", "执行结果", "执行结果"), ("SKUID", "执行结果", "失败原因", "陌生字段")):
            with self.subTest(headers=headers), self.assertRaises(SafetyError):
                self.parse(workbook([("1001", "成功", ""), ("1002", "失败", "x")], headers=headers))

    def test_numeric_sku_and_scientific_notation_refused(self):
        def numeric(root):
            cell = root.find("{" + NS + "}sheetData")[1][0]
            cell.clear()
            cell.attrib.update(r="A2", t="n")
            ET.SubElement(cell, "{" + NS + "}v").text = "1001"
        with self.assertRaises(SafetyError):
            self.parse(workbook([("1001", "成功", ""), ("1002", "失败", "x")], mutate=numeric))
        with self.assertRaises(SafetyError):
            self.parse(workbook([("1.001E3", "成功", ""), ("1002", "失败", "x")]))

    def test_count_boolean_or_mismatch_refused(self):
        raw = workbook([("1001", "成功", ""), ("1002", "失败", "x")])
        for success, failed in ((True, 1), (1, False), (-1, 3), (0, 2), (1, 0), (1.0, 1)):
            with self.subTest(success=success, failed=failed), self.assertRaises(SafetyError):
                self.parse(raw, success=success, failed=failed)

    def test_expected_scope_empty_duplicate_or_bad_id_refused(self):
        raw = workbook([("1001", "成功", ""), ("1002", "失败", "x")])
        for scope in ((), ("1001", "1001"), ("01001", "1002"), (True, "1002")):
            with self.subTest(scope=scope), self.assertRaises(SafetyError):
                self.parse(raw, expected=scope)

    def test_duplicate_row_or_cell_and_wrong_coordinate_refused(self):
        def duplicate_row(root):
            data = root.find("{" + NS + "}sheetData")
            data[2].attrib["r"] = "2"
        def duplicate_cell(root):
            data = root.find("{" + NS + "}sheetData")
            data[1][1].attrib["r"] = "A2"
        def wrong_coordinate(root):
            data = root.find("{" + NS + "}sheetData")
            data[1][0].attrib["r"] = "A3"
        for mutate in (duplicate_row, duplicate_cell, wrong_coordinate):
            with self.subTest(mutate=mutate.__name__), self.assertRaises(SafetyError):
                self.parse(workbook([("1001", "成功", ""), ("1002", "失败", "x")], mutate=mutate))

    def test_formula_and_shared_string_negative_index_refused(self):
        def formula(root):
            ET.SubElement(root.find("{" + NS + "}sheetData")[1][0], "{" + NS + "}f").text = "1+1"
        def negative_index(root):
            cell = root.find("{" + NS + "}sheetData")[1][0]
            cell.clear()
            cell.attrib.update(r="A2", t="s")
            ET.SubElement(cell, "{" + NS + "}v").text = "-1"
        for mutate in (formula, negative_index):
            with self.subTest(mutate=mutate.__name__), self.assertRaises(SafetyError):
                self.parse(workbook([("1001", "成功", ""), ("1002", "失败", "x")], mutate=mutate))

    def test_success_with_failure_reason_is_contradictory(self):
        with self.assertRaises(SafetyError):
            self.parse(workbook([("1001", "成功", "实际失败"), ("1002", "失败", "x")]))

    def test_private_or_url_reason_never_leaves_parser(self):
        # Synthetic markers only, never credentials or a real signed URL.
        for reason in ("Bearer synthetic-not-a-credential", "deviceId=synthetic-device", "https://example.invalid/result?expires=1&key=synthetic"):
            with self.subTest(case=reason.split(" ")[0].split("=")[0]), self.assertRaises(SafetyError):
                self.parse(workbook([("1001", "成功", ""), ("1002", "失败", reason)]))

    def test_partial_known_rows_cannot_exceed_reported_task_counts(self):
        with self.assertRaises(SafetyError):
            self.parse(workbook([("1001", "成功", ""), ("1002", "处理中", "")]), success=0, failed=2)

    def test_full_long_text_sku_is_preserved_exactly(self):
        sku = "9007199254740993"
        result = self.parse(workbook([(sku, "成功", ""), ("1002", "失败", "x")]), expected=(sku, "1002"))
        self.assertEqual(result["rows"][0]["skuId"], sku)

    def test_5000_rows_and_overlimit(self):
        rows = [(str(10000 + n), "成功", "") for n in range(5000)]
        result = self.parse(workbook(rows), expected=tuple(r[0] for r in rows), success=5000, failed=0)
        self.assertEqual(len(result["rows"]), 5000)
        rows.append(("20000", "成功", ""))
        with self.assertRaises(SafetyError):
            self.parse(workbook(rows), expected=tuple(r[0] for r in rows), success=5001, failed=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
