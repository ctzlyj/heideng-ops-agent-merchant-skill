"""Merchant photo generation with the mature durable per-image receipt."""
from __future__ import annotations
import hashlib,io,json,os,re,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image

MODELS=('gpt-image-2.5',)
class GenerationUnknown(RuntimeError):pass
class GenerationRejected(RuntimeError):
 def __init__(self,status,retry_after=0):
  self.status,self.retry_after=status,retry_after;super().__init__(f'model rejected request: HTTP {status}')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 raw=json.dumps(value,ensure_ascii=False,indent=2)
 for n in range(10):
  temp=path.with_name(path.name+'.'+os.urandom(4).hex()+'.tmp')
  try:
   with temp.open('w',encoding='utf-8') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   os.replace(temp,path);return
  except OSError:
   temp.unlink(missing_ok=True)
   if n==9:raise
   time.sleep(.15*(n+1))
def load(path,default=None):return json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).is_file() else default

def image_bytes(raw):
 with Image.open(io.BytesIO(raw)) as im:
  im.load()
  if min(im.size)<1:raise ValueError('empty generated image')
  if im.format=='JPEG':return raw
  out=io.BytesIO();im.convert('RGB').save(out,'JPEG',quality=95);return out.getvalue()

class CompanyPhotoClient:
 """Legacy call surface; the parent merchant adapter owns all transport/key handling."""
 def __init__(self,key=None,per_model=4,starts_per_second=1):
  self.capacity=per_model
  try:
   from heideng_merchant.mature_image import MerchantImageClient
  except ImportError:
   raise ValueError('Missing dependency heideng_merchant.mature_image.MerchantImageClient') from None
  self.client=MerchantImageClient(key)
  self.slots={m:threading.BoundedSemaphore(per_model) for m in MODELS}
  self.locks={m:threading.Lock() for m in MODELS};self.next={m:0. for m in MODELS};self.period=1/starts_per_second
 def edit(self,*,model,prompt,photos,size):
  if model not in MODELS:raise ValueError('Only merchant gpt-image-2.5 is supported; other image/text/video providers are blocked')
  refs=[]
  for p in photos:
   raw=Path(p).read_bytes()
   with Image.open(io.BytesIO(raw)) as im:
    im.load()
    if im.format not in ('PNG','JPEG','WEBP'):raise ValueError('invalid photo encoding')
   refs.append(Path(p))
  with self.slots[model]:
   with self.locks[model]:
    delay=self.next[model]-time.monotonic()
    if delay>0:time.sleep(delay)
    self.next[model]=time.monotonic()+self.period
   try:return image_bytes(self.client.edit(prompt=prompt,images=refs,size=size))
   except (Exception,SystemExit) as e:raise GenerationUnknown(type(e).__name__) from None

def key_from_environment():
 try:
  from heideng_merchant.mature_image import merchant_key
 except ImportError:
  raise ValueError('Missing dependency heideng_merchant.mature_image.merchant_key') from None
 key=merchant_key()
 if not key:raise ValueError('Missing HEIDENG_MERCHANT_LTS4AI_API_KEY; no alternate credential lookup')
 return key

def fingerprint(task):
 if 'referenceImages' in task:raise ValueError('Competitor images cannot be product generation references')
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',task.get('id','')):raise ValueError('Invalid task id')
 if not task.get('prompt') or not task.get('photos'):raise ValueError('Missing prompt or real photos')
 if task.get('size') not in ('1024x1024','1024x1536','1536x1024'):raise ValueError('Unsupported photo size')
 if any(not Path(p).is_file() for p in task['photos']):raise ValueError('Missing real photo')
 content={'prompt':task['prompt'],'photos':[sha(p) for p in task['photos']],'size':task['size'],'role':task.get('role')}
 return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def generation_scope(manifest, tasks):
    # Bind the authorized shop and deliverables; changing copy within that scope is allowed.
    identity = manifest['store']
    return {'task': manifest['packageId'], 'shop': str(identity['venderId']),
            'profile': identity['profile'], 'model': MODELS[0],
            'outputs': [{'id': t['id'], 'role': t['role'], 'sku': t.get('skuKey'), 'sources': t['sourceSha256'],
                         'action': 'reuse' if t.get('reusePhoto') else 'generate'} for t in tasks]}


def pending_ids(tasks, out, redo=()):
    ledger = load(Path(out)/'generation.json', {})
    return [t['id'] for t in tasks if not t.get('reusePhoto') and
            (t['id'] in redo or (ledger.get(t['id']) or {}).get('status') != 'SUCCEEDED')]


