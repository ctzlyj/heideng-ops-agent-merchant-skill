"""Freeze the merchant's physical first-image slots and their distinct creative assets."""
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from .pop_gallery import PUBLIC_GROUP, gallery_owners, gallery_readback, snapshot
from .refresh_storage import file_sha, read_json, configure_design


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def same_shop(expected, other):
    if not all(expected.get(k) and str(expected[k]) == str(other.get(k, ''))
               for k in ('profile', 'venderId', 'shopName')):
        raise ValueError('主图批次必须使用原店铺、商家及 Profile')
    if expected.get('shopId') and str(expected['shopId']) != str(other.get('shopId', '')):
        raise ValueError('主图批次店铺编号不一致')


def identifiers(values):
    parts = [str(item).strip() for item in values]
    if any(not s.isascii() or not s.isdecimal() or int(s) <= 0 for s in parts) or len(parts) != len(set(parts)):
        raise ValueError('商品或 SKU 范围需要唯一的有效编号')
    return parts


def copy_targets(report, excluded, shop):
    excluded=set(excluded)|set(report.get('excludedSourceProductIds',[]))
    if report.get('status') != 'batch-status':
        raise ValueError('请使用 shop-copy batch-status 的原批次报告')
    same_shop(shop, report.get('targetShop') or {})
    by_target, skipped, sources = {}, [], set()
    for row in report['rows']:
        source = str(row['sourceProductId'])
        sources.add(source)
        target = str(row.get('targetProductId') or '')
        evidence = row.get('comparison') or {}
        if source in excluded:
            reason = 'excluded-source'
        elif (not target or row.get('status') == 'mapping-conflict' or
              evidence.get('readbackView') != 'product' or evidence.get('auditState') in ('pending', 'rejected')):
            reason = 'target-product-unconfirmed'
        else:
            if target in by_target:
                raise ValueError('多个来源映射到同一目标商品，无法确定授权范围')
            by_target[target] = source
            continue
        skipped.append({'sourceProductId': source, 'targetProductId': target, 'reason': reason})
    if not excluded <= sources:
        raise ValueError('排除的来源商品不属于搬家批次')
    if set(by_target) & {r['targetProductId'] for r in skipped if r['targetProductId']}:
        raise ValueError('已排除或未核实的来源与目标商品映射冲突')
    return by_target, skipped


def configure(job, args):
    mode = args.main_selection
    supplied = (args.sku_id or args.from_main_run or args.copy_batch_report or args.exclude_source_product
                or args.max_images is not None or args.approved_sample)
    if not mode:
        if supplied:
            raise ValueError('请选择本次首图范围 --main-selection')
        design = configure_design(job, args)
        if design:
            job['imageDesign'] = design
        return
    if args.scope not in ('main', None) or job['mainPositions'] not in ([], [1]):
        raise ValueError('首图选择仅适用于主图第 1 位')
    if (mode == 'sku') != bool(args.sku_id) or (mode == 'remaining-colors') != bool(args.from_main_run):
        raise ValueError('指定 SKU 需要 --sku-id，其余颜色组需要 --from-main-run')
    if args.max_images is not None and args.max_images < 0:
        raise ValueError('张数上限不能小于零')
    chosen = identifiers(job['productIds'])
    excluded = set(identifiers(args.exclude_source_product))
    spec = {'mode': mode, 'skuIds': identifiers(args.sku_id), 'maxImages': args.max_images,
            'sourceByProduct': {}, 'exclusions': []}
    if args.copy_batch_report:
        report = read_json(args.copy_batch_report)
        by_target, skipped = copy_targets(report, excluded, job)
        if chosen and not set(chosen) <= set(by_target):
            raise ValueError('所选目标超出已核对的搬家范围')
        chosen = chosen or list(by_target)
        spec.update(sourceByProduct={p: by_target[p] for p in chosen}, exclusions=skipped,
                    copyBatchId=report.get('batchId'))
        if (report.get('targetShop') or {}).get('shopId'):
            job['shopId'] = report['targetShop']['shopId']
    elif excluded and not args.from_main_run:
        raise ValueError('按来源排除需要原搬家批次与目标商品映射')
    if args.from_main_run:
        parent = args.from_main_run.resolve()
        old_job = read_json(parent / 'job.json')
        old_plan = read_json(parent / 'plan-batch.json')
        if not old_job or not old_plan or 'main' not in old_plan.get('scopes', ['main']):
            raise ValueError('原任务缺少主图计划')
        same_shop(job, read_json(parent / 'identity.json') or old_job)
        verify_frozen(old_job, old_plan, parent)
        old_ids = {str(p['productId']) for p in old_plan['products']}
        if chosen and not set(chosen) <= old_ids:
            raise ValueError('其余颜色组不能加入原批次以外的商品')
        if not chosen and not args.copy_batch_report:
            chosen = sorted(old_ids, key=int)
        previous = old_job.get('mainSelection', {})
        if not args.copy_batch_report:
            sources = previous.get('sourceByProduct', {})
            if not excluded <= set(sources.values()):
                raise ValueError('原任务缺少要排除商品的来源映射')
            for p in chosen:
                if sources.get(p) in excluded:
                    spec['exclusions'].append({'sourceProductId': sources[p], 'targetProductId': p, 'reason': 'excluded-source'})
            chosen = [p for p in chosen if sources.get(p) not in excluded]
            spec['sourceByProduct'] = {p: sources[p] for p in chosen if p in sources}
        spec.update(fromRun=str(parent), parentPlanSha256=file_sha(parent / 'plan-batch.json'))
    if not chosen and not args.copy_batch_report:
        raise ValueError('指定真实商品、搬家报告或原主图批次以冻结范围')
    spec.update(configure_design(job, args))
    if args.approved_sample:
        photo = args.approved_sample.resolve()
        if photo.parent.name != 'generated' or photo.suffix.lower() != '.png' or not photo.is_file():
            raise ValueError('请选择商家已批准的原任务 generated 目录中的 PNG')
        spec['approvedSample'] = {'file': str(photo), 'sha256': file_sha(photo)}
        if not spec.get('approvedPrompt') and not getattr(args, 'image_prompts_file', None):
            record = (read_json(photo.parent.parent / 'internal-generation.json') or {}).get(photo.stem, {})
            if record.get('status') != 'succeeded' or not str(record.get('prompt') or '').strip():
                raise ValueError('原样张缺少成功回执和提示词原文')
            spec['approvedPrompt'] = record['prompt']
            spec['promptSource'] = {'kind': 'approved-sample', 'file': str(photo)}
    spec['productIds'] = chosen
    job.update(mainSelection=spec, productIds=[int(p) for p in chosen], scope='main', mainPositions=[1])


