"""Merchant JPEG image edits; mature receipts, one provider, no paid fallback."""
import hashlib
import io
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from heideng_merchant.image_models import MODELS, model_for


def save(path, value):
    from heideng_merchant.safety import atomic_json
    atomic_json(path, value)


class CompanyClient:
    """Legacy JPEG boundary backed only by the parent merchant image client."""
    def __init__(self, key=None, clock=None, sleep=None):
        try:
            from heideng_merchant.mature_image import MerchantImageClient
        except ImportError:
            raise RuntimeError('Missing dependency heideng_merchant.mature_image.MerchantImageClient') from None
        self.factory = MerchantImageClient
        self.key = key
        self.clients = {}
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.slots = {m: threading.BoundedSemaphore(4) for m in MODELS}
        self.lock = {m: threading.Lock() for m in MODELS}
        self.next_start = {m: 0.0 for m in MODELS}

    def prepare(self, model):
        if model not in MODELS:
            raise ValueError('Unsupported merchant image model')
        with self.lock[model]:
            if model not in self.clients:
                self.clients[model] = self.factory(self.key, model=model)

    def edit(self, *, model, prompt, source, size='1024x1024'):
        self.prepare(model)
        raw = Path(source).read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('Unsupported actual reference format')
        try:
            with self.slots[model]:
                with self.lock[model]:
                    delay = self.next_start[model] - self.clock()
                    if delay > 0:
                        self.sleep(delay)
                    self.next_start[model] = self.clock() + 1.0
                result = self.clients[model].edit(prompt=prompt, images=[Path(source)], size=size)
            with Image.open(io.BytesIO(result)) as image:
                image.load()
                if image.format != 'JPEG' or (size == '1024x1024' and image.size != (1024, 1024)):
                    raise ValueError('Unexpected image format or dimensions')
            return result, {'provider': 'lts4ai', 'model': model}
        except (Exception, SystemExit) as exc:
            raise SafeGenerationError(type(exc).__name__) from None


def resolve_api_key():
    try:
        from heideng_merchant.mature_image import merchant_key
    except ImportError:
        raise RuntimeError('Missing dependency heideng_merchant.mature_image.merchant_key') from None
    return merchant_key()


class SafeGenerationError(Exception):
    def __init__(self, category, status=None):
        self.category, self.status = category, status
        super().__init__("Merchant image request outcome unknown; reconcile before retry")


