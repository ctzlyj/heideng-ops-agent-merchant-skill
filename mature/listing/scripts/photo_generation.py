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


def inspect_attempts(tasks, out, scope, selected=None):
    """A point-in-time, read-only reconciliation; repeat it under the writer lock before spending."""
    from heideng_merchant.safety import read_json, safe_join
    out = Path(out)
    ledger = load(out/'generation.json', {})
    receipts = load(out/'tasks.json', {})
    budget = read_json(safe_join(out.parent, '.state/paid-image-budget.json'), {})
    latest = {}
    for reservation_id, request in budget.get('requests', {}).items():
        if request.get('state') != 'reserving':
            latest[request['unit']] = (reservation_id, request)
    chosen = set(selected or ())
    ids = [task['id'] for task in tasks if not task.get('reusePhoto')]
    if chosen - set(ids):
        raise ValueError('指定的图号未包含在原生成计划中')
    rows = []
    parents = {}
    # Budget entries may predate generation.json if the process stopped between the two writes.
    for task in tasks:
        unit = task['id']
        if task.get('reusePhoto') or (chosen and unit not in chosen):
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', unit):
            raise ValueError('Invalid task id')
        old = ledger.get(unit, {})
        reservation_id, entry = latest.get(unit, (None, {}))
        status = old.get('status') or 'NOT_STARTED'
        linked = (old.get('reservationId') == reservation_id if old.get('reservationId')
                  else bool(old.get('approvalRef')) and old['approvalRef'] == entry.get('approvalRef'))
        if reservation_id and not linked:
            status = 'RESERVED_WITHOUT_RECEIPT'
        output = safe_join(out, f'generated/{unit}.jpg')
        if status in ('STARTED', 'UNKNOWN') and output.is_file():
            old_key = old.get('fingerprint') or receipts.get(unit)
            # A filename alone cannot prove that bytes came from this attempt.
            result = (read_json(safe_join(out, f'attempts/{reservation_id}.result.json'), {})
                      if reservation_id else {})
            if (old_key and result.get('fingerprint') == old_key and old_key == fingerprint(task)
                    and result.get('sha256') == sha(output)):
                try:
                    image_bytes(output.read_bytes())
                except (ValueError, OSError):
                    pass
                else:
                    status = 'LOCAL_RESULT'
        uncertain = status in ('STARTED', 'UNKNOWN', 'RESERVED_WITHOUT_RECEIPT')
        if uncertain and reservation_id:
            parents[unit] = reservation_id
        rows.append({'unit':unit, 'status':status, 'reservationId':reservation_id,
                     'chargeKnown':False, 'previousApprovalRef':entry.get('approvalRef'),
                     'originalReceipt':str(out/'generation.json') if old else None})
    quote = None
    if parents and (not chosen or chosen == set(parents)):
        quote = {'scope':dict(scope, possibleDuplicateCharge=True, unresolvedRequests=parents),
                 'units':sorted(parents), 'maxRequests':len(parents), 'actualAmount':None,
                 'pricing':'原请求仍可能计费；每张另发一次，需要商家批准本次额外费用。'}
    return {'readOnly':True, 'submittedCount':0, 'providerChargeStatus':'unknown',
            'rows':rows, 'replacementQuote':quote}


def preserve_attempt(out, reservation_id, record):
    """Never replace an archived receipt. A restarted projection can refer to it by ID."""
    if not re.fullmatch(r'[a-f0-9]{64}', reservation_id or ''):
        raise ValueError('原请求缺少有效预占编号')
    path = out/'attempts'/(reservation_id + '.json')
    if path.exists():
        if load(path) != record:
            raise GenerationUnknown('历史请求回执不一致，请核对原任务')
    else:
        atomic_json(path, record)


