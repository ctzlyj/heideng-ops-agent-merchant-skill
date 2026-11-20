"""Bind a paid image request to the merchant's approval before contacting the provider."""
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
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


def validate_approval(approval, *, scope, units):
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
    if approval.get('billing') == 'amount':
        evidence = approval.get('priceEvidence')
        if not re.fullmatch('[A-Z]{3}', str(approval.get('currency', ''))) or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('按金额控制费用需要币种和可核验的价格依据')
        if _positive_amount(approval.get('unitPriceUpperBound')) * limit > _positive_amount(approval.get('maxAmount')):
            raise ValueError('按单次最高费用和请求数计算将超出批准金额')
    elif approval.get('billing') != 'requests':
        raise ValueError('金额未知时需要商家明确接受按计费请求数控制')
    return approval


def reserve_request(directory, approval, *, scope, units, request_id, previous_receipt=None):
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
        if previous_receipt is not None:
            # Only callers that verified a completed original request may start a revision.
            if not isinstance(previous_receipt, dict) or previous_receipt.get('status') != 'SUCCEEDED' or not previous_receipt.get('sha256'):
                raise ValueError('重做需要可核对的原成功回执')
            fingerprint = _digest([scope, request_id, previous_receipt])
        if fingerprint in data['requests']:
            raise ValueError('原生图请求已预占，请先查原回执，禁止重复发送')
        used = sum(item['approvalRef'] == reference for item in data['requests'].values())
        if used >= approval['maxRequests']:
            raise ValueError('已达到商家批准的计费请求上限')
        data['approvals'][reference] = digest
        data['requests'][fingerprint] = {'approvalRef': reference, 'unit': request_id, 'state': 'reserved'}
        atomic_json(ledger, data)
        return {'reserved': used + 1, 'limit': approval['maxRequests'], 'requestId': request_id}