def listed_products(cli, wanted):
    remaining = {int(p) for p in wanted}
    found, page, seen = {}, 1, set()
    while remaining:
        response = cli.get('jdo-product-status', '/rest/sp-product/v0/products',
                           {'scopeSet': 'productId,productStatus', 'page': page, 'pageSize': 100,
                            'sortBy': 'created', 'sortType': 'desc'})
        rows = response.get('data')
        if not isinstance(rows, list):
            raise ValueError('商品库未返回有效分页，无法冻结付费范围')
        if not rows:
            break
        ids = {int(row['productId']) for row in rows}
        if not ids - seen:
            raise ValueError('商品库分页重复，需重新核对目标商品')
        seen.update(ids)
        for row in rows:
            pid = int(row['productId'])
            if pid in remaining:
                found[pid] = row.get('productStatus')
                remaining.remove(pid)
        total = (response.get('paginationData') or {}).get('totalItems')
        if total is not None and len(seen) >= int(total):
            break
        page += 1
    return found


def prior_slots(spec, live, clean_url):
    parent = Path(spec['fromRun'])
    if file_sha(parent / 'plan-batch.json') != spec['parentPlanSha256']:
        raise ValueError('原主图批次范围已变化')
    plan = read_json(parent / 'plan-batch.json')
    table = {str(p['productId']): p for p in plan['products']}
    results = read_json(parent / 'patch-results.json', {})
    uploads = read_json(parent / 'uploads.json', {})
    eligible, excluded = {}, []
    for pid, detail in live.items():
        product = table[str(pid)]
        baseline = read_json(parent / 'products' / str(pid) / 'before-apply.json')
        if not baseline:
            raise ValueError(f'原任务缺少商品 {pid} 的完整快照')
        expected = snapshot(baseline, pid)
        original = {g: list(urls) for g, urls in expected['groups'].items()}
        live_state = snapshot(detail, pid)
        current = live_state['groups']
        approved = product.get('selectedSlots')
        if approved is None:  # Historical plans deduplicated by URL, including manually narrowed task sets.
            keys = {clean_url(t['currentUrl']): k for k, t in plan['tasks'].items()
                    if str(t['productId']) == str(pid) and t.get('scope') == 'main' and t.get('position') == 1}
            approved = [{'group': g, 'key': keys[clean_url(urls[0])]} for g, urls in original.items()
                        if urls and clean_url(urls[0]) in keys]
        old_groups = {s['group'] for s in approved}
        if (not approved or any(
                not current.get(s['group']) or not (uploads.get(s['key']) or {}).get('imgUrl') or
                uploads[s['key']].get('status') != 'succeeded' or
                clean_url(current[s['group']][0]) != clean_url(uploads[s['key']]['imgUrl']) for s in approved)):
            excluded.append({'productId': pid, 'reason': 'original-first-image-awaiting-reconciliation'})
            continue
        if not results.get(str(pid), {}).get('ok'):
            # An older receipt may still be awaiting readback. Recover only if every physical
            # position, SKU, price and binding now matches the original expected edit.
            for slot in approved:
                expected['groups'][slot['group']][0] = current[slot['group']][0]
            if gallery_readback(expected, live_state)['problems']:
                excluded.append({'productId': pid, 'reason': 'original-first-image-awaiting-reconciliation'})
                continue
        eligible[pid] = {g for g, urls in original.items() if g not in old_groups
                         and urls and current.get(g) and clean_url(urls[0]) == clean_url(current[g][0])}
        for g in (set(original) | set(current)) - old_groups - eligible[pid]:
            excluded.append({'productId': pid, 'group': g, 'reason': 'gallery-changed-since-original-plan'})
    return eligible, excluded


