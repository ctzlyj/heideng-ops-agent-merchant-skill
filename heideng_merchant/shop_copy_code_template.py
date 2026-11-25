"""Validate filled editor values, or recover the shape of this target's accepted creation request."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json

from . import sku_image_edit as edits
from .safety import file_sha, read_json


PRODUCT = {'WareTitle':'productName','WareItemnum':'itemNum','WareWeight':'weight','WareLength':'length','WareHeight':'height',
           'WareWide':'wide','WareBrand':'brandInfo.brandId','WareTransport':'logisticsInfo.transportId',
           'WarePromise':'logisticsInfo.promiseId','WareShopAddress':'logisticsInfo.delivery'}
SKU = {'SkuJdprice':'priceInfo.jdPrice','SkuVendorSku':'outerId','SkuEnableStatus':'skuEnableStatus',
       'SkuUpcCode':'upcCode','SkuWareUpccode':'upcCode','SkuPromise':'logisticsInfo.promiseId',
       'SkuId':'skuId','SkuUUid':'skuId'}
NUMBERS = {'WareWeight','WareLength','WareHeight','WareWide','SkuJdprice'}


def _at(record,path):
    for key in path.split('.'):
        if not isinstance(record,dict) or key not in record:
            return False,None
        record = record[key]
    return True,record


def _same(value,actual,code):
    if code in NUMBERS and value not in ('',None) and actual not in ('',None):
        try:
            return Decimal(str(value)).is_finite() and Decimal(str(value)) == Decimal(str(actual))
        except InvalidOperation:
            return False
    if actual in (None,''):
        return value in (None,'')
    if isinstance(actual,(dict,list)) or isinstance(value,(dict,list)):
        return value == actual
    return value is not None and str(value) == str(actual)


def _boxes(value):
    if isinstance(value,str):
        value=json.loads(value,object_pairs_hook=edits.unique)
    if value in (None,[], ''):
        return {}
    if not isinstance(value,list):
        raise ValueError('结构化规格缺少官方分项数组')
    return edits.unique((str(box['id']),box) for box in value)


def _sale_key(sales, *, submitted):
    pairs=[]
    for item in sales:
        if submitted:
            props=edits.properties(item)
            key=item['componentCode'].removeprefix('sale-prop-')
            alias=props.get('attrValueAlias')
            if isinstance(alias,str) and alias.startswith('[') and alias.endswith(']'):
                alias=alias[1:-1]
        else:
            props=item
            key=str(item.get('attrId') or '')
            alias=item.get('attrValueAlias')
        if not key or not isinstance(alias,str) or not alias:
            raise ValueError('销售规格缺少原始属性编号或展示值')
        pairs.append((key,[alias,_boxes(props.get('templateSkuProps'))]))
    return edits.digest(edits.unique(pairs))


def _nodes(items):
    for item in items:
        yield item
        yield from _nodes(item.get('childrenComponents') or [])


def _scalars(fields,actual,known,handled,declarations,*,historical,sku=False):
    # Re-read all scalar values transmitted in a full edit. Unknown control values
    # need an explicit official mapping; the presence of a plausible default is insufficient.
    for name,path in known.items():
        if name in fields or name in ('SkuUUid','SkuVendorSku'):
            continue
        if name in ('SkuUpcCode','SkuWareUpccode') and ('SkuUpcCode' in fields or 'SkuWareUpccode' in fields):
            continue
        _,present_value = _at(actual,path)
        if name=='WareWide':
            present_value = actual.get('wide',actual.get('width'))
        if present_value not in (None,''):
            raise ValueError(f'原编辑模板未覆盖当前商品的 {name}')
    for name,item in declarations.items():
        hint = item.get('productDetailField')
        prefix = 'skuList.' if sku else 'productInfo.'
        if name not in fields and name not in known and isinstance(hint,str) and hint.startswith(prefix):
            present,value = _at(actual,hint.removeprefix(prefix))
            if present and value not in (None,'',[],{}) and not item.get('readOnly'):
                raise ValueError(f'原编辑模板缺少目标现在有值的字段 {name}')
    for name,field in fields.items():
        if name in handled:
            continue
        if field.get('properties'):
            raise ValueError(f'标量组件 {name} 带有未能单独核对的属性')
        path=known.get(name)
        if path is None:
            hint=declarations.get(name,{}).get('productDetailField')
            prefix='skuList.' if sku else 'productInfo.'
            if not isinstance(hint,str) or not hint.startswith(prefix) or field.get('properties'):
                raise ValueError(f'原编辑字段 {name} 缺少可核对的官方回读映射')
            path=hint.removeprefix(prefix)
        present,value=_at(actual,path)
        if name=='WareWide':
            if 'wide' in actual and 'width' in actual and not _same(actual['wide'],actual['width'],name):
                raise ValueError('目标回读的宽度字段互相矛盾')
            present,value=('wide' in actual or 'width' in actual,actual.get('wide',actual.get('width')))
        elif name=='SkuPromise' and not present:
            present,value=_at(actual,'logistics.promiseId')
        if not present:
            if field.get('value') in (None,'') and name in known:
                continue
            raise ValueError(f'未从当前商品核实原字段 {name}')
        if _same(field.get('value'),value,name):
            continue
        if not historical or value is None or isinstance(value,(dict,list)) or type(value) is bool:
            raise ValueError(f'编辑模板与当前商品的 {name} 不一致')
        field['value']=str(value) if isinstance(field.get('value'),str) else value


def align_schema(schema,detail,pid,catalog,*,historical):
    """Align the approved body's SKU bindings to current IDs, independently of merchant codes."""
    schema = deepcopy(schema)
    top=edits.components(schema)
    groups=top['SKUS']['value']
    rows=edits.sku_rows(detail,pid)
    ids_by_spec={}
    for sid,row in rows.items():
        if not isinstance(row.get('saleAttrs'),list):
            raise ValueError('当前商品 SKU 销售属性未完整回读')
        ids_by_spec.setdefault(_sale_key(row['saleAttrs'],submitted=False),[]).append(sid)
    declarations = {item['componentCode']:item for item in _nodes(catalog)}
    checked = deepcopy(detail)
    projected = edits.sku_rows(checked,pid)
    group_keys={}
    seen=set()
    product=detail['productInfo']
    _scalars(top,product,PRODUCT,{'SKUS','WareSkuImg','LongImg','WareEditor','CategoryGroupList',
             'PayMethodLimit','WareSevenDayReturn'},declarations,historical=historical)
    for group in groups:
        fields=edits.components(group['value'])
        sales=fields.get('VenderCategoryValue',{}).get('value') or []
        if historical:
            options=ids_by_spec.get(_sale_key(sales,submitted=True),[])
            if len(options)!=1:
                raise ValueError('原通过体与目标当前销售规格不能唯一对应')
            sid=options[0]
            if 'SkuId' in fields and str(fields['SkuId'].get('value')) != sid:
                raise ValueError('历史请求中的 SKU ID 与当前规格证据不符')
            if 'SkuId' not in fields:
                fields['SkuId']={'componentCode':'SkuId','value':int(sid)}
                group['value'].append(fields['SkuId'])
            if 'SkuUUid' in fields:
                fields['SkuUUid']['value']=sid
        else:
            sid=str(fields.get('SkuId',{}).get('value') or '')
        if sid not in rows or sid in seen:
            raise ValueError('编辑模板 SKU ID 缺失、重复或与当前商品不符')
        seen.add(sid)
        row=rows[sid]
        if _sale_key(sales,submitted=True) != _sale_key(row['saleAttrs'],submitted=False):
            raise ValueError(f'SKU {sid} 的展示值或结构化分项与当前官方回读不同')
        axes = {str(a['attrId']):a for a in row['saleAttrs']}
        for cell in sales:
            props=edits.properties(cell)
            live=axes[cell['componentCode'].removeprefix('sale-prop-')]
            for key,value in (('index',live.get('indexId') or live.get('dim')),('attrName',live.get('attrName')),
                              ('attrValuesSeqNo',live.get('attrValuesSeqNo'))):
                if props.get(key) not in ('',None) and str(props[key]) != str(value):
                    raise ValueError(f'SKU {sid} 的销售属性 {key} 未能对上当前目标')
        _scalars(fields,row,SKU,{'SkuStockNum','VenderCategoryValue','SkuAttr','SkuMainImage',
                 'SkuRectangleImage','SkuGgtImage'},declarations,historical=historical,sku=True)
        if historical:
            by_attr={str(a['attrId']):a for a in projected[sid]['saleAttrs']}
            for cell in sales:
                props=edits.properties(cell)
                attr=by_attr[cell['componentCode'].removeprefix('sale-prop-')]
                prior=props.get('mappingId')
                if not prior or (attr.get('mappingId') and str(attr['mappingId'])!=str(prior)):
                    raise ValueError('原通过体的图片绑定与目标当前编辑映射不一致')
                actual=str(attr.get('attrValues') or '')
                if actual and group_keys.setdefault(actual,str(prior))!=str(prior):
                    raise ValueError('目标图片分组的原绑定无法唯一证明')
                attr['mappingId']=prior
    if seen!=set(rows) or len(set(group_keys.values()))!=len(group_keys):
        raise ValueError('原通过体与目标 SKU 或图片分组未能一一对应')
    if historical:
        for kind in ('mainImages','rectangleImages'):
            for group in (checked.get('material') or {}).get(kind) or []:
                key=str(group['uuid'])
                group['uuid']=group_keys.get(key,key)
    return schema,checked


