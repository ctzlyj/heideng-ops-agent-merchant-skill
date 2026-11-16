"""Download every unique source image into <RUN>/sources.

usage: python download_sources.py <run_dir> [productId ...]

The plan already dedupes by URL, so each physical image is fetched once and
reused by every group. Two CDN hosts are tried per image because the store's
older jfs paths are not served by the img10/image prefix on all shops.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

DEFAULT_HOSTS = ["https://img10.360buyimg.com/imgzone/"]


def candidate_urls(item, job):
    urls = [item["absoluteUrl"]]
    for host in job.get("downloadHosts") or DEFAULT_HOSTS:
        if "/jfs/" in item["currentUrl"]:
            urls.append(host.rstrip("/") + "/" + item["currentUrl"])
    seen, result = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def source_path(item, sources):
    return sources / ((item.get("sourceKey") or common.image_key(item["currentUrl"])) + ".img")


def fetch(item, job):
    destination = source_path(item, job["sources"])
    if destination.exists() and destination.stat().st_size > 0:
        with Image.open(destination) as img:
            img.verify()
        return item["key"], "cached", destination.stat().st_size
    headers = {"Referer": "https://item.jd.com/", "User-Agent": "Mozilla/5.0 (Windows NT; Win64; x64)"}
    last_error = None
    for attempt in range(6):
        for url in candidate_urls(item, job["job"]):
            try:
                response = requests.get(url, timeout=60, headers=headers)
                response.raise_for_status()
                destination.write_bytes(response.content)
                with Image.open(destination) as img:
                    img.verify()
                return item["key"], "downloaded", len(response.content)
            except Exception as exc:  # noqa: BLE001 - try next host / retry
                last_error = exc
        time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("%s: %s" % (item["key"], last_error))


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: download_sources.py <run_dir> [productId ...]")
    run = Path(argv[1]).resolve()
    job_config = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    tasks = common.plan_tasks(plan, argv[2:])
    if not tasks:
        raise SystemExit("no planned images for the requested products")

    job = {
        "job": job_config,
        "sources": run / "sources",
    }
    job["sources"].mkdir(exist_ok=True)

    failures = []
    counters = {"downloaded": 0, "cached": 0}
    workers = int(job_config.get("downloadConcurrency") or 8)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, item, job): item for item in tasks.values()}
        for index, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            try:
                _, state, _ = future.result()
                counters[state] = counters.get(state, 0) + 1
            except Exception as exc:  # noqa: BLE001
                failures.append({"key": item["key"], "url": item["currentUrl"], "error": str(exc)[:200]})
            if index % 20 == 0:
                print("progress %d/%d" % (index, len(tasks)), flush=True)

    print("total:", len(tasks), "downloaded:", counters["downloaded"],
          "cached:", counters["cached"], "failures:", len(failures))
    if failures:
        common.save_json(run / "download-report.json", {"failures": failures})
        print("first failures:", [item["key"] for item in failures[:3]])
        raise SystemExit(1)
    print("all sources ready")


if __name__ == "__main__":
    main(sys.argv)
