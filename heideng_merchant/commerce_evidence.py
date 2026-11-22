"""Align the host's anonymized aggregates before making a cross-domain diagnosis."""
from calendar import monthrange
from datetime import date
import math
from hashlib import sha256
import json
from pathlib import Path
import time

from .safety import SafetyError, atomic_json, read_json, redact, safe_join
from .state import FileLock


FIELDS = {
    'ads': ('impressions', 'clicks', 'spend', 'attributedOrders', 'attributedRevenue'),
    'sales': ('orders', 'revenue'),
    'service': ('consultations', 'concernSamples'),
    'returns': ('returns', 'reasonSamples'),
}


def _window(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('统计区间需要开始和结束日期')
    start, end = (date.fromisoformat(day) for day in value)
    if end < start:
        raise ValueError('结束日期早于开始日期')
    return start, end


def compare_evidence(data, shop_id, vender_id, spu_id):
    """Return comparable observations; missing and mismatched slices stay visible."""
    if not isinstance(data, dict):
        raise ValueError('需要经营报表汇总对象')
    periods = data['periods']
    if not isinstance(periods, dict) or 'current' not in periods or set(periods) - {'baseline','current'}:
        raise ValueError('请指定本期及可选的对照期')
    windows = {period: _window(window) for period, window in periods.items()}
    days = {period: (end-start).days + 1 for period, (start,end) in windows.items()}
    if 'baseline' in windows and windows['baseline'][1] >= windows['current'][0]:
        raise ValueError('对照期应早于本期且不重叠')
    full_months = all(start.day == 1 and (start.year,start.month) == (end.year,end.month)
                      and end.day == monthrange(end.year,end.month)[1] for start,end in windows.values())
    comparable_days = len(set(days.values())) == 1 or full_months
    pairs = {name: {} for name in FIELDS}
    if not isinstance(data.get('rows'), list):
        raise ValueError('需要提供已取得的分域报表行')
    for row in data['rows']:
        if not isinstance(row, dict):
            raise ValueError('报表行格式无效')
        if (row['shopId'], row['venderId'], row['spuId']) != (shop_id, vender_id, spu_id):
            raise ValueError('报表与指定店铺或商品不一致')
        domain, period = row['domain'], row['period']
        if domain not in pairs or period not in ('baseline', 'current') or period in pairs[domain]:
            raise ValueError('指标域或期间无效，或存在重复汇总行')
        pairs[domain][period] = row

    observations, gaps = {}, []
    for domain, pair in pairs.items():
        values, sources, definitions, daily = {}, {}, {}, {}
        for period, row in pair.items():
            if period not in windows or row.get('window') != periods[period]:
                gaps.append(f'{domain} 的 {period} 时间窗不符')
                continue
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('basis', 'channel', 'source')):
                gaps.append(f'{domain} 的 {period} 缺少口径、渠道或来源')
                continue
            metrics = row.get('metrics', {})
            if not isinstance(metrics, dict):
                raise ValueError('metrics 须为分域汇总数值')
            measured = {}
            per_day = {}
            for key in FIELDS[domain]:
                number = metrics.get(key)
                if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
                    raise ValueError(f'{domain}.{key} 需要有限的非负数')
                measured[key] = number
                # Samples are evidence from the selected records, not daily operational throughput.
                if number is not None and key not in ('reasonSamples','concernSamples'):
                    per_day[key] = number / days[period]
            if domain == 'ads':
                clicks, orders = measured['clicks'], measured['attributedOrders']
                measured['attributedOrdersPerClick'] = orders / clicks if clicks and orders is not None else None
            values[period], daily[period] = measured, per_day
            sources[period] = row['source']
            definitions[period] = {'channel':row['channel'], 'basis':row['basis']}
            absent = [key for key in FIELDS[domain] if measured[key] is None]
            if absent:
                gaps.append(f"{domain} 的 {period} 缺少字段：" + '、'.join(absent))
        if len(values) < 2:
            gaps.append(f'{domain} 缺少可比的两期数据')
        if not values:
            continue
        same_basis = len(values) == 2 and definitions['current'] == definitions['baseline']
        if len(values) == 2 and not same_basis:
            gaps.append(f'{domain} 的两期口径或渠道不同，仅展示各期事实')
        if len(values) == 2 and not comparable_days:
            gaps.append(f'{domain} 窗口长度不同且非完整自然月，仅展示各期事实')
        comparable = same_basis and comparable_days
        definition = definitions.get('current', next(iter(definitions.values())))
        observations[domain] = {**definition, **values, 'sources': sources, 'periodDefinitions':definitions,
                                'perDay':daily, 'comparable':comparable}
    return {'shopId': shop_id, 'venderId': vender_id, 'spuId': spu_id, 'periods': periods, 'days':days,
            'observations': observations, 'gaps': gaps, 'readOnly': True}


