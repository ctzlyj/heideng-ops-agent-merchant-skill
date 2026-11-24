"""Read-only discovery of shop-owned image, listing and edit receipts."""
from hashlib import sha256
import os
from pathlib import Path
import sys
from . import require_local

from .safety import SafetyError, atomic_json, is_linked, read_json, safe_join
from .state import FileLock, merchant_home


GOALS = {'listing':'商品上新与复刻', 'sample':'商品样张', 'creative':'商业图计划', 'sku-edit':'原链接规格图更新'}
CREATIVE_LEDGERS = {'image-refresh':'internal-generation.json', 'matrix-listing':'ledger.json',
                    'commercial-replica':'generation.json'}


def _task_id(kind, directory, identifier):
    return sha256(f'{kind}|{directory}|{identifier}'.encode()).hexdigest()


def register(kind, directory, store, identifier):
    """Remember task directories outside the default work tree as well."""
    if not os.environ.get('HEIDENG_MERCHANT_HOME') or not store.get('venderId') or not identifier:
        return
    directory = Path(directory).resolve()
    path = merchant_home()/'commercial-tasks'/(_task_id(kind, directory, identifier)+'.json')
    record = {'kind':kind, 'directory':str(directory), 'identifier':str(identifier),
              'store':{k:str(store[k]) for k in ('shopId','venderId','profile','shopName') if store.get(k)}}
    with FileLock(path.with_suffix('.lock')):
        if read_json(path, {}) != record:
            atomic_json(path, record)


def _matches(store, shop, vendor, profiles):
    if str(store.get('venderId') or '') != vendor:
        return False
    if store.get('shopId'):
        return str(store['shopId']) == shop
    # Legacy manifests carried only vendor and profile. Require the saved verified pair.
    entry = profiles.get(store.get('profile'), {})
    return (str(entry.get('venderId') or '') == vendor and str(entry.get('shopId') or '') == shop
            and (not store.get('shopName') or entry.get('shopName') == store['shopName']))


def _files(base, *filenames):
    """Do not traverse symlinks, browser data, image caches, or nested sample packages."""
    if not base.is_dir() or any(is_linked(p) for p in (base, *base.parents)):
        return
    require_local(base,parents=True)
    for folder, children, names in os.walk(base):
        path = Path(folder)
        children[:] = [c for c in children if not c.startswith('.') and not is_linked(path/c)
                       and c not in {'browser-profiles','node_modules','uploads','sources','实拍图','已接受样张'}]
        for child in children:
            require_local(path/child)
        for filename in filenames:
            if filename in names and not is_linked(path/filename):
                yield path/filename


def _entry(kind, directory, identifier, receipt):
    return {'kind':kind, 'goal':GOALS[kind], 'taskId':_task_id(kind, directory, identifier),
            'taskDirectory':str(directory), 'receipt':str(receipt), 'updatedAt':receipt.stat().st_mtime,
            'readOnly':True, 'nextAction':'核对原任务回执。'}


def _records(folder, pattern):
    require_local(folder,parents=True)
    for path in folder.glob(pattern):
        if is_linked(path):
            continue
        try:
            record = read_json(path)
        except (OSError, SafetyError):
            continue
        if isinstance(record, dict):
            yield path, record


