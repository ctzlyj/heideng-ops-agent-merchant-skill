"""Copy one merchant-owned product across two explicitly verified POP shops."""
import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys

import jdo_listing_mvp as api
import jd_product_pipeline as pipeline
import matrix_listing as matrix
from heideng_merchant import owned_product_copy as copy
from heideng_merchant.safety import atomic_json, file_sha, read_json, safe_join
from heideng_merchant.shop_copy_delivery import capture_freight
from heideng_merchant.state import FileLock, merchant_home


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def verify(config, profile):
    settings = read_json(config) or {}
    bound = (settings.get('stores') or {}).get(profile) or settings.get('store') or {}
    if not str(bound.get('shopId') or '').isdigit():
        raise ValueError('请从原店铺核验回执取得 shopId，再与 venderId 一起绑定到配置')
    store = api.verify_configured_store_identity(config, profile)
    if any(not str(store.get(k) or '').isascii() or not str(store[k]).isdigit() or int(store[k]) <= 0
           for k in ('shopId', 'venderId')):
        raise ValueError('官方核店缺少店铺编号或商家编号')
    return {k: str(store[k]) for k in ('profile', 'shopName', 'shopId', 'venderId')}


def inventory(args):
    target = verify(args.target_config,args.target_profile)
    source = verify(args.source_config,args.source_profile)
    if source['shopId']==target['shopId'] or source['profile']==target['profile']:
        raise ValueError('请选择两家不同的已授权店铺')
    products, seen = [], set()
    reasons = []
    for status in sorted(set(args.status)):
        expected = None
        count, page = 0, 1
        while True:
            response = api.get('jdo-product-status','/rest/sp-product/v0/products',{
                'scopeSet':['productId','productName','productStatus'],'productStatusList':str(status),
                'page':page,'pageSize':20,'sortBy':'created','sortType':'asc'})
            rows, meta = response.get('data'), response.get('paginationData') or {}
            if not isinstance(rows,list) or not str(meta.get('totalItems','')).isdigit():
                reasons.append(f'状态 {status} 第 {page} 页没有完整的列表与总数')
                break
            total = int(meta['totalItems'])
            if (expected is not None and expected != total) or int(meta.get('pageNum',page)) != page:
                reasons.append(f'状态 {status} 的列表在翻页期间发生变化')
                break
            expected = total
            ids = [str(r.get('productId') or '') for r in rows]
            if (any(not re.fullmatch('[1-9][0-9]*', pid) for pid in ids) or len(ids) != len(set(ids))
                    or seen.intersection(ids) or any(str(r.get('productStatus'))!=str(status) for r in rows)):
                reasons.append(f'状态 {status} 第 {page} 页存在身份重复、缺失或状态不一致')
                break
            products.extend({'productId':pid, 'title':r.get('productName'), 'status':status} for pid,r in zip(ids,rows))
            seen.update(ids)
            count += len(rows)
            if count == total:
                break
            if not rows or count > total:
                reasons.append(f'状态 {status} 的行数与官方总数不一致')
                break
            page += 1
    api.recheck_verified_jdo_store()
    record = {'sourceShop':source,'targetShop':target,'selectedStatuses':sorted(set(args.status)),'products':products,
              'issues':reasons,'status':'partial-inventory' if reasons else 'inventory-ready','publishedProducts':0}
    out = safe_join(merchant_home(), 'work/shop-copy-inventories/'+digest(record)[:32]+'.json')
    atomic_json(out,record)
    return {k:v for k,v in record.items() if k!='products'} | {
        'recordedProducts':len(products),'examples':products[:3],'inventoryFile':str(out)}


def read_owned_detail(pid):
    detail = matrix.read_product(pid)
    product = detail.get('productInfo') or {}
    if str(product.get('productId') or '') != str(pid):
        raise ValueError('官方商品详情没有返回所选商品，请核对原店铺和商品编号')
    active = api.require_verified_jdo_store()
    checked = set()
    for record in (product, detail):
        for key in ('venderId','shopId'):
            if key in record:
                if str(record[key]) != str(active[key]):
                    raise ValueError('商品详情中的店铺身份与本次核验的店铺不符')
                checked.add(key)
    if len(checked) != 2:
        # Some detail responses omit owner IDs. Prove membership in the authenticated
        # seller catalogue rather than treating a product URL as ownership evidence.
        result = api.get('jdo-product-status','/rest/sp-product/v0/products',{
            'productIdList':[int(pid)], 'scopeSet':'productId,productName,productStatus',
            'page':1,'pageSize':20})
        rows = result.get('data')
        if not isinstance(rows,list) or len(rows)!=1 or str(rows[0].get('productId'))!=str(pid):
            raise ValueError('当前店铺商品清单没有唯一匹配这一个商品')
    return detail