def prepare_references(plan, run):
    directory = run/"references"
    directory.mkdir(exist_ok=True)
    result = []
    for source in plan["sources"]:
        raw = Path(source["source"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha"]:
            raise ValueError("Source content changed since planning")
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            extension = {"PNG":"png", "JPEG":"jpg", "WEBP":"webp"}.get(image.format)
        if not extension:
            raise ValueError("Unsupported actual reference format")
        path = directory / (source["sha"]+"."+extension)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError("Reference artifact changed")
        path.write_bytes(raw)
        result.append({**source, "reference":str(path)})
    return result


def generate_plan(plan, run, client=None, *, approval_file=None, quote_only=False):
    from heideng_merchant.state import FileLock
    with FileLock(run / ".state" / "jpeg-generation.lock"):
        return _generate_plan(plan, run, client, approval_file, quote_only)


def _generate_plan(plan, run, client, approval_file, quote_only):
    from heideng_merchant.creative_images import CreativeOrder, host_prompt
    from heideng_merchant.safety import safe_join
    ledger_path = run / "generation.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    sources = prepare_references(plan, run)
    todo, designs, reused, seen = [], {}, {}, set()
    for source in sources:
        key = source.get("imageKey", source["sha"])
        if key in seen or Path(key).name != key:
            raise ValueError("Invalid or duplicate image identity")
        source["imageKey"] = key
        local = safe_join(run, "generated/" + key + ".jpg")
        seen.add(key)
        if source.get("reuse") is True:
            if key in ledger and ledger[key].get("status") != "succeeded":
                raise RuntimeError("A previous request is unresolved; reconcile before changing source")
            reused[key] = source["sha"]
            continue
        record = ledger.get(key)
        if not source.get("prompt") and record and record.get("status") == "succeeded":
            if hashlib.sha256(local.read_bytes()).hexdigest() != record["outputSha256"]:
                raise RuntimeError("Successful cached artifact changed")
            continue
        prompt = host_prompt({key: source.get("prompt")}, key)
        if source.get("model") is not None and source["model"] not in MODELS:
            raise ValueError("Unsupported merchant image model")
        designs[key] = {"prompt": prompt, "sourceSha256": source["sha"], "role": source.get("role"),
                        "source": source["source"], "size": source.get("size") or "1024x1024"}
        record = ledger.get(key)
        if record:
            if record.get("status") != "succeeded":
                raise RuntimeError("A request was already attempted; reconcile before retry")
            if hashlib.sha256(local.read_bytes()).hexdigest() != record["outputSha256"]:
                raise RuntimeError("Successful cached artifact changed")
            if record.get("prompt") and record["prompt"] != prompt:
                raise ValueError("Cached output belongs to another prompt")
        else:
            todo.append(source)
    shop = plan.get("shop")
    if not isinstance(shop, dict) or not shop.get("venderId") or not shop.get("profile"):
        raise ValueError("Missing shop identity in the image plan")
    context = {"kind": "commercial-replica", "shop": shop, "product": plan["sourceProduct"]}
    pinned = {s["imageKey"]: s["model"] for s in sources if s["imageKey"] in designs and s.get("model")}
    models = MODELS
    if pinned:
        if pinned.keys() == designs.keys() and len(set(pinned.values())) == 1:
            models = (next(iter(pinned.values())),)
        else:
            context["modelAssignments"] = pinned
    order = CreativeOrder(run, context, designs, [s["imageKey"] for s in todo],
                          approval_file, reused=reused, models=models)
    if not set(pinned.values()).issubset(order.models):
        raise ValueError("Image design requests a model outside the frozen quote")
    if quote_only:
        print(json.dumps(order.quote, ensure_ascii=False))
        return
    if todo:
        order.check()
        selected = set(order.selected)
        todo = [source for source in todo if source['imageKey'] in selected]
        if todo:
            client = client or CompanyClient(resolve_api_key())
        (run / "generated").mkdir(exist_ok=True)
        lock = threading.Lock()

        assignments = [(source, pinned.get(source["imageKey"], model_for(i, order.models)))
                       for i, source in enumerate(todo)]
        if hasattr(client, 'prepare'):
            for model in {model for _,model in assignments}:
                client.prepare(model)

        def one(source, model):
            key = source["imageKey"]
            with lock:
                order.reserve(key)
                ledger[key] = {"status": "request-started", "attempts": 1, "model": model, **designs[key]}
                save(ledger_path, ledger)
            try:
                options = {"size": source["size"]} if source.get("size") else {}
                raw, meta = client.edit(model=model, prompt=source["prompt"],
                                        source=source["reference"], **options)
                (run / "generated" / (key + ".jpg")).write_bytes(raw)
                record = {"status": "succeeded", "outputSha256": hashlib.sha256(raw).hexdigest(),
                          "bytes": len(raw), **meta}
            except Exception as exc:
                record = {"status": "unknown", "category": type(exc).__name__}
            with lock:
                ledger[key].update(record)
                save(ledger_path, ledger)

        with ThreadPoolExecutor(max_workers=4 * len(order.models)) as pool:
            for future in as_completed([pool.submit(one, source, model) for source, model in assignments]):
                future.result()
    if any(ledger[key]['status'] != "succeeded" for key in designs if key in ledger):
        raise RuntimeError("Generation incomplete; reconcile original receipts")
    if getattr(order, 'deferred', []):
        result = {'selectedUnits': order.selected, 'deferredUnits':order.deferred,
                  'nextAction':'本次选定图位已就绪；其余图位需复用或另行批准后完成整套复刻。'}
        print(json.dumps(result, ensure_ascii=False))
        return result
    print("GENERATION COMPLETE", len(sources), flush=True)


def remake_sources(plan, draft):
    from heideng_merchant.safety import safe_join
    from heideng_merchant.lts4ai_client import calculate_custom_canvas, nearest_ratio, read_image_dimensions, resolve_size
    entries = plan["images"] + plan.get("deannotate", [])
    result = []
    for row in entries:
        path = safe_join(draft, row["source"])
        size = row.get('size')
        if not size:
            # Historical plans without an explicit quality used the 1K pixel canvases.
            quality = str(row.get('quality') or '1K').upper()
            ratio = '1:1'
            if row.get('role') == 'detail':
                dimensions = read_image_dimensions(path)
                if dimensions:
                    ratio = nearest_ratio(*dimensions)
            if quality == '2K':
                width, height = ratio.split(':')
                size = calculate_custom_canvas(width,height,quality)['size']
            else:
                size = resolve_size(ratio, quality, path)
        result.append({**row, "source": str(path), "sha": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "size": size})
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate host-designed images from a scoped product plan")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft", type=Path, help="original replication draft for a remake plan")
    parser.add_argument("--store-config", type=Path)
    parser.add_argument("--fee-approval-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from heideng_merchant.safety import safe_join
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    if args.draft:
        if not args.store_config:
            parser.error("Use the verified shop configuration with --draft")
        store = json.loads(args.store_config.read_text(encoding="utf-8-sig"))["store"]
        shop = {k: store[k] for k in ("venderId", "profile", "shopName")}
        plan = {"shop": shop, "sourceProduct": plan["sourceSku"], "sources": remake_sources(plan, args.draft)}
    if not plan.get("sources"):
        parser.error("Missing sources")
    args.output.mkdir(parents=True, exist_ok=True)
    result = generate_plan(plan, args.output, approval_file=args.fee_approval_file, quote_only=args.dry_run)
    if args.draft and not args.dry_run:
        for source in plan["sources"]:
            if result and source['imageKey'] in result.get('deferredUnits', []):
                continue
            target = safe_join(args.draft, source["output"])
            if not Path(source["output"]).parts or Path(source["output"]).parts[0] != "重制-固定":
                raise ValueError("Unexpected remake output path")
            target.parent.mkdir(parents=True, exist_ok=True)
            artifact = Path(source["source"]) if source.get("reuse") else args.output / "generated" / (source["imageKey"] + ".jpg")
            with Image.open(artifact) as image:
                image.save(target, format="PNG")


if __name__ == "__main__":
    main()
