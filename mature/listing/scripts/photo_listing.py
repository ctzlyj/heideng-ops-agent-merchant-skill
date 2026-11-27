"""Real-photo listing orchestration. No product write occurs without a current human review digest."""
from __future__ import annotations
import argparse,hashlib,html,json,os,re,shutil,subprocess,sys,tempfile,time,uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parent))
import win_no_window  # noqa: F401
import jdo_listing_mvp as cli
import jd_product_pipeline as pipeline
import detail_pages as dp
import sale_attr_templates as sat
import photo_samples
from jd_product_mover import HttpClient,MoverError,parse_mobile_page,parse_detail_urls
from photo_contract import (SCHEMA_VERSION,ReconcileRequired,check_store,initial_manifest,join_detail_panels,media_entries,missing_information,package_path,review_digest,walk_components,required)
from photo_generation import GenerationUnknown,atomic_json,generate_tasks,load,sha
from skill_paths import installed_skill_dir

ON_SALE_STATUSES = (1, 103)


def ensure_shop(shop):
    connector = installed_skill_dir('connection')
    if not connector or not (connector / 'scripts/linker.py').is_file():
        raise ValueError('安装包缺少 mature/connection/scripts/linker.py，请修复安装后继续')
    command = [sys.executable, '-X', 'utf8', str(connector / 'scripts/linker.py'),
               'ensure-shop', '--shop', shop, '--no-auth']
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=900)
    try:
        data = json.loads(run.stdout)
    except ValueError:
        raise ValueError('连接器没有返回可核验的店铺身份，请用连接入口核对') from None
    if data.get('status') != 'ready':
        raise ValueError('请由宿主先完成目标店连接：' + str(data.get('reason') or data.get('status')))
    return check_store({k: data[k] for k in ('profile', 'venderId', 'shopName', 'shopId') if k in data})


def verify_store(store):
 check_store(store);actual=dict(store)
 cli.configure_jdo_profile(store['profile'])
 data=cli.get('jdo-seller-info','/rest/sp-seller/v0/venderinfo',{'scopeSet':'baseInfo'}).get('data') or {}
 if int(data.get('venderId') or 0)!=int(store['venderId']) or (data.get('shopBaseInfo') or {}).get('shopName')!=store['shopName']:raise ValueError('店铺三要素回查不匹配，禁止写入')
 shop=data.get('shopBaseInfo') or {}
 if int(shop.get('type',-1))!=0 or int(shop.get('status') or 0)!=1:raise ValueError('Store is not an active POP store; writing is prohibited')
 cli.mark_jdo_store_verified(store['profile'],int(store['venderId']),store['shopName']);return actual

def reject_credentials(value):
 if isinstance(value,dict):
  for key,item in value.items():
   if str(key).lower().replace('_','') in {'apikey','accesstoken','token','cookie','authorization','password','appsecret','deviceid'}:
    raise ValueError('Credential/device fields must not enter a listing package')
   reject_credentials(item)
 elif isinstance(value,list):
  for item in value:reject_credentials(item)
 elif isinstance(value,str) and re.search(r'Bearer\s+\S{20,}|sk-[A-Za-z0-9]{20,}',value):
  raise ValueError('Credential-looking content must not enter a listing package')

def clean_reference_url(url):
 if not url:return None
 parsed=urlparse(url)
 if parsed.scheme!='https' or parsed.hostname!='item.jd.com' or parsed.username or parsed.password or not re.fullmatch(r'/\d+\.html',parsed.path):raise ValueError('A canonical public JD item URL is required')
 return 'https://item.jd.com'+parsed.path

def create_package(root,store,photos,title,reference_url=None,reference_answered=False):
 if not reference_answered:raise ValueError('先问一次有没有参考京东链接，并记录用户回答')
 root=Path(root)
 if (root/'manifest.json').exists():raise ValueError('Package exists; resume it without overwriting')
 root.mkdir(parents=True,exist_ok=True);check_store(store);copied=[]
 for i,source in enumerate(photos,1):
  source=Path(source)
  if not source.is_file():raise ValueError('Missing user photo')
  destination=root/'实拍图'/f'photo-{i:02d}{source.suffix.lower()}';destination.parent.mkdir(exist_ok=True);shutil.copy2(source,destination);copied.append(str(destination.relative_to(root)))
 if not copied:raise ValueError('请提供真实商品照片')
 m=initial_manifest(store,copied,title,clean_reference_url(reference_url));m['packageId']=uuid.uuid4().hex;m['facts']['title']=title
 atomic_json(root/'manifest.json',m);atomic_json(root/'state.json',{'status':'INFORMATION_PENDING'})
 from heideng_merchant.commercial_tasks import register
 register('listing', root, store, m['packageId'])
 return m

def read_manifest(root):
 root=Path(root);m=load(root/'manifest.json')
 if not m or m.get('schemaVersion')!=SCHEMA_VERSION:raise ValueError('A valid listing-package/manifest.json is required')
 check_store(m['store']);return m

def create_from_same_shop(root, store, product_id, title, photos=(), client=None):
    """Use the verified shop's editor gallery for this SPU. Keep SEO slots out of the set."""
    from image_patch_update import group_urls
    root = Path(root)
    if (root/'manifest.json').exists():
        raise ValueError('已有原任务，请恢复原包')
    verify_store(store)
    source = cli.get('jdo-product-update', '/rest/sp-product/v0/product-apply/{applyId}',
                     {'applyId': str(product_id), 'scene': 'pop'}).get('data') or {}
    product = source.get('productInfo') or {}
    if str(product.get('productId')) != str(product_id):
        raise ValueError('本店源商品编辑详情未核实 SPU，请核对来源')
    groups = group_urls(source)
    main = groups.get('0000000000') or []
    desc = product.get('productDetailDesc') or {}
    detail = dp.extract_image_urls(desc.get('desc') or desc.get('mobileDesc'))
    sources = [('spu_main', '0000000000', i, value) for i, value in enumerate(main, 1) if value]
    for group, values in groups.items():
        if group != '0000000000':
            sources.extend(('sku_main', group, i, value) for i, value in enumerate(values, 1) if value)
    by_uuid = {}
    for item in (source.get('material') or {}).get('ggtImages') or []:
        key = str(item.get('uuid') or '')
        if key and item.get('imageUrl'):
            by_uuid.setdefault(key, set()).add(item['imageUrl'])
    variants = {}
    for sku in source.get('skuList') or []:
        sku_id = str(sku.get('skuId') or '')
        if not sku_id.isdecimal() or sku_id in variants:
            raise ValueError('源商品规格身份不完整或重复，请重新核对该商品')
        attrs = sku.get('saleAttrs') or []
        groups_for_sku = [str(a['attrValues']) for a in attrs if str(a.get('attrValues', '')) in groups
                          and (str(a.get('dim', '')) == '1' or len(attrs) == 1)]
        variants[sku_id] = {'skuId': sku_id, 'spec': [a.get('attrValueAlias') for a in attrs if a.get('attrValueAlias')],
                            'galleryGroups': groups_for_sku}
        if sku.get('logo'):
            sources.append(('sku_logo', sku_id, 1, sku['logo']))
        # The editor keys specification images by the SKU UUID, while galleries use sale-attribute groups.
        sku_uuid = str(sku.get('uuid') or sku_id)
        for value in sorted(by_uuid.get(sku_uuid, ())):
            sources.append(('sku_spec', sku_id, 1, value))
    if not sources:
        raise ValueError('本店编辑详情缺少可核验的轮播或规格图片，请取得目标规格的真实参考')
    sources.extend(('detail', '', i, value) for i, value in enumerate(detail, 1))
    client = client or HttpClient(retries=1)
    cache = root/'.reference-cache'
    cache.mkdir(parents=True, exist_ok=True)
    files, entries = [], []
    for role, group, order, value in sources:
        url = cli.detail_image_url(value)
        host = (urlparse(url).hostname or '').lower()
        if not host.endswith(('.360buyimg.com', '.jd.com')) or not url.startswith(('https://', 'http://')):
            raise ValueError('源商品图片地址未经核实')
        path = cache/(hashlib.sha256(url.encode()).hexdigest()+'.jpg')
        if not path.is_file():
            from photo_generation import image_bytes
            image = image_bytes(client.get_bytes(url, headers={'User-Agent': 'Mozilla/5.0'}))
            temp = path.with_suffix('.tmp')
            temp.write_bytes(image)
            os.replace(temp, path)
        if path not in files:
            files.append(path)
        entries.append({'role': role, 'group': group, 'order': order, 'sourceUrl': url,
                        'path': str(path.relative_to(root)), 'sha256': sha(path)})
    m = create_package(root, store, list(photos) + files, title, reference_answered=True)
    copied = dict(zip(files, m['sourcePhotos'][len(photos):]))
    for entry in entries:
        entry['productPhoto'] = copied[root/entry['path']]
    for sku_id, variant in variants.items():
        own_images = [e for e in entries if e['role'] in ('sku_logo', 'sku_spec') and e['group'] == sku_id]
        own_gallery = [e for e in entries if e['role'] == 'sku_main' and e['group'] in variant['galleryGroups']]
        variant['variantPhotos'] = list(dict.fromkeys(e['productPhoto'] for e in own_images + own_gallery))
        candidates = own_images + [e for e in own_gallery if e['order'] == 1]
        candidates += [e for e in entries if e['role'] == 'spu_main' and e['order'] == 1]
        variant.update(firstImageCandidates=list(dict.fromkeys(e['productPhoto'] for e in candidates)),
                       consumerPageStatus='unchecked')
    receipt = {'sourceSpuId': str(product_id), 'store': store, 'source': 'merchant-product-apply',
               'mainCount': len(main), 'detailCount': len(detail), 'entries': entries, 'sourceSkus': variants}
    atomic_json(cache/'assets.json', receipt)
    m['reference'].update(sourceSpuId=str(product_id), purpose='same-shop-replica',
                          cacheManifest='.reference-cache/assets.json')
    atomic_json(root/'manifest.json', m)
    return m