def read_product(pid):
    detail = read_owned_detail(pid)
    ids = [int(row['skuId']) for row in detail.get('skuList') or []]
    gaps = []
    try:
        stocks = api.query_sku_stocks(ids)
    except api.JdoError:
        stocks = None
        gaps.append('stock-service')
    try:
        videos = pipeline.existing_video_materials(ids)
    except api.JdoError:
        videos = None
        gaps.append('video-material-service')
    return detail, stocks, videos, gaps


def category(detail):
    return int(detail['productInfo']['categoryDetail']['lastCategoryId'])


def reference(shop, detail, *, for_creation=True):
    cid = category(detail)
    response = api.get('jdo-product-publish', '/rest/sp-product/v0/product-schemas',
                       {'scene':'pop','lastCategoryId':str(cid)}).get('data')
    if not isinstance(response, list) or len(response) != 1:
        raise ValueError('未取得当前类目唯一的官方创建模板')
    schema = json.loads(response[0]) if isinstance(response[0], str) else response[0]
    if not isinstance(schema, dict) or not schema.get('componentList'):
        raise ValueError('当前店铺的类目模板缺少组件')
    brands = (api.get('jdo-product-publish', '/rest/sp-seller/v0/vender-brands',
                      {'queryType':2, 'categoryId':cid}).get('data') if for_creation else [])
    return {'shopIdentity':shop, 'category':{'id':cid}, 'schema':schema, 'brands':brands}


def read_components(shop, detail):
    try:
        return reference(shop, detail, for_creation=False)['schema']['componentList']
    except (api.JdoError, ValueError):
        return []  # A read-only seller can still provide the product and its selected freight ID.


def task_directory(task):
    if not re.fullmatch('[0-9a-f]{64}', task):
        raise ValueError('请使用原任务回执中的 taskId')
    root = safe_join(merchant_home(), 'work/shop-copies/' + task[:24])
    existing = read_json(root/'current.json',{})
    if existing and existing.get('taskId') != task:
        raise ValueError('任务索引指向不同的源商品或店铺，未覆盖')
    return root


def load_copy(root):
    pointer = read_json(root/'current.json') or {}
    revision = pointer.get('revision', '')
    if not re.fullmatch('[0-9a-f]{64}', revision):
        raise ValueError('没有找到原商品复制任务')
    folder = safe_join(root, 'revisions/' + revision[:24])
    frozen = read_json(folder/'source.json')
    if not frozen or frozen.get('sha256') != revision:
        raise ValueError('原商品快照与任务回执不一致')
    copy.plan_copy(frozen)  # Check the frozen data hash before following any pointers.
    if pair_key(frozen) != pointer.get('taskId') or pair_key(frozen)[:24] != root.name:
        raise ValueError('快照绑定的源店、目标店或商品与原任务不一致')
    return folder, frozen


def pair_key(frozen):
    stores = (frozen['sourceShop'], frozen['targetShop'])
    return digest([*[s[key] for s in stores for key in ('shopId','venderId')], frozen['sourceProductId']])


def require_target(frozen, args):
    target = verify(args.target_config, args.target_profile)
    if target != frozen['targetShop']:
        raise ValueError('实际目标店铺与这笔原任务不一致')
    return target