def verify_galleries(schema,detail,*,historical):
    """Compare group ownership and exact ordered URLs before allowing full-edit submission."""
    checked=deepcopy(detail)
    material=checked.get('material') or {}
    top=edits.components(schema)
    for kind,main_code,sku_code in (('mainImages','WareSkuImg','SkuMainImage'),('rectangleImages','LongImg','SkuRectangleImage')):
        submitted={}
        groups=[top.get(main_code,{})]+[edits.components(entry['value']).get(sku_code,{}) for entry in top['SKUS']['value']]
        for group in groups:
            seen=set()
            for image in group.get('value') or []:
                props=edits.properties(image)
                gid=str(props.get('colorId') or '')
                order=int(props['orderSort'])
                key=(gid,order)
                if (not gid or str(props.get('imgRefId') or gid)!=gid or key in seen or
                        not isinstance(props.get('imgUrl'),str) or not props['imgUrl'] or order<1):
                    raise ValueError(f'原模板的 {kind} 图组、顺序或来源不完整')
                seen.add(key)
                if submitted.setdefault(gid,{}).setdefault(order,props['imgUrl'])!=props['imgUrl']:
                    raise ValueError('原编辑体中的主图图组含冲突')
        live=edits.unique((str(row['uuid']),row) for row in material.get(kind) or [])
        if set(submitted)!=set(live):
            raise ValueError(f'原编辑体缺少目标实际 {kind} 图组或带有其他图组')
        for gid,row in live.items():
            actual=edits.unique((int(img['orderSort']),img['imgUrl']) for img in row['imageInfoList'])
            desired=submitted[gid]
            if set(desired)!=set(range(1,len(desired)+1)) or set(actual)!=set(range(1,len(actual)+1)):
                raise ValueError('当前图位不连续')
            if desired==actual:continue
            if (not historical or not desired or len(actual)!=len(desired)+1
                    or actual[len(actual)]!=desired[1] or any(actual[p]!=url for p,url in desired.items())):
                raise ValueError(f'原目标通过体与当前 {kind} 原图或位置不同，未覆盖')
            # The server can append one duplicate of position one (see the binding reference).
            # The archived request intentionally did not submit this server-managed trailing slot.
            row['imageInfoList']=[i for i in row['imageInfoList'] if int(i['orderSort'])!=len(actual)]
    material.pop('rectangleImages',None)  # verified separately above; the existing title/attribute checker validates mainImages
    return checked


