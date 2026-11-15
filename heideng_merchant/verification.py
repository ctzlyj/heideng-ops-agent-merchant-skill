"""Bounded field evidence, including exact SKU selectors; never evaluates expressions."""
from __future__ import annotations
import math
import re
from decimal import Decimal, InvalidOperation
from .safety import SafetyError

_SEGMENT = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)(?:\[([A-Za-z_][A-Za-z0-9_]*)==([1-9][0-9]{0,18})\])?')
_MISSING = object()
MAX_EXPECTED_FIELDS = 1024  # Local evidence budget, not a platform SKU limit.


def business_payload(response):
    current = response
    for _ in range(5):
        if not isinstance(current, dict):
            return current
        if current.get('success') is False or current.get('ok') is False or current.get('status') in ('error', 'FAILED') or current.get('errorList'):
            raise SafetyError('official-business-response-not-successful')
        if 'data' not in current or any(key in current for key in ('productId', 'skuId', 'skuList', 'productInfo', 'applyInfo')):
            return current
        current = current['data']
    raise SafetyError('official-response-envelope-too-deep')


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SafetyError('finite-decimal-evidence-required')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise SafetyError('finite-decimal-evidence-required') from None
    if not result.is_finite():
        raise SafetyError('finite-decimal-evidence-required')
    return result


def _segments(path):
    if not isinstance(path, str) or not path or len(path) > 512:
        raise SafetyError('invalid-verification-field-selector')
    parts = path.split('.')
    if len(parts) > 16:
        raise SafetyError('invalid-verification-field-selector')
    matches = [_SEGMENT.fullmatch(part) for part in parts]
    if not all(matches):
        raise SafetyError('invalid-verification-field-selector')
    return [match.groups() for match in matches]


def validate_expected(expected):
    if not isinstance(expected, dict) or not expected or len(expected) > MAX_EXPECTED_FIELDS:
        raise SafetyError('bounded-verification-fields-required')
    for path, criterion in expected.items():
        _segments(path)
        if isinstance(criterion, dict) and any(str(key).startswith('$') for key in criterion):
            if set(criterion) != {'$decimal'}:
                raise SafetyError('unsupported-verification-criterion')
            _decimal(criterion['$decimal'])
        elif isinstance(criterion, float) and not math.isfinite(criterion):
            raise SafetyError('finite-verification-value-required')
    return expected


def _field(row, path):
    current = row
    for key, selector_key, selector_id in _segments(path):
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
        if selector_key:
            if not isinstance(current, list):
                return _MISSING
            hits = [item for item in current if isinstance(item, dict) and str(item.get(selector_key)) == selector_id]
            if len(hits) != 1:
                return _MISSING
            current = hits[0]
    return current


def matches_fields(row, expected):
    validate_expected(expected)
    for path, criterion in expected.items():
        actual = _field(row, path)
        if actual is _MISSING:
            return False
        if isinstance(criterion, dict) and set(criterion) == {'$decimal'}:
            try:
                if _decimal(actual) != _decimal(criterion['$decimal']):
                    return False
            except SafetyError:
                return False
        elif isinstance(criterion, (dict, list)):
            if actual != criterion:
                return False
        elif str(actual) != str(criterion):
            return False
    return True


def pagination_total(response):
    current = response
    totals = []
    for _ in range(5):
        if not isinstance(current, dict):
            break
        pagination = current.get('paginationData')
        if pagination is not None:
            if not isinstance(pagination, dict):
                raise SafetyError('invalid-native-pagination-metadata')
            value = pagination.get('totalItems')
            if value is not None:
                if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,19}', str(value)):
                    raise SafetyError('invalid-native-pagination-total')
                totals.append(int(value))
        if 'data' not in current or any(key in current for key in ('productId', 'skuId', 'skuList', 'productInfo', 'applyInfo')):
            break
        current = current['data']
    if len(set(totals)) > 1:
        raise SafetyError('conflicting-native-pagination-totals')
    return totals[0] if totals else None