def collect_reference(root,client=None):
 root=Path(root);m=read_manifest(root);url=clean_reference_url(m.get('reference',{}).get('url'))
 if not url:raise ValueError('The user selected no reference; do not ask again or invent one')
 sku=url.rsplit('/',1)[-1].split('.')[0];client=client or HttpClient(retries=1);began=time.monotonic()
 parsed=parse_mobile_page(client.get_text('https://item.m.jd.com/product/'+sku+'.html'))
 main=['https://img10.360buyimg.com/imgzone/'+p.lstrip('/') for p in parsed.get('item',{}).get('image') or []]
 info=parsed.get('product') or {};pid=info.get('popPid') or info.get('realSpuId')
 if not pid or not main:raise ValueError('Reference lacks verifiable image/detail identity; do not bypass login or guess')
 detail=parse_detail_urls(client.get_text('https://d.3.cn/desc/'+str(pid)))
 cache=root/'.reference-cache';entries=[]
 for role,urls in (('main',main),('detail',detail)):
  for i,source in enumerate(urls,1):
   destination=cache/role/f'{i:02d}.jpg';destination.parent.mkdir(parents=True,exist_ok=True)
   if not destination.is_file():destination.write_bytes(client.get_bytes(source,headers={'Referer':url,'User-Agent':'Mozilla/5.0'}))
   entries.append({'role':role,'order':i,'path':str(destination.relative_to(root)),'sourceUrl':source,'sha256':sha(destination),'purpose':'style-only'})
 result={'purpose':'style-only','sourceUrl':url,'sourceSkuId':sku,'consumerPageStatus':'unchecked','mainCount':len(main),'detailCount':len(detail),'entries':entries,'seconds':round(time.monotonic()-began,2)}
 atomic_json(cache/'assets.json',result);m['reference']['cacheManifest']=str((cache/'assets.json').relative_to(root));m['timings']['referenceCollectionSeconds']=result['seconds'];atomic_json(root/'manifest.json',m)
 return result


def record_first_view(root, sku_id, url, image, screenshot):
    """Attach the host's storefront observation to the exact source SKU and candidate."""
    root = Path(root)
    manifest = read_manifest(root)
    ref = manifest.get('reference') or {}
    if not ref.get('sourceSpuId') or not ref.get('cacheManifest'):
        raise ValueError('请先从已核店的源商品取得图位清单')
    receipt_path = package_path(root, ref['cacheManifest'])
    receipt = load(receipt_path)
    sku = receipt.get('sourceSkus', {}).get(sku_id)
    if (not sku or receipt.get('store') != manifest['store'] or receipt.get('sourceSpuId') != ref['sourceSpuId']
            or clean_reference_url(url) != f'https://item.jd.com/{sku_id}.html'
            or image not in sku['firstImageCandidates']):
        raise ValueError('实开链接、选中的规格与首图候选须对应')
    from PIL import Image
    with Image.open(screenshot) as shot:
        shot.verify()
    digest = sha(screenshot)
    dest = package_path(root, f'.reference-cache/storefront/{digest}{Path(screenshot).suffix.lower()}')
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        shutil.copyfile(screenshot, dest)
    sku.update(consumerPageStatus='host-observed', storefront={
        'url':url, 'productPhoto':image, 'screenshot':str(dest.relative_to(root)), 'sha256':digest,
        'recordedAt':time.strftime('%Y-%m-%dT%H:%M:%S')})
    atomic_json(receipt_path, receipt)
    return sku

def prepare_creative_plan(manifest, root, reference, design, *, preview=False, only=None):
    """Translate the host's ordered design into exact model calls and reusable assets."""
    facts = manifest.get('facts') or {}
    if only == 'detail':
        if not facts.get('skus') or not (facts.get('title') or manifest.get('title')):
            raise ValueError('详情页需要已确认的商品标题与规格')
    elif not preview:
        missing = missing_information(facts, reference)
        if missing:
            raise ValueError('先补齐发品事实：' + '、'.join(missing))
    if not isinstance(design, dict) or not isinstance(design.get('images'), list) or not design['images']:
        raise ValueError('请宿主根据商品事实、原图与经营目标提供逐图设计 --image-prompts-file')
    ref = manifest.get('reference') or {}
    evidence = {}
    if ref.get('url') or ref.get('sourceSpuId'):
        evidence = load(package_path(root, ref.get('cacheManifest') or '.reference-cache/assets.json'), {})
        if ref.get('sourceSpuId') and (evidence.get('sourceSpuId') != ref['sourceSpuId'] or evidence.get('store') != manifest['store']):
            raise ValueError('轮播来源与本次店铺、SPU 不匹配')
        if ref.get('url') and evidence.get('sourceUrl') != ref['url']:
            raise ValueError('轮播参考来源与本次链接不一致')
        if not (evidence.get('mainCount') or evidence.get('sourceSkus')) or not str(design.get('styleObservations') or '').strip():
            raise ValueError('先获取已指定的真实轮播图，记录宿主观察到的原图风格')
    source_photos = set(manifest['sourcePhotos'])
    sku_keys = {s['key'] for s in facts.get('skus') or []}
    tasks, modules, ids, planned_skus = [], [], set(), []
    for spec in design['images']:
        if not isinstance(spec, dict):
            raise ValueError('逐图设计条目必须是对象')
        key, role = spec.get('id'), spec.get('role')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', key) or key in ids:
            raise ValueError('逐图设计需要唯一的图片编号')
        if role not in ('main', 'sku', 'detail') or (only and role != only) or (preview and role == 'detail'):
            raise ValueError('图片用途与当前计划不一致')
        ids.add(key)
        reuse = spec.get('reusePhoto')
        photos = [reuse] if reuse else spec.get('photos')
        if not isinstance(photos, list) or not photos or not all(isinstance(p, str) and p in source_photos for p in photos):
            raise ValueError(f'{key} 需要选择包内真实商品素材，风格参考缓存只供观察')
        paths = [package_path(root, p) for p in photos]
        if not all(p.is_file() for p in paths):
            raise ValueError(f'{key} 的源图片缺失')
        prompt = spec.get('prompt')
        if not reuse and (not isinstance(prompt, str) or not prompt.strip()):
            raise ValueError(f'请宿主为 {key} 设计完整提示词')
        task = {'id': key, 'role': role, 'photos': list(map(str, paths)),
                'size': dp.MODULE_SIZE if role == 'detail' else '1024x1024',
                'previewOnly': preview, 'promptSource': 'host', 'sourceSha256': [sha(p) for p in paths]}
        if 'comparisonPhoto' in spec:
            provided = spec['comparisonPhoto']
            if not isinstance(provided,str) or provided not in source_photos or not package_path(root,provided).is_file():
                raise ValueError('商家指定的对照图须来自已登记的本商品素材')
            task['comparisonPhoto'] = provided
        if reuse:
            photo_samples.validate_reuse(manifest, role, spec.get('skuKey'), reuse, task['sourceSha256'][0])
        if reuse:
            task['reusePhoto'] = reuse
        else:
            task['prompt'] = prompt
        if role == 'main' and preview and manifest.get('sampleOf') and evidence:
            choices = [e.get('productPhoto') or e['path'] for e in evidence.get('entries', [])
                       if e.get('role') in ('main', 'spu_main') and e.get('order', 1) == 1]
            original = spec.get('firstImageReference') or next(iter(choices), None)
            if original:
                if original not in choices:
                    raise ValueError(f'{key} 应选择当前来源的首张主图作为对照')
                task.update(firstImageReference=original, consumerPageStatus='unchecked')
        if role == 'sku':
            task['skuKey'] = spec.get('skuKey')
            if task['skuKey'] not in sku_keys:
                raise ValueError('规格图需要对应本任务已登记的规格')
            if ref.get('sourceSpuId') and evidence.get('sourceSkus'):
                source_skus = evidence['sourceSkus']
                local = next(s for s in facts['skus'] if s['key'] == task['skuKey'])
                source_id = str(local.get('sourceSkuId') or spec.get('sourceSkuId') or '')
                if not source_id and len(source_skus) == 1:
                    source_id = next(iter(source_skus))
                if source_id not in source_skus:
                    raise ValueError(f'{key} 请按原商品规格对应 sourceSkuId，并核对该规格首图')
                related = source_skus[source_id]['firstImageCandidates']
                if not related:
                    raise ValueError(f'{key} 的源规格当前没有可核对的首图，请先核实该规格的实际展示图')
                observed = source_skus[source_id].get('storefront') or {}
                if observed:
                    related = [observed['productPhoto']]
                reference_photo = spec.get('firstImageReference') or (accepted or {}).get('firstImageReference') or (reuse if reuse in related else None)
                if related and reference_photo not in related:
                    raise ValueError(f'{key} 的 firstImageReference 应来自源规格 {source_id} 的首图候选')
                specific = {p for sku in source_skus.values() for p in sku['variantPhotos']}
                shared = {e['productPhoto'] for e in evidence['entries'] if e['role'] in ('spu_main', 'detail')}
                if set(photos) & (specific - set(source_skus[source_id]['variantPhotos']) - shared):
                    raise ValueError(f'{key} 的源图片专属另一规格，请核对商品差异')
                checks = spec.get('identityChecks')
                if not reuse and (not isinstance(checks, str) or not checks.strip()):
                    raise ValueError(f'{key} 请在 identityChecks 记录参考图能证明的商品和规格差异')
                task.update(sourceSkuId=source_id, firstImageReference=reference_photo,
                            identityChecks=spec.get('identityChecks') or '',
                            consumerPageStatus=source_skus[source_id]['consumerPageStatus'])
            planned_skus.append(task['skuKey'])
        elif role == 'detail':
            module = dict(spec, kind=spec.get('kind') or 'detail', skuKeys=spec.get('skuKeys') or [],
                          outputFile=f'详情图/{key}.jpg')
            if not set(module['skuKeys']).issubset(sku_keys):
                raise ValueError(f'{key} 含未登记的规格')
            issues = dp.scan_visible_text(module.get('exactVisibleText') or [], facts, ref.get('bannedTerms', []))
            if issues:
                raise ValueError('；'.join(issues))
            modules.append(module)
            task.update(module=module['kind'], skuKeys=module['skuKeys'])
        tasks.append(task)
    if not preview and not only and not any(t['role'] == 'main' for t in tasks):
        raise ValueError('主图计划不能为空')
    if not preview and not only and (set(planned_skus) != sku_keys or len(planned_skus) != len(sku_keys)):
        raise ValueError('请为每个实际 SKU 提供一张设计图或可复用规格图')
    if not preview:
        gaps=dp.detail_coverage_problems(facts,modules)
        if gaps:raise ValueError('；'.join(gaps))
        minimum = dp.detail_minimum(manifest)
        if len(modules) < minimum:
            raise ValueError(f'详情交付需要至少 {minimum} 张合格图，可选择已有图片复用')
    if not preview and not only:
        build_listing(manifest,root,reference,planned_tasks=tasks)
    return tasks, modules


