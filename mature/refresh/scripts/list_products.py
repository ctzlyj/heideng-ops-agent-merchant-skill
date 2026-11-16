"""Fill job.productIds from the shop product list.

usage: python list_products.py <run_dir> [--limit N] [--status 103,104] [--keep]

--limit 0 (default) means every product in the shop. --keep appends to the
existing list instead of replacing it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common


def parse_args(argv):
    limit, statuses, keep = 0, set(), False
    index = 2
    while index < len(argv):
        item = argv[index]
        if item == "--limit":
            limit = int(argv[index + 1])
            index += 2
            continue
        if item == "--status":
            statuses = {int(part) for part in argv[index + 1].split(",") if part.strip()}
            index += 2
            continue
        if item == "--keep":
            keep = True
            index += 1
            continue
        raise SystemExit("unknown argument: %s" % item)
    return limit, statuses, keep


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: list_products.py <run_dir> [--limit N] [--status 103,104] [--keep]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    limit, statuses, keep = parse_args(argv)
    cli = common.connect(job)
    common.verify_identity(cli, job, run)

    collected, page = [], 1
    while True:
        response = cli.get(
            "jdo-product-status",
            "/rest/sp-product/v0/products",
            {"scopeSet": "productId,productStatus,productName", "page": page, "pageSize": 100,
             "sortBy": "created", "sortType": "desc"},
        )
        rows = response.get("data") or []
        for row in rows:
            if statuses and int(row.get("productStatus") or 0) not in statuses:
                continue
            collected.append(int(row["productId"]))
        total = int((response.get("paginationData") or {}).get("totalItems") or 0)
        print("page %d: %d rows (collected %d / %d)" % (page, len(rows), len(collected), total), flush=True)
        if not rows or len(collected) >= total or (limit and len(collected) >= limit):
            break
        page += 1
    if limit:
        collected = collected[:limit]
    if keep:
        merged = list(dict.fromkeys([int(item) for item in job.get("productIds") or []] + collected))
    else:
        merged = collected
    job["productIds"] = merged
    common.save_json(run / "job.json", job)
    print("written productIds:", len(merged))


if __name__ == "__main__":
    main(sys.argv)
