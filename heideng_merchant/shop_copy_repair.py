"""Correct only merchant SKU codes on a specified, already existing target listing."""
from argparse import Namespace
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
from uuid import uuid4

from . import owned_product_copy as copy
from . import sku_image_edit as edits
from .safety import atomic_json, read_json, is_linked, safe_join, file_sha
from .shop_copy_code_template import align_schema, published_schema, verify_galleries


def _codes(detail, pid):
    return {sid:row.get('outerId') for sid,row in edits.sku_rows(detail,pid).items()}


PRODUCT_VOLATILE = ('modifiedTime','updatedAt','productStatus','productStatusNew','bossAuditStatus','auditStatus','saleCount')
SKU_VOLATILE = ('modifiedTime','updatedAt','stockNum','incrementStockNum','saleCount')
EDIT_ROUTE = '/rest/sp-product/v0/product-applies'
REFUSAL_CODES = {'1010300506','10103001002','99904030007','99904030008'}


def proven_rejection(record):
    if proven_review_rejection(record):
        return True
    refusal = record.get('officialRejection') or {}
    codes = refusal.get('codes')
    return (record.get('status')=='rejected' and refusal.get('call')==['POST',EDIT_ROUTE]
            and refusal.get('noIssuedIds') is True and isinstance(codes,list) and bool(codes)
            and all(isinstance(code,str) and code in REFUSAL_CODES for code in codes)
            and bool(record.get('bodySha256')) and refusal.get('bodySha256')==record['bodySha256'])


def proven_review_rejection(record):
    review=record.get('officialReviewRejection') or {}
    return (record.get('status')=='rejected' and str(review.get('draftComputeStatus'))=='3'
            and re.fullmatch('[1-9][0-9]*',str(review.get('applyId') or '')) is not None
            and str(review.get('productId') or '')==str((record.get('binding') or {}).get('targetProductId'))
            and bool(record.get('bodySha256')) and review.get('bodySha256')==record['bodySha256'])


def _preserved(detail, pid, *, live_readback=False):
    product = deepcopy(detail['productInfo'])
    for name in PRODUCT_VOLATILE if live_readback else ('modifiedTime',):
        product.pop(name,None)
    omitted = set(SKU_VOLATILE if live_readback else ('modifiedTime',)) | {'outerId'}
    rows = {sid:{k:v for k,v in row.items() if k not in omitted}
            for sid,row in edits.sku_rows(detail,pid).items()}
    return edits.digest({'product':product,'skus':rows,'material':detail.get('material'),
                         'extensions':detail.get('extendInfoList')})


def _rolling_values(detail,pid):
    return {'product':{k:detail['productInfo'][k] for k in PRODUCT_VOLATILE if k in detail['productInfo']},
            'skus':{sid:{k:row[k] for k in SKU_VOLATILE if k in row} for sid,row in edits.sku_rows(detail,pid).items()}}


def _mapping(frozen, detail, pid):
    source = frozen['sourceDetail']
    left = copy._view(source,None,None)['skus']
    right = copy._view(detail,None,None)['skus']
    matching = copy.pair_frozen_target_skus(frozen,detail)
    if len(matching['pairs']) != len(left) and any(
            axis.get('templateSkuProps') for rows in (left,right) for row in rows.values()
            for axis in (row['specifications'] or [])):
        from .shop_copy_command import reference
        matching = copy.pair_frozen_target_skus(frozen,detail,reference(frozen['targetShop'],detail,for_creation=False))
    pairs = matching['pairs']
    source_codes = _codes(source,frozen['sourceProductId'])
    current = _codes(detail,pid)
    changes, problems = {}, []
    if set(pairs) != set(left) or set(pairs.values()) != set(right) or len(set(pairs.values())) != len(pairs):
        problems.append('源、目标的全部规格尚未形成独立于商家编码的一一对应')
    for sid,tid in pairs.items():
        wanted = source_codes[sid]
        if not isinstance(wanted,str) or not wanted.strip():
            if wanted != current[tid] or wanted is None:
                problems.append(f'源 SKU {sid} 缺少明确的原始文本编码，保留目标现值')
            continue
        if current[tid] is not None and not isinstance(current[tid],str):
            problems.append(f'目标 SKU {tid} 的原编码不是可核对的文本值')
        elif wanted != current[tid]:
            changes[tid] = {'sourceSkuId':sid,'targetSkuId':tid,'before':current[tid],'after':wanted}
    return changes, problems


