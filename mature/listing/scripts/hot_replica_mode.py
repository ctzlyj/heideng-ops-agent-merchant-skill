# -*- coding: utf-8 -*-
"""Source grouping and category eligibility for commercial image replications."""
from __future__ import annotations

import re
from pathlib import Path


def no_brand_allowed(reference: dict) -> bool:
    """True when the target category accepts brandId=-1 (无品牌)."""
    brands = reference.get("brands") or []
    return any(int(b.get("brandId") or 0) == -1 for b in brands)


def brand_gate(reference: dict, category_label: str = "") -> dict:
    """Hard pre-generation gate. Returns {'ok': bool, ...} evidence dict."""
    if no_brand_allowed(reference):
        return {
            "ok": True,
            "decision": "PROCEED",
            "evidence": "类目授权品牌列表包含 brandId=-1（无品牌），可无品牌上架",
            "category": category_label,
        }
    brand_names = [str(b.get("brandName") or "") for b in reference.get("brands") or []]
    return {
        "ok": False,
        "decision": "SKIPPED_BRAND_REQUIRED",
        "evidence": "类目授权品牌列表不含 brandId=-1（无品牌），平台将拒绝无品牌商品",
        "category": category_label,
        "authorizedBrandCount": len(brand_names),
    }


def style_image_mode(source: dict) -> dict:
    """Classify JD source main-image layout from per-SKU page image lists.

    JD has two real layouts:
      - shared: every style exposes the same gallery sequence (only the SKU
        first/spec image differs);
      - series: at least two styles expose different scene sequences after
        position 1, so each style group must own its complete sequence.

    The check deliberately ignores position 1: that position is represented by
    the per-SKU spec image in both layouts. Comparing scene positions avoids
    misclassifying ordinary shared-gallery products as series products.
    2026-10-09 root cause: 100165442873 was a 7-style series product, but the
    old chain copied the entry style's 5-image sequence to every group.
    """
    sequences: dict[str, list[str]] = {}
    for variant in source.get("variants") or []:
        attrs = variant.get("sourceAttributes") or {}
        style = str(next(iter(attrs.values()), variant.get("sourceSku") or ""))
        urls = [str(url) for url in (variant.get("sourceImageUrls") or []) if str(url)]
        if style and len(urls) >= 2 and style not in sequences:
            sequences[style] = urls
    scene_sequences = {tuple(urls[1:]) for urls in sequences.values()}
    mode = "series" if len(sequences) >= 2 and len(scene_sequences) >= 2 else "shared"
    return {
        "mode": mode,
        "styleSequences": sequences,
        "evidence": (
            f"{len(sequences)} styles / {len(scene_sequences)} unique scene sequences"
            if mode == "series" else "all captured styles share one scene sequence"
        ),
    }


def square_pad_image(path: Path) -> tuple[int, int]:
    """Pad a generated image to exactly 1:1 (JD spu_main/sku_main rule).

    Non-square generated SKU/main images are rejected by the local preflight
    ("sku_main 必须为1:1"). Regenerating wastes quota, so pad losslessly with
    row-wise edge extension (keeps vertical gradients natural, no stretching,
    no cropping). The file is modified in place; returns the final size.
    2026-09-30 verified on 10201583840642 SKU图1.png (1086x1448 -> 1448x1448,
    published and platform-verified afterwards).
    """
    from PIL import Image

    with Image.open(path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        if width == height:
            return width, height
    import numpy as np

    arr = np.asarray(rgb)
    if width < height:
        pad = height - width
        left = np.repeat(arr[:, :1, :], pad // 2, axis=1)
        right = np.repeat(arr[:, -1:, :], pad - pad // 2, axis=1)
        arr = np.concatenate([left, arr, right], axis=1)
    else:
        pad = width - height
        top = np.repeat(arr[:1, :, :], pad // 2, axis=0)
        bottom = np.repeat(arr[-1:, :, :], pad - pad // 2, axis=0)
        arr = np.concatenate([top, arr, bottom], axis=0)
    out = Image.fromarray(arr)
    out.save(path, "PNG")
    return out.size
