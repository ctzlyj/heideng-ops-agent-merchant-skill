"""Replace specification images on one existing POP product using exact SKU identities."""
from argparse import Namespace
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from uuid import uuid4

from .safety import atomic_json, file_sha, read_json
from .state import FileLock, merchant_home


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'记录中存在重复字段：{key}')
        result[key] = value
    return result


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def sku_rows(detail, pid):
    if str(detail.get('productInfo', {}).get('productId')) != str(pid):
        raise ValueError('官方商品身份不一致')
    rows = {}
    for row in detail.get('skuList') or []:
        sid = str(row.get('skuId') or '')
        if not sid.isdecimal() or sid in rows or str(row.get('productId', pid)) != str(pid):
            raise ValueError('商品规格身份重复、缺失或跨商品')
        rows[sid] = row
    if not rows:
        raise ValueError('未读到完整规格')
    return rows


def pictures(detail, pid):
    rows = sku_rows(detail, pid)
    by_uuid = {}
    for item in (detail.get('material') or {}).get('ggtImages') or []:
        key = str(item.get('uuid') or '')
        if not key or key in by_uuid or not item.get('imageUrl'):
            raise ValueError('规格图片绑定不明确')
        by_uuid[key] = item['imageUrl']
    owners = {str(row.get('uuid') or sid): sid for sid, row in rows.items()}
    if len(owners) != len(rows) or not set(by_uuid).issubset(owners):
        raise ValueError('规格图与 SKU 归属不明确')
    return {sid: by_uuid.get(str(row.get('uuid') or sid), row.get('logo')) for sid, row in rows.items()}


def business_state(detail, pid):
    """Stock changes independently; an image edit never sends inventory fields."""
    product = dict(detail['productInfo'])
    product.pop('modifiedTime', None)
    material = dict(detail.get('material') or {})
    material.pop('ggtImages', None)
    rows = {sid: {k: v for k, v in row.items()
                  if k not in ('logo', 'imgTag', 'stockNum', 'incrementStockNum', 'modifiedTime')}
            for sid, row in sku_rows(detail, pid).items()}
    return {'product': product, 'material': material, 'skus': rows, 'extensions': detail.get('extendInfoList')}


def components(values):
    if not isinstance(values, list):
        raise ValueError('需要已有商品的完整编辑值')
    return unique((item['componentCode'], item) for item in values)


def properties(node):
    return unique((prop['key'], prop['value']) for prop in node.get('properties', []))


def check_attributes(actual, container, prefix):
    """Check the census as well as the selected values of category-dependent attributes."""
    expected = {}
    for attr in actual or []:
        key = prefix + str(attr['attrId'])
        expected[key] = sorted(str(v['attrValue']) for v in attr.get('values', []) if 'attrValue' in v)
    found = {}
    for key, item in components((container or {}).get('value') or []).items():
        values = properties(item).get('attrValues', '')
        if isinstance(values, str):
            values = values.strip('[]').split(',')
        found[key] = sorted(str(v).strip() for v in values if str(v).strip())
    if expected != found:
        raise ValueError('当前商品属性与编辑模板的属性或取值不同')