def freeze(args):
    if args.product_id <= 0:
        raise ValueError('请选择一个确定的源商品')
    target = verify(args.target_config, args.target_profile)
    existing_id = args.existing_target_id
    if existing_id:
        if existing_id <= 0 or existing_id == args.product_id:
            raise ValueError('既有目标商品编号不能是源商品编号')
        read_owned_detail(existing_id)
        api.recheck_verified_jdo_store()
    source = verify(args.source_config, args.source_profile)
    detail, stocks, videos, gaps = read_product(args.product_id)
    frozen = copy.freeze_copy(source, target, detail, stock_rows=stocks, video_rows=videos)
    task = pair_key(frozen)
    root = task_directory(task)
    with FileLock(root/'copy.lock'):
        task_directory(task)
        prior = publication_state(root,task)
        if prior['status'] != 'not-submitted':
            if existing_id and str(prior.get('targetProductId')) != str(existing_id):
                raise ValueError('本任务已有其他目标或未决提交，请先按原回执对账')
            return prior
        freight = capture_freight(api, detail, read_components(source, detail), source)
        api.recheck_verified_jdo_store()
        plan = copy.plan_copy(frozen)
        folder = safe_join(root, 'revisions/' + frozen['sha256'][:24])
        existing = read_json(folder/'source.json')
        if existing is not None and existing != frozen:
            raise ValueError('原商品快照目录已经绑定了不同内容，未覆盖')
        atomic_json(folder/'source.json', frozen)
        atomic_json(folder/'source-delivery.json', freight)
        atomic_json(folder/'plan.json', plan)
        atomic_json(root/'current.json', {'taskId':task, 'revision':frozen['sha256'], 'sourceShop':source,
                                         'targetShop':target,'sourceProductId':frozen['sourceProductId'],
                                         'existingTargetId':existing_id})
        content = plan['content']
        first_sku = next(iter(content['skus']), None)
        return {'status':'local-plan','taskId':task, 'revision':frozen['sha256'], 'sourceShop':source,
                'targetShop':target, 'sourceProductId':str(args.product_id), 'skuCount':plan['skuCount'],
                'sourceExampleSkuUrl':'https://item.jd.com/'+first_sku+'.html' if first_sku else None,
                'title':content['title'],'packaging':content['packaging'],
                'gallerySlots':{gid:len(urls) for gid,urls in (content['mainGroups'] or {}).items()},
                'readGaps':gaps, 'planFile':str(folder/'plan.json'), 'sourceFreightEvidence':str(folder/'source-delivery.json'),
                'existingTargetProductId':existing_id,'platformWrites':0}


def empty_media(frozen):
    return {k:frozen[k] for k in ('sourceShop','targetShop','sourceProductId')} | {'images':[]}


def stage_media(folder, frozen, target):
    from PIL import Image
    from heideng_merchant.sample_comparison import download_image
    from heideng_merchant.sku_image_edit import media_space
    urls = copy.plan_copy(frozen)['imageUrls']
    manifest = empty_media(frozen)
    task_root = folder.parent.parent
    zone = None
    for url in urls:
        url_key = digest(url)[:24]
        local = safe_join(folder, 'media/'+url_key+'.img')
        origin_file = safe_join(folder, 'media/'+url_key+'.json')
        origin = read_json(origin_file)
        if origin is None:
            raw = download_image('https:' + url if url.startswith('//') else url)
            original_hash = sha256(raw).hexdigest()
            if local.exists() and file_sha(local) != original_hash:
                raise ValueError('中断前的原图与当前获取的字节不同，请保留原样核对')
            local.parent.mkdir(parents=True, exist_ok=True)
            pending = local.with_suffix('.tmp')
            pending.write_bytes(raw)
            pending.replace(local)
            atomic_json(origin_file, {'sourceUrl':url,'sha256':original_hash})
            origin = read_json(origin_file)
        content_hash = file_sha(local)
        if origin != {'sourceUrl':url,'sha256':content_hash}:
            raise ValueError('缓存原图与首次读取的来源或文件哈希不一致')
        path = safe_join(task_root, 'uploads/'+content_hash[:32]+'.json')
        upload = read_json(path)
        if upload is not None:
            if (upload.get('status') != 'accepted' or not upload.get('imgUrl') or
                    upload.get('sha256') != content_hash or upload.get('shopIdentity') != target):
                return {'status':'upload-needs-reconciliation','receipt':str(path),'replayed':False}
        else:
            with Image.open(local) as image:
                suffix = {'JPEG':'.jpg','PNG':'.png'}.get(image.format)
                image.verify()
            if not suffix:
                return {'status':'needs-media-format-review','sourceImage':str(local)}
            staged = safe_join(task_root, 'uploads/'+content_hash[:32]+suffix)
            staged.parent.mkdir(exist_ok=True, parents=True)
            staged.write_bytes(local.read_bytes())
            if file_sha(staged) != content_hash:
                raise ValueError('原图在上传准备期间已改变')
            if zone is None:
                zone = media_space(api)
            intent = {'status':'uploading','sha256':content_hash,'shopIdentity':target}
            atomic_json(path, intent)
            response = api.upload(*zone, staged)
            if not response.get('imgUrl'):
                return {'status':'upload-needs-reconciliation','receipt':str(path),'replayed':False}
            upload = {**intent, 'status':'accepted','imgUrl':response['imgUrl']}
            atomic_json(path, upload)
        manifest['images'].append({'sourceUrl':url,'sourceFile':str(local),'sourceSha256':content_hash,
                                   'uploadReceipt':upload})
    atomic_json(folder/'media.json',manifest)
    return {'status':'media-ready','sourceUrls':len(urls),'uniqueFiles':len({i['sourceSha256'] for i in manifest['images']}),
            'receipt':str(folder/'media.json'), 'publishedProducts':0}


