"""Keep before/after image evidence separate from the product being copied."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import re
from urllib.parse import urlsplit

from .safety import SafetyError, atomic_json, file_sha, read_json, safe_join


def checked_image(root, relative, digest):
    if not isinstance(relative, str) or not digest:
        return None
    path = safe_join(root, relative.replace('\\', '/'))
    return path if path.is_file() and file_sha(path) == digest else None


def read_comparison(sample_dir, *, sample_sha, target_sku_id=None, target_product_id=None,
                    source_sku_id=None, source_product_id=None):
    """Only expose files when both pixels and their identities still match the review."""
    unavailable = {'kind':'unknown', 'status':'unverified', 'label':'对比图来源待核'}
    try:
        record = _verified_comparison(Path(sample_dir), sample_sha, target_sku_id, target_product_id,
                                      source_sku_id, source_product_id)
    except (SafetyError,OSError,ValueError,TypeError):
        record = None
    return record or unavailable


def _verified_comparison(sample_dir, sample_sha, target_sku_id, target_product_id, source_sku_id, source_product_id):
    if not re.fullmatch('[0-9a-f]{64}', str(sample_sha)):
        return None
    path = safe_join(sample_dir, f'.comparison/{sample_sha}.json')
    record = read_json(path, {})
    if not isinstance(record, dict) or record.get('sampleSha256') != sample_sha:
        return None
    pid, sid = record.get('productId'), record.get('skuId')
    kind = record.get('kind')
    if kind == 'target-sku':
        if not target_sku_id or str(target_sku_id) != sid or str(target_product_id) != pid:
            return None
    elif kind in ('source-sku', 'source-product'):
        if source_product_id is not None and str(source_product_id) != pid:
            return None
        if kind == 'source-sku' and (not source_sku_id or str(source_sku_id) != sid):
            return None
        if kind == 'source-product' and (not source_product_id or sid is not None):
            return None
    elif kind != 'merchant-provided' or sid is not None or pid is not None:
        return None
    before = checked_image(sample_dir,record.get('beforeFile'),record.get('beforeSha256'))
    sheet = checked_image(sample_dir,record.get('comparisonFile'),record.get('comparisonSha256'))
    if not before or not sheet:
        return None
    return {**record, 'status':'verified', 'beforePath':str(before), 'comparisonPath':str(sheet),
            'receipt':str(path), 'skuUrl':f'https://item.jd.com/{sid}.html' if sid and sid.isdecimal() else None}


def jd_image_url(value):
    value = str(value or '')
    if value.startswith('jfs/'):
        value = 'https://img10.360buyimg.com/imgzone/' + value
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not (parts.hostname or '').endswith('.360buyimg.com') or
            parts.username or parts.password or parts.port not in (None,443) or
            parts.query or parts.fragment or not re.fullmatch(r'/[\w/.-]+', parts.path) or
            '..' in parts.path.split('/') or '/jfs/' not in parts.path):
        raise ValueError('规格图地址未能核实为京东图片空间原文件')
    return value


def download_image(url):
    import requests
    from PIL import Image
    with requests.get(jd_image_url(url), stream=True, allow_redirects=False, timeout=(4,8)) as response:
        if response.status_code != 200:
            raise ValueError('京东图片读取失败')
        raw = BytesIO()
        for chunk in response.iter_content(65536):
            raw.write(chunk)
            if raw.tell() > 12*1024*1024:
                raise ValueError('原图超过单张读取范围')
    raw.seek(0)
    with Image.open(raw) as image:
        image.verify()
    return raw.getvalue()


def original_image_url(value):
    """Use the uploaded JD image when a gallery supplies a display rendition."""
    url = jd_image_url(value)
    parsed = urlsplit(url)
    if re.match(r'^/n\d+/',parsed.path):
        return f'https://{parsed.hostname}/imgzone/jfs/'+parsed.path.split('/jfs/',1)[1]
    return url


def before_for_sku(sample_dir, detail, target, *, existing=None, readback_source, fetch=None):
    """Capture exact live pixels, or match an old CDN rendition byte-for-byte."""
    from .sku_image_edit import pictures
    sample_dir = Path(sample_dir)
    sid, pid = str(target['skuId']), str(target['productId'])
    if not sid.isdecimal() or not pid.isdecimal():
        raise ValueError('缺少已核实的目标 SKU 或 SPU')
    url = original_image_url(pictures(detail,pid).get(sid))
    urls = [url]
    if existing:
        # Older WorkBuddy jobs saved the n1 thumbnail rather than the full uploaded JPEG.
        urls = list(dict.fromkeys(['https://img14.360buyimg.com/n1/jfs/'+url.split('/jfs/',1)[1],url]))
    fetch = fetch or download_image
    last_error = None
    for rendition in urls:
        try:
            raw = fetch(rendition)
        except (OSError, ValueError) as error:
            last_error = error
            continue
        digest = sha256(raw).hexdigest()
        if existing and digest not in existing:
            continue
        path = safe_join(sample_dir, f'.comparison/before-{digest}.img')
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        record = {'kind':'target-sku','label':'目标商品该规格的原图', 'productId':pid, 'skuId':sid,
                  'imageUrl':rendition, 'readbackSource':readback_source,
                  'beforeFile':path.relative_to(sample_dir).as_posix(), 'beforeSha256':digest}
        atomic_json(safe_join(sample_dir,'.comparison/before.json'), record)
        return record
    raise ValueError('历史原图未与目标 SKU 的图片字节匹配') from last_error


def write_comparison(sample_dir, sample_path, before):
    from PIL import Image, ImageOps
    sample_dir = Path(sample_dir)
    original = checked_image(sample_dir,before.get('beforeFile'),before.get('beforeSha256'))
    if not original:
        raise ValueError('原图与来源回执不一致')
    digest = file_sha(sample_path)
    sheet = Image.new('RGB', (1024,512), 'white')
    for i, path in enumerate((original,sample_path)):
        with Image.open(path) as image:
            panel = ImageOps.contain(ImageOps.exif_transpose(image).convert('RGB'), (512,512))
            sheet.paste(panel, (i*512+(512-panel.width)//2,(512-panel.height)//2))
    image_path = safe_join(sample_dir,f'.comparison/{digest}-{before["beforeSha256"]}.jpg')
    image_path.parent.mkdir(exist_ok=True)
    sheet.save(image_path,quality=92)
    record = {**before,'sampleSha256':digest,'comparisonFile':image_path.relative_to(sample_dir).as_posix(),
              'comparisonSha256':file_sha(image_path)}
    pointer = safe_join(sample_dir,f'.comparison/{digest}.json')
    previous = read_json(pointer,{})
    if previous and previous != record:
        prior_id = sha256(json.dumps(previous,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        atomic_json(safe_join(sample_dir,f'.comparison/history/{prior_id}.json'),previous)
    atomic_json(pointer,record)
    return {'original':str(original),'comparison':str(image_path),'layout':'左为'+before['label']+'，右为本次样张',
            'comparisonOrigin':{k:v for k,v in record.items() if k not in ('beforeFile','comparisonFile')}}