def _application(api, pid, apply_id=None):
    response = api.get('jdo-product-update','/rest/sp-product/v0/product-apply/{applyId}',
                       {'applyId':str(apply_id or pid),'scene':'pop'})
    detail = response.get('data') or {}
    edits.sku_rows(detail,pid)
    return detail


def _edit_baseline(application,online,prior):
    # A proven rejected draft is not the editable product's current state.
    # Use live product values only when the returned application is that exact terminal attempt.
    info=application.get('applyInfo') or {}
    if (proven_review_rejection(prior) and str(info.get('draftComputeStatus'))=='3'
            and str(info.get('applyId') or '')==str(prior['officialReviewRejection']['applyId'])):
        return online
    return application


def _merchant_source(api, frozen, args, read_product):
    """Read source codes/specifications again before the edit, using the original verified shop triple."""
    from .official import identity_from_response
    expected = frozen['sourceShop']
    try:
        api.configure_jdo_profile(expected['profile'])
        current = api.get('jdo-seller-info','/rest/sp-seller/v0/venderinfo',{'scopeSet':'baseInfo'})
        identity = identity_from_response(current)
        payload = current.get('data') or {}
        if 'shopBaseInfo' not in payload:
            payload = payload.get('data') or {}
        if (current.get('success') is not True or str((payload.get('shopBaseInfo') or {}).get('status')) != '1'
                or any(str(identity[k]) != str(expected[k]) for k in ('shopId','venderId','shopName'))):
            raise ValueError('源 Profile 与原任务店铺身份不符')
        api.mark_jdo_store_verified(expected['profile'],identity['venderId'],identity['shopName'],identity['shopId'])
        pid = int(frozen['sourceProductId'])
        fresh = read_product(pid)
        def inputs(detail):
            return {sid:(row.get('outerId'),copy._specs(row)) for sid,row in edits.sku_rows(detail,pid).items()}
        if inputs(fresh) != inputs(frozen['sourceDetail']):
            raise ValueError('源店商品规格或编码已变化，原修复计划需要更新')
    finally:
        target = api.verify_configured_store_identity(args.target_config,args.target_profile)
        if any(str(target.get(k) or '') != str(frozen['targetShop'][k]) for k in ('profile','shopId','venderId','shopName')):
            raise ValueError('重新核验时，目标 Profile 已指向别的店铺')


def _template(api, pid, category, *, existing):
    params = {'scene':'pop','lastCategoryId':category}
    if existing:
        params['productId'] = pid
    payload = api.get('jdo-product-publish','/rest/sp-product/v0/product-schemas',params).get('data')
    if not isinstance(payload,list) or len(payload) != 1:
        raise ValueError('未取得原目标类目的唯一官方模板')
    value = json.loads(payload[0],object_pairs_hook=edits.unique) if isinstance(payload[0],str) else payload[0]
    if isinstance(value,dict):
        if existing and value.get('productId') is not None and str(value['productId']) != str(pid):
            raise ValueError('官方回填模板属于另一商品')
        value = value.get('componentList')
    if not isinstance(value,list):
        raise ValueError('官方模板缺少完整组件数组')
    return value


def _declares_sku_code(schema):
    def declares(node):
        return node.get('componentCode') == 'SkuVendorSku' or any(
            declares(child) for child in node.get('childrenComponents',[]) if isinstance(child,dict))
    sku = edits.components(schema).get('SKUS') or {}
    return declares(sku)


def _original_body(root,folder,frozen,target,pid):
    from .shop_copy_command import load_copy, publication_state
    try:
        return published_schema(root,folder,frozen,target,pid)
    except ValueError as reason:
        first_reason = reason
    # Some merchants first associated a target in a later task. Only look for
    # its original accepted creation inside the same local managed-copy directory.
    found = {}
    for other in root.parent.glob('*'):
        if other == root or not re.fullmatch('[0-9a-f]{24}',other.name) or is_linked(other):
            continue
        index = read_json(other/'current.json',{})
        if index.get('targetShop') != target or not isinstance(index.get('taskId'),str):
            continue
        original = publication_state(other,index['taskId'])
        if original['status'] != 'submitted' or str(original.get('targetProductId') or '') != str(pid):
            continue
        revision, old = load_copy(other)
        schema = published_schema(other,revision,old,target,pid)
        found[edits.digest(schema)] = schema
    if len(found) != 1:
        raise ValueError('目标原通过体不唯一，或其本店原创建回执尚未找到。'+str(first_reason))
    return next(iter(found.values()))