def generate_tasks(tasks, out, *, client=None, redo=None, approval=None, scope=None, replace_unknown=()):
    from heideng_merchant.state import FileLock
    from heideng_merchant.image_budget import validate_approval, reserve_request

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    redo = set(redo or [])
    replacements = set(replace_unknown)
    if replacements and redo:
        raise ValueError('未知请求追加与已完成图重做需要分别核对')
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
        evidence = inspect_attempts(tasks, out, scope or {}, replacements)
        states = {row['unit']: row for row in evidence['rows']}
        parents = {}
        if replacements:
            quote = evidence['replacementQuote']
            if not quote:
                raise GenerationUnknown('所选图片不全是可核对的未知请求，请重新 reconcile-images')
            scope = quote['scope']
            parents = scope['unresolvedRequests']
        for task in tasks:
            name = task['id']
            if replacements and name not in replacements:
                continue
            current = fingerprint(task)
            old = ledger.get(name) or {}
            status = old.get('status')
            old_key = old.get('fingerprint') or receipts.get(name)
            path = out/'generated'/f'{name}.jpg'
            if name in parents:
                todo.append((task, current))
                continue
            if states[name]['status'] == 'RESERVED_WITHOUT_RECEIPT':
                raise GenerationUnknown(f'{name} 的原请求已预占，请先 reconcile-images')
            if status in ('STARTED', 'UNKNOWN'):
                if name in redo or states[name]['status'] != 'LOCAL_RESULT':
                    raise GenerationUnknown(f'{name} 的上次生成结果待核对，请先查原回执')
                if states[name]['reservationId']:
                    preserve_attempt(out, states[name]['reservationId'], old)
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
            if replacements and (set(units) != replacements or any(
                    states[unit]['previousApprovalRef'] == approval['approvalRef'] for unit in replacements)):
                raise ValueError('未知费用需要对应本次所选图片的新批准')
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
                parent = parents.get(name)
                if parent:
                    original = old if states[name]['status'] != 'RESERVED_WITHOUT_RECEIPT' else {
                        'status':'RESERVED_WITHOUT_RECEIPT', 'reservationId':parent,
                        'approvalRef':states[name]['previousApprovalRef']}
                    preserve_attempt(out, parent, original)
                if name in redo and old.get('status') == 'SUCCEEDED':
                    prior = {'status':'SUCCEEDED', 'sha256':old['sha256'],
                             'receiptHash': hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()}
                reservation = reserve_request(out.parent, approval, scope=scope, units=units,
                                              request_id=name, previous_receipt=prior,
                                              unresolved_reservation=parent)
                if (name in redo or parent) and path.exists():
                    archive = out/'history'
                    archive.mkdir(exist_ok=True)
                    os.replace(path, archive/f'{name}-{time.time_ns()}.jpg')
                record = {'status':'STARTED', 'model':model, 'fingerprint':current,
                          'reservationId':reservation['reservationId'],
                          'approvalRef':approval['approvalRef'], 'previousReceipt':prior, 'attempts':[]}
                if parent:
                    record['replacesUnknown'] = parent
                ledger[name] = record
                receipts[name] = current
                atomic_json(ledger_path, ledger)
                atomic_json(receipt_path, receipts)
            try:
                raw = client.edit(model=model, prompt=task['prompt'], photos=task['photos'], size=task['size'])
                data = image_bytes(raw)
                atomic_json(out/'attempts'/(record['reservationId']+'.result.json'),
                            {'fingerprint':current, 'sha256':hashlib.sha256(data).hexdigest()})
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
        selected = [ledger.get(name, {}) for name in ids]
        report = {'successCount':sum(r.get('status')=='SUCCEEDED' for r in selected),
                  'unknownCount':sum(r.get('status') in ('UNKNOWN','STARTED') for r in selected),
                  'failedCount':sum(r.get('status')=='REJECTED' for r in selected),
                  'seconds':round(time.monotonic()-began,2),
                  'modelsUsed':sorted({r['model'] for r in selected if r.get('model')}),
                  'ledger':ledger, 'submittedCount':len(todo), 'modelsSubmitted':list(MODELS) if todo else []}
        if report['unknownCount']:
            report['nextAction'] = '运行 reconcile-images 核对原图及请求；保存本次回执和预算预占。'
        atomic_json(out/'generation-result.json', report)
        return report
