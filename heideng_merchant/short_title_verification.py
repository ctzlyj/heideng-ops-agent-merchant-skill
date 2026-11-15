"""Native actual-title/health sources; field parsing alone is not provenance."""
from __future__ import annotations
import unicodedata
from .operations import digest
from .products import identifier, _product_identity
from .safety import SafetyError, redact

MAX_SKUS = 1000000
MAX_TITLE = 4096

def _refuse():
    raise SafetyError('bounded-original-scope-short-title-detail-required')

def title_detail_observation(detail, product_id, original_sku_ids):
    """Retain the complete original sibling scope, including absent/off-sale rows.

    Only the documented product-detail field is interpreted. The caller still
    must bind a fresh authorized native read, original root and full observations;
    parsing arbitrary JSON cannot prove title effectiveness or moderation.
    """
    product_id = identifier(product_id)
    if not isinstance(original_sku_ids, list) or not 0 < len(original_sku_ids) <= MAX_SKUS:
        _refuse()
    original = [identifier(value) for value in original_sku_ids]
    if len(set(original)) != len(original):
        _refuse()
    if not isinstance(detail, dict) or redact(detail) != detail:
        _refuse()
    _product_identity(detail, product_id)
    lists = []
    for container in (detail, detail.get('productInfo')):
        if isinstance(container, dict) and 'skuList' in container:
            value = container['skuList']
            if not isinstance(value, list) or len(value) > MAX_SKUS:
                _refuse()
            lists.append(value)
    if not lists or any(value != lists[0] for value in lists[1:]):
        _refuse()
    current = {}
    for row in lists[0]:
        if not isinstance(row, dict):
            _refuse()
        sku = identifier(row.get('skuId'))
        if sku in current or 'productId' in row and identifier(row['productId']) != product_id:
            _refuse()
        observed = False
        title = None
        if 'features' in row:
            features = row['features']
            if not isinstance(features, dict):
                _refuse()
            if 'shortTitle' in features:
                title = features['shortTitle']
                if not isinstance(title, str) or len(title) > MAX_TITLE or any(unicodedata.category(c).startswith('C') for c in title) or redact(title) != title:
                    _refuse()
                observed = True
        current[sku] = {'fieldObserved': observed, 'actualShortTitle': title,
                        'reason': 'exact-short-title-field-observed' if observed else 'exact-short-title-field-missing'}
    missing = [sku for sku in original if sku not in current]
    additional = sorted(set(current) - set(original), key=int)
    rows = [{'productId': product_id, 'skuId': sku,
             **current.get(sku, {'fieldObserved': False, 'actualShortTitle': None,
                                'reason': 'original-sku-not-in-current-detail'})}
            for sku in original]
    try:
        source_hash = digest(detail)
    except (TypeError, ValueError):
        _refuse()
    return {'productId': product_id, 'field': 'skuList[].features.shortTitle',
            'detailSha256': source_hash, 'rows': rows,
            'missingOriginalSkuIds': missing, 'additionalCurrentSkuIds': additional,
            'originalSkuCoverageComplete': not missing and not additional,
            'formalAuditVerified': False, 'healthVerified': False,
            'imported': False, 'retryAuthorized': False}

def _health_facts(source, original):
    """Health claims require full source and exact rows, not a totals guess."""
    import math
    by_sku = {}
    if not isinstance(source, dict) or redact(source) != source:
        _refuse()
    items = source.get('items')
    if not isinstance(items, list) or len(items) > MAX_SKUS:
        _refuse()
    for item in items:
        if not isinstance(item, dict):
            _refuse()
        sku = identifier(item.get('skuId'))
        if sku in by_sku:
            _refuse()
        by_sku[sku] = item
    complete = source.get('complete') is True and type(source.get('reportedTotal')) is int and source['reportedTotal'] == len(items) and isinstance(source.get('sourcePageHashes'), list) and bool(source['sourcePageHashes'])
    output = {}
    for row in original:
        sku = row['skuId']; item = by_sku.get(sku); score = None; flag = None
        linked = item is not None
        if linked and 'productId' in item:
            linked = identifier(item['productId']) == row['productId']
        if linked:
            value = item.get('healthScore')
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100:
                score = value
            improvements = item.get('improvementList')
            if isinstance(improvements, list) and all(isinstance(v, dict) and isinstance(v.get('improvementDetail'), dict) and isinstance(v['improvementDetail'].get('troubleCode'), str) and v['improvementDetail']['troubleCode'] for v in improvements):
                flag = any(v['improvementDetail']['troubleCode'] == 'hasShortTitle' for v in improvements)
        output[sku] = {'healthScore': score, 'healthTitleIssue': flag,
                       'healthRowObserved': bool(complete and linked)}
    return output, {'complete': complete, 'sourcePageHashes': source.get('sourcePageHashes', []),
                    'reportedTotal': source.get('reportedTotal'),
                    'originalValuesComplete': complete and all(v['healthScore'] is not None and v['healthTitleIssue'] is not None and v['healthRowObserved'] for v in output.values())}


