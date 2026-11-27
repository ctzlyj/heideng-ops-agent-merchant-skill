"""Public material helpers and collector root resolution; never queries prices or login."""
from __future__ import annotations
import os,sys,re,hashlib,io
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image
from collector_guard import atomic_json, ordered_variants
from image_variants import save_with_clean_fallback
from jpeg_cache import save_cached_jpeg

def resolve_root():
    for arg in sys.argv[1:]:
        if arg.startswith('--root='): return Path(arg.split('=',1)[1]).expanduser().resolve()
    if '--root' in sys.argv:
        at=sys.argv.index('--root')
        if len(sys.argv)>at+1:return Path(sys.argv[at+1]).expanduser().resolve()
    env=os.environ.get('HEIDENG_COLLECTION_ROOT')
    if env: return Path(env).expanduser().resolve()
    raise SystemExit('ROOT_REQUIRED: pass --root=<output-dir> or HEIDENG_COLLECTION_ROOT')
def resolve_stage(root, explicit=None):
    """All task state belongs to the parent-supplied merchant runtime home."""
    home = os.environ.get('HEIDENG_MERCHANT_HOME')
    if not home: raise SystemExit('HEIDENG_MERCHANT_HOME_REQUIRED')
    base = Path(home).expanduser().resolve() / 'mature' / 'collection' / 'batches'
    explicit = explicit or os.environ.get('HEIDENG_COLLECTION_STATE_DIR')
    stage = Path(explicit).expanduser().resolve() if explicit else base / hashlib.sha256(str(Path(root).resolve()).encode('utf-8')).hexdigest()
    if stage == base or not stage.is_relative_to(base): raise ValueError('COLLECTION_STATE_OUTSIDE_HOME')
    return stage

def state_argument():
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith('--state-dir='): return arg.split('=', 1)[1]
        if arg == '--state-dir' and len(sys.argv) > i + 1: return sys.argv[i + 1]
    return None

ROOT = resolve_root()
STAGE = resolve_stage(ROOT, state_argument())
CACHE = STAGE / 'asset_cache'

def safe_name(text):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text)).strip(' .') or '未命名'
    if len(text) > 100:
        text = text[:85] + '_' + hashlib.sha256(text.encode()).hexdigest()[:10]
    return text

def image_url(raw):
    if raw.startswith('//'): return 'https:' + raw
    if raw.startswith(('https://', 'http://')): return raw
    return 'https://img14.360buyimg.com/img/' + raw.lstrip('/')

def get_public(url):
    host = urlparse(url).hostname or ''
    if not (host.endswith('.360buyimg.com') or host == 'd.3.cn' or host.endswith('.300hu.com')):
        raise ValueError('Unexpected public material host')
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36', 'Referer': 'https://item.jd.com/'}, timeout=(10, 30))
    r.raise_for_status()
    return r.content

def final_state(initial, detail_count, missing_count, price_complete):
    if initial != 'ASSETS_STAGING' or not detail_count or missing_count:
        return 'ASSETS_INCOMPLETE_PRICE_PENDING'
    return 'ASSETS_READY_PRICE_PENDING' if not price_complete else 'ASSETS_READY'

def save_jpeg(url, destination):
    return save_cached_jpeg(url, destination, CACHE, STAGE, get_public)


def save_main_jpeg(url, destination):
    """Main images may publish a corrupt size variant; retry the same-host n12
    standard size once and report the substitution for the package receipt."""
    return save_with_clean_fallback(save_jpeg, url, destination)


def prior_receipts_path():
    return os.environ.get("HEIDENG_COLLECTION_PRIOR_RECEIPTS")