def make_plan(root, reference=None, preview=False, only=None, design=None, redo=()):
    root = Path(root)
    m = read_manifest(root)
    reference = reference if reference is not None else load(root/'reference.json', {})
    tasks, modules = prepare_creative_plan(m, root, reference, design, preview=preview, only=only)
    atomic_json(root/'plan.json', tasks)
    atomic_json(root/'host-design.json', design)
    if not preview:
        atomic_json(root/'detail-plan.json', {'schema': 'host-detail-plan/v1', 'modules': modules})
    quote = generation_quote(root, m, tasks, redo)
    atomic_json(root/'image-quote.json', quote)
    return {'tasks': tasks, 'previewOnly': preview, 'detailModules': len(modules), 'quote': quote}


def generation_quote(root, manifest, tasks, redo=()):
    from photo_generation import generation_scope, pending_ids
    from heideng_merchant.image_models import image_credit_quote
    scope = generation_scope(manifest, tasks, root)
    units = pending_ids(tasks, root/'.generation', redo)
    return {'scope': scope, 'units': units, 'canSelectUnits': True, 'estimatedPaidImageCount': len(units),
            'reusedImageCount': len(tasks) - len(units), 'maxRequests': len(units),
            **image_credit_quote({task['id']:task['size'] for task in tasks if task['id'] in units}),
            'actualAmount': None, 'pricing': 'LTS4AI 按实际图像尺寸计积分，具体积分见本次报价。',
            'nextAction': ('已交办生成：简述本报价并立即打开本机费用确认窗口；商家只在窗口确认一次。只询价时仅展示报价。'
                           if units else '新增计费请求为零，直接复用已有图片。')}