def merge_delivery(identity, capture, human):
    if not isinstance(human,dict) or (human and any(str((human.get('shop') or {}).get(k,'')) != identity[k]
                                                   for k in ('profile','shopId','venderId'))):
        raise ValueError('配送规则的原店铺身份不一致')
    result = {**human, **capture, 'shop':identity}
    for key in ('freightTemplates','promiseTemplates'):
        templates = {str(t['id']):t for t in human.get(key, [])}
        for t in capture.get(key, []):
            templates[str(t['id'])] = t
        result[key] = list(templates.values())
    return result


def check_freight_reads(previous, current, ids=None):
    for tid, old in previous.get('freightReads', {}).items():
        if ids is not None and tid not in ids:
            continue
        if old.get('status') == 'read':
            new = current.get('freightReads',{}).get(tid,{})
            if new.get('status') != 'read' or new.get('sha256') != old.get('sha256'):
                raise ValueError('原已核验的运费规则发生变化或暂时无法复查，请重新核对原任务')


def delivery_evidence(folder, frozen, detail, target, components, extra, *, source_capture=None):
    provided = read_json(extra) if extra else read_json(folder/'delivery-input.json',{})
    if not isinstance(provided, dict):
        raise ValueError('配送证据文件无法读取')
    result = {}
    for side, identity in (('source', frozen['sourceShop']), ('target', target)):
        human = provided.get(side, {})
        ids = [t['id'] for t in human.get('freightTemplates', [])]
        capture = ((source_capture if source_capture is not None else read_json(folder/'source-delivery.json',{})) if side == 'source' else
                   capture_freight(api, detail, components, target, template_ids=ids))
        # Keep the official capture and host-interpreted page rules together. Page input
        # cannot override shop identity or the platform's raw read receipts.
        result[side] = merge_delivery(identity, capture, human)
    return result


def prepare(folder, frozen, target, args):
    from heideng_merchant.owned_product_copy import prepare_copy_schema
    source = frozen['sourceDetail']
    ref = reference(target, source)
    delivery = delivery_evidence(folder, frozen, {}, target, ref['schema']['componentList'], args.delivery_evidence)
    if args.delivery_evidence:
        atomic_json(folder/'delivery-input.json',read_json(args.delivery_evidence))
    atomic_json(folder/'delivery-evidence.json', delivery)
    prepared = prepare_copy_schema(frozen, target, ref, media_evidence=read_json(folder/'media.json'),
                                   delivery_evidence=delivery)
    atomic_json(folder/'prepared.json',prepared)
    if prepared['status'] != 'ready':
        return {'status':'needs-evidence','missing':prepared.get('missing',[]),'evidenceFile':str(folder/'prepared.json'),
                'platformWrites':0}
    schema = prepared['schema']
    if args.intent == 'local-draft':
        atomic_json(folder/'pilot.json', {'intent':'local-draft','revision':frozen['sha256']})
        return {'status':'local-draft-ready','draftFile':str(folder/'prepared.json'),'followUp':prepared.get('followUp',[]),
                'sourceProductId':frozen['sourceProductId'],'targetShop':target,'platformWrites':0}
    cid = category(source)
    body = {'scene':'pop','schema':json.dumps(schema,ensure_ascii=False,separators=(',',':')),
            'productApplyDTO':{'categoryDTO':{'lastCategoryId':cid}}}
    approval = digest({'source':frozen['sha256'], 'target':target, 'body':body, 'delivery':delivery})
    atomic_json(folder/'pilot.json',{'approval':approval,'body':body,'intent':'publish-one','revision':frozen['sha256'],
                                    'deliveryDigest':digest(delivery),'target':target})
    return {'status':'pilot-prepared','approvalFingerprint':approval,'sourceProductId':frozen['sourceProductId'],
            'targetShop':target,'followUp':prepared.get('followUp',[]),'platformWrites':0}