def _exact_template(api, apply, pid, changes, root, folder, frozen, target):
    # The public POP SKU PATCH catalogue does not advertise SkuVendorSku.
    # Never substitute a creation template, source-shop schema or old published body.
    category = int(apply['productInfo']['categoryDetail']['lastCategoryId'])
    catalog = _template(api,pid,category,existing=False)
    skeleton = _template(api,pid,category,existing=True)
    components = edits.components(skeleton)
    historical = not (components.get('WareTitle',{}).get('value') and components.get('SKUS',{}).get('value'))
    if historical:
        skeleton = _original_body(root,folder,frozen,target,pid)
    schema, checked = align_schema(skeleton,apply,pid,catalog,historical=historical)
    edits.verify_live_template(schema,verify_galleries(schema,checked,historical=historical),pid)
    clean = edits.edit_schema(schema,checked,pid,{})  # checks exact SKU IDs/prices/status and omits inventory writes
    top = edits.components(clean)
    rows = edits.sku_rows(apply,pid)
    original_skus = edits.components(schema)['SKUS']['value']
    code_declared = None
    product = apply['productInfo']
    features = edits.unique((f.get('key'),f.get('value')) for f in product.get('features') or [])
    edits.pictures(apply,pid)  # Reject duplicate or unowned specification images.
    desc = product.get('productDetailDesc') or {}
    editors=edits.unique((attrs.get('userAgent'),attrs) for attrs in
                         (edits.properties(node) for node in top.get('WareEditor',{}).get('value') or []))
    for channel,desc_key in (('pc','desc'),('mobile','mobileDesc')):
        if (editors.get(channel,{}).get('desc') or '') != (desc.get(desc_key) or ''):
            raise ValueError('原编辑模板与当前目标详情不一致')
    if set(editors)-{'pc','mobile'}:
        raise ValueError('原编辑模板含未核实的详情渠道')
    packing = product.get('packSpecification')
    if packing not in ('',None,[]) and not any(c.get('productDetailField') == 'productInfo.packSpecification'
                                               and c.get('value') == packing for c in top.values()):
        raise ValueError('目标回填模板没有对应到原包装字段')
    address = (product.get('logisticsInfo') or {}).get('delivery')
    if address not in (None,'') and str(top.get('WareShopAddress',{}).get('value')) != str(address):
        raise ValueError('目标回填模板未对上原商品的发货地')
    if features.get('isPayFirst') is not None and str(edits.properties(top.get('PayMethodLimit',{})).get('isPayFirst')) != str(features['isPayFirst']):
        raise ValueError('目标模板付款限制与原商品不符')
    spec_images = {str(i.get('uuid')):i.get('imageUrl') for i in (apply.get('material') or {}).get('ggtImages') or []}
    for i,item in enumerate(top['SKUS']['value']):
        fields = edits.components(item['value'])
        sid = str(fields['SkuId']['value'])
        row = rows[sid]
        original_fields = edits.components(original_skus[i]['value'])
        if str(original_fields.get('SkuId',{}).get('value')) != sid:
            raise ValueError('目标编辑模板没有回填明确的原 SKU ID')
        if 'SkuUUid' in fields and str(fields['SkuUUid'].get('value')) != sid:
            raise ValueError('目标现有 SKU 的编辑 UUID 与原 ID 不符')
        selection = (row.get('logisticsInfo') or row.get('logistics') or {}).get('promiseId')
        if selection not in ('',None) and str(fields.get('SkuPromise',{}).get('value')) != str(selection):
            raise ValueError(f'目标 SKU {sid} 的时效未由原模板保留')
        expected_image = spec_images.get(str(row.get('uuid') or sid))
        image_rows = fields.get('SkuGgtImage',{}).get('value') or []
        images = [edits.properties(image).get('imgUrl') for image in image_rows]
        if images != ([expected_image] if expected_image else []):
            raise ValueError(f'目标 SKU {sid} 的规格图与原模板不符')
        current = row.get('outerId')
        field = fields.get('SkuVendorSku')
        if field is not None and (field.get('value') or '') != (current or ''):
            raise ValueError(f'目标 SKU {sid} 的编码与原模板不符')
        if sid in changes:
            if field is None:
                if code_declared is None:
                    code_declared = _declares_sku_code(catalog)
                if not code_declared or current not in (None,''):
                    raise ValueError(f'目标 SKU {sid} 的官方模板未能证明可填写商家编码')
                field = {'componentCode':'SkuVendorSku'}
                item['value'].append(field)
            field['value'] = changes[sid]['after']
    return {'scene':'pop','productApplyDTO':{'productId':int(pid),'saveActionType':0,
            'categoryDTO':{'lastCategoryId':int(product['categoryDetail']['lastCategoryId'])}},
            'schema':json.dumps(clean,ensure_ascii=False,separators=(',',':'))}