def published_schema(root, folder, frozen, target, pid):
    """A submitted request may be used only for this target and the same frozen revision."""
    from .shop_copy_batch import publication_directory
    publication=publication_directory(root)
    pointer=read_json(root/'current.json',{})
    response=read_json(publication/'result.json',{})
    state=read_json(publication/'publish-body.submit-state.json',{})
    receipt=response.get('data') if isinstance(response.get('data'),dict) else {}
    if (pointer.get('sourceShop')!=frozen['sourceShop'] or pointer.get('targetShop')!=target
            or pointer.get('sourceProductId')!=frozen['sourceProductId'] or pointer.get('revision')!=frozen['sha256']
            or state.get('stage') not in ('PUBLISHED','SUBMITTING')
            or response.get('success') is not True or not (receipt.get('productId') or receipt.get('applyId'))
            or any(str(value)!=str(pid) for value in (receipt.get('productId'),state.get('productId')) if value)):
        raise ValueError('缺少可归属到这件原目标商品的官方受理回执')
    # A resolved application-only association was already checked by publication_state.
    if not receipt.get('productId') and not state.get('productId'):
        binding=read_json(publication/'target-binding.json',{})
        if str(binding.get('productId'))!=str(pid) or binding.get('kind')!='original-application':
            raise ValueError('原申请的目标商品编号尚未核实')
    path=publication/'publish-body.json'
    body=read_json(path,{})
    plan=read_json(folder/'pilot.json',{})
    delivery=read_json(folder/'delivery-evidence.json')
    if (not body or plan.get('body')!=body or plan.get('target')!=target or plan.get('revision')!=frozen['sha256']
            or plan.get('intent')!='publish-one' or not isinstance(delivery,dict)
            or plan.get('approval')!=edits.digest({'source':frozen['sha256'],'target':target,'body':body,'delivery':delivery})
            or state.get('payloadSha256') and state['payloadSha256']!=file_sha(path)):
        raise ValueError('目标原发布体与原任务的审批指纹或受理记录不一致')
    schema=json.loads(body['schema'],object_pairs_hook=edits.unique)
    if not isinstance(schema,list):
        raise ValueError('原发布体没有完整组件')
    return schema
