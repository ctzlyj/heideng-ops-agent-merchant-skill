"""Publish a reviewed main image to the authorized gallery slots and reconcile its receipt."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from uuid import uuid4

from .safety import atomic_json, file_sha, read_json
from .sku_image_edit import gallery_write_directory as location, product_image_lock, require_no_pending_sku_edit


PUBLIC_GROUP = '0000000000'


def snapshot(detail, pid):
    product = detail.get('productInfo') or {}
    if str(product.get('productId')) != str(pid):
        raise ValueError('商品编辑详情与目标 SPU 不一致')
    groups = {}
    for group in (detail.get('material') or {}).get('mainImages') or []:
        gid = str(group.get('uuid') or '')
        images = sorted(group.get('imageInfoList') or [], key=lambda row: int(row.get('orderSort') or 0))
        orders = [int(row.get('orderSort') or 0) for row in images]
        urls = [row.get('imgUrl') for row in images]
        if not gid or gid in groups or orders != list(range(1, len(images) + 1)) or not all(urls):
            raise ValueError('图组身份、原图或图位顺序不完整')
        groups[gid] = urls
    skus = {}
    for row in detail.get('skuList') or []:
        sid = str(row.get('skuId') or '')
        if not sid.isdecimal() or sid in skus or str(row.get('productId', pid)) != str(pid):
            raise ValueError('SKU 身份缺失、重复或与商品不符')
        skus[sid] = {'price': (row.get('priceInfo') or {}).get('jdPrice'),
                     'uuid': str(row.get('uuid') or ''), 'attributes': row.get('saleAttrs') or []}
    if not groups or not skus:
        raise ValueError('缺少完整的图组与 SKU 清单')
    return {'groups': groups, 'skus': skus, 'categoryId': product['categoryDetail']['lastCategoryId']}


def gallery_owners(state):
    groups, rows = state['groups'], state['skus']
    owners = {}
    for sid, row in rows.items():
        attrs = row['attributes']
        first = [attr for attr in attrs if str(attr.get('dim')) == '1'
                 or (len(attrs) == 1 and attr.get('dim') in ('', None))]
        # The apply-detail gallery binds a direct SKU ID or the first sale dimension's
        # attrValues. SKU uuid addresses specification images, and mappingId belongs
        # to the edit schema. Neither alone identifies a gallery in this response.
        evidence = {sid}
        for attr in first:
            evidence.add(str(attr.get('attrValues') or ''))
        candidates = (evidence & set(groups)) - {PUBLIC_GROUP}
        if not candidates and set(groups) == {PUBLIC_GROUP}:
            candidates = {PUBLIC_GROUP}
        if len(candidates) != 1:
            raise ValueError(f'SKU {sid} 的主图归属未能唯一核验，请查同商品编辑回执')
        owners[sid] = candidates.pop()
    return owners


def pilot_group(state, sku):
    if sku not in state['skus']:
        raise ValueError('试发 SKU 不属于本店此商品')
    owners = gallery_owners(state)
    gid = owners[sku]
    affected = sorted(sid for sid in owners if owners[sid] == gid)
    if affected != [sku]:
        raise ValueError('该图组会同时影响其他规格，单 SKU 试发需要独立图组。共用 SKU：' + ', '.join(affected))
    if not state['groups'][gid]:
        raise ValueError('目标图组缺少当前首图')
    return gid


def patch_body(pid, state, changes):
    """PATCH consumes images in sequence. Send only the required prefix of affected groups."""
    expected = deepcopy(state)
    operations = []
    count = 0
    for gid, positions in changes.items():
        gallery = expected['groups'][gid]
        for position, (old, new) in positions.items():
            if not 1 <= position <= min(len(gallery), 9) or gallery[position - 1] != old or not new:
                raise ValueError('目标图位或原图已变化，请重新核对本次范围')
            gallery[position - 1] = new
            count += 1
        values = []
        for position, url in enumerate(gallery[:max(positions)], 1):
            values.append({'componentCode': 'img', 'inputType': 'multiText', 'properties': [
                {'key': 'colorId', 'value': gid}, {'key': 'imgUrl', 'value': url},
                {'key': 'imgRefId', 'value': gid}, {'key': 'orderSort', 'value': str(position)}]})
        component = {'componentCode': 'WareSkuImg', 'inputType': 'multiText', 'value': values}
        operations.append({'path': 'product', 'value': json.dumps(component, ensure_ascii=False, separators=(',', ':'))})
    if not count:
        raise ValueError('没有匹配到本次要更换的图位')
    body = {'applyId': str(pid), 'opType': 3, 'scene': 'pop',
            'productInfo': {'productId': pid, 'categoryDetail': {'lastCategoryId': int(state['categoryId'])}},
            'productApplyDTO': {'id': str(pid)}, 'patchOperationList': operations}
    return body, expected


def gallery_readback(expected, actual):
    """Compare the persisted slot/SKU contract and explain exactly what differed."""
    differences = {}

    def note(field, identity):
        entry = differences.setdefault(field, {'count': 0, 'examples': []})
        entry['count'] += 1
        if len(entry['examples']) < 5:
            entry['examples'].append(identity)

    if expected['categoryId'] != actual['categoryId']:
        note('categoryId', 'product')
    for gid in sorted(expected['groups'].keys() | actual['groups'].keys()):
        if gid not in expected['groups'] or gid not in actual['groups']:
            note('galleryGroup', gid)
            continue
        old, new = expected['groups'][gid], actual['groups'][gid]
        for pos in range(max(len(old), len(new))):
            if pos >= len(old) or pos >= len(new) or old[pos] != new[pos]:
                note('gallerySlot', f'{gid}/{pos + 1}')

    omitted = set()
    for sid in sorted(expected['skus'].keys() | actual['skus'].keys()):
        if sid not in expected['skus'] or sid not in actual['skus']:
            note('skuId', sid)
            continue
        old, new = expected['skus'][sid], actual['skus'][sid]
        for field in ('price', 'uuid'):
            if old[field] != new[field]:
                note(field, sid)
        if old['attributes'] == new['attributes']:
            continue
        if len(old['attributes']) != len(new['attributes']):
            note('saleAttrs', sid)
            continue
        for original, current in zip(old['attributes'], new['attributes']):
            for field in original.keys() | current.keys():
                if field == 'mappingId':
                    if original.get(field) == current.get(field):
                        continue
                    if current.get(field) in (None, ''):
                        omitted.add(sid)
                        continue
                elif field in original and field in current and original[field] == current[field]:
                    continue
                note('saleAttrs.' + field, sid)

    # In an edit-detail read the platform can omit the former edit-schema mappingId.
    # Accept that omission only when the actual gallery owner is independently proven.
    if omitted:
        try:
            before_owners = gallery_owners(expected)
            after_owners = gallery_owners(actual)
        except ValueError:
            before_owners, after_owners = {}, {}
        for sid in sorted(omitted):
            if not before_owners.get(sid) or before_owners[sid] != after_owners.get(sid):
                note('saleAttrs.mappingId/owner-unverified', sid)
    return {
        'fieldDifferences': differences,
        'mappingIdOmittedSkuCount': len(omitted),
        'problems': [f"{field} 差异 {entry['count']} 处（{', '.join(entry['examples'])}）"
                     for field, entry in differences.items()],
    }


def checked_result(record, state, *, recovered=False):
    evidence = gallery_readback(record['expected'], state)
    matches = not evidence['problems']
    return {**record['summary'], 'ok': matches,
            'status': 'verified-in-edit-detail' if matches else 'awaiting-readback',
            **evidence,
            'consumerPageStatus': 'unchecked', 'reconciled': recovered,
            'checkedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'receipt': record['directory']}


def require_available_draft(detail):
    if str((detail.get('applyInfo') or {}).get('draftComputeStatus')) == '1':
        raise ValueError('本商品已有在审申请，请先回查原申请，尚未发起新写入')


def check_old_body(path, state, pid):
    """Earlier versions persisted the PATCH body before dispatch, without a status."""
    if not path.exists():
        return
    body = read_json(path)
    try:
        same_product = str(body.get('applyId')) == str(pid) and int(body['opType']) == 3
        entries = [json.loads(op['value'])['value'] for op in body['patchOperationList']]
        if not same_product or not entries or not all(entries):
            raise ValueError()
        for images in entries:
            for item in images:
                props = {p['key']: p['value'] for p in item['properties']}
                pos = int(props['orderSort'])
                if pos < 1 or state['groups'][props['colorId']][pos - 1] != props['imgUrl']:
                    raise ValueError()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise ValueError('旧主图提交体尚未与当前编辑详情对上，请先核验这次原提交：' + str(path)) from None


def verify_receipt_store(record, identity):
    if record:
        store = record.get('shopIdentity') or {}
        if (any(str(store.get(k) or '') != str(identity.get(k) or '') for k in ('profile', 'shopName', 'venderId'))
                or (store.get('shopId') and str(store['shopId']) != str(identity.get('shopId') or ''))):
            raise ValueError('原图文回执属于其他店铺或 Profile，请用原任务身份核验')


def prior_result(root, current, state, request, reconcile):
    if not current:
        if reconcile:
            raise ValueError('此商品没有可回查的主图提交回执')
        return None
    same = request == current['request']
    if current['status'] == 'rejected':
        if same or reconcile:
            return {**current['summary'], 'status': 'rejected', 'ok': False, 'replayed': False,
                    'platformCode': current['platformCode'], 'receipt': current['directory']}
        return None
    if not reconcile and current['status'] == 'verified' and not same:
        return None
    result = checked_result(current, state, recovered=True)
    if result['ok']:
        atomic_json(root / 'current.json', {**current, 'status': 'verified'})
        atomic_json(Path(current['directory']) / 'readback.json', result)
    if not same and not reconcile:
        # A different request met an earlier unknown write. Do not report that new request as applied.
        result.update(ok=False, originalStatus=result['status'], status='prior-edit-recovered' if result['ok'] else 'prior-edit-pending',
                      newRequestApplied=False)
    return result


def submit(cli, read_detail, root, pid, state, changes, summary, request, identity, body_dir=None):
    body, expected = patch_body(pid, state, changes)
    directory = root / 'attempts' / uuid4().hex
    body_path = directory / ('request.json' if body_dir is not None else f'patch_{pid}.json')
    atomic_json(body_path, body)
    if body_dir is not None:
        atomic_json(Path(body_dir) / f'patch_{pid}.json', body)
    summary = {'productId': pid, 'changedSlots': sum(len(slots) for slots in changes.values()), **summary}
    record = {'status': 'submitting', 'request': request, 'summary': summary, 'before': state, 'expected': expected, 'shopIdentity': identity,
              'directory': str(directory)}
    atomic_json(directory / 'intent.json', record)
    atomic_json(root / 'current.json', record)
    try:
        response = cli.run_jdo_large(url='/rest/sp-product/v0/product-applies/{applyId}', method='PATCH', body_path=body_path,
                                     params={'applyId': str(pid)}, skill_id='jdo-product-update', yes=True)
    except Exception as exc:
        code = str(exc).split(maxsplit=1)[0] if str(exc) else ''
        if isinstance(exc, getattr(cli, 'JdoError', ())) and code.isdecimal() and len(code) >= 6:
            rejected = {**record, 'status': 'rejected', 'platformCode': code}
            atomic_json(directory / 'rejection.json', rejected)
            atomic_json(root / 'current.json', rejected)
        raise
    atomic_json(directory / 'response.json', response)
    if request['mode'] == 'url-map':
        record['summary'] = {**summary, 'submit': response.get('data')}
    result = checked_result(record, snapshot(read_detail(pid), pid))
    atomic_json(directory / 'readback.json', result)
    atomic_json(root / 'current.json', {**record, 'status': 'verified' if result['ok'] else 'submitted'})
    return result


def upload_once(cli, root, image, digest, identity):
    from PIL import Image
    from .sku_image_edit import media_space
    path = root / 'uploads' / (digest + '.json')
    receipt = read_json(path, {})
    if receipt:
        verify_receipt_store(receipt, identity)
        if not receipt.get('url'):
            raise ValueError('原素材上传结果未知，请先核对本店图片空间。回执：' + str(path))
        return receipt['url']
    staged = path.with_suffix(image.suffix.lower())
    if staged == path:
        raise ValueError('输入应为可解码的本地成图')
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, staged)
    if file_sha(staged) != digest:
        raise ValueError('待上传图片在取样后发生了变化')
    with Image.open(staged) as source:
        source.verify()
    zone, category = media_space(cli)
    atomic_json(path, {'status': 'uploading', 'sha256': digest, 'shopIdentity': identity})
    response = cli.upload(zone, category, staged)
    url = response.get('imgUrl')
    if not url:
        raise ValueError('本店图片空间未返回明确的素材地址，保留原上传回执')
    atomic_json(path, {'status': 'accepted', 'sha256': digest, 'url': url, 'shopIdentity': identity})
    return url


def pilot(cli, read_detail, identity, pid, sku, image=None, original=None, *, publish=False, reconcile=False):
    root = location(cli, identity, pid)
    with product_image_lock(root, identity, pid):
        detail = read_detail(pid)
        state = snapshot(detail, pid)
        current = read_json(root / 'current.json')
        digest = file_sha(image) if publish and image is not None else None
        request = {'mode': 'single-sku-first-image', 'skuId': sku, 'sha256': digest, 'oldUrl': original}
        if publish or reconcile:
            verify_receipt_store(current, identity)
            if reconcile and current:
                prior = current['request']
                if prior.get('mode') != request['mode'] or prior.get('skuId') != sku:
                    return {'status': 'different-original-edit', 'ok': False, 'productId': pid, 'skuId': sku,
                            'originalMode': prior.get('mode'), 'originalSkuId': prior.get('skuId'),
                            'newRequestApplied': False, 'writes': 0}
            previous = prior_result(root, current, state, request, reconcile)
            if previous is not None:
                return previous
        group = pilot_group(state, sku)
        source = state['groups'][group][0]
        summary = {'skuId': sku, 'affectedSkuIds': [sku], 'galleryGroup': group, 'position': 1, 'oldUrl': source,
                   'buyerUrl': f'https://item.jd.com/{sku}.html', 'consumerPageStatus': 'unchecked'}
        if not publish:
            return {'ok': True, 'status': 'eligible', 'writes': 0, 'productId': pid, **summary}
        require_no_pending_sku_edit(identity, pid)
        require_available_draft(detail)
        if not digest or original != source:
            raise ValueError('试发需要该 SKU 已核对的成图与制作时的首图地址')
        if not current:
            check_old_body(Path(cli.STATE_ROOT) / 'outputs' / 'image-patches' / f'patch_{pid}.json', state, pid)
        from .overlay_preview import verify_pilot_preview
        verify_pilot_preview(Path(image), identity, pid, sku, original)
        new = upload_once(cli, root, Path(image), digest, identity)
        fresh = read_detail(pid)
        require_available_draft(fresh)
        if snapshot(fresh, pid) != state:
            raise ValueError('上传期间商品或图组发生变化。已保留素材上传回执，尚未绑定')
        return submit(cli, read_detail, root, pid, state, {group: {1: (source, new)}},
                      {**summary, 'newUrl': new, 'replaced': 1}, request, identity)


def mapped_patch(cli, read_detail, identity, pid, mapping, *, allow_shared=False, body_dir=None):
    """Compatibility route for an explicitly approved product-wide URL replacement."""
    root = location(cli, identity, pid)
    with product_image_lock(root, identity, pid):
        detail = read_detail(pid)
        state = snapshot(detail, pid)
        request = {'mode': 'url-map', 'mapping': mapping, 'allMatchingSlots': allow_shared}
        current = read_json(root / 'current.json')
        verify_receipt_store(current, identity)
        previous = prior_result(root, current, state, request, False)
        if previous is not None:
            return previous
        require_no_pending_sku_edit(identity, pid)
        require_available_draft(detail)
        directory = Path(body_dir) if body_dir else Path(cli.STATE_ROOT) / 'outputs' / 'image-patches'
        if not current:
            check_old_body(directory / f'patch_{pid}.json', state, pid)
        changes = {}
        counts = {}
        capped = []
        for gid, urls in state['groups'].items():
            for position, url in enumerate(urls, 1):
                if url in mapping:
                    if position > 9:
                        capped.append({'group': gid, 'position': position})
                        continue
                    changes.setdefault(gid, {})[position] = (url, mapping[url])
                    counts[url] = counts.get(url, 0) + 1
        if not allow_shared and changes:
            if sum(counts.values()) != 1:
                raise ValueError('映射命中多个图位。单 SKU 首图请用 pilot-main-image；整商品替换须明确覆盖所有命中图位')
            group = next(iter(changes))
            if list(gallery_owners(state).values()).count(group) != 1 or (group == PUBLIC_GROUP and len(state['skus']) != 1):
                raise ValueError('该图组的改动会影响多个 SKU 或商品公共展示，请核对实际授权范围')
        unchanged = {url for gid, urls in state['groups'].items() for pos, url in enumerate(urls, 1)
                     if pos not in changes.get(gid, {})}
        summary = {'replaced': len(counts), 'mapping': {url: mapping[url] for url in counts},
                   'groups': len(state['groups']), 'unchangedUrls': sorted(unchanged), 'preservedTailSlots': capped}
        return submit(cli, read_detail, root, pid, state, changes, summary, request, identity, directory)


def frozen_patch(cli, read_detail, identity, pid, frozen_detail, mapping, positions, max_position, body_dir,
                 clean_url, selected_slots=None):
    """Reuse a refresh plan's deduplicated assets only in the originally selected positions."""
    root = location(cli, identity, pid)
    with product_image_lock(root, identity, pid):
        original = snapshot(frozen_detail, pid)
        detail = read_detail(pid)
        live = snapshot(detail, pid)
        changes = {}
        used = set()
        exact = None
        if selected_slots is not None:
            exact = {}
            for slot in selected_slots:
                address = (str(slot['group']), int(slot['position']))
                url = clean_url(slot['url'])
                if address in exact or url not in mapping:
                    raise ValueError('批准图位重复或缺少对应的原图上传回执')
                exact[address] = url
        for gid, urls in original['groups'].items():
            for pos, old in enumerate(urls, 1):
                key = clean_url(old)
                if exact is not None and exact.get((gid, pos)) != key:
                    continue
                if pos <= min(max_position, 9) and (not positions or pos in positions) and key in mapping:
                    changes.setdefault(gid, {})[pos] = (old, mapping[key])
                    used.add(key)
        count = sum(len(slots) for slots in changes.values())
        if used != set(mapping) or (exact is not None and count != len(exact)):
            raise ValueError('上传回执与冻结图位、原图地址无法一一对应')
        _, expected = patch_body(pid, original, changes)
        request = {'mode': 'refresh', 'mapping': mapping, 'run': str(Path(body_dir).resolve()),
                   'positions': sorted(positions), 'maxPosition': max_position}
        if exact is not None:
            request['selectedSlots'] = [[gid, pos, url] for (gid, pos), url in sorted(exact.items())]
        current = read_json(root / 'current.json')
        verify_receipt_store(current, identity)
        previous = prior_result(root, current, live, request, False)
        if previous is not None and previous.get('status') != 'prior-edit-recovered':
            return previous
        evidence = gallery_readback(expected, live)
        if not evidence['problems']:
            return {'productId': pid, 'ok': True, 'status': 'verified-in-edit-detail', 'reconciled': True,
                    'consumerPageStatus': 'unchecked', 'replaced': len(used), 'changedSlots': count, **evidence}
        legacy = Path(body_dir) / f'patch_{pid}.json'
        if legacy.exists() and (not current or current['request'] != request):
            raise ValueError('原刷新任务留有提交体，当前图组与原计划尚未完全对上，请先对账：' + str(legacy))
        require_no_pending_sku_edit(identity, pid)
        require_available_draft(detail)
        baseline = gallery_readback(original, live)
        if baseline['problems']:
            return {'productId': pid, 'status': 'frozen-state-changed', 'ok': False, 'writes': 0,
                    'consumerPageStatus': 'unchecked', **baseline}
        return submit(cli, read_detail, root, pid, live, changes, {'replaced': len(used)}, request, identity, body_dir)