def make_sample(root, design, image_id):
    """Select one deliverable without replacing the full package's plan, images or receipts."""
    root = Path(root)
    parent = read_manifest(root)
    if not isinstance(design, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', image_id):
        raise ValueError('请选择本次设计中一张有编号的图片')
    images = [s for s in design.get('images', []) if isinstance(s, dict) and s.get('id') == image_id]
    if len(images) != 1 or images[0].get('role') not in ('main', 'sku'):
        raise ValueError('请选择唯一的主图或规格图打样')
    selected = {**design, 'images': images}
    reference = load(root/'reference.json', {})
    tasks, _ = prepare_creative_plan(parent, root, reference, selected, preview=True)
    sample = package_path(root, f'.samples/{image_id}')
    origin = {'packageId': parent['packageId'], 'imageId': image_id}
    if not sample.exists():
        sample.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=sample.parent) as temp_dir:
            staging = Path(temp_dir)/'package'
            staging.mkdir()
            data = deepcopy(parent)
            data.update(packageId=uuid.uuid4().hex, sampleOf=origin, mainImages=[], detailImages=[],
                        variants=[], productId=None, skuIds=[], status='INFORMATION_PENDING')
            data.pop('review', None)
            data.pop('imageReview', None)
            for name in data['sourcePhotos']:
                target = package_path(staging, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(package_path(root, name), target)
            ref = data.get('reference') or {}
            if ref.get('cacheManifest'):
                receipt = load(package_path(root, ref['cacheManifest']))
                if ref.get('url'):
                    for entry in receipt.get('entries', []):
                        if entry.get('role') == 'main':
                            target = package_path(staging, entry['path'])
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(package_path(root, entry['path']), target)
                atomic_json(package_path(staging, ref['cacheManifest']), receipt)
            atomic_json(staging/'manifest.json', data)
            atomic_json(staging/'reference.json', reference)
            staging.rename(sample)
    manifest = read_manifest(sample)
    if manifest.get('sampleOf') != origin or manifest['store'] != parent['store'] or manifest['facts'] != parent['facts']:
        raise ValueError('样张来源或规格发生变化，请另选新的样张编号')
    checked, _ = prepare_creative_plan(manifest, sample, reference, selected, preview=True)
    if checked[0]['sourceSha256'] != tasks[0]['sourceSha256']:
        raise ValueError('样张源图已变化，请另选新的样张编号')
    result = make_plan(sample, preview=True, design=selected)
    output = {'samplePackage': str(sample), 'imageId': image_id, 'quote': result['quote']}
    if tasks[0]['role'] == 'sku' and not tasks[0].get('comparisonPhoto') and not manifest.get('samplePlanSha256'):
        from heideng_merchant.sample_delivery import target_sku
        from heideng_merchant.sample_comparison import before_for_sku
        target = target_sku(root,parent,tasks[0]['skuKey'])
        if target.get('skuId'):
            prior = load(sample/'.comparison/before.json',{}) or {}
            if (prior.get('productId'),prior.get('skuId')) != (target['productId'],target['skuId']):
                try:
                    verify_store(parent['store'])
                    detail = cli.get('jdo-product-status','/rest/sp-product/v0/products/{productId}',
                                     {'productId':int(target['productId']),'scene':'pop'}).get('data') or {}
                    before_for_sku(sample,detail,target,readback_source='official-product-detail')
                    output['comparisonStatus'] = 'target-original-captured'
                except (ValueError,OSError,cli.JdoError):
                    output['comparisonStatus'] = 'target-original-unverified'
    return output


def recover_sample_comparison(root, image_id, detail_receipt=None):
    """Match a local pre-revision original to an exact target SKU from a prior readback."""
    from heideng_merchant.sample_delivery import target_sku
    from heideng_merchant.sample_comparison import before_for_sku, read_comparison, write_comparison
    from heideng_merchant.safety import safe_join, is_linked
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',image_id):
        raise ValueError('样张编号无效')
    root = Path(root).resolve()
    parent = read_manifest(root)
    sample = safe_join(root,f'.samples/{image_id}')
    manifest = read_manifest(sample)
    if manifest.get('sampleOf') != {'packageId':parent['packageId'],'imageId':image_id} or manifest['store'] != parent['store']:
        raise ValueError('样张不属于该商品任务')
    accepted = [(path,row) for path,row in parent.get('acceptedSamples',{}).items()
                if path == f"已接受样张/{image_id}-{row.get('sha256')}.jpg" and row.get('role') == 'sku']
    if len(accepted) != 1:
        raise ValueError('未找到唯一已接受的规格样张版本')
    relative,row = accepted[0]
    accepted_path = safe_join(root,relative)
    if sha(accepted_path) != row['sha256']:
        raise ValueError('已接受样张与原回执不一致')
    target = target_sku(root,parent,row['skuKey'])
    if not target.get('skuId'):
        raise ValueError('没有唯一可核验的目标商品与规格')
    previous = read_comparison(sample,sample_sha=row['sha256'],target_product_id=target['productId'],target_sku_id=target['skuId'])
    if previous['kind'] == 'target-sku' and previous['status'] == 'verified':
        return previous
    candidates = {sha(p) for p in sample.iterdir() if not is_linked(p) and p.is_file()
                  and p.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and p.stat().st_size <= 12*1024*1024}
    if not candidates:
        return {'kind':'unknown','status':'unverified','reason':'原样张目录缺少可核对的历史原图'}
    # Some old WorkBuddy tasks saved the verified edit detail beside their listing package.
    paths = [safe_join(root,'.publish/readback-product.json'),safe_join(root,'.publish/readback-apply.json')]
    if detail_receipt:
        detail_receipt = Path(detail_receipt).absolute().relative_to(root.parent).as_posix()
        paths = [safe_join(root.parent,detail_receipt)]
    else:
        legacy = safe_join(root.parent,'after-edit-detail.json')
        if legacy.is_file():
            paths.insert(0,legacy)
    for path in paths:
        detail = load(path,{}) or {}
        if str((detail.get('productInfo') or {}).get('productId')) != str(target['productId']):
            continue
        try:
            before = before_for_sku(sample,detail,target,existing=candidates,readback_source=str(path))
        except (ValueError,OSError):
            continue
        write_comparison(sample,accepted_path,before)
        return read_comparison(sample,sample_sha=row['sha256'],target_product_id=target['productId'],target_sku_id=target['skuId'])
    return {'kind':'unknown','status':'unverified','reason':'未找到与已核对目标 SKU 图片字节一致的历史原图'}


def accept_sample(root, image_id, evidence):
    from heideng_merchant.sample_delivery import target_sku
    with package_lock(root, '.sample-accept.lock'):
        return photo_samples.accept_sample(root, image_id, evidence, read_manifest, target_sku)


def generate_plan(root, *, approval=None, redo=(), replace_unknown=()):
    root = Path(root)
    m = read_manifest(root)
    plan = load(root/'plan.json', [])
    design = load(root/'host-design.json')
    if not plan or not design:
        raise ValueError('付费执行需要宿主逐图设计。旧任务请保留原图与回执并重新 make-plan')
    only = 'detail' if all(t['role'] == 'detail' for t in plan) else None
    expected, _ = prepare_creative_plan(m, root, load(root/'reference.json', {}), design,
                                        preview=all(t.get('previewOnly') for t in plan), only=only)
    if expected != plan:
        raise ValueError('原计划或来源已变化，请重新核对设计和报价')
    quote = generation_quote(root, m, plan, redo)
    result = generate_tasks(plan, root/'.generation', redo=redo, approval=approval, scope=quote['scope'],
                            replace_unknown=replace_unknown)
    materialize_generated(root, plan, result)
    atomic_json(root/'image-quote.json', generation_quote(root, m, plan))
    return result


def materialize_generated(root,plan,result):
 root=Path(root);m=read_manifest(root);records=result['ledger'];main=[];details=[];variants=[]
 roles={t['role'] for t in plan};detail_only=roles=={'detail'}
 for task in plan:
  rec=records.get(task['id']) or {}
  if not task.get('reusePhoto') and rec.get('status')!='SUCCEEDED':continue
  folder={'main':'主图','sku':'SKU图','detail':'详情图'}[task['role']];dest=root/folder/f'{task["id"]}.jpg';dest.parent.mkdir(exist_ok=True)
  source=package_path(root,task['reusePhoto']) if task.get('reusePhoto') else root/'.generation'/rec['localPath']
  if task['role']=='detail':dp.normalize_detail_image(source,dest)
  else:shutil.copy2(source,dest)
  item={'id':task['id'],'localPath':str(dest.relative_to(root)),'sha256':sha(dest),'model':rec.get('model'), 'source':'reuse' if task.get('reusePhoto') else 'generated','onlineUrl':'','previewOnly':task.get('previewOnly',False)}
  if task['role']=='main':item['role']='main';main.append(item)
  elif task['role']=='detail':item.update(module=task.get('module'),skuKeys=task.get('skuKeys') or []);details.append(item)
  else:variants.append({'key':task['skuKey'],'skuId':None,'skuImage':item})
 if not detail_only:m['mainImages']=main;m['variants']=variants
 m['detailImages']=details
 m.setdefault('timings',{})['generationSeconds']=result['seconds'];m['generationModels']=result['modelsUsed']
 m.pop('review',None);m.pop('imageReview',None)
 complete=result['successCount']+sum(bool(t.get('reusePhoto')) for t in plan)==len(plan)
 m['deferredUnits']=result.get('deferredUnits',[])
 if m.get('sampleOf') and complete:m['samplePlanSha256']=sha(root/'plan.json')
 if not detail_only:m['status']='MATERIAL_PREVIEW' if any(t.get('previewOnly') for t in plan) else ('MATERIAL_REVIEW_PENDING' if complete else 'MATERIAL_INCOMPLETE')
 atomic_json(root/'manifest.json',m);return m

def _fetch_official_sale_templates(category_id):
 return cli.get('jdo-product-publish','/rest/sp-product/v0/categories/{categoryId}/sale-attr-templates',{'categoryId':category_id}).get('data')

def _fetch_same_shop_samples(category_id,limit=6):
 rows=[r for r in pipeline.list_products(category_id=int(category_id)) if int(r.get('productStatus') or 0) in sat.ON_SALE][:limit]
 out=[]
 for r in rows:
  body=cli.get('jdo-product-update','/rest/sp-product/v0/product-apply/{applyId}',{'applyId':str(r['productId']),'scene':'pop'}).get('data') or {}
  body['liveProductStatus']=int(r.get('productStatus') or 0);out.append(body)
 return out

def discover_sale_templates(root,reference):
 """Read official and same-shop evidence for this category's sale dimensions."""
 root=Path(root);m=read_manifest(root);verify_store(m['store']);category=int((m.get('facts') or {}).get('categoryId') or (reference.get('category') or {}).get('id') or 0)
 components=[c for c in walk_components(reference.get('schema') or {}) if c['componentCode'].startswith('sale-prop-')]
 result=sat.resolve(components,category,fetch_official=_fetch_official_sale_templates,fetch_samples=_fetch_same_shop_samples)
 result['category']=category;atomic_json(root/'sale-attr-templates.json',result)
 m['saleAttributeTemplates']={a:t['source'] for a,t in result['templates'].items()};atomic_json(root/'manifest.json',m);return result

def apply_sale_templates(root):
 """Build templateSkuProps from the user's own per-SKU values (facts.skus[].templateValues); nothing is invented."""
 root=Path(root);m=read_manifest(root);data=load(root/'sale-attr-templates.json',{}) or {};templates=data.get('templates') or {}
 if not templates:raise ValueError('No structured sale-attribute template recorded; run discover-sale-templates first')
 aliases={}
 for sku in m['facts'].get('skus') or []:
  by_attr=sku.get('templateValuesByAttr') or {}
  resolved={}
  for attr_id,template in templates.items():
   code='sale-prop-'+str(attr_id)
   values=by_attr.get(code) or (sku.get('templateValues') if len(templates)==1 else None)
   if not values:
    raise ValueError(f"SKU {sku.get('key')} 缺少 {code} 的结构化输入框取值")
   props,alias=sat.build_props(template,values)
   sku.setdefault('saleTemplateProps',{})[code]=props
   sku.setdefault('attributes',{})[code]=alias
   resolved[code]=alias
  aliases[sku['key']]=resolved
 m.pop('review',None);m.pop('imageReview',None);atomic_json(root/'manifest.json',m);return {'aliases':aliases,'source':{a:t['source'] for a,t in templates.items()}}

def sale_layout(facts,reference):
    if not isinstance(reference.get('schema'),dict) or not reference['schema']:
        raise ValueError('缺少当前类目的发品 schema，先刷新参考再核对规格')
    fields=sorted((c for c in walk_components(reference.get('schema') or {})
                   if c['componentCode'].startswith('sale-prop-')),
                  key=lambda c:int((c.get('extra') or {}).get('dim') or 1))
    names=facts.get('saleDimensions')
    if names is None:
        names=[c.get('componentTitle') or c['componentCode'] for c in fields]
    if not isinstance(names,list) or len(set(names)) != len(names):
        raise ValueError('销售维度应按真实 SKU 提供唯一名称或组件编码')
    selected=[]
    for name in names:
        matches=[c for c in fields if name in (c['componentCode'],c.get('componentTitle'))]
        if len(matches)!=1:
            raise ValueError(f'类目销售维度无法唯一匹配：{name}')
        selected.append(matches[0])
    if len({c['componentCode'] for c in selected})!=len(names):
        raise ValueError('同一销售属性组件被多次引用')
    absent=[c['componentCode'] for c in fields if c not in selected and required(c)]
    if absent:
        raise ValueError('类目必填销售维度缺失：'+','.join(absent))
    if not selected and len(facts['skus'])!=1:
        raise ValueError('无销售维度的类目只能区分一个 SKU')
    return [{**c,'componentTitle':c.get('componentTitle') or c['componentCode']} for c in fields if c in selected]


def build_listing(m,root,reference,*,planned_tasks=None):
 root=Path(root);f=m.get('facts') or {};missing=missing_information(f,reference)
 if missing:raise ValueError('Missing verified facts: '+','.join(missing))
 if planned_tasks is None:
  if not m.get('mainImages') or not m.get('detailImages') or any(i.get('previewOnly') for i in m['mainImages']):raise ValueError('Full generated main/SKU/detail materials are required')
  gate=dp.check_detail_set(m,root)
  if not gate['ok']:raise ValueError('详情页未通过发布前检查，禁止发布：'+'；'.join(gate['problems']))
 else:
  m={**m,'mainImages':[],'variants':[],'detailImages':[]}
  for task in planned_tasks:
   path=task.get('reusePhoto') or ('待生成/'+task['id']+'.jpg')
   item={'id':task['id'],'localPath':path}
   if task['role']=='main':m['mainImages'].append(item)
   elif task['role']=='detail':m['detailImages'].append(item)
   else:m['variants'].append({'key':task['skuKey'],'skuImage':item})
 if not reference.get('media',{}).get('defaultCategoryId'):
  raise ValueError('缺少当前店铺素材分类，请先刷新发品参考')
 specs = sale_layout(f,reference)
 dimensions=[c['componentTitle'] for c in specs]
 definitions={name:{'componentCode':c['componentCode'],'attrName':c['componentTitle']} for name,c in zip(('style','size'),specs)}
 key=m.get('packageId') or hashlib.sha256(json.dumps(m['store'],sort_keys=True).encode()).hexdigest()[:16]
 product={'productKey':'PN-'+key[:16],'title':f['title'],'brandId':f['brandId'],'itemNumber':'PN-'+key[:24],
          'sevenDayReturnCode':f.get('sevenDayReturnCode'),'freightTemplateId':f.get('freightTemplateId'),
          'saleDimensionCodes':[c['componentCode'] for c in specs],'includeSizeSaleAttribute':len(dimensions)>=2,'mainImageMode':'multi_set','detailMobile':True,**({'detailPolicy':dp.exemption(m)['type'],'detailExemptionReason':dp.exemption(m)['reason']} if dp.exemption(m) else {}),'saleAttributeComponents':definitions}
 for field in ('packageLengthMm','packageWidthMm','packageHeightMm','weightKg'):
  if f.get(field) not in (None,''):product[field]=f[field]
 orders={c['componentCode']:{} for c in specs}
 identical_sku_files={}
 skus=[];styles=[];sizes=[];images=[];sku_images={v['key']:v['skuImage'] for v in m['variants']}
 for i,item in enumerate(m['mainImages'],1):images.append({'imageKey':item.get('id') or f'M{i}','role':'spu_main','localPath':item['localPath'],'order':i,'mediaCategoryId':reference['media']['defaultCategoryId']})
 for i,s in enumerate(f['skus'],1):
  attributes=s.get('attributes') or {}
  sale=[]
  for index,c in enumerate(specs):
   code,name=c['componentCode'],c['componentTitle']
   alias=attributes.get(code) or attributes.get(name) or (s.get('spec') if len(specs)==1 else '')
   if not isinstance(alias,str) or not alias.strip():
    raise ValueError(f"SKU {s['key']} 缺少销售属性 {name} ({code})")
   known=orders[code]
   if alias not in known: known[alias]=len(known)+1
   mapping=hashlib.sha256((key+'|'+code+'|'+alias).encode()).hexdigest()[:32]
   entry={'componentCode':code,'name':name,'alias':alias,'order':known[alias],'mappingId':mapping,'dim':int((c.get('extra') or {}).get('dim') or index+1)}
   props=(s.get('saleTemplateProps') or {}).get(code)
   if not props and index<2:props=s.get(('styleTemplateSkuProps','sizeTemplateSkuProps')[index])
   if (c.get('extra') or {}).get('isStructure') and not props:
    raise ValueError(f"SKU {s['key']} 的结构化属性 {name} 缺少 templateSkuProps")
   if props:entry['templateSkuProps']=deepcopy(props)
   sale.append(entry)
  style=sale[0]['alias'] if sale else s['spec'];size=sale[1]['alias'] if len(sale)>1 else style
  if style not in styles:styles.append(style)
  if size not in sizes:sizes.append(size)
  skus.append({'skuKey':s['key'],'jdPrice':str(s['jdPrice']),'stock':int(s['stock']),'enabled':True,'vendorSku':s.get('vendorSku'),
               'styleAlias':style,'sizeAlias':size,'saleValues':sale,'styleMappingId':sale[0]['mappingId'] if sale else '0000000000','sizeMappingId':sale[1]['mappingId'] if len(sale)>1 else '0000000000',
               'styleOrder':styles.index(style)+1,'sizeOrder':sizes.index(size)+1,'skuAttributes':deepcopy(s['skuAttributes']),**({'styleTemplateSkuProps':deepcopy(s['styleTemplateSkuProps'])} if s.get('styleTemplateSkuProps') else {}),**({'sizeTemplateSkuProps':deepcopy(s['sizeTemplateSkuProps'])} if s.get('sizeTemplateSkuProps') else {})})
  if s['key'] not in sku_images:raise ValueError('Missing generated SKU image')
  item=sku_images[s['key']];local=item['localPath'] if isinstance(item,dict) else item
  if planned_tasks is None or not local.startswith('待生成/'):
   local=identical_sku_files.setdefault((style,sha(package_path(root,local))), local)
  images.insert(len(m['mainImages'])+i-1,{'imageKey':f'SKU-{i:02d}','skuKey':s['key'],'role':'sku_main','localPath':local,'order':1,'mediaCategoryId':reference['media']['defaultCategoryId']})
 for i,item in enumerate(m['detailImages'],1):images.append({'imageKey':item.get('id') or f'D{i}','role':'detail','localPath':item['localPath'],'order':i,'mediaCategoryId':reference['media']['defaultCategoryId']})
 listing={'category':{'id':int(f['categoryId'])},'product':product,'categoryAttributes':deepcopy(f.get('categoryAttributes') or []),'skus':skus,'images':images}
 errors,warnings=cli.validate_manifest(root/'listing.json',listing,reference,planned=planned_tasks is not None)
 if errors:raise ValueError('Local preflight failed: '+'; '.join(errors))
 return listing

def review_package(root):
 root=Path(root);m=read_manifest(root);digest=review_digest(m,root);m['review']={'digest':digest,'at':time.strftime('%Y-%m-%dT%H:%M:%S'),'confirmedByUser':False};atomic_json(root/'manifest.json',m)
 facts=m.get('facts') or {};lines=['# 发布前确认清单','',f"店铺：{m['store']['shopName']}（{m['store']['profile']} / {m['store']['venderId']}）",f"类目：{facts.get('categoryId','待确认')}",f"标题：{facts.get('title') or m['title']}",f"品牌ID：{facts.get('brandId','待确认')}",f"包装/重量：{facts.get('packageLengthMm')} × {facts.get('packageWidthMm')} × {facts.get('packageHeightMm')} mm / {facts.get('weightKg')} kg",f"运费模板：{facts.get('freightTemplateId','待确认')}",f"无理由退货代码：{facts.get('sevenDayReturnCode','待确认')}",'','|SKU|规格|京东价|库存|','|---|---|---|---|']
 for s in facts.get('skus') or []:lines.append(f"|{s['key']}|{s['spec']}|{s.get('jdPrice')}|{s.get('stock')}|")
 gate=dp.check_detail_set(m,root);details=m.get('detailImages') or []
 lines += ['','## 详情页（发布前门槛：'+('通过' if gate['ok'] else '未通过，禁止发布')+'）',f'详情页：{len(details)} 张，按本次方案核对 PC 与手机端的数量和顺序。']
 if gate.get('exemption'):lines.append(f"例外原因（{gate['exemption']['type']}）：{gate['exemption']['reason']}")
 for i,d in enumerate(details,1):lines.append(f"{i}. {d.get('id')}｜{dp.KIND_TITLES.get(d.get('module'),d.get('module') or '')}｜SKU：{','.join(d.get('skuKeys') or []) or '通用'}")
 lines += [f'- 问题：{p}' for p in gate['problems']]
 if details:
  overview=dp.overview_image([package_path(root,d['localPath']) for d in details],root/'详情图'/'详情页总览.jpg');lines += ['',f"![详情页总览]({overview.relative_to(root).as_posix()})（仅预览，不上传）"]
 lines += ['','## 图片预览']
 for item in media_entries(m):lines.append(f"![图片]({item['localPath']})")
 lines += ['',f'确认摘要：`{digest}`','宿主质检或商家亲审按实际审核人记录。发布采用本次商家的经营授权；预览变化时重新核验图片。']
 (root/'确认清单.md').write_text('\n'.join(lines),encoding='utf-8')
 page='<html><meta charset="utf-8"><title>实拍上新预览</title><style>body{font:16px sans-serif;padding:24px}img{max-width:450px;margin:8px;vertical-align:top}pre{white-space:pre-wrap}</style><h1>实拍上新预览（尚未发布）</h1><pre>'+html.escape('\n'.join(lines[:15]))+'</pre><h2>详情页：'+str(len(details))+' 张</h2><pre>'+html.escape('\n'.join(l for l in lines if l.startswith('例外') or l.startswith('- 问题') or l[:1].isdigit()))+'</pre>'+('<img src="详情图/详情页总览.jpg" style="max-width:100%">' if details else '')
 for item in media_entries(m):page+='<figure><img src="'+html.escape(item['localPath'],quote=True)+'"><figcaption>'+html.escape(item['localPath'])+'</figcaption></figure>'
 (root/'preview.html').write_text(page+'</html>',encoding='utf-8')
 result={'digest':digest,'checklist':str(root/'确认清单.md'),'preview':str(root/'preview.html'),'detailCount':len(details),'detailGate':gate['ok'],'detailProblems':gate['problems']}
 if m.get('sampleOf'):
  try:
   result['sampleReview']=sample_review(root,m)
  except (OSError, ValueError, KeyError, TypeError) as error:
   # The review page and original sample remain usable when only a comparison is unavailable.
   result['sampleReview']={'status':'comparison-unverified','comparisonOrigin':{'kind':'unknown','status':'unverified'},
                           'reason':str(error)[:240]}
   entries=list(media_entries(m))
   if len(entries)==1:
    local=package_path(root,entries[0]['localPath'])
    if local.is_file() and sha(local)==entries[0].get('sha256'):
     result['sampleReview']['sample']=str(local)
 return result


def sample_review(root, manifest):
    from heideng_merchant.sample_comparison import write_comparison
    plan = load(root/'plan.json', [])
    media = list(media_entries(manifest))
    if len(plan) != 1 or len(media) != 1 or media[0]['id'] != plan[0]['id']:
        return {'status': 'sample-pending'}
    task = plan[0]
    new = package_path(root, media[0]['localPath'])
    reference = task.get('firstImageReference')
    result = {'sample': str(new), 'skuKey': task.get('skuKey'), 'sourceSkuId': task.get('sourceSkuId'),
              'identityChecks': task.get('identityChecks'), 'consumerPageStatus': task.get('consumerPageStatus','unchecked')}
    before = load(root/'.comparison/before.json',{}) or {}
    if task.get('comparisonPhoto'):
        relative = task['comparisonPhoto']
        before = {'kind':'merchant-provided','label':'本任务指定的商品参考图','beforeFile':relative,
                  'beforeSha256':sha(package_path(root,relative))}
    elif before:
        from heideng_merchant.sample_delivery import target_sku
        parent_dir = root.parent.parent
        parent = read_manifest(parent_dir)
        if manifest['sampleOf']['packageId'] != parent['packageId'] or manifest['store'] != parent['store']:
            raise ValueError('样张与原商品任务不一致')
        target = target_sku(parent_dir,parent,task.get('skuKey'))
        if (target.get('productId'),target.get('skuId')) != (before.get('productId'),before.get('skuId')):
            raise ValueError('规格原图回执和本次样张目标不匹配')
    elif reference:
        ref = manifest.get('reference') or {}
        evidence = load(package_path(root,ref.get('cacheManifest') or '.reference-cache/assets.json'),{}) or {}
        asset = next((a for a in evidence.get('entries',[])
                      if reference in (a.get('productPhoto'),a.get('path'))),None)
        old = package_path(root,reference)
        if not asset or asset.get('sha256') != sha(old):
            return {**result,'comparisonOrigin':{'kind':'unknown','status':'unverified'}}
        sid = task.get('sourceSkuId') or evidence.get('sourceSkuId')
        before = {'kind':'source-sku' if sid else 'source-product', 'skuId':str(sid) if sid else None,
                  'productId':str(evidence.get('sourceSpuId') or '') or None, 'imageUrl':asset.get('sourceUrl'),
                  'beforeFile':reference,'beforeSha256':sha(old),
                  'label':'复刻来源规格实开记录中的首图' if result['consumerPageStatus']=='host-observed' else '复刻来源商品后台首图候选'}
    if before:
        result.update(write_comparison(root,new,before))
    return result

def check_review(root,digest):
 m=read_manifest(root)
 if not digest or (m.get('review') or {}).get('digest')!=digest or review_digest(m,root)!=digest:raise ValueError('Review changed or missing; show current preview and ask user confirmation')
 return m

def accept_images(root,digest,*,confirm,reviewer='host',evidence=None):
 if confirm!='PHOTOS_REVIEWED':raise ValueError('Only after user preview acceptance: --confirm PHOTOS_REVIEWED')
 if reviewer not in ('host','merchant') or (reviewer=='merchant' and not str(evidence or '').strip()):raise ValueError('商家亲审需要关联本次预览的明确答复')
 root=Path(root);m=check_review(root,digest)
 if m.get('deferredUnits'):
  raise ValueError('整套发布还缺这些图片，请继续完成或复用：'+'、'.join(m['deferredUnits']))
 if m.get('qualityProblems'):raise ValueError('Known image identity/text issues must be fixed and reviewed first')
 gate=dp.check_detail_set(m,root)
 if not gate['ok']:raise ValueError('详情页未通过发布前检查，先补生成：'+'；'.join(gate['problems']))
 m['imageReview']={'ok':True,'digest':digest,'by':'USER_CONFIRMED' if reviewer=='merchant' else 'HOST_REVIEWED','evidence':evidence,'at':time.strftime('%Y-%m-%dT%H:%M:%S')}
 atomic_json(root/'manifest.json',m);return m['imageReview']

@contextmanager
def package_lock(root,name):
 lock=Path(root)/name
 try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
 except FileExistsError:raise ReconcileRequired('Another operation owns this package; inspect before recovery')
 try:yield
 finally:lock.unlink(missing_ok=True)

def prepare_package(root,reference,*,confirm,digest):
 if confirm!='PREPARE_PHOTO_LISTING':raise ValueError('Explicit reviewed-image preparation confirmation is required')
 with package_lock(root,'.prepare.lock'):
  return _prepare_package(root,reference,confirm=confirm,digest=digest)

def _prepare_package(root,reference,*,confirm,digest):
 if confirm!='PREPARE_PHOTO_LISTING':raise ValueError('Image upload and platform validation require --confirm PREPARE_PHOTO_LISTING after preview')
 root=Path(root);m=check_review(root,digest)
 if not (m.get('imageReview') or {}).get('ok') or m['imageReview'].get('digest')!=digest or m.get('qualityProblems'):raise ValueError('Current image quality review is required before preparation')
 if m.get('productId') or load(root/'state.json',{}).get('status') in ('SUBMITTING','UNKNOWN','SUCCEEDED'):raise ReconcileRequired('Reconcile the existing submission first')
 listing=build_listing(m,root,reference);verify_store(m['store']);began=time.monotonic();runtime=root/'.publish';runtime.mkdir(exist_ok=True)
 ledger_path=runtime/'uploads.json';uploads=load(ledger_path,{}) or {};zone=reference['media']['zoneId'];cat=reference['media']['defaultCategoryId']
 for image in listing['images']:
  file=package_path(root,image['localPath']);hash_=sha(file);record=uploads.get(hash_) or {}
  if not record.get('imgUrl'):
   if record.get('status') in ('SUBMITTING','UNKNOWN'):raise ReconcileRequired('An image upload outcome is unknown; reconcile in the image zone first')
   uploads[hash_]={'status':'SUBMITTING','sha256':hash_,'localPath':image['localPath']};atomic_json(ledger_path,uploads)
   snapshot=runtime/'upload-snapshots'/f'{hash_}.jpg';snapshot.parent.mkdir(exist_ok=True);shutil.copy2(file,snapshot)
   if sha(snapshot)!=hash_ or sha(file)!=hash_:raise ValueError('Image changed during preparation; review it again')
   try:result=cli.upload(zone,cat,snapshot)
   except Exception:
    uploads[hash_]['status']='UNKNOWN';atomic_json(ledger_path,uploads);raise ReconcileRequired('Image upload outcome unknown; never replay automatically') from None
   url=result.get('imgUrl') or result.get('imageUrl')
   if not url:raise ReconcileRequired('Image upload has no returned URL')
   record={'status':'SUCCEEDED','imgUrl':url,'sha256':hash_};uploads[hash_]=record;atomic_json(ledger_path,uploads)
  image['upload']={'imgUrl':record['imgUrl'],'status':'uploaded'}
 check_review(root,digest)
 atomic_json(root/'listing.json',listing);paths=cli.write_publish_payloads(root/'listing.json',runtime)
 response=cli.run_jdo_large(url='/rest/sp-product/v0/product-schemas/validations',method='POST',body_path=Path(paths['paths']['validation']),skill_id='jdo-product-publish',yes=True)
 atomic_json(runtime/'validation-response.json',response)
 if not isinstance(response,dict) or response.get('success') is not True:
  raise ReconcileRequired('平台校验未返回明确成功回执，请核对原校验记录')
 strong=[v for v in pipeline.validation_violations(response) if int(v.get('detectResult') or 0)==1]
 if strong:raise ValueError('Platform validation rejected the listing; review violations in validation-response.json')
 for item in media_entries(m):
  raw=uploads[sha(package_path(root,item['localPath']))]['imgUrl'];item['imgUrl']=raw;item['onlineUrl']=cli.detail_image_url(raw)
 m['title']=m['facts']['title'];m['category']={'id':int(m['facts']['categoryId'])};m['sellingPoints']=m['facts'].get('sellingPoints') or []
 contract={'reviewDigest':digest,'bodySha256':sha(runtime/'publish-body.json'),'listingSha256':sha(root/'listing.json'),'itemNumber':listing['product']['itemNumber']}
 atomic_json(runtime/'prepared.json',contract);m['status']='PREPARED_AWAITING_CONFIRMATION';m['timings']['prepareSeconds']=round(time.monotonic()-began,2)
 by_key={s['skuKey']:s for s in listing['skus']}
 for v in m['variants']:
  s=by_key[v['key']];v.update({'spec':s['styleAlias'],'vendorSku':s['vendorSku'],'jdPrice':s['jdPrice'],'stock':s['stock']})
 atomic_json(root/'manifest.json',m);return {'status':m['status'],'reviewDigest':digest,'prepared':contract,'published':False}

def publish_package(root,*,confirm,digest):
 if confirm!='PUBLISH_TO_JD':raise ValueError('Explicit user confirmation PUBLISH_TO_JD is required')
 root=Path(root);m=check_review(root,digest);runtime=root/'.publish';prepared=load(runtime/'prepared.json')
 if not prepared or prepared.get('reviewDigest')!=digest or sha(runtime/'publish-body.json')!=prepared['bodySha256'] or sha(root/'listing.json')!=prepared['listingSha256']:raise ValueError('Prepared payload no longer matches reviewed materials')
 state_path=root/'state.json';state=load(state_path,{}) or {}
 if m.get('productId') or state.get('status') in ('SUBMITTING','UNKNOWN','SUCCEEDED','REJECTED'):return reconcile_package(root)
 verify_store(m['store']);existing=pipeline.find_existing_product(prepared['itemNumber'])
 if existing:
  atomic_json(state_path,{'status':'SUBMITTING','itemNumber':prepared['itemNumber'],'productId':int(existing['productId'])});return reconcile_package(root)
 lock_path=root/'.publish.lock'
 try:fd=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
 except FileExistsError:raise ReconcileRequired('Another publish process owns this package')
 began=time.monotonic()
 try:
  latest=load(state_path,{}) or {}
  if latest.get('status') in ('SUBMITTING','UNKNOWN','SUCCEEDED','REJECTED') or read_manifest(root).get('productId'):return reconcile_package(root)
  check_review(root,digest)
  atomic_json(state_path,{'status':'SUBMITTING','itemNumber':prepared['itemNumber'],'bodySha256':prepared['bodySha256']})
  try:response=cli.run_jdo_large(url='/rest/sp-product/v0/product-applies',method='POST',body_path=runtime/'publish-body.json',skill_id='jdo-product-publish',yes=True)
  except cli.JdoError as e:
   code=re.match(r'\s*(\d{6,})',str(e))
   if code:  # the platform answered with an error code: an explicit refusal, not a lost response
    reason=str(e)[:600];record={'status':'REJECTED','itemNumber':prepared['itemNumber'],'bodySha256':prepared['bodySha256'],'reason':reason,'at':time.strftime('%Y-%m-%dT%H:%M:%S')}
    atomic_json(state_path,record);atomic_json(runtime/'rejection.json',record)
    raise ReconcileRequired('Platform explicitly rejected the submission ('+reason[:200]+'); fix the cause, then run confirm-not-created (read-only remote check) before any new submission') from None
   atomic_json(state_path,{'status':'UNKNOWN','itemNumber':prepared['itemNumber'],'bodySha256':prepared['bodySha256']});raise ReconcileRequired('Product submission outcome unknown; query by technical item number') from None
  except Exception:
   atomic_json(state_path,{'status':'UNKNOWN','itemNumber':prepared['itemNumber'],'bodySha256':prepared['bodySha256']});raise ReconcileRequired('Product submission outcome unknown; query by technical item number') from None
  atomic_json(runtime/'publish-response.json',response);data=response.get('data') or {}
  if not data.get('productId'):raise ReconcileRequired('No product ID returned; reconcile by item number before any retry')
  m['productId']=int(data['productId']);m['applyId']=str(data.get('applyId') or data['productId']);m['status']='PUBLISHED_UNVERIFIED';m['timings']['publishSeconds']=round(time.monotonic()-began,2)
  atomic_json(root/'manifest.json',m);atomic_json(state_path,{'status':'SUCCEEDED','itemNumber':prepared['itemNumber'],'productId':m['productId'],'bodySha256':prepared['bodySha256']});return verify_package(root)
 finally:lock_path.unlink(missing_ok=True)

def confirm_not_created(root,*,reason):
 """Read-only proof that nothing was created, required before re-submitting after REJECTED/UNKNOWN."""
 root=Path(root);m=read_manifest(root);state_path=root/'state.json';state=load(state_path,{}) or {}
 if state.get('status') not in ('UNKNOWN','REJECTED'):raise ValueError('Only an UNKNOWN or REJECTED submission needs this check')
 if not str(reason or '').strip():raise ValueError('Write why the previous submission failed (platform text or cause)')
 verify_store(m['store']);prepared=load(root/'.publish/prepared.json',{}) or {}
 item=state.get('itemNumber') or prepared.get('itemNumber') or ''
 by_item=[existing for existing in [pipeline.find_existing_product(item)] if existing] if item else []
 title=(m.get('facts') or {}).get('title') or m['title']
 same_title=[] if by_item else [r for r in pipeline.list_products() if r.get('productName')==title]  # an itemNumber hit already settles it
 matches=[{'productId':r['productId'],'itemNum':r.get('itemNum'),'by':'itemNumber'} for r in by_item]+[{'productId':r['productId'],'itemNum':r.get('itemNum'),'by':'title'} for r in same_title if r['productId'] not in {x['productId'] for x in by_item}]
 evidence={'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%S'),'itemNumber':item,'title':title,'matches':matches,'previousStatus':state.get('status'),'previousReason':state.get('reason'),'userReason':str(reason)[:400]}
 atomic_json(root/'.publish'/'no-product-evidence.json',evidence)
 if matches:raise ReconcileRequired('A matching remote product exists ('+str(matches[0]['productId'])+'); adopt it with reconcile instead of re-submitting')
 atomic_json(state_path,{'status':'REJECTED_CONFIRMED','itemNumber':item,'confirmedAt':evidence['checkedAt'],'reason':evidence['userReason']});return evidence

