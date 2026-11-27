"""Inventory and scope checks shared by the internal and merchant POP audits."""
from concurrent.futures import ThreadPoolExecutor


def _id(row, key):
    return str(row.get(key) or '').strip()


def _read_siblings(client, products, workers):
    groups = [products[i:i + 10] for i in range(0, len(products), 10)]
    siblings = []
    seen = set()
    with ThreadPoolExecutor(max_workers=min(workers, max(len(groups), 1))) as reader:
        for group, rows in zip(groups, reader.map(client.skus, groups)):
            for row in rows:
                sku = _id(row, 'skuId')
                if _id(row, 'productId') not in group:
                    raise ValueError('coverage SKU lookup returned an out-of-scope product')
                if not sku or sku in seen:
                    raise ValueError('coverage inventory contains empty or duplicate SKU IDs')
                seen.add(sku)
                siblings.append(row)
    return siblings


def _online(rows):
    return [r for r in rows if int(r.get('skuStatus') or r.get('status') or 0) == 103]


def _scope_key(rows):
    return {(_id(r, 'productId'), _id(r, 'skuId'), int(r.get('skuStatus') or r.get('status') or 0)) for r in rows}


def audit_inventory(client, list_products, *, product_ids=None, authorized_sku_ids=None, workers=8):
    """Read exact siblings when scoped. Keep the whole-shop census for unscoped callers."""
    scoped = product_ids is not None
    if scoped:
        products = list(dict.fromkeys(str(pid).strip() for pid in product_ids))
        if not products or not all(products):
            raise ValueError('coverage requires a nonempty target product scope')
    else:
        products = [_id(row, 'productId') for row in list_products()]
    siblings = _read_siblings(client, products, workers)
    online = _online(siblings)
    if scoped and {_id(row, 'productId') for row in online} != set(products):
        raise ValueError('target product has no verified on-sale SKUs in this shop')
    if authorized_sku_ids is not None:
        allowed = set(map(str, authorized_sku_ids))
        if not allowed or not allowed.issubset({_id(r, 'skuId') for r in online}):
            raise ValueError('one or more frozen SKUs could not be verified on sale')
        online = [row for row in online if _id(row, 'skuId') in allowed]

    def verify():
        if scoped:
            if _scope_key(siblings) != _scope_key(_read_siblings(client, products, workers)):
                raise ValueError('target product SKU scope changed during coverage audit')
        elif {_id(row, 'productId') for row in list_products()} != set(products):
            raise ValueError('on-sale product scope changed during coverage audit')

    return products, siblings, online, verify


def material_rows(payload, error_type):
    rows = payload.get('data')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise error_type('SKU 素材查询未返回有效列表')
    # An explicit success echoing just an identifier is evidence of an empty binding.
    return [dict(row, materials=None) if 'materials' not in row and
            (payload.get('success') is not True or not set(row) <= {'skuId', 'productId'})
            else row for row in rows]


def read_materials(client, identifiers, error_type, *, read_gaps=None, workers=8):
    """Fetch image/text batches independently. Strict callers stop on any missing evidence."""
    identifiers = list(map(str, identifiers))
    materials = {sku: [] for sku in identifiers}
    jobs = [(identifiers[i:i + 50], kinds, scope)
            for i in range(0, len(identifiers), 50)
            for kinds, scope in (((31, 32, 33, 36), 1), ((1002,), 2))]

    def read(job):
        group, kinds, scope = job
        try:
            rows = client.sku_materials(group, kinds, scope)
            by_sku = {_id(row, 'skuId'): row for row in rows}
            if len(rows) != len(by_sku) or set(by_sku) - set(group):
                raise ValueError('SKU material verification returned unexpected or duplicate SKUs')
            missing = [sku for sku in group if sku not in by_sku or
                       ('materials' in by_sku[sku] and not isinstance(by_sku[sku]['materials'], list))]
            if missing and read_gaps is None:
                raise ValueError('SKU material verification returned an incomplete SKU set')
            return [row for sku, row in by_sku.items() if sku not in missing], missing, kinds
        except (error_type, OSError, ValueError, TypeError, KeyError):
            if read_gaps is None:
                raise
            return [], group, kinds

    with ThreadPoolExecutor(max_workers=min(workers, max(len(jobs), 1))) as reader:
        for rows, missing, kinds in reader.map(read, jobs):
            for sku in missing:
                read_gaps.setdefault(sku, []).extend(kinds)
            for row in rows:
                materials[_id(row, 'skuId')].extend(row.get('materials') or [])
    return materials


def slot_state(matches, value_for):
    statuses = {int(entry.get('status') or 0) for entry in matches}
    approved = list(dict.fromkeys(value_for(entry) for entry in matches
                                  if int(entry.get('status') or 0) == 4 and value_for(entry)))
    if 3 in statuses:
        return 'pending', approved
    if approved:
        return 'approved', approved
    if 5 in statuses:
        return 'rejected', []
    return ('unknown' if matches else 'missing'), []