def observe_original_effects(manager, import_id, browser, *, max_pages=1000):
    """Read live original POP details/health using the still-owned browser guard.

    This read does not store a C3 receipt, start media or mutate a shop. No
    formal short-title moderation or portal source is invented. These facts are
    not a terminal receipt and cannot release update/write quarantine.
    """
    from .short_title_contract import source_context
    from .short_title_import_state import evidence
    from .short_title_result_state import read_log, result_rows
    from .products import ProductService
    if type(max_pages) is not int or not 1 <= max_pages <= 1000:
        _refuse()
    root = manager.record(import_id)
    manager._browser(root, browser)
    browser.install_lock.require_owned(manager.state / 'install.lock')
    manager._current(root, readonly=True)
    plan = manager.plans.plan(root['scope']['planId'])
    _, original = source_context(manager.state, plan['scope']['auditId'], plan['scope']['auditFingerprint'])
    history = evidence(manager.state, root)
    latest, sequence, result_receipt_sha = read_log(manager.state, root, history[3])
    results = {v['skuId']: v for v in result_rows(root, history[3], latest)}
    products = {}
    for row in original:
        products.setdefault(row['productId'], []).append(row['skuId'])
    reader = ProductService(manager.state, manager.client)
    profile = root['scope']['shop']['profile']
    def owned():
        manager._browser(root,browser)
        browser.install_lock.require_owned(manager.state / 'install.lock')
    from .operations import _same_identity
    def native_identity():
        owned()
        actual = manager.client.identity(profile)
        owned()
        if not isinstance(actual, dict) or redact(actual) != actual or not _same_identity(actual, root['scope']['shop']):
            raise SafetyError('original-effects-current-shop-identity-required')
        return {key: str(actual[key]) for key in ('venderId', 'shopId', 'shopName', 'shopType')}
    start_identity = native_identity()
    def details():
        values = {}
        for pid, skus in sorted(products.items(), key=lambda pair: int(pair[0])):
            owned()
            manager._current(root, readonly=True)
            owned()
            raw = reader.detail(profile, pid)
            owned()
            manager._current(root, readonly=True)
            owned()
            values[pid] = title_detail_observation(raw, pid, skus)
        return values
    start = details()
    owned()
    health = reader.list_health(profile, page_size=100, max_pages=max_pages)
    owned()
    manager._current(root, readonly=True)
    owned()
    health_values, health_source = _health_facts(health, original)
    end = details()
    manager._current(root, readonly=True)
    owned()
    if manager.record(import_id)['fingerprint'] != root['fingerprint']:
        _refuse()
    stable = all(start[pid]['detailSha256'] == end[pid]['detailSha256'] for pid in products)
    full_scope = all(end[pid]['originalSkuCoverageComplete'] for pid in products)
    title_values = {v['skuId']: v for source in end.values() for v in source['rows']}
    output = []
    for row in original:
        sku = row['skuId']; actual = title_values[sku]; processed = results.get(sku)
        target = processed is not None
        match = bool(target and actual['fieldObserved'] and stable and actual['actualShortTitle'] == processed['proposedShortTitle'])
        outcome = processed['outcome'] if target else 'not-target'
        output.append({'productId': row['productId'], 'skuId': sku,
                       'originalOnSale': row['onSale'], 'target': target,
                       'actualShortTitle': actual['actualShortTitle'],
                       'actualFieldObserved': actual['fieldObserved'],
                       'actualTitleMatchesProposed': match,
                       'actualTitleVerified': match and outcome == 'success' and full_scope,
                       'processingOutcome': outcome,
                       'proposedShortTitle': processed['proposedShortTitle'] if target else None,
                       **health_values[sku], 'formalAuditStatus': 'unverified-source-contract',
                       'formalAuditVerified': False, 'retryAuthorized': False})
    targets = [row for row in output if row['target']]
    end_identity = native_identity()
    owned()
    if end_identity != start_identity:
        _refuse()
    return {'importId': import_id, 'fingerprint': root['fingerprint'],
            'originalAuditFingerprint': plan['scope']['auditFingerprint'],
            'originalResultReceiptSha256': result_receipt_sha,
            'originalResultSequence': sequence, 'rows': output,
            'identitySha256': digest(start_identity),
            'originalAnchors': {f'{batch:06d}': digest(value) for (batch, phase), value in history[3].items() if phase == 'create'},
            'detailSources': [{'productId': pid, 'startSha256': start[pid]['detailSha256'],
                               'endSha256': end[pid]['detailSha256'],
                               'missingOriginalSkuIds': end[pid]['missingOriginalSkuIds'],
                               'additionalCurrentSkuIds': end[pid]['additionalCurrentSkuIds']}
                              for pid in sorted(products, key=int)],
            'healthSource': health_source, 'currentIdentityVerified': True,
            'sourceDetailsStable': stable, 'currentOriginalScopeComplete': full_scope,
            'currentTargetTitlesMatch': bool(targets) and all(v['actualTitleMatchesProposed'] for v in targets),
            'actualTitlesVerified': bool(targets) and all(v['actualTitleVerified'] for v in targets),
            'formalAuditVerified': False, 'portalVerified': False, 'healthVerified': False,
            'C3ReceiptPersisted': False, 'imported': False, 'retryAuthorized': False}