def _receipt_id(body):
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return sha256(raw.encode()).hexdigest()


def save_handoff(state, facts, notes):
    """Persist only scoped aggregate evidence and the host's explicitly supplied assessment."""
    from .merchant_tasks import task_context

    shop, vendor, product = (facts[k] for k in ('shopId','venderId','spuId'))
    registry = read_json(safe_join(state,'linker/shops.json'), {}).get('profiles', {})
    if not any(str(p.get('shopId')) == shop and str(p.get('venderId')) == vendor and
               p.get('lastVerifiedAt') and p.get('status') == 'ok' for p in registry.values()):
        raise ValueError('保存经营交接前，请先用连接入口核验本店身份')
    if not isinstance(notes, dict):
        raise ValueError('交接需要宿主整理 priorityAction、nextRole 和 recheck')
    assessment = {}
    for key in ('priorityAction','nextRole','recheck','hypothesis'):
        value = notes.get(key)
        if key == 'hypothesis' and value in (None,''):
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'经营交接缺少 {key}')
        assessment[key] = value.strip()

    related = []
    for item in task_context(state, shop, vendor, product_id=product)['tasks']:
        kind = item.get('kind','materials')
        if kind not in ('materials','sku-edit','listing','creative','sample'):
            continue
        summary = {k:item[k] for k in ('taskId','goal','state','updatedAt','receipt','originalScope',
                    'originalHandoff','consumerPageStatus') if k in item}
        # A multi-product batch total cannot establish which of this product's slots is live.
        if set(item.get('productIds') or [product]) == {product} and item.get('results'):
            summary['results'] = {name:{k:r[k] for k in ('phase','pendingReviewCount','submittedSkuSlotCount',
                                           'approvedSkuSlotCount','checkedAt','receipt') if k in r}
                                  for name,r in item['results'].items()}
        related.append(summary)
    related.sort(key=lambda item:item['taskId'])
    body = redact({'facts':facts, 'hostAssessment':assessment, 'relatedReceiptsAtSave':related})
    key = _receipt_id(body)
    path = safe_join(state, f'commerce-handoffs/{shop}/{vendor}/{key}.json')
    with FileLock(path.with_suffix('.lock')):
        if not path.is_file():
            atomic_json(path, {'body':body, 'savedAt':int(time.time())})
    return {'taskId':key,'receipt':str(path)}


def saved_handoffs(state, shop, vendor, product=None, task_id=None):
    directory = safe_join(Path(state), f'commerce-handoffs/{shop}/{vendor}')
    for entry in directory.glob('*.json'):
        if task_id and entry.stem != task_id:
            continue
        try:
            path = safe_join(directory, entry.name)
            record = read_json(path)
            body = record['body']
            facts = body['facts']
            if ((facts['shopId'],facts['venderId']) != (shop,vendor) or _receipt_id(body) != entry.stem
                    or product and product != facts['spuId']):
                continue
            item = {'kind':'diagnosis','goal':'经营诊断交接','state':'saved','taskId':entry.stem,
                    'shopIdentity':{'shopId':shop,'venderId':vendor},'productId':facts['spuId'],
                    'updatedAt':record['savedAt'], 'receipt':str(path), **body,
                    'nextAction':body['hostAssessment']['priorityAction'], 'readOnly':True}
        except (SafetyError, OSError, KeyError, TypeError, ValueError):
            # An incomplete local record cannot establish the handoff's shop or product.
            continue
        yield item