def generate_tasks(tasks, out, *, client=None, redo=None, approval=None, scope=None):
    from heideng_merchant.state import FileLock
    from heideng_merchant.image_budget import validate_approval, reserve_request

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    redo = set(redo or [])
    tasks = [task for task in tasks if not task.get('reusePhoto')]
    ids = [task['id'] for task in tasks]
    if len(ids) != len(set(ids)) or not redo.issubset(ids):
        raise ValueError('Invalid duplicate/redo task ids')
    if (out/'.generation.lock').exists():
        raise GenerationUnknown('发现旧版任务锁，请先核实旧 worker 与原回执')

    with FileLock(out/'.generation.guard'):
        ledger_path = out/'generation.json'
        ledger = load(ledger_path, {})
        receipt_path = out/'tasks.json'
        receipts = load(receipt_path, {})
        todo = []
        lock = threading.Lock()
        began = time.monotonic()
        for task in tasks:
            name = task['id']
            current = fingerprint(task)
            old = ledger.get(name) or {}
            status = old.get('status')
            old_key = old.get('fingerprint') or receipts.get(name)
            path = out/'generated'/f'{name}.jpg'
            if status in ('STARTED', 'UNKNOWN'):
                if name in redo or current != old_key or not path.is_file():
                    raise GenerationUnknown(f'{name} 的上次生成结果待核对，请先查原回执')
                image_bytes(path.read_bytes())
                ledger[name] = dict(old, status='SUCCEEDED', sha256=sha(path),
                                    localPath=str(path.relative_to(out)), recovered=True)
                atomic_json(ledger_path, ledger)
                continue
            if old_key and old_key != current and name not in redo:
                raise ValueError('Task changed: request an explicit single-image redo')
            if status == 'SUCCEEDED':
                if not path.is_file() or sha(path) != old['sha256']:
                    raise ValueError('Cached generated file changed')
                if name not in redo:
                    continue
            todo.append((task, current))

        if todo:
            units = approval.get('units') if isinstance(approval, dict) else None
            needed = {task['id'] for task, _ in todo}
            if not isinstance(units, list) or not needed.issubset(units) or not set(units).issubset(ids):
                raise ValueError('付费图片需要与当前商品、素材范围和新增请求数一致的商家批准')
            validate_approval(approval, scope=scope, units=units)
            if approval['maxRequests'] < len(needed):
                raise ValueError('新增图片数超过请求上限，请按已批准张数调整计划')
            if client is None:
                client = CompanyPhotoClient(key_from_environment())

        def work(task, current):
            name = task['id']
            path = out/'generated'/f'{name}.jpg'
            model = MODELS[0]
            started = time.monotonic()
            with lock:
                old = ledger.get(name) or {}
                prior = None
                if name in redo and old.get('status') == 'SUCCEEDED':
                    prior = {'status':'SUCCEEDED', 'sha256':old['sha256'],
                             'receiptHash': hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()}
                reserve_request(out.parent, approval, scope=scope, units=units,
                                request_id=name, previous_receipt=prior)
                if name in redo and path.exists():
                    archive = out/'history'
                    archive.mkdir(exist_ok=True)
                    os.replace(path, archive/f'{name}-{time.time_ns()}.jpg')
                record = {'status':'STARTED', 'model':model, 'fingerprint':current,
                          'approvalRef':approval['approvalRef'], 'previousReceipt':prior, 'attempts':[]}
                ledger[name] = record
                receipts[name] = current
                atomic_json(ledger_path, ledger)
                atomic_json(receipt_path, receipts)
            try:
                raw = client.edit(model=model, prompt=task['prompt'], photos=task['photos'], size=task['size'])
                data = image_bytes(raw)
                path.parent.mkdir(exist_ok=True)
                tmp = path.with_suffix('.tmp')
                tmp.write_bytes(data)
                os.replace(tmp, path)
                outcome = dict(record, status='SUCCEEDED', sha256=sha(path), localPath=str(path.relative_to(out)))
            except GenerationRejected as error:
                outcome = dict(record, status='REJECTED', attempts=[{'model':model, 'status':'REJECTED', 'httpStatus':error.status}])
            except Exception as error:
                outcome = dict(record, status='UNKNOWN', error=type(error).__name__)
            with lock:
                ledger[name] = dict(outcome, seconds=round(time.monotonic()-started, 2))
                atomic_json(ledger_path, ledger)

        if todo:
            with ThreadPoolExecutor(max_workers=max(1, min(12, int(getattr(client, 'capacity', 4))))) as pool:
                futures = [pool.submit(work, task, current) for task, current in todo]
                for future in as_completed(futures):
                    future.result()
        selected = [ledger[name] for name in ids]
        report = {'successCount':sum(r['status']=='SUCCEEDED' for r in selected),
                  'unknownCount':sum(r['status']=='UNKNOWN' for r in selected),
                  'failedCount':sum(r['status']=='REJECTED' for r in selected),
                  'seconds':round(time.monotonic()-began,2),
                  'modelsUsed':sorted({r['model'] for r in selected if r.get('model')}),
                  'ledger':ledger, 'submittedCount':len(todo), 'modelsSubmitted':list(MODELS) if todo else []}
        atomic_json(out/'generation-result.json', report)
        return report
