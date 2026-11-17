"""POP missing category-attribute inventory and atomic completion through official jdo-cli.

Chain (verified 2026-11-01, do not swap APIs):
  products list -> products/{pid}?scene=pop (goodsAttrInfos) -> product-schemas?lastCategoryId&scene=pop
  -> PATCH product-applies/{pid} (CategoryGroupList, FULL attribute list) -> GET product-apply/{pid} readback.
Only category attributes are written. Title, price, stock, images and short titles are never touched.
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL_ID = 'jdo-product-status'
DOMESTIC_TITLES = ('国产/进口', '是否进口', '国产或进口', '进口/国产')
CUSTOM_TITLES = ('是否可定制', '是否定制')


def _save(path, value):
    from pop_safety import atomic_json
    atomic_json(path, value)


def _schema_payload(data):
    first = (data or [None])[0]
    if isinstance(first, str):
        return json.loads(first)
    return first or {}


def template_attrs(schema):
    groups = [c for c in schema.get('componentList') or [] if c.get('componentCode') == 'CategoryGroupList']
    out = []
    for child in (groups[0].get('childrenComponents') or []) if groups else []:
        rules = child.get('validateRule') or []
        required = any(r.get('validateType') == 'required' and str(r.get('validateRule')).lower() == 'true' for r in rules)
        max_items = next((int(r['validateRule']) for r in rules if r.get('validateType') == 'maxLength' and str(r.get('validateRule')).isdigit()), None)
        out.append({'code': child.get('componentCode'), 'title': (child.get('componentTitle') or '').strip(), 'inputType': child.get('inputType'),
                    'required': required, 'important': bool((child.get('extra') or {}).get('isImportant')), 'maxItems': max_items,
                    'options': [{'label': str(o.get('label') or ''), 'value': str(o.get('value'))} for o in child.get('optionsValueList') or [] if o.get('value') is not None]})
    return out


def main_image_url(detail):
    """First SPU main image from product detail; only trusted JD image hosts."""
    def walk(value):
        if isinstance(value, dict):
            for key in ('imgUrl', 'imageUrl', 'url', 'logo'):
                v = value.get(key)
                if isinstance(v, str) and ('jfs/' in v):return v
            for v in value.values():
                found = walk(v)
                if found:return found
        elif isinstance(value, list):
            for v in value[:5]:
                found = walk(v)
                if found:return found
        return None
    raw = walk(detail.get('material')) or walk((detail.get('skuList') or [None])[:1]) or (detail.get('productInfo') or {}).get('logo')
    if not raw:return None
    if raw.startswith('jfs/'):return 'https://img14.360buyimg.com/n0/' + raw
    if raw.startswith('//'):raw = 'https:' + raw
    return raw if '.360buyimg.com/' in raw and raw.startswith('https://') else None


def current_attrs(product_info):
    result = {}
    for item in product_info.get('goodsAttrInfos') or []:
        name = (item.get('attrName') or '').strip()
        values = [str(v.get('attrValue')) for v in item.get('values') or [] if v.get('attrValue') not in (None, '')]
        if name:
            result[name] = {'attrId': item.get('attrId'), 'values': values, 'labels': [v.get('attrValueAlias') for v in item.get('values') or []]}
    return result


def _label_matches(title, options):
    found = [o for o in options if len(o['label']) >= 2 and o['label'] not in ('其他', '其它') and o['label'] in title]
    # Drop labels that are substrings of another matched label (e.g. 棉 vs 纯棉).
    return [o for o in found if not any(o is not p and o['label'] in p['label'] for p in found)]


def infer_value(attr, product_name, shop_defaults):
    """Return (value_string, reason) or (None, why_pending). Never guess free text."""
    title = attr['title'];options = attr['options'];kind = attr['inputType']
    if kind == 'areaCascade' or title == '产地':
        origin = shop_defaults.get('origin', {}).get(title) or shop_defaults.get('origin', {}).get('*')
        return (origin, 'shop-origin') if origin else (None, '产地无法从店铺主体或同店商品可靠推断，请提供 --origin 省id,市id')
    if title in DOMESTIC_TITLES or ('国产' in title and '进口' in title):
        hit = [o for o in options if o['label'] == '国产']
        imported = any(word in product_name for word in ('进口', '原装进口', '海外'))
        if hit and not imported:
            return hit[0]['value'], 'default-domestic'
        return None, '标题含进口信息或无“国产”选项，需人工确认'
    if title in CUSTOM_TITLES:
        hit = [o for o in options if o['label'] in ('不可定制', '否', '不支持定制')]
        return (hit[0]['value'], 'default-not-custom') if hit else (None, '无“不可定制”选项')
    if kind in ('singleSelect', 'multiSelect') and options:
        # Real-shop review: substring hits are unreliable (a bedroom diffuser title mentioning
        # 卫生间 is not a bathroom product). Offer them as suggestions, never auto-write them.
        hits = _label_matches(product_name, options)
        if hits:
            return None, '标题出现候选“%s”，需人工确认后填写' % '/'.join(o['label'] for o in hits[:3])
        return None, '标题未出现任何合法选项'
    return None, '%s 类型需人工填写' % (kind or 'unknown')


MODEL_SYSTEM = ('你是京东商品类目属性填写专家。根据商品主图、标题、类目和已有属性，从每个属性的合法选项中选择最符合该商品真实情况的选项编号。'
                '材质、功能、场景、风格等按主图和标题选最贴近事实的；不确定时选最通用且不会误导消费者的选项。'
                '若所有选项都明显不适用该商品（例如普通手套的“加热方式”、非礼品商品的“寓意”），返回空数组。'
                '标注 important=true 的属性是平台“重要属性”，只要有一个选项与商品不矛盾就必须选择一个，不要留空。只输出JSON。')


def model_prompt(product_name, category_id, known, attrs):
    items = []
    for a in attrs:
        items.append({'title': a['title'], 'important': bool(a.get('important') or a.get('required')), 'multi': a['inputType'] == 'multiSelect', 'max': a.get('maxItems') or (3 if a['inputType'] == 'multiSelect' else 1),
                      'options': [{'n': i, 'label': o['label']} for i, o in enumerate(a['options'])]})
    user = json.dumps({'商品标题': product_name, '类目ID': category_id, '已有属性': known, '待填属性': items}, ensure_ascii=False)
    user += '\n输出：{"choices":[{"title":"属性名","n":[选项编号...],"confidence":"high|medium|low"}]}'
    return MODEL_SYSTEM, user


def validate_choices(value, attrs):
    """Map model choices back to legal option ids; reject anything outside the template."""
    by_title = {a['title']: a for a in attrs};result = {}
    for item in value.get('choices') or []:
        if not isinstance(item, dict):raise ValueError('choice must be object')
        attr = by_title.get(str(item.get('title') or '').strip())
        if attr is None:continue
        picks = item.get('n') or []
        if not isinstance(picks, list) or any(not isinstance(i, int) or not 0 <= i < len(attr['options']) for i in picks):
            raise ValueError('option index outside template')
        picks = list(dict.fromkeys(picks))
        limit = 1 if attr['inputType'] == 'singleSelect' else (attr.get('maxItems') or 3)
        if not picks or (str(item.get('confidence')) == 'low' and not (attr.get('important') or attr.get('required'))):continue
        picks = picks[:limit]
        result[attr['title']] = {'value': ','.join(attr['options'][i]['value'] for i in picks),
                                 'reason': 'model:' + '/'.join(attr['options'][i]['label'] for i in picks)}
    return result


VISION_MODEL_HINTS = ('DeepSeek-V4.1-Flash', 'GPT-5', 'Gemini-3.1-Pro', 'Qwen-VL', 'Doubao-Vision')


class VisionAttrModel:
    """Main-image + title attribute chooser via an OpenAI-compatible vision model on the current key.
    Probed at runtime; unusable models are skipped. No key is logged or stored."""
    def __init__(self, key, base_url=None, timeout=90, models=None):
        raise RuntimeError('external-vision-provider-not-configured; use original deterministic attribute rules or obtain merchant input')
    def close(self):
        self.http.close()
    def generate(self, system, user, validator, image_url=None):
        import base64
        content = [{'type': 'text', 'text': user}]
        if image_url:
            try:
                raw = self.http.get(image_url, timeout=30).content
                if raw[:3] == b'\xff\xd8\xff' or raw[:8] == b'\x89PNG\r\n\x1a\n':
                    mime = 'image/png' if raw[:4] == b'\x89PNG' else 'image/jpeg'
                    content.insert(0, {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime, base64.b64encode(raw).decode())}})
            except Exception:
                pass
        last = None
        for model in [m for m in self.models if m not in self.disabled]:
            try:
                r = self.http.post('/chat/completions', json={'model': model, 'max_tokens': 1024, 'stream': False,
                                   'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]})
                if r.status_code in (401, 403, 404) or (r.status_code == 429 and '2007' in r.text):
                    with self.lock:self.disabled.add(model)
                    continue
                r.raise_for_status()
                from pop_text import parse_json
                value = validator(parse_json((r.json().get('choices') or [{}])[0].get('message', {}).get('content')))
                with self.lock:self.usage[model] = self.usage.get(model, 0) + 1
                return value
            except Exception as error:
                last = error
        raise RuntimeError('vision attribute model unavailable') from last


def model_fill(text_pool, rows, templates, details, workers=8):
    """rows: plan rows with needsConfirmation; returns {pid: {title: {value, reason}}}. Text pool only."""
    def one(row):
        pid = row['productId'];info = details[pid];template = {a['title']: a for a in templates[info['categoryId']]}
        attrs = [template[t['title']] for t in row['needsConfirmation'] if t['title'] in template and template[t['title']]['options'] and template[t['title']]['inputType'] in ('singleSelect', 'multiSelect')]
        if not attrs:return pid, {}
        known = {k: '/'.join(filter(None, map(str, v.get('labels') or []))) for k, v in info['attrs'].items()}
        system, user = model_prompt(info['productName'], info['categoryId'], known, attrs)
        validator = lambda value: validate_choices(value, attrs)
        image = info.get('imageUrl')
        try:
            if image and getattr(text_pool, 'generate', None) and 'image_url' in text_pool.generate.__code__.co_varnames:
                return pid, text_pool.generate(system, user, validator, image_url=image)
            return pid, text_pool.generate(system, user, validator)
        except Exception:return pid, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, rows))


def shop_origin_defaults(details, templates, explicit=None):
    """Origin from explicit config, else the single majority value already used by same-shop products."""
    if explicit:
        return {'origin': {'*': explicit}, 'source': 'explicit'}
    counts = {}
    for pid, info in details.items():
        cats = {a['title']: a for a in templates.get(info['categoryId'], [])}
        for name, value in info['attrs'].items():
            if name in cats and (cats[name]['inputType'] == 'areaCascade' or name == '产地') and value['values']:
                key = (name, ','.join(value['values']));counts[key] = counts.get(key, 0) + 1
    origin = {}
    for (name, value), count in sorted(counts.items(), key=lambda kv: -kv[1]):
        if name not in origin:
            competing = [c for (n, v), c in counts.items() if n == name and v != value]
            if not competing or count >= 2 * max(competing):
                origin[name] = value
    return {'origin': origin, 'source': 'same-shop-majority' if origin else 'none'}


def build_patch(pid, category_id, template, attrs, additions):
    """Complete CategoryGroupList: every current attribute + inferred missing ones, in template order."""
    by_title = {a['title']: a for a in template}
    unknown = sorted(set(attrs) - set(by_title))
    if unknown:
        raise ValueError('current attributes not in category template: ' + ','.join(unknown))
    entries = []
    for attr in template:
        if attr['title'] in attrs and attrs[attr['title']]['values']:
            value = ','.join(attrs[attr['title']]['values'])
        elif attr['title'] in additions:
            value = additions[attr['title']]
        else:
            continue
        if not value or any(not part.strip().lstrip('-').isdigit() for part in value.split(',')):
            raise ValueError('attrValues must be option ids, not text: ' + attr['title'])
        entries.append({'componentCode': attr['code'], 'properties': [{'key': 'attrValues', 'value': value}]})
    component = {'componentCode': 'CategoryGroupList', 'value': entries}
    body = {'applyId': str(pid), 'opType': 3, 'scene': 'pop',
            'productInfo': {'productId': int(pid), 'categoryDetail': {'lastCategoryId': int(category_id)}},
            'productApplyDTO': {'id': str(pid)},
            'patchOperationList': [{'path': 'product', 'value': json.dumps(component, ensure_ascii=False, separators=(',', ':'))}]}
    expected = {e_title: e_value for e_title, e_value in ((a['title'], next(e['properties'][0]['value'] for e in entries if e['componentCode'] == a['code'])) for a in template if any(e['componentCode'] == a['code'] for e in entries))}
    return body, expected


def verify_apply(apply_payload, expected, original_name=None):
    info = (apply_payload.get('data') or {}).get('productInfo') or {}
    actual = current_attrs(info)
    mismatches = [title for title, value in expected.items() if sorted(actual.get(title, {}).get('values', [])) != sorted(value.split(','))]
    if original_name is not None and info.get('productName') not in (None, original_name):
        mismatches.append('productName-changed')
    data = apply_payload.get('data') or {}
    status = next((x.get('bossAuditStatus') for x in (data, data.get('applyInfo') or {}, info) if isinstance(x, dict) and x.get('bossAuditStatus') is not None), None)
    return {'matched': not mismatches, 'mismatches': mismatches, 'bossAuditStatus': status}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def platform_broken_attrs(output_dir):
    """Category+attribute pairs the platform explicitly rejected as misconfigured (10103004000)."""
    broken = set()
    for receipt in Path(output_dir).parent.glob('**/attr-receipts/*.json'):
        try:value = json.loads(receipt.read_text(encoding='utf-8'))
        except Exception:continue
        reason = str(value.get('reason') or '')
        if value.get('status') == 'platform-rejected' and '属性配置异常' in reason and value.get('categoryId'):
            for title in __import__('re').findall('【([^】]+)】', reason):broken.add((int(value['categoryId']), title))
    return broken


def load_agent_choices(path):
    if not path:return {}
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or any(not isinstance(row, dict) for row in value.values()):raise ValueError('Agent attribute file must map product IDs to evidenced choices')
    return value


def inventory(client, identity, *, origin=None, workers=8, text_pool=None, skip_attrs=(), exclude_product_ids=(), product_ids=None, agent_choices=None):
    if product_ids is None:
        pids = []
        page = 1
        while True:
            # Unsorted pages are unstable (duplicates/missing rows observed on a 424-product shop).
            payload = client._get(SKILL_ID, '/rest/sp-product/v0/products', {'scopeSet': 'baseInfo,skuInfo', 'page': str(page), 'pageSize': '50', 'sortBy': 'created', 'sortType': 'asc'})
            rows = payload.get('data') or []
            pids.extend(str(r['productId']) for r in rows if r.get('productId'))
            total = int((payload.get('paginationData') or {}).get('totalItems') or 0)
            if not rows or len(pids) >= total:break
            page += 1
        if len(set(pids)) != len(pids) or len(pids) != total:raise ValueError('product list pagination incomplete or duplicated; no plan written')
    else:
        pids = list(map(str, product_ids))
        if any(not p.isdecimal() for p in pids) or len(set(pids)) != len(pids):raise ValueError('exact product IDs empty/duplicated/invalid')
    excluded = {str(p) for p in exclude_product_ids or ()}
    pids = [p for p in pids if p not in excluded]

    def detail(pid):
        data = client._get(SKILL_ID, '/rest/sp-product/v0/products/{productId}', {'productId': int(pid), 'scene': 'pop'}).get('data') or {}
        info = data.get('productInfo') or {}
        return pid, {'categoryId': (info.get('categoryDetail') or {}).get('lastCategoryId'), 'productName': info.get('productName') or '', 'attrs': current_attrs(info), 'imageUrl': main_image_url(data)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        details = dict(pool.map(detail, pids))
    templates = {}
    def schema(cid):
        return cid, template_attrs(_schema_payload(client._get(SKILL_ID, '/rest/sp-product/v0/product-schemas', {'lastCategoryId': int(cid), 'scene': 'pop'}).get('data')))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        templates = dict(pool.map(schema, sorted({d['categoryId'] for d in details.values() if d['categoryId']})))
    defaults = shop_origin_defaults(details, templates, origin)
    plans = [];pending = [];blocked = []
    first = {}
    for pid in pids:
        info = details[pid];template = templates.get(info['categoryId']) or []
        missing = [a for a in template if a['title'] not in info['attrs']]
        todo = [a for a in missing if infer_value(a, info['productName'], defaults)[0] is None]
        if todo:first[pid] = {'productId': pid, 'needsConfirmation': [{'title': a['title']} for a in todo]}
    model_values = model_fill(text_pool, list(first.values()), templates, details, workers) if (text_pool is not None and first) else {}
    for pid, supplied in (agent_choices or {}).items():
        if str(pid) not in details:raise ValueError('Agent attributes outside frozen product scope')
        choices = supplied.get('choices') or []
        if not supplied.get('evidence') or any(c.get('confidence') != 'high' for c in choices):raise ValueError('Host attribute choices need factual evidence and high confidence')
        model_values[str(pid)] = validate_choices(supplied, templates.get(details[str(pid)]['categoryId']) or [])
        for value in model_values[str(pid)].values():value['reason'] = 'host-evidence:' + str(supplied['evidence'])[:300]
    for pid in pids:
        info = details[pid];template = templates.get(info['categoryId']) or []
        missing = [a for a in template if a['title'] not in info['attrs']]
        skipped = [a['title'] for a in missing if (int(info['categoryId'] or 0), a['title']) in set(skip_attrs)]
        missing = [a for a in missing if a['title'] not in skipped]
        if not missing:continue
        additions = {};todo = []
        for attr in missing:
            value, why = infer_value(attr, info['productName'], defaults)
            if not value and attr['title'] in model_values.get(pid, {}):
                value, why = model_values[pid][attr['title']]['value'], model_values[pid][attr['title']]['reason']
            if value:additions[attr['title']] = {'value': value, 'reason': why}
            else:todo.append({'title': attr['title'], 'code': attr['code'], 'inputType': attr['inputType'], 'required': attr['required'], 'important': attr['important'], 'reason': why, 'options': [o['label'] for o in attr['options'][:30]]})
        row = {'productId': pid, 'categoryId': info['categoryId'], 'productName': info['productName'], 'missing': [a['title'] for a in missing], 'autoFill': additions, 'needsConfirmation': todo}
        if any(t['required'] for t in todo):
            row['status'] = 'blocked-required-unknown';blocked.append(row);continue
        if not additions:
            row['status'] = 'needs-confirmation';pending.append(row);continue
        try:
            body, expected = build_patch(pid, info['categoryId'], template, info['attrs'], {k: v['value'] for k, v in additions.items()})
        except ValueError as error:
            row.update(status='blocked-template-mismatch', reason=str(error));blocked.append(row);continue
        row.update(status='planned', body=body, expected=expected, beforeFingerprint=fingerprint(info['attrs']))
        plans.append(row)
        if todo:pending.append({**{k: row[k] for k in ('productId', 'productName', 'missing')}, 'needsConfirmation': todo, 'status': 'partially-planned'})
    return {'shopIdentity': identity, 'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'productCount': len(pids), 'categoryCount': len(templates),
            'missingProductCount': len(plans) + len([p for p in pending if p['status'] == 'needs-confirmation']) + len(blocked),
            'originDefaults': defaults, 'plans': plans, 'needsConfirmation': pending, 'blocked': blocked}


def submit_and_verify(client, plan_path, *, receipts_dir=None, product_ids=None, workers=4):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if product_ids:
        wanted = set(map(str, product_ids));plan = {**plan, 'plans': [r for r in plan['plans'] if r['productId'] in wanted]}
    out = Path(receipts_dir or Path(plan_path).parent / 'attr-receipts');out.mkdir(parents=True, exist_ok=True)
    def one(row):
        pid = row['productId'];receipt = out / (pid + '.json')
        saved = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
        if saved and saved.get('bodyFingerprint') != fingerprint(row['body']):
            return {'productId': pid, 'status': 'blocked', 'reason': 'Receipt belongs to another patch; no replay'}
        if not saved:
            data = client._get(SKILL_ID, '/rest/sp-product/v0/products/{productId}', {'productId': int(pid), 'scene': 'pop'}).get('data') or {}
            info = data.get('productInfo') or {}
            if fingerprint(current_attrs(info)) != row['beforeFingerprint']:
                return {'productId': pid, 'status': 'skipped-changed', 'reason': 'Attributes changed since planning; re-plan'}
            saved = {'status': 'intent', 'bodyFingerprint': fingerprint(row['body']), 'productName': info.get('productName'), 'categoryId': row.get('categoryId'), 'at': int(time.time())}
            _save(receipt, saved)
            try:
                response = client._post_with_body_file(SKILL_ID, '/rest/sp-product/v0/product-applies/{applyId}', row['body'], params={'applyId': pid}, method='PATCH')
                saved.update(status='submitted', response=response.get('data'))
            except Exception as error:
                rejected = type(error).__name__ == 'JdoBusinessRejected'
                saved.update(status='platform-rejected' if rejected else 'unknown', failureClass=type(error).__name__, reason=str(error)[:300])
            _save(receipt, saved)
        try:
            apply = client._get(SKILL_ID, '/rest/sp-product/v0/product-apply/{applyId}', {'applyId': int(pid), 'scene': 'pop'})
            check = verify_apply(apply, row['expected'], saved.get('productName'))
        except Exception as error:
            check = {'matched': False, 'mismatches': ['readback-unavailable'], 'failureClass': type(error).__name__}
        status = 'verified-apply' if check['matched'] else ('submitted-mismatch' if saved['status'] == 'submitted' else saved['status'])
        saved.update(verification=check, verifiedAt=int(time.time()), status=status if status != 'verified-apply' else 'verified-apply');_save(receipt, saved)
        return {'productId': pid, 'status': status, 'filled': sorted(row['autoFill']), 'mismatches': check['mismatches'], 'bossAuditStatus': check.get('bossAuditStatus')}
    # Each product is its own atomic apply; bounded parallelism, one receipt per product.
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(plan['plans']) or 1))) as pool:
        results = list(pool.map(one, plan['plans']))
    counts = {}
    for r in results:counts[r['status']] = counts.get(r['status'], 0) + 1
    summary = {'shopIdentity': plan['shopIdentity'], 'plannedProducts': len(plan['plans']), 'counts': counts, 'results': results,
               'allVerified': bool(results) and all(r['status'] == 'verified-apply' for r in results),
               'note': 'verified-apply = 申请单回查与提交值一致；不等于线上已生效（bossAuditStatus=-1为POP轻量更新正常态）。'}
    _save(Path(plan_path).parent / ('attr-submit-result.json' if not product_ids else 'attr-submit-canary.json'), summary)
    return summary
