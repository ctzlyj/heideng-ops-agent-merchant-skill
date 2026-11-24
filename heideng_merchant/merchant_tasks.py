"""Shop-scoped references to existing frozen material plans and business receipts."""
from hashlib import sha256
import json
import sys
import os
from pathlib import Path
import time

from .merchant_experience import task_summary
from . import require_local
from .safety import atomic_json, is_linked, read_json
from .state import FileLock, merchant_home


def _shop(identity):
    return str(identity.get('shopId', '')), str(identity.get('venderId', ''))


def register_material_task(handoff):
    identity = handoff['shopIdentity']
    shop_id, vender_id = _shop(identity)
    if not all(x.isdecimal() for x in (shop_id, vender_id)):
        return
    directory = Path(handoff['taskDirectory']).resolve()
    key = sha256(str(directory).encode('utf-8')).hexdigest()
    index = merchant_home() / 'merchant-tasks'
    path = index / (key + '.json')
    with FileLock(index / 'index.lock'):
        previous = read_json(path,{})
        record = {'taskId':key, 'taskDirectory':str(directory), 'shopIdentity':identity,
                  'planHash':handoff['planHash'], 'scope':handoff['scope'],
                  'goal':'维护商品信息分', 'updatedAt':int(time.time())}
        if previous and _shop(previous['shopIdentity']) != _shop(identity):
            raise ValueError('原任务目录已绑定其他店铺')
        atomic_json(path,record)


def register_repair_task(directory, identity, profile):
    """Keep a reference as soon as the authenticated repair scope is frozen."""
    directory = Path(directory).resolve()
    index = merchant_home() / 'merchant-tasks'
    task_id = sha256(('repair:' + str(directory)).encode('utf-8')).hexdigest()
    path = index / (task_id + '.json')
    with FileLock(index / 'index.lock'):
        previous = read_json(path, {})
        if previous and _shop(previous.get('shopIdentity', {})) != _shop(identity):
            raise ValueError('维修目录已绑定其他店铺')
        atomic_json(path, {'kind':'repair', 'taskId':task_id, 'taskDirectory':str(directory),
                           'shopIdentity':identity, 'profile':profile})


def _repair_context(state, directory, identity_key, record=None):
    freeze = directory / 'repair-scope.json'
    receipt = directory / '.state' / 'merchant-result-repair-rejected.json'
    if any(is_linked(p) for p in (directory, freeze, receipt.parent, receipt)):
        return None
    frozen = read_json(freeze, {})
    identity = frozen.get('shopIdentity', {})
    if _shop(identity) != identity_key:
        return None
    record = record or {}
    task_id = sha256(('repair:' + str(directory)).encode('utf-8')).hexdigest()
    profile = record.get('profile')
    base = [sys.executable, '-I', '-B', str(Path(os.environ.get('HEIDENG_MERCHANT_PACKAGE') or
             Path(__file__).resolve().parents[1]) / 'scripts/merchant.py'), '--state', str(state),
            'run', 'materials', '--', 'check-repair-status', '--output-dir', str(directory)]
    result = {'taskId':task_id, 'goal':'修复驳回素材', 'shopIdentity':identity,
              'productIds':sorted({str(row['productId']) for row in frozen.get('rows',[]) if row.get('productId')}),
              'taskDirectory':str(directory), 'originalScope':str(freeze), 'state':'recoverable',
              'updatedAt':freeze.stat().st_mtime, 'recoverArgv':base+['--profile',profile] if profile else [],
              'readbackCommand':base, 'nextAction':'使用本店已核验 Profile 只读回查原绑定；未知生成先对账。', 'results':{}}
    for command, path in (('repair-rejected',receipt), ('check-repair-status',receipt.parent/'repair-readback.json')):
        if is_linked(path):
            continue
        raw = read_json(path, {})
        if not raw or raw.get('shopName') != identity.get('shopName'):
            continue
        known_skus = set(frozen.get('originals', {}))
        if any(str(row['skuId']) not in known_skus for row in raw.get('rows', []) if 'skuId' in row):
            continue
        result['updatedAt'] = max(result['updatedAt'], path.stat().st_mtime)
        result['results'][command] = {**task_summary(raw), 'receipt':str(path),
                'checkedAt':int(path.stat().st_mtime), 'submittedSkuSlotCount':raw.get('submittedSkuSlotCount'),
                'approvedSkuSlotCount':sum(r.get('status') == 'approved' for r in raw.get('rows', [])),
                'modelAttempts':sum((raw.get('modelStats', {}).get('attempts') or {}).values()) if 'modelStats' in raw else None}
    return result


