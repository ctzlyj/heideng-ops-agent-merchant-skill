"""Reconcile historical migration receipts with the current target catalogue. Read-only."""
import re
from collections import defaultdict
from pathlib import Path
import time

from .safety import SafetyError, atomic_json, is_linked, read_json, safe_join
from .state import merchant_home


def register(subs):
    p=subs.add_parser('history-census',help='对照旧搬家工作目录、实际在售商品与指定目标链接')
    p.add_argument('--history-dir',required=True,type=Path)
    p.add_argument('--target-config',required=True,type=Path)
    p.add_argument('--target-profile',required=True)
    p.add_argument('--target-product-id',action='append',default=[])


def history_records(directory,target):
    if not directory.is_dir() or is_linked(directory):
        raise ValueError('请选择原搬家工作目录')
    candidates=defaultdict(lambda:defaultdict(list))
    skipped=[]
    for path in sorted(directory.glob('batch*/*/state/*.json')):
        parts=path.relative_to(directory).parts
        if not re.fullmatch(r'batch[0-9]*',parts[0]) or not re.fullmatch('[1-9][0-9]*',parts[1]):
            continue
        relative=path.relative_to(directory).as_posix()
        try:
            d=read_json(safe_join(directory,relative))
            store=d.get('store') or {}
            if any(str(store.get(k,''))!=str(target[k]) for k in ('profile','shopId','venderId')):
                skipped.append({'file':relative,'reason':'other-or-unverified-shop'})
                continue
            sid=str(d.get('sourceSpu') or '')
            if sid!=parts[1]:
                skipped.append({'file':relative,'reason':'unconfirmed-source-product'})
                continue
            values={'publication':d.get('productId'),'verification':(d.get('verification') or {}).get('productId')}
            for role,value in values.items():
                if re.fullmatch('[1-9][0-9]*',str(value)):
                    candidates[str(value)][sid].append({'field':role,'file':relative,'applyId':d.get('applyId')})
        except (SafetyError,ValueError,TypeError,AttributeError,OSError):
            skipped.append({'file':relative,'reason':'unreadable-receipt'})
    return candidates,skipped


def run(args,entry):
    target=entry.verify(args.target_config,args.target_profile)
    candidates,skipped=history_records(args.history_dir,target)
    products=entry.pipeline.list_products(require_success=True)
    entry.api.recheck_verified_jdo_store()
    current={str(p['productId']):p for p in products}
    requested=list(map(str,args.target_product_id))
    if any(not re.fullmatch('[1-9][0-9]*',pid) for pid in requested):
        raise ValueError('目标商品编号无效')
    ids=list(dict.fromkeys(requested)) if requested else sorted(set(current)|set(candidates))
    by_source=defaultdict(set)
    for tid,origins in candidates.items():
        for sid in origins:by_source[sid].add(tid)
    rows=[]
    by_name=defaultdict(list)
    for tid,product in current.items():
        if product.get('productName') and tid in candidates:
            by_name[product['productName']].append(tid)
    for tid in ids:
        row=current.get(tid)
        links=candidates.get(tid,{})
        sibling_hints=[]
        if row and not links:
            for other in by_name.get(row.get('productName'),[]):
                sibling=current[other]
                if row.get('categoryId') and sibling.get('categoryId') and str(row['categoryId'])!=str(sibling['categoryId']):
                    continue
                sibling_hints.append({'targetProductId':other,'sourceProductIds':sorted(candidates[other]),
                                      'evidence':'same-catalogue-title','requiresIndependentProductAndSkuCheck':True})
        rows.append({'targetProductId':tid,'productName':row.get('productName') if row else None,
                     'liveCatalogueStatus':row.get('productStatus') if row else None,
                     'foundInProductCatalogue':row is not None,'sourceCandidates':dict(links),
                     'unverifiedSiblingHints':sibling_hints,
                     'otherTargetsForSameSource':{sid:sorted(by_source[sid]-{tid}) for sid in links if len(by_source[sid])>1}})
    out={'status':'history-compared','targetShop':target,'requestedRowCount':len(requested),'uniqueTargetCount':len(ids),
         'checkedAt':int(time.time()),'rows':rows,'unusableReceipts':skipped,'platformWrites':0,
         'scopeNote':'创建回执与回读可能指向不同目标。此表供追溯。素材写入另行核实两店真实商品及规格。'}
    dest=safe_join(merchant_home(),'work/shop-copy-catalogues/'+entry.digest(out)+'.json')
    atomic_json(dest,out)
    return {'ok':True,**out,'reportFile':str(dest)}
