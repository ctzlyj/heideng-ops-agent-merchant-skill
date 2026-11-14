"""Mandatory native-price contract at the shared task boundary, not a caller-only convention."""
from __future__ import annotations
import json
import re
from .safety import SafetyError
from .verification import business_payload

DETAIL = '/rest/sp-product/v0/products/{productId}'
PENDING = '/rest/sp-product/v0/product-apply/{applyId}'
PATCH = '/rest/sp-product/v0/product-applies/{applyId}'


def native_price_operation(operation):
    if operation.get('method') != 'PATCH' or not str(operation.get('url', '')).startswith('/rest/sp-product/v0/product-applies/'):
        return False
    body = operation.get('body', {})
    patches = body.get('patchOperationList', []) if isinstance(body, dict) else []
    if not isinstance(patches, list):
        return False
    for item in patches:
        value = item.get('value') if isinstance(item, dict) else None
        try:
            component = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            component = None
        if isinstance(component, dict) and str(component.get('componentCode', '')).casefold() == 'skujdprice':
            return True
    return False


def _query(query, template, parameter, product_id):
    from .products import identifier
    if query.get('method') != 'GET' or query.get('url') not in (template, template.replace('{' + parameter + '}', product_id)):
        raise SafetyError('native-price-query-must-address-approved-product')
    params = query.get('params', {})
    if params.get('scene') != 'pop' or identifier(params.get(parameter)) != product_id:
        raise SafetyError('native-price-query-must-address-approved-product')


def _identity_expected(expected, product_id):
    return any(str(expected.get(path)) == product_id for path in ('productId', 'productInfo.productId'))


def _decimal_expected(expected, paths, *, positive=True):
    from .products import money
    for path in paths:
        value = expected.get(path)
        if isinstance(value, dict) and set(value) == {'$decimal'}:
            return money(value['$decimal'], positive=positive)
    raise SafetyError('native-price-sku-values-must-be-bound-before-approval')


def price_contract(scope):
    operation = scope['operation']
    if not native_price_operation(operation):
        return None
    from .products import identifier, money
    try:
        body = operation['body']; product_id = identifier(body['productInfo']['productId']); category = identifier(body['productInfo']['categoryDetail']['lastCategoryId'])
        if body['scene'] != 'pop' or body['opType'] != 3 or not isinstance(body['applyId'], str) or not isinstance(body['productApplyDTO']['id'], str) or isinstance(body['productInfo']['productId'], bool) or not isinstance(body['productInfo']['productId'], int):
            raise SafetyError('native-price-flat-pop-body-required')
        if identifier(body['applyId']) != product_id or identifier(body['productApplyDTO']['id']) != product_id:
            raise SafetyError('native-price-body-product-id-conflict')
        if operation['url'] not in (PATCH, PATCH.replace('{applyId}', product_id)) or identifier(operation['params'].get('applyId')) != product_id:
            raise SafetyError('native-price-path-product-id-conflict')
        targets = {}
        for patch in body['patchOperationList']:
            component = json.loads(patch['value']); match = re.fullmatch(r'skus\[skuId==([1-9][0-9]{0,18})\]', patch['path'])
            if component.get('componentCode') != 'SkuJdprice' or set(component)!={'componentCode','value'} or not isinstance(component.get('value'),str) or match is None or set(patch) != {'path', 'value'}:
                raise SafetyError('native-price-sku-only-component-scope-required')
            sku_id = identifier(match[1])
            if sku_id in targets:
                raise SafetyError('duplicate-native-price-sku')
            targets[sku_id] = money(component['value'])
        before = scope['precondition']; pending = scope['verification']; online = scope['onlineVerification']
        _query(before['query'], DETAIL, 'productId', product_id); _query(online['query'], DETAIL, 'productId', product_id); _query(pending['query'], PENDING, 'applyId', product_id)
        if not _identity_expected(before['expected'], product_id) or not _identity_expected(pending['expected'], product_id) or not _identity_expected(online['expected'], product_id):
            raise SafetyError('native-price-product-identity-must-be-bound')
        if not any(str(before['expected'].get(path)) == category for path in ('categoryDetail.lastCategoryId', 'productInfo.categoryDetail.lastCategoryId', 'categoryDTO.lastCategoryId')):
            raise SafetyError('native-price-category-must-be-bound')
        for sku_id, new in targets.items():
            paths = [prefix + '[skuId==' + sku_id + '].priceInfo.jdPrice' for prefix in ('skuList', 'productInfo.skuList')]
            _decimal_expected(before['expected'], paths, positive=False)
            if _decimal_expected(pending['expected'], ['skuList[skuId==' + sku_id + '].priceInfo.jdPrice']) != new or _decimal_expected(online['expected'], paths) != new:
                raise SafetyError('native-price-verification-does-not-match-approved-values')
    except (KeyError, TypeError, ValueError):
        raise SafetyError('native-price-requires-flat-body-and-complete-three-stage-evidence') from None
    return {'productId': product_id, 'categoryId': category, 'targets': targets}


def validate_native_price_response(contract, response, *, stage):
    from .products import _product_identity, _category, _sku_source, _path_value, identifier, money
    data = business_payload(response)
    if not isinstance(data, dict):
        raise SafetyError('native-price-response-object-required')
    _product_identity(data, contract['productId'])
    category_present = any(_path_value(data, path) is not None for path in ('categoryDetail', 'productInfo.categoryDetail', 'categoryDTO'))
    if stage == 'before' or category_present:
        category, _ = _category(data)
        if stage == 'before' and str(category) != contract['categoryId']:
            raise SafetyError('native-price-source-category-changed')
    _, rows = _sku_source(data)
    skus = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SafetyError('invalid-native-sku-row')
        sku_id = identifier(row.get('skuId'))
        if sku_id in skus:
            raise SafetyError('ambiguous-native-sku-id')
        if row.get('productId') is not None and identifier(row['productId']) != contract['productId']:
            raise SafetyError('native-sku-belongs-to-other-product')
        skus[sku_id] = row
    for sku_id in contract['targets']:
        if sku_id not in skus:
            raise SafetyError('native-price-target-sku-missing')
        money(_path_value(skus[sku_id], 'priceInfo.jdPrice'), positive=False)
    return data
