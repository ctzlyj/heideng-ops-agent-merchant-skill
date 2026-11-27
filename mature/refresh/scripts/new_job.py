"""Scaffold a run directory with job.json.

usage:
  python new_job.py <run_dir> --profile pop-xxx --vender-id 123 \
      --shop-name 店铺名 --products 1001,1002 [--image-prompts-file designs.json] \
      [--lnk <店铺浏览器.lnk>] [--max-position 9] [--concurrency 8]

Build the inventory before authoring a complete prompt for each image key.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common
from heideng_merchant.refresh_selection import configure


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--vender-id", required=True, type=int)
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--products", default="")
    parser.add_argument("--image-prompts-file", "--prompt-file", help="宿主逐图设计 JSON，按 plan-batch.json 的图片 key 保存完整提示词")
    parser.add_argument("--lnk", default="")
    parser.add_argument("--max-position", type=int, default=common.DEFAULT_MAX_POSITION)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--scope", help="main / detail / both")
    parser.add_argument("--main-positions", default="", help="comma separated, e.g. 1")
    parser.add_argument("--detail-size", default="")
    parser.add_argument("--main-selection", choices=("per-link", "sku", "remaining-colors"))
    parser.add_argument("--sku-id", action="append", default=[], help="可重复，批次实际影响的 SKU")
    parser.add_argument("--from-main-run", type=Path, help="其余颜色组所依照的原首图任务目录")
    parser.add_argument("--copy-batch-report", type=Path, help="shop-copy batch-status 的 JSON，按源商品核对目标")
    parser.add_argument("--exclude-source-product", action="append", default=[], help="排除该来源及其历次申请")
    parser.add_argument("--max-images", type=int, help="本次范围内不同成图的数量上限")
    parser.add_argument("--approved-sample", type=Path, help="商家选定的原任务 generated 目录中的成图")
    parser.add_argument("--approved-prompt-file", "--design-brief-file", type=Path, help="商家已给的 UTF-8 设计要求或提示词原文")
    parser.add_argument("--reuse-approved-prompt", action="store_true", help="商家明确沿用时，加载本店记住的已批准提示词")
    parser.add_argument("--use-host-design", action="store_true", help="商家将本次设计交给宿主")
    return parser.parse_args(argv[1:])


def main(argv):
    args = parse_args(argv)
    run = Path(args.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    for folder in ("products", "sources", "generated", "patch-bodies"):
        (run / folder).mkdir(exist_ok=True)

    job = {
        "profile": args.profile,
        "venderId": args.vender_id,
        "shopName": args.shop_name,
        "productIds": [
            int(part)
            for part in str(args.products).replace("，", ",").split(",")
            if part.strip()
        ],
        "imagePromptsFile": str(Path(args.image_prompts_file).resolve()) if args.image_prompts_file else "",
        "imageBase": common.DEFAULT_IMAGE_BASE,
        "size": "1024x1024",
        "maxPosition": args.max_position,
        "concurrency": args.concurrency,
        "scope": args.scope or "both",
        "mainPositions": [
            int(part) for part in str(args.main_positions).replace("，", ",").split(",") if part.strip()
        ],
        "detailSize": args.detail_size,
        "detailWrite": False,
        "browserShortcut": args.lnk,
    }
    path = run / "job.json"
    if path.exists():
        raise SystemExit("%s already exists; edit it instead of re-scaffolding" % path)
    configure(job, args)
    common.save_json(path, job)
    print("created", path)
    print("products:", len(job["productIds"]))


if __name__ == "__main__":
    main(sys.argv)