def _readback(api, read_product, pid, record, path):
    result = {'ok':False,'status':'sku-code-repair-awaiting-readback','targetProductId':str(pid),
              'receipt':str(path),'replayed':False,'consumerPageStatus':'unchecked'}
    body = Path(record['body'])
    if (not re.fullmatch('[a-f0-9]{32}',body.parent.name) or
            body!=safe_join(path.parent,'attempts/'+body.parent.name+'/edit.json') or file_sha(body)!=record.get('bodySha256')):
        raise ValueError('原修码请求体或其指纹已改变，请从同一任务核对')
    response = read_json(body.with_name('response.json'),{})
    data = response.get('data') or {}
    accepted = (response.get('success') is True and not response.get('errorList') and isinstance(data,dict)
                and not data.get('errorList') and bool(data.get('productId') or data.get('applyId'))
                and (not data.get('productId') or str(data['productId'])==str(pid)))
    refusal = read_json(body.with_name('rejection.json'),{})
    declined = {**record,'status':'rejected','officialRejection':refusal}
    if refusal and proven_rejection(declined):
        if accepted:
            return {**result,'status':'conflicting-original-repair-receipts','retryAllowed':False}
        atomic_json(path,declined)
        return {**result,'status':'sku-code-repair-rejected','officialRejection':refusal}
    result.update(submissionStatus='accepted' if accepted else 'original-receipt-unconfirmed',
                  applyId=data.get('applyId') if accepted else None)
    def check(detail):
        return {'codesMatch':_codes(detail,pid) == record['expected'],
                'otherFieldsMatch':_preserved(detail,pid,live_readback=True) == record['protected']}
    detail=read_product(pid)
    online = check(detail)
    online['observedCodes'] = _codes(detail,pid)
    online['expectedCodes'] = record['expected']
    result['online'] = online
    rolling=_rolling_values(detail,pid)
    if rolling != record['rolling']:
        result['changedCountersOrStatus']={'before':record['rolling'],'current':rolling}
    saved_review=read_json(body.with_name('review-rejection.json'),{})
    reviewed={**record,'status':'rejected','officialReviewRejection':saved_review}
    if (proven_review_rejection(reviewed) and accepted
            and str(saved_review['applyId'])==str(result['applyId'])):
        result.update(status='sku-code-application-rejected',applicationOutcome='rejected',
                      applicationStatus=saved_review['applicationStatus'],applicationPending=False,retryAllowed=False)
        atomic_json(path,{**reviewed,'lastReadback':result})
        return result
    apply=_application(api,pid,result['applyId'])
    application = check(apply)
    result['application'] = application
    result['applicationStatus']=apply.get('applyInfo') or {}
    echoed = result['applicationStatus'].get('applyId')
    if result['applyId'] and echoed and str(echoed)!=str(result['applyId']):
        return {**result,'status':'different-application-readback','applicationOutcome':'unconfirmed','retryAllowed':False}
    if str(result['applicationStatus'].get('draftComputeStatus'))=='3':
        if not accepted or not re.fullmatch('[1-9][0-9]*',str(result['applyId'] or '')):
            return {**result,'status':'rejected-application-original-unconfirmed','applicationOutcome':'unconfirmed',
                    'retryAllowed':False}
        review={'applyId':str(result['applyId']),'productId':str(pid),'bodySha256':record['bodySha256'],
                'draftComputeStatus':3,'applicationStatus':result['applicationStatus']}
        result.update(status='sku-code-application-rejected',applicationOutcome='rejected',applicationPending=False,
                      retryAllowed=False)
        atomic_json(body.with_name('review-rejection.json'),review)
        atomic_json(path,{**record,'status':'rejected','officialReviewRejection':review,'lastReadback':result})
        return result
    pending = str(result['applicationStatus'].get('draftComputeStatus'))=='1'
    result['applicationPending'] = pending
    if online['codesMatch'] and accepted:
        result.update(ok=online['otherFieldsMatch'],status='sku-codes-verified' if online['otherFieldsMatch'] else 'sku-codes-match-other-fields-differ')
        if not pending:
            record={**record,'status':'verified'}  # Codes settled. Other observed changes remain in the readback.
        else:
            result.update(ok=False,status='sku-codes-observed-application-pending')
    elif online['codesMatch']:
        result['status']='sku-codes-observed-original-unconfirmed'
    elif application['codesMatch'] and accepted:
        result['status'] = 'sku-codes-in-application'
    elif application['codesMatch']:
        result['status']='application-codes-observed-original-unconfirmed'
    atomic_json(path,{**record,'lastReadback':result})
    return result


