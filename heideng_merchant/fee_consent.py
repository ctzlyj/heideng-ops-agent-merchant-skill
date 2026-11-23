"""Issue and check local merchant decisions for paid image work."""
import os
import hashlib
import json
import re
import uuid
from pathlib import Path

from .safety import atomic_json, read_json, safe_join
from .state import FileLock, merchant_home


def _receipt_path(state, reference):
    if not isinstance(reference, str) or not re.fullmatch(r'fee-[a-f0-9]{32}', reference):
        raise ValueError('本次报价需要商家确认，请使用 confirm-image-fee')
    return safe_join(Path(state), 'fee-consents/' + reference + '.json')


def verified_receipt(approval, state=None):
    path = _receipt_path(state or merchant_home(), approval.get('approvalRef'))
    record = read_json(path, {})
    if not record or approval != record.get('approval'):
        raise ValueError('商家费用回执缺失或内容已变动，请核对本次报价')
    return path


def charge_attempt(approval, *, directory, fingerprint, intent, unit=None):
    """Count an intent before dispatch, including copies of the same task directory."""
    path = verified_receipt(approval)
    with FileLock(path.with_suffix('.lock')):
        record = read_json(path)
        attempts = record['attempts']
        entry = {'directory': str(Path(directory).resolve()), 'intent':intent}
        if approval.get('billing') == 'credits':
            entry.update(unit=unit, credits=approval['creditCostsByUnit'][unit])
        if attempts.get(fingerprint) == entry:
            return
        if fingerprint in attempts:
            raise ValueError('原生图请求已预占，请先查原回执')
        if len(attempts) >= approval['maxRequests']:
            raise ValueError('已达到商家批准的计费请求上限')
        if 'credits' in entry and sum(v['credits'] for v in attempts.values()) + entry['credits'] > approval['maxCredits']:
            raise ValueError('已达到商家批准的积分上限')
        attempts[fingerprint] = entry
        atomic_json(path, record)


def _ask_merchant(message):
    if os.name == 'nt':
        import ctypes
        # YES/NO, default No, foreground, topmost. Works even without Tk installed.
        return ctypes.windll.user32.MessageBoxW(None, message, '黑灯 · 确认本次生图费用',
                                                 0x04 | 0x100 | 0x10000 | 0x40000) == 6
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
    except (ImportError, RuntimeError, OSError) as error:
        raise ValueError('当前无法显示商家费用确认窗口，请在商家桌面前台打开') from error
    except Exception as error:
        # TclError is only available when the import succeeded.
        if type(error).__name__ != 'TclError':
            raise
        raise ValueError('当前无法显示商家费用确认窗口，请在商家桌面前台打开') from error
    try:
        root.withdraw()
        root.attributes('-topmost', True)
        return messagebox.askyesno('黑灯 · 确认本次生图费用', message, parent=root, default='no')
    finally:
        root.destroy()


