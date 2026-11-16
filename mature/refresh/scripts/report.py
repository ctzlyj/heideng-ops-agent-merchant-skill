"""Write the Excel result workbook and batch-result.md.

usage: python report.py <run_dir> [productId ...]

Both deliverables always carry 店铺名, 店铺ID and the optimisation scope
(主图 / 详情页), plus the prompt that was actually used.
"""

import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

UNDERLINE = Font(name="Microsoft YaHei", size=10, underline="single", color="0563C1")
HEADERS = [
    "商品ID",
    "商品标题",
    "主图组数",
    "主图数",
    "主图换新",
    "详情图数",
    "详情换新",
    "超位保留",
    "审核拒绝",
    "保留原图",
    "SKU价格",
    "商品状态",
    "校验",
    "问题",
    "主图对比",
    "详情对比",
]


def capped_count(plan, pid):
    return sum(1 for item in plan.get("capped") or [] if int(item["productId"]) == int(pid))


def scope_text(plan):
    scopes = plan.get("scopes") or ["main"]
    names = {"main": "主图", "detail": "详情页"}
    return " + ".join(names.get(item, item) for item in scopes)


def rejected_rows(plan, generation):
    """Every rejected image as (productId, title, scope, group, position, reason)."""
    titles = {str(item["productId"]): item["title"] for item in plan["products"]}
    rows = []
    for key, task in (plan.get("tasks") or {}).items():
        record = generation.get(key) or {}
        if record.get("status") != "rejected":
            continue
        pid = str(task.get("productId"))
        rows.append((
            pid,
            titles.get(pid, ""),
            "主图" if task.get("scope") == "main" else "详情页",
            str(task.get("group") or ""),
            str(task.get("position") or ""),
            str(record.get("error") or "内容审核拒绝"),
        ))
    rows.sort(key=lambda item: (item[0], item[3], item[4]))
    return rows


