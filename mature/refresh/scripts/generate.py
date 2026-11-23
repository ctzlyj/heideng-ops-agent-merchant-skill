"""Generate host-designed images from the scoped plan, retaining original paid receipts."""

import argparse
import hashlib
import io
import json
import sys
import threading
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import no_window  # noqa: F401
import _common as common

from heideng_merchant.mature_image import MerchantImageClient
from heideng_merchant.image_models import MODELS, model_for
from heideng_merchant.creative_images import CreativeOrder, host_prompt
from heideng_merchant.state import FileLock
LOCK = threading.RLock()
def source_path(task, sources: Path) -> Path:
    key = task.get("sourceKey") or task["key"]
    path = sources / (key + ".img")
    if not path.exists():
        raise SystemExit("source image missing: %s (rerun download_sources.py)" % path)
    return path


class PinnedClient:
    def __init__(self, model, api_key, concurrency):
        if model not in MODELS:
            raise ValueError('merchant-image-model-not-configured')
        self.model = model
        self.client = MerchantImageClient(api_key, model=model)
        self.slots = threading.BoundedSemaphore(concurrency)

    def edit_image(self, *, prompt, images, size):
        with self.slots:
            return self.client.edit(prompt=prompt, images=images, size=size)


def work(key, item, client, paths):
    source = source_path(item, paths['sources'])
    design = paths['order'].quote['designs'][key]
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != design['sourceSha256']:
        raise ValueError('原图在报价后已变更')
    # Download receipts keep opaque .img names; the provider requires an actual image MIME/filename.
    with Image.open(io.BytesIO(raw)) as image:
        extension = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp','GIF':'.gif'}.get(image.format)
        image.verify()
    if not extension:
        raise ValueError('原图编码不受支持')
    with tempfile.TemporaryDirectory(prefix='refresh-reference-') as tmp:
        ref = Path(tmp)/('reference'+extension)
        ref.write_bytes(raw)
        with LOCK:
            if paths['stop'].is_set():
                return None
            paths['order'].reserve(key)
            record = {**design, 'status':'unknown', 'attempts':1, 'model':client.model}
            paths['ledger'][key] = record
            common.save_json(paths['ledger_path'], paths['ledger'])
        started = time.monotonic()
        try:
            data = client.edit_image(prompt=item['prompt'], images=[ref], size=design['size'])
            out = paths['generated']/(key+'.png')
            with Image.open(io.BytesIO(data)) as generated:
                generated.save(out, format='PNG')
            return dict(record, status='succeeded', elapsed=round(time.monotonic()-started, 1), bytes=out.stat().st_size)
        except Exception as error:
            paths['stop'].set()
            return dict(record, error=type(error).__name__)


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
                        "productId": task["productId"], "role": task.get("scope"), "url": task.get("currentUrl"),
                        "size":task.get("size") or paths["size"]}
        task["prompt"] = prompt
    context = {"kind": "image-refresh", "shop": {k: job[k] for k in ("profile", "venderId", "shopName")},
               "products": sorted({str(v["productId"]) for v in tasks.values()})}
    order = CreativeOrder(run, context, designs, pending, args.fee_approval_file,
                          models=job.get("imageModels") or MODELS)
    if args.quote_only:
        print(json.dumps(order.quote, ensure_ascii=False))
        return
    order.check()
    pending = [key for key in pending if key in order.selected]
    if not pending:
        print(json.dumps({'selectedUnits':[], 'deferredUnits':order.deferred}, ensure_ascii=False))
        if order.deferred:
            raise SystemExit(2)  # Pause the whole-store pipeline before upload/patch.
        return
    paths["order"] = order
    api_key = common.resolve_api_key()
    if not api_key:
        raise SystemExit('merchant LTS4AI Key required; use the masked merchant Key launcher after task/cost approval')
    models = order.models
    paths.update(ledger=ledger, ledger_path=ledger_path, stop=threading.Event())
    workers = max(1, min(int(job.get('concurrency') or 8), int(job.get('concurrentImageRequests') or 8)))
    per_client = max(1, (workers + len(models) - 1) // len(models))
    clients = {model: PinnedClient(model, api_key, per_client) for model in models}
    assignments = [(key, clients[model_for(index, models)]) for index, key in enumerate(pending)]
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
            if record is None:
                continue
            with LOCK:
                ledger[key] = record
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
        if key not in order.deferred and (ledger.get(key) or {}).get("status") not in ("succeeded", "rejected")
    ]
    print("done: succeeded=%d rejected=%d failed=%d total=%d"
          % (ok, len(rejected), len(failed_keys), len(tasks)), flush=True)
    if rejected:
        print("rejected keys (keep original image): %s" % rejected[:10], flush=True)
    if failed_keys:
        print("failed keys:", failed_keys[:10])
        raise SystemExit(1)
    if order.deferred:
        print(json.dumps({'selectedUnits':order.selected, 'deferredUnits':order.deferred,
                          'nextAction':'本次图位已完成；全店流水线等待其余图位分批完成或复用。'}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv)
