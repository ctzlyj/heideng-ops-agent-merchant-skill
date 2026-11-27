"""Copy exact SKU short titles between two verified merchant-owned products."""
from argparse import Namespace
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys
import unicodedata

from . import owned_product_copy as copy
from . import shop_copy_materials as materials
from .mature_runtime import registered_browser_profile, source_path
from .safety import atomic_json, file_sha, read_json, redact, safe_join
from .shop_copy_history import material_origins
from .state import FileLock, merchant_home


def register(subs):
    p = subs.add_parser('copy-short-titles', help='逐 SKU 核对两店短标题，生成目标店导入表并沿原任务回查')
    for side in ('source', 'target'):
        p.add_argument('--'+side+'-config', required=True, type=Path)
        p.add_argument('--'+side+'-profile', required=True)
        p.add_argument('--'+side+'-product-id', required=True, type=int)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--confirm', choices=['IMPORT_COPY_SHORT_TITLES'], help='向已核验的目标店导入当前明确为空的 SKU')
    mode.add_argument('--reconcile', action='store_true', help='仅查询原导入任务、目标短标题与处理结果')
    p.add_argument('--history-dir', type=Path, help='核对同源多目标的原搬家回执')
    p.add_argument('--health', action='store_true', help='另查目标店信息分中的短标题改进项')


def _services():
    script, _ = source_path('short-title')
    if str(script.parent) not in sys.path:
        sys.path.insert(0, str(script.parent))
    import jd_material_agent as agent
    import pop_browser
    import pop_title_batches
    import pop_workflow
    return agent, pop_title_batches, pop_workflow, pop_browser


def _title(row):
    features = row.get('features')
    if isinstance(features, dict):
        value = features.get('shortTitle')
    elif isinstance(features, list):
        if any(not isinstance(item, dict) or not isinstance(item.get('key'), str) for item in features):
            return None
        titles = [item.get('value') for item in features if item['key'] == 'shortTitle']
        value = titles[0] if len(titles) == 1 else None
    else:
        return None
    if (isinstance(value, str) and len(value) <= 4096 and redact(value) == value
            and not any(unicodedata.category(c).startswith('C') for c in value)):
        return value
    return None


def _observe(entry, frozen, source_numbers, detail, agent, origins):
    target = frozen['targetShop']
    proof = materials.product_pair(entry, frozen, detail, source_numbers, origins)
    source = copy.sku_rows(frozen['sourceDetail'], frozen['sourceProductId'])
    target_rows = copy.sku_rows(detail, proof['targetProductId'])
    mapping = materials._pair(entry, frozen, target, detail) if proof['verified'] else {'pairs':{}, 'matchedBy':{}}
    materials._same_session(entry.api, target)
    rows = []
    for sid, sku in source.items():
        tid = mapping['pairs'].get(sid)
        left = _title(sku)
        right = _title(target_rows[tid]) if tid else None
        if not tid:
            status = 'unpaired'
        elif right and left == right:
            status = 'matched'
        elif right:
            status = 'target-preserved'
        elif right is None:
            status = 'target-unreported'
        elif left is None:
            status = 'source-unreported'
        elif left == '':
            status = 'source-empty'
        elif not agent.valid_short_title(left):
            status = 'source-outside-template'
        else:
            status = 'ready'
        rows.append({'sourceSkuId':sid, 'targetSkuId':tid, 'sourceShortTitle':left, 'targetShortTitle':right,
                     'status':status, 'pairedBy':mapping['matchedBy'].get(sid)})
    return proof, rows, target_rows


def _prepare(root, pairs, agent, batches):
    """Leave a content-addressed official workbook and its platform-sized batches."""
    content = agent._short_title_workbook_bytes(pairs)
    path = root/'workbooks'/(sha256(content).hexdigest()+'.xlsx')
    batches.save_import_workbook(path, content)
    return batches.prepare_import_batches([path], root, agent=agent)