def derive(plan, spec, snapshots, listed, clean_url):
    mode = spec['mode']
    exclusions = list(spec['exclusions'])
    exclusions.extend({'productId': pid, 'reason': 'not-in-target-product-index'} for pid in spec['productIds']
                      if int(pid) not in listed)
    groups_by_pid = {}
    if mode == 'remaining-colors':
        groups_by_pid, pending = prior_slots(spec, snapshots, clean_url)
        exclusions.extend(pending)
    products, tasks, seen_skus = [], {}, set()
    wanted_skus = set(spec['skuIds'])
    for product in plan['products']:
        pid = product['productId']
        state = snapshot(snapshots[pid], pid)
        groups = state['groups']
        if mode == 'per-link':
            first = PUBLIC_GROUP if groups.get(PUBLIC_GROUP) else next((g for g, urls in groups.items() if urls), None)
            chosen = [first] if first else []
        elif mode == 'sku':
            local = set(state['skus']) & wanted_skus
            if not local:
                continue
            owners = gallery_owners(state)
            chosen = {owners[sku] for sku in local}
            others = {sku for sku, group in owners.items() if group in chosen} - local
            if others:
                raise ValueError('所选 SKU 共用图组会影响未选择规格：' + ','.join(sorted(others)))
            if seen_skus & local:
                raise ValueError('SKU 归属多个目标商品')
            seen_skus.update(local)
        else:
            chosen = groups_by_pid.get(pid, set())
        by_url = {row['url']: row for row in product['positions']}
        slots, assets = [], {}
        for gid, urls in groups.items():
            if gid not in chosen:
                continue
            if not urls:
                raise ValueError(f'目标图组 {pid}/{gid} 缺少首图')
            row = {**by_url[clean_url(urls[0])], 'group': gid, 'position': 1}
            slots.append(row)
            assets.setdefault(row['key'], row)
        if not slots:
            continue
        product.update(selectedSlots=slots, positions=list(assets.values()), uniqueImages=len(assets),
                       listStatus=listed[pid], sourceProductId=spec['sourceByProduct'].get(str(pid)),
                       baselineSha256=digest(snapshots[pid]))
        products.append(product)
        for key, row in assets.items():
            tasks[key] = {**plan['tasks'][key], 'group': row['group'], 'position': 1}
    if seen_skus != wanted_skus:
        raise ValueError('所选 SKU 未全部出现在目标商品的实际规格中')
    if spec['maxImages'] is not None and len(tasks) > spec['maxImages']:
        raise ValueError(f'选中 {len(tasks)} 张超过商家范围 {spec["maxImages"]}，未生成报价')
    plan.update(selectionMode=mode, products=products, tasks=tasks, capped=[], exclusions=exclusions,
                selectedSlotCount=sum(len(p['selectedSlots']) for p in products),
                selectionSpecSha256=digest(spec))
    plan['selectionSha256'] = digest(plan)
    return plan


def verify_frozen(job, plan, run=None):
    if not job.get('mainSelection') and not plan.get('selectionMode'):
        return
    if (plan.get('selectionSpecSha256') != digest(job.get('mainSelection'))
            or plan.get('selectionSha256') != digest({k: v for k, v in plan.items() if k != 'selectionSha256'})):
        raise ValueError('冻结的主图范围或计划已变化，保留原回执并核对')
    if run is not None:
        for product in plan['products']:
            pid = product['productId']
            baseline = read_json(Path(run) / 'products' / str(pid) / 'before-apply.json')
            if baseline is None or digest(baseline) != product['baselineSha256']:
                raise ValueError(f'原任务商品 {pid} 的冻结快照缺失或已变化')


