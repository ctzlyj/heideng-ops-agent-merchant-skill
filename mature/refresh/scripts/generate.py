"""Generate host-designed images from the scoped plan, retaining original paid receipts."""

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

from heideng_merchant.mature_image import MerchantImageClient
from heideng_merchant.creative_images import CreativeOrder, host_prompt
from heideng_merchant.state import FileLock
LOCK = threading.RLock()
QUOTA_MARKERS = ("额度已用尽", "2006", "2007", "insufficient", "quota", "rate limit")
CONTENT_MARKERS = ("moderation", "safety", "invalid_request", "rejected by the safety")
def is_quota_error(text: str) -> bool:
    lowered = str(text).lower()
    return any(marker.lower() in lowered for marker in QUOTA_MARKERS)


def is_content_rejection(text: str) -> bool:
    lowered = str(text).lower()
    return any(marker.lower() in lowered for marker in CONTENT_MARKERS)


def source_path(task, sources: Path) -> Path:
    key = task.get("sourceKey") or task["key"]
    path = sources / (key + ".img")
    if not path.exists():
        raise SystemExit("source image missing: %s (rerun download_sources.py)" % path)
    return path


class PinnedClient:
    """Thin mature sufy adapter; no company SDK, model switching or retries."""
    def __init__(self, first_model, *, max_image_requests=None, api_key=None, **kwargs):
        if first_model != 'gpt-image-2.5':raise RuntimeError('merchant-image-model-not-configured')
        self.client=MerchantImageClient(api_key)
        self.last_image_model='gpt-image-2.5'
        self._image_semaphore=threading.BoundedSemaphore(max(1,int(max_image_requests or 1)))
    def edit_image(self, *, prompt, images, size):
        with self._image_semaphore:
            return self.client.edit(prompt=prompt,images=images,size=size)


def probe_task(models, task, sources, size, api_key):
    """First approved planned image, not a schema/extra-output paid probe."""
    if list(dict.fromkeys(models)) != ['gpt-image-2.5']:
        raise RuntimeError('merchant-image-model-not-configured')
    try:
        client=PinnedClient('gpt-image-2.5',api_key=api_key)
        data=client.edit_image(prompt=task['prompt'],images=[source_path(task,sources)],size=task.get('size') or size)
        return 'ok','gpt-image-2.5',data,''
    except Exception as error:
        detail=str(error)
        if is_quota_error(detail):return 'quota','',b'',detail
        if is_content_rejection(detail):return 'content','',b'',detail
        return 'error','',b'',detail


def preflight(models, tasks, sources, size, api_key, ledger, ledger_path, order):
    """Probe up to five pending tasks before spawning workers."""
    if not tasks:
        return "empty", "", b"", None, "", []
    skipped, detail = [], ""
    for task in list(tasks.values())[:5]:
        order.reserve(task["key"])
        if ledger is not None:
            ledger[task['key']]={**order.quote['designs'][task['key']], 'status':'unknown','attempts':1,'error':'Original submission result not yet confirmed; no automatic replay'}
            common.save_json(ledger_path,ledger)
        status, model, image, detail = probe_task(models, task, sources, size, api_key)
        if status == "ok":
            return "ok", model, image, task, "", skipped
        if status == "quota":
            return "blocked", "", b"", task, detail, skipped
        if status == "content":
            skipped.append(task["key"])
            continue
        return "error", "", b"", task, detail, skipped
    return "content", "", b"", None, detail, skipped


def work(key, item, client, paths):
    started=time.time()
    try:
        source=source_path(item,paths['sources'])
        with LOCK:
            paths['order'].reserve(key)
            paths['ledger'][key]={**paths['order'].quote['designs'][key], 'status':'unknown','attempts':1,'error':'Original submission result not yet confirmed; no automatic replay'}
            common.save_json(paths['ledger_path'],paths['ledger'])
        data=client.edit_image(prompt=item['prompt'],images=[source],size=item.get('size') or paths['size'])
        out=paths['generated']/(key+'.png');out.write_bytes(data)
        with Image.open(out) as check:check.verify()
        return {'status':'succeeded','attempts':1,'model':client.last_image_model,'elapsed':round(time.time()-started,1),'bytes':len(data)}
    except Exception as error:
        return {'status':'unknown','attempts':1,'error':type(error).__name__}


