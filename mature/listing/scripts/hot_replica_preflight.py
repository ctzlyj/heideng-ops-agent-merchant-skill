# -*- coding: utf-8 -*-
"""Hot-replica preflight for one source SKU (formal, parameterized).

Read the host's observed drops and continuity analysis, then produce a scoped
inventory and an individually designed generation or reuse decision for each image.
"""
import argparse, json, pathlib, sys, os
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import jd_product_mover as mover  # noqa: E402
import hot_replica_mode as hotmode  # noqa: E402

def read_analysis(path):
    if path is None:
        raise RuntimeError("Use --analysis-file with actual host image review; no model request submitted")
    analysis = mover.read_json(path)
    if not isinstance(analysis, dict) or not isinstance(analysis.get("drops"), list) or not isinstance(analysis.get("continuity"), dict):
        raise ValueError("Host analysis must contain drops and continuity")
    return analysis


def build_sheet(folder: pathlib.Path, items, out_path: pathlib.Path, cell_w=300, cols=10):
    from PIL import Image, ImageDraw
    thumbs = []
    for item in items:
        im = Image.open(folder / item["localPath"]).convert("RGB")
        im.thumbnail((cell_w, 1400))
        thumbs.append(im)
    h = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    cw = max(t.width for t in thumbs) + 8
    ch = h + 36
    sheet = Image.new("RGB", (cols * cw, rows * ch), (240, 240, 240))
    d = ImageDraw.Draw(sheet)
    for n, im in enumerate(thumbs, 1):
        r, c = divmod(n - 1, cols)
        x, y = c * cw + 4, r * ch + 30
        sheet.paste(im, (x, y))
        d.rectangle([x, r * ch, x + 46, r * ch + 26], fill=(200, 0, 0))
        d.text((x + 10, r * ch + 7), f"#{n}", fill=(255, 255, 255))
    sheet.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sku", required=True, help="source SKU/SPU id; draft folder is <draft-root>/<sku>_*")
    ap.add_argument("--reference", required=True,
                    help="target category reference JSON (feeds the hard brand gate)")
    ap.add_argument("--draft-root", default=str(pathlib.Path(os.environ.get("HEIDENG_MERCHANT_HOME", str(pathlib.Path.home() / ".heideng-merchant"))) / "work/listing/migrations"))
    ap.add_argument("--work-dir", default=None,
                    help="artifact dir (default <draft>/hot-replica): sheets, continuity plan, remake plan")
    ap.add_argument("--analysis-file", type=pathlib.Path, help="Actual host review JSON: drops list and continuity {spec,pages}; not a company model")
    ap.add_argument("--image-prompts-file", type=pathlib.Path, help="JSON mapping imageKey to the complete host design")
    ap.add_argument("--model", default="host-analysis", help="source label for the recorded analysis")
    ap.add_argument("--drop-passes", type=int, default=2)
    ap.add_argument("--page-attempts", type=int, default=6)
    a = ap.parse_args()
    SKU = a.sku
    root = pathlib.Path(a.draft_root)
    folder = next(root.glob(SKU + "_*"), None)
    if not folder:
        print(f"FAIL: draft folder not found for {SKU} under {root}")
        return 1
    work = pathlib.Path(a.work_dir) if a.work_dir else folder / "hot-replica"
    work.mkdir(parents=True, exist_ok=True)

    # Hard brand gate BEFORE any plan / generation quota.
    reference = mover.read_json(pathlib.Path(a.reference))
    listing = mover.read_json(folder / "listing.json")
    gate = hotmode.brand_gate(reference, str(reference.get("category", {}).get("name") or ""),
                              (listing.get("product") or {}).get("brandId"))
    (work / f"brand-gate-{SKU}.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    if not gate["ok"]:
        print("BRAND_GATE", gate["decision"], "|", gate["evidence"])
        return 2
    print("BRAND_GATE PROCEED |", gate["evidence"])

    details = sorted([i for i in listing["images"] if i.get("role") == "detail"],
                     key=lambda x: int(x.get("order") or 0))

    analysis = read_analysis(a.analysis_file)
    if details:
        build_sheet(folder, details, work / f"drop-sheet-{SKU}.png")
    drop_by_index = {int(row["i"]): str(row["reason"]) for row in analysis["drops"]}
    if any(i < 1 or i > len(details) for i in drop_by_index):
        raise ValueError("Host review refers to an absent detail image")
    dropped_details = {details[i - 1]["imageKey"]: drop_by_index[i]
                       for i in sorted(drop_by_index) if 1 <= i <= len(details)}
    kept = [item for n, item in enumerate(details, 1) if n not in drop_by_index]
    print(f"drop pass: {len(dropped_details)} dropped, {len(kept)} kept | {dropped_details}")

    details = kept
    sheet_path = work / f"preflight-sheet-{SKU}.png"
    if details:
        build_sheet(folder, details, sheet_path)
    continuity = analysis["continuity"]
    spec = str(continuity.get("spec") or continuity.get("unifiedStyleSpec") or "")
    rows = continuity.get("pages") or []
    pages_by_i = {int(row["i"]): row for row in rows}
    if len(rows) != len(details) or set(pages_by_i) != set(range(1, len(details) + 1)):
        raise ValueError("Host continuity review must cover each retained detail image once")
    pages = [pages_by_i[i] for i in range(1, len(details) + 1)]

    kept_idx = list(zip(details, pages))
    cont_images = []
    for new_pos, (item, page) in enumerate(kept_idx, 1):
        cont_images.append({
            "order": new_pos, "displayIndex": new_pos, "imageKey": item["imageKey"],
            "source": item["localPath"], "output": f"重制-固定/详情图/{item['imageKey']}.png",
            "title": str(page.get("title") or "")[:40],
            "continuousWithPrev": bool(page.get("prev")) and new_pos > 1,
            "continuousWithNext": False,
            "topContract": "", "bottomContract": "",
        })
    for i in range(len(cont_images) - 1):
        cont_images[i]["continuousWithNext"] = cont_images[i + 1]["continuousWithPrev"]
    cont = {"sku": SKU, "model": a.model, "sheet": sheet_path.name if details else None,
            "unifiedStyleSpec": spec[:800],
            "images": cont_images}
    (work / f"continuity-plan-{SKU}.json").write_text(
        json.dumps(cont, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"continuity: {len(cont_images)} kept pages, drops={dropped_details}")

    # dynamic-prompt remake plan (flexible main count)
    mains_src = [i["localPath"] for i in sorted(listing["images"], key=lambda x: int(x.get("order") or 0))
                 if i.get("role") == "spu_main"]
    if len(mains_src) < 2:
        print(f"FAIL: spu_main images must be >= 2, got {len(mains_src)}")
        return 1
    images, order = [], 0
    for n, src in enumerate(mains_src, 1):
        order += 1
        images.append({"imageKey": f"SPU-MAIN-{n:02d}", "role": "spu_main", "order": order,
                       "source": src, "output": f"重制-固定/主图/SPU-MAIN-{n:02d}.png"})
    for new_pos, (item, page) in enumerate(kept_idx, 1):
        order += 1
        images.append({"imageKey": item["imageKey"], "role": "detail", "order": new_pos,
                       "source": item["localPath"],
                       "output": f"重制-固定/详情图/{item['imageKey']}.png"})
    sku_mains = [i for i in listing["images"] if i.get("role") == "sku_main"]
    seen = {}
    for im in sku_mains:
        seen.setdefault(im["localPath"], im["imageKey"])
    style_scenes = sorted([i for i in listing["images"] if i.get("role") == "style_scene"],
                          key=lambda x: (str(x.get("imageKey") or "")))
    main_source_to_key = {i["localPath"]: i["imageKey"]
                          for i in listing["images"] if i.get("role") == "spu_main"}
    scene_source_to_key: dict[str, str] = {}
    style_scene_mapping: list[dict] = []
    for row in listing["skus"]:
        style = str(row.get("styleAlias") or "")
        if any(m.get("style") == style for m in style_scene_mapping):
            continue
        style_order = int(row.get("styleOrder") or 0)
        for item in style_scenes:
            if not str(item.get("imageKey") or "").startswith(f"STYLE-{style_order:02d}-POS"):
                continue
            source_path = str(item.get("localPath") or "")
            if source_path in main_source_to_key:
                target_key = main_source_to_key[source_path]
            elif source_path in scene_source_to_key:
                target_key = scene_source_to_key[source_path]
            else:
                target_key = str(item["imageKey"])
                order += 1
                images.append({"imageKey": target_key, "role": "style_scene", "order": order,
                               "source": source_path,
                               "output": f"重制-固定/款式组/{target_key}.png"})
                scene_source_to_key[source_path] = target_key
            position = int(item.get("order") or 0)
            style_scene_mapping.append({"style": style, "pos": position, "imageKey": target_key})
    series_mode = bool(style_scene_mapping)
    deannotate = []
    for n, (src, key) in enumerate(seen.items(), 1):
        out = f"重制-固定/SKU图/SKU图{n}.png"
        images.append({"imageKey": f"SKU-MAIN-{n:03d}", "source": src, "output": out})
        if not series_mode:
            deannotate.append({"imageKey": f"SKU-REP-{n:03d}", "source": src, "output": f"重制-固定/款式代表/SKU-REP-{n:03d}.png"})
    units = images + deannotate
    prompts = mover.read_json(a.image_prompts_file) if a.image_prompts_file else analysis.get("imagePrompts", {})
    source_sheet = [{"imageKey": row["imageKey"], "source": row["source"], "role": row.get("role") or "sku"}
                    for row in units]
    (work / f"design-input-{SKU}.json").write_text(json.dumps(source_sheet, ensure_ascii=False, indent=2), encoding="utf-8")
    from heideng_merchant.creative_images import host_prompt
    for row in units:
        design = prompts.get(row["imageKey"])
        if isinstance(design, dict) and design.get("reuse") is True:
            row["reuse"] = True
        else:
            row["prompt"] = host_prompt(prompts, row["imageKey"])
    plan = {"task": f"{SKU} hot-replica (host design + continuity)",
            "title": listing["product"]["title"], "mode": "host-design+continuity",
            "styleImageMode": "series" if series_mode else "shared",
            "styleSceneMapping": style_scene_mapping,
            "sourceSku": SKU,
            "droppedDetails": dropped_details,
            "skuMainPolicy": "host-design",
            "images": images, "deannotate": deannotate}
    (work / f"remake-plan-{SKU}.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"plan: styleImageMode={plan['styleImageMode']} "
          f"styleScenes={len(scene_source_to_key)} styleSlots={len(style_scene_mapping)} "
          f"mains={len(mains_src)} details={len(kept_idx)} sku={len(seen)} "
          f"reps={len(deannotate)} drops={len(dropped_details)}")
    print(f"使用 company_jpeg_edits.py --plan {work / ('remake-plan-' + SKU + '.json')} --draft {folder} "
          f"--output {work} --store-config <已核店配置> --dry-run 查看增量报价")
    return 0


if __name__ == "__main__":
    sys.exit(main())