def import_sample(run, job, designs, ledger):
    """Use the exact reviewed file. An unverifiable named sample never falls through to a paid remake."""
    from PIL import Image
    selected = (job.get('mainSelection') or {}).get('approvedSample')
    if not selected:
        return
    image = Path(selected['file'])
    parent, key = image.parent.parent, image.stem
    if key not in designs:
        raise ValueError('已批准样张不属于本次选中的商品首图')
    target = run / 'generated' / (key + '.png')
    original = ledger.get(key)
    if original:
        reused = original.get('reusedSample') or {}
        if (original.get('status') == 'succeeded' and original.get('outputSha256') == selected['sha256']
                and all(original.get(k) == v for k, v in designs[key].items())
                and reused == {'sourceRun': str(parent), 'key': key, 'sha256': selected['sha256']}
                and target.is_file() and file_sha(target) == selected['sha256']):
            return
        raise ValueError('本图已有其他生成请求或批准的成图已变化，保留原回执')
    same_shop(read_json(run / 'identity.json') or job, read_json(parent / 'identity.json') or {})
    old = (read_json(parent / 'internal-generation.json') or {}).get(key, {})
    design = designs[key]
    if old.get('status') != 'succeeded' or any(old.get(k) != v for k, v in design.items()):
        raise ValueError('样张回执与本次商品、原图、尺寸或提示词不一致')
    prior_plan = read_json(parent / 'plan-batch.json') or {}
    source = prior_plan.get('tasks', {}).get(key, {})
    if (source.get('productId') != design['productId'] or source.get('scope') != design['role']
            or not source.get('sourceKey') or file_sha(parent / 'sources' / (source['sourceKey'] + '.img')) != design['sourceSha256']):
        raise ValueError('样张的原商品或参考图无法核对')
    raw = image.read_bytes()
    sha = sha256(raw).hexdigest()
    if sha != selected['sha256'] or old.get('outputSha256', sha) != sha:
        raise ValueError('商家批准的样张已变更')
    from io import BytesIO
    with Image.open(BytesIO(raw)) as decoded:
        if decoded.format != 'PNG' or 'x'.join(str(n) for n in decoded.size) != design['size']:
            raise ValueError('样张尺寸或格式不匹配')
        decoded.verify()
    if target.exists() and file_sha(target) != sha:
        raise ValueError('同一图位已有不同成图，保留原文件')
    if not target.exists():
        fd, name = tempfile.mkstemp(dir=target.parent, suffix='.png')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
    ledger[key] = {**design, 'status': 'succeeded', 'attempts': 0, 'outputSha256': sha,
                   'bytes': len(raw), 'model': old.get('model'),
                   'reusedSample': {'sourceRun': str(parent), 'key': key, 'sha256': sha}}


def build_scoped(common, run, job, args):
    from concurrent.futures import ThreadPoolExecutor

    spec = job["mainSelection"]
    pids = [int(pid) for pid in spec["productIds"]]
    if args or job["productIds"] != pids:
        raise ValueError("已冻结商品范围，build_plan 从原任务获取商品及快照")
    existing = common.load_json(run / "plan-batch.json")
    if existing:
        verify_frozen(job, existing, run)
        print("沿用已冻结范围，图片", len(existing["tasks"]), "实际图位", existing["selectedSlotCount"])
        return
    cli = common.connect(job)
    common.verify_identity(cli, job, run)
    listed = listed_products(cli, pids)
    with ThreadPoolExecutor(max_workers=int(job.get("fetchConcurrency") or 6)) as pool:
        snapshots = dict(zip(listed, pool.map(lambda pid: common.apply_detail(cli, pid), listed)))
    plan = common.build_plan(snapshots, prompt_template=job.get("promptTemplate"), image_base=job.get("imageBase"), order=[p for p in pids if p in listed],
                             scopes=["main"], positions=[1])
    derive(plan, spec, snapshots, listed, common.clean_url)
    for product in plan["products"]:
        pid = product["productId"]
        common.save_json(run / "products" / str(pid) / "before-apply.json", snapshots[pid])
    common.save_json(run / "plan-batch.json", plan)
    print("商品", len(plan["products"]), "成图", len(plan["tasks"]), "实际图位", plan["selectedSlotCount"],
          "排除记录", len(plan["exclusions"]))


def plan_products(plan, pids=None):
    wanted = {str(item) for item in (pids or []) if str(item).strip()}
    products = plan.get("products") or []
    result = []
    for item in products:
        if wanted and str(item["productId"]) not in wanted:
            continue
        if "tasks" in plan and not plan.get("selectionMode"):
            # Some older hosts narrowed tasks after planning without narrowing positions.
            # Never carry discarded keys into a second batch's patch, report or verification.
            keys = plan["tasks"]
            physical = item.get("positions", [])
            details = item.get("detailImages", [])
            kept = [r for r in physical if r["key"] in keys]
            kept_details = [r for r in details if r["key"] in keys]
            if (physical or details) and not (kept or kept_details):
                continue
            if len(kept) != len(physical) or len(kept_details) != len(details):
                item = {**item, "positions": kept, "uniqueImages": len({r["key"] for r in kept})}
                if details:
                    item["detailImages"] = kept_details
        result.append(item)
    return result
