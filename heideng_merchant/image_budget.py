"""Bind a paid image request to the merchant's approval before contacting the provider."""
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
import uuid
from pathlib import Path

from .safety import atomic_json, read_json, safe_join
from .state import FileLock


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return sha256(encoded.encode('utf-8')).hexdigest()


def _positive_amount(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('费用上限或单次价格无效') from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError('费用上限或单次价格须为有限正数')
    return amount


def validate_terms(approval, *, scope, units):
    """Validate the actual task scope and the stable list of approved image IDs."""
    if not isinstance(approval, dict) or not isinstance(scope, dict) or not scope or approval.get('scope') != scope:
        raise ValueError('请先取得当前店铺与任务范围的生图费用批准')
    expected = list(units)
    approved = approval.get('units')
    if not isinstance(approved, list) or not expected or any(
        not isinstance(unit, str) or not unit.strip() for unit in expected + approved
    ):
        raise ValueError('请列出已批准的图组')
    if len(set(expected)) != len(expected) or sorted(approved) != sorted(expected):
        raise ValueError('批准的图组与实际计划不一致')
    limit = approval.get('maxRequests')
    if type(limit) is not int or limit < 1:
        raise ValueError('生图需要明确的计费请求上限')
    if not isinstance(approval.get('approvalRef'), str) or not approval['approvalRef'].strip():
        raise ValueError('缺少商家费用批准的原始消息或回执引用')
    if approval.get('billing') == 'credits':
        from .image_models import TIER_CREDITS, resolution_tier
        costs = approval.get('creditCostsByUnit')
        if (not isinstance(costs,dict) or set(costs) != set(approved)
                or any(type(c) is not int or c not in TIER_CREDITS.values() for c in costs.values())
                or limit < len(costs)):
            raise ValueError('图位积分和计费请求上限不一致')
        for unit, cost in costs.items():
            size = scope.get('imageSizes',{}).get(unit) or scope.get('imageSize')
            if size and cost != TIER_CREDITS[resolution_tier(size)]:
                raise ValueError('图位积分与实际请求的分辨率不一致')
        cap = sum(costs.values()) + (limit-len(costs))*max(costs.values())
        if approval.get('maxCredits') != cap:
            raise ValueError('批准积分与报价上限不一致')
    elif approval.get('billing') == 'amount':
        evidence = approval.get('priceEvidence')
        if not re.fullmatch('[A-Z]{3}', str(approval.get('currency', ''))) or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('按金额控制费用需要币种和可核验的价格依据')
        if _positive_amount(approval.get('unitPriceUpperBound')) * limit > _positive_amount(approval.get('maxAmount')):
            raise ValueError('按单次最高费用和请求数计算将超出批准金额')
    elif approval.get('billing') != 'requests':
        raise ValueError('金额未知时需要商家明确接受按计费请求数控制')
    return approval


def validate_approval(approval, *, scope, units):
    from .fee_consent import verified_receipt
    validate_terms(approval, scope=scope, units=units)
    verified_receipt(approval)
    return approval


def reserve_request(directory, approval, *, scope, units, request_id, previous_receipt=None,
                    unresolved_reservation=None):
    """Keep uncertain attempts reserved across crashes, overlapping workers and reruns."""
    validate_approval(approval, scope=scope, units=units)
    if request_id not in approval['units']:
        raise ValueError('该图不在商家批准范围内')
    ledger = safe_join(Path(directory), '.state/paid-image-budget.json')
    with FileLock(ledger.with_suffix('.lock')):
        data = read_json(ledger, {'approvals': {}, 'requests': {}})
        reference = approval['approvalRef']
        digest = _digest(dict(approval, units=sorted(approval['units'])))
        if reference in data['approvals'] and data['approvals'][reference] != digest:
            raise ValueError('费用批准范围已改变，请核对批准记录')
        fingerprint = _digest([scope, request_id])
        if unresolved_reservation is not None:
            parent = data['requests'].get(unresolved_reservation, {})
            if (previous_receipt is not None or parent.get('unit') != request_id or
                    parent.get('approvalRef') == reference or scope.get('possibleDuplicateCharge') is not True or
                    scope.get('unresolvedRequests', {}).get(request_id) != unresolved_reservation):
                raise ValueError('追加尝试须关联原未知请求和独立的重复计费风险批准')
            # The same outstanding attempt can have at most one direct successor.
            fingerprint = _digest(['replace-unresolved', unresolved_reservation])
        elif previous_receipt is not None:
            # Only callers that verified a completed original request may start a revision.
            if not isinstance(previous_receipt, dict) or previous_receipt.get('status') != 'SUCCEEDED' or not previous_receipt.get('sha256'):
                raise ValueError('重做需要可核对的原成功回执')
            fingerprint = _digest([scope, request_id, previous_receipt])
        previous = data['requests'].get(fingerprint)
        if previous and (previous.get('state') != 'reserving' or previous.get('approvalRef') != reference):
            raise ValueError('原生图请求已预占，请先查原回执，禁止重复发送')
        used = sum(item['approvalRef'] == reference for item in data['requests'].values())
        if not previous and used >= approval['maxRequests']:
            raise ValueError('已达到商家批准的计费请求上限')
        from .fee_consent import charge_attempt
        data['approvals'][reference] = digest
        entry = previous or {'approvalRef': reference, 'unit': request_id, 'state': 'reserving',
                             'intent': uuid.uuid4().hex}
        data['requests'][fingerprint] = entry
        if unresolved_reservation is not None:
            entry['replacesUnknown'] = unresolved_reservation
        atomic_json(ledger, data)
        try:
            charge_attempt(approval, directory=directory, fingerprint=fingerprint, intent=entry['intent'], unit=request_id)
        except ValueError:
            # The central receipt declined this reservation. No dispatch has been authorized.
            del data['requests'][fingerprint]
            atomic_json(ledger, data)
            raise
        entry['state'] = 'reserved'
        atomic_json(ledger, data)
        return {'reserved': used + (0 if previous else 1), 'limit': approval['maxRequests'], 'requestId': request_id,
                'reservationId': fingerprint}
