"""Align the host's anonymized aggregates before making a cross-domain diagnosis."""
from datetime import date
import math


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
    before, after = (_window(periods[p]) for p in ('baseline', 'current'))
    if before[1] >= after[0] or before[1] - before[0] != after[1] - after[0]:
        raise ValueError('对照期与本期须等长且不重叠')
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
        if len(pair) != 2:
            gaps.append(f'{domain} 缺少可比的两期数据')
            continue
        values = {}
        for period, row in pair.items():
            if row.get('window') != periods[period]:
                gaps.append(f'{domain} 的 {period} 时间窗不符')
                break
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('basis', 'channel', 'source')):
                gaps.append(f'{domain} 的 {period} 缺少口径、渠道或来源')
                break
            metrics = row.get('metrics', {})
            if not isinstance(metrics, dict):
                raise ValueError('metrics 须为分域汇总数值')
            values[period] = {}
            for key in FIELDS[domain]:
                number = metrics.get(key)
                if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
                    raise ValueError(f'{domain}.{key} 需要有限的非负数')
                values[period][key] = number
            if domain == 'ads':
                clicks = values[period]['clicks']
                orders = values[period]['attributedOrders']
                values[period]['attributedOrdersPerClick'] = orders / clicks if clicks and orders is not None else None
        else:
            current, baseline = pair['current'], pair['baseline']
            if any(current[k] != baseline[k] for k in ('basis', 'channel')):
                gaps.append(f'{domain} 的两期口径或渠道不同')
                continue
            absent = [key for key in FIELDS[domain] if any(v[key] is None for v in values.values())]
            if absent:
                gaps.append(f"{domain} 未提供完整两期的字段：" + '、'.join(absent))
            observations[domain] = {
                'basis': current['basis'], 'channel': current['channel'], **values,
                'sources': {period: row['source'] for period, row in pair.items()},
            }
    return {'shopId': shop_id, 'venderId': vender_id, 'spuId': spu_id, 'periods': periods,
            'observations': observations, 'gaps': gaps, 'readOnly': True}
