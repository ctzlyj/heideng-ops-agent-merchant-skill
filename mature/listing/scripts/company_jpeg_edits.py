"""Merchant JPEG image edits; mature receipts, one provider, no paid fallback."""
import hashlib
import io
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image

MODELS = ("gpt-image-2.5",)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class CompanyClient:
    """Legacy JPEG boundary backed only by the parent merchant image client."""
    def __init__(self, key=None, clock=None, sleep=None):
        try:
            from heideng_merchant.mature_image import MerchantImageClient
        except ImportError:
            raise RuntimeError('Missing dependency heideng_merchant.mature_image.MerchantImageClient') from None
        self.client = MerchantImageClient(key)
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.slots = threading.BoundedSemaphore(4)
        self.lock = threading.Lock()
        self.next_start = 0.0

    def edit(self, *, model, prompt, source):
        if model not in MODELS:
            raise ValueError('Only merchant gpt-image-2.5 is supported; other providers are blocked')
        raw = Path(source).read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('Unsupported actual reference format')
        try:
            with self.slots:
                with self.lock:
                    delay = self.next_start - self.clock()
                    if delay > 0:
                        self.sleep(delay)
                    self.next_start = self.clock() + 1.0
                result = self.client.edit(prompt=prompt, images=[Path(source)], size='1024x1024')
            with Image.open(io.BytesIO(result)) as image:
                image.load()
                if image.format != 'JPEG' or image.size != (1024, 1024):
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


def generate_plan(plan, run, client=None):
    ledger_path=run/"generation.json"
    ledger=json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    sources=prepare_references(plan,run)
    todo=[]
    for source in sources:
        sha=source["sha"]
        record=ledger.get(sha)
        if record:
            if record.get("status") != "succeeded":
                raise RuntimeError("A request was already attempted; reconcile before retry")
            path=run/"generated"/(sha+".jpg")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["outputSha256"]:
                raise RuntimeError("Successful cached artifact changed")
        else:
            todo.append(source)
    if not todo:
        print("GENERATION COMPLETE (cached)", len(sources), flush=True)
        return
    key=resolve_api_key() if client is None else None
    if not key and client is None:
        raise RuntimeError("Missing HEIDENG_MERCHANT_LTS4AI_API_KEY")
    client=client or CompanyClient(key)
    (run/"generated").mkdir(exist_ok=True)
    for source in todo:
        ledger[source["sha"]]={"status":"request-started", "model":source["model"],
            "outputFormat":"jpeg", "externalAllowed":False, "attempts":1}
    save(ledger_path,ledger)
    def one(source):
        began=time.monotonic()
        raw,meta=client.edit(model=source["model"],prompt=plan["prompt"],source=source["reference"])
        (run/"generated"/(source["sha"]+".jpg")).write_bytes(raw)
        return {"status":"succeeded", "model":source["model"], "outputFormat":"jpeg",
            "externalAllowed":False,"attempts":1,"bytes":len(raw),"size":[1024,1024],
            "seconds":round(time.monotonic()-began,2),"outputSha256":hashlib.sha256(raw).hexdigest(),**meta}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(one,s):s for s in todo}
        for job in as_completed(jobs):
            source=jobs[job]
            try:
                record=job.result()
            except SafeGenerationError as exc:
                record={"status":"failed","model":source["model"],"category":exc.category,
                    "httpStatus":exc.status,"outputFormat":"jpeg","externalAllowed":False,"attempts":1}
            except Exception as exc:
                record={"status":"failed","model":source["model"],"category":type(exc).__name__,
                    "outputFormat":"jpeg","externalAllowed":False,"attempts":1}
            ledger[source["sha"]]=record
            save(ledger_path,ledger)
            print(source["sha"],json.dumps(record),flush=True)
    if not all(ledger[s["sha"]]["status"]=="succeeded" for s in sources):
        raise RuntimeError("Generation incomplete; nothing uploaded or changed")
    print("GENERATION COMPLETE",len(sources),flush=True)


def main():
    import argparse
    from hot_replica_mode import build_dynamic_prompt
    parser = argparse.ArgumentParser(description="Merchant JPEG remake, no publication or external fallback")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    if plan["prompt"].encode("utf-8") != build_dynamic_prompt(plan["title"]).encode("utf-8"):
        parser.error("Prompt differs from the user-finalized dynamic template")
    if not plan.get("sources") or len({s["sha"] for s in plan["sources"]}) != len(plan["sources"]):
        parser.error("Missing or duplicate source identities")
    for source in plan["sources"]:
        if source.get("model") not in MODELS or not Path(source["source"]).is_file():
            parser.error("Invalid merchant model or missing reference")
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if args.dry_run:
        print(json.dumps({"dryRun":True,"promptExact":True,"uniqueImages":len(plan["sources"]),
            "models":MODELS,"outputFormat":"jpeg","externalAllowed":False,
            "maxConcurrency":4,"maxStartsPerSecond":1},ensure_ascii=False))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = args.output/"generation-plan.sha256"
    if receipt.exists() and receipt.read_text(encoding="utf-8") != fingerprint:
        parser.error("Output belongs to a different plan; do not reuse receipts")
    receipt.write_text(fingerprint,encoding="utf-8")
    generate_plan(plan,args.output)


if __name__ == "__main__":
    main()
