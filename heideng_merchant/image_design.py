"""Merchant-authored design preferences are local to the verified shop and carry no fee grant."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .safety import atomic_json, read_json, safe_join
from .state import FileLock


def register(sub):
    parser = sub.add_parser('image-design', help='读取或按商家明确交办保存本店改图偏好')
    parser.add_argument('action', choices=('show', 'remember'))
    parser.add_argument('--shop-id', required=True)
    parser.add_argument('--vender-id', required=True)
    parser.add_argument('--preference', choices=('merchant-first', 'host-design'))
    parser.add_argument('--approved-prompt-file', type=Path)
    parser.add_argument('--source-ref', help='商家明确要求记住该偏好或提示词的原消息引用')


def identity(state, vendor, shop=None, profile=None):
    profiles = read_json(safe_join(state, 'linker/shops.json'), {}).get('profiles', {})
    candidates = {str(row.get('shopId')) for key, row in profiles.items()
                  if str(row.get('venderId')) == str(vendor) and (not profile or key == profile)
                  and (not shop or str(row.get('shopId')) == str(shop))}
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError('改图偏好需定位到唯一的本店')
    sid = candidates.pop()
    if not (sid.isascii() and sid.isdecimal() and str(vendor).isascii() and str(vendor).isdecimal()):
        raise ValueError('店铺或商家编号无效')
    return {'shopId': sid, 'venderId': str(vendor)}


def _path(state, store):
    return safe_join(state, 'image-design/' + store['venderId'] + '/' + store['shopId'] + '.json')


def load_design(state, store):
    record = read_json(_path(state, store), {})
    if record and record.get('shop') != store:
        raise ValueError('偏好记录与本店身份不符')
    return record


def handle(state, args):
    store = identity(state, args.vender_id, args.shop_id)
    if not store:
        raise ValueError('找不到本机已核验的这家店铺身份')
    if args.action == 'show':
        if args.preference or args.approved_prompt_file or args.source_ref:
            raise ValueError('读取偏好不接受写入参数')
        record = load_design(state, store)
    else:
        if not (args.source_ref or '').strip() or not (args.preference or args.approved_prompt_file):
            raise ValueError('记忆偏好或商家批准的提示词，需要原交办引用及本次要记住的内容')
        source = {'sourceRef': args.source_ref, 'savedAt': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        path = _path(state, store)
        with FileLock(path.with_suffix('.lock')):
            record = load_design(state, store) or {'shop': store}
            if args.preference:
                record['preference'] = {**source, 'mode': args.preference}
            if args.approved_prompt_file:
                prompt = args.approved_prompt_file.read_bytes().decode('utf-8-sig')
                if not prompt.strip():
                    raise ValueError('商家批准的提示词原文为空')
                record['approvedPrompt'] = {**source, 'text': prompt, 'sha256': sha256(prompt.encode()).hexdigest()}
            atomic_json(path, record)
    approved = record.get('approvedPrompt', {})
    return {'shop': store, 'preference': record.get('preference'), 'hasApprovedPrompt': bool(approved),
            'approvedPromptEvidence': {k: v for k, v in approved.items() if k != 'text'},
            'feeAuthorized': False, 'platformWrites': 0}
