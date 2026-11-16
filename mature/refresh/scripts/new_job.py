"""Scaffold a run directory with job.json.

usage:
  python new_job.py <run_dir> --profile pop-xxx --vender-id 123 \
      --shop-name 店铺名 --products 1001,1002 [--prompt-file prompt.txt] \
      [--lnk <店铺浏览器.lnk>] [--max-position 9] [--concurrency 8]

The prompt template keeps one {title} placeholder; everything else is literal.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--vender-id", required=True, type=int)
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--products", default="")
    parser.add_argument("--prompt-file")
    parser.add_argument("--lnk", default="")
    parser.add_argument("--max-position", type=int, default=common.DEFAULT_MAX_POSITION)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--scope", default="both", help="main / detail / both")
    parser.add_argument("--main-positions", default="", help="comma separated, e.g. 1")
    parser.add_argument("--detail-size", default="")
    return parser.parse_args(argv[1:])


def main(argv):
    args = parse_args(argv)
    run = Path(args.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    for folder in ("products", "sources", "generated", "patch-bodies"):
        (run / folder).mkdir(exist_ok=True)

    template = common.DEFAULT_PROMPT_TEMPLATE
    if args.prompt_file:
        template = Path(args.prompt_file).read_text(encoding="utf-8-sig").strip()
        if not template:
            raise SystemExit("prompt file is empty")

    job = {
        "profile": args.profile,
        "venderId": args.vender_id,
        "shopName": args.shop_name,
        "productIds": [
            int(part)
            for part in str(args.products).replace("，", ",").split(",")
            if part.strip()
        ],
        "promptTemplate": template,
        "imageBase": common.DEFAULT_IMAGE_BASE,
        "size": "1024x1024",
        "maxPosition": args.max_position,
        "concurrency": args.concurrency,
        "scope": args.scope,
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
    common.save_json(path, job)
    print("created", path)
    print("products:", len(job["productIds"]))


if __name__ == "__main__":
    main(sys.argv)
