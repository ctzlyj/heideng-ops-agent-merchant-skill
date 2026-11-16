"""Snapshot live apply bodies and build <RUN>/plan-batch.json.

usage: python build_plan.py <run_dir> [productId ...]
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401  (hide jdo-cli console windows)
import _common as common


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: build_plan.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job = common.load_job(run)
    use_cache = "--cache" in argv
    args = [item for item in argv[2:] if item != "--cache"]
    pids = common.requested_pids(job, args)
    scopes = common.job_scopes(job)

    cli = common.connect(job)
    identity = common.verify_identity(cli, job, run)
    print("identity:", identity["venderId"], identity["shopName"], flush=True)

    snapshots = {}
    workers = int(job.get("fetchConcurrency") or 6)

    if use_cache:
        for pid in pids:
            detail = common.load_json(run / "products" / str(pid) / "before-apply.json")
            if not detail:
                raise SystemExit("missing cached snapshot for %s" % pid)
            snapshots[pid] = detail
        print("reused cached snapshots:", len(snapshots), flush=True)

    def fetch(pid):
        detail = common.apply_detail(cli, pid)
        common.save_json(run / "products" / str(pid) / "before-apply.json", detail)
        return pid, detail

    if not use_cache:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, pid): pid for pid in pids}
            for index, future in enumerate(as_completed(futures), 1):
                pid, detail = future.result()
                snapshots[pid] = detail
                if index % 25 == 0 or index == len(pids):
                    print("snapshots %d/%d" % (index, len(pids)), flush=True)

    plan = common.build_plan(
        snapshots,
        job["promptTemplate"],
        int(job.get("maxPosition") or common.DEFAULT_MAX_POSITION),
        job.get("imageBase"),
        order=pids,
        scopes=scopes,
        detail_prompt_template=job.get("detailPromptTemplate"),
        detail_size=job.get("detailSize"),
        positions=job.get("mainPositions"),
    )
    # Record the authoritative list status so verify can prove it did not move.
    pending = {int(product["productId"]) for product in plan["products"]}
    page = 1
    while pending and page <= 20:
        response = cli.get(
            "jdo-product-status",
            "/rest/sp-product/v0/products",
            {"scopeSet": "productId,productStatus", "page": page, "pageSize": 100,
             "sortBy": "created", "sortType": "desc"},
        )
        rows = response.get("data") or []
        for row in rows:
            pid = int(row["productId"])
            if pid in pending:
                pending.discard(pid)
                for product in plan["products"]:
                    if int(product["productId"]) == pid:
                        product["listStatus"] = row.get("productStatus")
        if not rows:
            break
        page += 1
    common.save_json(run / "plan-batch.json", plan)

    main_tasks = sum(1 for task in plan["tasks"].values() if task.get("scope") == "main")
    detail_tasks = sum(1 for task in plan["tasks"].values() if task.get("scope") == "detail")
    print("scope: %s" % "+".join(scopes))
    if plan.get("positionFilter"):
        print("main positions: %s" % plan["positionFilter"])
    print(
        "products: %d, main images: %d, detail images: %d, capped slots: %d"
        % (len(plan["products"]), main_tasks, detail_tasks, len(plan["capped"]))
    )
    for product in plan["products"]:
        print(
            "  %d groups=%d main=%d detail=%d rect=%d ggt=%d %s"
            % (
                product["productId"],
                product["groupCount"],
                product["uniqueImages"],
                len(product.get("detailImages") or []),
                product["rectImages"],
                product["ggtCount"],
                product["title"][:34],
            )
        )
    for product in plan["products"]:
        if product["rectImages"]:
            print("  RECT productId=%d images=%d (3:4 rectangles are out of scope)"
                  % (product["productId"], product["rectImages"]))
        if not product["title"]:
            print("  WARN empty title for", product["productId"])


if __name__ == "__main__":
    main(sys.argv)