def verify_live_template(template, detail, pid):
    """A schema requested for a product may still contain unfilled category defaults."""
    top = components(template)
    product = detail['productInfo']
    def match(items, name, expected):
        if expected not in (None, '') and str(items.get(name, {}).get('value', '')) != str(expected):
            raise ValueError(f'编辑模板与当前商品字段 {name} 不符')
    for code, field in [('WareItemnum','itemNum'), ('WareWeight','weight'), ('WareLength','length'),
                        ('WareWide','width'), ('WareHeight','height')]:
        match(top, code, product.get(field))
    logistics = product.get('logisticsInfo') or {}
    for code, field in [('WareTransport','transportId'), ('WarePromise','promiseId')]:
        match(top, code, logistics.get(field))
    features = {f['key']: f['value'] for f in product.get('features') or []}
    match(top, 'WareSevenDayReturn', features.get('is7ToReturn'))
    check_attributes(product.get('goodsAttrInfos'), top.get('CategoryGroupList'), 'prop-product-')
    desc = product.get('productDetailDesc') or {}
    editors = [properties(c) for c in top.get('WareEditor', {}).get('value', [])]
    for channel, name in [('pc','desc'), ('mobile','mobileDesc')]:
        if desc.get(name) and not any(e.get('userAgent') == channel and e.get('desc') == desc[name] for e in editors):
            raise ValueError('编辑模板缺少当前详情描述')
    rows = sku_rows(detail, pid)
    for sku in top['SKUS']['value']:
        vals = components(sku['value'])
        sid = str(vals.get('SkuId', {}).get('value') or '')
        if sid not in rows:
            raise ValueError('实时模板未返回明确 SKU ID')
        row = rows[sid]
        match(vals, 'SkuVendorSku', row.get('outerId'))
        match(vals, 'SkuUpcCode', row.get('upcCode'))
        check_attributes(row.get('goodsAttrInfos'), vals.get('SkuAttr'), 'prop-sku-')
        sale = {a['componentCode']:properties(a) for a in vals.get('VenderCategoryValue', {}).get('value', [])}
        attrs = row.get('saleAttrs') or []
        if set(sale) != {'sale-prop-'+str(a['attrId']) for a in attrs}:
            raise ValueError('实时模板缺少当前规格销售属性')
        for attr in attrs:
            val = sale['sale-prop-'+str(attr['attrId'])]
            if (str(val.get('attrValueAlias', '')).strip('[]') != str(attr.get('attrValueAlias', ''))
                    or str(val.get('mappingId', '')) not in {str(x) for x in
                    (attr.get('mappingId'), attr.get('attrValues')) if x not in ('', None)}):
                raise ValueError('实时模板与销售属性或图片分组不一致')
    material = detail.get('material') or {}
    # All gallery groups must be accounted for in the official edit echo. GGT-only edits
    # must not drop an unrecognized type of online picture from the full body.
    known = {'mainImages','ggtImages','publishScheduleFlag'}
    if any(value and key not in known for key, value in material.items()):
        raise ValueError('线上存在尚未核对的附加素材，请取得经核验的完整原发布包')
    grouped = {}
    image_components = [top.get('WareSkuImg', {})]
    image_components.extend(components(sku['value']).get('SkuMainImage', {}) for sku in top['SKUS']['value'])
    for component in image_components:
        for image in component.get('value', []):
            props = properties(image)
            positions = grouped.setdefault(str(props.get('colorId')), {})
            position = int(props['orderSort'])
            if position in positions and positions[position] != props.get('imgUrl'):
                raise ValueError('编辑模板中的图片分组存在冲突')
            positions[position] = props.get('imgUrl')
    actual = {str(group['uuid']): {int(i['orderSort']):i['imgUrl'] for i in group['imageInfoList']}
              for group in material.get('mainImages') or []}
    if actual != grouped:
        raise ValueError('实时模板没有完整保留现有图片分组和顺序')


def edit_schema(template, detail, pid, targets):
    """Keep every existing business component, changing only the identified SKU's image."""
    schema = deepcopy(template)
    top = components(schema)
    title = detail['productInfo'].get('productName')
    if not title or top.get('WareTitle', {}).get('value') != title or 'SKUS' not in top:
        raise ValueError('模板未回填当前商品的标题和规格')
    brand = (detail['productInfo'].get('brandInfo') or {}).get('brandId')
    if brand is not None and str(top.get('WareBrand', {}).get('value')) != str(brand):
        raise ValueError('编辑模板的品牌与当前商品不符')
    rows = sku_rows(detail, pid)
    if not set(targets).issubset(rows):
        raise ValueError('指定规格不属于当前商品')
    codes = {}
    for sid, row in rows.items():
        if row.get('outerId'):
            codes.setdefault(str(row['outerId']), []).append(sid)
    seen = set()
    for group in top['SKUS']['value']:
        values = group['value']
        items = components(values)
        sid = str(items.get('SkuId', {}).get('value') or '')
        merchant_code = str(items.get('SkuVendorSku', {}).get('value') or '')
        if not sid and len(codes.get(merchant_code, [])) == 1:
            sid = codes[merchant_code][0]
            values.append({'componentCode':'SkuId', 'value':int(sid)})
        if sid not in rows or sid in seen or (merchant_code and merchant_code != str(rows[sid].get('outerId') or '')):
            raise ValueError('编辑模板 SKU 与官方规格无法逐一对应')
        row = rows[sid]
        price = (row.get('priceInfo') or {}).get('jdPrice')
        try:
            matches_price = Decimal(str(items.get('SkuJdprice', {}).get('value'))) == Decimal(str(price))
        except InvalidOperation:
            matches_price = False
        if not matches_price:
            raise ValueError('编辑模板价格与当前规格不符')
        if row.get('skuEnableStatus') is not None and str(items.get('SkuEnableStatus', {}).get('value')) != str(row['skuEnableStatus']):
            raise ValueError('编辑模板与规格启用状态不符')
        seen.add(sid)
        values[:] = [v for v in values if v['componentCode'] != 'SkuStockNum']
        if sid not in targets:
            continue
        item = items.get('SkuGgtImage')
        if item is None:
            item = {'componentCode':'SkuGgtImage'}
            values.append(item)
        item['value'] = [{'componentCode':'img', 'properties':[
            {'key':'imgUrl', 'value':targets[sid]}, {'key':'imgRefId', 'value':sid}]}]
    if seen != set(rows):
        raise ValueError('编辑模板没有覆盖线上全部 SKU')
    return schema


