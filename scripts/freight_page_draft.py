"""Build and verify a freight-template form from host-observed fields; no browser or network."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.shop_copy_delivery import _id, _number, _rules, _same_shop, _templates
from heideng_merchant.safety import atomic_json, read_json
from heideng_merchant.state import FileLock


RATES = ('firstQuantity','firstFee','nextQuantity','nextFee')


def digest(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _payment_methods(zone, rules):
    # Who pays for freight and which payment tab the rule belongs to are independent.
    for record in (zone,rules):
        if 'paymentMethod' in record or 'paymentMethods' in record:
            methods=record.get('paymentMethods',[record.get('paymentMethod')])
            if not isinstance(methods,list) or any(not isinstance(x,str) or not x.strip() for x in methods):
                raise ValueError('支付方式需要源模板页面实际显示的分组名称')
            if 'paymentMethod' in record and methods != [record['paymentMethod']]:
                raise ValueError('源规则中的支付方式分组不一致')
            if len(set(methods))!=len(methods):
                raise ValueError('同一规则重复列出支付方式')
            return methods
    return []


def make_draft(evidence, source_template_id):
    source=evidence['source']
    target=evidence['target']['shop']
    if not _same_shop(source['shop'],source['shop']) or not _same_shop(target,target) or str(target['shopId'])==str(source['shop']['shopId']):
        raise ValueError('创建规则表需要两个不同的已核验店铺')
    template=source.get('defaultFreight') if source_template_id=='default' else _templates(source,'freightTemplates').get(source_template_id)
    rules=_rules(template or {},'freightTemplates')
    fields={k:v for k,v in rules.items() if k not in ('zones','paymentMethods','paymentMethod')}
    rows=[]
    gaps=[]
    for i,zone in enumerate(rules['zones'],1):
        methods=_payment_methods(zone,rules)
        if not methods:
            gaps.append(f'源运费规则第 {i} 行缺少页面上的支付方式分组')
        terms={k:v for k,v in zone.items() if k not in ('regions','paymentMethod','paymentMethods')}
        for name in RATES:
            if name in terms:
                terms[name]=_number(terms[name],positive=name.endswith('Quantity'))
        for method in methods or [None]:
            row={'paymentMethod':method,'regions':zone['regions'],'fields':terms}
            rows.append({**row,'rowKey':digest(row)})
    if len({r['rowKey'] for r in rows})!=len(rows):
        gaps.append('源页面有完全相同的支付方式、地区和费用行，请核对重复项')
    draft={'sourceShop':source['shop'],'targetShop':target,'sourceTemplateId':source_template_id,
           'sourceReceipt':template['receipt'],'globalFields':fields,'ruleTable':rows}
    methods={'weight':'按重量','item':'按件','volume':'按体积'}
    payers={'buyer':'买家承担','seller':'卖家承担','conditional':'按条件'}
    display=[{'支付方式':r['paymentMethod'],'适用地区':r['regions'],'计费方式':methods.get(fields.get('chargeBy')),
              '单位':fields.get('unit'),'币种':fields.get('currency'),'运费承担方':payers[fields['payer']],
              '首件或首重':r['fields'].get('firstQuantity'),'首费':r['fields'].get('firstFee'),
              '续件或续重':r['fields'].get('nextQuantity'),'续费':r['fields'].get('nextFee'),
              '其他条款':{k:v for k,v in r['fields'].items() if k not in RATES}} for r in rows]
    return {**draft,'draftFingerprint':digest(draft),'status':'needs-source-evidence' if gaps else 'form-draft-ready',
            'missing':gaps,'创建规则表':display,'platformWrites':0,
            'pageSteps':['在已核验的目标店窗口按创建规则表找到支付方式和该分组内的具体规则行。',
                         '从该行打开地区选择；需要时展开上级地区，再逐项操作对应地区复选框。',
                         '回读复选框选中状态、该行已选地区摘要、首续数量及费用；逐行核对其他支付分组。',
                         '已授权并保存后重新打开目标模板，记录目标店模板 ID、全部规则和原回执。']}


def _checked_regions(picker):
    if not isinstance(picker,dict) or picker.get('complete') is not True or not picker.get('receipt'):
        return None
    boxes=picker.get('controls')
    if not isinstance(boxes,list):
        return None
    selected=[]
    for box in boxes:
        if not isinstance(box,dict) or box.get('role')!='checkbox' or box.get('visible') is False:
            continue  # Expanding a tree item or clicking its text supplies no checked state.
        checked=box.get('checked')
        if checked=='mixed':
            continue  # Only checked delivery regions, not their partially selected ancestors.
        if checked in ('true','false'):
            checked=checked=='true'
        if type(checked) is not bool or not isinstance(box.get('region'),str) or not box['region'].strip():
            return None
        if checked:
            selected.append(box['region'])
    return sorted(selected) if len(set(selected))==len(selected) else None


def verify_form(draft, observed):
    if draft['missing']:
        return draft
    if not _same_shop(observed.get('shop'),draft['targetShop']) or observed.get('draftFingerprint')!=draft['draftFingerprint']:
        raise ValueError('页面回读与本次目标店或创建规则表不一致')
    if observed.get('stage') not in ('editing','reopened-detail') or not observed.get('receipt') or observed.get('allRowsVisible') is not True:
        raise ValueError('需要完整规则行、页面阶段和本次可见页的回读凭据')
    issues=[]
    if draft['globalFields']!=observed.get('globalFields'):
        issues.append('模板级计费、单位、币种、承担方或附加条件不同')
    expected={row['rowKey']:row for row in draft['ruleTable']}
    seen=Counter()
    locators=set()
    rows=observed.get('rows')
    if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('rowKey'),str) for r in rows):
        raise ValueError('需要目标页面各个实际规则行及对应的行标识')
    for actual in rows:
        key=actual.get('rowKey')
        seen[key]+=1
        row=expected.get(key)
        if row is None:
            issues.append('目标模板出现额外规则行')
            continue
        method=row['paymentMethod']
        where=f'{method} / {", ".join(row["regions"])}'
        locator=actual.get('rowRef')
        if not isinstance(locator,str) or not locator.strip() or (method,locator) in locators or actual.get('paymentMethod')!=method:
            issues.append(where+'：未唯一定位该支付分组的规则行')
        elif locator:
            locators.add((method,locator))
        selected=_checked_regions(actual.get('regionPicker'))
        summary=actual.get('rowRegions')
        if selected!=row['regions'] or not isinstance(summary,list) or any(not isinstance(v,str) for v in summary) or sorted(summary)!=row['regions']:
            issues.append(where+'：请核对地区复选框的选中状态和该行已选地区摘要')
        if not isinstance(actual.get('fields'),dict):
            issues.append(where+'：缺少本行实际费用或区域条件')
            continue
        fields=dict(actual['fields'])
        for name in RATES:
            if name in fields:
                try:fields[name]=_number(fields[name],positive=name.endswith('Quantity'))
                except ValueError:fields[name]=None
        if fields!=row['fields']:
            issues.append(where+'：首续数量、金额或本行例外条件不同')
    if seen!=Counter(expected.keys()):
        issues.append('目标完整规则行与源规则表的范围或数量不一致')
    result={**draft,'status':'form-differences' if issues else 'form-matches','differences':issues,
            'pageReceipt':observed['receipt'],'evidenceSource':'host-observed-page','livePageAccess':False,
            'savedTemplateVerified':False}
    if not issues and observed['stage']=='reopened-detail':
        tid=_id(observed.get('templateId'))
        if not tid:
            raise ValueError('重新打开的目标模板详情缺少官方模板 ID')
        result.update(status='reopened-template-verified',targetTemplateId=tid,savedTemplateVerified=True)
    return result


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='backslashreplace')
    parser=argparse.ArgumentParser(description='生成目标店运费创建规则表，核验宿主从已授权可见页面回读的结果')
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--source-template',required=True,help='实际源运费模板 ID，店铺有效默认规则使用 default')
    parser.add_argument('--readback',type=Path,help='目标店可见表单回读')
    parser.add_argument('--output',type=Path,help='另存本机 JSON 回执')
    args=parser.parse_args(argv)
    try:
        result=make_draft(read_json(args.evidence),args.source_template)
        if args.readback:
            result=verify_form(result,read_json(args.readback))
        if args.output:
            output=args.output.resolve()
            lock=output.with_name(output.name+'.lock')
            if {output,lock}.intersection(path.resolve() for path in (args.evidence,args.readback) if path):
                raise ValueError('本机输出与原证据文件同名')
            with FileLock(lock):
                if output.exists():
                    if read_json(output)!=result:
                        raise ValueError('请用独立文件保留新回执，已有回执内容不同')
                else:
                    atomic_json(output,result)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in ('form-draft-ready','form-matches','reopened-template-verified') else 2
    except (KeyError,TypeError,ValueError,OSError,RuntimeError) as exc:
        print(json.dumps({'status':'needs-page-evidence','reason':str(exc),'platformWrites':0},ensure_ascii=False))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
