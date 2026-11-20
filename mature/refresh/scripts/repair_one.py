"""Rebuild one product after an external edit, so it can be patched again.

usage: python repair_one.py <run_dir> <productId>

The old snapshot no longer describes the live product when someone else edited
it between our PATCH and verification (groups/slots changed). This re-snapshots
that single product, replaces its plan entry, drops its patch result, then runs
patch.py / verify.py for that product only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common


def main(argv):
    if len(argv) < 3:
        raise SystemExit("usage: repair_one.py <run_dir> <productId>")
    run = Path(argv[1]).resolve()
    pid = int(argv[2])
    job = common.load_job(run)
    cli = common.connect(job)
    common.verify_identity(cli, job, run)

    detail = common.apply_detail(cli, pid)
    common.save_json(run / "products" / str(pid) / "before-apply.json", detail)

    fresh = common.build_plan(
        {pid: detail},
        None,
        int(job.get("maxPosition") or common.DEFAULT_MAX_POSITION),
        job.get("imageBase"),
        order=[pid],
        scopes=common.job_scopes(job),
        detail_prompt_template=job.get("detailPromptTemplate"),
        detail_size=job.get("detailSize"),
        positions=job.get("mainPositions"),
    )
    plan = common.load_json(run / "plan-batch.json")
    plan["products"] = [p for p in plan["products"] if int(p["productId"]) != pid]
    plan["products"].extend(fresh["products"])
    plan["tasks"].update(fresh["tasks"])
    plan["capped"] = [c for c in plan.get("capped") or [] if int(c["productId"]) != pid]
    plan["capped"].extend(fresh["capped"])

    status = None
    page = 1
    while page <= 20:
        response = cli.get(
            "jdo-product-status",
            "/rest/sp-product/v0/products",
            {"scopeSet": "productId,productStatus", "page": page, "pageSize": 100,
             "sortBy": "created", "sortType": "desc"},
        )
        rows = response.get("data") or []
        for row in rows:
            if int(row["productId"]) == pid:
                status = row.get("productStatus")
        if not rows or status is not None:
            break
        page += 1
    for product in plan["products"]:
        if int(product["productId"]) == pid:
            product["listStatus"] = status
    common.save_json(run / "plan-batch.json", plan)

    results = common.load_json(run / "patch-results.json") or {}
    results.pop(str(pid), None)
    common.save_json(run / "patch-results.json", results)

    product = next(p for p in plan["products"] if int(p["productId"]) == pid)
    print("replanned %s: groups=%d planned=%d listStatus=%s"
          % (pid, product["groupCount"], len(product["positions"]), status))
    print("next: python scripts/patch.py <run> %d && python scripts/verify.py <run> %d" % (pid, pid))


if __name__ == "__main__":
    main(sys.argv)