def _native_summary(browser, receipt, count):
    done = browser.completed_batch(receipt, count)
    return {'status':receipt.get('status', 'unknown'), 'taskId':receipt.get('taskId'),
            'uploaded':('uploadSourceHashes' in receipt or receipt.get('creationAccepted') is True),
            'accepted':receipt.get('creationAccepted') is True, 'finished':done,
            'successRows':receipt['successRows'] if done else 0, 'failedRows':receipt['failedRows'] if done else 0,
            'beforeUpload':receipt.get('dispatchState') == 'before-upload',
            'reason':redact(str(receipt.get('reason') or receipt.get('nextAction') or ''))[:400]}


def _reconcile(root, records, target, profile_dir, browser):
    for record in records.values():
        if record['targetShop'] != target:
            raise ValueError('原导入记录的目标店身份不一致')
        previous = record['result']
        if previous.get('finished'):
            continue
        path = safe_join(root, record['workbook'])
        receipt = browser.batch_receipt_path(path, record['sha256'])
        if previous.get('beforeUpload') and not receipt.exists():
            record['reconciliation'] = 'before-upload'
            continue
        if not receipt.is_file() or not path.is_file() or file_sha(path) != record['sha256']:
            record['reconciliation'] = 'original-receipt-or-workbook-unavailable'
            continue
        if not profile_dir:
            record['reconciliation'] = 'registered-target-browser-required'
            continue
        try:
            native = browser._import_short_title_batch(str(profile_dir), str(path), expected_shop_name=target['shopName'],
                        expected_shop_id=target['shopId'], expected_sha256=record['sha256'], receipt_path=receipt,
                        reconcile_only=True, poll_seconds=0)
            record['result'] = _native_summary(browser, native, len(record['rows']))
            record['reconciliation'] = 'original-task-checked'
        except Exception as error:
            record['reconciliation'] = 'original-task-unavailable'
            record['reconciliationReason'] = redact(str(error))[:400]


def _request(root, batch, mapping, target, source, args, browser, workflow):
    path = Path(batch['path'])
    actual = workflow._workbook_titles(path)
    if (file_sha(path) != batch['sha256'] or len(actual) != batch['rowCount']
            or any(tid not in mapping or mapping[tid]['sourceShortTitle'] != title for tid, title in actual.items())):
        raise ValueError('原短标题导入表与规划行不符')
    return {'sourceShop':source, 'targetShop':target, 'sourceProductId':str(args.source_product_id),
            'targetProductId':str(args.target_product_id), 'workbook':path.relative_to(root).as_posix(),
            'sha256':batch['sha256'], 'receiptFile':str(browser.batch_receipt_path(path, batch['sha256'])),
            'rows':[mapping[tid] for tid in actual]}


def _originals(root, target, browser):
    ledger = root/'requests.json'
    records = read_json(ledger, {})
    handoffs = read_json(root/'handoffs.json', {})
    # A delivered workbook may also have been submitted through the regular short-title entry.
    for fingerprint, handoff in handoffs.items():
        if fingerprint in records and not records[fingerprint]['result'].get('beforeUpload'):
            continue
        path = safe_join(root, handoff['workbook'])
        receipt = browser.batch_receipt_path(path, fingerprint)
        if not receipt.exists():
            continue
        native = read_json(receipt)
        result = {'status':'original-receipt-unverified'}
        if (handoff['targetShop'] == target and path.is_file() and file_sha(path) == fingerprint
                and native.get('sha256') == fingerprint and native.get('shopName') == target['shopName']
                and str(native.get('shopId')) == target['shopId'] and native.get('rowCount') == len(handoff['rows'])):
            result = _native_summary(browser, native, len(handoff['rows']))
        records[fingerprint] = {**handoff, 'result':result}
        atomic_json(ledger, records)
    return ledger, records, handoffs


def _score(api, target, skus):
    try:
        evidence = materials._health(api, skus, target)
    except (api.JdoError, OSError, KeyError, ValueError, TypeError) as error:
        return {'status':'unverified', 'reason':redact(str(error))[:400]}
    results = {}
    for sid, row in evidence['skus'].items():
        items = row['improvements']
        if type(row['score']) not in (int, float) or not 0 <= row['score'] <= 100 or not isinstance(items, list):
            continue
        codes = [v.get('improvementDetail', {}).get('troubleCode') for v in items
                 if isinstance(v, dict) and isinstance(v.get('improvementDetail'), dict)]
        if len(codes) == len(items) and all(isinstance(code, str) and code for code in codes):
            results[sid] = 'issue-present' if 'hasShortTitle' in codes else 'clear'
    return {'status':'observed' if set(results) == set(skus) else 'partial',
            'perSku':results, 'unverifiedSkuIds':sorted(set(skus) - set(results))}


