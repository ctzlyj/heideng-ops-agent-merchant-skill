"""Locate merchant registrations without opening browser data or native credentials."""
from pathlib import Path

from . import SKILL_NAME
from .safety import SafetyError, read_json, safe_join


def _registered(root, query):
    path = safe_join(root, 'linker/shops.json')
    raw = read_json(path, {'profiles': {}})
    if not isinstance(raw, dict) or not isinstance(raw.get('profiles'), dict):
        raise SafetyError('店铺登记文件无法核对，请保留原目录。')
    stores = {}
    incomplete = 0
    for row in raw['profiles'].values():
        if not isinstance(row, dict):
            continue
        shop, vendor = str(row.get('shopId') or ''), str(row.get('venderId') or '')
        name = str(row.get('shopName') or '')
        aliases = row.get('aliases') or []
        if query and query not in [shop, vendor, name, *(aliases if isinstance(aliases, list) else [])]:
            continue
        if not (shop.isascii() and shop.isdigit() and vendor.isascii() and vendor.isdigit() and name):
            incomplete += 1
            continue
        stores[shop, vendor] = {'shopId':shop, 'venderId':vendor, 'shopName':name}
    return {'stateRoot':str(root), 'registryFound':path.is_file(), 'registeredShops':list(stores.values()),
            'incompleteRecords':incomplete, 'liveIdentityChecked':False}


def locate_shops(state, query=None, other_installs=(), *, home=None):
    from .distribution import RECEIPT, verify_install
    state = Path(state).resolve()
    expert = (Path(home or Path.home()) / '.heideng-wb-beta').resolve()
    expert_note = {'channel':'workbuddy-expert', 'stateRoot':str(expert), 'liveIdentityChecked':False,
                   'nextAction':'用原 WorkBuddy 专家的已授权入口查这家店。'}
    locations = ([expert_note] if state == expert else
                 [{**_registered(state, query), 'channel':'current-installation'}])
    known = {state}
    # Only consult another ordinary installation when selected by the caller. The
    # original installed receipt and state binding must agree in both directions.
    for selected in other_installs:
        package = Path(selected).resolve()
        if package.is_relative_to(expert):
            continue
        checked = verify_install(package)
        if not checked.get('valid'):
            raise SafetyError('所选旧安装缺少可核对的黑灯安装回执。')
        receipt = read_json(safe_join(package, RECEIPT))
        old = Path(receipt.get('stateRoot') or '')
        if receipt.get('skill') != SKILL_NAME or not old.is_absolute():
            raise SafetyError('旧安装回执缺少明确的商家状态目录。')
        old = old.resolve()
        if old in known or old == expert:
            continue
        binding = read_json(safe_join(old, 'installation-target.json'), {})
        if binding.get('target') != str(package):
            raise SafetyError('原安装与状态目录的绑定不一致，请核对原安装回执。')
        locations.append({**_registered(old, query), 'channel':'selected-installation', 'packageRoot':str(package)})
        known.add(old)
    if expert not in known and safe_join(expert, 'linker/shops.json').is_file():
        locations.append({**expert_note, 'registryFound':True})
    return {'status':'located', 'query':query, 'locations':locations, 'businessWrites':0,
            'nextAction':'在所属安装中按店名或店铺编号只读核店；网页登录状态由该店专用窗口确认。'}
