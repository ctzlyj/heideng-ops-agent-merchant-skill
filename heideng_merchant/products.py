"""Merchant POP reads and native atomic SKU-price plans; no direct online-price shortcut."""
from __future__ import annotations
import json
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .operations import Operations, digest, _same_identity
from .safety import SafetyError, redact
from .verification import business_payload,pagination_total

DETAIL = '/rest/sp-product/v0/products/{productId}'
APPLY_DETAIL = '/rest/sp-product/v0/product-apply/{applyId}'
PATCH = '/rest/sp-product/v0/product-applies/{applyId}'

_PRODUCT_FILTERS = set('productStatusList categoryIdList brandIdList productIdList skuIdList productName itemNum upcCode colType productType minJdPrice maxJdPrice minSalesVolume maxSalesVolume minStockNum maxStockNum createStartTime createEndTime modifiedStartTime modifiedEndTime onlineStartTime onlineEndTime offlineStartTime offlineEndTime shopCategoryIdList promiseId transportId templateId sortBy sortType'.split())
_HEALTH_FILTERS = {'scoreStart', 'scoreEnd', 'detectFactor', 'skuId', 'productId'}
_FILTERS = {'/rest/sp-product/v0/products':_PRODUCT_FILTERS, '/rest/sp-product/v0/skus':{'productIdList'}, '/rest/sp-product/v0/health-infos':_HEALTH_FILTERS}


def _validate_filters(url, filters):
    if filters is None:return {}
    if not isinstance(filters,dict) or set(filters)-_FILTERS[url]:
        raise SafetyError('unreviewed-query-field-check-current-official-schema')
    for value in filters.values():
        values=value if isinstance(value,list) else [value]
        if isinstance(value,dict) or any(not isinstance(item,(str,int,float,bool)) or len(str(item))>1024 for item in values):
            raise SafetyError('scalar-business-filter-values-required')
    if redact(filters)!=filters:raise SafetyError('credentials-not-allowed-in-query')
    return filters



def identifier(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,18}', str(value)) or int(value) > 2**63 - 1:
        raise SafetyError('actual-positive-platform-id-required')
    return str(value)


def money(value, *, positive=True):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 128:
        raise SafetyError('exact-jdprice-value-required')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or (positive and amount == 0):
            raise SafetyError('positive-finite-jdprice-required')
        rounded = amount.quantize(Decimal('0.01'))
        if amount != rounded:
            raise SafetyError('jdprice-supports-exact-cents-no-rounding')
        return format(rounded, 'f')
    except InvalidOperation:
        raise SafetyError('exact-jdprice-value-required') from None