def reconcile_package(root):
 root=Path(root);m=read_manifest(root);verify_store(m['store']);state=load(root/'state.json',{}) or {};prepared=load(root/'.publish/prepared.json',{}) or {}
 pid=m.get('productId') or state.get('productId')
 if not pid:
  existing=pipeline.find_existing_product(state.get('itemNumber') or prepared.get('itemNumber') or '')
  if not existing:raise ReconcileRequired('No matching remote product yet; still unknown, do not resubmit')
  pid=int(existing['productId'])
 m['productId']=int(pid);m['status']='PUBLISHED_UNVERIFIED';atomic_json(root/'manifest.json',m);return verify_package(root)

def verify_package(root,attempts=18,interval=10):
 root=Path(root);m=read_manifest(root)
 if not m.get('productId'):raise ValueError('No published product ID; use reconcile')
 verify_store(m['store']);listing=load(root/'listing.json');pid=int(m['productId']);began=time.monotonic();detail={};apply={}
 for n in range(attempts):
  try:
   apply=cli.get('jdo-product-update','/rest/sp-product/v0/product-apply/{applyId}',{'applyId':str(pid),'scene':'pop'}).get('data') or {}
   if int((apply.get('applyInfo') or {}).get('draftComputeStatus') or 0)==3:
    m['status']='PRODUCT_APPLY_REJECTED';atomic_json(root/'manifest.json',m);raise ValueError('Platform rejected product application')
   detail=cli.get('jdo-product-status','/rest/sp-product/v0/products/{productId}',{'productId':pid,'scene':'pop'}).get('data') or {}
   if detail.get('skuList') and int((apply.get('applyInfo') or {}).get('draftComputeStatus') or 0)!=1:break
  except cli.JdoError as e:
   if '未查询到商品信息' not in str(e):raise
  if n+1<attempts:time.sleep(interval)
 else:raise ReconcileRequired('Product propagation pending; only retry readback')
 atomic_json(root/'.publish/readback-apply.json',apply);atomic_json(root/'.publish/readback-product.json',detail)
 online,problems=match_published_variants(listing,detail['skuList'])
 from image_patch_update import group_urls
 groups=group_urls(apply)
 if (detail.get('productInfo') or {}).get('productName')!=listing['product']['title']:problems.append('title mismatch')
 if int(((detail.get('productInfo') or {}).get('productStatus') or {}).get('productStatusNew') or 0) not in ON_SALE_STATUSES:problems.append('product not on sale')
 expected_main=[i['upload']['imgUrl'] for i in listing['images'] if i['role']=='spu_main']
 if groups.get('0000000000')!=expected_main:problems.append('SPU main image order mismatch')
 from heideng_merchant.sku_image_edit import pictures
 try:spec_images=pictures(detail,pid)
 except ValueError:
  spec_images={}
  problems.append('SKU image ownership not verified')
 stocks={str(s.get('skuId')):s for s in cli.query_sku_stocks([int(s['skuId']) for s in detail['skuList']])}
 for sku in listing['skus']:
  key=sku['skuKey']
  remote=online.get(key)
  if not remote:continue
  if sku.get('vendorSku') is not None and (remote.get('outerId') is None or str(remote['outerId'])!=str(sku['vendorSku'])):
   problems.append('merchant code '+key)
  value=(remote.get('priceInfo') or {}).get('jdPrice')
  if value is None or float(value)!=float(sku['jdPrice']):problems.append('price '+key)
  if int(remote.get('skuEnableStatus') or 0)!=1:problems.append('disabled SKU '+key)
  status=remote.get('skuStats') if 'skuStats' in remote else remote.get('skuStatus')
  if int((status or {}).get('onOffShelfStatus') or 0)!=1:problems.append('SKU not on shelf '+key)
  stock=stocks.get(str(remote['skuId'])) or {}
  actual_stock=stock.get('stockNum')
  if actual_stock is None or int(actual_stock)!=int(sku['stock']):problems.append('stock '+key)
  sale=remote.get('saleAttrs') or [];actual_aliases=[s.get('attrValueAlias') for s in sale]
  wanted=cli.expected_sale_aliases(listing['product'],sku)
  if 'saleValues' in sku:
   by_code={str(a.get('attrId')):a.get('attrValueAlias') for a in sale}
   actual_aliases=[by_code.get(v['componentCode'].removeprefix('sale-prop-')) for v in sku['saleValues']] if len(sale)==len(wanted) else None
  if actual_aliases!=wanted:problems.append('sale specifications '+key)
  sku_urls=[i['upload']['imgUrl'] for i in listing['images'] if i['role']=='sku_main' and i['skuKey']==sku['skuKey']]+expected_main[1:]
  if wanted:
   first=sale[0] if sale else {}
   if sku.get('saleValues'):
    attr_id=sku['saleValues'][0]['componentCode'].removeprefix('sale-prop-')
    first=next((a for a in sale if str(a.get('attrId'))==attr_id),{})
   if groups.get(str(first.get('attrValues'))) != sku_urls:problems.append('SKU gallery '+key)
  if not sku_urls or spec_images.get(str(remote['skuId']))!=sku_urls[0]:problems.append('SKU image '+key)
  for v in m['variants']:
   if v.get('key')==key:v['skuId']=int(remote['skuId'])
 details=[cli.detail_image_url(i['upload']['imgUrl']) for i in listing['images'] if i['role']=='detail']
 for d,url in zip(m.get('detailImages') or [],details):d['onlineUrl']=url
 readback=dp.readback_detail((apply.get('productInfo') or {}).get('productDetailDesc') or {},details);detail_problems=list(readback['problems'])
 local_gate=dp.check_detail_set(m,root)
 if not local_gate['ok']:detail_problems += ['local detail gate: '+x for x in local_gate['problems']]
 problems += ['detail '+x for x in detail_problems]
 validation=load(root/'.publish/validation-response.json')
 validated=(isinstance(validation,dict) and validation.get('success') is True and
            not any(int(v.get('detectResult') or 0)==1 for v in pipeline.validation_violations(validation)))
 if not validated:problems.append('平台发品校验缺少成功回执')
 m['detailPlan']={'moduleCount':len(m.get('detailImages') or []),'width':dp.OUTPUT_WIDTH,'exemption':local_gate.get('exemption'),'readback':{k:v for k,v in readback.items() if k!='problems'},'modules':[{'id':d.get('id'),'kind':d.get('module'),'localPath':d.get('localPath'),'skuKeys':d.get('skuKeys') or [],'onlineUrl':d.get('onlineUrl') or ''} for d in m.get('detailImages') or []]}
 m['deliveryChecks']={'platformValidationPassed':validated,'productOnSale':'product not on sale' not in problems and not any(x.startswith(('SKU not on shelf','disabled SKU')) for x in problems),'detailQualityPassed':not detail_problems,'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%S')}
 m['deliveryChecks']=dp.delivery_checks(m);m['deliveryChecks']['statement']=dp.completion_statement(m['deliveryChecks'])
 if problems:m['deliveryChecks']['statement']='已提交，交付待核对：'+'、'.join(problems)
 m['skuIds']=[int(s['skuId']) for s in detail['skuList']];m['status']='VERIFIED' if not problems else 'VERIFICATION_FAILED';m['timings']['verifySeconds']=round(time.monotonic()-began,2);m['verification']={'problems':problems,'skuCount':len(online),'at':time.strftime('%Y-%m-%dT%H:%M:%S')}
 links=consumer_links(online.values())
 m['consumerLinks']=links
 m['verification'].update(consumerLinks=links,consumerPageStatus='unchecked')
 atomic_json(root/'manifest.json',m)
 atomic_json(root/'.publish/verification.json',m['verification'])
 return {'status':m['status'],'productId':pid,'skuIds':m['skuIds'],'consumerLinks':links,
         'representativeLink':links[0]['url'] if links else None, 'consumerPageStatus':'unchecked',
         'problems':problems,'deliveryChecks':dp.delivery_checks(m),'statement':m['deliveryChecks']['statement']}