def template_for(api, identity, detail, pid, package, checkpoint=None):
    category = int(detail['productInfo']['categoryDetail']['lastCategoryId'])
    if package:
        package = Path(package)
        manifest = read_json(package/'manifest.json')
        store = manifest['store']
        if str(manifest.get('productId')) != str(pid) or any(
                str(store[k]) != str(identity[k]) for k in ('profile', 'shopName', 'venderId')):
            raise ValueError('原发布回执与当前商品、店铺不符')
        path = package/'.publish/publish-body.json'
        state = read_json(package/'state.json')
        if state.get('status') != 'SUCCEEDED' or str(state.get('productId')) != str(pid) or state.get('bodySha256') != file_sha(path):
            raise ValueError('原发布体缺少可核验的成功回执')
        baseline = read_json(package/'.publish/readback-apply.json')
        if business_state(baseline, pid) != business_state(detail, pid):
            raise ValueError('发布后商品已变更，请使用实时商品编辑模板')
        if pictures(baseline, pid) != pictures(detail, pid):
            checkpoint = checkpoint or {}
            if checkpoint.get('status') == 'verified' and checkpoint.get('expected') == pictures(detail, pid):
                last = Path(checkpoint['directory'])/'edit-body.json'
                if checkpoint.get('bodySha256') == file_sha(last):
                    return json.loads(read_json(last)['schema'], object_pairs_hook=unique)
            raise ValueError('原发布后图片已变更，需要与当前图片一致的编辑回执')
        return json.loads(read_json(path)['schema'], object_pairs_hook=unique)
    data = api.get('jdo-product-publish', '/rest/sp-product/v0/product-schemas',
                   {'scene':'pop', 'lastCategoryId':category, 'productId':pid}).get('data')
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], str):
        raise ValueError('未取得该商品当前完整的编辑模板')
    schema = json.loads(data[0], object_pairs_hook=unique)
    top = components(schema)
    # Unpopulated category templates have no current item values. Never post their defaults.
    if not top.get('WareTitle', {}).get('value') or not top.get('SKUS', {}).get('value'):
        raise ValueError('类目模板缺少该商品的回填值，请定位原发布包再核对')
    verify_live_template(schema, detail, pid)
    return schema