def build_xlsx(run, job, identity, plan, verification, patches, generation, label):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "优化结果"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(name="Microsoft YaHei", size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for product in plan["products"]:
        pid = str(product["productId"])
        entry = verification.get(pid) or {}
        patch = patches.get(pid) or {}
        planned_keys = [item["key"] for item in product.get("positions") or []]
        planned_keys += [item["key"] for item in product.get("detailImages") or []]
        rejected = sum(
            1 for key in planned_keys
            if (generation.get(key) or {}).get("status") == "rejected"
        )
        kept_original = max(0, entry.get("oldKept", 0) or 0)
        # Comparison images are optional: only link files that actually exist.
        main_compare = (
            "comparisons/%s-compare.png" % pid
            if (run / "comparisons" / ("%s-compare.png" % pid)).exists()
            else ""
        )
        detail_compare = (
            "comparisons/%s-detail-compare.png" % pid
            if product.get("detailImages")
            and (run / "comparisons" / ("%s-detail-compare.png" % pid)).exists()
            else ""
        )
        sheet.append(
            [
                int(pid),
                product["title"],
                product["groupCount"],
                entry.get("images", ""),
                entry.get("newImages", ""),
                entry.get("detailImages", 0),
                entry.get("detailNewImages", 0),
                patch.get("cappedPositions", capped_count(plan, pid)),
                rejected,
                kept_original,
                "未变更" if entry.get("pricesUnchanged", True) else "有变更",
                entry.get("status", ""),
                "通过" if entry.get("ok") else "未通过",
                "; ".join(entry.get("problems") or []),
                main_compare if product.get("positions") else "",
                detail_compare,
            ]
        )
        row = sheet.max_row
        for column, target in ((15, main_compare), (16, detail_compare)):
            cell = sheet.cell(row=row, column=column)
            if target:
                cell.hyperlink = target
                cell.font = UNDERLINE

    sheet.freeze_panes = "A2"
    widths = [16, 50, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 8, 26, 32, 34]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if not cell.hyperlink:
                cell.font = Font(name="Microsoft YaHei", size=9)
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column == 2)

    meta = workbook.create_sheet("数据说明")
    rows = [
        ("店铺", identity["shopName"]),
        ("店铺ID", identity["venderId"]),
        ("优化范围", scope_text(plan)),
        (
            "改图口径",
            "逐张按原图重制；同一商品内相同图片只生成一次、多组复用；"
            "双 gpt 生图模型（Flare/Sunburst）并发生成",
        ),
        ("提示词", job["promptTemplate"].replace("{title}", "商品标题")),
        (
            "未变更项",
            "标题、价格、品牌、库存、商品状态、SKU 规格图（ggtImages）；"
            "主图位号超过%d的不参与" % int(job.get("maxPosition") or common.DEFAULT_MAX_POSITION),
        ),
    ]
    if "detail" in (plan.get("scopes") or []):
        rows.append(("详情页写回", "desc 与 mobileDesc 只替换计划内图片 URL，其余 HTML 逐字节保留"))
    rows.append((
        "保留原图",
        "本次未换新的图片数：含只改首图时未计划的位、模型审核拒绝、超位排除三类",
    ))
    for index, (name, value) in enumerate(rows, 1):
        meta.cell(row=index, column=1, value=name)
        meta.cell(row=index, column=2, value=value)
        meta.cell(row=index, column=1).font = Font(name="Microsoft YaHei", size=10, bold=True)
        meta.cell(row=index, column=2).font = Font(name="Microsoft YaHei", size=10)
        meta.cell(row=index, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    meta.column_dimensions["A"].width = 14
    meta.column_dimensions["B"].width = 90

    out = run / ("%s-图片优化结果-%s.xlsx" % (identity["shopName"], label))
    workbook.save(out)
    return out


def add_rejected_sheet(workbook, plan, generation):
    rows = rejected_rows(plan, generation)
    sheet = workbook.create_sheet("审核拒绝明细")
    sheet.append(["商品ID", "商品标题", "范围", "主图组", "位号", "原因"])
    for cell in sheet[1]:
        cell.font = Font(name="Microsoft YaHei", size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor="FCE4D6")
    for row in rows:
        sheet.append(list(row))
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Microsoft YaHei", size=9)
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column in (2, 6))
    for index, width in enumerate([16, 46, 8, 16, 6, 34], 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    return len(rows)


def build_markdown(run, job, identity, plan, verification, generation, uploads, patches, label):
    total_main = sum(entry.get("images", 0) for entry in verification.values())
    new_main = sum(entry.get("newImages", 0) for entry in verification.values())
    total_detail = sum(entry.get("detailImages", 0) for entry in verification.values())
    new_detail = sum(entry.get("detailNewImages", 0) for entry in verification.values())
    lines = [
        "# %s 图片批量优化（%s）" % (identity["shopName"], label),
        "",
        "- 店铺：%s" % identity["shopName"],
        "- 店铺ID：%s" % identity["venderId"],
        "- jdo Profile：%s" % job["profile"],
        "- 优化范围：%s" % scope_text(plan),
        "- 目标商品：%d 条" % len(verification),
        "- 主图：槽位 %d 个，换新 %d 个" % (total_main, new_main),
        "- 详情页：图片 %d 张，换新 %d 张" % (total_detail, new_detail),
        "- 生图：%d/%d 成功" % (
            sum(1 for value in generation.values() if value.get("status") == "succeeded"),
            len(generation),
        ),
        "- 上传：%d，主图 PATCH：%d/%d 商品成功" % (
            sum(1 for value in uploads.values() if value.get("status") == "succeeded"),
            sum(1 for value in patches.values() if value.get("ok")),
            len(patches),
        ),
        "- 独立终验：%d/%d 通过" % (
            sum(1 for value in verification.values() if value.get("ok")),
            len(verification),
        ),
        "- 审核拒绝：%d 张（对应图片保留原图，明细见 Excel「审核拒绝明细」）" % sum(
            1 for value in generation.values() if value.get("status") == "rejected"
        ),
        "",
        "## 提示词（用户定稿）",
        "",
        "> " + job["promptTemplate"].replace("{title}", "商品标题"),
        "",
        "## 明细",
        "",
    ]
    for pid, entry in verification.items():
        lines.append(
            "- %s %s：主图 %d/%d，详情 %d/%d，SKU价格%s，状态 %s，%s"
            % (
                pid,
                entry["title"][:22],
                entry.get("newImages", 0),
                entry.get("images", 0),
                entry.get("detailNewImages", 0),
                entry.get("detailImages", 0),
                "未变更" if entry.get("pricesUnchanged", True) else "有变更",
                entry.get("status", ""),
                "通过" if entry.get("ok") else "未通过：" + "; ".join(entry.get("problems") or []),
            )
        )
    lines += [
        "",
        "## 交付物",
        "",
        "- comparisons/（可选：仅在用户要求对比图时由 compare.py 生成）",
        "- %s-图片优化结果-%s.xlsx" % (identity["shopName"], label),
        "- plan-batch.json / internal-generation.json / uploads.json / patch-results.json / "
        "detail-patch-results.json / final-verification.json（台账，可续跑）",
    ]
    out = run / "batch-result.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out, lines


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: report.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    verification = common.load_json(run / "final-verification.json")
    if not plan or not verification:
        raise SystemExit("missing plan-batch.json or final-verification.json")
    identity = common.load_json(run / "identity.json") or {
        "shopName": job["shopName"],
        "venderId": job["venderId"],
    }
    generation = common.load_json(run / "internal-generation.json") or {}
    uploads = common.load_json(run / "uploads.json") or {}
    patches = common.load_json(run / "patch-results.json") or {}
    label = str(job.get("label") or datetime.now().strftime("%Y%m%d"))

    xlsx = build_xlsx(run, job, identity, plan, verification, patches, generation, label)
    workbook = openpyxl.load_workbook(xlsx)
    rejected_count = add_rejected_sheet(workbook, plan, generation)
    workbook.save(xlsx)
    if rejected_count:
        print("审核拒绝明细：%d 张（该图片保留原图）" % rejected_count)
    markdown, lines = build_markdown(
        run, job, identity, plan, verification, generation, uploads, patches, label
    )
    print("saved", xlsx)
    print("saved", markdown)
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv)