def _generation(entry, directory, ledger_name, quote, grants):
    ledger_path = safe_join(directory, ledger_name)
    ledger = read_json(ledger_path, {})
    path = safe_join(directory, '.state/paid-image-budget.json')
    budget = read_json(path, {})
    states = {key:str(value.get('status', '')).upper() for key,value in ledger.items()
              if isinstance(value, dict)}
    pending = set(quote.get('pendingUnits', quote.get('units', [])))
    complete = {key for key,state in states.items() if state in ('SUCCEEDED','OK')}
    unknown = {key for key,state in states.items() if state in
               ('STARTED','REQUEST-STARTED','UNKNOWN','ATTEMPTED','SUBMITTING')}
    latest = {}
    for reservation, row in budget.get('requests', {}).items():
        key = row.get('unit')
        if key and row.get('state') == 'reserved':
            latest[key] = (reservation,row)
    for key,(reservation,row) in latest.items():
        old = ledger.get(key, {})
        if key not in states or (ledger_name.startswith('.generation/') and (
                old.get('reservationId') != reservation if old.get('reservationId')
                else old.get('approvalRef') != row.get('approvalRef'))):
            unknown.add(key)
            complete.discard(key)
    entry.update(generatedUnits=sorted(complete), unknownUnits=sorted(unknown),
                 pendingUnits=sorted(pending-complete-unknown))
    for receipt in (ledger_path, path):
        if receipt.is_file():
            entry['updatedAt'] = max(entry['updatedAt'], receipt.stat().st_mtime)
    entry['feeDecisions'] = []
    for record in grants:
        approval = record.get('approval', {})
        scope = approval.get('scope') or {}
        orig = quote.get('scope')
        if not orig or {k:v for k,v in scope.items() if k not in ('unresolvedRequests','possibleDuplicateCharge')} != orig:
            continue
        attempts = record.get('attempts', {})
        if 'packageId' not in entry and not any(a.get('directory') == str(directory) for a in attempts.values()):
            # Commercial plans can share an identical source shop, variant and unit names.
            # A copied approval for another task does not establish a budget for this one.
            continue
        entry['feeDecisions'].append({'approvalRef':approval.get('approvalRef'), 'units':approval.get('units'),
                    'maxRequests':approval['maxRequests'], 'remainingRequests':max(0, approval['maxRequests']-len(attempts))})
    if unknown:
        entry['state'] = 'needs-reconciliation'
        entry['nextAction'] = '从原包只读对账未知图片请求，先核对原计费与产物。'
    elif entry['pendingUnits']:
        entry['nextAction'] = '核对原图位、已批准范围和剩余次数，只处理未交付项。'


def _listing(directory, manifest, grants, parent=None, *, state_root=None, shop=None, vendor=None):
    receipt = safe_join(directory,'manifest.json')
    kind = 'sample' if parent else 'listing'
    entry = _entry(kind, directory, manifest['packageId'], receipt)
    entry.update(title=manifest.get('title',''), packageId=manifest['packageId'],
                 productId=str((parent or manifest).get('productId') or ''),
                 sourceProductId=str((manifest.get('reference') or {}).get('sourceSpuId') or ''),
                 state=manifest.get('status') or 'recoverable')
    if parent:
        entry.update(parentTaskId=_task_id('listing',directory.parent.parent,parent['packageId']),
                     imageId=manifest['sampleOf']['imageId'])
    quote_path = safe_join(directory,'image-quote.json')
    quote = read_json(quote_path, {})
    if quote and quote.get('scope',{}).get('task') == manifest['packageId']:
        entry['quoteFile'] = str(quote_path)
        _generation(entry, directory, '.generation/generation.json', quote, grants)
    if parent:
        from .sample_delivery import accepted_delivery
        delivery = accepted_delivery(state_root, shop, vendor, directory.parent.parent, parent, directory, manifest)
        if delivery:
            entry['sampleDelivery'] = delivery
            if delivery['status'] == 'accepted':
                entry.update(state='sample-accepted', productId=delivery['productId'] or '',
                             nextAction='向商家展示已接受原图、对应规格商品链接、上传状态及可核对的对比来源。')
            else:
                entry.update(state='sample-'+delivery['status'], nextAction='原样张有多个版本或文件待核对，请据原回执区分。')
        elif entry['state'] == 'MATERIAL_PREVIEW':
            entry['nextAction'] = '展示原样张与源图，已有成图可直接复用。'
        return entry
    state = read_json(safe_join(directory,'state.json'), {})
    publish_state = state.get('status')
    if publish_state in ('UNKNOWN','SUBMITTING','REJECTED','SUCCEEDED'):
        entry['publishStatus'] = publish_state
        entry['nextAction'] = '核对原发布回执与商品状态，沿用原商品标识。'
        if publish_state in ('UNKNOWN','SUBMITTING'):
            entry.update(state='needs-reconciliation', nextAction='先按原发布货号对账，结果未知时不再提交。')
    if publish_state == 'SUCCEEDED' and entry['productId'] == str(state.get('productId')):
        # Only expose previously read-back SKU links. An active backend listing is not proof of a shopper view.
        verified = read_json(safe_join(directory,'.publish/verification.json'), {})
        links = verified.get('consumerLinks') or manifest.get('consumerLinks') or []
        allowed = {str(v) for v in manifest.get('skuIds') or []}
        entry['consumerLinks'] = [f"https://item.jd.com/{v['skuId']}.html" for v in links
                                  if str(v.get('skuId','')).isdecimal() and str(v['skuId']) in allowed]
        if not entry['consumerLinks'] and verified.get('problems') == []:
            entry['consumerLinks'] = [f'https://item.jd.com/{sku}.html' for sku in sorted(allowed) if sku.isdecimal()]
        entry['consumerPageStatus'] = 'unchecked'
    uploads = read_json(safe_join(directory,'.publish/uploads.json'), {})
    if any(item.get('status') in ('UNKNOWN','SUBMITTING') for item in uploads.values() if isinstance(item,dict)):
        entry.update(state='needs-reconciliation', nextAction='核对原图片空间上传回执，暂缓重复上传与发品。')
    return entry


