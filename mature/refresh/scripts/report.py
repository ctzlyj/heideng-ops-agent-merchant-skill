"""Write the Excel result workbook and batch-result.md.

usage: python report.py <run_dir> [productId ...]

Both deliverables always carry 店铺名, 店铺ID and the optimisation scope
(主图 / 详情页), plus the prompt that was actually used.
"""

import json
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
    "授权主图位",
    "已核实保留原图",
    "目标图位待核",
    "范围外3:4长图",
    "长图改前位数",
    "长图回读位数",
]


def capped_count(plan, pid):
    return sum(1 for item in plan.get("capped") or [] if int(item["productId"]) == int(pid))


def scope_text(plan):
    scopes = plan.get("scopes") or ["main"]
    names = {"main": "主图", "detail": "详情页"}
    return " + ".join(names.get(item, item) for item in scopes)


def price_result(entry):
    return {True: "未变更", False: "有变更"}.get(entry.get("pricesUnchanged"), "待核对")


def main_target(plan, product):
    return "main" in (plan.get("scopes") or ["main"]) and (
        "positions" not in product or bool(product["positions"]) or bool(product.get("selectedSlots"))
    )


def slot_counts(product, entry):
    receipt = entry.get("mainSlotReadback") or {}
    fields = ("requested", "verified", "retained", "unresolved")
    if (all(type(receipt.get(k)) is int and receipt[k] >= 0 for k in fields)
            and receipt["requested"] == sum(receipt[k] for k in fields[1:])):
        return {k:receipt[k] for k in fields}, True
    # Older plans can list one asset per URL even when several physical positions use it.
    # Only selectedSlots contains the explicitly frozen physical positions.
    slots = product.get("selectedSlots")
    requested = None
    if isinstance(slots, list) and all(isinstance(s, dict) and s.get("group") is not None
                                      and type(s.get("position")) is int and s["position"] > 0 for s in slots):
        requested = len({(str(s["group"]), s["position"]) for s in slots})
    return {"requested":requested, "verified":0, "retained":0, "unresolved":requested}, False


def rectangle_result(entry):
    receipt = entry.get("rectangleReadback") or {}
    if receipt.get("status") == "changed":
        return "范围外有变化"
    if receipt.get("status") == "unchanged" and type(receipt.get("beforeSlots")) is int:
        if receipt["beforeSlots"] == receipt.get("afterSlots") and receipt["beforeSlots"] >= 0:
            return "已核实未变" if receipt["beforeSlots"] else "已核实无长图"
    return "待核对"


def product_verdict(entry, needs_main, has_slot_evidence):
    if not entry or (needs_main and not has_slot_evidence):
        return "待核对"
    return "通过" if entry.get("ok") else "未通过"


def progress(plan, generation, uploads, patches, verification):
    """Summarize the frozen task's existing receipts, including partially finished runs."""
    keys = set(plan.get("tasks") or {})
    products = plan.get("products")
    if products is None:
        # Early progress receipts may only contain a task index.
        products = [{"productId":pid} for pid in {task["productId"] for task in plan.get("tasks", {}).values()}]
    pids = {str(item["productId"]) for item in products}
    succeeded = [generation[key] for key in keys if generation.get(key, {}).get("status") == "succeeded"]
    confirmed = {pid: patches[pid] for pid in pids if patches.get(pid, {}).get("status") == "verified-in-edit-detail"}
    independent = 0
    passed_slots = 0
    slots = {"requested":0, "verified":0, "retained":0, "unresolved":0, "productsPendingEvidence":0}
    rectangles = {"unchangedProducts":0, "unchangedSlots":0, "absentProducts":0, "changedProducts":0,
                  "unverifiedProducts":0, "beforeSlots":0, "afterSlots":0}
    for product in products:
        entry = verification.get(str(product["productId"])) or {}
        needs_main = main_target(plan, product)
        counts, known = slot_counts(product, entry)
        if product_verdict(entry, needs_main, known) == "通过":
            independent += 1
            passed_slots += counts["verified"] if needs_main else 0
        if not needs_main:
            continue
        for key, value in counts.items():
            slots[key] = slots[key] + value if slots[key] is not None and value is not None else None
        slots["productsPendingEvidence"] += not known
        rect = entry.get("rectangleReadback") or {}
        for key in ("beforeSlots", "afterSlots"):
            value = rect.get(key)
            rectangles[key] = rectangles[key] + value if (rectangles[key] is not None and
                                                          type(value) is int and value >= 0) else None
        state = rectangle_result(entry)
        if state == "已核实未变":
            rectangles["unchangedProducts"] += 1
            rectangles["unchangedSlots"] += entry["rectangleReadback"]["beforeSlots"]
        elif state == "已核实无长图":
            rectangles["absentProducts"] += 1
        elif state == "范围外有变化":
            rectangles["changedProducts"] += 1
        else:
            rectangles["unverifiedProducts"] += 1
    reused = sum(bool(record.get("reusedSample")) for record in succeeded)
    return {"targetProducts": len(pids), "plannedAssets": len(keys), "newImagesSucceeded": len(succeeded) - reused,
            "approvedSamplesReused": reused,
            "uploadedAssets": sum(uploads.get(key, {}).get("status") == "succeeded" for key in keys),
            "unresolvedUploads": sum(uploads.get(key, {}).get("status") in ("uploading", "unknown") for key in keys),
            "patchVerifiedProducts": len(confirmed),
            "patchVerifiedMainSlots": sum(record.get("changedSlots", 0) for record in confirmed.values()),
            "patchAwaitingReadback": sum(patches.get(pid, {}).get("status") in
                                         ("awaiting-readback", "prior-edit-pending") for pid in pids),
            "finalVerifiedProducts": independent,
            "finalVerifiedMainSlots": passed_slots,
            "mainSlotReadback": slots, "rectangleReadback": rectangles,
            "consumerPageStatus": "unchecked"}