def confirm_fee(quote, state, output, *, max_requests, billing='requests', price=None, selected_units=None, quote_path=None):
    from .image_budget import validate_terms
    from .image_models import TIER_CREDITS

    if not isinstance(quote, dict):
        raise ValueError('需要原任务的图片报价')
    quote = quote.get('replacementQuote') or quote.get('feeQuote') or quote
    units = quote.get('units')
    scope = quote.get('scope')
    pending = quote.get('pendingUnits', units)
    if (not isinstance(units, list) or not isinstance(pending, list) or
            not all(isinstance(k, str) and k for k in units + pending) or
            len(set(pending)) != len(pending) or not set(pending).issubset(units)):
        raise ValueError('报价图位不在任务范围内')
    if not pending:
        raise ValueError('没有待生成图片，可直接复用原素材和回执')
    deferred = []
    if selected_units is not None:
        if quote.get('canSelectUnits') is not True:
            raise ValueError('该报价须按完整范围执行，请从原任务重新生成所选图位的报价')
        if (not isinstance(selected_units, (list, tuple)) or not selected_units or
                not all(isinstance(k, str) for k in selected_units) or len(set(selected_units)) != len(selected_units)
                or not set(selected_units).issubset(pending)):
            raise ValueError('请从原报价待做图位中选择具体图号')
        deferred = [key for key in pending if key not in selected_units]
        units = pending = list(selected_units)
    if type(max_requests) is int and len(pending) > max_requests:
        raise ValueError(f'当前待做 {len(pending)} 张，超过请求上限 {max_requests}；请先明确优先图位或安排复用，再确认费用')
    approval = dict(scope=scope, units=units, maxRequests=max_requests, billing=billing,
                    approvalRef='fee-' + uuid.uuid4().hex)
    if 'creditCostsByUnit' in quote or billing == 'credits':
        costs = quote.get('creditCostsByUnit')
        if (not isinstance(costs,dict) or billing not in ('credits','requests') or
                any(type(costs.get(k)) is not int or costs[k] not in TIER_CREDITS.values() for k in pending)):
            raise ValueError('请使用原任务的逐图积分报价')
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError('请指定获准的计费请求数')
        billing = 'credits'
        units = list(pending)
        costs = {k:costs[k] for k in units}
        approval.update(billing=billing, units=units, creditCostsByUnit=costs,
                        maxCredits=sum(costs.values())+(max_requests-len(costs))*max(costs.values()))
    if price:
        approval.update({key: price.get(key) for key in ('currency','maxAmount','unitPriceUpperBound','priceEvidence')})
    validate_terms(approval, scope=scope, units=units or [])
    output = Path(output)
    if output.resolve().is_relative_to((Path(state)/'fee-consents').resolve()):
        raise ValueError('任务回执请保存在任务目录')
    identity = scope.get('shopIdentity') or {}
    shop = identity.get('shopName') or scope.get('shopName') or scope.get('shop') or scope.get('venderId') or scope.get('profile')
    if isinstance(shop, dict):
        shop = shop.get('shopName') or shop.get('venderId')
    outputs = {o.get('id'):o for o in scope.get('outputs') or [] if isinstance(o, dict)}
    labels = {'main':'共享主图', 'sku':'规格图', 'detail':'详情图'}
    kinds = {}
    for unit in pending:
        row = outputs.get(unit, {})
        kind = labels.get(row.get('role'), '图片')
        kinds[kind] = kinds.get(kind, 0) + 1
    summary = '、'.join(f'{k} {v} 张' for k,v in kinds.items())
    lines = [f"店铺或任务：{shop or scope.get('task') or scope.get('source') or '本次图片任务'}",
             f"本次待生成 {len(pending)} 张（{summary}）。最多发送 {max_requests} 次计费请求，含返工。",
             '图位：' + '、'.join(units[:12]) + (f' 等 {len(units)} 项' if len(units)>12 else '')]
    products = scope.get('products') or scope.get('sourceProduct')
    if products:
        lines.insert(1, '商品：' + str(products)[:240])
    if deferred:
        lines.append(f'其余 {len(deferred)} 张暂缓。若交付需整套图片，须补齐或复用后才能发布。')
    if scope.get('possibleDuplicateCharge'):
        lines.append('原请求结果仍未知，可能已经扣费。本次将另发请求，可能再次计费。')
    if billing == 'credits':
        lines.append(f"按画质计费：1K 每张 3 积分、2K 每张 4 积分、4K 每张 5 积分。本次预计 {sum(costs.values())} 积分，含返工最多 {approval['maxCredits']} 积分。实际扣减及可用余额以 LTS4AI 为准。")
    elif billing == 'amount':
        lines.append(f"最高费用 {approval['maxAmount']} {approval['currency']}，每次最高 {approval['unitPriceUpperBound']}。")
    else:
        lines.append('金额未知；仅按上述请求次数封顶。')
    # A new host/chat can use a different delivery filename for the same quote.
    # Serialize the decision by original quote and terms, independent of that filename.
    terms = {k:v for k,v in approval.items() if k != 'approvalRef'}
    anchor = str(Path(quote_path).resolve()) if quote_path else str(output.resolve().parent)
    key = hashlib.sha256(json.dumps([anchor, dict(terms, units=sorted(units))],
                         ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    index = safe_join(Path(state), 'fee-decisions/' + key + '.json')
    with FileLock(index.with_suffix('.lock'), timeout=120):
        existing = read_json(output, {})
        if existing and {k:v for k,v in existing.items() if k != 'approvalRef'} == terms:
            verified_receipt(existing, state)
            atomic_json(index, {'approvalRef':existing['approvalRef']})
            return existing
        previous = read_json(index, {}).get('approvalRef')
        if previous:
            record = read_json(_receipt_path(state, previous), {})
            prior = record.get('approval', {})
            prior_terms = {k:v for k,v in prior.items() if k != 'approvalRef'}
            if (dict(prior_terms, units=sorted(prior.get('units', []))) == dict(terms, units=sorted(units))
                    and prior.get('approvalRef') == previous
                    and max_requests - len(record['attempts']) >= len(pending)):
                atomic_json(output, prior)
                return prior
        if not _ask_merchant('\n\n'.join(lines)):
            raise ValueError('商家未批准本次生图费用，可继续免费工作')
        path = _receipt_path(state, approval['approvalRef'])
        atomic_json(path, {'approval':approval, 'attempts':{}})
        atomic_json(index, {'approvalRef':approval['approvalRef']})
        atomic_json(output, approval)
        return approval
