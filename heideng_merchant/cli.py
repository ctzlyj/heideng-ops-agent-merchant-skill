"""Agent interface: dispatch actual mature Skills, not rebuilt business operations."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from . import VERSION, SKILL_NAME
from .state import installed_state
from .safety import SafetyError, redact
from .mature_runtime import ROUTES, MatureSourceUnavailable, run, status

def build_parser():
    parser = argparse.ArgumentParser(description='黑灯商家版：复用成熟业务 Skill')
    parser.add_argument('--state', type=Path, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    st=sub.add_parser('status');st.add_argument('--detail',action='store_true',help='维护者查看完整来源与能力清单')
    k=sub.add_parser('key',help='merchant OS secret maintenance, never prints a key')
    k.add_argument('action',choices=('forget',))
    u = sub.add_parser('update', help='software maintenance only; never business scheduling')
    us = u.add_subparsers(dest='update_command', required=True)
    for name in ('status','check','apply','enable','disable','recover','repair-switch'): us.add_parser(name)
    v = us.add_parser('usage'); v.add_argument('action', choices=('begin','heartbeat','end')); v.add_argument('--task-id',required=True); v.add_argument('--component',action='append'); v.add_argument('--receipt'); v.add_argument('--loaded-version')
    p = sub.add_parser('run')
    p.add_argument('--entry', help='registered source entry only')
    p.add_argument('capability', choices=sorted(ROUTES))
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    task = sub.add_parser('task-context', help='按已核验店铺查询原任务和回执')
    task.add_argument('--shop-id', required=True)
    task.add_argument('--vender-id', required=True)
    task.add_argument('--task-id')
    task.add_argument('--goal', choices=['materials','listing','sample','creative','sku-edit','diagnosis'])
    task.add_argument('--product-id', help='目标商品 SPU')
    task.add_argument('--source-product-id', help='复刻来源 SPU')
    sample = sub.add_parser('sample-context', help='找回已认可的原样图、对应规格链接和上传回执')
    sample.add_argument('--shop-id')
    sample.add_argument('--vender-id')
    sample.add_argument('--product-id')
    sample.add_argument('--task-id')
    sample.add_argument('--image-sha')
    fee = sub.add_parser('confirm-image-fee', help='商家一次确认本次图片费用与计费请求上限')
    fee.add_argument('--quote', type=Path, required=True)
    fee.add_argument('--output', type=Path, required=True)
    fee.add_argument('--max-requests', type=int, required=True)
    fee.add_argument('--units', nargs='+', help='从可拆分报价选定本次实际制作的图号')
    fee.add_argument('--billing', choices=['credits','requests','amount'], default='requests', help='新生图报价自动使用 LTS4AI 积分；旧报价保留原口径')
    fee.add_argument('--currency')
    fee.add_argument('--max-amount')
    fee.add_argument('--unit-price-upper-bound')
    fee.add_argument('--price-evidence')
    evidence = sub.add_parser('compare-evidence', help='同店同商品广告、成交、客服、退货两期汇总核对')
    evidence.add_argument('--shop-id', required=True)
    evidence.add_argument('--vender-id', required=True)
    evidence.add_argument('--spu-id', required=True)
    evidence.add_argument('--input', type=Path, required=True)
    evidence.add_argument('--save-handoff', action='store_true', help='保存本次比较结果和输入中的 handoff 供下个岗位续办')
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state = args.state or installed_state(Path(__file__).resolve().parents[1])
        if args.command == 'sample-context':
            from .commercial_tasks import accepted_sample_context
            if any(value and not value.isdecimal() for value in (args.shop_id,args.vender_id,args.product_id)):
                raise SafetyError('invalid-shop-or-product-identity')
            result = accepted_sample_context(state,shop_id=args.shop_id,vender_id=args.vender_id,
                                             product_id=args.product_id,task_id=args.task_id,image_sha=args.image_sha)
            print(json.dumps(redact(result),ensure_ascii=False))
            return 0
        if args.command == 'confirm-image-fee':
            from .fee_consent import confirm_fee
            try:
                price = dict(currency=args.currency, maxAmount=args.max_amount,
                             unitPriceUpperBound=args.unit_price_upper_bound, priceEvidence=args.price_evidence)
                if args.output.resolve() == args.quote.resolve():
                    raise ValueError('报价与费用回执需保存在两个文件')
                approval = confirm_fee(json.loads(args.quote.read_text(encoding='utf-8-sig')), state, args.output,
                    max_requests=args.max_requests, billing=args.billing, price=price if args.billing=='amount' else None,
                    selected_units=args.units, quote_path=args.quote)
            except (ValueError, OSError, TypeError) as error:
                raise SafetyError(str(error)) from None
            print(json.dumps({'status':'approved','approvalRef':approval['approvalRef'],'output':str(args.output)},ensure_ascii=False))
            return 0
        if args.command == 'compare-evidence':
            from .commerce_evidence import compare_evidence
            if not all(key.isdecimal() for key in (args.shop_id, args.vender_id, args.spu_id)):
                raise SafetyError('invalid-shop-or-product-identity')
            try:
                data = json.loads(args.input.read_text(encoding='utf-8-sig'))
                result = compare_evidence(data, args.shop_id, args.vender_id, args.spu_id)
                if args.save_handoff:
                    from .commerce_evidence import save_handoff
                    result['handoff'] = save_handoff(state, result, data.get('handoff'))
            except (ValueError, TypeError, KeyError, OSError) as exc:
                raise SafetyError(f'经营报表不能对齐：{exc}') from None
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 0
        if args.command == 'task-context':
            from .merchant_tasks import task_context
            if not args.shop_id.isdecimal() or not args.vender_id.isdecimal():
                raise SafetyError('invalid-shop-identity')
            print(json.dumps(redact(task_context(state,args.shop_id,args.vender_id,args.task_id,
                goal=args.goal, product_id=args.product_id, source_product_id=args.source_product_id)),ensure_ascii=False))
            return 0
        if args.command == 'key':
            from .merchant_key_store import forget_key
            forget_key(state)
            print(json.dumps({'status':'forgotten','merchantKeyOnly':True,'businessExecuted':False}));return 0
        if args.command == 'update':
            from .runtime_dependencies import reexec_update_runtime
            switched=reexec_update_runtime(state)
            if switched is not None:return switched
            from . import update_client as updater
            name = args.update_command
            if name == 'status': result = updater.status(state)
            elif name == 'check': result = updater.check(state, force=True)
            elif name == 'apply': result = updater.apply(state)
            elif name == 'enable':
                result = updater.set_enabled(state, True); updater.maybe_schedule(state)
            elif name == 'disable': result = updater.set_enabled(state, False)
            elif name == 'recover': result = updater.recover(state, confirm=True)
            elif name == 'repair-switch': result = updater.recover_switch(state)
            else:
                result = updater.usage(state, args.action, args.task_id, components=args.component, receipt=args.receipt, loaded_version=args.loaded_version)
                if args.action == 'end': updater.maybe_schedule(state)
            print(json.dumps(redact(result), ensure_ascii=False)); return 0
        if args.command == 'status':
            from .update_client import consume_notice
            try: notice = consume_notice(state)
            except Exception: notice = {'reason':'update-status-unavailable','businessUsable':True,'action':'diagnose-updater-settings-without-resetting-trust'}
            from .merchant_experience import merchant_status
            result={'skill':SKILL_NAME,'version':VERSION,'architecture':'mature-skill-dispatch','merchantSummary':merchant_status(VERSION),'softwareUpdateNotice':notice}
            if args.detail:result['detail']=status()
            print(json.dumps(result,ensure_ascii=False))
            return 0
        return run(args.capability, args.arguments, state=state, entry=args.entry)
    except MatureSourceUnavailable as error:
        from .merchant_experience import error_summary
        print(json.dumps({'status': 'blocked', 'error': redact(str(error)), 'capability': error.capability, 'builtinFallback': False, **error_summary(error)}, ensure_ascii=False))
        return 2
    except SafetyError as error:
        from .merchant_experience import error_summary
        print(json.dumps({'status':'blocked', 'error': redact(str(error)), **error_summary(error)}, ensure_ascii=False))
        return 2

    finally:
        if args.command != 'update':
            try:
                from .update_client import maybe_schedule
                maybe_schedule(state)
            except Exception: pass

if __name__ == '__main__':
    raise SystemExit(main())