def _sample_entries(directory, manifest, grants, state, shop, vendor):
    for file in safe_join(directory,'.samples').glob('*/manifest.json'):
        if is_linked(file) or is_linked(file.parent):
            continue
        sample = read_json(file, {})
        if (sample.get('sampleOf') == {'packageId':manifest['packageId'],'imageId':file.parent.name}
                and sample.get('store') == manifest['store'] and sample.get('packageId')):
            yield _listing(file.parent,sample,grants,parent=manifest,state_root=state,shop=shop,vendor=vendor)


def accepted_sample_context(state, *, shop_id=None, vender_id=None, product_id=None, task_id=None, image_sha=None):
    """Resolve an accepted sample from local receipts, even without a previous chat directory."""
    state = Path(state).resolve()
    profiles = read_json(safe_join(state,'linker/shops.json'), {}).get('profiles', {})
    directories = {file.parent for file in _files(state/'work/listing', 'manifest.json')}
    for _, record in _records(safe_join(state,'commercial-tasks'),'*.json'):
        if record.get('kind') == 'listing' and isinstance(record.get('directory'),str):
            path = Path(record['directory'])
            if path.is_absolute() and not any(is_linked(p) for p in (path,*path.parents)):
                directories.add(path)
    matches = []
    for directory in sorted(directories):
        try:
            manifest = read_json(safe_join(directory,'manifest.json'), {})
            if manifest.get('mode') != 'photo-new-listing' or not manifest.get('acceptedSamples') or not manifest.get('packageId'):
                continue
            store = manifest['store']
            verified = profiles.get(store.get('profile'), {})
            shop, vendor = str(verified.get('shopId') or ''), str(verified.get('venderId') or '')
            if (not verified.get('lastVerifiedAt') or not shop.isdecimal() or not vendor.isdecimal()
                    or (shop_id and shop_id != shop) or (vender_id and vender_id != vendor)
                    or not _matches(store,shop,vendor,profiles)):
                continue
            for task in _sample_entries(directory,manifest,[],state,shop,vendor):
                delivery = task.get('sampleDelivery')
                if not delivery or (task_id and task['taskId'] != task_id):
                    continue
                cards = delivery.get('versions') if delivery.get('status') == 'ambiguous' else None
                for card in cards or [delivery]:
                    if (product_id and str(card.get('productId') or task.get('productId')) != product_id
                            or image_sha and card.get('imageSha256') != image_sha):
                        continue
                    matches.append({'taskId':task['taskId'], 'shopName':verified.get('shopName'),
                                    'shopId':shop,'venderId':vendor,'title':manifest.get('title'),
                                    'delivery':card})
        except (KeyError, TypeError, ValueError, OSError, SafetyError):
            continue
    if len(matches) == 1:
        verified = matches[0]['delivery']['status'] == 'accepted'
        return {'selection':'matched' if verified else 'needs-verification', **matches[0], 'readOnly':True}
    choices = [{**{k:v for k,v in m.items() if k!='delivery'},
                **{k:m['delivery'].get(k) for k in ('imageId','spec','productId','skuId','imageSha256')}} for m in matches]
    return {'selection':'ambiguous' if choices else 'not-found','choices':choices,'readOnly':True}