def publication_state(root, task):
    body_dir = root/'publication'
    result = read_json(body_dir/'result.json', {}) or {}
    data = result.get('data') if isinstance(result.get('data'),dict) else {}
    marker = body_dir/'publish-body.submit-state.json'
    saved = read_json(marker,{})
    for key in ('productId','applyId'):
        if data.get(key) and saved.get(key) and str(data[key]) != str(saved[key]):
            raise ValueError('原申请回执与提交记录中的商品或申请编号不一致')
    target_id = data.get('productId') or saved.get('productId')
    apply_id = data.get('applyId') or saved.get('applyId')
    status = ('submitted' if target_id or apply_id else
              'submission-needs-reconciliation' if marker.exists() else 'not-submitted')
    pointer = read_json(root/'current.json',{})
    bound = pointer.get('existingTargetId')
    if bound is not None:
        if status != 'not-submitted' or pointer.get('taskId') != task or not str(bound).isdigit():
            raise ValueError('已有目标与任务提交记录不一致，请核对原样品')
        status, target_id = 'existing-target-for-comparison', bound
    return {'status':status,
            'taskId':task,'targetProductId':target_id,'applyId':apply_id,
            'followUp':read_json(body_dir/'follow-up.json',[]),
            'receiptDirectory':str(body_dir),'consumerPageStatus':'unchecked','replayed':False}


def validation_passed(response):
    if not isinstance(response,dict) or response.get('success') is not True or not isinstance(response.get('data'),dict):
        return False
    data = response['data']
    for level in (response,data):
        if level.get('errorList') or ('code' in level and level['code'] not in (0,'0',200,'200','SUCCESS')):
            return False
        if any(k in level and level[k] is not True for k in ('valid','success','ok','passed','allowPublish')):
            return False
        if 'status' in level and str(level['status']).lower() not in ('ok','success'):
            return False
    if not data:
        return True  # Documented clean validation can have an empty data object.
    if set(data) - {'wareKeeperDetectResultList','success','valid','passed','allowPublish','ok','status','code','errorList','message'}:
        return False
    findings = data.get('wareKeeperDetectResultList')
    return isinstance(findings,list) and all(isinstance(row,dict) and str(row.get('detectResult'))=='0' for row in findings)


def submit_one(root, folder, frozen, target, args):
    prior = publication_state(root,args.task)
    if prior['status'] != 'not-submitted':
        return prior
    original = folder/'pilot.json'
    plan = read_json(original) or {}
    if (read_json(folder/'prepared.json',{}).get('status') != 'ready' or plan.get('intent') != 'publish-one' or
            plan.get('revision') != frozen['sha256'] or plan.get('target') != target):
        raise ValueError('请先在当前版本准备并核对这一个目标商品')
    body = plan['body']
    delivery = read_json(folder/'delivery-evidence.json')
    if args.approval != plan.get('approval') or args.approval != digest(
            {'source':frozen['sha256'],'target':target,'body':body,'delivery':delivery}):
        raise ValueError('获准样品与原商品、目标店铺或草稿内容不符')
    # An unknown or already accepted write always wins, even if the caller refreshes
    # a snapshot or switches to another task folder for the same product/shops.
    source = verify(args.source_config,args.source_profile)
    if source != frozen['sourceShop']:
        raise ValueError('重新核对时源店铺已变化')
    detail, stocks, videos, _ = read_product(int(frozen['sourceProductId']))
    current = copy.freeze_copy(source,target,detail,stock_rows=stocks,video_rows=videos)
    if copy.source_fidelity(current) != copy.source_fidelity(frozen):
        raise ValueError('原商品在打样后发生变化，请重新取原商品、核对差异')
    old_freight = delivery['source']
    current_freight = capture_freight(api,detail,read_components(source,detail),source,
                                      template_ids=list(old_freight.get('freightReads', {})))
    check_freight_reads(old_freight, current_freight)
    target = require_target(frozen,args)
    ref = reference(target,detail)
    fresh_delivery = delivery_evidence(folder,frozen,{},target,ref['schema']['componentList'],None,
                                       source_capture=current_freight)
    check_freight_reads(delivery['target'], fresh_delivery['target'])
    from heideng_merchant.owned_product_copy import prepare_copy_schema
    fresh = prepare_copy_schema(frozen,target,ref,media_evidence=read_json(folder/'media.json'),
                                delivery_evidence=fresh_delivery)
    if fresh['status'] != 'ready' or fresh['schema'] != json.loads(body['schema']):
        raise ValueError('目标模板、媒体或配送规则与已审草稿不一致，请重新准备样品')
    out = root/'publication'
    brand = next(c['value'] for c in json.loads(body['schema']) if c['componentCode']=='WareBrand')
    validation = {**body,'productApplyDTO':{'brandId':brand,'categoryDTO':body['productApplyDTO']['categoryDTO']}}
    atomic_json(out/'validation-body.json',validation)
    with redirect_stdout(io.StringIO()):
        rc = api.command_validate_jd(argparse.Namespace(body=out/'validation-body.json',output=out/'validation-result.json'))
    response = read_json(out/'validation-result.json') or {}
    if rc or not validation_passed(response):
        return {'status':'validation-needs-review','receipt':str(out/'validation-result.json'),'publishedProducts':0}
    atomic_json(out/'publish-body.json',body)
    atomic_json(out/'follow-up.json',fresh.get('followUp',[]))
    try:
        api.submit_product_once(out/'publish-body.json',out/'result.json')
    except (api.JdoError, OSError, RuntimeError):
        if not (out/'publish-body.submit-state.json').exists():
            raise
    return publication_state(root,args.task)