def repair_codes(root, folder, frozen, target, args, *, api, read_product):
    from .shop_copy_command import publication_state, validation_passed
    copy._validate(frozen,target)
    original = publication_state(root,args.task)
    bound = str(original.get('targetProductId') or '')
    explicit = str(getattr(args,'product_id',None) or '')
    pid = bound or explicit
    if not re.fullmatch('[1-9][0-9]*',pid) or explicit and bound and explicit != bound:
        return {'ok':False,'status':'needs-target-evidence','message':'请核对此任务已绑定的原目标商品编号。','productWrites':0}
    pid = int(pid)
    submit = getattr(args,'confirm',None) == 'REPAIR_TARGET_SKU_CODES'
    eligible_origin = bool(bound) and (original['status'] == 'submitted' or (
        original['status'] == 'existing-target-for-comparison' and explicit == bound))
    directory = edits.code_repair_directory(target,pid)
    gallery = edits.gallery_write_directory(api,target,pid)
    with edits.product_image_lock(gallery,target,pid):
        receipt = directory/'current.json'
        prior = read_json(receipt,{})
        binding = {'taskId':args.task,'sourceShop':frozen['sourceShop'],'sourceProductId':frozen['sourceProductId'],
                   'targetShop':target,'targetProductId':str(pid)}
        if (prior.get('status')=='verified' and str((prior.get('lastReadback',{}).get('applicationStatus') or {}).get(
                'draftComputeStatus'))=='3'):
            prior={**prior,'status':'submitted'}
        if prior and prior.get('status') == 'rejected' and not proven_rejection(prior):
            # A text-only refusal in an older task may have hidden an accepted write.
            # Preserve it and use the original request and current platform reads; never replay it.
            if not all(key in prior for key in ('body','bodySha256','expected','protected','rolling')):
                return {'ok':False,'status':'original-repair-outcome-unconfirmed','receipt':str(receipt),'retryAllowed':False}
            prior={**prior,'status':'submitting','previousUnverifiedStatus':'rejected'}
        if prior and (prior.get('status') not in ('verified','rejected') or
                      getattr(args,'reconcile',False) and (prior.get('status') == 'verified' or proven_review_rejection(prior))):
            if prior.get('binding') != binding:
                return {'ok':False,'status':'different-original-repair','receipt':str(receipt),'productWrites':0}
            # A repeated request, including --confirm, reads the original operation before any other work.
            return _readback(api,read_product,pid,prior,receipt)
        if getattr(args,'reconcile',False):
            return {'ok':False,'status':'sku-code-repair-rejected' if prior else 'no-original-repair','receipt':str(receipt),'productWrites':0}
        online = read_product(pid)
        changes,problems = _mapping(frozen,online,pid)
        if not eligible_origin:
            problems.append('当前没有可绑定的原目标发布回执，或尚未明确指定已关联的目标链接')
        base = {'targetProductId':str(pid),'changeCount':len(changes),'changes':list(changes.values()),'productWrites':0}
        if problems:
            return {**base,'ok':False,'status':'needs-repair-evidence','reasons':problems}
        if not changes:
            if proven_review_rejection(prior) and prior.get('binding')==binding:
                return _readback(api,read_product,pid,prior,receipt)
            return {**base,'ok':True,'status':'sku-codes-already-match'}
        try:
            apply = _edit_baseline(_application(api,pid),online,prior)
            baseline = _preserved(online,pid)
            if (str((apply.get('applyInfo') or {}).get('draftComputeStatus')) == '1'
                    or _preserved(apply,pid) != baseline or _codes(apply,pid) != _codes(online,pid)):
                raise ValueError('现有申请与线上商品尚未一致，请先核对原申请')
            body = _exact_template(api,apply,pid,changes,root,folder,frozen,target)
        except (ValueError,TypeError,KeyError) as exc:
            return {**base,'ok':False,'status':'needs-edit-template','reasons':[str(exc)]}
        fingerprint = edits.digest([binding,baseline,body,frozen['sha256']])
        proposal = folder/'sku-code-plan.json'
        if proven_rejection(prior) and (prior.get('requestDigest') == edits.digest(body) or prior.get('fingerprint') == fingerprint):
            if proven_review_rejection(prior):
                return _readback(api,read_product,pid,prior,receipt)
            return {**base,'ok':False,'status':'sku-code-repair-rejected','receipt':str(receipt),'replayed':False}
        if not submit:
            atomic_json(proposal,{'fingerprint':fingerprint,**binding,**base})
            return {**base,'ok':True,'status':'sku-code-repair-ready','planFile':str(proposal),'fingerprint':fingerprint}
        previous_plan = read_json(proposal,{})
        if previous_plan and previous_plan.get('fingerprint') != fingerprint:
            return {**base,'ok':False,'status':'repair-plan-changed','message':'目标字段或模板已变化，请先重新检查原商品。'}
        edits.require_settled_edit(edits.sku_edit_directory(target,pid)/'current.json','规格图整版编辑')
        edits.require_settled_edit(gallery/'current.json','主图提交')
        _merchant_source(api,frozen,args,read_product)
        attempt = directory/'attempts'/uuid4().hex
        destination = attempt/'edit.json'
        atomic_json(destination,body)
        brand = (apply['productInfo'].get('brandInfo') or {}).get('brandId')
        validation = {**body,'productApplyDTO':{**body['productApplyDTO'],'brandId':brand}} if brand is not None else body
        check = attempt/'validation-body.json'
        response_path = attempt/'validation-result.json'
        atomic_json(check,validation)
        with redirect_stdout(io.StringIO()):
            rc = api.command_validate_jd(Namespace(body=check,output=response_path))
        if rc or not validation_passed(read_json(response_path,{})):
            return {**base,'ok':False,'status':'validation-needs-review','receipt':str(response_path)}
        fresh = read_product(pid)
        current_apply = _edit_baseline(_application(api,pid),fresh,prior)
        if (_preserved(fresh,pid) != baseline or _codes(fresh,pid) != _codes(online,pid)
                or _preserved(current_apply,pid) != baseline or _codes(current_apply,pid) != _codes(online,pid)
                or current_apply.get('applyInfo') != apply.get('applyInfo') or
                _exact_template(api,current_apply,pid,changes,root,folder,frozen,target) != body):
            return {**base,'ok':False,'status':'repair-plan-changed'}
        expected = {**_codes(online,pid),**{sid:change['after'] for sid,change in changes.items()}}
        record = {'status':'submitting','binding':binding,'fingerprint':fingerprint,'expected':expected,
                  'baseline':baseline,'protected':_preserved(online,pid,live_readback=True),'rolling':_rolling_values(online,pid),
                  'body':str(destination),'bodySha256':file_sha(destination),'requestDigest':edits.digest(body),
                  'changes':list(changes.values())}
        atomic_json(attempt/'intent.json',record)
        atomic_json(receipt,record)
        try:
            with redirect_stdout(io.StringIO()):
                api.command_edit_product(Namespace(product_id=pid,body=destination,output=attempt/'response.json',
                                                   confirm='EDIT_EXISTING_PRODUCT'))
        except (api.JdoError,OSError,RuntimeError) as exc:
            codes = getattr(exc,'platform_codes',None)
            if (isinstance(exc,api.JdoError) and getattr(exc,'platform_call',None)==('POST',EDIT_ROUTE)
                    and getattr(exc,'no_issued_ids',False) is True and isinstance(codes,list)
                    and codes and all(isinstance(code,str) and code in REFUSAL_CODES for code in codes)):
                refusal={'call':['POST',EDIT_ROUTE],'codes':codes,'noIssuedIds':True,
                         'requestId':getattr(exc,'request_id',None),'bodySha256':record['bodySha256']}
                record.update(status='rejected',officialRejection=refusal)
                atomic_json(attempt/'rejection.json',refusal)
                atomic_json(receipt,record)
            return {'ok':False,'status':'sku-code-repair-rejected' if record['status']=='rejected' else 'sku-code-repair-awaiting-readback',
                    'targetProductId':str(pid),'receipt':str(receipt),'retryAllowed':False}
        record['status']='submitted'
        atomic_json(receipt,record)
        return _readback(api,read_product,pid,record,receipt)