def readback(api, pid, receipt):
    detail = api.get('jdo-product-status', '/rest/sp-product/v0/products/{productId}',
                     {'productId':pid, 'scene':'pop'}).get('data') or {}
    actual = pictures(detail, pid)
    evidence = {sid: actual.get(sid) == url for sid, url in receipt['expected'].items()}
    preserved = digest(business_state(detail, pid)) == receipt['beforeOnlineBusiness']
    verified = set(actual) == set(evidence) and all(evidence.values()) and preserved
    return {'status':'verified' if verified else 'awaiting-readback', 'productId':pid,
            'skuMatches':evidence, 'otherFieldsMatch':preserved, 'consumerPageStatus':'unchecked',
            'checkedAt':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def media_space(api):
    zones = api.get('jdo-product-material', '/rest/sp-product/v0/media-zones').get('data') or []
    zone = next((z['zoneId'] for z in zones if z.get('zoneType') == 1), None)
    if zone is None:
        raise ValueError('未找到本店图片空间')
    cats = api.get('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/categories',
                   {'zoneId':zone, 'page':1, 'pageSize':100}).get('data') or []
    cat = next((c['categoryId'] for c in cats if c.get('categoryName') == '我的本地文件' or c.get('status') == 1), None)
    if cat is None:
        raise ValueError('本店图片空间无可用目录')
    return zone, cat


def run(api, get_detail, identity, pid, images, package=None, *, check_only=False, reconcile=False):
    from PIL import Image
    directory = merchant_home()/'work'/'sku-image-edits'/str(identity['venderId'])/str(pid)
    with FileLock(directory/'edit.lock'):
        record_path = directory/'current.json'
        prior = read_json(record_path, {})
        if reconcile or prior.get('status') in ('submitting', 'submitted', 'awaiting-readback'):
            if not prior.get('expected'):
                raise ValueError('没有待核验的原编辑回执')
            result = readback(api, pid, prior)
            if result['status'] == 'verified':
                prior = {**prior, 'status':'verified', 'readback':result}
                atomic_json(record_path, prior)
                atomic_json(Path(prior['directory'])/'readback.json', result)
            same_inputs = images and prior['inputs'] == {sid:file_sha(path) for sid,path in images.items()}
            result.update(originalEdit=prior['directory'], resumedOriginal=True)
            if not reconcile and not same_inputs:
                result['originalStatus'] = result['status']
                result['status'] = 'original-edit-recovered' if result['originalStatus'] == 'verified' else 'prior-edit-pending'
                result['newRequestApplied'] = False
            return result
        detail = get_detail(pid)
        old = pictures(detail, pid)
        status = (detail.get('applyInfo') or {}).get('draftComputeStatus')
        if str(status) == '1':
            raise ValueError('商品申请正在审核，先核验原申请')
        before = digest(business_state(detail, pid))
        online = api.get('jdo-product-status','/rest/sp-product/v0/products/{productId}',
                         {'productId':pid,'scene':'pop'}).get('data') or {}
        if pictures(online, pid) != old:
            raise ValueError('线上规格图片与编辑详情不同，请先核对在途申请')
        template = template_for(api, identity, detail, pid, package, prior)
        edit_schema(template, detail, pid, {sid: 'planned' for sid in images})
        if check_only:
            return {'status':'eligible','productId':pid,'skuIds':sorted(old),'writes':0}
        if not images:
            raise ValueError('需要目标 SKU 及已准备好的图片')
        inputs = {}
        for sid, path in images.items():
            with Image.open(path) as img:
                img.verify()
                if img.width != img.height or not 480 <= img.width <= 1500:
                    raise ValueError(f'{sid} 的规格图需为 480–1500 像素方图')
            inputs[sid] = file_sha(path)
        if prior.get('status') == 'verified' and prior.get('inputs') == inputs and old == prior['expected']:
            return readback(api, pid, prior)
        zone, category = media_space(api)
        targets = {}
        store = {k:identity[k] for k in ('shopId','venderId','shopName','profile') if k in identity}
        for sid, image_hash in inputs.items():
            path = images[sid]
            upload_path = directory/'uploads'/f'{image_hash}.json'
            receipt = read_json(upload_path, {})
            if receipt and not receipt.get('url'):
                raise ValueError('此文件的原上传结果未知，请先核验图片空间')
            if not receipt:
                staged = directory/'uploads'/f'{image_hash}{path.suffix.lower()}'
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, staged)
                if file_sha(staged) != image_hash:
                    raise ValueError('图片文件已改变，重新核对后再上传')
                intent = {'status':'uploading','sha256':image_hash,'shopIdentity':store,'productId':pid}
                atomic_json(upload_path, intent)
                entry = api.upload(zone, category, staged)
                if not entry.get('imgUrl'):
                    raise ValueError('图片上传结果未知，请保留原回执')
                receipt = {**intent,'status':'accepted','url':entry['imgUrl']}
                atomic_json(upload_path, receipt)
            targets[sid] = receipt['url']
        fresh = get_detail(pid)
        if digest(business_state(fresh, pid)) != before or pictures(fresh, pid) != old or fresh.get('applyInfo') != detail.get('applyInfo'):
            raise ValueError('图片准备期间商品发生变化，已保留上传回执，编辑尚未提交')
        expected = {**old, **targets}
        work = directory/uuid4().hex
        body = {'scene':'pop', 'productApplyDTO':{'productId':pid,'saveActionType':0,
                'categoryDTO':{'lastCategoryId':int(detail['productInfo']['categoryDetail']['lastCategoryId'])}},
                'schema':json.dumps(edit_schema(template, detail, pid, targets), ensure_ascii=False)}
        if prior.get('status') == 'rejected' and prior.get('businessRequestHash') == digest(body):
            return {'status':'rejected','productId':pid,'platformCode':prior.get('platformCode'),
                    'originalEdit':prior['directory'],'replayed':False}
        atomic_json(work/'edit-body.json', body)
        record = {'status':'submitting','inputs':inputs,'shopIdentity':store,'beforeOnlineBusiness':digest(business_state(online, pid)),
                  'bodySha256':file_sha(work/'edit-body.json'), 'businessRequestHash':digest(body),
                  'expected':expected,'directory':str(work),'productId':pid}
        atomic_json(work/'intent.json', record)
        atomic_json(record_path, record)
        try:
            api.command_edit_product(Namespace(product_id=pid, confirm='EDIT_EXISTING_PRODUCT', body=work/'edit-body.json',
                                               output=work/'edit-result.json'))
        except Exception as exc:
            # The official CLI prefixes an explicit platform refusal with its numeric code.
            code = str(exc).split(maxsplit=1)[0] if str(exc) else ''
            if isinstance(exc, getattr(api, 'JdoError', ())) and code.isdecimal() and len(code) >= 6:
                record.update(status='rejected', platformCode=code)
                atomic_json(work/'rejection.json', record)
                atomic_json(record_path, record)
            raise
        record['status'] = 'submitted'
        atomic_json(record_path, record)
        result = readback(api, pid, record)
        atomic_json(work/'readback.json', result)
        atomic_json(record_path, {**record, 'status':result['status'], 'readback':result})
        return result