def compare(root, folder, frozen, target, args):
    submitted = publication_state(root,args.task)
    pid = str(args.product_id or submitted.get('targetProductId') or '')
    if not pid.isdecimal() or int(pid) <= 0:
        return {**submitted,'nextAction':'先按原商品货号、申请和原提交回执查询目标商品编号。'}
    if submitted.get('targetProductId') and str(submitted['targetProductId']) != pid:
        raise ValueError('目标商品与本任务提交回执不符')
    if args.apply_id:
        if submitted.get('applyId') and str(submitted['applyId']) != str(args.apply_id):
            raise ValueError('指定申请编号与原样品的回执不一致')
        detail = matrix.read_apply(args.apply_id)
        if str((detail.get('productInfo') or {}).get('productId') or '') != pid:
            raise ValueError('申请单回读尚未证明属于所选商品')
        stocks, videos, gaps = None, None, ['application-readback-only']
    else:
        detail, stocks, videos, gaps = read_product(int(pid))
    delivery = delivery_evidence(folder, frozen, detail, target, read_components(target,detail), args.delivery_evidence)
    report = copy.compare_copy(frozen,target,detail,stock_rows=stocks,video_rows=videos,
                               media_evidence=read_json(folder/'media.json'),delivery_evidence=delivery)
    original = read_json(folder/'delivery-evidence.json',{})
    if original and not args.delivery_evidence:
        try:
            check_freight_reads(original['target'],delivery['target'])
        except ValueError as error:
            report['delivery']['checks'].append({'field':'WareTransport.readback','status':'needs-evidence',
                                                 'nextAction':str(error)})
            report['delivery']['status']='needs-evidence'
            if report['status']=='verified':
                report['status']='needs-evidence'
    info = detail['productInfo']
    source_info = frozen['sourceDetail']['productInfo']
    report.update(sourceProductId=frozen['sourceProductId'],targetProductId=pid,
                  sourcePlatformStatus={k:source_info[k] for k in ('productStatus','productStatusNew') if k in source_info},
                  platformStatus={k:info[k] for k in ('productStatus','productStatusNew') if k in info},
                  readbackView='application' if args.apply_id else 'product',
                  consumerPageStatus='unchecked',readGaps=gaps)
    report['skuLinks'] = [{'sourceSkuId':s,'targetSkuId':t,'sourceUrl':'https://item.jd.com/'+s+'.html',
                           'targetUrl':'https://item.jd.com/'+t+'.html'} for s,t in report['skuPairs'].items()]
    if report['status']=='verified':
        report['status']='compared-fields-match'
    report['bulkAuthorized'] = False
    atomic_json(folder/'comparison.json',report)
    checks = [*report['checks'], *report['delivery'].get('checks',[])]
    counts = {state:sum(c.get('status') == state for c in checks)
              for state in ('verified','different','needs-evidence')}
    mismatches = []
    for c in checks:
        if c.get('status') == 'different':
            mismatches.append({'field':c['field'],'source':str(c.get('source',c.get('sourceValue')))[:120],
                               'target':str(c.get('target',c.get('targetValue')))[:120]})
    return {k:report[k] for k in ('status','sourceProductId','targetProductId','sourcePlatformStatus','platformStatus','readbackView',
                                  'consumerPageStatus','packagingListStatus','bulkAuthorized','readGaps')} | {
            'checkCounts':counts,'skuLinkCount':len(report['skuLinks']),'skuLinks':report['skuLinks'][:3],
            'unresolvedFields':[c['field'] for c in checks if c.get('status')!='verified'][:12],
            'firstDifferences':mismatches[:4],
            'reportFile':str(folder/'comparison.json')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='自家两店单商品原样复制')
    subs = parser.add_subparsers(dest='action',required=True)
    for name in ('inventory','freeze','stage-media','prepare','submit-one','compare'):
        p = subs.add_parser(name)
        p.add_argument('--target-config', type=Path, required=True)
        p.add_argument('--target-profile', required=True)
        if name in ('inventory','freeze','submit-one'):
            p.add_argument('--source-config', type=Path, required=True)
            p.add_argument('--source-profile', required=True)
        if name not in ('inventory','freeze'):
            p.add_argument('--task', required=True)
        if name == 'freeze':
            p.add_argument('--product-id', type=int, required=True)
            p.add_argument('--existing-target-id', type=int, help='原任务已有目标商品时绑定该商品，仅对账')
        if name == 'inventory':
            p.add_argument('--status', type=int, action='append', required=True, help='要盘点的官方商品状态码，可重复')
        if name == 'stage-media':
            p.add_argument('--confirm', choices=['UPLOAD_COPY_MEDIA'], required=True)
        if name in ('prepare','compare'):
            p.add_argument('--delivery-evidence', type=Path)
        if name == 'prepare':
            p.add_argument('--intent', choices=['local-draft','publish-one'], default='local-draft')
        if name == 'submit-one':
            p.add_argument('--approval', required=True)
            p.add_argument('--confirm', choices=['PUBLISH_ONE_COPY'], required=True)
        if name == 'compare':
            p.add_argument('--product-id', type=int)
            p.add_argument('--apply-id', type=int, help='用原申请单回读目标商品的编辑值')
    args = parser.parse_args(argv)
    try:
        if args.action == 'inventory':
            result = inventory(args)
        elif args.action == 'freeze':
            result = freeze(args)
        else:
            root = task_directory(args.task)
            with FileLock(safe_join(root,'copy.lock')):
                folder, frozen = load_copy(root)
                target = require_target(frozen,args)
                if args.action == 'stage-media':
                    prior = publication_state(root,args.task)
                    result = prior if prior['status'] != 'not-submitted' else stage_media(folder, frozen, target)
                elif args.action == 'prepare':
                    prior = publication_state(root,args.task)
                    result = prior if prior['status'] != 'not-submitted' else prepare(folder, frozen, target, args)
                elif args.action == 'submit-one':
                    result = submit_one(root, folder, frozen, target, args)
                    result.update(sourceProductId=frozen['sourceProductId'],targetShop=target,
                                  sourceSkuUrl='https://item.jd.com/'+str(frozen['sourceDetail']['skuList'][0]['skuId'])+'.html')
                    if result.get('targetProductId'):
                        try:
                            result['comparison'] = compare(root,folder,frozen,target,argparse.Namespace(
                                task=args.task, product_id=result['targetProductId'], apply_id=None, delivery_evidence=None))
                        except (api.JdoError,ValueError,KeyError,OSError):
                            result['comparison'] = {'status':'awaiting-readback','nextAction':'从原复制任务只读对账。'}
                else:
                    result = compare(root, folder, frozen, target, args)
        result['ok'] = result['status'] in ('inventory-ready','local-plan','media-ready','local-draft-ready',
                                             'pilot-prepared','submitted','existing-target-for-comparison',
                                             'compared-fields-match')
        if result['status'] in ('submission-needs-reconciliation','upload-needs-reconciliation'):
            result['retryAllowed'] = False
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ok'] else 2
    except api.JdoError:
        print(json.dumps({'status':'needs-platform-receipt','message':'官方店铺请求未完成，请保留本任务并核对原回执。'},ensure_ascii=False))
        return 2
    except (KeyError, TypeError, ValueError, OSError) as error:
        from heideng_merchant.safety import redact
        print(json.dumps({'status':'blocked','message':redact(str(error))},ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
