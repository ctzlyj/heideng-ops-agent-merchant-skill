"""Compose a merchant's supplied artwork on one image without a platform write."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

from .safety import SafetyError, atomic_json, file_sha, read_json, safe_join
from .sample_comparison import download_image, jd_image_url
from .state import FileLock


def _recipe_id(recipe):
    return sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def verify_pilot_preview(path, identity, product_id, sku_id, old_url):
    """Bind a managed preview to its original SKU before sending it to the media space."""
    path = Path(path).absolute()
    if path.parent.parent.name != 'overlay-previews':
        return  # An independently supplied merchant file uses the pilot's regular checks.
    receipt = read_json(safe_join(path.parent, 'receipt.json'), {})
    recipe = {k: receipt.get(k) for k in ('version', 'target', 'source', 'layers', 'compareBox')}
    if (path.name != 'preview.png' or receipt.get('status') != 'local-preview' or
            _recipe_id(recipe) != path.parent.name or receipt.get('recipeId') != path.parent.name or
            file_sha(safe_join(path.parent, path.name)) != receipt.get('previewSha256')):
        raise ValueError('请选择原样图回执中的 preview.png；先核对原件与内容哈希')
    target = receipt.get('target') or {}
    expected = {'shopId': identity.get('shopId'), 'venderId': identity.get('venderId'),
                'productId': product_id, 'skuId': sku_id}
    if any(target.get(k) != str(value) for k, value in expected.items()):
        raise ValueError('样图回执中的店铺、商品或 SKU 与本次试发不一致')
    if target.get('galleryUrl') and (jd_image_url(old_url).split('/jfs/', 1)[1] !=
                                     jd_image_url(target['galleryUrl']).split('/jfs/', 1)[1]):
        raise ValueError('该规格的当前首图与制作样图时记录的图源不一致')


def _local_bytes(root, name):
    path = safe_join(root, name)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('单张素材超过本地样图读取上限')
    return path.read_bytes()


def _decode(raw):
    with Image.open(BytesIO(raw)) as image:
        if image.width * image.height > 24_000_000 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('请提供单帧且不超过 2400 万像素的图片')
        if image.mode not in ('RGB', 'RGBA', 'P', 'L', 'LA'):
            raise ValueError('请先按原色彩配置导出 RGB 底图或贴图')
        return ImageOps.exif_transpose(image).convert('RGBA')


def _box(values, size):
    if not isinstance(values, list) or len(values) != 4 or any(type(v) is not int for v in values):
        raise ValueError('裁切或位置需要四个整数像素坐标')
    x0, y0, x1, y1 = values
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise ValueError('图层或比较区域超出原图')
    return x0, y0, x1, y1


def preview(plan_path, *, fetch=None):
    plan_path = Path(plan_path).resolve()
    root = plan_path.parent
    plan = read_json(plan_path)
    if not isinstance(plan, dict) or not isinstance(plan.get('source'), dict):
        raise ValueError('缺少样图计划或底图来源')
    target = plan.get('target', {})
    fields = ('shopId', 'venderId', 'productId', 'skuId')
    if not isinstance(target, dict) or any(not isinstance(target.get(k), str) or
            not target[k].isascii() or not target[k].isdecimal() for k in fields):
        raise ValueError('请填入本次已核验的店铺、商品和目标 SKU 编号')
    source = plan['source']
    if bool(source.get('file')) == bool(source.get('url')):
        raise ValueError('每次样图需要指明一个本地底稿或真实图片链接')
    if source.get('url'):
        locator = jd_image_url(source['url'])
        gallery_url = jd_image_url(target.get('galleryUrl'))
        if locator.split('/jfs/', 1)[1] != gallery_url.split('/jfs/', 1)[1]:
            raise ValueError('图片空间链接和该规格编辑前首图的资源标识不同，请核对原素材')
        raw = (fetch or download_image)(locator)
    else:
        locator = source['file']
        raw = _local_bytes(root, locator)
    source_hash = sha256(raw).hexdigest()
    if source.get('sha256') and source_hash != source['sha256']:
        raise ValueError('底图内容与原回执不同，请核对历史原件')
    original = _decode(raw)
    canvas = original.copy()
    layers = plan.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 24:
        raise ValueError('请提供 1 至 24 个按叠放顺序排列的图层')
    layer_evidence = []
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError('图层需要文件与放置区域')
        art = _local_bytes(root, layer.get('file'))
        item = _decode(art)
        if 'crop' in layer:
            item = item.crop(_box(layer['crop'], item.size))
        mirror = layer.get('mirror', False)
        if not isinstance(mirror, bool):
            raise ValueError('请用布尔值指定是否镜像该层')
        if mirror:
            item = ImageOps.mirror(item)
        x0, y0, x1, y1 = _box(layer.get('box'), canvas.size)
        item = ImageOps.contain(item, (x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        x, y = x0 + (x1 - x0 - item.width) // 2, y0 + (y1 - y0 - item.height) // 2
        canvas.alpha_composite(item, (x, y))
        layer_evidence.append({'sha256': sha256(art).hexdigest(), 'file': layer['file'],
                               'crop': layer.get('crop'), 'mirror': mirror,
                               'placedBox': [x, y, x + item.width, y + item.height]})

    region = _box(plan['compareBox'], canvas.size) if 'compareBox' in plan else None
    scope = {k: target[k] for k in fields}
    if target.get('galleryUrl'):
        scope['galleryUrl'] = jd_image_url(target['galleryUrl'])
    recipe = {'version': 1, 'target': scope,
              'source': {'location': locator, 'sha256': source_hash, 'bytes': len(raw),
                         'pixelSize': list(original.size)}, 'layers': layer_evidence,
              'compareBox': list(region) if region else None}
    key = _recipe_id(recipe)
    parent = safe_join(root, 'overlay-previews')
    parent.mkdir(exist_ok=True)
    dest = safe_join(parent, key)
    with FileLock(parent / (key + '.lock')):
        if dest.exists():
            receipt = read_json(safe_join(dest, 'receipt.json'), {})
            if (receipt.get('recipeId') != key or any(receipt.get(k) != v for k, v in recipe.items()) or
                    file_sha(safe_join(dest, 'source.img')) != source_hash or
                    file_sha(safe_join(dest, 'preview.png')) != receipt.get('previewSha256') or
                    (region and file_sha(safe_join(dest, 'compare.png')) != receipt.get('comparisonSha256'))):
                raise SafetyError('原样图或来源回执已改变，请核对原任务')
        else:
            with TemporaryDirectory(dir=parent) as scratch:
                stage = Path(scratch) / 'result'
                stage.mkdir()
                (stage / 'source.img').write_bytes(raw)
                canvas.save(stage / 'preview.png')
                receipt = {**recipe, 'recipeId': key, 'status': 'local-preview', 'sourceFile': 'source.img',
                           'previewSha256': file_sha(stage / 'preview.png'), 'platformWrites': 0, 'paidRequests': 0}
                if region:
                    before, after = original.crop(region), canvas.crop(region)
                    comparison = Image.new('RGBA', (before.width * 2, before.height))
                    comparison.paste(before, (0, 0))
                    comparison.paste(after, (before.width, 0))
                    comparison.save(stage / 'compare.png')
                    receipt['comparisonSha256'] = file_sha(stage / 'compare.png')
                atomic_json(stage / 'receipt.json', receipt)
                stage.rename(dest)
    result = {**receipt, 'previewPath': str(dest / 'preview.png'), 'receiptPath': str(dest / 'receipt.json')}
    if region:
        result['comparisonPath'] = str(dest / 'compare.png')
    return result
