"""Build per-product before/after comparison sheets plus one overview image.

usage: python compare.py <run_dir> [productId ...]

Each comparison keeps the full image (no crop) with the original on the left
and the regenerated image on the right, one row per main-image slot.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

FONT = "C:/Windows/Fonts/msyh.ttc"
ROW_LABEL_H = 42
GAP = 14
MARGIN = 18
TITLE_H = 58
THUMB = 260
DETAIL_W = 620


def fonts():
    return (
        ImageFont.truetype(FONT, 26),
        ImageFont.truetype(FONT, 20),
        ImageFont.truetype(FONT, 18),
    )


def slot_label(group_id, position):
    if group_id == "0000000000":
        return "公共组 位%s%s" % (position, "（全组共用）" if position != 1 else "")
    return "颜色组%s 位%s" % (group_id[-5:], position)


def detail_row(label, before_path, after_path):
    with Image.open(before_path) as before_img:
        before_image = before_img.convert("RGB")
    with Image.open(after_path) as after_img:
        after_image = after_img.convert("RGB")
    for image in (before_image, after_image):
        if image.width > DETAIL_W:
            image.thumbnail((DETAIL_W, DETAIL_W * 4))
    return label, before_image, after_image


def build_detail_compare(run, product, comparisons, font, font_note):
    pid = int(product["productId"])
    rows = []
    for index, image in enumerate(product.get("detailImages") or [], 1):
        before_path = run / "sources" / ((image.get("sourceKey") or common.image_key(image["currentUrl"])) + ".img")
        after_path = run / "generated" / (image["key"] + ".png")
        if not before_path.exists() or not after_path.exists():
            continue
        rows.append(detail_row("详情页 %d" % index, before_path, after_path))
    if not rows:
        return None
    row_height = max(max(before.height, after.height) for _, before, after in rows)
    cell_width = max(max(before.width, after.width) for _, before, after in rows)
    canvas_w = MARGIN * 2 + cell_width * 2 + GAP
    canvas_h = TITLE_H + len(rows) * (ROW_LABEL_H + row_height + GAP) + MARGIN
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (MARGIN, 14),
        "%d %s（详情页换新 左前右后）" % (pid, product["title"][:34]),
        fill="black",
        font=font,
    )
    y = TITLE_H
    for label, before_image, after_image in rows:
        draw.text((MARGIN, y + 8), label, fill="#333333", font=font_note)
        y += ROW_LABEL_H
        canvas.paste(before_image, (MARGIN, y))
        canvas.paste(after_image, (MARGIN + cell_width + GAP, y))
        draw.rectangle(
            [MARGIN, y, MARGIN + before_image.width - 1, y + before_image.height - 1],
            outline="#bbbbbb",
        )
        draw.rectangle(
            [MARGIN + cell_width + GAP, y,
             MARGIN + cell_width + GAP + after_image.width - 1, y + after_image.height - 1],
            outline="#e0533d",
        )
        draw.text((MARGIN + 6, y + 6), "前", fill="#333333", font=font_note)
        draw.text((MARGIN + cell_width + GAP + 6, y + 6), "后", fill="#e0533d", font=font_note)
        y += row_height + GAP
    out = comparisons / ("%d-detail-compare.png" % pid)
    canvas.save(out, "PNG")
    print("built", out, canvas.size, flush=True)
    return out


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: compare.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    identity = common.load_json(run / "identity.json") or {
        "shopName": job["shopName"],
        "venderId": job["venderId"],
    }
    sources = run / "sources"
    generated = run / "generated"
    comparisons = run / "comparisons"
    comparisons.mkdir(exist_ok=True)
    font, font_note, font_small = fonts()

    overview_rows = []
    for product in common.plan_products(plan, argv[2:]):
        pid = int(product["productId"])
        rows = []
        for position in product["positions"]:
            key = position["key"]
            source_key = position.get("sourceKey") or common.image_key(position["url"])
            before_path = sources / (source_key + ".img")
            after_path = generated / (key + ".png")
            if not before_path.exists() or not after_path.exists():
                continue
            with Image.open(before_path) as before_img:
                before_image = before_img.convert("RGB")
            with Image.open(after_path) as after_img:
                after_image = after_img.convert("RGB")
            rows.append(
                (
                    slot_label(position["group"], position["position"]),
                    before_image,
                    after_image,
                )
            )
        if product.get("detailImages"):
            build_detail_compare(run, product, comparisons, font, font_note)
        if not rows:
            if not product.get("detailImages"):
                print("skip", pid, "no local before/after pair", flush=True)
            continue

        row_height = max(max(before.height, after.height) for _, before, after in rows)
        cell_width = rows[0][1].width
        canvas_w = MARGIN * 2 + cell_width * 2 + GAP
        canvas_h = TITLE_H + len(rows) * (ROW_LABEL_H + row_height + GAP) + MARGIN
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (MARGIN, 14),
            "%d %s（主图换新 左前右后）" % (pid, product["title"][:36]),
            fill="black",
            font=font,
        )
        y = TITLE_H
        for label, before_image, after_image in rows:
            draw.text((MARGIN, y + 8), label, fill="#333333", font=font_note)
            y += ROW_LABEL_H
            canvas.paste(before_image, (MARGIN, y))
            canvas.paste(after_image, (MARGIN + before_image.width + GAP, y))
            draw.rectangle(
                [MARGIN, y, MARGIN + before_image.width - 1, y + before_image.height - 1],
                outline="#bbbbbb",
                width=1,
            )
            draw.rectangle(
                [
                    MARGIN + before_image.width + GAP,
                    y,
                    MARGIN + before_image.width + GAP + after_image.width - 1,
                    y + after_image.height - 1,
                ],
                outline="#e0533d",
                width=1,
            )
            draw.text((MARGIN + 6, y + 6), "前", fill="#333333", font=font_note)
            draw.text(
                (MARGIN + before_image.width + GAP + 6, y + 6), "后", fill="#e0533d", font=font_note
            )
            y += row_height + GAP
        out = comparisons / ("%d-compare.png" % pid)
        canvas.save(out, "PNG")
        print("built", out, canvas.size, flush=True)

        thumbs = []
        for _, before_image, after_image in rows[:3]:
            before_thumb = before_image.copy()
            before_thumb.thumbnail((THUMB, THUMB))
            after_thumb = after_image.copy()
            after_thumb.thumbnail((THUMB, THUMB))
            thumbs.append((before_thumb, after_thumb))
        overview_rows.append((pid, product["title"], thumbs))

    if 1 < len(overview_rows) <= 60:
        label_w = 430
        row_h = (
            max(
                max(before.height, after.height)
                for _, _, thumbs in overview_rows
                for before, after in thumbs
            )
            + 8
        )
        pair_w = THUMB * 2 + 6
        canvas_w = MARGIN * 2 + label_w + 3 * pair_w
        canvas_h = 46 + len(overview_rows) * row_h
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (MARGIN, 10),
            "%s %d 条商品主图换新总览（每条前3位 左前右后）"
            % (identity["shopName"], len(overview_rows)),
            fill="black",
            font=font,
        )
        y = 46
        for pid, title, thumbs in overview_rows:
            draw.text(
                (MARGIN, y + 6), "%d %s" % (pid, title[:22]), fill="#333333", font=font_small
            )
            x = MARGIN + label_w
            for before, after in thumbs:
                canvas.paste(before, (x, y))
                draw.rectangle([x, y, x + before.width - 1, y + before.height - 1], outline="#bbbbbb")
                canvas.paste(after, (x + before.width + 6, y))
                draw.rectangle(
                    [
                        x + before.width + 6,
                        y,
                        x + before.width + 6 + after.width - 1,
                        y + after.height - 1,
                    ],
                    outline="#e0533d",
                )
                x += pair_w
            y += row_h
            draw.line([(MARGIN, y), (canvas_w - MARGIN, y)], fill="#dddddd")
        out = run / "all-links-overview.png"
        canvas.save(out, "PNG")
        print("overview saved:", out, canvas.size)
    elif len(overview_rows) > 60:
        print(
            "overview skipped: %d products would need an unusable canvas; "
            "per-product comparisons are complete" % len(overview_rows)
        )


if __name__ == "__main__":
    main(sys.argv)