def commercial_tasks(state, shop, vendor):
    state = Path(state).resolve()
    profiles = read_json(safe_join(state,'linker/shops.json'), {}).get('profiles', {})
    grants = [record for path,record in _records(safe_join(state,'fee-consents'),'fee-*.json')
              if path.stem == record.get('approval',{}).get('approvalRef')]
    directories = {}
    for root, names in [('listing',('manifest.json','image-quote.json')), ('refresh',('image-quote.json',))]:
        for file in _files(state/'work'/root, *names):
            directories[('listing' if file.name == 'manifest.json' else 'creative', file.parent)] = None
    for path,record in _records(safe_join(state,'commercial-tasks'),'*.json'):
        if record.get('kind') in ('listing','creative') and _matches(record.get('store',{}),shop,vendor,profiles):
            directory = Path(record['directory'])
            if directory.is_absolute() and not any(is_linked(p) for p in (directory,*directory.parents)):
                directories.setdefault((record['kind'],directory), record['identifier'])
    entries = []
    for (kind,directory), identifier in directories.items():
        try:
            if kind == 'listing':
                m = read_json(safe_join(directory,'manifest.json'), {})
                package = m.get('packageId')
                if not package or m.get('mode') != 'photo-new-listing' or m.get('sampleOf') or (identifier and package != identifier):
                    continue
                if not _matches(m.get('store', {}),shop,vendor,profiles):
                    continue
                entries.append(_listing(directory,m,grants))
                entries.extend(_sample_entries(directory,m,grants,state,shop,vendor))
            else:
                path = safe_join(directory,'image-quote.json')
                quote = read_json(path,{})
                scope = quote.get('scope',{})
                variant = scope.get('kind')
                if (variant not in CREATIVE_LEDGERS or (identifier and identifier != variant)
                        or not _matches(scope.get('shop',{}),shop,vendor,profiles)):
                    continue
                entry = _entry('creative', directory, variant, path)
                entry.update(state='recoverable', operation=variant, productIds=[str(v) for v in
                    (scope.get('products') or [scope.get('productId') or scope.get('product')]) if v])
                _generation(entry,directory,CREATIVE_LEDGERS[variant],quote,grants)
                entries.append(entry)
        except (OSError, KeyError, TypeError, ValueError, SafetyError):
            # A removed, incomplete or unverifiable legacy package cannot identify this shop.
            continue
    for path in _files(state/'work'/'sku-image-edits'/vendor, 'current.json'):
        directory = path.parent
        try:
            receipt = read_json(path,{})
        except (OSError, SafetyError):
            continue
        product = str(receipt.get('productId',''))
        if not product.isdecimal() or directory != state/'work'/'sku-image-edits'/vendor/product:
            continue
        identity = receipt.get('shopIdentity')
        if identity:
            if not _matches(identity,shop,vendor,profiles):
                continue
        elif {str(s.get('shopId') or '') for s in profiles.values() if str(s.get('venderId')) == vendor} != {shop}:
            continue
        entry = _entry('sku-edit', directory, product, path)
        entry.update(productId=product, state=receipt.get('status'), consumerPageStatus='unchecked',
                     nextAction='沿原编辑回执只读核对各 SKU 图片及商品状态。')
        origins = [other for other in entries if other['kind'] == 'listing' and other.get('productId') == product
                   and other.get('publishStatus') == 'SUCCEEDED']
        if len(origins) == 1:
            entry.update(parentTaskId=origins[0]['taskId'], sourceProductId=origins[0]['sourceProductId'])
        entries.append(entry)
    for entry in entries:
        entry['shopIdentity'] = {'shopId':shop,'venderId':vendor}
        if entry['kind'] in ('listing','sample') and entry.get('unknownUnits'):
            wrapper = Path(os.environ.get('HEIDENG_MERCHANT_PACKAGE') or Path(__file__).resolve().parents[1])
            entry['readbackArgv'] = [sys.executable, '-I', '-B', str(wrapper/'scripts/merchant.py'),
                '--state', str(state), 'run', 'photo-listing', '--', 'reconcile-images', '--package',
                entry['taskDirectory'], '--units', *entry['unknownUnits']]
    return entries