def _legacy_repair_directories(state):
    # Older versions did not index standalone repairs. Limit discovery to the merchant's own materials tree.
    base = require_local(Path(state) / 'work' / 'materials',parents=True)
    if is_linked(base) or is_linked(base.parent):
        return
    for folder, children, names in os.walk(base):
        directory = Path(folder)
        children[:] = [child for child in children if child not in {'.state','shared','browser-profiles'}
                       and not is_linked(directory / child)]
        if 'repair-scope.json' in names:
            yield directory
            children.clear()
        for child in children:
            require_local(directory/child)


def task_context(state, shop_id, vender_id, task_id=None, *, goal=None, product_id=None, source_product_id=None):
    """Return a scoped handoff; never infer that a local process is still running."""
    index = require_local(Path(state) / 'merchant-tasks',parents=True)
    matches = []
    indexed_repairs = set()
    commands = ('auto-maintain','maintain-short-titles','repair-rejected','reconcile-receipts')
    for path in sorted(index.glob('*.json')):
        if is_linked(path):
            continue
        record = read_json(path,{})
        if _shop(record.get('shopIdentity',{})) != (shop_id,vender_id):
            continue
        if task_id and record.get('taskId') != task_id:
            continue
        directory = Path(record['taskDirectory'])
        if record.get('kind') == 'repair':
            indexed_repairs.add(directory)
            entry = _repair_context(state, directory, (shop_id, vender_id), record)
            if entry:
                matches.append(entry)
            continue
        handoff = directory / '.state/host-handoff.json'
        if any(is_linked(p) for p in (directory, handoff.parent, handoff)):
            continue
        current = read_json(handoff,{})
        if (_shop(current.get('shopIdentity',{})) != (shop_id,vender_id)
                or current.get('planHash') != record['planHash']):
            continue
        plan_path = directory / '自动维护计划.json'
        if is_linked(plan_path):
            continue
        plan = read_json(plan_path,{})
        payload = {key:value for key,value in plan.items() if key != 'planHash'}
        digest = sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if (_shop(plan.get('shopIdentity',{})) != (shop_id,vender_id)
                or plan.get('planHash') != record['planHash'] or digest != record['planHash']):
            continue
        results = {}
        for command in commands:
            receipt = directory / '.state' / f'merchant-result-{command}.json'
            if receipt.is_file() and not is_linked(receipt):
                raw = read_json(receipt,{})
                evidence = raw.get('taskEvidence', {})
                if (_shop(evidence.get('shopIdentity',{})) != (shop_id,vender_id)
                        or evidence.get('planHash') != record['planHash']):
                    continue
                results[command] = {
                    **task_summary(raw), 'receipt':str(receipt), 'checkedAt':int(receipt.stat().st_mtime)
                }
        matches.append({
            **record, 'state':'recoverable', 'results':results, 'originalHandoff':str(handoff),
            'productIds':[str(spu) for spu in current.get('scope',{}).get('spuIds',[])],
            'recoverArgv':current.get('recoverArgv',[]),
        })
    for directory in _legacy_repair_directories(state):
        if directory in indexed_repairs:
            continue
        entry = _repair_context(state, directory, (shop_id, vender_id))
        if entry and (not task_id or task_id == entry['taskId']):
            matches.append(entry)
    from .commercial_tasks import commercial_tasks
    matches.extend(commercial_tasks(state, shop_id, vender_id))
    if goal in (None, 'diagnosis'):
        from .commerce_evidence import saved_handoffs
        matches.extend(saved_handoffs(state, shop_id, vender_id, product_id, task_id))
    matches = [entry for entry in matches if (not task_id or entry['taskId'] == task_id)
               and (not goal or goal == entry.get('kind', 'materials'))
               and (not product_id or product_id == entry.get('productId') or product_id in entry.get('productIds', []))
               and (not source_product_id or source_product_id == entry.get('sourceProductId'))]
    matches.sort(key=lambda item:item['updatedAt'],reverse=True)
    selection = 'ambiguous' if len(matches) > 1 else 'matched' if matches else 'not-found'
    return {'shopId':shop_id,'venderId':vender_id,'tasks':matches,'selection':selection}