def main_delivery(counts):
    slots = counts["mainSlotReadback"]
    requested = slots["requested"]
    scope = f"本次授权 {requested} 个主图位" if requested is not None else "本次授权主图位总数待核对"
    parts = [scope, f"已逐位核实换新 {slots['verified']} 个"]
    if slots["retained"]:
        parts.append(f"审核拒绝后已核实保留原图 {slots['retained']} 个")
    if slots["unresolved"]:
        parts.append(f"仍待核实 {slots['unresolved']} 个")
    if slots["productsPendingEvidence"]:
        parts.append(f"{slots['productsPendingEvidence']} 个商品缺少逐位终验回执")
    return "，".join(parts) + "。"


def rectangle_delivery(counts):
    rect = counts["rectangleReadback"]
    facts = []
    for key, description in [("unchangedProducts", f"个商品的 {rect['unchangedSlots']} 个长图位已核实未变"),
                             ("absentProducts", "个商品已核实无长图"),
                             ("changedProducts", "个商品的长图发生变化，需核对改动来源"),
                             ("unverifiedProducts", "个商品的长图状态待核对")]:
        if rect[key]:
            facts.append(f"{rect[key]} {description}")
    return "，".join(facts) + "。" if facts else "本次没有目标主图。"


def readback_problems(entry):
    messages = {
        "rectangle images present": "旧版把已有 3:4 长图计为失败，需按原范围只读复核",
        "rectangle images changed": "范围外 3:4 长图发生变化，需核对改动来源",
    }
    return "，".join(messages.get(problem, problem) for problem in entry.get("problems") or [])


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


def build_xlsx(run, job, identity, plan, verification, patches, generation, label, counts=None):
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
        needs_main = main_target(plan, product)
        slots, known = slot_counts(product, entry)
        rect = entry.get("rectangleReadback") or {}
        patch = patches.get(pid) or {}
        planned_keys = [item["key"] for item in product.get("positions") or []]
        planned_keys += [item["key"] for item in product.get("detailImages") or []]
        rejected = sum(
            1 for key in planned_keys
            if (generation.get(key) or {}).get("status") == "rejected"
        )
        kept_original = entry.get("oldKept") if known and needs_main else None
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
                slots["verified"] if known and needs_main else None,
                entry.get("detailImages", 0),
                entry.get("detailNewImages", 0),
                patch.get("cappedPositions", capped_count(plan, pid)),
                rejected,
                kept_original,
                price_result(entry),
                entry.get("status", ""),
                product_verdict(entry, needs_main, known),
                readback_problems(entry),
                main_compare if product.get("positions") else "",
                detail_compare,
                slots["requested"] if needs_main else None,
                slots["retained"] if known and needs_main else None,
                slots["unresolved"] if needs_main else None,
                rectangle_result(entry) if needs_main else None,
                rect.get("beforeSlots") if needs_main else None,
                rect.get("afterSlots") if needs_main else None,
            ]
        )
        row = sheet.max_row
        for column, target in ((15, main_compare), (16, detail_compare)):
            cell = sheet.cell(row=row, column=column)
            if target:
                cell.hyperlink = target
                cell.font = UNDERLINE

    sheet.freeze_panes = "A2"
    widths = [16, 50, 9, 9, 12, 9, 9, 9, 9, 9, 9, 9, 8, 26, 32, 34, 15, 20, 16, 22, 16, 16]
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
            "按本批次选中的图位与图片设计执行，原图及成图标识见任务回执。",
        ),
        ("提示词", "逐图设计与执行结果见 internal-generation.json；生成报价（如有）见 image-quote.json"),
        (
            "核验范围",
            "主图按组、位次及 SKU 核对编辑详情。买家端另行检查。"
            "本次主图操作的位置上限为 %d。" % int(job.get("maxPosition") or common.DEFAULT_MAX_POSITION),
        ),
    ]
    counts = counts or progress(plan, generation, {}, patches, verification)
    if "main" in (plan.get("scopes") or ["main"]):
        rows.extend([("本次主图交付", main_delivery(counts)),
                     ("范围外3:4长图", rectangle_delivery(counts)),
                     ("商品独立终验", f"{counts['finalVerifiedProducts']}/{counts['targetProducts']} 个商品通过")])
        if counts["mainSlotReadback"]["productsPendingEvidence"]:
            rows.append(("补回执", "使用原任务目录只读运行 verify.py，逐图位对照原计划和上传记录。"))
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


