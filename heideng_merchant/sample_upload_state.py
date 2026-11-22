"""Summarize durable evidence for exact accepted image bytes without contacting the shop."""
from pathlib import Path
import re

from .commercial_tasks import _matches
from .safety import SafetyError, read_json, safe_join
from .sku_image_edit import pictures


def _status(code, message, path=None, checked=None):
    result = {'status':code, 'message':message, 'consumerPageStatus':'unchecked'}
    if path is not None:
        result['receipt'] = str(path)
        result['receiptRecordedAt'] = int(path.stat().st_mtime)
    if checked:
        result['checkedAt'] = checked
    return result


def sample_upload_state(state, shop_id, vender_id, product_id, sku_id, image_sha256, *, package=None):
    """Use only matching shop, product, SKU, asset hash and the last official readback.

    No receipt means no recorded upload. A saved successful readback describes its own
    timestamp, never the current storefront.
    """
    identity = (str(shop_id or ''), str(vender_id or ''), str(product_id or ''), str(sku_id or ''))
    shop, vendor, pid, sid = identity
    if not shop.isdecimal() or not vendor.isdecimal() or not re.fullmatch('[0-9a-f]{64}', str(image_sha256)):
        return _status('unresolved', '缺少可核验的店铺或样图指纹，上传状态待核。')
    if (pid and not pid.isdecimal()) or (sid and not sid.isdecimal()):
        return _status('unresolved', '商品或规格身份待核。')
    try:
        state = Path(state)
        profiles = read_json(safe_join(state, 'linker/shops.json'), {}).get('profiles', {})
        return _lookup(state, shop, vendor, pid, sid, image_sha256, package, profiles)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SafetyError):
        return _status('unresolved', '原回执不完整或无法读取，上传及线上状态待核。')


def _lookup(state, shop, vendor, pid, sid, sha, package, profiles):
    evidence = _status('no-recorded-upload', '已接受原样图；未找到这张图的上传回执。')
    urls = set()
    if package is not None:
        parent = Path(package)
        manifest = read_json(safe_join(parent, 'manifest.json'), {})
        published = read_json(safe_join(parent, 'state.json'), {})
        stored_pid = str(manifest.get('productId') or published.get('productId') or '')
        if _matches(manifest.get('store', {}), shop, vendor, profiles) and stored_pid == pid:
            upload_path = safe_join(parent, '.publish/uploads.json')
            record = read_json(upload_path, {}).get(sha, {})
            if record.get('sha256') == sha:
                if record.get('status') == 'SUCCEEDED' and record.get('imgUrl'):
                    urls.add(record['imgUrl'])
                    evidence = _status('uploaded', '同一文件已上传至图片空间，规格绑定待核。', upload_path)
                elif record.get('status') in ('UNKNOWN','SUBMITTING'):
                    evidence = _status('upload-unknown', '原图片空间上传结果未知，先核对原请求。', upload_path)
            if urls and pid and sid and str(published.get('productId')) == pid and published.get('status') == 'SUCCEEDED':
                path = safe_join(parent, '.publish/readback-product.json')
                detail = read_json(path, {})
                if detail and pictures(detail, pid).get(sid) in urls:
                    evidence = _status('verified-as-of', '发布后的后台回读已核验该 SKU 使用这张图。', path,
                                       read_json(safe_join(parent,'.publish/verification.json'), {}).get('at'))
    if not pid:
        return evidence
    directory = safe_join(state, f'work/sku-image-edits/{vendor}/{pid}')
    upload_path = safe_join(directory, f'uploads/{sha}.json')
    upload = read_json(upload_path, {})
    owners = {str(p.get('shopId') or '') for p in profiles.values() if str(p.get('venderId')) == vendor}
    def owned(record):
        store = record.get('shopIdentity')
        return _matches(store, shop, vendor, profiles) if store else owners == {shop}
    if upload.get('sha256') == sha and str(upload.get('productId',pid)) == pid and owned(upload):
        if upload.get('status') == 'accepted' and upload.get('url'):
            urls.add(upload['url'])
            if evidence['status'] != 'verified-as-of':
                evidence = _status('uploaded', '同一文件已上传至图片空间，规格绑定待核。', upload_path)
        elif upload.get('status') == 'uploading' and not urls:
            evidence = _status('upload-unknown', '已记录上传意图，原上传结果待核。', upload_path)
    current_path = safe_join(directory, 'current.json')
    current = read_json(current_path, {})
    if not sid or str(current.get('productId')) != pid or not owned(current):
        return evidence
    target_url = (current.get('expected') or {}).get(sid)
    linked = (current.get('inputs') or {}).get(sid) == sha
    readback = current.get('readback') or {}
    status = current.get('status')
    if (status == 'verified' and readback.get('status') == 'verified' and str(readback.get('productId')) == pid
            and readback.get('skuMatches', {}).get(sid) is True and readback.get('otherFieldsMatch') is True):
        if target_url and target_url in urls:
            return _status('verified-as-of', '后台最近一次回读已核验该 SKU 使用这张图。', current_path, readback.get('checkedAt'))
        if target_url and urls and not linked:
            return _status('other-image-as-of', '同一文件已有上传回执，最近回读的该规格使用另一张图。', current_path, readback.get('checkedAt'))
    if linked:
        if status == 'submitting':
            return _status('edit-unknown', '原规格图编辑结果未知，先对账。', current_path)
        if status in ('submitted','awaiting-readback'):
            return _status('submitted', '该 SKU 的规格图已提交，线上回读待核。', current_path)
        if status == 'rejected':
            return _status('edit-rejected', '该 SKU 的规格图编辑被平台拒绝。', current_path)
        return _status('unresolved', '规格编辑与图片空间回执未能核对，线上状态待核。', current_path)
    if evidence['status'] == 'verified-as-of' and status in ('submitting','submitted','awaiting-readback') and target_url not in urls:
        return _status('later-edit-pending', '有历史生效回读，后续换图的结果仍待核。', current_path)
    return evidence
