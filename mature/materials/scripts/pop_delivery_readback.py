"""Offline projection of frozen parent and child evidence, plus exact repair readback."""
from pathlib import Path
import json
import time
from pop_safety import atomic_json
from pop_scope import ScopeLedger, make_scope

def load_parent_plan(path, *, agent):
    path=Path(path)
    payload=json.loads(path.read_text(encoding='utf-8'))
    if payload.get('formatVersion')!=1 or payload.get('businessMode')!='pop' or payload.get('planHash')!=agent._auto_maintain_plan_hash(payload):
        raise ValueError('Original parent plan checksum/type invalid; do not reconstruct it from chat')
    prepared=agent._prepared_from_payload(payload['prepared'])
    if payload.get('taskSignature')!=agent._task_signature(prepared):
        raise ValueError('Parent prepared-source signature invalid')
    source=Path(payload['sourceWorkbook']['path'])
    if not source.is_file() or agent._file_sha256(source)!=payload['sourceWorkbook']['sha256']:
        raise ValueError('Parent source workbook missing/changed; original SKU facts need verification')
    from pop_scope import verify_scope
    scope=verify_scope(payload['coverageScope']) if payload.get('coverageScope') else make_scope(prepared,agent=agent,
        snapshot={'capturedAt':payload.get('createdAt'),'targetSkuCount':payload['counts']['skus'],'basis':'legacy-plan'})
    if scope['taskSignature']!=agent._task_signature(prepared):
        raise ValueError('Parent scope/source disagree')
    return prepared,scope

def coverage_summary(args, agent):
    prepared,scope=load_parent_plan(args.parent_plan,agent=agent)
    from pop_scope import legacy_report
    if getattr(args,'coverage_root',None):
        path=args.coverage_root/'.state/coverage.json'
        if not path.is_file():raise ValueError('Parent coverage ledger missing; do not invent historical coverage')
        result=ScopeLedger(path,scope).report()
    else:
        result=legacy_report(scope,args.child_dir,agent=agent)
    result['scope']=scope
    if args.report:
        if args.report.resolve()==args.parent_plan.resolve():
            raise ValueError('Coverage report cannot overwrite original parent plan')
        atomic_json(args.report,result)
    return result

def read_repair_status(client, directory, agent):
    """Read the original bound values by SKU without reconstructing or submitting a write."""
    from pop_title_io import read_json
    identity = agent._shop_identity(client.seller_info())
    scope = read_json(directory / 'repair-scope.json', {})
    if identity != scope.get('shopIdentity'):
        raise ValueError('原任务与当前官方店铺身份不一致')
    receipt_paths = sorted((directory / 'shared-bindings').glob('*.json'))
    receipt_paths += sorted(directory.glob('*/*-binding.json'))
    requests = []
    identifiers = set()
    for path in receipt_paths:
        saved = read_json(path, {})
        request = saved.get('request', {})
        sku_ids = list(map(str, request['skuIds']))
        if not sku_ids or len(set(sku_ids)) != len(sku_ids) or not set(sku_ids).issubset(scope['originals']):
            raise ValueError('绑定回执超出原维修范围')
        requests.append((path, request, sku_ids))
        identifiers.update(sku_ids)
    read_gaps = {}
    reads = agent._query_binding_materials(client, sorted(identifiers), read_gaps=read_gaps)
    rows = []
    for path, request, sku_ids in requests:
        for sku in sku_ids:
            single = {**request, 'skuIds':[sku]}
            if 'preservedMaterialsBySku' in request:
                single['preservedMaterialsBySku'] = {sku:request['preservedMaterialsBySku'].get(sku, [])}
            if int(request['materialType']) in read_gaps.get(sku, ()):
                status, reason = 'unknown', '平台未返回该 SKU 图位的完整证据'
            else:
                status, reason = agent._evaluate_binding_request(single, reads)
            status = {'mismatch':'unknown','failed':'rejected'}.get(status, status)
            rows.append({'skuId':sku,'materialType':request['materialType'],'status':status,
                         'reason':reason,'receipt':str(path)})
    unknown_images = [str(path) for path in (directory/'shared').glob('*/*.request.json')
                      if read_json(path, {}).get('status') in ('intent','unknown')]
    if agent._shop_identity(client.seller_info()) != identity:
        raise ValueError('修图回查期间店铺身份发生变化')
    if unknown_images or any(row['status'] == 'unknown' for row in rows):
        status = 'unknown'
    elif not rows:
        status = 'no-binding-receipts'
    elif any(row['status'] == 'rejected' for row in rows):
        status = 'repair-incomplete'
    elif any(row['status'] == 'pending' for row in rows):
        status = 'repairs-submitted-awaiting-review'
    else:
        status = 'verified' if all(row['status'] == 'approved' for row in rows) else 'submitted'
    result = {'status':status,'shopName':identity['shopName'],'shopIdentity':identity,
              'rows':rows,'unknownImageReceipts':unknown_images,'writesPerformed':False,
              'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    atomic_json(directory/'.state/repair-readback.json', result)
    return result