def build_markdown(run, job, identity, plan, verification, generation, uploads, patches, label, counts=None):
    counts = counts or progress(plan, generation, uploads, patches, verification)
    entries = [verification.get(str(p["productId"])) or {} for p in plan["products"]]
    lines = [
        "# %s 图片批量优化（%s）" % (identity["shopName"], label),
        "",
        "- 店铺：%s" % identity["shopName"],
        "- 店铺ID：%s" % identity["venderId"],
        "- jdo Profile：%s" % job["profile"],
        "- 优化范围：%s" % scope_text(plan),
        "- 目标商品：%d 条" % counts["targetProducts"],
    ]
    if "main" in (plan.get("scopes") or ["main"]):
        lines.extend(["- " + main_delivery(counts), "- 范围外 3:4 长图：" + rectangle_delivery(counts)])
        if counts["mainSlotReadback"]["productsPendingEvidence"]:
            lines.append("- 使用原任务目录只读运行 verify.py，按原计划和上传记录补齐图位回执。")
    if "detail" in (plan.get("scopes") or []):
        lines.append("- 详情页：已回读图片 %d 张，换新 %d 张。" % (
            sum(entry.get("detailImages", 0) for entry in entries),
            sum(entry.get("detailNewImages", 0) for entry in entries),
        ))
    lines += [
        "- 图片计划 %d 张，新增生成 %d 张，复用已批准样张 %d 张。" %
        (counts["plannedAssets"], counts["newImagesSucceeded"], counts["approvedSamplesReused"]),
        "- 上传：%d，主图 PATCH：%d/%d 商品成功" % (
            counts["uploadedAssets"], counts["patchVerifiedProducts"], counts["targetProducts"],
        ),
        "- 独立终验：%d/%d 通过" % (
            counts["finalVerifiedProducts"], counts["targetProducts"],
        ),
        "- 买家端尚未核验。",
        "- 审核拒绝：%d 张（对应图片保留原图，明细见 Excel「审核拒绝明细」）" % sum(
            1 for value in generation.values() if value.get("status") == "rejected"
        ),
        "",
        "## 本次图片设计",
        "",
        "> " + "逐图设计与执行结果见 internal-generation.json；生成报价（如有）见 image-quote.json",
        "",
        "## 明细",
        "",
    ]
    for product, entry in zip(plan["products"], entries):
        needs_main = main_target(plan, product)
        slots, known = slot_counts(product, entry)
        facts = []
        if needs_main:
            if known:
                facts.append(f"目标主图位已核实换新 {slots['verified']}/{slots['requested']}")
            else:
                facts.append("目标主图位待核对")
            facts.append("范围外 3:4 长图" + rectangle_result(entry))
        if product.get("detailImages"):
            facts.append("详情换新 %s/%s" % (entry.get("detailNewImages", "待核"), entry.get("detailImages", "待核")))
        facts.extend(["SKU 价格" + price_result(entry), "状态 " + str(entry.get("status", "待核")),
                      product_verdict(entry, needs_main, known)])
        if entry.get("problems"):
            facts.append(readback_problems(entry))
        lines.append("- %s %s：%s" % (product["productId"], product["title"][:22], "，".join(facts)))
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
    if not plan:
        raise SystemExit("missing plan-batch.json")
    identity = common.load_json(run / "identity.json") or {
        "shopName": job["shopName"],
        "venderId": job["venderId"],
    }
    generation = common.load_json(run / "internal-generation.json") or {}
    uploads = common.load_json(run / "uploads.json") or {}
    patches = common.load_json(run / "patch-results.json") or {}
    if "--progress" in argv[2:]:
        print(json.dumps(progress(plan, generation, uploads, patches, verification or {}), ensure_ascii=False))
        return
    if not verification:
        raise SystemExit("missing final-verification.json; use --progress to read current receipts")
    label = str(job.get("label") or datetime.now().strftime("%Y%m%d"))

    counts = progress(plan, generation, uploads, patches, verification)
    xlsx = build_xlsx(run, job, identity, plan, verification, patches, generation, label, counts)
    workbook = openpyxl.load_workbook(xlsx)
    rejected_count = add_rejected_sheet(workbook, plan, generation)
    workbook.save(xlsx)
    if rejected_count:
        print("审核拒绝明细：%d 张（该图片保留原图）" % rejected_count)
    markdown, lines = build_markdown(
        run, job, identity, plan, verification, generation, uploads, patches, label, counts
    )
    print("saved", xlsx)
    print("saved", markdown)
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv)