def match_published_variants(listing, remote_rows):
    """Match on the complete set of sale dimensions before checking merchant codes."""
    product = listing['product']
    definitions = product.get('saleAttributeComponents') or {}
    legacy_codes = [definitions[key]['componentCode'] for key in ('style', 'size') if key in definitions]
    by_spec = {}
    problems = []
    sku_ids = set()
    for row in remote_rows:
        attrs = row.get('saleAttrs')
        sku_id = str(row.get('skuId') or '')
        if not isinstance(attrs, list) or not sku_id.isdecimal() or sku_id in sku_ids:
            problems.append('missing or duplicate SKU identity')
            continue
        sku_ids.add(sku_id)
        spec = tuple(sorted((str(a.get('attrId')), str(a.get('attrValueAlias'))) for a in attrs))
        by_spec.setdefault(spec, []).append(row)
    result = {}
    local_specs = set()
    for sku in listing['skus']:
        if 'saleValues' in sku:
            fields = [(v['componentCode'], v['alias']) for v in sku['saleValues']]
        else:
            fields = list(zip(legacy_codes, cli.expected_sale_aliases(product, sku), strict=True))
        spec = tuple(sorted((code.removeprefix('sale-prop-'), str(value)) for code,value in fields))
        if spec in local_specs or len(by_spec.get(spec, [])) != 1:
            problems.append('ambiguous or missing sale specifications '+sku['skuKey'])
        else:
            result[sku['skuKey']] = by_spec[spec][0]
        local_specs.add(spec)
    if len(remote_rows) != len(listing['skus']) or set(by_spec) != local_specs:
        problems.append('SKU specification set mismatch')
    return result, problems


