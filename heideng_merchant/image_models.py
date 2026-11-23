"""Model IDs and per-image LTS4AI credit pricing for merchant generation."""
import re

MODELS = ('gpt-image-2.6', 'gpt-image-2.5')
TIER_CREDITS = {'1K':3, '2K':4, '4K':5}


def _allowed(models):
    if isinstance(models, str):
        models = (models,)
    models = tuple(models)
    if not models or len(set(models)) != len(models) or any(m not in MODELS for m in models):
        raise ValueError('LTS4AI 生图模型未配置')
    return models


def model_for(index, models=MODELS):
    models = _allowed(models)
    return models[index % len(models)]


def model_scope(models=MODELS):
    models = _allowed(models)
    return {'models':list(models)} if len(models) > 1 else {'model':models[0]}


def resolution_tier(size):
    """Use LTS4AI's requested pixel-area tiers (including non-square retail images)."""
    size = str(size).strip().lower()
    if size in ('1k','2k','4k'):
        return size.upper()
    if size == 'auto':
        return '1K'
    if not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}', size):
        raise ValueError('无法核对生图尺寸和积分档位')
    w, h = map(int,size.split('x'))
    pixels = w*h
    return '4K' if pixels > 4_700_000 else '2K' if pixels > 2_000_000 else '1K'


def image_credit_quote(unit_sizes):
    tiers = {unit:resolution_tier(size) for unit,size in unit_sizes.items()}
    costs = {unit:TIER_CREDITS[tier] for unit,tier in tiers.items()}
    total = sum(costs.values())
    return {'qualityByUnit':tiers,'creditCostsByUnit':costs, 'estimatedCredits':total,
            'maxCredits':total, 'actualCredits':None}