def handle(args, entry):
    agent, batches, workflow, browser = _services()
    source = entry.verify(args.source_config, args.source_profile)
    source_detail = entry.read_owned_detail(args.source_product_id)
    source_numbers = materials._numbers(entry, source_detail['productInfo'])
    materials._same_session(entry.api, source)
    target = entry.verify(args.target_config, args.target_profile)
    if (target['shopId'] == source['shopId'] or target['profile'] == source['profile']
            or args.source_product_id == args.target_product_id):
        raise ValueError('请指定不同的两家已核验店铺与原目标商品')
    frozen = copy.freeze_copy(source, target, source_detail)
    root = safe_join(merchant_home(), 'work/shop-copy-short-titles/'+entry.digest([
        target['shopId'], target['venderId'], args.target_product_id]))
    online_receipts = bool(args.confirm or args.reconcile)
    profile_dir = registered_browser_profile(target['profile'], target) if online_receipts else None
    with FileLock(root/'short-titles.lock'):
        def observe(refresh_source=False):
            nonlocal frozen, source_numbers
            if refresh_source:
                if entry.verify(args.source_config, args.source_profile) != source:
                    raise ValueError('导入前核验的实际源店铺发生变化')
                fresh = entry.read_owned_detail(args.source_product_id)
                source_numbers = materials._numbers(entry, fresh['productInfo'])
                materials._same_session(entry.api, source)
                frozen = copy.freeze_copy(source, target, fresh)
                if entry.verify(args.target_config, args.target_profile) != target:
                    raise ValueError('导入前核验的实际目标店铺发生变化')
            detail = entry.read_owned_detail(args.target_product_id)
            origins = material_origins(args.history_dir, frozen, str(args.target_product_id)) if args.history_dir else ()
            return _observe(entry, frozen, source_numbers, detail, agent, origins)

        ledger, records, handoffs = _originals(root, target, browser)
        if records and online_receipts:
            _reconcile(root, records, target, profile_dir, browser)
            atomic_json(ledger, records)
        proof, rows, target_rows = observe()
        reserved = {r['targetSkuId'] for rec in records.values() if not rec['result'].get('beforeUpload')
                    for r in rec['rows']}
        def eligible(checks):
            return {r['targetSkuId']:r for r in checks if r['status'] == 'ready' and r['targetSkuId'] not in reserved}

        initial = eligible(rows)
        pairs = sorted((tid, r['sourceShortTitle']) for tid, r in initial.items())
        planned = _prepare(root, pairs, agent, batches) if pairs and not args.reconcile else []
        if planned:
            for batch in planned:
                handoffs[batch['sha256']] = _request(root, batch, initial, target, source, args, browser, workflow)
            atomic_json(root/'handoffs.json', handoffs)
        submitted = 0
        changed = []
        if args.confirm and profile_dir and planned:
            for batch in planned:
                if file_sha(Path(batch['path'])) != batch['sha256']:
                    raise ValueError('原短标题导入表与规划摘要不符')
                original = workflow._workbook_titles(batch['path'])
                proof, rows, target_rows = observe(refresh_source=True)
                current = eligible(rows)
                kept = [(tid, title) for tid, title in original.items()
                        if tid in current and current[tid]['sourceSkuId'] == initial[tid]['sourceSkuId']
                        and current[tid]['sourceShortTitle'] == title]
                changed.extend(sorted(set(original)-{tid for tid, _ in kept}))
                if not kept:
                    continue
                if len(kept) != len(original):
                    batch, = _prepare(root, kept, agent, batches)
                path, fingerprint = Path(batch['path']), batch['sha256']
                if file_sha(path) != fingerprint:
                    raise ValueError('原短标题导入表与规划摘要不符')
                request = _request(root, batch, current, target, source, args, browser, workflow)
                request['result'] = {'status':'dispatch-intent'}
                records[fingerprint] = request
                atomic_json(ledger, records)
                submitted += 1
                try:
                    outcome = workflow._import_delivery(Namespace(profile_dir=profile_dir, output_dir=root),
                                  [path], target, agent, [{'path':str(path), 'sha256':fingerprint}])
                    receipt = (outcome.get('imports') or [outcome])[0]
                    result = _native_summary(browser, receipt, len(kept))
                    if Path(request['receiptFile']).exists():
                        result['beforeUpload'] = False
                    request['result'] = result
                except Exception as error:
                    request['result'] = {'status':'outcome-unknown', 'reason':redact(str(error))[:400]}
                atomic_json(ledger, records)
            proof, rows, target_rows = observe()
        health = _score(entry.api, target, target_rows) if args.health else {'status':'not-queried'}
        materials._same_session(entry.api, target)
        counts = dict(Counter(row['status'] for row in rows))
        own = [rec for rec in records.values() if rec['sourceShop'] == source and
               rec['sourceProductId'] == str(args.source_product_id)]
        dispatched = [rec for rec in own if not rec['result'].get('beforeUpload')]
        attempted = {r['targetSkuId'] for rec in dispatched for r in rec['rows']}
        exact = sum(_title(target_rows.get(r['targetSkuId'], {})) == r['sourceShortTitle']
                    for rec in dispatched for r in rec['rows'])
        stats = {'preparedRows':sum(b['rowCount'] for b in planned), 'dispatchedBatchesThisRun':submitted,
                 'originalPreparedRows':len({r['targetSkuId'] for rec in own for r in rec['rows']}),
                 'originalTaskStatusCounts':dict(Counter(rec['result']['status'] for rec in own)),
                 'originalTaskIds':sorted({str(rec['result']['taskId']) for rec in own if rec['result'].get('taskId')}),
                 'uploadedRows':sum(len(rec['rows']) for rec in own if rec['result'].get('uploaded')),
                 'platformAcceptedRows':sum(len(rec['rows']) for rec in own if rec['result'].get('accepted')),
                 'platformSuccessRows':sum(rec['result'].get('successRows', 0) for rec in own),
                 'platformFailedRows':sum(rec['result'].get('failedRows', 0) for rec in own),
                 'originalTargetTitlesMatched':exact,
                 'originalTargetScoreClearRows':(sum(health['perSku'].get(sid) == 'clear' for sid in attempted)
                                                 if 'perSku' in health else None)}
        unpaired_targets = sorted(set(target_rows)-{r['targetSkuId'] for r in rows})
        if not proof['verified']:
            status = 'unverified-product-pair'
        elif args.reconcile and not own:
            status = 'no-original-import'
        elif args.confirm and planned and not profile_dir:
            status = 'blocked-target-browser'
        elif any(not rec['result'].get('finished') for rec in own):
            status = 'short-title-import-needs-reconciliation'
        elif stats['platformFailedRows']:
            status = 'short-title-import-row-failures'
        elif set(counts)-{'matched','ready','source-empty'} or unpaired_targets or changed:
            status = 'short-title-copy-partial'
        elif attempted and (exact < len(attempted) or args.health and stats['originalTargetScoreClearRows'] != len(attempted)):
            status = 'short-title-awaiting-readback'
        elif planned and not args.confirm:
            status = 'short-title-handoff-ready'
        elif counts.get('ready'):
            status = 'short-title-original-request-reserved'
        else:
            status = 'short-titles-checked'
        checked = datetime.now(timezone.utc).isoformat()
        path = root/('report-'+entry.digest([source, args.source_product_id])[:24]+'.json')
        summary = {'ok':status in ('short-title-handoff-ready', 'short-titles-checked'), 'status':status,
                   'sourceShop':source, 'targetShop':target, 'productPair':proof, 'skuCounts':counts,
                   'targetSkuCount':len(target_rows), 'targetHealthStatus':health['status'], **stats,
                   'checkedAt':checked, 'reportFile':str(path), 'workbooks':[b['path'] for b in planned]}
        atomic_json(path, {**summary, 'rows':rows, 'targetHealth':health, 'unpairedTargetSkus':unpaired_targets,
                           'changedBeforeWrite':changed, 'plannedBatches':planned, 'originalRequests':own,
                           'reservedTargetSkuIds':sorted(reserved)})
        return summary
