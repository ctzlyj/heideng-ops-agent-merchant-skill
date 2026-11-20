"""Shop-scoped references to existing frozen material plans and business receipts."""
from hashlib import sha256
import json
from pathlib import Path
import time

from .merchant_experience import task_summary
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


def task_context(state, shop_id, vender_id, task_id=None):
    """Return a scoped handoff; never infer that a local process is still running."""
    index = Path(state) / 'merchant-tasks'
    matches = []
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
            'recoverArgv':current.get('recoverArgv',[]),
        })
    matches.sort(key=lambda item:item['updatedAt'],reverse=True)
    return {'shopId':shop_id,'venderId':vender_id,'tasks':matches}