def _path_value(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _product_identity(data, product_id):
    observed = [(path, _path_value(data, path)) for path in ('productId', 'productInfo.productId')]
    found = [(path, identifier(value)) for path, value in observed if value is not None]
    if not found or any(value != product_id for _, value in found):
        raise SafetyError('native-product-detail-target-mismatch')
    return found[0][0]


def _category(data):
    found = [(path,_path_value(data,path)) for path in ('categoryDetail.lastCategoryId', 'productInfo.categoryDetail.lastCategoryId', 'categoryDTO.lastCategoryId')]
    identifiers = [identifier(value) for _,value in found if value is not None]
    if not identifiers or len(set(identifiers)) != 1:
        raise SafetyError('native-last-category-id-missing-or-conflicting')
    return int(identifiers[0]),next(path for path,value in found if value is not None)


def _sku_source(data):
    candidates = [(path, _path_value(data, path)) for path in ('skuList', 'productInfo.skuList')]
    present = [(path, rows) for path, rows in candidates if isinstance(rows, list)]
    if not present or any(rows != present[0][1] for _, rows in present[1:]):
        raise SafetyError('native-sku-list-missing-or-conflicting')
    return present[0]


class ProductService:
    def __init__(self, state, client):
        self.state = Path(state).resolve()
        self.client = client
        self.ops = Operations(self.state, client)

    def _read(self, profile, url, params, *, skill='jdo-product-update'):
        shop = self.ops.shop(profile)
        if not profile.startswith('merchant-'):
            raise SafetyError('merchant-owned-profile-required')
        if not _same_identity(self.client.identity(profile), shop):
            raise SafetyError('shop-identity-mismatch-before-read')
        if redact(params) != params:
            raise SafetyError('credentials-not-allowed-in-query')
        result = self.client.invoke(profile, url, method='GET', params=params, skill_id=skill)
        business_payload(result)
        return result

    def detail(self, profile, product_id):
        product_id = identifier(product_id)
        response = self._read(profile, DETAIL, {'productId': int(product_id), 'scene': 'pop'})
        data = business_payload(response)
        if not isinstance(data, dict):
            raise SafetyError('native-product-detail-object-required')
        _product_identity(data, product_id)
        return data

    def list_products(self, profile, *, filters=None, page_size=20, max_pages=100, start_page=1):
        return self._list_records(profile, '/rest/sp-product/v0/products', 'productId',
                                  fields=['productId', 'productName', 'productStatus'], filters=filters,
                                  page_size=page_size, max_pages=max_pages, start_page=start_page)

    def list_skus(self, profile, product_id, *, page_size=20, max_pages=100, start_page=1):
        product_id = identifier(product_id)
        return self._list_records(profile, '/rest/sp-product/v0/skus', 'skuId',
                                  fields=['skuId', 'productId', 'skuName', 'status'], filters={'productIdList': product_id},
                                  parent=product_id, page_size=page_size, max_pages=max_pages, start_page=start_page)

    def list_health(self, profile, *, filters=None, page_size=100, max_pages=100, start_page=1):
        return self._list_records(profile, '/rest/sp-product/v0/health-infos', 'skuId', filters=filters,
                                  skill='jdo-product-price', maximum_page=100,
                                  page_size=page_size, max_pages=max_pages, start_page=start_page)

    def _list_records(self, profile, url, id_field, *, fields=None, filters=None, skill='jdo-product-status',
                      parent=None, page_size=20, max_pages=100, start_page=1, maximum_page=50):
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (page_size, max_pages, start_page)) or not 1 <= page_size <= maximum_page or not 1 <= max_pages <= 1000 or start_page < 1:
            raise SafetyError('bounded-pagination-required')
        filters = _validate_filters(url,filters)
        rows = []; seen = set(); total = None; hashes = []; end_reached = False; next_page = start_page; reason = 'page-budget-reached'
        for page in range(start_page, start_page + max_pages):
            params = {**filters, 'page': page, 'pageSize': page_size}
            if fields is not None:params['scopeSet'] = fields
            try:
                result = self._read(profile, url, params, skill=skill)
                data = business_payload(result)
                if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                    raise SafetyError('native-page-array-required')
                ids = [identifier(item.get(id_field)) for item in data]
                if parent is not None and any(identifier(item.get('productId')) != parent for item in data):
                    raise SafetyError('sku-page-target-product-mismatch')
                page_total = pagination_total(result)
            except Exception:
                if not rows:
                    raise SafetyError('native-product-read-incomplete') from None
                next_page = page; reason = 'native-product-read-incomplete'; break
            if len(ids) != len(set(ids)) or seen.intersection(ids):
                next_page = page; reason = 'pagination-identity-repeat'; break
            if page_total is not None:
                if total is not None and page_total != total:
                    next_page = page; reason = 'pagination-total-changed'; break
                total = page_total
            rows.extend(data); seen.update(ids); hashes.append(digest(result)); next_page = page + 1
            remaining = max(total - (start_page - 1) * page_size, 0) if total is not None else None
            if remaining is not None and len(rows) == remaining:
                end_reached = True; next_page = None; reason = None; break
            if remaining is not None and len(rows) > remaining:
                reason = 'pagination-total-mismatch'; break
            if not data or (total is None and len(data) < page_size):
                end_reached = total is None or len(rows) == remaining
                next_page = None if end_reached else page + 1; reason = None if end_reached else 'pagination-total-incomplete'; break
        if end_reached and start_page > 1:reason = 'earlier-pages-not-in-this-result'
        return {'items': rows, 'complete': end_reached and start_page == 1, 'segmentComplete': end_reached,
                'startPage': start_page, 'nextPage': next_page, 'reason': reason,
                'reportedTotal': total, 'sourcePageHashes': hashes, 'profile': profile,
                'source': 'official-realtime-pop', 'observedAt': time.time()}

    def prepare_price(self, profile, product_id, changes):
        product_id = identifier(product_id)
        if not isinstance(changes, list) or not changes or len(changes) > 1000:
            raise SafetyError('explicit-bounded-sku-jdprice-changes-required')
        proposed = {}
        for change in changes:
            if not isinstance(change, dict) or set(change) - {'skuId', 'jdPrice', 'expectedOldPrice'} or not {'skuId', 'jdPrice'} <= set(change):
                raise SafetyError('skuId-and-jdPrice-required-not-handPrice')
            sku_id = identifier(change['skuId'])
            if sku_id in proposed:
                raise SafetyError('duplicate-sku-change')
            proposed[sku_id] = {'new': money(change['jdPrice']), 'expected': money(change['expectedOldPrice'], positive=False) if 'expectedOldPrice' in change else None}
        data = self.detail(profile, product_id)
        product_path = _product_identity(data, product_id); category,category_path = _category(data); sku_path, rows = _sku_source(data)
        skus = {}
        for row in rows:
            if not isinstance(row, dict):
                raise SafetyError('invalid-native-sku-row')
            sku_id = identifier(row.get('skuId'))
            if sku_id in skus:
                raise SafetyError('ambiguous-native-sku-id')
            if row.get('productId') is not None and identifier(row['productId']) != product_id:
                raise SafetyError('native-sku-belongs-to-other-product')
            skus[sku_id] = row
        preview = []; patches = []; before = {product_path: product_id,category_path:str(category)}; pending = {'productInfo.productId':product_id}; online = {product_path: product_id}; unchanged = []
        for sku_id, values in proposed.items():
            if sku_id not in skus:
                raise SafetyError('requested-sku-not-in-native-product-detail')
            old = money(_path_value(skus[sku_id], 'priceInfo.jdPrice'), positive=False)
            if values['expected'] is not None and Decimal(old) != Decimal(values['expected']):
                raise SafetyError('explicit-old-price-does-not-match-native-detail')
            field = sku_path + '[skuId==' + sku_id + '].priceInfo.jdPrice'
            before[field] = {'$decimal': old}; online[field] = {'$decimal': values['new']}
            if Decimal(old) == Decimal(values['new']):
                unchanged.append(sku_id); continue
            pending['skuList[skuId==' + sku_id + '].priceInfo.jdPrice'] = {'$decimal': values['new']}
            patches.append({'path': 'skus[skuId==' + sku_id + ']', 'value': json.dumps({'componentCode': 'SkuJdprice', 'value': values['new']}, separators=(',', ':'))})
            preview.append({'skuId': sku_id, 'oldJdPrice': old, 'newJdPrice': values['new']})
        result = {'task': None, 'preview': preview, 'unchangedSkuIds': unchanged, 'requiresApproval': bool(patches),
                  'productId': product_id, 'priceType': 'jdPrice', 'sourceHash': digest(data), 'phase': 'awaiting-approval' if patches else 'already-current',
                  'notice': 'Updates pending application values first; hand price and online activation are separate.'}
        if not patches:
            return result
        body = {'applyId': product_id, 'opType': 3, 'scene': 'pop', 'productInfo': {'productId': int(product_id), 'categoryDetail': {'lastCategoryId': category}},
                'productApplyDTO': {'id': product_id}, 'patchOperationList': patches}
        # The official transport selects binary/stdin from actual argv size.
        # Do not truncate the approved SKU scope to fit a legacy argv estimate.
        query = {'url': DETAIL, 'method': 'GET', 'params': {'productId': int(product_id), 'scene': 'pop'}, 'skillId': 'jdo-product-update'}
        pending_query = {'url': APPLY_DETAIL, 'method': 'GET', 'params': {'applyId': int(product_id), 'scene': 'pop'}, 'skillId': 'jdo-product-update'}
        op = {'url': PATCH, 'method': 'PATCH', 'params': {'applyId': product_id}, 'body': body, 'skillId': 'jdo-product-update'}
        result['task'] = self.ops.prepare(profile, op, {'query': pending_query, 'expected': pending},
                                          precondition={'query': query, 'expected': before}, online_verification={'query': query, 'expected': online})
        return result

    def price_status(self, task_id, *, refresh='none'):
        if refresh not in ('none', 'pending', 'online'):
            raise SafetyError('price-status-refresh-invalid')
        task = self.ops.task(task_id); op = task['scope']['operation']
        if op['method'] != 'PATCH' or op['url'] != PATCH:
            raise SafetyError('native-price-task-required')
        try:
            if not op['body']['patchOperationList'] or any(json.loads(item['value']).get('componentCode') != 'SkuJdprice' for item in op['body']['patchOperationList']):
                raise SafetyError('native-price-task-required')
        except (KeyError, ValueError, TypeError):
            raise SafetyError('native-price-task-required') from None
        if refresh == 'pending' and task['status'] in ('submitted', 'unknown', 'verified'):
            verification = task['scope']['verification']
            task = self.ops.readback(task_id, verification['query'], verification['expected'])
        if refresh == 'online' and task['status'] in ('submitted', 'unknown', 'verified'):
            task = self.ops.verify_online(task_id)
        data = business_payload(task.get('readback', {}).get('result', {}))
        audit = _path_value(data, 'applyInfo.bossAuditStatus')
        audit = int(audit) if isinstance(audit, (int, str)) and re.fullmatch(r'-?[0-9]+', str(audit)) else None
        online = bool(task.get('onlineStateVerified')) and task['status'] != 'unknown' and audit != 11
        phase = 'unknown' if task['status'] == 'unknown' else 'application-audit-rejected' if audit == 11 else 'online-values-confirmed' if online else 'application-values-confirmed' if task.get('targetStateVerified') else 'awaiting-approval' if task['status'] == 'prepared' else 'submitted-awaiting-application-readback'
        return {'taskId': task_id, 'phase': phase, 'requestStatus': task['status'], 'onlineEffective': online,
                'pendingValuesMatch': bool(task.get('targetStateVerified')), 'onlineValuesMatch': bool(task.get('onlineStateVerified')),
                'bossAuditStatus': audit, 'pendingObservedAt':task.get('readback',{}).get('at'), 'onlineObservedAt':task.get('onlineReadback',{}).get('at'), 'lastRefresh':refresh, 'task': task, 'originalOutcomeUnknown': task['status'] == 'unknown'}