def consumer_links(skus, expected=None):
    links = []
    for sku in skus:
        sku_id = str(sku.get('skuId') or '')
        if not sku_id.isdecimal() or (expected is not None and str(sku.get('outerId')) not in expected):
            continue
        aliases = [attr.get('attrValueAlias') for attr in sku.get('saleAttrs') or []]
        links.append({'skuId': int(sku_id), 'spec': ' / '.join(x for x in aliases if x),
                      'jdPrice': (sku.get('priceInfo') or {}).get('jdPrice'),
                      'url': f'https://item.jd.com/{sku_id}.html'})
    return links


def main(argv=None):
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 init=sub.add_parser('init');init.add_argument('--package',required=True,type=Path);init.add_argument('--shop',required=True);init.add_argument('--photos',nargs='+',default=[],type=Path);init.add_argument('--title',required=True)
 choice=init.add_mutually_exclusive_group(required=True);choice.add_argument('--reference');choice.add_argument('--source-spu',type=int);choice.add_argument('--no-reference',action='store_true')
 view=sub.add_parser('record-first-view');view.add_argument('--package',required=True,type=Path)
 view.add_argument('--source-sku',required=True);view.add_argument('--url',required=True)
 view.add_argument('--product-photo',required=True);view.add_argument('--screenshot',required=True,type=Path)
 recovery=sub.add_parser('recover-sample-comparison',help='从目标 SKU 的原回读核对旧样张对比来源，仅补本机对比回执')
 recovery.add_argument('--package',required=True,type=Path);recovery.add_argument('--image-id',required=True)
 recovery.add_argument('--detail-receipt',type=Path)
 for name in ('make-sample','accept-sample','sample-context'):
  sample=sub.add_parser(name);sample.add_argument('--package',required=True,type=Path);sample.add_argument('--image-id',required=True)
  if name=='make-sample':sample.add_argument('--image-prompts-file',required=True,type=Path)
  elif name=='accept-sample':sample.add_argument('--evidence',required=True)
 recover_images=sub.add_parser('reconcile-images',help='只读核对原生图回执、预算预占及本地产物')
 recover_images.add_argument('--package',required=True,type=Path)
 recover_images.add_argument('--units',nargs='+',help='只核对这些图号，取得对应范围的追加报价')
 for name in ('refresh','reference','set-facts','questions','make-plan','generate','review','accept-images','prepare','publish','verify','reconcile','confirm-not-created','discover-sale-templates','apply-sale-templates'):
  p=sub.add_parser(name);p.add_argument('--package',required=True,type=Path)
  if name=='refresh':p.add_argument('--category-id',type=int,required=True);p.add_argument('--category-name',default='');p.add_argument('--brand-category-id',type=int)
  if name=='confirm-not-created':p.add_argument('--reason',required=True)
  if name=='set-facts':p.add_argument('--facts',required=True,type=Path);p.add_argument('--style',type=Path)
  if name=='make-plan':p.add_argument('--preview',action='store_true');p.add_argument('--only',choices=['detail'],help='只重做详情模块（已有主图/SKU图不变）')
  if name=='make-plan':p.add_argument('--image-prompts-file',type=Path,required=True);p.add_argument('--redo',nargs='*',default=[])
  if name=='generate':p.add_argument('--redo',nargs='*',default=[]);p.add_argument('--approval-file','--fee-approval-file',type=Path)
  if name=='generate':p.add_argument('--replace-unknown',nargs='+',default=[],help='对已核对的未知请求另行批准并追加一次尝试')
  if name=='accept-images':p.add_argument('--reviewer',choices=['host','merchant'],default='host');p.add_argument('--evidence')
  if name in ('prepare','publish','accept-images'):p.add_argument('--confirm',required=True);p.add_argument('--review-digest',required=True)
 args=parser.parse_args(argv);root=args.package.resolve();command=args.command;command_began=time.monotonic()
 try:
  if command=='init':
   shop=args.shop
   if shop.lower().endswith('.lnk'):
    link=Path(shop)
    if not link.is_file():raise ValueError('The exact shop shortcut is missing')
    shop=link.stem.removeprefix('京麦-')
   store=ensure_shop(shop)
   if args.source_spu:
    result=create_from_same_shop(root,store,args.source_spu,args.title,args.photos)
   else:
    result=create_package(root,store,args.photos,args.title,args.reference,True)
  elif command=='record-first-view':result=record_first_view(root,args.source_sku,args.url,args.product_photo,args.screenshot)
  elif command=='sample-context':result=photo_samples.accepted_context(root,args.image_id,read_manifest)
  elif command=='make-sample':result=make_sample(root,load(args.image_prompts_file),args.image_id)
  elif command=='recover-sample-comparison':result=recover_sample_comparison(root,args.image_id,args.detail_receipt)
  elif command=='accept-sample':result=accept_sample(root,args.image_id,args.evidence)
  elif command=='refresh':
   m=read_manifest(root);verify_store(m['store']);r=cli.refresh_reference(root/'reference.json',args.category_id,args.category_name,args.brand_category_id);r['store']=m['store'];atomic_json(root/'reference.json',r)
   result={'category':r['category'],'brandlessAllowed':any(str(b.get('brandId'))=='-1' for b in r['brands'])}
  elif command=='reference':result=collect_reference(root)
  elif command=='set-facts':
   m=read_manifest(root);f=load(args.facts);reject_credentials(f)
   if not isinstance(f,dict):raise ValueError('Facts must be a JSON object')
   m['facts']=f;m['title']=f.get('title') or m['title'];m['sellingPoints']=f.get('sellingPoints') or [];m.pop('review',None)
   if args.style:
    style=load(args.style);reject_credentials(style);m['reference']['styleSummary']=str(style.get('styleSummary') or '')
   atomic_json(root/'manifest.json',m);result={'missing':missing_information(f,load(root/'reference.json',{}))}
  elif command=='questions':
   m=read_manifest(root);reference=load(root/'reference.json',{});missing=missing_information(m.get('facts') or {},reference)
   structured=load(root/'sale-attr-templates.json',{}) or {};missing=missing+(['sale-attribute-template:'+m_['attrName'] for m_ in structured.get('missing') or []])
   question={'missingFields':missing,**({'templateNextAction':structured['ask']} if structured.get('ask') else {}),
             'rule':'从本商品已有资料、销售属性原值和当前店铺模板查缺项。只有仍缺的实物事实或经营选择需要商家一次补充。'}
   atomic_json(root/'missing-information.json',question);result=question
  elif command=='make-plan':
   r=make_plan(root,preview=args.preview,only=args.only,design=load(args.image_prompts_file),redo=args.redo);result={**r,'tasks':len(r['tasks'])}
  elif command=='generate':
   result=generate_plan(root,redo=args.redo,approval=load(args.approval_file) if args.approval_file else None,replace_unknown=args.replace_unknown);review_package(root);result={k:v for k,v in result.items() if k!='ledger'}
  elif command=='reconcile-images':
   from photo_generation import generation_scope, inspect_attempts
   plan=load(root/'plan.json',[])
   result=inspect_attempts(plan,root/'.generation',generation_scope(read_manifest(root),plan,root),args.units)
  elif command=='review':result=review_package(root)
  elif command=='accept-images':result=accept_images(root,args.review_digest,confirm=args.confirm,reviewer=args.reviewer,evidence=args.evidence)
  elif command=='prepare':result=prepare_package(root,load(root/'reference.json'),confirm=args.confirm,digest=args.review_digest)
  elif command=='publish':result=publish_package(root,confirm=args.confirm,digest=args.review_digest)
  elif command=='discover-sale-templates':result=discover_sale_templates(root,load(root/'reference.json',{}))
  elif command=='apply-sale-templates':result=apply_sale_templates(root)
  elif command=='confirm-not-created':result=confirm_not_created(root,reason=args.reason)
  elif command=='verify':result=verify_package(root)
  else:result=reconcile_package(root)
  if command!='reconcile-images' and (root/'manifest.json').is_file():
   current=read_manifest(root);current.setdefault('timings',{})[command+'CommandSeconds']=round(time.monotonic()-command_began,2);atomic_json(root/'manifest.json',current)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (ValueError,GenerationUnknown,ReconcileRequired,cli.JdoError,MoverError,OSError) as e:
  print(json.dumps({'ok':False,'type':type(e).__name__,'message':str(e)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
