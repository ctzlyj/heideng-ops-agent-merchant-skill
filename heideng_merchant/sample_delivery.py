"""Resolve an accepted local image and its actual published SKU from the original receipts."""
from pathlib import Path
import re

from .safety import SafetyError, file_sha, read_json, safe_join


def _numeric(value):
    value = str(value or '')
    return value if value.isascii() and value.isdecimal() and int(value) > 0 else None


def target_sku(parent_dir, parent, sku_key):
    """Resolve the target SKU using its local key, merchant code, and official readback."""
    result = {'productId':None, 'skuId':None, 'skuUrl':None, 'spec':None, 'targetStatus':'unverified'}
    try:
        return _resolve_sku(Path(parent_dir), parent, sku_key, result)
    except (OSError, TypeError, KeyError, ValueError, SafetyError):
        # One unreadable SKU receipt must not hide the independently verified image.
        return result


def _resolve_sku(directory, parent, sku_key, target):
    state = read_json(safe_join(directory, 'state.json'), {})
    product_id = _numeric(state.get('productId'))
    manifest_id = _numeric(parent.get('productId'))
    if state.get('status') != 'SUCCEEDED' or not product_id:
        if not manifest_id and state.get('status') not in ('SUBMITTING','UNKNOWN','SUCCEEDED'):
            target['targetStatus'] = 'unpublished'
        return target
    if manifest_id and product_id != manifest_id:
        return target
    target['productId'] = product_id
    facts = [s for s in (parent.get('facts') or {}).get('skus', []) if s.get('key') == sku_key]
    if len(facts) == 1:
        target['spec'] = facts[0].get('spec')

    listing = read_json(safe_join(directory, 'listing.json'), {})
    if state.get('itemNumber') and listing and state['itemNumber'] != listing.get('product', {}).get('itemNumber'):
        return target
    local = [s for s in listing.get('skus', []) if s.get('skuKey') == sku_key]
    variants = [s for s in parent.get('variants', []) if s.get('key') == sku_key]
    if len(local) > 1 or len(variants) > 1 or len(facts) > 1:
        return target
    codes = {s['vendorSku'] for s in local + variants if s.get('vendorSku')}
    if len(codes) > 1:
        return target
    code = next(iter(codes), None)
    if code and any(s.get('vendorSku') == code and s.get('skuKey') != sku_key for s in listing.get('skus', [])):
        return target
    direct = _numeric(variants[0].get('skuId')) if variants else None
    matches = set()
    for filename in ('readback-product.json','readback-apply.json'):
        detail = read_json(safe_join(directory, '.publish/'+filename), {})
        if not detail:
            continue
        if _numeric((detail.get('productInfo') or {}).get('productId')) != product_id:
            return target
        rows = detail.get('skuList') or []
        if sku_key is None:
            # For a shared main image, only a single real SKU makes a unique target link.
            selected = rows if len(rows) == 1 else []
        elif code:
            selected = [s for s in rows if s.get('outerId') == code]
        else:
            selected = [s for s in rows if direct and _numeric(s.get('skuId')) == direct]
        if len(selected) != 1:
            return target
        sid = _numeric(selected[0].get('skuId'))
        if not sid or (direct and sid != direct) or sum(_numeric(s.get('skuId')) == sid for s in rows) != 1:
            return target
        matches.add(sid)
    if len(matches) != 1:
        return target
    sid = matches.pop()
    target.update(skuId=sid, skuUrl=f'https://item.jd.com/{sid}.html', targetStatus='verified')
    return target


def accepted_delivery(state, shop, vendor, parent_dir, parent, sample_dir, manifest):
    """Read only content-addressed merchant acceptances for this parent task and image ID."""
    from .sample_comparison import read_comparison
    from .sample_upload_state import sample_upload_state

    image_id = manifest['sampleOf']['imageId']
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', image_id):
        return None
    versions, invalid = [], 0
    for relative, acceptance in parent.get('acceptedSamples', {}).items():
        digest = acceptance.get('sha256', '')
        if relative != f'已接受样张/{image_id}-{digest}.jpg':
            continue
        if (not re.fullmatch(r'[0-9a-f]{64}', digest) or not acceptance.get('evidence') or
                acceptance.get('role') not in ('sku','main') or
                (acceptance['role'] == 'sku' and not acceptance.get('skuKey'))):
            invalid += 1
            continue
        try:
            image = safe_join(parent_dir, relative)
            if not image.is_file() or file_sha(image) != digest:
                invalid += 1
                continue
        except (SafetyError, OSError):
            invalid += 1
            continue
        key = acceptance.get('skuKey')
        target = target_sku(parent_dir, parent, key)
        accepted_target = acceptance.get('targetAtAcceptance')
        if accepted_target and (target['productId'],target['skuId']) != (
                accepted_target.get('productId'),accepted_target.get('skuId')):
            target.update(skuId=None, skuUrl=None, targetStatus='needs-reconciliation')
        source_product = (parent.get('reference') or {}).get('sourceSpuId')
        try:
            comparison = read_comparison(sample_dir, sample_sha=digest, target_product_id=target['productId'],
                target_sku_id=target['skuId'], source_sku_id=acceptance.get('sourceSkuId'), source_product_id=source_product)
        except (OSError, KeyError, TypeError, ValueError, SafetyError):
            comparison = {'kind':'unknown','status':'unverified','label':'对比图来源待核'}
        upload = sample_upload_state(state, shop, vendor, target['productId'], target['skuId'], digest, package=parent_dir)
        versions.append({'status':'accepted', 'imageId':image_id, 'role':acceptance['role'], 'skuKey':key,
                         'imagePath':str(image), 'imageSha256':digest, **target, 'comparison':comparison, 'upload':upload})
    if invalid or len(versions) > 1:
        return {'status':'needs-verification' if invalid else 'ambiguous', 'imageId':image_id,
                'versions':versions, 'unverifiedCount':invalid}
    return next(iter(versions), None)