def main(argv):
    parser = argparse.ArgumentParser(description="Generate the selected host-designed product images")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("product_ids", nargs="*")
    parser.add_argument("--wait-quota", type=float, default=0, help="legacy option; unknown submissions are preserved")
    parser.add_argument("--image-prompts-file", type=Path)
    parser.add_argument("--fee-approval-file", type=Path)
    parser.add_argument("--quote-only", action="store_true")
    args = parser.parse_intermixed_args(argv[1:])
    run = args.run_dir.resolve()
    with FileLock(run / ".state" / "refresh-generation.lock"):
        return generate(run, args)


def generate(run, args):
    pids = args.product_ids
    job = common.load_job(run)
    plan = common.load_json(run / "plan-batch.json")
    if not plan:
        raise SystemExit("missing plan-batch.json; run build_plan.py first")
    tasks = common.plan_tasks(plan, pids)
    if not tasks:
        raise SystemExit("no planned images for the requested products")

    paths = {
        "sources": run / "sources",
        "generated": run / "generated",
        "size": job.get("size") or "1024x1024",
    }
    paths["generated"].mkdir(parents=True, exist_ok=True)
    ledger_path = run / "internal-generation.json"
    ledger = common.load_json(ledger_path) or {}

    unresolved=[key for key in tasks if key in ledger and ledger[key].get('status') not in ('succeeded','rejected')]
    if unresolved:raise SystemExit('Original image submission unresolved; preserve original ledger/output and do not automatically regenerate')

    pending = [
        key for key in tasks
        if (ledger.get(key) or {}).get("status") not in ("succeeded", "rejected")
    ]

    prompt_file = args.image_prompts_file or job.get("imagePromptsFile") or run / "host-prompts.json"
    prompts = common.load_json(Path(prompt_file)) or {}
    for key in tasks.keys() - set(pending):
        record = ledger[key]
        supplied = prompts.get(key) if isinstance(prompts, dict) else None
        if record.get("prompt") and supplied and record["prompt"] != supplied.strip():
            raise ValueError("图片已有原请求回执；修改设计须作为明确的重做任务")
    if not pending and not args.quote_only:
        print("All selected images already have terminal receipts")
        return
    designs = {}
    for key, task in tasks.items():
        prompt = host_prompt(prompts, key)
        reference = source_path(task, paths['sources'])
        designs[key] = {"prompt": prompt, "sourceSha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                        "productId": task["productId"], "role": task.get("scope"), "url": task.get("currentUrl")}
        task["prompt"] = prompt
    context = {"kind": "image-refresh", "shop": {k: job[k] for k in ("profile", "venderId", "shopName")},
               "products": sorted({str(v["productId"]) for v in tasks.values()})}
    order = CreativeOrder(run, context, designs, pending, args.fee_approval_file)
    if args.quote_only:
        print(json.dumps(order.quote, ensure_ascii=False))
        return
    order.check()
    paths["order"] = order
    api_key = common.resolve_api_key()
    if not api_key:
        raise SystemExit('merchant LTS4AI Key required; use the masked merchant Key launcher after task/cost approval')
    models = list(dict.fromkeys(str(item) for item in (job.get('imageModels') or ['gpt-image-2.5'])))
    if models != ['gpt-image-2.5']:raise SystemExit('merchant-image-model-not-configured')
    paths.update(ledger=ledger,ledger_path=ledger_path)
    if pending:
        while True:
            probe_set = {key: tasks[key] for key in pending[:5]}
            status, model, image, task, detail, skipped = preflight(
                models, probe_set, paths["sources"], paths["size"], api_key, ledger, ledger_path, order
            )
            for key in skipped:
                ledger[key] = {**designs[key], "status": "rejected",
                               "error": "内容审核拒绝（任务级，保留原图）"}
                pending = [item for item in pending if item != key]
            if skipped:
                common.save_json(ledger_path, ledger)
                print("preflight skipped %d moderation-rejected image(s)" % len(skipped), flush=True)
            if status == "blocked":
                print("PREFLIGHT_BLOCKED: %s" % detail, flush=True)
                print("原图片请求结果/扣费未确认；保留台账，不自动重提。", flush=True)
                raise SystemExit(3)
            if status == "error":
                raise SystemExit("Original first image request unresolved; preserve ledger and do not replay")
            if status == "content":
                print("PREFLIGHT_REJECTED: probed images were blocked by content moderation; "
                      "其余任务继续，被拒图片保留原图。", flush=True)
            if status == "ok" and task is not None:
                key = task["key"]
                (paths["generated"] / (key + ".png")).write_bytes(image)
                ledger[key] = {**designs[key], "status": "succeeded", "attempts": 1, "model": model,
                               "elapsed": 0, "bytes": len(image), "preflight": True}
                common.save_json(ledger_path, ledger)
                pending = [item for item in pending if item != key]
                print("preflight ok via %s; %d pending" % (model, len(pending)), flush=True)
                if model != models[0]:
                    models = [model] + [item for item in models if item != model]
            break

    workers = int(job.get("concurrency") or 8)
    per_client = max(1, int(job.get("concurrentImageRequests") or workers)) // max(len(models), 1)
    clients = [
        PinnedClient(model, api_key=api_key, max_image_requests=per_client)
        for model in models
    ]
    assignments = [(key, clients[index % len(clients)]) for index, key in enumerate(pending)]
    print("tasks: %d pending: %d" % (len(tasks), len(pending)), flush=True)

    done_in_run = 0
    started = time.time()
    print("workers: %d, image requests in flight per client: %d" % (workers, per_client), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(work, key, tasks[key], client, paths): key
            for key, client in assignments
        }
        for future in as_completed(futures):
            key = futures[future]
            record = future.result()
            with LOCK:
                ledger[key] = {**designs[key], **record}
                try:
                    common.save_json(ledger_path, ledger)
                except OSError as exc:  # noqa: PERF203 - keep generating
                    # A locked ledger must not kill the batch; rebuild_ledger.py
                    # can recover the files afterwards.
                    print("ledger save skipped: %s" % str(exc)[:120], flush=True)
            done_in_run += 1
            if record["status"] not in ("succeeded", "rejected"):
                print("failed", key, record.get("error", "")[:120], flush=True)
            if done_in_run % 20 == 0 or done_in_run == len(assignments):
                spent = time.time() - started
                rate = done_in_run / max(spent / 3600, 1e-6)
                left = len(assignments) - done_in_run
                eta = (left / rate * 60) if rate else 0
                print(
                    "progress %d/%d %.1f%% rate=%.0f/h eta=%.0fmin"
                    % (done_in_run, len(assignments), 100.0 * done_in_run / max(len(assignments), 1),
                       rate, eta),
                    flush=True,
                )

    try:
        common.save_json(ledger_path, ledger)
    except OSError as exc:  # noqa: PERF203
        print("final ledger save failed: %s" % str(exc)[:160], flush=True)
    ok = sum(1 for key in tasks if (ledger.get(key) or {}).get("status") == "succeeded")
    rejected = [key for key in tasks if (ledger.get(key) or {}).get("status") == "rejected"]
    failed_keys = [
        key for key in tasks
        if (ledger.get(key) or {}).get("status") not in ("succeeded", "rejected")
    ]
    print("done: succeeded=%d rejected=%d failed=%d total=%d"
          % (ok, len(rejected), len(failed_keys), len(tasks)), flush=True)
    if rejected:
        print("rejected keys (keep original image): %s" % rejected[:10], flush=True)
    if failed_keys:
        print("failed keys:", failed_keys[:10])
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
