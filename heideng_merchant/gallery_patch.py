"""Merchant pilot and URL-map workflows using shared POP gallery receipts."""
from functools import partial
import shutil
from pathlib import Path
from .safety import atomic_json, read_json, file_sha
from .sku_image_edit import gallery_write_directory as location, product_image_lock, require_no_pending_sku_edit
from .pop_gallery import (
    PUBLIC_GROUP, snapshot, gallery_owners, pilot_group, patch_body,
    gallery_readback, checked_result, require_available_draft, check_old_body,
    verify_receipt_store, prior_result, submit, frozen_patch,
)


frozen_patch = partial(frozen_patch, before_dispatch=require_no_pending_sku_edit)


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
