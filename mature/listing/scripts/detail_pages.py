"""Detail-page planning, quality gate, PC/mobile readback and WareEditor-only repair body.

Every route that creates a new product must pass `check_detail_set` (photo route) or
`listing_detail_errors` (generic listing.json routes) before anything is uploaded or published.
Reference/competitor images are never uploadable: they are style analysis only.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

MIN_MODULES = 1
DEFAULT_MAX_MODULES = 8
SKUS_PER_MODULE = 4
OUTPUT_WIDTH = 790
ALLOWED_WIDTHS = (750, 790)
MODULE_SIZE = '1024x1536'
REQUIRED_KINDS = ('hero', 'selling_points', 'sku_options', 'scene', 'structure', 'specs_package', 'aftercare')
EXEMPT_POLICIES = ('user-single-image', 'platform-limit')
KIND_TITLES = {
    'hero': '首屏商品价值', 'selling_points': '核心卖点', 'sku_options': '款式/组合选择',
    'scene': '真实使用场景', 'structure': '结构与细节', 'specs_package': '参数与包装',
    'aftercare': '注意事项与售后说明',
}
# a sku_options module also answers the "pattern / colour / style" requirement
KIND_COVERS = {'sku_options': ('sku_options', 'style_variants')}
FORBIDDEN = ('价格、促销、折扣、秒杀、榜单、销量排名、优惠券、来源店铺名、他牌名称与标识、水印、二维码、'
             '未经证实的认证/功效/材质/尺寸/承重、绝对化用语（最好、第一、正品保证等）')
_BANNED = re.compile(r'[¥￥]|\d\s*元|价格|到手价|券后|折扣|立减|秒杀|限时|促销|特价|包邮|爆款|热销|销量|榜单|排行|排名|'
                     r'第一|NO\.?\s*1|最好|最佳|最强|正品保证|旗舰店|专卖店|官方|专利|认证|二维码|水印', re.I)
_IMG_SRC = re.compile(r'<img\b[^>]*?\b(?:src|data-src)\s*=\s*([\'"])(.*?)\1', re.I | re.S)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def banned_hits(text, reference_terms=()):
    hits = [m.group(0) for m in _BANNED.finditer(text or '')]
    hits += [t for t in reference_terms if t and t in (text or '')]
    return list(dict.fromkeys(hits))


def scan_visible_text(lines, facts, reference_terms=()):
    """Planned on-image text must be promo-free, free of reference identity and fact-backed."""
    facts_text = _text(facts)
    problems = []
    for line in lines:
        hits = banned_hits(line, reference_terms)
        if hits:
            problems.append(f'画面文字含禁止内容 {hits[:3]}：{line[:20]}')
        for number in re.findall(r'\d+(?:\.\d+)?', line):
            if number not in facts_text:
                problems.append(f'画面文字含未确认数字 {number}：{line[:20]}')
    return problems


def _chunk_skus(skus):
    if not skus:
        return [[]]
    count = max(1, -(-len(skus) // SKUS_PER_MODULE))
    size = -(-len(skus) // count)
    return [skus[i:i + size] for i in range(0, len(skus), size)]


def normalize_detail_image(source, destination, width=OUTPUT_WIDTH):
    with Image.open(source) as im:
        im = im.convert('RGB')
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        im.save(destination, 'JPEG', quality=92)
    return Path(destination)


def overview_image(paths, destination, thumb=200):
    thumbs = []
    for p in paths:
        with Image.open(p) as im:
            im = im.convert('RGB')
            thumbs.append(im.resize((thumb, round(im.height * thumb / im.width)), Image.Resampling.LANCZOS))
    if not thumbs:
        raise ValueError('No detail images for overview')
    sheet = Image.new('RGB', ((thumb + 8) * len(thumbs) + 8, max(t.height for t in thumbs) + 16), 'white')
    for i, t in enumerate(thumbs):
        sheet.paste(t, (8 + i * (thumb + 8), 8))
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, 'JPEG', quality=85)
    return Path(destination)


def _reference_hashes(root):
    path = Path(root) / '.reference-cache' / 'assets.json'
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('source') == 'merchant-product-apply':
        return set()
    return {e.get('sha256') for e in data.get('entries') or [] if e.get('sha256')}


def exemption(manifest):
    policy = ((manifest.get('facts') or {}).get('detailPolicy')) or {}
    if policy.get('type') in EXEMPT_POLICIES and str(policy.get('reason') or '').strip():
        return {'type': policy['type'], 'reason': str(policy['reason']).strip(),
                'minimum': max(1, int(policy.get('minimum') or 1))}
    return None


def detail_minimum(manifest):
    return (exemption(manifest) or {}).get('minimum', MIN_MODULES)


def detail_coverage_problems(facts, modules):
    """The host records specific buyer questions and where the design answers them."""
    required = facts.get('requiredDetailTopics') or []
    if not isinstance(required, list) or not all(isinstance(v,str) and v.strip() for v in required):
        return ['requiredDetailTopics 需要逐项列出商品待说明的事项']
    covered = set()
    for module in modules:
        topics = module.get('covers', [])
        if not isinstance(topics,list) or not all(isinstance(v,str) for v in topics):
            return ['详情图 covers 需要逐项记录覆盖的事项']
        covered.update(topics)
    return ['详情页还需说明：'+topic for topic in required if topic not in covered]


def check_detail_set(manifest, root, plan=None):
    """Hard pre-publish gate for the photo route. Returns {'ok','problems','modules',...}."""
    from image_quality_gate import duplicate_details
    root = Path(root).resolve()
    problems = []
    items = manifest.get('detailImages') or []
    exempt = exemption(manifest)
    plan = plan if plan is not None else _load_plan(root)
    minimum = detail_minimum(manifest)
    if len(items) < minimum:
        problems.append(f'详情交付需要至少{minimum}张，当前{len(items)}张')
    if plan:
        problems.extend(detail_coverage_problems(manifest.get('facts') or {},plan.get('modules') or []))
    if not exempt:
        if not plan:
            problems.append('缺少 detail-plan.json，请先 make-plan')
        else:
            modules = {m['id']: m for m in plan.get('modules') or []}
            ids = [i.get('id') for i in items]
            if ids != [m['id'] for m in plan.get('modules') or []]:
                problems.append('详情图与 detail-plan 模块不一致或顺序错误')
            if plan.get('schema') != 'host-detail-plan/v1':
                kinds = {c for m in plan.get('modules') or [] for c in m.get('covers') or [m['kind']]}
                for kind in REQUIRED_KINDS:
                    if kind not in kinds:
                        problems.append(f'缺少必需详情模块：{KIND_TITLES[kind]}')
                if 'style_variants' not in kinds:
                    problems.append('缺少图案/颜色/款式模块')
                facts_keys = {s['key'] for s in (manifest.get('facts') or {}).get('skus') or []}
                covered = {k for m in plan.get('modules') or [] if m['kind'] == 'sku_options' for k in m.get('skuKeys') or []}
                if facts_keys - covered:
                    problems.append('详情页未覆盖全部SKU：' + ','.join(sorted(facts_keys - covered)))
                if len(plan.get('modules') or []) > max(DEFAULT_MAX_MODULES, len(REQUIRED_KINDS) + len(_chunk_skus(list(facts_keys)))) + 4:
                    problems.append('详情模块数量异常过多')
            terms = (manifest.get('reference') or {}).get('bannedTerms') or []
            for mod in modules.values():
                problems += scan_visible_text(mod.get('exactVisibleText') or [], manifest.get('facts') or {}, terms)
    reference = _reference_hashes(root)
    seen_paths, existing = [], []
    for item in items:
        rel = str(item.get('localPath') or '')
        target = (root / rel).resolve()
        if root not in target.parents or '.reference-cache' in target.parts:
            problems.append(f'详情图路径不合法或来自参考缓存：{rel}')
            continue
        try:
            with Image.open(target) as im:
                im.load()
                width, height = im.size
        except Exception:
            problems.append(f'详情图不可读：{rel}')
            continue
        if width not in ALLOWED_WIDTHS:
            problems.append(f'详情图宽度必须为750或790：{rel} 当前{width}')
        if not exempt and height <= width:
            problems.append(f'详情图必须为竖版：{rel}')
        digest = _sha(target)
        if digest in reference:
            problems.append(f'详情图与参考链接原图相同，禁止上传：{rel}')
        if item.get('sha256') and item['sha256'] != digest:
            problems.append(f'详情图文件与记录不一致：{rel}')
        existing.append(str(target))
    if len(set(existing)) != len(existing):
        problems.append('详情图重复')
    hashes = [_sha(p) for p in existing]
    if len(set(hashes)) != len(hashes):
        problems.append('详情图内容完全重复')
    elif len(existing) > 1 and duplicate_details(existing, threshold=2):
        problems.append('详情图高度相似疑似重复')
    return {'ok': not problems, 'problems': list(dict.fromkeys(problems)), 'count': len(items),
            'modules': [{'id': i.get('id'), 'kind': i.get('module'), 'file': i.get('localPath'), 'skuKeys': i.get('skuKeys') or []} for i in items],
            'exemption': exempt}


def _load_plan(root):
    path = Path(root) / 'detail-plan.json'
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else None


def listing_detail_errors(images, product):
    """Generic gate for listing.json routes (link move / replica / matrix / templates)."""
    detail = [i for i in images if i.get('role') == 'detail']
    if not images:
        return []
    policy = product.get('detailPolicy')
    if policy in EXEMPT_POLICIES:
        if not str(product.get('detailExemptionReason') or '').strip():return ['详情页例外必须写明 detailExemptionReason']
    if len(detail) < MIN_MODULES:
        return ['缺少可交付的详情图']
    return []


def normalize_url(url):
    url = str(url or '').strip()
    if '/imgzone/' in url:
        return url.split('/imgzone/', 1)[1].split('?', 1)[0].lstrip('/')
    parts = urlsplit(url)
    return (parts.netloc + parts.path) if parts.netloc else url.split('?', 1)[0].lstrip('/')


def extract_image_urls(html):
    return [m.group(2) for m in _IMG_SRC.finditer(html or '')]


def detail_html(urls, mobile=False):
    style = 'max-width:100%;' if mobile else 'max-width:790px;'
    return ''.join(f"<p><img style='{style}' src='{u}'/></p>" for u in urls)


def readback_detail(product_detail_desc, expected_urls):
    """Compare remote PC and mobile detail HTML to the local plan (count + order)."""
    desc = product_detail_desc if isinstance(product_detail_desc, dict) else {}
    want = [normalize_url(u) for u in expected_urls]
    result = {'expectedCount': len(want), 'problems': []}
    for field, label in (('desc', 'pc'), ('mobileDesc', 'mobile')):
        got = [normalize_url(u) for u in extract_image_urls(desc.get(field, ''))]
        result[label + 'Count'] = len(got)
        result[label + 'OrderMatches'] = got == want
        if len(got) != len(want):
            result['problems'].append(f'{label} 详情图数量 {len(got)} != 方案 {len(want)}')
        elif got != want:
            result['problems'].append(f'{label} 详情图URL顺序与本地方案不一致')
    return result


def wareeditor_component(urls, existing=None):
    existing = existing if isinstance(existing, dict) else {}

    def entry(html, flag, agent):
        return {'componentCode': 'detail', 'properties': [
            {'key': 'desc', 'value': html},
            {'key': 'zhuangBaUseFlag', 'value': '0' if flag is None else str(flag)},
            {'key': 'userAgent', 'value': agent}]}
    return {'componentCode': 'WareEditor', 'inputType': 'multiText', 'value': [
        entry(detail_html(urls), existing.get('zhuangBaUseFlag'), 'pc'),
        entry(detail_html(urls, mobile=True), existing.get('mobileZhuangBaUseFlag'), 'mobile')]}


def build_detail_patch_body(product_id, category_id, urls, existing=None):
    """PATCH body that changes only WareEditor (PC + mobile detail HTML)."""
    component = wareeditor_component(urls, existing)
    return {'applyId': str(product_id), 'opType': 3, 'scene': 'pop',
            'productInfo': {'productId': int(product_id), 'categoryDetail': {'lastCategoryId': int(category_id)}},
            'productApplyDTO': {'id': str(product_id)},
            'patchOperationList': [{'path': 'product', 'value': json.dumps(component, ensure_ascii=False, separators=(',', ':'))}]}


def delivery_checks(manifest):
    c = dict(manifest.get('deliveryChecks') or {})
    binding = ((manifest.get('video') or {}).get('binding') or {})
    c['videoBound'] = binding.get('stage') == 'VIDEO_VERIFIED'
    for key in ('platformValidationPassed', 'productOnSale', 'detailQualityPassed'):
        c[key] = bool(c.get(key))
    return c


def completion_statement(checks):
    failed = [k for k in ('platformValidationPassed', 'productOnSale', 'detailQualityPassed') if not checks.get(k)]
    if failed:
        return '上架未完成：' + '、'.join(failed) + ' 未通过'
    return '全部完成' if checks.get('videoBound') else '上架完成（主图视频尚未绑定，不能称全部完成）'


def source_detail_problems(product_detail_desc, exemption_reason=''):
    """Matrix/clone routes keep the source product's own detail HTML: it must be complete on PC and mobile."""
    desc = product_detail_desc if isinstance(product_detail_desc, dict) else {}
    pc = [normalize_url(u) for u in extract_image_urls(desc.get('desc', ''))]
    mobile = [normalize_url(u) for u in extract_image_urls(desc.get('mobileDesc', ''))]
    if str(exemption_reason or '').strip():
        return []
    problems = []
    if len(pc) < MIN_MODULES:
        problems.append('源商品没有可核验的详情图，请先补充详情素材')
    if mobile and mobile != pc:
        problems.append('源商品 PC 与手机端详情图数量/顺序不一致，先修复源详情页')
    return problems
