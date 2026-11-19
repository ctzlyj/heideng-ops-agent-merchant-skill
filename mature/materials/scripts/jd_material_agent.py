from __future__ import annotations
import argparse
import base64
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, closing, contextmanager, nullcontext
from dataclasses import asdict, dataclass, replace
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse
import httpx
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageOps
_script_directory = str(Path(__file__).resolve().parent)
if _script_directory not in sys.path:
    sys.path.insert(0, _script_directory)

VARIANT_ID = 'merchant-pop-mature'
SKILL_VERSION = '2026.11.207'
MAX_SPUS_PER_BATCH = 199
MAX_SPU_CONCURRENCY = 50
POP_SHORT_TITLE_MAX_ROWS = 10000
AUTO_MAINTAIN_PLAN_NAME = '自动维护计划.json'
MANUAL_VERIFICATION_MESSAGE = '京麦素材已提交；审核中不等于通过。短标题以独立导入任务回执与平台回读为准，导出表只用于留档。'
JDO_CLI_DEFAULT = Path(os.environ['JDO_HOME']) / 'bin' / ('jdo-cli.exe' if os.name == 'nt' else 'jdo-cli') if os.environ.get('JDO_HOME') else Path.cwd() / '.missing-merchant-cli'
JDO_IMAGE_BASE = 'https://img14.360buyimg.com/imgzone/'
JDO_PERMISSION_CODES = {'99904030007', '99904030008'}
JDO_MATERIAL_SLOTS = {'white': (31, 1), 'scene1': (32, 1), 'scene2': (32, 2), 'selling': (33, 1), 'transparent': (36, 1), 'point1': (1002, 1), 'point2': (1002, 2), 'point3': (1002, 3)}

IMAGE_MODEL_POOL = (('gpt-image-2.5', 1),)
SCENE_SELLING_EXTRA_MODEL = 'gpt-image-2.5'
SCENE_SELLING_MODEL_POOL = IMAGE_MODEL_POOL
IMAGE_MODEL_POOL_ALIAS = 'pool'
GEMINI_IMAGE_MODELS = ()
GEMINI_IMAGE_ENDPOINT = ''

@dataclass(frozen=True)
class ProviderConfig:
    id: str
    base_url: str
    text_model: str
    image_model: str
    api_key_env: str
    text_endpoint: str
    image_endpoint: str
    text_concurrency: int
    default_image_concurrency: int
    maximum_image_concurrency: int
    requests_per_minute: int | None = None
    text_start_interval_seconds: float = 0.0
    image_start_interval_seconds: float = 0.0
    image_response_format: str | None = None
    scene_image_model: str | None = None
    flare_model: str = 'gpt-image-2.5'
    flare_endpoint: str = 'images/edits'
    image_model_pool: tuple[tuple[str, int], ...] = IMAGE_MODEL_POOL
PROVIDER = ProviderConfig(id='merchant-lts4ai', base_url='https://api.lts4ai.com/v1', text_model='external-text-not-configured', image_model='gpt-image-2.5', api_key_env='HEIDENG_MERCHANT_LTS4AI_API_KEY', text_endpoint='', image_endpoint='images/edits', text_concurrency=20, default_image_concurrency=10, maximum_image_concurrency=20, text_start_interval_seconds=0.75, image_start_interval_seconds=0.1, scene_image_model=None, flare_model='gpt-image-2.5', image_model_pool=IMAGE_MODEL_POOL)
IMAGE_SUFFIXES = {'white': '白底图.jpg', 'transparent': '透明图.png', 'scene1': '场景图1.jpg', 'scene2': '场景图2.jpg', 'selling': '卖点图.jpg'}
BANNED_SELLING_POINT_TERMS = {'第一', '顶级', '独家', '国家级', '最先进', '金牌', '质量免检', '销量', '好评', '包邮', '京东', '自营', '物流', '官方', '授权', '专供', '特供', '热卖', '疯抢', '直降', '清仓', '推荐', '爆款', '首发', '让利', '特价', '折', '赠'}
SKU_HEADERS = {'SKUID', 'SKUID（必填）', 'SKUID(必填)'}
SPU_HEADERS = {'商品编码', 'SPUID', '商品SPUID'}
TITLE_HEADERS = {'商品名称', '商品标题', '长标题'}
SCORE_HEADERS = {'商品信息分', '商品信息分数'}

@dataclass(frozen=True)
class SourceRow:
    sku_id: str
    title: str
    spu_id: str
    score: str = ''
    raw: tuple[object, ...] = ()
    source_path: str = ''
    sheet_name: str = ''
    row_number: int = 0
    header_row: int = 1

@dataclass(frozen=True)
class SpuJob:
    spu_id: str
    representative_sku_id: str
    title: str
    sku_ids: tuple[str, ...]
    skus: tuple[tuple[str, str], ...]
    short_title_sku_ids: tuple[str, ...] = ()
    needs_selling_points: bool = True
    needs_white: bool = True
    needs_scenes: bool = True
    needs_selling_image: bool = True
    needs_transparent: bool = True

    @property
    def sku_count(self) -> int:
        return len(self.sku_ids)

@dataclass(frozen=True)
class PreparedSource:
    source_type: str
    sheet_name: str
    headers: tuple[object, ...]
    rows: tuple[SourceRow, ...]
    jobs: tuple[SpuJob, ...]
    original_rows: int
    filtered_rows: int
    duplicate_rows: int

@dataclass(frozen=True)
class BatchResult:
    total_spus: int
    completed_spus: int
    failed_spus: int
    output_dir: Path
    manifest_path: Path | None
    short_title_path: Path | None
    failure_path: Path | None

@dataclass(frozen=True)
class UploadResult:
    uploaded_files: int
    reused_files: int
    failed_files: int
    browser_required: bool
    url_export_path: Path
    failures: tuple[str, ...] = ()
    failed_spu_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class MaterialBindingPlan:
    prepared: PreparedSource
    output_dir: Path
    requests: tuple[dict[str, Any], ...]
    authorization_requests: tuple[dict[str, Any], ...]
    target_spus: tuple[dict[str, Any], ...]
    preflight_failures: tuple[dict[str, str], ...] = ()

@dataclass(frozen=True)
class MaterialBindingResult:
    submitted_types: int
    approved_spus: int
    pending_spus: int
    failed_spus: int
    browser_required: bool
    confirmation_required: bool
    confirm_token: str | None
    success_workbook: Path | None
    pending_workbook: Path | None
    failure_workbook: Path | None
    failures: tuple[str, ...] = ()
    failed_spu_ids: tuple[str, ...] = ()

class JdoError(RuntimeError):
    pass

class JdoPermissionError(JdoError):
    pass

class JdoUnavailableError(JdoError):
    pass

class JdoWriteUncertainError(JdoError):
    pass

@contextmanager
def pop_execution_lock(output_dir):
    # OS lock is released even when a host reclaims the process; receipts are independent.
    from heideng_merchant.state import FileLock, process_alive
    from heideng_merchant.safety import SafetyError
    path = Path(output_dir).resolve() / '.state' / 'pop-execution.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(path.with_suffix('.guard'), timeout=0):
            if path.exists():
                try:previous = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):raise JdoWriteUncertainError('Execution owner unreadable; preserve lock and receipts') from None
                if not isinstance(previous, dict) or process_alive(previous.get('pid')) is not False:
                    raise JdoWriteUncertainError('POP execution owner active or unknown; preserve original receipts')
                # Only the confirmed dead owner's execution marker is retired, never a task/receipt.
                path.replace(path.with_name(path.name + '.retired-' + uuid.uuid4().hex))
            owner = {'pid': os.getpid(), 'token': uuid.uuid4().hex, 'createdAt': int(time.time())}
            with path.open('x', encoding='utf-8') as handle:json.dump(owner, handle)
            try:yield
            finally:
                if path.exists() and json.loads(path.read_text(encoding='utf-8')) == owner:path.unlink()
    except SafetyError as error:
        if str(error) != 'resource-busy':raise
        raise JdoWriteUncertainError('POP execution is active; do not replay') from None

@contextmanager
def stage_timer(output_dir, stage):
    started = time.perf_counter()
    outcome = 'interrupted'
    try:
        yield
        outcome = 'returned'
    finally:
        path = Path(output_dir) / '.state' / 'stage-timings.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {'stage': stage, 'seconds': round(time.perf_counter() - started, 6), 'outcome': outcome, 'timestamp': int(time.time())}
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record) + '\n')

def measured_stage(stage, output_parameter):
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def measured(*args, **kwargs):
            output = signature.bind(*args, **kwargs).arguments[output_parameter]
            if isinstance(output, MaterialBindingPlan):
                output = output.output_dir
            with stage_timer(output, stage):
                return function(*args, **kwargs)
        return measured
    return decorate

def exclusive_pop_run(function):
    @wraps(function)
    def run(args):
        with pop_execution_lock(args.output_dir), stage_timer(args.output_dir, function.__name__):
            return function(args)
    return run

def assert_no_unknown_uploads(output_dir):
    for path in Path(output_dir).glob('批次*/.state/upload-ledger.json'):
        ledger = _load_upload_ledger(path)
        if any(entry.get('status') in {'intent', 'unknown'} for entry in ledger['files'].values()):
            raise JdoWriteUncertainError('unresolved upload found; stop before generation and reconcile the original receipt')

def cell_text(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()

def normalize_header(value: object) -> str:
    return re.sub('\\s+', '', cell_text(value)).upper()

def image_names(spu_id: str) -> dict[str, str]:
    text = cell_text(spu_id)
    if not re.fullmatch('\\d+', text):
        raise ValueError('SPUID 必须是数字文本。')
    return {kind: f'{text}{suffix}' for kind, suffix in IMAGE_SUFFIXES.items()}

def weighted_length(value: object) -> int:
    return sum(2 if unicodedata.name(character, '').startswith(('CJK UNIFIED IDEOGRAPH', 'CJK COMPATIBILITY IDEOGRAPH')) else 1 for character in cell_text(value))

def platform_length(value: object) -> int:
    # Conservative upper-bound measure: every East Asian wide/fullwidth character (including the
    # fullwidth parentheses/digits the platform counts as 2) is 2, everything else 1.
    return sum(2 if unicodedata.east_asian_width(character) in ('W', 'F') else 1 for character in cell_text(value))

def valid_short_title(value: object) -> bool:
    text = cell_text(value)
    return bool(text) and 16 <= weighted_length(text) <= 30 and platform_length(text) <= 30

def validate_selling_points(points: Iterable[object]) -> list[str]:
    normalized = [cell_text(point) for point in points]
    if len(normalized) != 3 or len(set(normalized)) != 3:
        raise ValueError('卖点必须为 3 个互不重复的词组。')
    for point in normalized:
        if not 2 <= len(point) <= 8:
            raise ValueError(f'卖点必须为 2-8 个字符：{point}')
        if re.search('[★☞【】/|｜▏♥♡]', point):
            raise ValueError(f'卖点包含无关符号：{point}')
        banned = next((term for term in BANNED_SELLING_POINT_TERMS if term in (re.sub('折叠|弯折|折弯', '', point) if term == '折' else point)), None)
        if banned:
            raise ValueError(f'卖点包含禁用词“{banned}”：{point}')
    return normalized

def _find_columns(row: tuple[object, ...]) -> dict[str, int]:
    normalized = [normalize_header(value) for value in row]
    aliases = {'sku': {normalize_header(value) for value in SKU_HEADERS}, 'spu': {normalize_header(value) for value in SPU_HEADERS}, 'title': {normalize_header(value) for value in TITLE_HEADERS}, 'score': {normalize_header(value) for value in SCORE_HEADERS}}
    result = {}
    for key, candidates in aliases.items():
        match = next((index for index, header in enumerate(normalized) if header in candidates), None)
        if match is not None:
            result[key] = match
    return result

def _sheet_candidate(workbook, selected_sheet: str | None=None):
    candidates = []
    for sheet in workbook.worksheets:
        if sheet.sheet_state != 'visible' or (selected_sheet and sheet.title != selected_sheet):
            continue
        for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 20, 20), values_only=True), 1):
            columns = _find_columns(tuple(row))
            if all((key in columns for key in ('sku', 'spu', 'title'))):
                candidates.append((sheet, row_number, tuple(row), columns))
                break
    if not candidates:
        raise ValueError('前 20 行未找到包含 SKU、SPU 和商品名称的可见工作表。')
    if len(candidates) > 1 and (not selected_sheet):
        raise ValueError('存在多个候选工作表，请使用 --sheet 指定：' + '、'.join((item[0].title for item in candidates)))
    return candidates[0]

def _numeric_score(value: object) -> float | None:
    try:
        return float(cell_text(value)) if cell_text(value) else None
    except ValueError:
        return None

def _reset_read_only_dimensions(workbook) -> None:
    for sheet in workbook.worksheets:
        reset = getattr(sheet, 'reset_dimensions', None)
        if callable(reset):
            reset()

def _jobs_from_rows(rows: list[SourceRow]) -> tuple[SpuJob, ...]:
    grouped: dict[str, list[SourceRow]] = {}
    seen_skus: set[str] = set()
    for row in rows:
        if row.sku_id in seen_skus:
            continue
        seen_skus.add(row.sku_id)
        grouped.setdefault(row.spu_id, []).append(row)
    return tuple((SpuJob(spu_id=spu_id, representative_sku_id=items[0].sku_id, title=items[0].title, sku_ids=tuple((item.sku_id for item in items)), skus=tuple(((item.sku_id, item.title) for item in items)), short_title_sku_ids=tuple((item.sku_id for item in items))) for spu_id, items in grouped.items()))

def collect_jdo_pages(fetch_page: Callable[[int, int], dict[str, Any]], page_size: int, id_field: str, label: str) -> list[dict[str, Any]]:
    if page_size < 1:
        raise ValueError('page_size must be positive')
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_total: int | None = None
    page = 1
    while expected_total is None or len(rows) < expected_total:
        payload = fetch_page(page, page_size)
        current_page = int(payload.get('pageNum') or payload.get('currentPage') or page)
        if current_page != page:
            raise ValueError(f'{label} pagination is not contiguous: expected page {page}, got {current_page}')
        total = int(payload.get('totalItems') or 0)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError(f'{label} total changed during pagination: {expected_total} -> {total}')
        items = payload.get('items') or []
        if not isinstance(items, list) or len(items) > page_size:
            raise ValueError(f'{label} returned an invalid page')
        if not items and len(rows) < expected_total:
            raise ValueError(f'{label} pagination ended before totalItems')
        for item in items:
            identifier = cell_text(item.get(id_field))
            if not identifier:
                raise ValueError(f'{label} contains an empty {id_field}')
            if identifier in seen:
                raise ValueError(f'{label} contains duplicate {id_field}: {identifier}')
            seen.add(identifier)
            rows.append(item)
        if len(rows) > expected_total:
            raise ValueError(f'{label} returned more rows than totalItems')
        page += 1
    if len(rows) != expected_total or len(seen) != expected_total:
        raise ValueError(f'{label} completeness check failed')
    return rows

def collect_jdo_pages_parallel(fetch_page, page_size, id_field, label, workers=8):
    """Page 1 fixes totalItems; remaining pages are fetched concurrently, then the same strict checks apply."""
    first = fetch_page(1, page_size)
    total = int(first.get('totalItems') or 0)
    pages = max(1, -(-total // page_size))
    results = {1: first}
    if pages > 1:
        with ThreadPoolExecutor(max_workers=min(workers, pages - 1)) as pool:
            for number, payload in zip(range(2, pages + 1), pool.map(lambda n: fetch_page(n, page_size), range(2, pages + 1))):
                results[number] = payload
    rows = [];seen = set()
    for number in range(1, pages + 1):
        payload = results[number]
        if int(payload.get('totalItems') or 0) != total:
            raise ValueError(f'{label} total changed during pagination')
        if int(payload.get('pageNum') or number) != number:
            raise ValueError(f'{label} pagination is not contiguous')
        for item in payload.get('items') or []:
            identifier = cell_text(item.get(id_field))
            if not identifier or identifier in seen:
                raise ValueError(f'{label} contains an empty or duplicate {id_field}')
            seen.add(identifier);rows.append(item)
    if len(rows) != total:
        raise ValueError(f'{label} completeness check failed')
    return rows

def _jdo_error(payload: dict[str, Any]) -> tuple[set[str], str]:
    errors = payload.get('errorList') or payload.get('errors') or []
    if isinstance(errors, dict):
        errors = [errors]
    codes = {cell_text(item.get('code')) for item in errors if isinstance(item, dict)}
    messages = [' '.join(filter(None, (cell_text(item.get('code')), cell_text(item.get('message'))))) for item in errors if isinstance(item, dict)]
    return (codes, '; '.join(messages) or cell_text(payload.get('message')) or 'jdo-cli call failed')

def _parse_jdo_response(output: str) -> dict[str, Any]:
    cleaned = output.strip()
    candidates = [cleaned]
    if cleaned.startswith('HTTP ') and ':' in cleaned:
        candidates.insert(0, cleaned.split(':', 1)[1].strip())
    candidates.extend((line.strip() for line in reversed(cleaned.splitlines()) if line.strip().startswith('{')))
    payload = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(payload, dict):
        raise JdoUnavailableError('jdo-cli did not return JSON')
    if payload.get('success') is False:
        codes, message = _jdo_error(payload)
        if codes & JDO_PERMISSION_CODES:
            raise JdoPermissionError(message)
        raise JdoError(message)
    return payload

class JdoBusinessRejected(JdoError):
    """Platform returned an explicit business errorList for a write; nothing was applied."""

class JdoClient:

    def __init__(self, profile: str | None=None, runtime_dir: str | Path | None=None):
        self.profile = profile
        self.runtime_dir = Path(runtime_dir) if runtime_dir else Path.cwd() / '.jdo-runtime'
        configured = os.environ.get('JDO_CLI_PATH')
        discovered = shutil.which('jdo-cli')
        self.executable = Path(configured or discovered or JDO_CLI_DEFAULT)
        self._zone_id: str | None = None

    def _run(self, arguments: list[str]) -> dict[str, Any]:
        if not self.executable.is_file():
            raise JdoUnavailableError(f'jdo-cli not found: {self.executable}')
        command = [str(self.executable), *arguments]
        if self.profile:
            command.extend(('--profile', self.profile))
        environment = os.environ.copy()
        environment['JDO_ENV'] = 'prod'
        environment['PYTHONIOENCODING'] = 'utf-8'
        completed = subprocess.run(command, cwd=self.runtime_dir.parent if self.runtime_dir.parent.exists() else Path.cwd(), env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=210, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
        if completed.returncode:
            raise JdoUnavailableError(f'jdo-cli exited with code {completed.returncode}; response not trusted')
        output = '\n'.join((part for part in (completed.stdout, completed.stderr) if part))
        return _parse_jdo_response(output)

    def _get(self, skill_id: str, url: str, params: dict[str, Any] | None=None) -> dict[str, Any]:
        arguments = ['invoke', '--skill-id', skill_id, '--url', url, '--method', 'GET']
        if params:
            arguments.extend(('--params', json.dumps(params, ensure_ascii=False, separators=(',', ':'))))
        arguments.extend(('--request-identity', 'vender'))
        return self._run(arguments)

    @staticmethod
    def _page(payload: dict[str, Any], requested_page: int) -> dict[str, Any]:
        items = payload.get('data') or []
        pagination = payload.get('paginationData') or {}
        return {'totalItems': int(pagination.get('totalItems') or len(items)), 'pageNum': int(pagination.get('currentPage') or pagination.get('page') or requested_page), 'items': items}

    def seller_info(self) -> dict[str, Any]:
        payload = self._get('jdo-seller-info', '/rest/sp-seller/v0/venderinfo', {'scopeSet': 'baseInfo'})
        data = payload.get('data') or {}
        shop = data.get('shopBaseInfo') or {}
        return {'success': True, 'whitelistMatch': True, 'isPop': int(shop.get('type', -1)) == 0, 'active': int(shop.get('status') or 0) == 1, 'shopName': cell_text(shop.get('shopName')), 'shopId': cell_text(shop.get('shopId')), 'venderId': cell_text(data.get('venderId'))}

    def health_infos(self, page_num: int, page_size: int) -> dict[str, Any]:
        payload = self._get('jdo-product-price', '/rest/sp-product/v0/health-infos', {'page': page_num, 'pageSize': page_size})
        return self._page(payload, page_num)

    def _exact_list(self, url: str, scope_set: str, product_ids: Iterable[str], id_field: str, label: str, *, page_size: int, extra_params: dict[str, Any] | None=None) -> list[dict[str, Any]]:
        identifiers = [int(value) for value in product_ids]

        def fetch(page: int, page_size: int) -> dict[str, Any]:
            params = {'scopeSet': scope_set, 'page': page, 'pageSize': page_size, 'productIdList': identifiers}
            params.update(extra_params or {})
            payload = self._get('jdo-product-status', url, params)
            return self._page(payload, page)
        return collect_jdo_pages(fetch, page_size, id_field, label)

    def skus(self, product_ids: Iterable[str]) -> list[dict[str, Any]]:
        return self._exact_list('/rest/sp-product/v0/skus', 'skuId,productId,skuName,status,logo', product_ids, 'skuId', 'SKU exact lookup', page_size=50, extra_params={'sortBy': 'created', 'sortType': 'asc'})

    def products(self, product_ids: Iterable[str]) -> list[dict[str, Any]]:
        return self._exact_list('/rest/sp-product/v0/products', 'productId,productName,productStatus,logo', product_ids, 'productId', 'product exact lookup', page_size=100)

    def online_products(self, page_num: int, page_size: int) -> dict[str, Any]:
        payload = self._get('jdo-product-status', '/rest/sp-product/v0/products', {'scopeSet': 'productId,productName,productStatus,logo', 'productStatusList': [103], 'page': page_num, 'pageSize': page_size, 'sortBy': 'created', 'sortType': 'asc'})
        return self._page(payload, page_num)

    def sku_materials(self, sku_ids: Iterable[str], material_types: Iterable[int], scope_set: int) -> list[dict[str, Any]]:
        payload = self._get('jdo-api-830', '/rest/sp-product/v0/sku-materials', {'skuIds': [int(value) for value in sku_ids], 'materialTypes': [int(value) for value in material_types], 'scopeSet': [int(scope_set)]})
        errors = payload.get('errorList') or []
        if errors:
            _, message = _jdo_error(payload)
            raise JdoError(message)
        return payload.get('data') or []

    def bind_sku_materials(self, body: dict[str, Any]) -> dict[str, Any]:
        sku_materials = list(body.get('skuMaterials') or [])
        if not sku_materials:
            raise ValueError('SKU material binding body is empty')
        results = []
        for group in _chunks(sku_materials, 50):
            payload = self._post_with_body_file('jdo-api-830', '/rest/sp-product/v0/sku-materials/batch', {**body, 'skuMaterials': list(group)})
            errors = payload.get('errorList') or []
            if errors:
                codes, message = _jdo_error(payload)
                if codes & JDO_PERMISSION_CODES:
                    raise JdoPermissionError(message)
                raise JdoError(message)
            results.append(payload.get('data') or {})
        if len(results) == 1:
            return results[0]
        return {'batchResults': results}

    def image_zone_id(self) -> str:
        if self._zone_id:
            return self._zone_id
        payload = self._get('jdo-product-material', '/rest/sp-product/v0/media-zones')
        zone = next((item for item in payload.get('data') or [] if int(item.get('zoneType') or 0) == 1), None)
        if not zone or not cell_text(zone.get('zoneId')):
            raise JdoError('current shop has no image media zone')
        self._zone_id = cell_text(zone['zoneId'])
        return self._zone_id

    def find_zone_images(self, name: str) -> list[dict[str, Any]]:
        payload = self._get('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/images', {'zoneId': self.image_zone_id(), 'imgName': Path(name).stem, 'page': 1, 'pageSize': 20})
        return list(payload.get('data') or [])

    def resolve_category(self, category_id: int | None=None, category_name: str | None=None) -> int:
        if category_id is not None:
            return int(category_id)
        zone_id = self.image_zone_id()
        payload = self._get('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/categories', {'zoneId': zone_id, 'page': 1, 'pageSize': 100})
        categories = payload.get('data') or []
        selected = next((item for item in categories if category_name and item.get('categoryName') == category_name), None)
        if selected is None and (not category_name):
            selected = next((item for item in categories if item.get('categoryName') == '我的本地文件'), None)
        if selected is None and (not category_name):
            selected = next((item for item in categories if int(item.get('status') or 0) == 1), None)
        if selected is None:
            raise JdoError('requested image-space category is unavailable')
        return int(selected['categoryId'])

    def _python312(self) -> Path:
        from jdo_bridge_probe import find_bridge_python, bridge_status
        python=find_bridge_python()
        if python is None:
            raise JdoUnavailableError(bridge_status(exe=self.executable,python=None,runtime_ok=None)['userMessage'])
        return python

    def _runtime(self) -> Path:
        from jdo_bridge_probe import probe_runtime, interface_changed_message
        try:
            from PyInstaller.archive.readers import CArchiveReader
        except ImportError:
            raise JdoUnavailableError('大请求发送组件未安装；让助手补装 requirements.txt，查询和审计不受影响。') from None
        if not self.executable.is_file():raise JdoUnavailableError('官方京麦 CLI 未安装，请先用“京麦 CLI 店铺连接”。')
        try:runtime=CArchiveReader(str(self.executable)).extract('jdo-cli')
        except Exception:raise JdoUnavailableError(interface_changed_message()) from None
        self.runtime_dir.mkdir(parents=True,exist_ok=True)
        path=self.runtime_dir/'jdo-cli.pyc'
        checked=probe_runtime(path,runtime,python=getattr(self,'_bridge_python',None) or self._python312(),cache=self.runtime_dir/'interface-cache.json')
        if not checked['ok']:raise JdoUnavailableError(checked['userMessage'])
        return path

    def check_bridge(self):
        # A long-lived client must not reuse evidence after the executable changes.
        stat=self.executable.stat() if self.executable.is_file() else None
        identity=(stat.st_size,stat.st_mtime_ns) if stat else None
        if not getattr(self,'_bridge_paths',None) or identity!=getattr(self,'_bridge_executable_identity',None):
            self._bridge_python=self._python312()
            self._bridge_paths=(self._bridge_python,self._runtime())
            self._bridge_executable_identity=identity
        return self._bridge_paths

    def _post_with_body_file(self, skill_id: str, url: str, body: dict[str, Any], *, params: dict[str, Any] | None=None, timeout: int=180, method: str='POST', dry_run: bool=False) -> dict[str, Any]:
        from jdo_bridge_probe import needs_bridge, COMMAND_LINE_BODY_LIMIT
        if not cell_text(self.profile) or cell_text(self.profile).casefold()=='default':
            raise JdoError('请指定已核对店名和 venderId 的该店独立 Profile，禁止 default。')
        body_text=json.dumps(body,ensure_ascii=False,separators=(',',':'))
        command=[str(self.executable),'invoke','--skill-id',skill_id,'--url',url,'--method',method,
                 '--body',body_text,'--profile',self.profile,'--request-identity','vender','--timeout',str(timeout)]
        if params:command.extend(['--params',json.dumps(params,ensure_ascii=False,separators=(',',':'))])
        command.append('--dry-run' if dry_run else '--yes')
        # Count the actual quoted command too: JSON quotes / path / parameters consume OS units.
        large=needs_bridge(body_text) or len(subprocess.list2cmdline(command).encode('utf-16-le'))//2>COMMAND_LINE_BODY_LIMIT
        environment=os.environ.copy();environment['JDO_ENV']='prod';environment['PYTHONIOENCODING']='utf-8'
        body_path=request_path=None
        if large:
            python312,runtime=self.check_bridge()
            self.runtime_dir.mkdir(parents=True,exist_ok=True)
            unique=uuid.uuid4().hex
            body_path=self.runtime_dir/f'body-{unique}.json';request_path=self.runtime_dir/f'request-{unique}.json'
            body_path.write_text(body_text,encoding='utf-8')
            request_path.write_text(json.dumps({'url':url,'method':method,'bodyFile':str(body_path.resolve()),'params':params or {},'profile':self.profile,'skillId':skill_id,'requestIdentity':'vender','timeout':timeout,'yes':not dry_run,'dryRun':dry_run},ensure_ascii=False),encoding='utf-8')
            command=[str(python312),str(Path(__file__).with_name('jdo_large_body_bridge.py')),'--runtime',str(runtime.resolve()),'--request',str(request_path.resolve())]
        elif not self.executable.is_file():
            raise JdoUnavailableError('官方京麦 CLI 未安装，请先用“京麦 CLI 店铺连接”。')
        try:
            try:
                completed=subprocess.run(command,cwd=self.runtime_dir if large else (self.runtime_dir.parent if self.runtime_dir.parent.exists() else Path.cwd()),env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',check=False,timeout=timeout+30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
            except (OSError,subprocess.SubprocessError):
                raise JdoWriteUncertainError('京麦请求结果不明，先核对原回执和远端状态，不要重发。') from None
            output='\n'.join(part for part in (completed.stdout,completed.stderr) if part)
            if completed.returncode:
                try:_parse_jdo_response(output)
                except JdoPermissionError:raise
                except JdoUnavailableError:pass
                except JdoError as error:raise JdoBusinessRejected(str(error)) from None
                except Exception:pass
                raise JdoWriteUncertainError('京麦请求结果不明，先核对原回执和远端状态，不要重发。')
            try:payload=_parse_jdo_response(output)
            except JdoUnavailableError:raise JdoWriteUncertainError('京麦请求结果不明，先核对原回执和远端状态，不要重发。') from None
            if dry_run:
                # The official dry-run prints assembled inputs; never return its signing data.
                return {'dryRun':True,'requestPrepared':True,'method':method,'bodyUnits':len(body_text.encode('utf-16-le'))//2,'transport':'file' if large else 'cli','writes':0}
            if payload.get('success') is not True:raise JdoWriteUncertainError('京麦响应未明确确认成功，先核对原回执，不要重发。')
            return payload
        finally:
            if body_path is not None:body_path.unlink(missing_ok=True)
            if request_path is not None:request_path.unlink(missing_ok=True)

    def upload_image(self, path: str | Path, category_id: int) -> dict[str, Any]:
        path = Path(path)
        payload = self._post_with_body_file('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/images', {'imgBase64': base64.b64encode(path.read_bytes()).decode('ascii'), 'zoneImageDTO': {'imgName': path.name, 'categoryId': int(category_id)}}, params={'zoneId': self.image_zone_id()})
        return payload.get('data') or {}

def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]

def _jd_image_url(value: object) -> str:
    url = cell_text(value)
    if not url:
        return ''
    if url.startswith('jfs/'):
        return JDO_IMAGE_BASE + url
    if url.startswith('//'):
        url = 'https:' + url
    elif not re.match('^https?://', url) and '.360buyimg.com/' in url:
        url = 'https://' + url.lstrip('/')
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host.endswith('.360buyimg.com') or host.endswith('.jd.com')):
        raise ValueError('JDO returned an untrusted product image URL')
    return url

def _material_value(material: dict[str, Any]) -> str:
    material_type = int(material.get('materialType') or 0)
    if material_type == 1002:
        contents = (material.get('textMaterial') or {}).get('contents') or []
        return cell_text(contents[0]) if contents else ''
    images = (material.get('imageMaterial') or {}).get('skuImages') or []
    return _jd_image_url(images[0].get('imgUrl')) if images and images[0].get('imgUrl') else ''

def _jfs_path(value: object) -> str:
    url = cell_text(value)
    if url.startswith('jfs/'):
        return url
    parsed = urlparse(url)
    marker = '/jfs/'
    if parsed.scheme == 'https' and marker in parsed.path:
        return parsed.path[parsed.path.index(marker) + 1:]
    raise ValueError('material image URL does not contain a relative jfs path')

def _binding_material(material_type: int, order: int, value: str, sku_id: str) -> dict[str, Any]:
    material = {'skuId': int(sku_id), 'materialType': int(material_type), 'order': int(order)}
    if material_type == 1002:
        material['textMaterial'] = {'contents': [value]}
    else:
        material['imageMaterial'] = {'imgType': 1, 'replaceType': 1, 'skuImages': [{'index': 1, 'imgUrl': _jfs_path(value)}]}
    return material

def binding_selling_points(spu_id, points, item):
    origin=item.get('selling_points_origin') or {}
    if (origin.get('source')=='platform-approved' and str(origin.get('spuId'))==str(spu_id)
            and origin.get('values')==list(points) and item.get('selling_points')==list(points)
            and len(points)==3 and all(isinstance(p,str) and p and len(p)<=4096 and not any(c in p for c in ('\x00','\r','\n')) for p in points)):
        return list(points)  # Exactly the frozen approved values; not a bypass for new host text.
    return validate_selling_points(points)


def build_material_binding_requests(job: SpuJob, state_item: dict[str, Any]) -> list[dict[str, Any]]:
    uploaded = state_item.get('uploaded_urls') or {}
    specifications: list[tuple[int, list[tuple[int, str]]]] = []
    if job.needs_white:
        specifications.append((31, [(1, cell_text(uploaded.get('white')))]))
    if job.needs_scenes:
        specifications.append((32, [(1, cell_text(uploaded.get('scene1'))), (2, cell_text(uploaded.get('scene2')))]))
    if job.needs_selling_image:
        specifications.append((33, [(1, cell_text(uploaded.get('selling')))]))
    if job.needs_transparent:
        specifications.append((36, [(1, cell_text(uploaded.get('transparent')))]))
    if job.needs_selling_points:
        points = binding_selling_points(job.spu_id,state_item.get('selling_points') or [],state_item)
        specifications.append((1002, list(enumerate(points, 1))))
    requests = []
    for material_type, ordered_values in specifications:
        if any((not value for _, value in ordered_values)):
            raise ValueError(f'SPU {job.spu_id} material type {material_type} is incomplete before binding')
        sku_materials = []
        for sku_id in job.sku_ids:
            sku_materials.append({'productId': int(job.spu_id), 'skuId': int(sku_id), 'materials': [_binding_material(material_type, order, value, sku_id) for order, value in ordered_values]})
        body = {'skuMaterials': sku_materials}
        fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        requests.append({'spuId': job.spu_id, 'materialType': material_type, 'skuIds': list(job.sku_ids), 'body': body, 'fingerprint': fingerprint})
    return requests

READ_CONCURRENCY = 8

def _query_binding_materials(client: Any, sku_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    identifiers = [cell_text(value) for value in sku_ids]
    materials_by_sku = {sku_id: [] for sku_id in identifiers}
    jobs = [(group, material_types, scope_set) for group in _chunks(identifiers, 50) for material_types, scope_set in (((31, 32, 33, 36), 1), ((1002,), 2))]

    def read(job):
        group, material_types, scope_set = job
        rows = client.sku_materials(group, material_types, scope_set)
        returned = [cell_text(item.get('skuId')) for item in rows]
        if len(returned) != len(group) or set(returned) != set(group):
            raise ValueError('SKU material verification returned an incomplete SKU set')
        return rows
    # Read-only and independent per 50-SKU chunk: bounded parallel reads (8,191-SKU shop took ~26 min serially).
    workers = 1 if len(jobs) <= 2 else READ_CONCURRENCY
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(read, jobs):
            for item in rows:
                materials_by_sku[cell_text(item.get('skuId'))].extend(item.get('materials') or [])
    return materials_by_sku

def prepare_rejected_slot_request(spu_id: str, full_sku_ids: Iterable[str], original: dict[str, list[dict[str, Any]]], current: dict[str, list[dict[str, Any]]], kind: str, new_url: str, *, allow_white_scene_repair: bool=False, allow_manual_appeal_repair: bool=False) -> dict[str, Any]:
    if kind in {'white', 'scene1', 'scene2', 'transparent'} and not (allow_manual_appeal_repair or (kind != 'transparent' and allow_white_scene_repair)):
        raise ValueError('white/scene/transparent rejection defaults to manual appeal; export SKU IDs and reasons instead of regenerating or resubmitting')
    identifiers = [cell_text(value) for value in full_sku_ids]
    if not identifiers or any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('complete unique sibling SKU scope required')
    if kind not in IMAGE_SUFFIXES or set(original) != set(identifiers) or set(current) != set(identifiers):
        raise ValueError('image repair kind or complete material scope invalid')
    material_type, order = JDO_MATERIAL_SLOTS[kind]
    if not new_url.startswith('https://') or not _jfs_path(_jd_image_url(new_url)).startswith('jfs/'):
        raise ValueError('repair requires a real new image-space URL')
    selected = []
    preserved = []
    preserved_materials = {}
    for sku_id in identifiers:
        old_items = original[sku_id]
        current_items = current[sku_id]
        old_values = {(int(item['materialType']), int(item['order'])): _material_value(item) for item in old_items}
        current_values = {(int(item['materialType']), int(item['order'])): _material_value(item) for item in current_items}
        if len(old_values) != len(old_items) or len(current_values) != len(current_items) or old_values != current_values:
            raise ValueError('original material values changed or contain duplicate slots')
        old = [item for item in old_items if (int(item['materialType']), int(item['order'])) == (material_type, order)]
        latest = [item for item in current_items if (int(item['materialType']), int(item['order'])) == (material_type, order)]
        if not old and not latest:
            preserved.append(sku_id)
            continue
        if len(old) != 1 or len(latest) != 1:
            raise ValueError('repair target slot is missing or duplicated')
        if _jfs_path(_material_value(latest[0])) == _jfs_path(new_url):
            raise ValueError('repair URL equals the original URL')
        if int(old[0].get('status') or 0) == 5:
            if int(latest[0].get('status') or 0) != 5:
                raise ValueError('rejected slot changed; do not resubmit')
            selected.append(sku_id)
            preserved_materials[sku_id] = [item for item in current_items if int(item['materialType']) == material_type and int(item['order']) != order]
        elif int(old[0].get('status') or 0) in (3, 4) and int(latest[0].get('status') or 0) in (3, 4):
            preserved.append(sku_id)
        else:
            raise ValueError('sibling status needs a separate repair scope')
    if not selected:
        raise ValueError('no confirmed rejected SKU to repair')
    body = {'skuMaterials': [{'productId': int(spu_id), 'skuId': int(sku_id), 'materials': [_binding_material(material_type, order, new_url, sku_id)]} for sku_id in selected]}
    fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'spuId': spu_id, 'materialType': material_type, 'skuIds': selected, 'fullSiblingSkuIds': identifiers, 'preservedSkuIds': preserved, 'preservedMaterialsBySku': preserved_materials, 'body': body, 'fingerprint': fingerprint}

def _evaluate_binding_request(request: dict[str, Any], materials_by_sku: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    pending = False
    rejected_reasons = []
    material_type = int(request['materialType'])
    expected_by_sku = {cell_text(item['skuId']): item['materials'] for item in request['body']['skuMaterials']}
    for sku_id in request['skuIds']:
        targets = expected_by_sku[cell_text(sku_id)]
        preserved_by_sku = request.get('preservedMaterialsBySku')
        if preserved_by_sku is not None and set(preserved_by_sku) != set(map(cell_text, request['skuIds'])):
            return ('mismatch', 'preserved material scope mismatch')
        preserved = (preserved_by_sku or {}).get(cell_text(sku_id), [])
        expected = targets + preserved
        orders = [int(item['order']) for item in expected]
        if len(set(orders)) != len(orders) or any(int(item['materialType']) != material_type for item in expected):
            return ('mismatch', f'SKU {sku_id} expected material scope mismatch')
        actual = [item for item in materials_by_sku.get(cell_text(sku_id), []) if int(item.get('materialType') or 0) == material_type]
        if len(actual) != len(expected):
            return ('mismatch', f'SKU {sku_id} material count mismatch')
        for item in actual:
            if material_type == 1002:
                contents = (item.get('textMaterial') or {}).get('contents') or []
                if len(contents) != 1:
                    return ('mismatch', f'SKU {sku_id} selling-point contents mismatch')
            else:
                images = (item.get('imageMaterial') or {}).get('skuImages') or []
                if len(images) != 1 or int(images[0].get('index') or 0) != 1:
                    return ('mismatch', f'SKU {sku_id} image structure mismatch')

        def comparable(item: dict[str, Any]) -> str:
            value = _material_value(item)
            return value if material_type == 1002 else _jfs_path(value)
        expected_values = {int(item['order']): comparable(item) for item in expected}
        actual_values = {int(item.get('order') or 0): comparable(item) for item in actual}
        if expected_values != actual_values:
            return ('mismatch', f'SKU {sku_id} material order or value mismatch')
        target_orders = {int(item['order']) for item in targets}
        target_actual = [item for item in actual if int(item['order']) in target_orders]
        statuses = [int(item.get('status') or 0) for item in target_actual]
        if any((status not in (3, 4) for status in statuses)):
            details = list(dict.fromkeys((cell_text(item.get('auditDesc') or item.get('reason')) for item in target_actual if int(item.get('status') or 0) not in (3, 4) and cell_text(item.get('auditDesc') or item.get('reason')))))
            rejected_reasons.append(f'SKU {sku_id} material was rejected' + (': ' + '; '.join(details) if details else ''))
        pending = pending or any((status == 3 for status in statuses))
    if rejected_reasons:
        return ('failed', '; '.join(rejected_reasons))
    return ('pending', 'waiting for audit') if pending else ('approved', 'approved')

def inspect_unscored_materials(client: Any, sku_rows: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, dict[str, Any]]]:
    sku_ids = [cell_text(item.get('skuId')) for item in sku_rows]
    if any((not sku_id for sku_id in sku_ids)) or len(set(sku_ids)) != len(sku_ids):
        raise ValueError('unscored SKU list contains an empty or duplicate skuId')
    materials_by_sku: dict[str, list[dict[str, Any]]] = _query_binding_materials(client, sku_ids) if sku_ids else {}
    rows_by_spu: dict[str, list[dict[str, Any]]] = {}
    for row in sku_rows:
        rows_by_spu.setdefault(cell_text(row.get('productId')), []).append(row)
    missing_by_spu: dict[str, set[str]] = {}
    existing_by_spu: dict[str, dict[str, Any]] = {}
    for spu_id, items in rows_by_spu.items():
        missing: set[str] = set()
        approved_values: dict[str, set[str]] = {slot: set() for slot in JDO_MATERIAL_SLOTS}
        for slot, (material_type, order) in JDO_MATERIAL_SLOTS.items():
            slot_missing = False
            slot_pending = False
            for item in items:
                sku_id = cell_text(item.get('skuId'))
                matches = [material for material in materials_by_sku[sku_id] if int(material.get('materialType') or 0) == material_type and int(material.get('order') or 0) == order]
                active = [material for material in matches if int(material.get('status') or 0) in (3, 4)]
                if not active and not any(int(material.get('status') or 0) == 5 for material in matches):
                    # Rejected (5) slots are repaired by repair-rejected with fresh bytes; the material
                    # stage binds only truly empty slots, so generating here would be wasted uploads.
                    slot_missing = True
                for material in active:
                    status = int(material.get('status') or 0)
                    if status == 3:
                        slot_pending = True
                        continue
                    if status != 4:
                        continue
                    value = _material_value(material)
                    if value:
                        approved_values[slot].add(value)
                    else:
                        slot_missing = True
            if not slot_pending and (slot_missing or len(approved_values[slot]) > 1):
                missing.add(slot)
        if not missing:
            continue
        state: dict[str, Any] = {'uploaded_urls': {}}
        for kind in IMAGE_SUFFIXES:
            values = approved_values[kind]
            if len(values) == 1:
                state['uploaded_urls'][kind] = next(iter(values))
        points = []
        for slot in ('point1', 'point2', 'point3'):
            values = approved_values[slot]
            if len(values) != 1:
                points = []
                break
            points.append(next(iter(values)))
        if points:
            state['selling_points'] = points
            state['selling_points_origin']={'source':'platform-approved','spuId':spu_id,'values':list(points)}
        missing_by_spu[spu_id] = missing
        existing_by_spu[spu_id] = state
    return (missing_by_spu, existing_by_spu)

def collect_pop_image_appeals(sku_rows, materials_by_sku):
    identifiers = [cell_text(row.get('skuId')) for row in sku_rows]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers) or set(identifiers) != set(materials_by_sku):
        raise ValueError('appeal export requires a complete unique SKU/material scope')
    names = {(31, 1): '白底图', (32, 1): '场景图1', (32, 2): '场景图2', (36, 1): '透明图'}
    records = []
    for row in sku_rows:
        sku_id = cell_text(row['skuId'])
        product_id = cell_text(row.get('productId'))
        if not sku_id.isdecimal() or not product_id.isdecimal():
            raise ValueError('appeal SKU and product IDs must be exact numeric text')
        for item in materials_by_sku[sku_id]:
            material_type = int(item.get('materialType') or 0)
            order = int(item.get('order') or 0)
            if material_type not in (31, 32, 36) or int(item.get('status') or 0) != 5:
                continue
            records.append({'skuId': sku_id, 'productId': product_id, 'skuName': cell_text(row.get('skuName')),
                            'materialType': material_type, 'order': order, 'status': 5,
                            'materialName': names.get((material_type, order), f'类型{material_type}/顺序{order}'),
                            'imageUrl': _material_value(item), 'auditDesc': str(item.get('auditDesc') or item.get('reason') or '')})
    return records

def export_pop_image_appeals(report, output_dir):
    identity = report.get('shopIdentity') or {}
    records = report.get('appealRows')
    if not all(identity.get(key) for key in ('shopName', 'shopId', 'venderId')) or not report.get('checkedAt') or not report.get('scopeNote') or not isinstance(records, list):
        raise ValueError('appeal report requires identity, snapshot time, scope and explicit appealRows; legacy absence is not zero rejections')
    by_sku = {}
    for item in records:
        if item.get('materialType') not in (31, 32, 36) or item.get('status') != 5 or not str(item.get('skuId', '')).isdecimal() or not str(item.get('productId', '')).isdecimal():
            raise ValueError('appeal report contains an invalid or non-rejected white/scene/transparent slot')
        previous = by_sku.setdefault(item['skuId'], [])
        if previous and any(previous[0].get(key) != item.get(key) for key in ('productId', 'skuName')):
            raise ValueError('appeal report contains conflicting SKU identity')
        previous.append(item)
    result = {'skuCount': len(by_sku), 'rejectedSlotCount': len(records), 'appealFiles': [], 'appealSubmitted': False, 'writesPerformed': False}
    if not records:
        return result
    frozen = {'shopIdentity': identity, 'checkedAt': report['checkedAt'], 'scopeNote': report['scopeNote'], 'appealRows': records}
    digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / f'白底场景透明图驳回申诉清单_{len(by_sku)}SKU_{digest[:12]}.xlsx'
    evidence = path.with_suffix('.json')
    if path.exists() or evidence.exists():
        if not path.is_file() or not evidence.is_file():
            raise ValueError('existing appeal delivery has incomplete evidence; original files preserved')
        saved = json.loads(evidence.read_text(encoding='utf-8'))
        if saved.get('snapshotSha256') != digest or saved.get('fileSha256') != _file_sha256(path):
            raise ValueError('existing appeal delivery changed; user file preserved')
    else:
        workbook = Workbook()
        sku_sheet = workbook.active
        sku_sheet.title = 'SKU清单'
        sku_sheet.append(['SKU ID', 'SPU ID', '商品名称', '驳回素材', '处理方式'])
        for sku_id, items in by_sku.items():
            sku_sheet.append([sku_id, items[0]['productId'], items[0]['skuName'], '、'.join(dict.fromkeys(item['materialName'] for item in items)), '用户去商家素材群申诉，未代提交'])
        details = workbook.create_sheet('驳回原因明细')
        details.append(['SKU ID', 'SPU ID', '商品名称', '素材类型', 'materialType', 'order', 'status', '原图URL', '平台驳回原因原文'])
        for item in records:
            details.append([item['skuId'], item['productId'], item['skuName'], item['materialName'], item['materialType'], item['order'], item['status'], item['imageUrl'], item['auditDesc']])
        notes = workbook.create_sheet('交付说明')
        for row in [('项目', '内容'), ('店铺', identity['shopName']), ('shopId', identity['shopId']), ('venderId', identity['venderId']),
                    ('查询时间', report['checkedAt']), ('查询范围', report['scopeNote']), ('SKU数量', len(by_sku)), ('驳回素材记录数', len(records)),
                    ('默认处理', '白底/场景/透明图仅交付清单，不重生、不修图、不上传、不重新绑定、不代发申诉；不是已审核通过'),
                    ('其他字段', '不整SPU跳过；卖点图、短标题等仍按各自授权及计划处理；真正缺图（非驳回）按原计划维护'),
                    ('状态口径', '只包含status=5的白底/场景/透明图；审核中、通过、缺失不列为驳回；原因空白表示平台未返回'),
                    ('原证据', '旧图、URL、冻结计划和回执保持不变；本表是申诉材料，不是平台导入模板'), ('快照SHA256', digest)]:
            notes.append(row)
        widths = {'SKU清单': [22, 22, 60, 25, 40], '驳回原因明细': [22, 22, 60, 18, 16, 12, 12, 65, 85], '交付说明': [24, 115]}
        for sheet in workbook:
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            sheet.row_dimensions[1].height = 28
            for index, width in enumerate(widths[sheet.title], 1):
                sheet.column_dimensions[get_column_letter(index)].width = width
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = 's'
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
                    if cell.row == 1:
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid', fgColor='23435B')
                    else:
                        cell.font = Font(size=11)
                        sheet.row_dimensions[cell.row].height = 60 if sheet.title == '驳回原因明细' else 46
            sheet.sheet_view.showGridLines = False
        try:
            with path.open('xb') as stream:
                workbook.save(stream)
        finally:
            workbook.close()
        _save_state(evidence, {**frozen, 'snapshotSha256': digest, 'fileSha256': _file_sha256(path), 'appealSubmitted': False})
    return {**result, 'appealFiles': [str(path)], 'snapshotSha256': digest, 'fileSha256': _file_sha256(path)}

def audit_generation_summary(path):
    """Estimate from the same approved sibling sources, not from SKU deficits or local alpha work."""
    rows=json.loads(Path(path).read_text(encoding='utf-8')).get('rows') or []
    missing={};sources={};approved=set();pending=set()
    for row in rows:
        spu=str(row.get('productId') or row.get('spuId'))
        for kind,slot in (row.get('slots') or {}).items():
            state=slot.get('state') or slot.get('status') if isinstance(slot,dict) else slot
            if state=='missing':missing.setdefault(spu,set()).add(kind)
            if state=='pending':pending.add((spu,kind))
            if state=='approved':
                approved.add((spu,kind))
                for value in slot.get('approvedValues') or [] if isinstance(slot,dict) else []:
                    if kind in IMAGE_SUFFIXES and _trusted_jd_image_url(value):sources.setdefault((spu,kind),set()).add(value)
    reuse=0;derived=0;new=0;generation_spus=set();uncertain=[]
    for spu,kinds in missing.items():
        for kind in sorted(kinds & set(IMAGE_SUFFIXES)):
            values=sources.get((spu,kind),set())
            if (spu,kind) in pending or len(values)>1 or ((spu,kind) in approved and not values):
                uncertain.append({'spuId':spu,'kind':kind,'reason':'来源缺失、歧义或审核中；先核对，不报精确付费量'})
            elif len(values)==1:reuse+=1
            elif kind=='transparent':derived+=1
            else:new+=1;generation_spus.add(spu)
    return {'generationSpuCount':len(generation_spus),'missingSpuCount':len(missing),
            'missingSlotCount':sum(len(v) for v in missing.values()),
            'imageGenerationRequestCount':None if uncertain else new,'newImageCandidateCount':new,
            'reuseImageSlotCount':reuse,'transparentDerivationCount':derived,'sourceIssues':uncertain,
            'estimateComplete':not uncertain,'spuImageReuse':True,
            'note':'按同SPU唯一已通过素材复用；透明图本地派生不计付费生图。不是最终扣费或绑定生效证明。'}


def audit_pop_coverage(client, expected_shop_name, title_workbooks=(), *, product_ids=None, authorized_sku_ids=None):
    seller = client.seller_info()
    identity = _shop_identity(seller)
    if identity['shopName'] != expected_shop_name or not seller.get('success') or not seller.get('whitelistMatch', True) or not seller.get('isPop') or not seller.get('active'):
        raise ValueError('coverage audit requires the expected active POP shop identity')
    scoped_products=product_ids is not None
    if product_ids is None:
        products = collect_jdo_pages(client.online_products, 100, 'productId', 'coverage online products')
        product_ids = [cell_text(item.get('productId')) for item in products]
    else:
        product_ids = list(dict.fromkeys(map(str, product_ids)))
    health = collect_jdo_pages_parallel(client.health_infos, 100, 'skuId', 'coverage health scores')
    scores = {cell_text(item.get('skuId')): item for item in health}
    siblings = []
    groups = list(_chunks(product_ids, 10))
    with ThreadPoolExecutor(max_workers=1 if len(groups) <= 2 else READ_CONCURRENCY) as pool:
        for group, found in zip(groups, pool.map(client.skus, groups)):
            if any(cell_text(item.get('productId')) not in group for item in found):
                raise ValueError('coverage SKU lookup returned an out-of-scope product')
            siblings.extend(found)
    sku_ids = [cell_text(item.get('skuId')) for item in siblings]
    if any(not sku_id for sku_id in sku_ids) or len(set(sku_ids)) != len(sku_ids):
        raise ValueError('coverage inventory contains empty or duplicate SKU IDs')
    online = [item for item in siblings if int(item.get('skuStatus') or item.get('status') or 0) == 103]
    if authorized_sku_ids is not None:
        allowed = set(map(str, authorized_sku_ids))
        online = [item for item in online if cell_text(item.get('skuId')) in allowed]
    online_ids = [cell_text(item.get('skuId')) for item in online]
    materials = _query_binding_materials(client, online_ids) if online_ids else {}
    rows = []
    issues = {}
    deficits = []
    rejected = []
    pending = []
    short_titles = []
    for item in online:
        sku_id = cell_text(item.get('skuId'))
        health_item = scores.get(sku_id) or {}
        details = [entry.get('improvementDetail') or {} for entry in health_item.get('improvementList') or []]
        for detail in details:
            code = cell_text(detail.get('troubleCode'))
            if code:
                issues[code] = issues.get(code, 0) + 1
            if code == 'hasShortTitle':
                short_titles.append(sku_id)
        slots = {}
        for slot, (kind, order) in JDO_MATERIAL_SLOTS.items():
            found = [entry for entry in materials[sku_id] if int(entry.get('materialType') or 0) == kind and int(entry.get('order') or 0) == order]
            statuses = [int(entry.get('status') or 0) for entry in found]
            approved = any(int(entry.get('status') or 0) == 4 and _material_value(entry) for entry in found)
            state = 'pending' if 3 in statuses else 'approved' if approved else 'rejected' if 5 in statuses else 'missing'
            slots[slot] = {'state': state, 'statuses': statuses, 'approvedValues':list(dict.fromkeys(_material_value(entry) for entry in found if int(entry.get('status') or 0)==4 and _material_value(entry))), 'auditReasons': list(dict.fromkeys(cell_text(entry.get('auditDesc')) for entry in found if entry.get('auditDesc')))}
        states = {value['state'] for value in slots.values()}
        if states & {'missing', 'rejected'}:
            deficits.append(sku_id)
        if 'rejected' in states:
            rejected.append(sku_id)
        if 'pending' in states:
            pending.append(sku_id)
        rows.append({'skuId': sku_id, 'productId': cell_text(item.get('productId')), 'skuName': cell_text(item.get('skuName')), 'healthScore': health_item.get('healthScore'), 'improvements': details, 'slots': slots})
    historical_ids = set()
    historical_files = []
    for source in title_workbooks:
        validation = validate_short_title_workbook(source)
        with closing(load_workbook(source, read_only=True)) as workbook:
            historical_ids.update(cell_text(row[0]) for row in workbook['Sheet1'].iter_rows(min_row=3, max_col=2, values_only=True) if row[0] is not None)
        historical_files.append(validation)
    if scoped_products:
        final_siblings=[item for group in groups for item in client.skus(group)]
        if any(cell_text(item.get('productId')) not in product_ids for item in final_siblings) or {cell_text(item.get('skuId')) for item in final_siblings}!=set(sku_ids):
            raise ValueError('目标商品SKU范围已改变，不能组合两次盘点')
    else:
        final_products = collect_jdo_pages(client.online_products, 100, 'productId', 'coverage final products')
        if {cell_text(item.get('productId')) for item in final_products} != set(product_ids):
            raise ValueError('on-sale product scope changed during coverage audit')
    if _shop_identity(client.seller_info()) != identity:
        raise ValueError('shop identity changed during coverage audit')
    appeals = collect_pop_image_appeals(online, materials)
    return {'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'appealRows': appeals, 'manualAppealSkuIds': list(dict.fromkeys(item['skuId'] for item in appeals)), 'shopIdentity': identity, 'onlineProductCount': len(product_ids), 'onlineSkuCount': len(online), 'allSiblingSkuCount': len(siblings), 'healthSkuCount': len(health), 'unscoredSkuIds': [sku for sku in online_ids if sku not in scores], 'materialDeficitSkuCount': len(deficits), 'materialDeficitSkuIds': deficits, 'rejectedSkuCount': len(rejected), 'rejectedSkuIds': rejected, 'pendingSkuCount': len(pending), 'pendingSkuIds': pending, 'shortTitleIssueSkuIds': list(dict.fromkeys(short_titles)), 'issueCounts': issues, 'historicalTitleSkuCount': len(historical_ids), 'historicalTitleFiles': historical_files, 'notInHistoricalTitleSkuIds': [sku for sku in online_ids if sku not in historical_ids], 'historicalTitleNoLongerOnlineSkuIds': sorted(historical_ids - set(online_ids)), 'rows': rows, 'writesPerformed': False, 'platformTitleImportVerified': False, 'scopeNote': 'Complete paginated on-sale inventory, not a transaction snapshot; scores and workbook delivery do not prove material acceptance. Rejected white/scene/transparent images default to manual appeal delivery, not automatic repair; other rejected slots require a reviewed strategy.'}

def _short_title_issue(score_item: dict[str, Any]) -> bool:
    for entry in score_item.get('improvementList') or []:
        detail = entry.get('improvementDetail') or {}
        if cell_text(detail.get('troubleCode')) == 'hasShortTitle':
            return True
    return False

def product_reference_url(payload, representative_sku_id=''):
    """Official product/detail shapes only; preserve representative SKU identity."""
    info = payload.get('productInfo') or {}
    skus = payload.get('skuList') or []
    own = next((row for row in skus if cell_text(row.get('skuId')) == cell_text(representative_sku_id)), {})
    material = payload.get('material') or info.get('material') or {}
    candidates = [own.get('logo'), own.get('skuImage'), payload.get('logo'), payload.get('productImage'), payload.get('skuImage'), info.get('logo')]
    candidates.extend(material.get('mainImages') or [])
    for raw in candidates:
        if isinstance(raw, dict):raw = raw.get('url') or raw.get('imageUrl') or raw.get('imgUrl')
        if raw:return _jd_image_url(raw)
    return ''

def discover_jdo_pop_source(client: Any, page_size: int=100, expected_shop_name: str | None=None, include_spu_ids: Iterable[str]=(), include_full_score: bool=False, off_shelf_spu_ids: Iterable[str]=(), scope_spu_ids: Iterable[str] | None=None) -> tuple[PreparedSource, dict[str, str], dict[str, dict[str, Any]]]:
    seller = client.seller_info()
    if not seller.get('success') or not seller.get('whitelistMatch', True):
        raise JdoPermissionError('current shop is not enabled for jdo-cli')
    if not seller.get('isPop') or not seller.get('active'):
        raise JdoError('auto-maintain requires an active POP shop')
    if expected_shop_name and cell_text(seller.get('shopName')) != cell_text(expected_shop_name):
        raise JdoError('current jdo-cli shop does not match --expected-shop-name')
    health_rows = collect_jdo_pages_parallel(client.health_infos, page_size, 'skuId', 'health score')
    scores = {cell_text(item.get('skuId')): item for item in health_rows if _numeric_score(item.get('healthScore')) is not None}
    low_scores = {sku_id: item for sku_id, item in scores.items() if 0 <= _numeric_score(item.get('healthScore')) <= 89}
    products_100 = collect_jdo_pages(client.online_products, 100, 'productId', 'online product 100')
    product_ids_100 = [cell_text(item.get('productId')) for item in products_100]
    included_spus = {cell_text(spu_id) for spu_id in include_spu_ids if cell_text(spu_id)}
    off_shelf_ids = [cell_text(spu_id) for spu_id in off_shelf_spu_ids if cell_text(spu_id)]
    requested_scope = set(map(str, scope_spu_ids)) if scope_spu_ids is not None else None
    included_spus |= requested_scope or set()
    unknown_spus = included_spus - set(product_ids_100) - set(off_shelf_ids)
    if unknown_spus:
        raise ValueError(f"requested resume SPU is not currently on sale: {','.join(sorted(unknown_spus))}")
    online_rows: list[dict[str, Any]] = []
    seen_online_skus: set[str] = set()
    sku_groups = list(_chunks([pid for pid in product_ids_100 if requested_scope is None or pid in requested_scope], 10))
    with ThreadPoolExecutor(max_workers=1 if len(sku_groups) <= 2 else READ_CONCURRENCY) as sku_pool:
        sku_pages = list(sku_pool.map(client.skus, sku_groups))
    for group, found in zip(sku_groups, sku_pages):
        if any(cell_text(item.get('productId')) not in group for item in found):raise ValueError('exact SKU lookup returned an out-of-scope product')
        for item in found:
            if int(item.get('skuStatus') or item.get('status') or 0) != 103:
                continue
            sku_id = cell_text(item.get('skuId'))
            if not sku_id or sku_id in seen_online_skus:
                raise ValueError(f'online SKU exact lookup contains an empty or duplicate skuId: {sku_id}')
            seen_online_skus.add(sku_id)
            online_rows.append(item)
    for spu_id in dict.fromkeys(off_shelf_ids):
        if requested_scope is not None and spu_id not in requested_scope:continue
        if spu_id in product_ids_100:
            continue
        product = next((item for item in client.products([spu_id]) if cell_text(item.get('productId')) == spu_id), None)
        if not product:
            raise ValueError(f'off-shelf SPU not found in this shop: {spu_id}')
        products_100.append(product)
        product_ids_100.append(spu_id)
        for item in client.skus([spu_id]):
            sku_id = cell_text(item.get('skuId'))
            if not sku_id or sku_id in seen_online_skus:
                continue
            seen_online_skus.add(sku_id)
            online_rows.append({**item, 'productId': spu_id})
        included_spus.add(spu_id)
    online_spu_by_sku = {cell_text(item.get('skuId')): cell_text(item.get('productId')) for item in online_rows}
    low_spus = {online_spu_by_sku[sku_id] for sku_id in low_scores if sku_id in online_spu_by_sku}
    # Low scores select candidates, not imaginary deficits. Reuse the mature slot audit.
    inspect_rows = [item for item in online_rows if include_full_score or cell_text(item.get('productId')) in low_spus | included_spus or cell_text(item.get('skuId')) not in scores]
    missing_by_spu, existing_by_spu = inspect_unscored_materials(client, inspect_rows)
    # SPUs whose images are complete but still carry hasShortTitle must be planned for titles only.
    title_only_spus = ({online_spu_by_sku[sku_id] for sku_id, item in scores.items() if sku_id in online_spu_by_sku and _short_title_issue(item)} - low_spus - set(missing_by_spu)) if include_full_score else set()
    for spu_id in title_only_spus:
        missing_by_spu[spu_id] = set()
    selected_spus = low_spus | set(missing_by_spu)
    resumed_spus = included_spus - selected_spus
    for spu_id in resumed_spus:
        missing_by_spu.setdefault(spu_id, set())
    selected_spus |= included_spus
    headers = ('SKUID', '商品名称', 'SPUID', '商品信息分', '发现来源', '短标题判断')
    if not selected_spus:
        prepared = PreparedSource('jdo-pop', '实时待维护商品', headers, (), (), len(online_rows), len(online_rows), 0)
        return (prepared, {}, {})
    retained: list[SourceRow] = []
    rows_by_spu: dict[str, list[SourceRow]] = {}
    sku_payloads: dict[str, dict[str, Any]] = {}
    for item in online_rows:
        spu_id = cell_text(item.get('productId'))
        if spu_id not in selected_spus:
            continue
        sku_id = cell_text(item.get('skuId'))
        title = cell_text(item.get('skuName'))
        score = cell_text((scores.get(sku_id) or {}).get('healthScore'))
        score_item = scores.get(sku_id) or {}
        if spu_id in low_spus:
            source, short_title_status = ('信息分0-89', '按现有流程维护')
        elif spu_id in resumed_spus:
            source, short_title_status = ('指定SPU续跑', '沿用任务状态')
        elif score_item:
            source = '信息分90+-素材直查缺失'
            short_title_status = '短标题待生成' if _short_title_issue(score_item) else '短标题已达标'
        else:
            source, short_title_status = ('未产分-素材直查缺失', '推定缺失')
        row = SourceRow(sku_id, title, spu_id, score, (sku_id, title, spu_id, score, source, short_title_status), 'jdo-cli', '实时待维护商品')
        retained.append(row)
        rows_by_spu.setdefault(spu_id, []).append(row)
        sku_payloads.setdefault(spu_id, item)
    jobs: list[SpuJob] = []
    for spu_id, items in rows_by_spu.items():
        missing = missing_by_spu.get(spu_id, set())
        short_title_sku_ids = tuple(item.sku_id for item in items if item.sku_id not in scores or _short_title_issue(scores[item.sku_id]))
        jobs.append(SpuJob(spu_id=spu_id, representative_sku_id=items[0].sku_id, title=items[0].title, sku_ids=tuple((item.sku_id for item in items)), skus=tuple(((item.sku_id, item.title) for item in items)), short_title_sku_ids=short_title_sku_ids, needs_selling_points=any((slot.startswith('point') for slot in missing)), needs_white=bool({'white', 'transparent'} & missing), needs_scenes=bool({'scene1', 'scene2'} & missing), needs_selling_image='selling' in missing, needs_transparent='transparent' in missing))
    product_ids = list(dict.fromkeys((row.spu_id for row in retained)))
    product_map = {cell_text(item.get('productId')): item for item in products_100}
    references: dict[str, str] = {}
    for spu_id in dict.fromkeys((row.spu_id for row in retained)):
        product = product_map.get(spu_id) or {}
        sku = sku_payloads.get(spu_id) or {}
        image = product_reference_url(product, cell_text(sku.get('skuId'))) or product_reference_url(sku, cell_text(sku.get('skuId')))
        if not image:
            detail = client._get('jdo-product-status', '/rest/sp-product/v0/products/{productId}', {'productId': int(spu_id), 'scene': 'pop'}).get('data') or {}
            image = product_reference_url(detail, cell_text(sku.get('skuId')))
        if image:
            references[spu_id] = image
    prepared = PreparedSource('jdo-pop', '实时待维护商品', headers, tuple(retained), tuple(jobs), len(online_rows), len(online_rows) - len(retained), 0)
    return (prepared, references, existing_by_spu)

def prepare_standard_source(path: str | Path, selected_sheet: str | None=None) -> PreparedSource:
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise ValueError('只支持 .xlsx 底表。')
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        _reset_read_only_dimensions(workbook)
        sheet, header_row, headers, columns = _sheet_candidate(workbook, selected_sheet)
        rows, seen = ([], {})
        original = filtered = duplicates = 0
        for row_number, raw in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
            if not any((cell_text(value) for value in raw)):
                continue
            original += 1
            sku_id = cell_text(raw[columns['sku']] if columns['sku'] < len(raw) else None)
            spu_id = cell_text(raw[columns['spu']] if columns['spu'] < len(raw) else None)
            title = cell_text(raw[columns['title']] if columns['title'] < len(raw) else None)
            if not re.fullmatch('\\d+', sku_id) or not re.fullmatch('\\d+', spu_id) or (not title):
                raise ValueError(f'工作表“{sheet.title}”第 {row_number} 行的 SKU、SPU 或商品名称无效。')
            score = cell_text(raw[columns['score']]) if 'score' in columns and columns['score'] < len(raw) else ''
            numeric_score = _numeric_score(score)
            if 'score' in columns and numeric_score is not None and (not 0 <= numeric_score <= 89):
                filtered += 1
                continue
            item = SourceRow(sku_id, title, spu_id, score, tuple(raw), str(path.resolve()), sheet.title, row_number, header_row)
            previous = seen.get(sku_id)
            if previous:
                if previous.spu_id != spu_id or previous.title != title:
                    raise ValueError(f'SKUID {sku_id} 在底表中对应不同 SPU 或商品名称。')
                duplicates += 1
            else:
                seen[sku_id] = item
            rows.append(item)
        if not rows:
            raise ValueError('过滤后没有可处理商品。')
        return PreparedSource('procurement' if 'score' in columns else 'ordinary', sheet.title, tuple(headers), tuple(rows), _jobs_from_rows(rows), original, filtered, duplicates)
    finally:
        workbook.close()

def split_rows_by_spu(rows: Iterable[SourceRow], maximum_spus=None) -> list[list[SourceRow]]:
    maximum_spus=maximum_spus or MAX_SPUS_PER_BATCH
    if maximum_spus < 1:
        raise ValueError('maximum_spus 必须大于 0。')
    groups: dict[str, list[SourceRow]] = {}
    for row in rows:
        groups.setdefault(row.spu_id, []).append(row)
    chunks, current = ([], [])
    for index, items in enumerate(groups.values()):
        if index and index % maximum_spus == 0:
            chunks.append(current)
            current = []
        current.extend(items)
    if current:
        chunks.append(current)
    return chunks

def frozen_scope_batches(prepared, output_dir):
    """Retain the original batch identity when an approved whole-shop plan is narrowed."""
    chunks = split_rows_by_spu(prepared.rows)
    plan = json.loads((Path(output_dir)/AUTO_MAINTAIN_PLAN_NAME).read_text(encoding='utf-8'))
    all_rows = _prepared_from_payload(plan['prepared']).rows
    all_chunks = split_rows_by_spu(all_rows)
    if len(chunks)==1 and len(all_chunks)==1:return [(1,chunks[0])]
    result = []
    for rows in chunks:
        keys = {row.spu_id for row in rows}
        matching = [index for index, original in enumerate(all_chunks,1) if keys == {row.spu_id for row in original}]
        if len(matching) != 1:
            raise ValueError('冻结计划子集必须保持原整批组成；不支持半批拆分或跨批组合，请重新确认原范围')
        result.append((matching[0],rows))
    return result


def write_split_sources(prepared: PreparedSource, output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, rows in enumerate(split_rows_by_spu(prepared.rows), 1):
        spu_count = len({row.spu_id for row in rows})
        source_groups: dict[tuple[str, str, int], list[SourceRow]] = {}
        for row in rows:
            if row.source_path and row.sheet_name and row.row_number:
                source_groups.setdefault((row.source_path, row.sheet_name, row.header_row), []).append(row)
        if source_groups and all((row.source_path and row.sheet_name and row.row_number for row in rows)):
            add_source_name = prepared.source_type == 'self-operated' or len(source_groups) > 1
            for (source_name, sheet_name, header_row), source_rows in source_groups.items():
                source_path = Path(source_name)
                suffix = f'_{source_path.stem}' if add_source_name else ''
                path = output_dir / f'待执行底表_第{index:03d}批_{spu_count}SPU{suffix}.xlsx'
                workbook = load_workbook(source_path)
                try:
                    sheet = workbook[sheet_name]
                    included = {row.row_number for row in source_rows}
                    for row_number in range(sheet.max_row, header_row, -1):
                        if row_number not in included:
                            sheet.delete_rows(row_number)
                    workbook.save(path)
                finally:
                    workbook.close()
                paths.append(path)
            continue
        path = output_dir / f'待执行底表_第{index:03d}批_{spu_count}SPU.xlsx'
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = prepared.sheet_name[:31] or '待维护SKU'
        sheet.append(list(prepared.headers) if prepared.headers else ['SKUID', '商品名称', 'SPUID', '商品信息分'])
        for row in rows:
            sheet.append(list(row.raw) if row.raw else [row.sku_id, row.title, row.spu_id, row.score])
        workbook.save(path)
        workbook.close()
        paths.append(path)
    return paths

def selling_point_prompts(title: str) -> tuple[str, str]:
    banned = '、'.join(sorted(BANNED_SELLING_POINT_TERMS))
    system = f'你是一名资深京东电商文案策划。仅输出3个词组式卖点，每个2-8个字符；真实、不重复；不得使用绝对词、促销词、品牌或平台信息、销量评价、无依据认证功效或特殊符号；以下禁用词及包含它们的表达不得出现：{banned}。卖点将用于同一SPU全部SKU，禁止规格、尺寸、颜色、价格、型号、款式、图案、容量、重量、数量、套装、版本等SKU差异属性。标题只用于识别品类，只提炼品类共有功能、体验、工艺、便利性或场景。'
    return (system, f'商品长标题：{title}\n只输出JSON：{{"selling_points":["卖点1","卖点2","卖点3"]}}')

def short_title_prompts(skus: Iterable[tuple[str, str]]) -> tuple[str, str]:
    rows = [{'sku_id': sku_id, 'long_title': title} for sku_id, title in skus]
    system = '为每个输入SKU生成短标题，不得遗漏或新增SKU。只能依据对应长标题压缩，不得虚构。保留商品品类和必要SKU区分信息，删除价格、促销、夸张和平台词。加权长度必须16-30字符；仅汉字按2计，数字、英文和符号均按1计，乘号×、全角数字及括号也是1，不能将所有非ASCII字符计为2。只输出JSON。'
    return (system, f'SKU长标题：\n{json.dumps(rows, ensure_ascii=False)}\n输出：{{"short_titles":[{{"sku_id":"输入SKUID","short_title":"短标题"}}]}}')

def _shared_image_rules(title: str | None) -> str:
    title_rule = f'商品长标题：【{title}】。标题只用于识别商品大类和合理场景；' if title else '本轮不提供商品标题；'
    return '参考图是商品外观、结构、数量和组合关系的唯一依据。' + title_rule + '不得把标题作为外观、规格、颜色、材质、图案、数量、配件或包装依据。严格保持轮廓、结构、比例、颜色、材质、纹理、图案、组件数量、可见配件和组合关系。不得增加礼盒、包装、赠品、配件或参考图中不存在的部件。画面1:1，最终用于800×800；商品完整清晰、无遮挡、不裁切、位于中央安全区；禁止水印、Logo、品牌、价格、促销、平台标识和无关文字。'

def image_prompt(kind: str, title: str | None) -> str:
    shared = _shared_image_rules(title)
    prompts = {'white': '生成严格纯白#FFFFFF商品白底图，只更换背景，不改变商品本体；允许极轻微接触阴影。', 'scene1': '生成明亮整洁、符合实际用途的日常场景图；只更换环境、背景和光线，不出现文字。', 'scene2': '生成温暖高级且真实的另一日常场景，构图与第一张明显不同；不改变商品，不出现文字。', 'selling': '生成京东电商卖点主图，只增加简洁可信的卖点文案和版式，不遮挡商品，不重新设计商品。'}
    if kind not in prompts:
        raise ValueError(f'未知图片类型：{kind}')
    return shared + prompts[kind]

def _json_object(text: str) -> dict:
    cleaned = re.sub('^```(?:json)?\\s*|\\s*```$', '', cell_text(text), flags=re.I)
    start, end = (cleaned.find('{'), cleaned.rfind('}'))
    if start < 0 or end < start:
        raise ValueError('模型未返回 JSON 对象。')
    return json.loads(cleaned[start:end + 1])

class AdaptiveLimiter:
    """Semaphore whose limit can shrink at runtime (gateway overload: dropped connections).

    Shrinking never interrupts current holders; new entrants wait until active < limit.
    The limit is intentionally not restored inside a run (disconnect waves recur under load)."""

    def __init__(self, limit: int, *, floor: int=4, cooldown: float=0.0):
        self.cooldown = cooldown
        self._last_shrink = float('-inf')
        self._cond = threading.Condition()
        self.limit = max(1, int(limit))
        self.floor = max(1, min(int(floor), self.limit))
        self._active = 0

    def __enter__(self):
        with self._cond:
            while self._active >= self.limit:
                self._cond.wait()
            self._active += 1
        return self

    def __exit__(self, *exc):
        with self._cond:
            self._active -= 1
            self._cond.notify_all()
        return False

    def shrink(self) -> int:
        with self._cond:
            now = time.monotonic()
            if now - self._last_shrink >= self.cooldown:
                self._last_shrink = now
                self.limit = max(self.floor, self.limit // 2)
                self._cond.notify_all()
            return self.limit

class RequestGate:

    def __init__(self, requests_per_minute: int | None=None, start_interval: float=0.0):
        self.requests_per_minute = requests_per_minute
        self.start_interval = start_interval
        self.lock = threading.Lock()
        self.starts = deque()
        self.last_start = 0.0

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.starts and now - self.starts[0] >= 60:
                    self.starts.popleft()
                delay = max(0.0, self.start_interval - (now - self.last_start))
                if self.requests_per_minute and len(self.starts) >= self.requests_per_minute:
                    delay = max(delay, 60 - (now - self.starts[0]))
                if delay <= 0:
                    self.starts.append(now)
                    self.last_start = now
                    return
            time.sleep(min(delay, 1.0))

class ModelRequestLimitError(RuntimeError):
    """This invocation has used its explicitly approved image-request allowance."""

class ModelQuotaExceeded(RuntimeError):

    def __init__(self, detail: str | None=None):
        message = '模型接口明确返回当前模型配额已用尽（code=2007）；已暂停新模型请求，恢复额度后使用原目录继续。'
        super().__init__(message + (f'（{detail}）' if detail else ''))

class ModelUnauthorized(RuntimeError):

    def __init__(self, model: str):
        super().__init__(f'当前业务未授权使用生图模型 {model}；不要重试，改用已授权模型或 JoyAgent-image 兜底，并让商家/平台开通该模型授权。')

class ModelModerationBlocked(RuntimeError):

    def __init__(self, detail: str=''):
        message = ('GPT 生图模型池全部被内容安全策略拦截；不要继续重试同一参考图。'
                   '请改用纯商品参考图（无人物/道具/营销文字）或 JoyAgent-image 兜底。')
        super().__init__(message + (f'（{detail}）' if detail else ''))

def is_model_unauthorized(error: BaseException) -> bool:
    return bool(re.search('未授权使用该生图模型|not authorized|unauthorized', str(error), re.I))

def pool_switchable(error: Exception) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    message = str(error)
    if re.search(r'HTTP (?:408|409|425|429|5\d\d)\b', message):
        return True
    lowered = message.lower()
    return 'timeout' in lowered or 'timed out' in lowered or 'get access token failed' in lowered

def _merge_image_model_stats(previous: dict[str, Any] | None, stats: dict[str, Any]) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    merged: dict[str, Any] = {'usage': {}, 'failures': {}}
    for bucket in ('usage', 'failures'):
        for source in (previous.get(bucket), stats.get(bucket)):
            for model, count in (source or {}).items():
                merged[bucket][model] = merged[bucket].get(model, 0) + int(count)
    merged['exhausted'] = sorted(set(previous.get('exhausted') or []) | set(stats.get('exhausted') or []))
    merged['runs'] = list(previous.get('runs') or []) + [{'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **stats}]
    return merged

class ModelClient:

    def __init__(self, api_key: str, timeout: float=600.0, image_concurrency: int | None=None, text_model: str | None=None):
        if not api_key:
            from heideng_merchant.mature_image import merchant_key
            api_key=merchant_key()
        if not api_key.isascii() or any((character.isspace() for character in api_key)):
            raise ValueError(f'{PROVIDER.api_key_env} 未设置或格式无效。')
        from heideng_merchant.mature_image import MerchantImageClient
        self._merchant_images = MerchantImageClient(api_key)
        self.http = httpx.Client(timeout=timeout, headers={'Authorization': f'Bearer {api_key}'})
        self.download_http = httpx.Client(timeout=120.0)
        self.text_gate = RequestGate(PROVIDER.requests_per_minute, PROVIDER.text_start_interval_seconds)
        self.image_gate = self.text_gate if PROVIDER.requests_per_minute else RequestGate(None, PROVIDER.image_start_interval_seconds)
        self.text_semaphore = threading.Semaphore(PROVIDER.text_concurrency)
        requested = image_concurrency or PROVIDER.default_image_concurrency
        self.image_semaphore = AdaptiveLimiter(max(1, min(PROVIDER.maximum_image_concurrency, requested)), cooldown=20.0)
        self.text_model = text_model or PROVIDER.text_model
        self._text_pool = None
        self._text_key = api_key if text_model == 'auto' else None
        self._text_pool_lock = threading.Lock()
        self._title_registry = {}
        self._title_registry_lock = threading.Lock()
        self.quota_exhausted = False
        self.exhausted_models: set[str] = set()
        self.unavailable_models: set[str] = set()
        self.pool_usage: dict[str, int] = {}
        self.pool_failures: dict[str, int] = {}
        self.pool_attempts: dict[str, int] = {}
        self.max_model_requests=None
        self._pool_slots = tuple((model for model, weight in PROVIDER.image_model_pool for _ in range(max(1, int(weight)))))
        self._pool_cursor = 0
        self._material_context = threading.local()
        self._slot_pool_cursors = {}
        self._pool_lock = threading.Lock()
        self.cancel_event = None

    def close(self) -> None:
        if self._text_pool is not None:self._text_pool.close()
        self._text_key = None
        self.http.close()
        self.download_http.close()

    def image_model_stats(self) -> dict[str, Any]:
        with self._pool_lock:
            return {'usage': dict(self.pool_usage), 'failures': dict(self.pool_failures), 'attempts':dict(self.pool_attempts),'exhausted': sorted(self.exhausted_models)}

    def material_pool_models(self, kind):
        if kind == 'transparent':
            raise ValueError('Transparent images are local derivations, never model requests')
        if kind not in {'white', 'scene1', 'scene2', 'selling'}:
            raise ValueError('Unknown image material kind')
        pool = SCENE_SELLING_MODEL_POOL if kind in {'scene1', 'scene2', 'selling'} else PROVIDER.image_model_pool
        return [model for model, _weight in pool]

    def edit_material_image(self, kind, prompt, source_path, *, model=None):
        self.material_pool_models(kind)
        selected = model or IMAGE_MODEL_POOL_ALIAS
        if kind == 'white' and selected == SCENE_SELLING_EXTRA_MODEL:
            raise ValueError('Oxygen-Product-Pro is forbidden for white and transparent materials')
        previous = getattr(self._material_context, 'kind', None)
        self._material_context.kind = kind
        try:
            return self.edit_image(prompt, source_path, model=selected)
        finally:
            self._material_context.kind = previous

    def _remaining_pool_models(self) -> list[str]:
        kind = getattr(self._material_context, 'kind', None)
        models = self.material_pool_models(kind) if kind else [model for model, _weight in PROVIDER.image_model_pool]
        return [model for model in models if model not in self.exhausted_models and model not in self.unavailable_models]

    def _next_pool_model(self) -> str:
        with self._pool_lock:
            for _ in range(max(1, len(self._pool_slots)) * 2):
                model = self._pool_slots[self._pool_cursor % len(self._pool_slots)]
                self._pool_cursor += 1
                if model not in self.exhausted_models and model not in self.unavailable_models:
                    return model
        raise ModelQuotaExceeded('GPT 生图模型池配额已用尽')

    def _pool_candidates(self) -> list[str]:
        kind = getattr(self._material_context, 'kind', None)
        if kind in {'scene1', 'scene2', 'selling'}:
            slots = [model for model, weight in SCENE_SELLING_MODEL_POOL for _ in range(weight)]
            with self._pool_lock:
                cursor = self._slot_pool_cursors.get(kind, 0)
                choices = [slots[(cursor+i) % len(slots)] for i in range(len(slots))]
                selected = next((name for name in choices if name not in self.exhausted_models and name not in self.unavailable_models), None)
                if selected is None: raise ModelQuotaExceeded('Slot model pool exhausted')
                self._slot_pool_cursors[kind] = cursor + choices.index(selected) + 1
            candidates = [selected]
        else:
            candidates = [self._next_pool_model()]
        for model in self._remaining_pool_models():
            if model not in candidates:
                candidates.append(model)
        return candidates

    def _record_model(self, model: str, *, failed: bool=False) -> None:
        with self._pool_lock:
            bucket = self.pool_failures if failed else self.pool_usage
            bucket[model] = bucket.get(model, 0) + 1

    def _download_image(self, url: str) -> bytes:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in {'http', 'https'} or not (host == '360buyimg.com' or host.endswith('.360buyimg.com')):
            raise ValueError('图片响应 URL 不在可信京东图片域名内，拒绝下载。')
        response = None
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.jd.com/'}
        for attempt in range(4):
            response = self.download_http.get(url, headers=headers)
            if response.status_code < 400:
                break
            transient = response.status_code in {403, 408, 429} or response.status_code >= 500
            if not transient or attempt == 3:
                raise RuntimeError(f'图片下载失败：HTTP {response.status_code}')
            time.sleep(1.5 * (attempt + 1))
        if not response.content:
            raise ValueError('下载的图片为空。')
        return response.content

    def _request(self, *args, **kwargs):
        raise RuntimeError('raw-model-transport-disabled-use-mature-sufy-image-client')

    def text(self, system: str, user: str) -> str:
        from pop_text import TextPoolUnavailable
        raise TextPoolUnavailable('external-text-provider-not-configured; preserve frozen SKU scope and use the mature Agent-authored title delivery/import workflow')

    def edit_image(self, prompt: str, source_path: Path, *, model: str | None=None) -> bytes:
        # External paid image calls are single-attempt; unknown output is not a pool-switch retry.
        if model not in (None, IMAGE_MODEL_POOL_ALIAS, 'gpt-image-2.5'):
            raise RuntimeError('merchant-image-model-not-configured')
        with self.image_semaphore:
            self.image_gate.wait()
            return self._edit_once(prompt, source_path, 'gpt-image-2.5')

    def reserve_image_request(self, model):
        with self._pool_lock:
            event=getattr(self,'cancel_event',None)
            if event is not None and event.is_set():raise JdoWriteUncertainError('原结果待核对，未发起新的图片请求。')
            if self.max_model_requests is not None and sum(self.pool_attempts.values())>=self.max_model_requests:
                raise ModelRequestLimitError('model-request-budget-exhausted；本次图片请求上限已达到，未再调用模型。')
            self.pool_attempts[model]=self.pool_attempts.get(model,0)+1

    def _edit_once(self, prompt: str, source_path: Path, image_model: str, *, pool: bool=False) -> bytes:
        if image_model != 'gpt-image-2.5':raise RuntimeError('merchant-image-model-not-configured')
        self.reserve_image_request(image_model)
        try:result = self._merchant_images.edit(prompt=prompt, images=[source_path])
        except Exception:
            self._record_model(image_model,failed=True)
            raise
        self._record_model(image_model)
        return result

    def text_pool(self):
        with self._text_pool_lock:
            if self._text_pool is None:
                from pop_text import TextPool
                self._text_pool = TextPool(self._text_key, timeout=120, cancelled=lambda: self.cancel_event is not None and self.cancel_event.is_set())
                self._text_key = None
            return self._text_pool

    def text_model_stats(self):
        return self._text_pool.stats() if self._text_pool is not None else {'usage': {}, 'discoverySeconds': 0, 'keyLogged': False}

    def selling_points(self, title: str) -> list[str]:
        system, user = selling_point_prompts(title)
        if getattr(self, 'text_model', None) == 'auto':
            def validate(value):
                points=value['selling_points']
                if not isinstance(points,list) or any(not isinstance(point,str) for point in points):raise ValueError('Selling points must be a list of strings')
                return validate_selling_points(points)
            return self.text_pool().generate(system, user, validate)
        last_error = None
        for _ in range(3):
            try:
                return validate_selling_points(_json_object(self.text(system, user))['selling_points'])
            except (KeyError, TypeError, ValueError) as error:
                last_error = error
                user += '\n上次输出不合规，请只重写 JSON 并严格遵守长度和禁用词。'
        raise ValueError(f'连续3次未生成合规卖点：{last_error}')

    def short_titles(self, skus: Iterable[tuple[str, str]], *, partial: bool=False) -> dict[str, str]:
        skus = tuple(skus)
        expected = {sku_id for sku_id, _ in skus}
        system, user = short_title_prompts(skus)
        if getattr(self, 'text_model', None) == 'auto':
            from pop_text import TextPoolUnavailable
            def validate_for(scope):
                def validate(value):
                    rows=value['short_titles']
                    if not isinstance(rows,list) or any(not isinstance(item,dict) or not isinstance(item.get('sku_id'),str) or not isinstance(item.get('short_title'),str) for item in rows):raise ValueError('Expected string SKU/title rows')
                    seen={};accepted={};repeated=set()
                    for item in rows:
                        sku=cell_text(item['sku_id']);text=cell_text(item['short_title'])
                        if sku in seen:repeated.add(sku)
                        if sku in scope:seen[sku]=text
                    for sku in repeated:seen.pop(sku,None)
                    counts={}
                    for text in seen.values():counts[text]=counts.get(text,0)+1
                    with self._title_registry_lock:
                        for sku,text in seen.items():
                            other=self._title_registry.get(text)
                            # Keep only exact, valid, unique rows; failed rows are re-asked alone.
                            if valid_short_title(text) and counts[text]==1 and (other is None or other==sku):accepted[sku]=text
                            elif valid_short_title(text):taken.add(text)
                        if not accepted:raise ValueError('No valid short title rows in this response')
                        self._title_registry.update({text:sku for sku,text in accepted.items()})
                    return accepted
                return validate
            merged={};remaining=skus;taken=set()
            for _ in range(3):
                scope={sku for sku,_ in remaining}
                system,user=short_title_prompts(remaining)
                if taken:
                    # Sibling SPUs often share identical long titles; name the collisions so the retry
                    # differentiates instead of producing the same shop-duplicate title again.
                    user+='\n以下短标题已被店内其他SKU占用，必须避开且不得与之相同，请调整词序或补充该SKU规格以区分：'+json.dumps(sorted(taken)[:60],ensure_ascii=False)
                try:merged.update(self.text_pool().generate(system,user,validate_for(scope)))
                except TextPoolUnavailable:
                    if not merged:raise
                    break
                remaining=tuple((sku,title) for sku,title in remaining if sku not in merged)
                if not remaining:return merged
            if partial and merged:return merged
            raise TextPoolUnavailable('Some short titles failed validation; Agent fills only unresolved frozen SKU text')
        last_error = None
        for _ in range(3):
            try:
                rows = _json_object(self.text(system, user))['short_titles']
                result = {cell_text(item['sku_id']): cell_text(item['short_title']) for item in rows}
                if set(result) != expected or any((not valid_short_title(value) for value in result.values())):
                    raise ValueError('短标题存在缺失、额外 SKU 或长度不合规。')
                return result
            except (KeyError, TypeError, ValueError) as error:
                last_error = error
                user += '\n上次输出不合规，请只重写缺失或长度不合规项并保持 SKUID 精确一致。'
        raise ValueError(f'连续3次未生成合规短标题：{last_error}')

def _square_800(image: Image.Image, background: tuple[int, ...]) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)
    canvas = Image.new(image.mode, (800, 800), background)
    offset = ((800 - image.width) // 2, (800 - image.height) // 2)
    canvas.paste(image, offset, image if image.mode == 'RGBA' else None)
    return canvas

def normalize_jpeg(content: bytes, output: Path, pure_white: bool=False) -> None:
    with Image.open(BytesIO(content)) as opened:
        image = _square_800(opened.convert('RGB'), (255, 255, 255))
    if pure_white:
        corners = ((0, 0), (799, 0), (0, 799), (799, 799))
        if True:  # always inset to 600px; white corners alone do not prove a clean border
            inset = image.copy()
            inset.thumbnail((600, 600), Image.Resampling.LANCZOS)
            image = Image.new('RGB', (800, 800), (255, 255, 255))
            image.paste(inset, ((800 - inset.width) // 2, (800 - inset.height) // 2))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue = pixels[x, y]
                if min(red, green, blue) >= 235 and max(red, green, blue) - min(red, green, blue) <= 24:
                    pixels[x, y] = (255, 255, 255)
    output.parent.mkdir(parents=True, exist_ok=True)
    for quality in (95, 92, 88, 84, 80, 75):
        for attempt in range(4):
            try:
                image.save(output, 'JPEG', quality=quality, optimize=True, progressive=True, subsampling=0)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.5 * (attempt + 1))
        if output.stat().st_size <= 1000000:
            return
    raise ValueError(f'JPG 超过 1MB：{output}')

def make_transparent(source: Path, output: Path, *, quality: str='fast') -> dict:
    # Efficiency first: normal maintenance uses the fast local flood algorithm.
    # Only rejected transparent repair requests the slower neural model explicitly.
    if quality == 'fast':
        started = time.perf_counter()
        make_transparent_legacy(source, output)
        return {'status': 'generated-local', 'backend': 'legacy-flood', 'elapsedSeconds': round(time.perf_counter() - started, 3), 'modelCalls': 0, 'platformWrites': 0}
    if quality != 'neural':
        raise ValueError('Transparent quality must be fast or neural')
    from pop_cutout import make_cutout
    return make_cutout(source, output)

def make_transparent_legacy(source: Path, output: Path) -> None:
    with Image.open(source) as opened:
        rgb = _square_800(opened.convert('RGB'), (255, 255, 255))
    width, height = rgb.size
    pixels = rgb.load()
    visited = bytearray(width * height)
    background = bytearray(width * height)
    queue = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if not visited[index]:
            visited[index] = 1
            queue.append((x, y))
    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)
    while queue:
        x, y = queue.popleft()
        pixel = pixels[x, y]
        if min(pixel) < 225 or max(pixel) - min(pixel) > 36:
            continue
        background[y * width + x] = 1
        if x:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)
    rgba = rgb.convert('RGBA')
    alpha = Image.new('L', (width, height), 255)
    alpha_pixels = alpha.load()
    for y in range(height):
        for x in range(width):
            if background[y * width + x]:
                alpha_pixels[x, y] = 0
    rgba.putalpha(alpha)
    output.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(output, 'PNG', optimize=True)
    if output.stat().st_size > 3000000:
        raise ValueError(f'透明 PNG 超过 3MB：{output}')

def repair_transparent_mask(source, output, source_sha256, foreground_regions):
    source = Path(source)
    output = Path(output)
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != source_sha256:
        raise ValueError('transparent repair source hash changed')
    if not foreground_regions or any(len(region) < 3 for region in foreground_regions):
        raise ValueError('explicit source-bound foreground polygons are required')
    for region in foreground_regions:
        for point in region:
            if len(point) != 2 or any(not isinstance(value, (int, float)) or not 0 <= value <= 799 for value in point):
                raise ValueError('foreground coordinates must be finite and inside the source image')
    with Image.open(BytesIO(content)) as opened:
        if opened.size != (800, 800):
            raise ValueError('transparent repair requires an existing 800x800 source')
        image = opened.convert('RGBA')
    mask = Image.new('L', (3200, 3200), 0)
    draw = ImageDraw.Draw(mask)
    for region in foreground_regions:
        draw.polygon([(round(horizontal * 4), round(vertical * 4)) for horizontal, vertical in region], fill=255)
    image.putalpha(mask.resize((800, 800), Image.Resampling.LANCZOS))
    buffer = BytesIO()
    image.save(buffer, 'PNG', optimize=True)
    repaired = buffer.getvalue()
    if len(repaired) > 3000000:
        raise ValueError('transparent repair PNG exceeds 3MB')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(repaired)
    return {'source': str(source.resolve()), 'sourceSha256': source_sha256, 'output': str(output.resolve()), 'outputSha256': hashlib.sha256(repaired).hexdigest(), 'foregroundRegions': foreground_regions, 'rgbPixelsUnchanged': True, 'modelCalls': 0, 'platformWrites': 0}

def _white_background_ratio(rgb: Image.Image, threshold: int=245) -> float:
    sample = rgb.resize((80, 80), Image.Resampling.BILINEAR)
    pixels = list(sample.get_flattened_data()) if hasattr(sample, 'get_flattened_data') else list(sample.getdata())
    return sum(1 for red, green, blue in pixels if min(red, green, blue) >= threshold) / len(pixels)

def _border_white_ratio(rgb: Image.Image, threshold: int=245) -> float:
    sample = rgb.resize((200, 200), Image.Resampling.BILINEAR)
    pixels = sample.load()
    low, high = 12, 32
    total = 0
    white = 0
    for y in range(200):
        for x in range(200):
            if low <= x < high or low <= y < high or 200 - high <= x < 200 - low or 200 - high <= y < 200 - low:
                total += 1
                if min(pixels[x, y]) >= threshold:
                    white += 1
    return white / total if total else 0.0

def valid_material_image(path: Path, kind: str) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.size != (800, 800):
                return False
            if kind == 'transparent':
                return image.format == 'PNG' and 'A' in image.mode and (path.stat().st_size <= 3000000)
            if image.format not in {'JPEG', 'JPG'} or path.stat().st_size > 1000000:
                return False
            if kind == 'white':
                rgb = image.convert('RGB')
                if not all((min(rgb.getpixel(point)) >= 248 for point in ((0, 0), (799, 0), (0, 799), (799, 799)))):
                    return False
                return _white_background_ratio(rgb) >= 0.05 and _border_white_ratio(rgb) >= 0.50
            return True
    except (OSError, ValueError):
        return False

def resolve_reference(reference_dir: Path, job: SpuJob) -> Path:
    candidates = []
    for stem in (job.spu_id, f'{job.spu_id}_{job.representative_sku_id}', job.representative_sku_id):
        for suffix in ('.png', '.jpg', '.jpeg', '.webp'):
            candidates.append(reference_dir / f'{stem}{suffix}')
    match = next((path for path in candidates if path.is_file()), None)
    if not match:
        raise FileNotFoundError(f'SPU {job.spu_id} 缺少参考图。请由 Agent 使用已登录京东页面下载主图到 {reference_dir}，命名为 {job.spu_id}.jpg。')
    return match

def gallery_reference_candidates(reference_dir: Path, job: SpuJob) -> list[Path]:
    pattern = re.compile(f'^{re.escape(job.spu_id)}_gallery_(\\d+)$', re.I)
    candidates = []
    for path in reference_dir.iterdir() if reference_dir.is_dir() else ():
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            continue
        match = pattern.fullmatch(path.stem)
        if match:
            candidates.append((int(match.group(1)), path.name.lower(), path))
    return [item[2] for item in sorted(candidates)]

def is_moderation_error(error: BaseException) -> bool:
    return bool(re.search('moderation|content[_ -]?policy|safety\\s+system|审核|安全策略', str(error), re.I))

def _trusted_jd_image_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (host == '360buyimg.com' or host.endswith('.360buyimg.com'))

def restore_uploaded_white(url: str, output: Path, timeout: float) -> None:
    if not _trusted_jd_image_url(url):
        raise ValueError('已确认白底图不是可信京东图片域名，拒绝下载。')
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    if len(response.content) > 20000000:
        raise ValueError('已确认白底图超过 20MB，拒绝处理。')
    normalize_jpeg(response.content, output, pure_white=True)

def _image_model_for_kind(kind: str, scene_model: str | None=None, image_model: str | None=None) -> str:
    if kind == 'transparent':
        raise ValueError('Transparent is locally derived; no image model may generate it')
    if kind not in {'white', 'scene1', 'scene2', 'selling'}:
        raise ValueError('Unknown image material kind')
    selected = (scene_model if scene_model is not None else IMAGE_MODEL_POOL_ALIAS) if kind in {'scene1', 'scene2'} else (image_model if image_model is not None else IMAGE_MODEL_POOL_ALIAS)
    if not selected: raise ValueError('Image model cannot be empty')
    if kind == 'white' and selected == SCENE_SELLING_EXTRA_MODEL:
        raise ValueError('Oxygen-Product-Pro is scene/selling-only; forbidden for white or transparent')
    return selected

def request_material_image(client, kind, prompt, source, *, model=None):
    selected = _image_model_for_kind(kind, scene_model=model if kind.startswith('scene') else None, image_model=model if not kind.startswith('scene') else None)
    # Real runtime clients enforce slot eligibility inside their shared concurrency context.
    if callable(getattr(type(client), 'edit_material_image', None)):
        return client.edit_material_image(kind, prompt, source, model=selected)
    return client.edit_image(prompt, source, model=selected)

def _request_image_set(client: ModelClient, kinds: Iterable[str], source: Path, title: str | None, scene_model: str | None=None, image_model: str | None=None) -> tuple[dict[str, bytes], dict[str, Exception]]:
    kinds = tuple(kinds)
    results: dict[str, bytes] = {}
    errors: dict[str, Exception] = {}
    if not kinds:
        return (results, errors)
    with ThreadPoolExecutor(max_workers=min(len(kinds), PROVIDER.maximum_image_concurrency)) as image_pool:
        futures = {image_pool.submit(request_material_image, client, kind, image_prompt(kind, title), source, model=_image_model_for_kind(kind, scene_model, image_model)): kind for kind in kinds}
        for future in as_completed(futures):
            kind = futures[future]
            try:
                results[kind] = future.result()
            except Exception as error:
                errors[kind] = error
    fallback = PROVIDER.scene_image_model
    for kind in [name for name in errors if name in {'scene1', 'scene2'}]:
        error = errors[kind]
        if not isinstance(error, (ModelModerationBlocked, ModelUnauthorized)) or not fallback:
            continue
        try:
            results[kind] = request_material_image(client, kind, image_prompt(kind, title), source, model=fallback)
            errors.pop(kind, None)
        except Exception as fallback_error:
            errors[kind] = fallback_error
    return (results, errors)

def _commit_staged_images(results: dict[str, bytes], images: Path, names: dict[str, str], spu_id: str) -> None:
    staging = images.parent / '.state' / 'staging' / spu_id
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for kind, content in results.items():
            normalize_jpeg(content, staging / names[kind], pure_white=kind == 'white')
        for kind in results:
            (staging / names[kind]).replace(images / names[kind])
    finally:
        shutil.rmtree(staging, ignore_errors=True)

def _load_state(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version': 1, 'jobs': {}}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('task state unreadable; preserve the original and recover before running') from error
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), dict):
        raise ValueError('invalid task state; never reset receipts to an empty task')
    return payload

def _save_state(path: Path, state: dict) -> None:
    # Large shops reach tens of MB of state; compact JSON keeps each durable save fast.
    from pop_safety import atomic_json
    atomic_json(path, state, compact=True)

def _load_upload_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('files', {}), dict):
            raise ValueError('invalid upload ledger')
        payload.setdefault('version', 1)
        payload.setdefault('files', {})
        return payload
    except FileNotFoundError:
        return {'version': 1, 'files': {}}

def _save_upload_ledger(path: Path, ledger: dict[str, Any]) -> None:
    from pop_safety import atomic_json
    atomic_json(path, ledger)

def _write_url_export(path: Path, prepared: PreparedSource, state: dict) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '图片空间链接'
    sheet.append(['图片名称', '图片链接'])
    for job in prepared.jobs:
        uploaded = (state.get('jobs', {}).get(job.spu_id, {}) or {}).get('uploaded_urls') or {}
        for kind, name in image_names(job.spu_id).items():
            if uploaded.get(kind):
                sheet.append([name, uploaded[kind]])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path

@measured_stage('upload', 'output_dir')
def upload_generated_materials(client: Any, prepared: PreparedSource, output_dir: str | Path, category_id: int, *, images_dir: str | Path | None=None) -> UploadResult:
    output = Path(output_dir)
    images = Path(images_dir) if images_dir else output / '全部图片'
    state_path = output / '.state' / 'task.json'
    state = _load_state(state_path)
    _bind_state(state, prepared, state_path)
    ledger_path = output / '.state' / 'upload-ledger.json'
    ledger = _load_upload_ledger(ledger_path)
    uploaded_count = 0
    reused_count = 0
    failures: list[str] = []
    export_path = output / '图片空间链接.xlsx'
    for job in prepared.jobs:
        state_item = state['jobs'].setdefault(job.spu_id, {})
        uploaded_urls = dict(state_item.get('uploaded_urls') or {})
        required = set(_model_kinds(job))
        if job.needs_transparent:
            required.add('transparent')
        names = image_names(job.spu_id)
        for kind in IMAGE_SUFFIXES:
            if kind not in required:
                continue
            path = images / names[kind]
            entry = ledger['files'].get(path.name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ''
            if entry and digest and (entry.get('sha256') != digest):
                raise ValueError(f'uploaded filename content changed: {path.name}')
            if entry and entry.get('status') in {'intent', 'unknown'}:
                raise JdoWriteUncertainError(f'upload receipt unresolved: {path.name}; reconcile before resuming')
            if entry and entry.get('status') == 'rejected':
                failures.append(f'{path.name}: previously rejected; not retried')
                continue
            if uploaded_urls.get(kind):
                reused_count += 1
                continue
            if entry and entry.get('url'):
                uploaded_urls[kind] = entry['url']
                state_item['uploaded_urls'] = uploaded_urls
                _save_state(state_path, state)
                reused_count += 1
                continue
            if not valid_material_image(path, kind):
                failures.append(f'{path.name}: local image is missing or invalid')
                continue
            entry = {'sha256': digest, 'kind': kind, 'categoryId': int(category_id), 'status': 'intent', 'submittedAt': int(time.time())}
            ledger['files'][path.name] = entry
            _save_upload_ledger(ledger_path, ledger)
            try:
                response = client.upload_image(path, int(category_id))
            except JdoPermissionError:
                entry['status'] = 'rejected'
                state_item['uploaded_urls'] = uploaded_urls
                _save_state(state_path, state)
                _save_upload_ledger(ledger_path, ledger)
                _write_url_export(export_path, prepared, state)
                return UploadResult(uploaded_count, reused_count, len(failures), True, export_path, tuple(failures))
            except (JdoUnavailableError, JdoWriteUncertainError) as error:
                entry['status'] = 'unknown'
                _save_upload_ledger(ledger_path, ledger)
                raise JdoWriteUncertainError(f'upload result unknown: {path.name}') from None
            except JdoError:
                entry['status'] = 'rejected'
                _save_upload_ledger(ledger_path, ledger)
                failures.append(f'{path.name}: official request rejected')
                continue
            except Exception as error:
                entry['status'] = 'unknown'
                _save_upload_ledger(ledger_path, ledger)
                raise JdoWriteUncertainError(f'upload result unknown: {path.name}') from None
            returned_name = cell_text(response.get('imgName'))
            if returned_name and returned_name != path.name:
                raise JdoWriteUncertainError(f'{path.name}: returned filename mismatch; do not replay')
            url = _jd_image_url(response.get('imgUrl'))
            if not url:
                raise JdoWriteUncertainError(f'{path.name}: missing upload URL; do not replay')
            entry.update({'status': 'accepted', 'url': url})
            uploaded_urls[kind] = url
            state_item['uploaded_urls'] = uploaded_urls
            _save_upload_ledger(ledger_path, ledger)
            _save_state(state_path, state)
            uploaded_count += 1
    _write_url_export(export_path, prepared, state)
    return UploadResult(uploaded_count, reused_count, len(failures), False, export_path, tuple(failures))

def _business_mode(prepared: PreparedSource) -> str:
    if VARIANT_ID == 'merchant':
        return 'merchant'
    return 'self-operated' if prepared.source_type in {'self-operated', 'self-operated-live'} else 'pop'

def _task_signature(prepared: PreparedSource) -> str:
    payload = {'source_type': prepared.source_type, 'jobs': [{'spu_id': job.spu_id, 'skus': list(job.skus), 'short_title_sku_ids': list(job.short_title_sku_ids), 'needs_selling_points': job.needs_selling_points, 'needs_white': job.needs_white, 'needs_scenes': job.needs_scenes, 'needs_selling_image': job.needs_selling_image, 'needs_transparent': job.needs_transparent} for job in prepared.jobs]}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

def _prepared_payload(prepared: PreparedSource) -> dict[str, Any]:
    return {'sourceType': prepared.source_type, 'sheetName': prepared.sheet_name, 'headers': list(prepared.headers), 'rows': [asdict(row) for row in prepared.rows], 'jobs': [asdict(job) for job in prepared.jobs], 'originalRows': prepared.original_rows, 'filteredRows': prepared.filtered_rows, 'duplicateRows': prepared.duplicate_rows}

def _prepared_from_payload(payload: dict[str, Any]) -> PreparedSource:
    rows = tuple((SourceRow(sku_id=cell_text(item.get('sku_id')), title=cell_text(item.get('title')), spu_id=cell_text(item.get('spu_id')), score=cell_text(item.get('score')), raw=tuple(item.get('raw') or ()), source_path=cell_text(item.get('source_path')), sheet_name=cell_text(item.get('sheet_name')), row_number=int(item.get('row_number') or 0), header_row=int(item.get('header_row') or 1)) for item in payload.get('rows') or []))
    jobs = tuple((SpuJob(spu_id=cell_text(item.get('spu_id')), representative_sku_id=cell_text(item.get('representative_sku_id')), title=cell_text(item.get('title')), sku_ids=tuple((cell_text(value) for value in item.get('sku_ids') or ())), skus=tuple(((cell_text(pair[0]), cell_text(pair[1])) for pair in item.get('skus') or ())), short_title_sku_ids=tuple((cell_text(value) for value in item.get('short_title_sku_ids') or ())), needs_selling_points=bool(item.get('needs_selling_points')), needs_white=bool(item.get('needs_white')), needs_scenes=bool(item.get('needs_scenes')), needs_selling_image=bool(item.get('needs_selling_image')), needs_transparent=bool(item.get('needs_transparent', True))) for item in payload.get('jobs') or []))
    return PreparedSource(source_type=cell_text(payload.get('sourceType')), sheet_name=cell_text(payload.get('sheetName')), headers=tuple(payload.get('headers') or ()), rows=rows, jobs=jobs, original_rows=int(payload.get('originalRows') or 0), filtered_rows=int(payload.get('filteredRows') or 0), duplicate_rows=int(payload.get('duplicateRows') or 0))

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _shop_identity(seller: dict[str, Any]) -> dict[str, str]:
    if seller.get('isPop') is False or seller.get('active') is False:
        raise ValueError('current shop must be an active POP shop')
    identity = {'shopId': cell_text(seller.get('shopId')), 'shopName': cell_text(seller.get('shopName')), 'venderId': cell_text(seller.get('venderId'))}
    if not all(identity.values()):
        raise ValueError('无法确认当前店铺的 shopId、shopName 和 venderId，禁止创建或复用自动维护计划')
    return identity

def _auto_maintain_plan_hash(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != 'planHash'}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

def write_pop_auto_maintain_plan(prepared: PreparedSource, reference_urls: dict[str, str], existing_materials: dict[str, dict[str, Any]], seller: dict[str, Any], output_dir: str | Path, source_path: str | Path, *, target_spu_id: str | None, now: int | None=None) -> Path:
    output = Path(output_dir).resolve()
    source = Path(source_path).resolve()
    created_at = int(time.time() if now is None else now)
    payload = {'formatVersion': 1, 'skillVersion': SKILL_VERSION, 'businessMode': 'pop', 'outputDir': str(output), 'shopIdentity': _shop_identity(seller), 'targetSpuId': cell_text(target_spu_id), 'createdAt': created_at, 'taskSignature': _task_signature(prepared), 'sourceWorkbook': {'path': str(source), 'sha256': _file_sha256(source)}, 'counts': {'spus': len(prepared.jobs), 'skus': len(prepared.rows)}, 'prepared': _prepared_payload(prepared), 'referenceUrls': reference_urls, 'existingMaterials': existing_materials}
    payload['planHash'] = _auto_maintain_plan_hash(payload)
    plan_path = output / AUTO_MAINTAIN_PLAN_NAME
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = plan_path.with_suffix(plan_path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(plan_path)
    return plan_path

def load_pop_auto_maintain_plan(output_dir: str | Path, seller: dict[str, Any], target_spu_id: str | None, *, now: int | None=None, expected_output_dir: str | Path | None=None) -> tuple[PreparedSource, dict[str, str], dict[str, dict[str, Any]], Path]:
    output = Path(output_dir).resolve()
    plan_path = output / AUTO_MAINTAIN_PLAN_NAME
    if not plan_path.is_file():
        raise ValueError('自动维护计划不存在，请先运行 plan-auto-maintain')
    try:
        payload = json.loads(plan_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('自动维护计划无法读取，请重新运行 plan-auto-maintain') from error
    if payload.get('planHash') != _auto_maintain_plan_hash(payload):
        raise ValueError('自动维护计划校验失败，请重新运行 plan-auto-maintain')
    if payload.get('formatVersion') != 1:
        raise ValueError('自动维护计划版本不匹配，请重新运行 plan-auto-maintain')
    expected_output = Path(expected_output_dir or output).resolve()
    if os.path.normcase(cell_text(payload.get('outputDir'))) != os.path.normcase(str(expected_output)):
        raise ValueError('自动维护计划的输出目录不匹配，请重新运行 plan-auto-maintain')
    if payload.get('businessMode') != 'pop':
        raise ValueError('自动维护计划不是 POP 模式，请重新运行 plan-auto-maintain')
    if payload.get('shopIdentity') != _shop_identity(seller):
        raise ValueError('自动维护计划与当前店铺不匹配，请重新运行 plan-auto-maintain')
    if cell_text(payload.get('targetSpuId')) and cell_text(payload.get('targetSpuId')) != cell_text(target_spu_id):
        raise ValueError('自动维护计划的目标 SPU 不匹配，请重新运行 plan-auto-maintain')
    prepared = _prepared_from_payload(payload.get('prepared') or {})
    if payload.get('taskSignature') != _task_signature(prepared):
        raise ValueError('自动维护计划的任务签名不匹配，请重新运行 plan-auto-maintain')
    source_info = payload.get('sourceWorkbook') or {}
    source_path = Path(cell_text(source_info.get('path'))).resolve()
    if source_path.parent != output:
        raise ValueError('自动维护计划的源表不在目标输出目录，请重新运行 plan-auto-maintain')
    if not source_path.is_file() or _file_sha256(source_path) != source_info.get('sha256'):
        raise ValueError('自动维护计划的源表已变化，请重新运行 plan-auto-maintain')
    references = {cell_text(key): cell_text(value) for key, value in (payload.get('referenceUrls') or {}).items()}
    existing = {cell_text(key): value for key, value in (payload.get('existingMaterials') or {}).items()}
    if cell_text(target_spu_id):
        if cell_text(target_spu_id) not in {job.spu_id for job in prepared.jobs}:
            raise ValueError('目标 SPU 不在冻结计划内，禁止扩大范围')
        prepared, references, existing = _scope_pop_discovery(prepared, references, existing, target_spu_id)
    return (prepared, references, existing, source_path)

def _bind_state(state: dict, prepared: PreparedSource, state_path: Path) -> None:
    mode = _business_mode(prepared)
    signature = _task_signature(prepared)
    allowed_signatures={signature,_task_signature(route_jingmai_batch_images(prepared,model_cutout_images=False)[0])}
    allowed_jobs={job.spu_id for job in prepared.jobs}
    if state_path.parent.parent.name.startswith('批次'):
        plan_path=state_path.parent.parent.parent/AUTO_MAINTAIN_PLAN_NAME
        if plan_path.is_file():
            try:
                frozen=json.loads(plan_path.read_text(encoding='utf-8'))
                full,_,_,_=load_pop_auto_maintain_plan(state_path.parent.parent.parent,frozen.get('shopIdentity') or {},frozen.get('targetSpuId'))
                batch_number=int(state_path.parent.parent.name.removeprefix('批次'))
                groups=split_rows_by_spu(full.rows)
                current_spus={job.spu_id for job in prepared.jobs}
                if (frozen.get('planHash')==_auto_maintain_plan_hash(frozen) and 1<=batch_number<=len(groups) and current_spus.issubset({row.spu_id for row in groups[batch_number-1]})):
                    batch_prepared=_subset_prepared(full,groups[batch_number-1])
                    signature=_task_signature(batch_prepared)
                    allowed_jobs={job.spu_id for job in batch_prepared.jobs}
                    allowed_signatures={signature,_task_signature(route_jingmai_batch_images(batch_prepared,model_cutout_images=False)[0])}
            except (OSError,ValueError,KeyError,json.JSONDecodeError):pass
    existing_jobs = set((state.get('jobs') or {}).keys())
    current_jobs = {job.spu_id for job in prepared.jobs}
    existing_variant = state.get('variant')
    existing_mode = state.get('business_mode')
    existing_signature = state.get('task_signature')
    # The full batch's own signature is the normal state; a smaller approved subset may also be nested.
    nested_batch = state_path.parent.parent.name.startswith('批次') and (state_path.parent.parent.parent/AUTO_MAINTAIN_PLAN_NAME).is_file()
    if existing_signature and existing_signature not in allowed_signatures:
        raise ValueError('输出目录属于另一份底表任务，禁止复用其状态。请选择新的输出目录。')
    if existing_jobs and not existing_jobs.issubset(allowed_jobs):
        raise ValueError('旧任务含当前范围外商品；只有同一冻结批次子集可以保留原回执。')
    state['version'] = 2
    state['variant'] = VARIANT_ID
    state['business_mode'] = mode
    state['task_signature'] = signature
    state.setdefault('jobs', {})
    for job in prepared.jobs:
        state['jobs'].setdefault(job.spu_id, {})['sku_ids'] = list(job.sku_ids)
    _save_state(state_path, state)

@measured_stage('binding-preflight-readback', 'output_dir')
def prepare_material_binding_plan(client: Any, prepared: PreparedSource, output_dir: str | Path, *, excluded_bindings: frozenset[tuple[str, int]]=frozenset()) -> MaterialBindingPlan:
    output = Path(output_dir)
    state_path = output / '.state' / 'task.json'
    state = _load_state(state_path)
    _bind_state(state, prepared, state_path)
    material_jobs = [job for job in prepared.jobs if _has_material_work(job)]
    sku_ids = [sku_id for job in material_jobs for sku_id in job.sku_ids]
    materials_by_sku = _query_binding_materials(client, sku_ids) if sku_ids else {}
    requests: list[dict[str, Any]] = []
    authorization_requests: list[dict[str, Any]] = []
    preflight_failures: list[dict[str, str]] = []
    for job in material_jobs:
        state_item = state['jobs'].setdefault(job.spu_id, {})
        binding_state = state_item.setdefault('material_bindings', {})
        try:
            binding_job=job
            if job.needs_selling_points:
                try:binding_selling_points(job.spu_id,state_item.get('selling_points') or [],state_item)
                except ValueError as error:
                    previous_text=(binding_state.get('1002') or {}).get('status')
                    if previous_text in ('intent','unknown','submitted'):raise JdoWriteUncertainError('原卖点提交须先核对，未覆盖回执')
                    preflight_failures.append({'spuId':job.spu_id,'materialType':1002,'reason':str(error)})
                    state_item['selling_point_issue']={'status':'blocked-local','reason':str(error)}
                    binding_job=replace(job,needs_selling_points=False)
            desired = build_material_binding_requests(binding_job, state_item)
            from pop_safety import missing_only_requests
            fresh = []
            for request in desired:
                saved = binding_state.get(str(request['materialType'])) or {}
                if (job.spu_id, int(request['materialType'])) in excluded_bindings:
                    fresh.append(request)
                elif saved.get('status') == 'failed' and saved.get('fingerprint') != request['fingerprint']:
                    fresh.extend(missing_only_requests([request], materials_by_sku))
                elif saved.get('status') not in {None, 'planned', 'mismatch'}:
                    from pop_safety import receipt_request
                    original_request = receipt_request(job.spu_id, request['materialType'], saved)
                    if not original_request:
                        raise JdoWriteUncertainError('Original binding request unavailable; reconcile before replay')
                    fresh.append(original_request)
                else:
                    fresh.extend(missing_only_requests([request], materials_by_sku))
            desired = fresh
        except Exception as error:
            if any(item.get('status') not in {None, 'planned', 'mismatch', 'rejected'} for key, item in binding_state.items() if key != 'preflight'):
                raise JdoWriteUncertainError('original binding inputs missing; preserve receipts and reconcile before generation') from None
            preflight_failures.append({'spuId': job.spu_id, 'reason': str(error)})
            binding_state['preflight'] = {'status': 'failed', 'reason': str(error), 'updatedAt': int(time.time())}
            continue
        binding_state.pop('preflight', None)
        authorization_requests.extend((request for request in desired if (job.spu_id, int(request['materialType'])) not in excluded_bindings))
        for request in desired:
            key = str(request['materialType'])
            previous = binding_state.get(key) or {}
            if (job.spu_id, int(request['materialType'])) in excluded_bindings:
                if previous.get('status') not in {None, 'excluded-appeal'}:
                    raise ValueError(f"SPU {job.spu_id} type {key} 已有执行回执，不能用 --exclude-binding 覆盖，请先对账")
                binding_state[key] = {'status': 'excluded-appeal', 'reason': '人工申诉接管，本槽不重绑', 'updatedAt': int(time.time())}
                continue
            has_receipt = previous.get('status') not in {None, 'planned', 'mismatch'}
            if has_receipt and previous.get('status') == 'failed' and previous.get('fingerprint') != request['fingerprint']:
                # A definite platform failure is not an unknown write: a new image means a new request.
                has_receipt = False
                previous = {**previous, 'status': 'planned'}
                binding_state[key] = previous
            if has_receipt and previous.get('fingerprint') != request['fingerprint']:
                raise JdoWriteUncertainError('binding fingerprint changed; preserve and reconcile the original request')
            status, reason = _evaluate_binding_request(request, materials_by_sku)
            current = {**previous, 'request': request, 'fingerprint': request['fingerprint'], 'status': status, 'reason': reason, 'updatedAt': int(time.time())}
            if status in {'approved', 'pending'}:
                if previous.get('status') in {'intent', 'unknown', 'submitted', 'failed'}:
                    current['reconciliation'] = {'previousStatus': previous['status'], 'previousReason': previous.get('reason'), 'verifiedAt': int(time.time())}
                binding_state[key] = current
                continue
            if previous.get('status') == 'rejected':
                continue
            if has_receipt:
                if status == 'failed':
                    binding_state[key] = {**current, 'status': 'rejected'}
                    continue
                raise JdoWriteUncertainError(f'SPU {job.spu_id} type {key}: exact readback unresolved; do not replay')
            binding_state[key] = {**current, 'status': 'planned'}
            requests.append(request)
    _save_state(state_path, state)
    targets = []
    for job in prepared.jobs:
        material_types = sorted({int(request['materialType']) for request in requests if request['spuId'] == job.spu_id})
        if material_types:
            targets.append({'spuId': job.spu_id, 'skuCount': job.sku_count, 'materialTypes': material_types, 'overwrite': True})
    return MaterialBindingPlan(prepared, output, tuple(requests), tuple(authorization_requests), tuple(targets), tuple(preflight_failures))

def _write_binding_workbook(path: Path, title: str, jobs: Iterable[SpuJob], reasons: dict[str, str]) -> Path | None:
    selected = list(jobs)
    if not selected:
        path.unlink(missing_ok=True)
        return None
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(['SPUID', '代表SKUID', 'SKU数量', '状态说明'])
    for job in selected:
        sheet.append([job.spu_id, job.representative_sku_id, job.sku_count, reasons.get(job.spu_id, '')])
    detail = workbook.create_sheet('SKU明细')
    detail.append(['SPUID', 'SKUID', '商品名称'])
    for job in selected:
        for sku_id, product_title in job.skus:
            detail.append([job.spu_id, sku_id, product_title])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path

@measured_stage('binding-and-readback', 'plan')
def execute_material_binding_plan(client: Any, plan: MaterialBindingPlan) -> MaterialBindingResult:
    state_path = plan.output_dir / '.state' / 'task.json'
    state = _load_state(state_path)
    _bind_state(state, plan.prepared, state_path)
    request_errors: dict[tuple[str, int], str] = {}
    requests_by_spu: dict[str, list[dict[str, Any]]] = {}
    for request in plan.authorization_requests:
        requests_by_spu.setdefault(request['spuId'], []).append(request)
    browser_required = False
    submitted = 0
    for request in plan.requests:
        spu_id = request['spuId']
        material_type = int(request['materialType'])
        binding_state = state['jobs'].setdefault(spu_id, {}).setdefault('material_bindings', {})
        previous = binding_state.get(str(material_type)) or {}
        digest = hashlib.sha256(json.dumps(request['body'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        if digest != request['fingerprint'] or previous.get('fingerprint') not in {None, digest}:
            raise JdoWriteUncertainError('binding request changed after planning')
        if previous.get('status') not in {None, 'planned'}:
            raise JdoWriteUncertainError('stale binding plan; reconcile receipts before execution')
        record = {'request': request, 'fingerprint': digest, 'status': 'intent', 'chunks': [], 'updatedAt': int(time.time())}
        binding_state[str(material_type)] = record
        try:
            for group in _chunks(request['body']['skuMaterials'], 50):
                chunk = {'body': {**request['body'], 'skuMaterials': list(group)}, 'status': 'intent'}
                record['chunks'].append(chunk)
                _save_state(state_path, state)
                receipt = client.bind_sku_materials(chunk['body'])
                chunk.update({'status': 'accepted', 'receipt': receipt})
                _save_state(state_path, state)
            record.update({'status': 'submitted', 'reason': 'submitted'})
            submitted += 1
            print(json.dumps({'event':'binding-submitted','spuId':spu_id,'materialType':material_type,'skuCount':len(request['body']['skuMaterials']),'submittedTypeCount':submitted,'message':'本类型绑定已受理；尚待平台回读和审核。'},ensure_ascii=False),flush=True)
        except JdoPermissionError as error:
            record.update({'status': 'rejected', 'reason': 'official permission denied'})
            browser_required = True
            for remaining in plan.requests:
                key = (remaining['spuId'], int(remaining['materialType']))
                request_errors[key] = 'official permission denied'
            break
        except (JdoUnavailableError, JdoWriteUncertainError):
            record.update({'status': 'unknown', 'reason': 'transport result unknown'})
            raise JdoWriteUncertainError('binding result unknown; stop and reconcile exact request') from None
        except JdoError:
            request_errors[spu_id, material_type] = 'official request rejected'
            record.update({'status': 'rejected', 'reason': 'official request rejected'})
        except Exception as error:
            record.update({'status': 'unknown', 'reason': 'transport result unknown'})
            raise JdoWriteUncertainError('binding result unknown; stop and reconcile exact request') from None
        finally:
            _save_state(state_path, state)
    materials_by_sku = {}
    print(json.dumps({'event':'binding-readback','submittedTypeCount':submitted,'message':'正在核对原绑定回执；不重提已受理的请求。'},ensure_ascii=False),flush=True)
    if not browser_required:
        sku_ids = [sku_id for job in plan.prepared.jobs for sku_id in job.sku_ids if job.spu_id in requests_by_spu]
        try:
            materials_by_sku = _query_binding_materials(client, sku_ids) if sku_ids else {}
        except Exception as error:
            raise JdoWriteUncertainError('binding readback unavailable; preserved receipts must be reconciled') from None
    for request in plan.authorization_requests:
        spu_id = request['spuId']
        material_type = int(request['materialType'])
        key = (spu_id, material_type)
        binding_state = state['jobs'].setdefault(spu_id, {}).setdefault('material_bindings', {})
        previous = binding_state.get(str(material_type)) or {}
        if key in request_errors:
            status, reason = ('rejected', request_errors[key])
        elif previous.get('status') == 'rejected':
            status, reason = ('rejected', previous.get('reason', 'official request rejected'))
        elif materials_by_sku:
            status, reason = _evaluate_binding_request(request, materials_by_sku)
            if status == 'mismatch':
                raise JdoWriteUncertainError('binding readback does not yet match; do not replay accepted writes')
            if status == 'failed':
                status = 'rejected'
        else:
            current = binding_state.get(str(material_type)) or {}
            status, reason = (current.get('status', 'failed'), current.get('reason', 'verification unavailable'))
        binding_state[str(material_type)] = {**previous, 'fingerprint': request['fingerprint'], 'status': status, 'reason': reason, 'updatedAt': int(time.time())}
    _save_state(state_path, state)
    approved_jobs = []
    pending_jobs = []
    failed_jobs = []
    reasons: dict[str, str] = {item['spuId']: item['reason'] for item in plan.preflight_failures}
    for job in plan.prepared.jobs:
        bindings = state['jobs'].setdefault(job.spu_id, {}).get('material_bindings') or {}
        statuses = [bindings.get(str(item['materialType']), {}) for item in requests_by_spu.get(job.spu_id, [])]
        if not statuses and job.spu_id not in reasons:
            continue
        if job.spu_id in reasons or any((item.get('status') in {'failed', 'rejected'} for item in statuses)):
            failed_jobs.append(job)
            details = [item.get('reason') for item in statuses if item.get('status') in {'failed', 'rejected'}]
            reasons[job.spu_id] = reasons.get(job.spu_id) or '；'.join(dict.fromkeys(filter(None, details))) or 'binding failed'
        elif any((item.get('status') in {'pending', 'submitted'} for item in statuses)):
            pending_jobs.append(job)
            reasons[job.spu_id] = 'waiting for audit status 4'
        elif all((item.get('status') == 'approved' for item in statuses)):
            approved_jobs.append(job)
            reasons[job.spu_id] = 'all planned materials approved'
        else:
            failed_jobs.append(job)
            reasons[job.spu_id] = 'binding state is incomplete'
    success_path = _write_binding_workbook(plan.output_dir / '素材绑定成功清单.xlsx', '绑定成功SPU', approved_jobs, reasons)
    pending_path = _write_binding_workbook(plan.output_dir / '素材绑定审核中清单.xlsx', '审核中SPU', pending_jobs, reasons)
    failure_path = _write_binding_workbook(plan.output_dir / '素材绑定失败SPU清单.xlsx', '绑定失败SPU', failed_jobs, reasons)
    failures = tuple((f'SPU {job.spu_id}: {reasons[job.spu_id]}' for job in failed_jobs))
    return MaterialBindingResult(submitted, len(approved_jobs), len(pending_jobs), len(failed_jobs), browser_required, False, None, success_path, pending_path, failure_path, failures)

def _model_kinds(job: SpuJob) -> list[str]:
    kinds = []
    if job.needs_white:
        kinds.append('white')
    if job.needs_scenes:
        kinds.extend(('scene1', 'scene2'))
    if job.needs_selling_image:
        kinds.append('selling')
    return kinds

def _has_material_work(job: SpuJob) -> bool:
    return job.needs_selling_points or job.needs_transparent or bool(_model_kinds(job))

def _material_is_complete(job: SpuJob, item: dict, images: Path) -> bool:
    if job.needs_selling_points:
        try:
            binding_selling_points(job.spu_id,item.get('selling_points') or [],item)
        except ValueError:
            return False
    names = image_names(job.spu_id)
    required = _model_kinds(job)
    if job.needs_transparent:
        required.append('transparent')
    uploaded = item.get('uploaded_urls') or {}
    return all((valid_material_image(images / names[kind], kind) or bool(uploaded.get(kind)) for kind in required))

def _short_titles_are_complete(job: SpuJob, item: dict) -> bool:
    values = item.get('short_titles') or {}
    return all((valid_short_title(values.get(sku_id)) for sku_id in job.short_title_sku_ids))

def load_agent_text(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:raise ValueError('Agent 文案 JSON 存在重复字段/SKU：' + str(key))
            result[key] = value
        return result
    try:
        payload = json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=unique_fields)
    except json.JSONDecodeError as error:
        raise ValueError(f'Agent 文案文件不是有效 JSON：{error}') from None
    if not isinstance(payload, dict):
        raise ValueError('Agent 文案文件必须是 JSON 对象。')
    points_payload = payload.get('sellingPoints') or {}
    titles_payload = payload.get('shortTitles') or {}
    if not isinstance(points_payload, dict) or not isinstance(titles_payload, dict):
        raise ValueError('Agent 文案文件中 sellingPoints 和 shortTitles 必须是对象。')
    points = {str(key): value for key, value in points_payload.items()}
    titles = {str(key): value for key, value in titles_payload.items()}
    if not points and not titles:
        raise ValueError('Agent 文案文件为空。')
    return {'selling_points': points, 'short_titles': titles}

def _validate_agent_text_scope(agent_text: dict[str, Any], prepared: PreparedSource) -> dict[str, Any]:
    known_spus = {job.spu_id for job in prepared.jobs}
    all_skus = {sku_id for job in prepared.jobs for sku_id in job.sku_ids}
    needed_skus = {sku_id for job in prepared.jobs for sku_id in job.short_title_sku_ids}
    unknown_spus = sorted(set(agent_text['selling_points']) - known_spus)
    unknown_skus = sorted(set(agent_text['short_titles']) - all_skus)
    missing_skus = sorted(needed_skus - set(agent_text['short_titles']))
    if unknown_spus or unknown_skus:
        raise ValueError(f'Agent 文案冻结计划范围差集：多余SPU {unknown_spus}，多余SKU {unknown_skus}；待补SKU {missing_skus}。')
    # Host may send the frozen inventory's already-qualified titles; ignore, never overwrite them.
    return {**agent_text, 'short_titles': {key: value for key, value in agent_text['short_titles'].items() if key in needed_skus}}

def load_scoped_agent_text(path, prepared, output, seller):
    """Project only an owned full-task file through the verified original frozen plan."""
    text=load_agent_text(path)
    output=Path(output).resolve();source=Path(path).resolve()
    # External input remains a strict current-scope input; it cannot silently become a full-task file.
    if not source.is_relative_to(output):return _validate_agent_text_scope(text,prepared)
    from heideng_merchant.safety import safe_join
    safe_join(output,source.relative_to(output).as_posix())
    frozen=json.loads((output/AUTO_MAINTAIN_PLAN_NAME).read_text(encoding='utf-8'))
    full,_,_,_=load_pop_auto_maintain_plan(output,seller,frozen.get('targetSpuId'))
    if not {j.spu_id for j in prepared.jobs}.issubset({j.spu_id for j in full.jobs}):
        raise ValueError('当前文案目标不属于原冻结任务，未投影。')
    validated=_validate_agent_text_scope(text,full)  # Reject all full-plan outliers before selecting a subset.
    return _validate_agent_text_scope(_batch_agent_text(validated,prepared),prepared)


def _batch_agent_text(agent_text: dict[str, Any] | None, batch: PreparedSource) -> dict[str, Any] | None:
    if not agent_text:
        return None
    spus = {job.spu_id for job in batch.jobs}
    skus = {sku_id for job in batch.jobs for sku_id in job.short_title_sku_ids}
    return {
        'selling_points': {key: value for key, value in agent_text['selling_points'].items() if key in spus},
        'short_titles': {key: value for key, value in agent_text['short_titles'].items() if key in skus},
    }

def _seed_agent_text(prepared: PreparedSource, state: dict, agent_text: dict[str, Any]) -> None:
    known_spus = {job.spu_id for job in prepared.jobs}
    known_skus = {sku_id for job in prepared.jobs for sku_id in job.short_title_sku_ids}
    unknown_spus = sorted(set(agent_text['selling_points']) - known_spus)
    unknown_skus = sorted(set(agent_text['short_titles']) - known_skus)
    if unknown_spus or unknown_skus:
        raise ValueError(f'Agent 文案包含冻结计划外的 SPU/SKU：SPU {unknown_spus}，SKU {unknown_skus}。')
    for job in prepared.jobs:
        item = state['jobs'].setdefault(job.spu_id, {})
        if job.needs_selling_points and not item.get('selling_points'):
            raw_points = agent_text['selling_points'].get(job.spu_id)
            if raw_points is not None:
                item['selling_points'] = validate_selling_points(raw_points)
        titles = dict(item.get('short_titles') or {})
        for sku_id in job.short_title_sku_ids:
            if valid_short_title(titles.get(sku_id)):
                continue
            value = agent_text['short_titles'].get(sku_id)
            if value is None:
                continue
            if not valid_short_title(value):
                raise ValueError(f'Agent 短标题不符合 16-30 加权长度规则（SPU {job.spu_id} / SKU {sku_id}）：{cell_text(value)}')
            titles[sku_id] = cell_text(value)
        if titles:
            item['short_titles'] = titles

def _write_results(prepared: PreparedSource, output: Path, state: dict, failures: list[tuple[SpuJob, str]]) -> BatchResult:
    output.mkdir(parents=True, exist_ok=True)
    images = output / '全部图片'
    reported_failures: dict[str, list[str]] = {}
    for job, reason in failures:
        reported_failures.setdefault(job.spu_id, []).append(cell_text(reason) or '处理失败。')
    completed = []
    material_successes = []
    incomplete: list[tuple[SpuJob, str]] = []
    for job in prepared.jobs:
        item = state.get('jobs', {}).get(job.spu_id, {})
        material_complete = not _has_material_work(job) or _material_is_complete(job, item, images)
        short_complete = _short_titles_are_complete(job, item)
        reasons = list(reported_failures.get(job.spu_id, []))
        if not material_complete:
            reasons.append('计划素材未全部完成。')
        if not short_complete:
            reasons.append('计划短标题未全部完成。')
        if _has_material_work(job) and material_complete:
            material_successes.append(job)
        if material_complete and short_complete and (not reasons):
            completed.append(job)
        else:
            incomplete.append((job, '；'.join(dict.fromkeys(reasons))))
    manifest_path = output / '素材生成清单.xlsx' if material_successes else None
    short_title_path = output / '商品导入短标题模板_已回填.xlsx'
    failure_path = output / '失败SPU清单.xlsx' if incomplete else None
    if manifest_path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '素材生成清单'
        sheet.append(['SPUID', '代表SKUID', 'SKU数量', '代表商品名称', '卖点1', '卖点2', '卖点3', '白底图', '透明图', '场景图1', '场景图2', '卖点图', '需要卖点', '需要白底图', '需要场景图', '需要卖点图'])
        for job in material_successes:
            item = state['jobs'].get(job.spu_id, {})
            points = item.get('selling_points') if job.needs_selling_points else ['', '', '']
            names = image_names(job.spu_id)
            sheet.append([job.spu_id, job.representative_sku_id, job.sku_count, job.title, *points, names['white'] if job.needs_white else '', names['transparent'] if (job.needs_white and job.needs_transparent) else '', names['scene1'] if job.needs_scenes else '', names['scene2'] if job.needs_scenes else '', names['selling'] if job.needs_selling_image else '', int(job.needs_selling_points), int(job.needs_white), int(job.needs_scenes), int(job.needs_selling_image)])
        detail = workbook.create_sheet('SKU明细')
        detail.append(['SPUID', 'SKUID', '商品名称'])
        for job in material_successes:
            for sku_id, title in job.skus:
                detail.append([job.spu_id, sku_id, title])
        workbook.save(manifest_path)
        workbook.close()
    else:
        (output / '素材生成清单.xlsx').unlink(missing_ok=True)
    short_rows = []
    for job in prepared.jobs:
        values = state['jobs'].get(job.spu_id, {}).get('short_titles', {})
        for sku_id in job.short_title_sku_ids:
            if valid_short_title(values.get(sku_id)):
                short_rows.append((sku_id, values[sku_id]))
    if short_rows:
        template_path = Path(__file__).resolve().parents[1] / 'assets' / '商品导入短标题模板.xlsx'
        if not template_path.is_file():
            raise FileNotFoundError(f'内置短标题模板不存在：{template_path}')
        shutil.copyfile(template_path, short_title_path)
        workbook = load_workbook(short_title_path)
        if workbook.sheetnames != ['Sheet1']:
            workbook.close()
            raise ValueError('内置短标题模板缺少 Sheet1 工作表。')
        sheet = workbook['Sheet1']
        if sheet.max_row > 2:
            sheet.delete_rows(3, sheet.max_row - 2)
        for row in short_rows:
            sheet.append(row)
        workbook.save(short_title_path)
        workbook.close()
    else:
        short_title_path = None
        (output / '商品导入短标题模板_已回填.xlsx').unlink(missing_ok=True)
    if failure_path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '失败SPU'
        sheet.append(['SPUID', 'SKUID', '商品名称', '失败原因'])
        for job, reason in incomplete:
            for sku_id, title in job.skus:
                sheet.append([job.spu_id, sku_id, title, reason])
        workbook.save(failure_path)
        workbook.close()
    else:
        (output / '失败SPU清单.xlsx').unlink(missing_ok=True)
    return BatchResult(len(prepared.jobs), len(completed), len(incomplete), output, manifest_path, short_title_path, failure_path)

@measured_stage('generation', 'output_dir')
def generate_batch(prepared: PreparedSource, reference_dir: str | Path, output_dir: str | Path, *, spu_concurrency: int=5, image_concurrency: int | None=None, timeout: float=600.0, existing_url_exports: Iterable[str | Path]=(), existing_materials: dict[str, dict[str, Any]] | None=None, agent_text: dict[str, Any] | None=None, scene_image_model: str | None=None, image_model: str | None=None, text_model: str | None=None, model_client_factory=None, joyagent_adapter=None) -> BatchResult:
    if not 1 <= spu_concurrency <= MAX_SPU_CONCURRENCY:
        raise ValueError('SPU 并发必须为 1-50。')
    if text_model == 'agent':text_model = None
    _image_model_for_kind('scene1', scene_image_model, image_model)
    output = Path(output_dir)
    images = output / '全部图片'
    state_path = output / '.state' / 'task.json'
    images.mkdir(parents=True, exist_ok=True)
    reference_dir = Path(reference_dir)
    state = _load_state(state_path)
    _bind_state(state, prepared, state_path)
    for job in prepared.jobs:
        seed = (existing_materials or {}).get(job.spu_id) or {}
        if not seed:
            continue
        item = state['jobs'].setdefault(job.spu_id, {})
        uploaded = dict(item.get('uploaded_urls') or {})
        for kind, url in (seed.get('uploaded_urls') or {}).items():
            uploaded.setdefault(kind, url)
        if uploaded:
            item['uploaded_urls'] = uploaded
        if job.needs_selling_points and (not item.get('selling_points')):
            points = seed.get('selling_points') or []
            if len(points) == 3:
                item['selling_points'] = list(points)
        if seed.get('selling_points_origin') and item.get('selling_points')==seed.get('selling_points'):
            item['selling_points_origin']=dict(seed['selling_points_origin'])
    _save_state(state_path, state)
    if existing_url_exports:
        existing_urls = load_url_exports(existing_url_exports)
        for job in prepared.jobs:
            names = image_names(job.spu_id)
            uploaded = dict(state['jobs'].setdefault(job.spu_id, {}).get('uploaded_urls') or {})
            for kind, filename in names.items():
                url = existing_urls.get(normalize_material_stem(filename))
                if url:
                    uploaded[kind] = url
            if uploaded:
                state['jobs'][job.spu_id]['uploaded_urls'] = uploaded
        _save_state(state_path, state)
    if agent_text:
        _seed_agent_text(prepared, state, agent_text)
        _save_state(state_path, state)
    if not text_model:
        for job in prepared.jobs:
            item = state.get('jobs', {}).get(job.spu_id, {})
            if job.needs_selling_points and (not item.get('selling_points')):
                raise ValueError(f'SPU {job.spu_id} 卖点文本默认由 agent 按 SKILL 规则自拟并通过 --agent-text-file 注入；本命令默认不调用网关文本模型。宿主补齐本任务文案后继续，不使用公司文本渠道。')
            if not _short_titles_are_complete(job, item):
                raise ValueError(f'SPU {job.spu_id} 短标题默认由 agent 按 SKILL 规则自拟并通过 --agent-text-file 注入；本命令默认不调用网关文本模型。宿主补齐本任务文案后继续，不使用公司文本渠道。')
    state_lock = threading.Lock()

    def needs_model_client() -> bool:
        for job in prepared.jobs:
            item = state.get('jobs', {}).get(job.spu_id, {})
            if job.needs_selling_points and (not item.get('selling_points')):
                return True
            if not _short_titles_are_complete(job, item):
                return True
            names = image_names(job.spu_id)
            uploaded = item.get('uploaded_urls') or {}
            if any((not valid_material_image(images / names[kind], kind) and (not uploaded.get(kind)) for kind in _model_kinds(job))):
                return True
        return False
    client = None
    if needs_model_client():
        client = model_client_factory() if model_client_factory else ModelClient(os.environ.get(PROVIDER.api_key_env, ''), timeout=timeout, image_concurrency=image_concurrency, text_model=text_model)
    if client is not None and getattr(client, 'text_model', None) == 'auto':
        with client._title_registry_lock:
            for item in state['jobs'].values():
                for sku, title in (item.get('short_titles') or {}).items():
                    if valid_short_title(title):client._title_registry[title] = sku
    if client is not None and joyagent_adapter:
        from pop_repair import install_joyagent_fallback
        template = json.loads(Path(joyagent_adapter).read_text(encoding='utf-8'))
        install_joyagent_fallback(client, template, output, timeout)
    failures: list[tuple[SpuJob, str]] = []

    def save_job(spu_id: str, key: str, value) -> None:
        with state_lock:
            state['jobs'].setdefault(spu_id, {})[key] = value
            _save_state(state_path, state)

    def complete_job(spu_id: str) -> None:
        with state_lock:
            item = state['jobs'].setdefault(spu_id, {})
            item['status'] = 'completed'
            item.pop('failure', None)
            _save_state(state_path, state)

    @stage_timer(output, 'text')
    def process_text(job: SpuJob, item: dict) -> None:
        if job.needs_selling_points and (not item.get('selling_points')):
            assert client is not None
            save_job(job.spu_id, 'selling_points', client.selling_points(job.title))
        pending_short = [(sku, title) for sku, title in job.skus if sku in job.short_title_sku_ids and (not valid_short_title(item.get('short_titles', {}).get(sku)))]
        if pending_short:
            assert client is not None
            merged = dict(item.get('short_titles', {}))
            chunks = [pending_short[index:index + 25] for index in range(0, len(pending_short), 25)]
            if getattr(client, 'text_model', None) == 'auto':
                # Large SPUs: chunks run in parallel under the shared text semaphore; valid rows
                # are saved even when a few SKU rows need Agent fallback.
                with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as title_pool:
                    futures = [title_pool.submit(client.short_titles, chunk, partial=True) for chunk in chunks]
                    error = None
                    for future in as_completed(futures):
                        try:
                            merged.update(future.result())
                            save_job(job.spu_id, 'short_titles', merged)
                        except Exception as failure:
                            error = error or failure
                if any(sku not in merged for sku, _ in pending_short):
                    from pop_text import TextPoolUnavailable
                    raise TextPoolUnavailable('Some short titles failed validation; Agent fills only unresolved frozen SKU text') from error
            else:
                for chunk in chunks:
                    merged.update(client.short_titles(chunk))
                    save_job(job.spu_id, 'short_titles', merged)

    @stage_timer(output, 'images')
    def process_images(job: SpuJob, item: dict) -> None:
        names = image_names(job.spu_id)
        uploaded = item.get('uploaded_urls') or {}
        required_model_kinds = _model_kinds(job)
        pending = [kind for kind in required_model_kinds if not valid_material_image(images / names[kind], kind) and (not uploaded.get(kind))]
        if pending:
            assert client is not None
            source = resolve_reference(reference_dir, job)
            recovery = dict(item.get('moderation_recovery') or {})
            if recovery.get('normal_status') != 'blocked':
                results, errors = _request_image_set(client, pending, source, job.title, scene_model=scene_image_model, image_model=image_model)
                # Gateway disconnect waves (peer closed/timeouts across every pool model) used to fail the whole
                # SPU and wait for a manual rerun; retry only the transiently failed kinds a few times in-run.
                for retry_round in range(1, 4):
                    transient = [kind for kind, failure in errors.items() if pool_switchable(failure) and not is_moderation_error(failure)]
                    if not transient:
                        break
                    time.sleep(3 * retry_round)
                    retried, retried_errors = _request_image_set(client, transient, source, job.title, scene_model=scene_image_model, image_model=image_model)
                    results.update(retried)
                    for kind in transient:
                        errors.pop(kind, None)
                    errors.update(retried_errors)
                for kind, content in results.items():
                    normalize_jpeg(content, images / names[kind], pure_white=kind == 'white')
                all_required_moderated = set(pending) == set(required_model_kinds) and len(errors) == len(required_model_kinds) and all((is_moderation_error(error) for error in errors.values()))
                if errors and (not all_required_moderated):
                    raise RuntimeError('；'.join((f'{kind}: {error}' for kind, error in errors.items())))
                if all_required_moderated:
                    recovery['normal_status'] = 'blocked'
                    save_job(job.spu_id, 'moderation_recovery', recovery)
            pending = [kind for kind in required_model_kinds if not valid_material_image(images / names[kind], kind)]
            if pending and recovery.get('normal_status') == 'blocked':
                if recovery.get('titleless_status') not in {'failed', 'succeeded'}:
                    recovery['titleless_status'] = 'running'
                    save_job(job.spu_id, 'moderation_recovery', recovery)
                    results, errors = _request_image_set(client, required_model_kinds, source, None, scene_model=scene_image_model, image_model=image_model)
                    if not errors and set(results) == set(required_model_kinds):
                        _commit_staged_images(results, images, names, job.spu_id)
                        recovery['titleless_status'] = 'succeeded'
                        recovery['status'] = 'succeeded'
                        save_job(job.spu_id, 'moderation_recovery', recovery)
                    else:
                        recovery['titleless_status'] = 'failed'
                        save_job(job.spu_id, 'moderation_recovery', recovery)
                        if not errors or not all((is_moderation_error(error) for error in errors.values())):
                            raise RuntimeError('；'.join((f'{kind}: {error}' for kind, error in errors.items())))
                pending = [kind for kind in required_model_kinds if not valid_material_image(images / names[kind], kind)]
                if pending:
                    attempted = set(recovery.get('attempted_candidates') or [])
                    available = [path for path in gallery_reference_candidates(reference_dir, job) if path.name not in attempted]
                    selected = None
                    for candidate in available:
                        attempted.add(candidate.name)
                        recovery['attempted_candidates'] = sorted(attempted)
                        recovery['status'] = 'running'
                        save_job(job.spu_id, 'moderation_recovery', recovery)
                        try:
                            white = request_material_image(client, 'white', image_prompt('white', None), candidate, model='pool')
                        except Exception as error:
                            if is_moderation_error(error):
                                continue
                            recovery['status'] = 'failed'
                            save_job(job.spu_id, 'moderation_recovery', recovery)
                            raise
                        normalize_jpeg(white, images / names['white'], pure_white=True)
                        if job.needs_transparent:
                            make_transparent(images / names['white'], images / names['transparent'])
                        derived = [kind for kind in required_model_kinds if kind != 'white' and (not valid_material_image(images / names[kind], kind))]
                        results, errors = _request_image_set(client, derived, images / names['white'], None, scene_model=scene_image_model, image_model=image_model)
                        if errors:
                            recovery['status'] = 'failed'
                            save_job(job.spu_id, 'moderation_recovery', recovery)
                            raise RuntimeError('；'.join((f'{kind}: {error}' for kind, error in errors.items())))
                        _commit_staged_images(results, images, names, job.spu_id)
                        selected = candidate
                        break
                    if not selected:
                        recovery['status'] = 'failed'
                        save_job(job.spu_id, 'moderation_recovery', recovery)
                        raise RuntimeError(f'SPU {job.spu_id} 正常轮和无标题轮均被安全策略拦截；请由 Agent 获取其他可信商品相册图，按 {job.spu_id}_gallery_001.jpg 顺序放入参考图目录后重试。')
                    recovery['selected_candidate'] = selected.name
                    recovery['status'] = 'succeeded'
                    save_job(job.spu_id, 'moderation_recovery', recovery)
        if job.needs_transparent and (not uploaded.get('transparent')) and (not valid_material_image(images / names['transparent'], 'transparent')):
            if not valid_material_image(images / names['white'], 'white'):
                if uploaded.get('white'):
                    restore_uploaded_white(uploaded['white'], images / names['white'], timeout)
                else:
                    raise RuntimeError('缺少有效白底图，无法生成透明图。')
            make_transparent(images / names['white'], images / names['transparent'])

    def process(job: SpuJob) -> None:
        with state_lock:
            item = dict(state['jobs'].setdefault(job.spu_id, {}))
        errors = []
        with ThreadPoolExecutor(max_workers=2) as branches:
            futures = [branches.submit(process_text, job, item), branches.submit(process_images, job, item)]
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    errors.append(str(error))
        if errors:
            raise RuntimeError('；'.join(dict.fromkeys(errors)))
        complete_job(job.spu_id)
    try:
        with ThreadPoolExecutor(max_workers=min(spu_concurrency, max(1, len(prepared.jobs)))) as executor:
            futures = {executor.submit(process, job): job for job in prepared.jobs}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as error:
                    failures.append((job, str(error)))
                    save_job(job.spu_id, 'failure', str(error))
    finally:
        if client and model_client_factory is None:
            client.close()
    unresolved_text = {'sellingPoints': {}, 'shortTitles': {}}
    for job in prepared.jobs:
        item = state['jobs'].get(job.spu_id, {})
        if job.needs_selling_points and not item.get('selling_points'):
            unresolved_text['sellingPoints'][job.spu_id] = {'sourceTitle': job.title, 'requiredCount': '2-3'}
        for sku, source_title in job.skus:
            if sku in job.short_title_sku_ids and not valid_short_title((item.get('short_titles') or {}).get(sku)):
                unresolved_text['shortTitles'][sku] = {'sourceTitle': source_title, 'weightedLength': '16-30'}
    if any(unresolved_text.values()):
        _save_state(output / '.state' / 'agent-text-fallback.json', {'status': 'agent-fallback-required', 'frozenScopeOnly': True, **unresolved_text})
    result = _write_results(prepared, output, state, failures)
    if client is not None and hasattr(client, 'text_model_stats'):
        state['text_models'] = client.text_model_stats()
        _save_state(state_path, state)
    if client is not None and hasattr(client, 'image_model_stats'):
        state['image_models'] = _merge_image_model_stats(state.get('image_models'), client.image_model_stats())
        _save_state(state_path, state)
    from pop_repair import workflow_quota_exhausted
    if workflow_quota_exhausted(client, result.failed_spus):
        state['model_pause'] = {'reason': 'quota-exhausted', 'code': 2007}
        _save_state(state_path, state)
        raise ModelQuotaExceeded()
    if state.pop('model_pause', None) is not None:
        _save_state(state_path, state)
    return result

def normalize_material_stem(value: object) -> str:
    name = cell_text(value).replace('\\', '/').rsplit('/', 1)[-1]
    return re.sub('\\.(?:jpe?g|png|webp)$', '', name, flags=re.I).strip()

def load_url_exports(paths: Iterable[str | Path]) -> dict[str, str]:
    mapping = {}
    for path in paths:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            found = False
            for sheet in workbook.worksheets:
                rows = list(sheet.iter_rows(values_only=True))
                for index, row in enumerate(rows[:20]):
                    headers = [cell_text(value).replace(' ', '') for value in row]
                    name_index = next((i for i, value in enumerate(headers) if value in {'图片名称', '文件名称', '名称'}), None)
                    url_index = next((i for i, value in enumerate(headers) if value in {'图片链接', '图片URL', '链接', 'URL'}), None)
                    if name_index is None or url_index is None:
                        continue
                    found = True
                    for data in rows[index + 1:]:
                        name = normalize_material_stem(data[name_index] if name_index < len(data) else None)
                        url = cell_text(data[url_index] if url_index < len(data) else None)
                        if not name and (not url):
                            continue
                        if url.startswith('//'):
                            url = 'https:' + url
                        if not re.match('^https?://', url):
                            raise ValueError(f'图片链接无效：{url}')
                        if name in mapping and mapping[name] != url:
                            raise ValueError(f'图片名称重复且链接不同：{name}')
                        mapping[name] = url
                    break
            if not found:
                raise ValueError(f'URL 表 {path} 未找到图片名称/图片链接表头。')
        finally:
            workbook.close()
    return mapping

def fill_material_template(manifest_path: str | Path, url_exports: Iterable[str | Path], output_path: str | Path, template_path: str | Path | None=None) -> Path:
    urls = load_url_exports(url_exports)
    manifest = load_workbook(manifest_path, read_only=True, data_only=True)
    rows = []
    manifest_state=_load_state(Path(manifest_path).parent/'.state/task.json')
    try:
        sheet = manifest['素材生成清单']
        headers = [cell_text(value) for value in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
        columns = {name: index for index, name in enumerate(headers)}
        requirement_headers = {'points': '需要卖点', 'white': '需要白底图', 'scenes': '需要场景图', 'selling': '需要卖点图'}
        has_requirements = all((name in columns for name in requirement_headers.values()))
        for values in sheet.iter_rows(min_row=2, values_only=True):
            spu_id = cell_text(values[columns.get('SPUID', 0)])
            required = {key: not has_requirements or cell_text(values[columns[name]]).lower() in {'1', 'true', '是', '需要'} for key, name in requirement_headers.items()}
            points = binding_selling_points(spu_id,values[4:7],manifest_state.get('jobs',{}).get(spu_id,{})) if required['points'] else ['', '', '']
            stems = {kind: normalize_material_stem(name) for kind, name in image_names(spu_id).items()}
            required_kinds = []
            if required['white']:
                required_kinds.extend(('transparent', 'white'))
            if required['scenes']:
                required_kinds.extend(('scene1', 'scene2'))
            if required['selling']:
                required_kinds.append('selling')
            missing = [stems[kind] for kind in required_kinds if stems[kind] not in urls]
            if missing:
                raise ValueError(f"SPU {spu_id} 缺少图片链接：{','.join(missing)}")
            rows.append([spu_id, '', *points, None, None, None, None, None, urls[stems['transparent']] if required['white'] else '', urls[stems['white']] if required['white'] else '', urls[stems['scene1']] if required['scenes'] else '', urls[stems['scene2']] if required['scenes'] else '', urls[stems['selling']] if required['selling'] else ''])
    finally:
        manifest.close()
    template = Path(template_path) if template_path else Path(__file__).parents[1] / 'assets' / '商品素材导入模板-通用场景.xlsx'
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    workbook = load_workbook(output)
    try:
        if '通用场景' not in workbook.sheetnames or workbook['通用场景'].max_column != 15:
            raise ValueError('官方模板缺少 15 列“通用场景”工作表。')
        sheet = workbook['通用场景']
        if sheet.max_row > 1:
            sheet.delete_rows(2, sheet.max_row - 1)
        for row_index, values in enumerate(rows, 2):
            for column, value in enumerate(values, 1):
                sheet.cell(row_index, column, value).number_format = '@'
        workbook.save(output)
    finally:
        workbook.close()
    return output

def finalize_uploaded_materials(prepared: PreparedSource, manifest_path: str | Path, url_export_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    urls = load_url_exports([url_export_path])
    successful: set[str] = set()
    failed: list[SpuJob] = []
    for job in prepared.jobs:
        required = set(_model_kinds(job))
        if job.needs_transparent:
            required.add('transparent')
        stems = {kind: normalize_material_stem(name) for kind, name in image_names(job.spu_id).items()}
        if all((stems[kind] in urls for kind in required)):
            successful.add(job.spu_id)
        elif _has_material_work(job):
            failed.append(job)
    output = Path(output_dir)
    success_manifest = output / '素材上传成功清单.xlsx'
    final_workbook = output / '商品素材导入-已回填.xlsx'
    failure_workbook = output / '上传失败SPU清单.xlsx'
    if successful:
        shutil.copy2(manifest_path, success_manifest)
        workbook = load_workbook(success_manifest)
        try:
            for sheet in workbook.worksheets:
                if sheet.max_row < 2:
                    continue
                headers = [cell_text(value) for value in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
                if 'SPUID' not in headers:
                    continue
                column = headers.index('SPUID') + 1
                for row_number in range(sheet.max_row, 1, -1):
                    if cell_text(sheet.cell(row_number, column).value) not in successful:
                        sheet.delete_rows(row_number)
            workbook.save(success_manifest)
        finally:
            workbook.close()
        fill_material_template(success_manifest, [url_export_path], final_workbook)
    else:
        success_manifest.unlink(missing_ok=True)
        final_workbook.unlink(missing_ok=True)
    if failed:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '上传失败SPU'
        sheet.append(['SPUID', '代表SKUID', 'SKU数量', '失败原因'])
        for job in failed:
            sheet.append([job.spu_id, job.representative_sku_id, job.sku_count, '图片空间链接不完整'])
        detail = workbook.create_sheet('SKU明细')
        detail.append(['SPUID', 'SKUID', '商品名称'])
        for job in failed:
            for sku_id, title in job.skus:
                detail.append([job.spu_id, sku_id, title])
        workbook.save(failure_workbook)
        workbook.close()
    else:
        failure_workbook.unlink(missing_ok=True)
    return {'successfulSpus': len(successful), 'failedSpus': len(failed), 'successManifest': success_manifest if successful else None, 'failureWorkbook': failure_workbook if failed else None, 'finalWorkbook': final_workbook if successful else None}

def _write_jdo_source(prepared: PreparedSource, path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = prepared.sheet_name
    sheet.append(list(prepared.headers))
    for row in prepared.rows:
        sheet.append(list(row.raw) if row.raw else [row.sku_id, row.title, row.spu_id, row.score])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path

def _normalize_reference_file(output: Path) -> None:
    with Image.open(output) as image:
        if image.size == (800, 800) and image.format == 'JPEG':
            image.verify()
            return
    temporary = output.with_suffix('.normalized.tmp.jpg')
    normalize_jpeg(output.read_bytes(), temporary)
    temporary.replace(output)

def _download_reference(url: str, output: Path, timeout: float) -> Path:
    trusted_url = _jd_image_url(url)
    if output.is_file():
        try:
            with Image.open(output) as image:
                image.verify()
            _normalize_reference_file(output)
            return output
        except OSError:
            pass
    response = httpx.get(trusted_url, timeout=timeout, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://item.jd.com/'})
    response.raise_for_status()
    final_url = _jd_image_url(str(response.url))
    if not final_url:
        raise ValueError('product image download redirected to an invalid URL')
    if len(response.content) > 20 * 1024 * 1024:
        raise ValueError('product image exceeds 20MB')
    with Image.open(BytesIO(response.content)) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp.jpg')
        image.save(temporary, 'JPEG', quality=95, optimize=True)
        temporary.replace(output)
    _normalize_reference_file(output)
    return output

def _subset_prepared(prepared: PreparedSource, rows: list[SourceRow]) -> PreparedSource:
    selected_spus = list(dict.fromkeys((row.spu_id for row in rows)))
    jobs_by_spu = {job.spu_id: job for job in prepared.jobs}
    missing = [spu_id for spu_id in selected_spus if spu_id not in jobs_by_spu]
    if missing:
        raise ValueError(f"prepared subset contains unknown SPUs: {','.join(missing)}")
    return PreparedSource(prepared.source_type, prepared.sheet_name, prepared.headers, tuple(rows), tuple((jobs_by_spu[spu_id] for spu_id in selected_spus)), len(rows), 0, 0)

def _auto_resume_targets(output: Path, target_spu_id: str) -> tuple[str, ...]:
    if not target_spu_id:
        return ()
    candidates = [output / '.state' / 'task.json', *sorted(output.glob('批次*/.state/task.json'))]
    for state_path in candidates:
        if not state_path.is_file():
            continue
        state = _load_state(state_path)
        if target_spu_id in (state.get('jobs') or {}):
            return (target_spu_id,)
    return ()

KIND_BY_SUFFIX = {'白底图.jpg': 'white', '透明图.png': 'transparent', '场景图1.jpg': 'scene1', '场景图2.jpg': 'scene2', '卖点图.jpg': 'selling'}
SLOT_BY_KIND = {'white': 31, 'transparent': 36, 'scene1': 32, 'scene2': 32, 'selling': 33}

def _kind_from_filename(name: str) -> tuple[str, str] | None:
    for suffix, kind in KIND_BY_SUFFIX.items():
        if name.endswith(suffix):
            return (name[: -len(suffix)], kind)
    return None

def reconcile_run_receipts(client: Any, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    if not output.is_dir() or not any(output.glob('批次*/.state/task.json')):
        raise ValueError('对账目录必须是原任务根目录（包含批次*/.state/task.json），不能指定批次或.state目录')
    from pop_safety import reconcile
    return reconcile(client, output_dir, sys.modules[__name__])

def _parse_excluded_bindings(values: Iterable[str], prepared: PreparedSource) -> frozenset[tuple[str, int]]:
    known_spus = {job.spu_id for job in prepared.jobs}
    parsed: list[tuple[str, int]] = []
    for value in values:
        parts = cell_text(value).split(':')
        if len(parts) != 2 or not parts[0].isdecimal() or not parts[1].isdecimal() or int(parts[1]) not in {31, 32, 33, 36, 1002}:
            raise ValueError('--exclude-binding 格式必须是 SPUID:素材类型，素材类型仅支持 31/32/33/36/1002')
        if parts[0] not in known_spus:
            raise ValueError(f'--exclude-binding SPU {parts[0]} 不在当前维护计划内')
        parsed.append((parts[0], int(parts[1])))
    return frozenset(parsed)

def _parse_reference_overrides(values: Iterable[str], prepared: PreparedSource) -> dict[str, Path]:
    known_spus = {job.spu_id for job in prepared.jobs}
    overrides: dict[str, Path] = {}
    for value in values:
        parts = cell_text(value).split('=', 1)
        if len(parts) != 2 or not parts[0].isdecimal() or not parts[1].strip():
            raise ValueError('--reference-override 格式必须是 SPUID=图片路径（本地文件）')
        spu_id, raw_path = parts[0], Path(parts[1].strip())
        if spu_id not in known_spus:
            raise ValueError(f'--reference-override SPU {spu_id} 不在当前维护计划内')
        if not raw_path.is_file():
            raise ValueError(f'--reference-override 参考图不存在：{raw_path}')
        overrides[spu_id] = raw_path
    return overrides

def _scope_pop_discovery(prepared: PreparedSource, reference_urls: dict[str, str], existing_materials: dict[str, dict[str, Any]], target_spu_id: str, *, exclude_spu_ids: Iterable[str]=()) -> tuple[PreparedSource, dict[str, str], dict[str, dict[str, Any]]]:
    excluded = {cell_text(value) for value in exclude_spu_ids or () if cell_text(value)}
    if target_spu_id and target_spu_id in excluded:
        raise ValueError('--target-spu-id cannot also be passed to --exclude-spu-id')
    if excluded:
        # User-declared out-of-scope SPUs never enter the frozen plan, so nothing is generated/uploaded/bound for them.
        kept = [row for row in prepared.rows if row.spu_id not in excluded]
        prepared = _subset_prepared(prepared, kept) if kept else PreparedSource(prepared.source_type, prepared.sheet_name, prepared.headers, (), (), 0, 0, 0)
        reference_urls = {k: v for k, v in reference_urls.items() if k not in excluded}
        existing_materials = {k: v for k, v in existing_materials.items() if k not in excluded}
    if not target_spu_id:
        return (prepared, reference_urls, existing_materials)
    target_rows = [row for row in prepared.rows if row.spu_id == target_spu_id]
    if not target_rows:
        raise ValueError('--target-spu-id is not in the current maintenance set')
    return (_subset_prepared(prepared, target_rows), {target_spu_id: reference_urls.get(target_spu_id, '')}, {target_spu_id: existing_materials.get(target_spu_id, {})})

def host_task_handoff(prepared, output, seller, profile=None):
    """Expose exact host inputs and original commands; no planning or business dispatch."""
    output=Path(output).resolve()
    frozen=json.loads((output/AUTO_MAINTAIN_PLAN_NAME).read_text(encoding='utf-8'))
    full,_,_,_=load_pop_auto_maintain_plan(output,seller,frozen.get('targetSpuId'))
    allowed={job.spu_id for job in full.jobs}
    if not {job.spu_id for job in prepared.jobs}.issubset(allowed):raise ValueError('交接范围超出原计划')
    needs_points=[];needs_titles=[];facts=[]
    for index,rows in frozen_scope_batches(prepared,output):
        state=_load_state(output/f'批次{index:03d}/.state/task.json')
        for job in _subset_prepared(prepared,rows).jobs:
            item=state.get('jobs',{}).get(job.spu_id,{})
            if job.needs_selling_points and not item.get('selling_points'):needs_points.append(job.spu_id)
            needs_titles.extend(sku for sku in job.short_title_sku_ids if not valid_short_title((item.get('short_titles') or {}).get(sku)))
            facts.append({'spuId':job.spu_id,'title':job.title,'skus':[{'skuId':sku,'title':title} for sku,title in job.skus]})
    entry=str(Path(os.environ.get('HEIDENG_MERCHANT_PACKAGE') or Path(__file__).resolve().parents[3])/'scripts/merchant.py')
    base=['python',entry,'run','materials','--']
    scope_args=['--output-dir',str(output)] + (['--profile',profile] if profile else [])
    expected=['--expected-shop-name',_shop_identity(seller)['shopName']]
    execute=base+['auto-maintain',*scope_args,*expected,'--agent-text-file',str(output/'host-text.json'),'--confirm','AUTO_MAINTAIN','--no-paid-repairs']
    selected={job.spu_id for job in prepared.jobs}
    if selected!=allowed:
        if len(selected)!=1:raise ValueError('恢复命令只支持完整任务或单SPU子集')
        execute+=['--target-spu-id',next(iter(selected))]
    return {'schemaVersion':1,'taskDirectory':str(output),'planHash':frozen['planHash'],'shopIdentity':_shop_identity(seller),
            'scope':{'spuIds':[j.spu_id for j in prepared.jobs],'skuIds':[r.sku_id for r in prepared.rows]},
            'facts':facts,'textInput':{'file':str(output/'host-text.json'),'neededSellingPointSpuIds':needs_points,
              'neededShortTitleSkuIds':needs_titles,'schema':{'type':'object','required':['sellingPoints','shortTitles'],
              'properties':{'sellingPoints':{'type':'object','additionalProperties':{'type':'array','minItems':3,'maxItems':3,'items':{'type':'string'}}},
                            'shortTitles':{'type':'object','additionalProperties':{'type':'string'}}},'additionalProperties':False},
              'validation':'原卖点禁词/长度与短标题加权16–30规则；只补上述待补ID，已合格文本不改'},
            'attributes':{'inputFile':str(output/'host-attrs.json'),
              'schema':{'type':'object','additionalProperties':{'type':'object','required':['evidence','choices'],
                'properties':{'evidence':{'type':'string','minLength':1},'choices':{'type':'array','items':{'type':'object',
                'required':['title','n','confidence'],'properties':{'title':{'type':'string'},
                'n':{'type':'array','items':{'type':'integer','minimum':0}},'confidence':{'const':'high'}}}}}}},
              'applyArgv':base+['complete-product-attrs',*scope_args,*expected,'--confirm','AUTO_MAINTAIN',*[v for j in prepared.jobs for v in ('--product-id',j.spu_id)]],
              'replanArgv':base+['plan-missing-attrs',*scope_args,*expected,'--agent-attrs-file',str(output/'host-attrs.json'),*[v for j in prepared.jobs for v in ('--product-id',j.spu_id)]],
              'inventoryArgv':base+['plan-missing-attrs',*scope_args,*expected,*[v for j in prepared.jobs for v in ('--product-id',j.spu_id)]],
              'rule':'按原attr-plan中的类型和合法选项产出agent-attrs-file；不猜地区ID或调用员工视觉模型'},
            'executeArgv':execute,'recoverArgv':base+['reconcile-receipts',*scope_args],
            'executionAuthorized':False,'nextAction':'宿主按事实补文案/属性，沿用已确认范围；新写入/费用确认后执行，未知先对账'}


def _save_host_handoff(prepared, output, seller, profile=None):
    from pop_safety import atomic_json
    payload=host_task_handoff(prepared,output,seller,profile)
    path=Path(output)/'.state/host-handoff.json';atomic_json(path,payload)
    return {'file':str(path.resolve()),'missingSellingPointCount':len(payload['textInput']['neededSellingPointSpuIds']),
            'missingShortTitleCount':len(payload['textInput']['neededShortTitleSkuIds']),'nextAction':payload['nextAction']}


@exclusive_pop_run
def run_plan_auto_maintain(args) -> dict[str, Any]:
    if getattr(args, 'business_mode', 'pop') != 'pop':
        raise ValueError('plan-auto-maintain currently supports POP mode only')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    refresh = bool(getattr(args, 'refresh', False))
    if refresh and any(output.glob('批次*/.state/task.json')):
        raise ValueError('该输出目录已有执行状态；刷新全店请使用新输出目录')
    target_spu_id = cell_text(getattr(args, 'target_spu_id', None))
    include_full_score = bool(getattr(args, 'include_full_score', False))
    client = JdoClient(getattr(args, 'profile', None), output / '.state' / 'jdo-runtime')
    plan_path = output.resolve() / AUTO_MAINTAIN_PLAN_NAME
    if plan_path.is_file() and (not refresh) and include_full_score:
        raise ValueError('该输出目录已有不含满分级直查的计划；--include-full-score 需要 --refresh 或新输出目录')
    if plan_path.is_file() and (not refresh):
        seller = client.seller_info()
        expected_shop_name = cell_text(getattr(args, 'expected_shop_name', None))
        if expected_shop_name and cell_text(seller.get('shopName')) != expected_shop_name:
            raise ValueError('current jdo-cli shop does not match --expected-shop-name')
        prepared, _, _, source_path = load_pop_auto_maintain_plan(output, seller, target_spu_id)
        return {'status': 'planned-existing', 'shopName': _shop_identity(seller)['shopName'], 'source': str(source_path), 'plan': str(plan_path), 'planReused': True, 'skuCount': len(prepared.rows), 'spuCount': len(prepared.jobs), 'hostHandoff':_save_host_handoff(prepared,output,seller,getattr(args,'profile',None))}
    prepared, reference_urls, existing_materials = discover_jdo_pop_source(client, expected_shop_name=getattr(args, 'expected_shop_name', None), include_spu_ids=_auto_resume_targets(output, target_spu_id), include_full_score=include_full_score, off_shelf_spu_ids=getattr(args, 'include_off_shelf_spu', ()), scope_spu_ids=[target_spu_id] if target_spu_id else None)
    prepared, reference_urls, existing_materials = _scope_pop_discovery(prepared, reference_urls, existing_materials, target_spu_id, exclude_spu_ids=getattr(args, 'exclude_spu_id', ()) or ())
    source_path = _write_jdo_source(prepared, output / '实时商品信息分0-89.xlsx')
    seller = client.seller_info()
    plan_path = write_pop_auto_maintain_plan(prepared, reference_urls, existing_materials, seller, output, source_path, target_spu_id=target_spu_id)
    return {'status': 'planned', 'shopName': _shop_identity(seller)['shopName'], 'source': str(source_path), 'plan': str(plan_path), 'planReused': False, 'skuCount': len(prepared.rows), 'spuCount': len(prepared.jobs), 'hostHandoff':_save_host_handoff(prepared,output,seller,getattr(args,'profile',None))}

def route_jingmai_batch_images(prepared: PreparedSource, *, model_cutout_images: bool=False) -> tuple[PreparedSource, list[dict[str, Any]]]:
    """Route missing cutout slots externally without changing the frozen plan."""
    if model_cutout_images:
        return prepared, []
    handoff = []
    jobs = []
    for job in prepared.jobs:
        kinds = (["white"] if job.needs_white else []) + (["transparent"] if job.needs_transparent else [])
        if kinds:
            handoff.append({'spuId': job.spu_id, 'skuIds': list(job.sku_ids), 'kinds': kinds})
        jobs.append(replace(job, needs_white=False, needs_transparent=False))
    return replace(prepared, jobs=tuple(jobs)), handoff

def pending_cutout_handoff(prepared: PreparedSource, output: str | Path) -> list[dict[str, Any]]:
    """After a model cutout attempt, list SPUs whose white/transparent slot is still unusable."""
    output = Path(output)
    handoff = []
    for index, rows in frozen_scope_batches(prepared, output):
        batch = _subset_prepared(prepared, rows)
        batch_dir = output / f'批次{index:03d}'
        images = batch_dir / '全部图片'
        state = _load_state(batch_dir / '.state' / 'task.json')
        for job in batch.jobs:
            item = state['jobs'].get(job.spu_id) or {}
            if item.get('status') == 'completed':
                continue
            uploaded = item.get('uploaded_urls') or {}
            names = image_names(job.spu_id)
            kinds = []
            if job.needs_white and (not uploaded.get('white')) and (not valid_material_image(images / names['white'], 'white')):
                kinds.append('white')
            if job.needs_transparent and (not uploaded.get('transparent')) and (not valid_material_image(images / names['transparent'], 'transparent')):
                kinds.append('transparent')
            if kinds:
                handoff.append({'spuId': job.spu_id, 'skuIds': list(job.sku_ids), 'kinds': kinds})
    return handoff

@exclusive_pop_run
def run_generate_auto_maintain(args) -> dict[str, Any]:
    if args.confirm != 'AUTO_MAINTAIN':
        raise ValueError('generate-auto-maintain requires --confirm AUTO_MAINTAIN before billable generation')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assert_no_unknown_uploads(output)
    target_spu_id = cell_text(getattr(args, 'target_spu_id', None))
    client = JdoClient(args.profile, output / '.state' / 'jdo-runtime')
    seller = client.seller_info()
    expected_shop_name = cell_text(getattr(args, 'expected_shop_name', None))
    if expected_shop_name and cell_text(seller.get('shopName')) != expected_shop_name:
        raise ValueError('current jdo-cli shop does not match --expected-shop-name')
    prepared, reference_urls, existing_materials, source_path = load_pop_auto_maintain_plan(output, seller, target_spu_id)
    prepared, batch_image_handoff = route_jingmai_batch_images(prepared, model_cutout_images=getattr(args, "model_cutout_images", False))
    agent_text = load_scoped_agent_text(args.agent_text_file,prepared,output,seller) if getattr(args, 'agent_text_file', None) else None
    batch_payloads = []
    for index, rows in enumerate(split_rows_by_spu(prepared.rows), 1):
        batch = _subset_prepared(prepared, rows)
        batch_dir = output / f'批次{index:03d}'
        references = batch_dir / '参考图'
        reference_failures = []
        for job in batch.jobs:
            target_reference = references / f'{job.spu_id}.jpg'
            override = _parse_reference_overrides(getattr(args, 'reference_override', ()) or (), prepared).get(job.spu_id)
            if not _model_kinds(job):
                continue
            if override:
                references.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(override, target_reference)
                _normalize_reference_file(target_reference)
                continue
            try:
                url = reference_urls.get(job.spu_id)
                if not url:
                    raise ValueError('JDO did not return a trusted main image')
                _download_reference(url, target_reference, args.timeout)
            except Exception as error:
                reference_failures.append({'spuId': job.spu_id, 'error': str(error)})
        generation = generate_batch(batch, references, batch_dir, spu_concurrency=args.spu_concurrency, image_concurrency=args.image_concurrency, timeout=args.timeout, existing_materials={job.spu_id: existing_materials.get(job.spu_id, {}) for job in batch.jobs}, agent_text=_batch_agent_text(agent_text, batch), scene_image_model=getattr(args, 'scene_model', None), image_model=getattr(args, 'image_model', None), text_model=getattr(args, 'text_model', None))
        batch_payloads.append({'batch': index, 'spuCount': len(batch.jobs), 'skuCount': len(batch.rows), 'completedSpus': generation.completed_spus, 'failedSpus': generation.failed_spus, 'referenceFailures': reference_failures, 'manifest': str(generation.manifest_path) if generation.manifest_path else None, 'shortTitles': str(generation.short_title_path) if generation.short_title_path else None, 'failureWorkbook': str(generation.failure_path) if generation.failure_path else None})
    has_failures = any((batch['failedSpus'] or batch['referenceFailures'] for batch in batch_payloads))
    delivery = export_short_title_delivery([(prepared, output)], output, shop_name=_shop_identity(seller)['shopName'])
    return {'status': 'generated-local-with-failures' if has_failures else 'generated-local', 'shopName': _shop_identity(seller)['shopName'], 'source': str(source_path), 'planReused': True, 'skuCount': len(prepared.rows), 'spuCount': len(prepared.jobs), 'batches': batch_payloads, 'uploadPerformed': False, 'bindingPerformed': False, 'batchImageHandoff': batch_image_handoff, 'shortTitleFiles': delivery['shortTitleFiles'], 'shortTitleDelivery': delivery}

@exclusive_pop_run
def run_auto_maintain(args) -> dict[str, Any]:
    if args.confirm != 'AUTO_MAINTAIN':
        raise ValueError('auto-maintain requires --confirm AUTO_MAINTAIN before billable generation and upload')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assert_no_unknown_uploads(output)
    target_spu_id = cell_text(getattr(args, 'target_spu_id', None))
    client = JdoClient(args.profile, output / '.state' / 'jdo-runtime')
    plan_path = output.resolve() / AUTO_MAINTAIN_PLAN_NAME
    plan_reused = plan_path.is_file()
    if plan_reused:
        seller = client.seller_info()
        expected_shop_name = cell_text(getattr(args, 'expected_shop_name', None))
        if expected_shop_name and cell_text(seller.get('shopName')) != expected_shop_name:
            raise ValueError('current jdo-cli shop does not match --expected-shop-name')
        prepared, reference_urls, existing_materials, source_path = load_pop_auto_maintain_plan(output, seller, target_spu_id)
    else:
        prepared, reference_urls, existing_materials = discover_jdo_pop_source(client, expected_shop_name=args.expected_shop_name, include_spu_ids=_auto_resume_targets(output, target_spu_id), include_full_score=bool(getattr(args, 'include_full_score', False)), off_shelf_spu_ids=getattr(args, 'include_off_shelf_spu', ()), scope_spu_ids=[target_spu_id] if target_spu_id else None)
        prepared, reference_urls, existing_materials = _scope_pop_discovery(prepared, reference_urls, existing_materials, target_spu_id, exclude_spu_ids=getattr(args, 'exclude_spu_id', ()) or ())
        source_path = _write_jdo_source(prepared, output / '实时商品信息分0-89.xlsx')
        seller = client.seller_info()
        write_pop_auto_maintain_plan(prepared, reference_urls, existing_materials, seller, output, source_path, target_spu_id=target_spu_id)
    prepared, reference_urls, existing_materials = _scope_pop_discovery(prepared, reference_urls, existing_materials, target_spu_id, exclude_spu_ids=getattr(args, 'exclude_spu_id', ()) or ())
    args._maintenance_product_ids = [job.spu_id for job in prepared.jobs]
    args._maintenance_sku_ids = [sku for job in prepared.jobs for sku in job.sku_ids]
    if getattr(args, 'skip_transparent', False):
        prepared = replace(prepared, jobs=tuple(replace(job, needs_transparent=False) for job in prepared.jobs))
    prepared, batch_image_handoff = route_jingmai_batch_images(prepared, model_cutout_images=getattr(args, 'model_cutout_images', False))
    agent_text = load_scoped_agent_text(args.agent_text_file,prepared,output,seller) if getattr(args, 'agent_text_file', None) else None
    if not prepared.jobs:
        return {'status': 'no-work', 'batchImageHandoff': [], 'source': str(source_path), 'skuCount': 0, 'spuCount': 0, 'batches': [], 'browserRequired': False, 'planReused': plan_reused, 'verificationMode': getattr(args, 'verification_mode', 'submit-only'), 'manualVerificationRequired': False, 'manualVerificationMessage': None}
    if args.upload_mode != 'browser' and any(_has_material_work(job) for job in prepared.jobs):
        client.check_bridge()
    excluded_bindings = _parse_excluded_bindings(getattr(args, 'exclude_binding', None) or (), prepared)
    for index, rows in frozen_scope_batches(prepared, output):
        batch_dir = output / f'批次{index:03d}'
        state_path = batch_dir / '.state' / 'task.json'
        existing_state = _load_state(state_path)
        if any(item.get('material_bindings') for item in existing_state['jobs'].values()):
            prepare_material_binding_plan(client, _subset_prepared(prepared, rows), batch_dir, excluded_bindings=excluded_bindings)
    category_id = None
    material_work = any(_has_material_work(job) for job in prepared.jobs)
    browser_required = material_work and args.upload_mode == 'browser'
    if material_work and not browser_required:
        try:
            category_id = client.resolve_category(args.category_id, args.category_name)
        except (JdoPermissionError, JdoUnavailableError):
            if args.upload_mode == 'cli':
                raise
            browser_required = True
    batch_payloads = []
    binding_plans: list[tuple[int, MaterialBindingPlan]] = []
    for index, rows in frozen_scope_batches(prepared, output):
        batch = _subset_prepared(prepared, rows)
        batch_dir = output / f'批次{index:03d}'
        references = batch_dir / '参考图'
        reference_failures = []
        for job in batch.jobs:
            target_reference = references / f'{job.spu_id}.jpg'
            override = _parse_reference_overrides(getattr(args, 'reference_override', ()) or (), prepared).get(job.spu_id)
            if not _model_kinds(job):
                continue
            if override:
                references.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(override, target_reference)
                _normalize_reference_file(target_reference)
                continue
            try:
                url = reference_urls.get(job.spu_id)
                if not url:
                    raise ValueError('JDO did not return a trusted main image')
                _download_reference(url, target_reference, args.timeout)
            except Exception as error:
                reference_failures.append({'spuId': job.spu_id, 'error': str(error)})
        generation = generate_batch(batch, references, batch_dir, spu_concurrency=args.spu_concurrency, image_concurrency=args.image_concurrency, timeout=args.timeout, existing_materials={job.spu_id: existing_materials.get(job.spu_id, {}) for job in batch.jobs}, agent_text=_batch_agent_text(agent_text, batch), scene_image_model=getattr(args, 'scene_model', None), image_model=getattr(args, 'image_model', None), text_model=getattr(args, 'text_model', None), joyagent_adapter=getattr(args, 'joyagent_adapter', None))
        upload = None
        finalization = None
        binding = None
        if generation.manifest_path and (not browser_required):
            try:
                upload = upload_generated_materials(client, batch, batch_dir, category_id)
                browser_required = browser_required or upload.browser_required
            except (JdoPermissionError, JdoUnavailableError):
                if args.upload_mode == 'cli':
                    raise
                browser_required = True
        if generation.manifest_path and upload and (not upload.browser_required):
            finalization = finalize_uploaded_materials(batch, generation.manifest_path, upload.url_export_path, batch_dir)
            binding_plans.append((index, prepare_material_binding_plan(client, batch, batch_dir, excluded_bindings=excluded_bindings)))
        batch_payloads.append({'batch': index, 'spuCount': len(batch.jobs), 'completedSpus': generation.completed_spus, 'failedSpus': generation.failed_spus, 'referenceFailures': reference_failures, 'manifest': str(generation.manifest_path) if generation.manifest_path else None, 'upload': asdict(upload) if upload else None, 'finalization': finalization, 'binding': binding})
    binding_confirmation = None
    for index, plan in binding_plans:
        result = execute_material_binding_plan(client, plan)
        if result.browser_required and args.upload_mode == 'cli':
            raise JdoPermissionError('jdo-cli lacks permission for direct SKU material binding')
        browser_required = browser_required or result.browser_required
        batch_payloads[index - 1]['binding'] = asdict(result)
    if getattr(args, 'model_cutout_images', False):
        batch_image_handoff = pending_cutout_handoff(prepared, output)
    for batch in batch_payloads:
        if batch['upload']:
            batch['upload']['url_export_path'] = str(batch['upload']['url_export_path'])
        if batch['finalization']:
            for key in ('successManifest', 'failureWorkbook', 'finalWorkbook'):
                value = batch['finalization'][key]
                batch['finalization'][key] = str(value) if value else None
        if batch['binding']:
            for key in ('success_workbook', 'pending_workbook', 'failure_workbook'):
                value = batch['binding'][key]
                batch['binding'][key] = str(value) if value else None
    pending_review = any((batch['binding'] and batch['binding']['pending_spus'] for batch in batch_payloads))
    binding_failures = any((batch['binding'] and batch['binding']['failed_spus'] for batch in batch_payloads))
    has_failures = binding_failures or any((batch['failedSpus'] or batch['referenceFailures'] or (batch['upload'] and batch['upload']['failed_files']) or (batch['finalization'] and batch['finalization']['failedSpus']) for batch in batch_payloads))
    verification_mode = getattr(args, 'verification_mode', 'submit-only')
    status = 'completed'
    if browser_required:
        status = 'browser-handoff'
    elif verification_mode == 'submit-only':
        status = 'submitted-with-failures' if has_failures else 'submitted-for-manual-verification'
    elif pending_review:
        status = 'waiting-review'
    elif binding_failures:
        status = 'completed-with-failures'
    if batch_image_handoff and status != 'browser-handoff':
        status = 'partial-external-image-pending-with-failures' if has_failures else 'partial-external-image-pending'
    from pop_workflow import finish_external_images
    external_images = finish_external_images(args, batch_image_handoff, _shop_identity(seller), client, sys.modules[__name__])
    repair_result = {'status': 'not-requested'}
    if getattr(args, 'repair_rejected', False):
        from pop_repair import run_rejected_repairs
        repair_args = argparse.Namespace(max_model_requests=getattr(args,'max_repair_model_requests',None),repair_kinds=getattr(args,'repair_kind',None),no_paid_generation=not bool(getattr(args,'paid_repairs',False)), excluded_spu_ids=list(getattr(args, 'exclude_spu_id', ()) or ()), authorized_sku_ids=[sku for job in prepared.jobs for sku in job.sku_ids], authorized_product_ids=[job.spu_id for job in prepared.jobs], excluded_bindings=list(excluded_bindings), profile=args.profile, expected_shop_name=_shop_identity(seller)['shopName'], output_dir=output / 'rejected-repairs', confirm=args.confirm, image_concurrency=args.image_concurrency or 20, timeout=args.timeout, joyagent_adapter=getattr(args, 'joyagent_adapter', None), reference_override=[], profile_dir=getattr(args, 'profile_dir', None), jingmai_first=getattr(args, 'jingmai_first', True))
        try: repair_result = run_rejected_repairs(repair_args, sys.modules[__name__])
        except JdoWriteUncertainError: raise
        except Exception as error: repair_result = {'status': 'repair-incomplete', 'failureClass': type(error).__name__, 'reason': 'Repair scope/dependency not ready; preserve frozen audit and receipts'}
    delivery = export_short_title_delivery([(prepared, output)], output, shop_name=_shop_identity(seller)['shopName'])
    from pop_workflow import complete_short_title_import
    delivery = complete_short_title_import(args, delivery, _shop_identity(seller), client, sys.modules[__name__])
    attributes = {'status': 'not-requested'}
    if getattr(args, 'complete_attrs', False) is True:
        # Important attributes are part of the information score; same atomic chain as complete-product-attrs.
        try:
            import pop_attrs
            attr_dir = output / 'product-attrs';attr_dir.mkdir(parents=True, exist_ok=True)
            pool = None  # Host supplies evidenced choices; no configured external vision provider.
            try:attr_plan = pop_attrs.inventory(client, _shop_identity(seller), text_pool=pool, skip_attrs=pop_attrs.platform_broken_attrs(attr_dir), exclude_product_ids=getattr(args, 'exclude_spu_id', ()) or (), product_ids=[job.spu_id for job in prepared.jobs], agent_choices=pop_attrs.load_agent_choices(getattr(args, 'agent_attrs_file', None)))
            finally:
                if pool is not None:pool.close()
            pop_attrs._save(attr_dir / 'attr-plan.json', attr_plan)
            attributes = {'planned': len(attr_plan['plans']), 'leftNotImportant': len(attr_plan['needsConfirmation'])}
            if attr_plan['plans']:attributes.update(pop_attrs.submit_and_verify(client, attr_dir / 'attr-plan.json'))
            attributes.pop('results', None)
        except JdoWriteUncertainError:raise
        except Exception as error:attributes = {'status': 'attrs-incomplete', 'failureClass': type(error).__name__, 'reason': str(error)[:200]}
    if delivery['status'] not in {'verified', 'no-titles'}:
        status = 'short-title-' + delivery['status']
    coverage = {'status': 'verification-unavailable', 'allApproved': False}
    if getattr(args, 'repair_rejected', False):
        try:
            snapshot = audit_pop_coverage(client, _shop_identity(seller)['shopName'], product_ids=[job.spu_id for job in prepared.jobs], authorized_sku_ids=[sku for job in prepared.jobs for sku in job.sku_ids])
            states = [slot['state'] for row in snapshot['rows'] for slot in row['slots'].values()]
            coverage = {'status': 'verified-snapshot', 'allApproved': bool(states) and all(item == 'approved' for item in states), 'missingSlots': states.count('missing'), 'rejectedSlots': states.count('rejected'), 'pendingSlots': states.count('pending'), 'shortTitleIssueCount': len(snapshot['shortTitleIssueSkuIds']), 'otherIssues': snapshot['issueCounts']}
            if coverage['allApproved'] and delivery['status'] in {'verified', 'no-titles'}: status = 'completed-materials'
            elif coverage['pendingSlots'] and not coverage['missingSlots'] and not coverage['rejectedSlots']: status = 'waiting-review'
            elif coverage['missingSlots'] or coverage['rejectedSlots']: status = 'maintenance-incomplete'
        except Exception: pass
    if external_images['blocked'] or repair_result['status'] == 'repair-incomplete':
        status = 'maintenance-incomplete'
    return {'status': status, 'coverage': coverage, 'externalImages': external_images, 'rejectedRepairs': repair_result, 'batchImageHandoff': batch_image_handoff, 'source': str(source_path), 'skuCount': len(prepared.rows), 'spuCount': len(prepared.jobs), 'batches': batch_payloads, 'browserRequired': browser_required, 'bindingConfirmation': binding_confirmation, 'planReused': plan_reused, 'verificationMode': verification_mode, 'manualVerificationRequired': verification_mode == 'submit-only' or bool(batch_image_handoff), 'manualVerificationMessage': MANUAL_VERIFICATION_MESSAGE if verification_mode == 'submit-only' else ('Jingmai batch white/transparent images require submission and per-SKU audit readback' if batch_image_handoff else None), 'shortTitleFiles': delivery['shortTitleFiles'], 'shortTitleDelivery': delivery, 'productAttributes': attributes}

@exclusive_pop_run
def run_bind_external_cutouts(args) -> dict[str, Any]:
    if args.confirm != 'AUTO_MAINTAIN':
        raise ValueError('bind-external-cutouts requires --confirm AUTO_MAINTAIN before upload and binding')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assert_no_unknown_uploads(output)
    client = JdoClient(args.profile, output / '.state' / 'jdo-runtime')
    seller = client.seller_info()
    expected = cell_text(getattr(args, 'expected_shop_name', None))
    if expected and cell_text(seller.get('shopName')) != expected:
        raise JdoError('current jdo-cli shop does not match --expected-shop-name')
    if not _shop_identity(seller).get('shopName'):
        raise JdoError('bind-external-cutouts requires a verified active POP shop')
    requested_spu = cell_text(getattr(args, 'target_spu_id', None))
    prepared, _, _, _ = load_pop_auto_maintain_plan(output, seller, requested_spu)
    if requested_spu:
        prepared, _, _ = _scope_pop_discovery(prepared, {}, {}, requested_spu)
    prepared, handoff = route_jingmai_batch_images(prepared, model_cutout_images=False)
    handoff = [entry for entry in handoff if entry.get('kinds')]
    if not handoff:
        return {'status': 'no-cutout-slots', 'shopName': _shop_identity(seller)['shopName'], 'submittedSlots': [], 'skipped': [], 'failures': []}
    category_id = client.resolve_category()
    handoff_by_spu = {cell_text(entry['spuId']): entry for entry in handoff}
    all_skus = sorted({cell_text(sku_id) for entry in handoff for sku_id in entry['skuIds']})
    current_materials = _query_binding_materials(client, all_skus)
    slot_results: list[dict[str, Any]] = []
    failures: list[str] = []
    skipped: list[dict[str, Any]] = []
    submitted_pairs: list[tuple[str, int]] = []

    def slot_platform_statuses(spu_id: str, sku_ids: list[str], material_type: int) -> list[int]:
        statuses = []
        for sku_id in sku_ids:
            found = [item for item in current_materials.get(cell_text(sku_id), []) if int(item.get('materialType') or 0) == material_type and int(item.get('order') or 0) == 1]
            statuses.append(int(found[0].get('status') or 0) if found else 0)
        return statuses

    for index, rows in frozen_scope_batches(prepared, output):
        batch = _subset_prepared(prepared, rows)
        batch_dir = output / f'批次{index:03d}'
        if not batch_dir.is_dir():
            continue
        state_path = batch_dir / '.state' / 'task.json'
        ledger_path = batch_dir / '.state' / 'upload-ledger.json'
        state = _load_state(state_path)
        _bind_state(state, batch, state_path)
        ledger = _load_upload_ledger(ledger_path)
        images = batch_dir / '全部图片'
        try:
            for job in batch.jobs:
                entry = handoff_by_spu.get(job.spu_id)
                if not entry:
                    continue
                sku_ids = [cell_text(value) for value in entry['skuIds']]
                state_item = state['jobs'].setdefault(job.spu_id, {})
                uploaded_urls = dict(state_item.get('uploaded_urls') or {})
                binding_state = state_item.setdefault('material_bindings', {})
                names = image_names(job.spu_id)
                white_path = images / names['white']
                transparent_path = images / names['transparent']
                for material_type, kind, path in ((31, 'white', white_path), (36, 'transparent', transparent_path)):
                    if kind not in entry['kinds']:
                        continue
                    key = str(material_type)
                    statuses = slot_platform_statuses(job.spu_id, sku_ids, material_type)
                    if statuses and all((status in (3, 4) for status in statuses)):
                        skipped.append({'spuId': job.spu_id, 'materialType': material_type, 'reason': 'platform slot already pending or approved for every SKU'})
                        continue
                    target_skus = [sku for sku in sku_ids if not any(int(m.get('materialType') or 0) == material_type and int(m.get('order') or 0) == 1 for m in current_materials[sku])]
                    if not target_skus:
                        skipped.append({'spuId': job.spu_id, 'materialType': material_type, 'reason': 'Existing rejected slots require repair-rejected with fresh-byte provenance; no missing slot to bind'})
                        continue
                    if any(status not in (0,3,4,5) for status in statuses):
                        raise JdoWriteUncertainError('Existing slot status unknown; no external cutout write')
                    platform_rejected = False
                    previous = binding_state.get(key) or {}
                    appeal_managed = previous.get('status') == 'excluded-appeal'
                    if kind == 'transparent' and not valid_material_image(transparent_path, 'transparent') and valid_material_image(white_path, 'white'):
                        make_transparent(white_path, transparent_path)
                    if not valid_material_image(path, kind):
                        skipped.append({'spuId': job.spu_id, 'materialType': material_type, 'reason': f'{path.name} missing or invalid; generate it via the JoyAgent-image browser fallback first'})
                        continue
                    url = uploaded_urls.get(kind)
                    if not url:
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        ledger_entry = ledger['files'].get(path.name)
                        if ledger_entry and ledger_entry.get('sha256') and ledger_entry.get('sha256') != digest:
                            raise ValueError(f'uploaded filename content changed: {path.name}')
                        if ledger_entry and ledger_entry.get('status') in {'intent', 'unknown'}:
                            raise JdoWriteUncertainError(f'upload receipt unresolved: {path.name}; reconcile before resuming')
                        if ledger_entry and ledger_entry.get('status') == 'rejected':
                            failures.append(f'{path.name}: previously rejected by the shop; not retried')
                            continue
                        if ledger_entry and ledger_entry.get('url'):
                            url = ledger_entry['url']
                        else:
                            ledger_entry = {'sha256': digest, 'kind': kind, 'categoryId': int(category_id), 'status': 'intent', 'submittedAt': int(time.time())}
                            ledger['files'][path.name] = ledger_entry
                            _save_upload_ledger(ledger_path, ledger)
                            try:
                                response = client.upload_image(path, int(category_id))
                            except JdoPermissionError:
                                ledger_entry['status'] = 'rejected'
                                _save_upload_ledger(ledger_path, ledger)
                                failures.append(f'{path.name}: official permission denied')
                                continue
                            except Exception:
                                ledger_entry['status'] = 'unknown'
                                _save_upload_ledger(ledger_path, ledger)
                                raise JdoWriteUncertainError('External cutout upload result unknown; do not replay') from None
                            returned_name = cell_text(response.get('imgName'))
                            try:
                                returned_url = _jd_image_url(response.get('imgUrl'))
                            except ValueError:
                                returned_url = ''
                            if returned_name != path.name or not returned_url:
                                ledger_entry['status'] = 'unknown'
                                _save_upload_ledger(ledger_path, ledger)
                                raise JdoWriteUncertainError(f'upload result unknown: {path.name}; do not replay')
                            ledger_entry.update({'status': 'accepted', 'url': returned_url, 'receipt': {'imgName': returned_name, 'imgUrl': returned_url}})
                            url = returned_url
                            _save_upload_ledger(ledger_path, ledger)
                    uploaded_urls[kind] = url
                    state_item['uploaded_urls'] = uploaded_urls
                    body = {'skuMaterials': [{'productId': int(job.spu_id), 'skuId': int(sku_id), 'materials': [_binding_material(material_type, 1, url, sku_id)]} for sku_id in target_skus]}
                    fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
                    if previous.get('status') not in {None, 'planned', 'mismatch', 'excluded-appeal'}:
                        if previous.get('fingerprint') == fingerprint and previous.get('status') in {'submitted', 'pending', 'approved'}:
                            skipped.append({'spuId': job.spu_id, 'materialType': material_type, 'reason': 'identical binding already submitted with accepted receipt'})
                            continue
                        raise JdoWriteUncertainError(f'SPU {job.spu_id} type {material_type}: existing receipt fingerprint mismatch; reconcile before replay')
                    request = {'spuId': job.spu_id, 'materialType': material_type, 'skuIds': target_skus, 'fullSiblingSkuIds': sku_ids, 'body': body, 'fingerprint': fingerprint}
                    record = {'request': request, 'fingerprint': fingerprint, 'status': 'intent', 'chunks': [], 'updatedAt': int(time.time())}
                    if platform_rejected or appeal_managed:
                        record['reconciliation'] = {'previousStatus': 'platform-rejected' if platform_rejected else previous.get('status'), 'route': 'joyagent-cutout-fallback', 'updatedAt': int(time.time())}
                    binding_state[key] = record
                    try:
                        for group in _chunks(body['skuMaterials'], 50):
                            chunk = {'body': {**body, 'skuMaterials': list(group)}, 'status': 'intent'}
                            record['chunks'].append(chunk)
                            _save_state(state_path, state)
                            receipt = client.bind_sku_materials(chunk['body'])
                            chunk.update({'status': 'accepted', 'receipt': receipt})
                            _save_state(state_path, state)
                        record.update({'status': 'submitted', 'reason': 'submitted', 'updatedAt': int(time.time())})
                        submitted_pairs.append((job.spu_id, material_type))
                        slot_results.append({'spuId': job.spu_id, 'materialType': material_type, 'skuCount': len(target_skus), 'url': url, 'repairedRejected': bool(platform_rejected or appeal_managed)})
                    except (JdoUnavailableError, JdoWriteUncertainError):
                        record.update({'status': 'unknown', 'reason': 'transport result unknown', 'updatedAt': int(time.time())})
                        _save_state(state_path, state)
                        raise JdoWriteUncertainError('binding result unknown; stop and reconcile exact request') from None
                    finally:
                        _save_state(state_path, state)
            _save_state(state_path, state)
            _save_upload_ledger(ledger_path, ledger)
        finally:
            pass
    readback = _query_binding_materials(client, all_skus)
    pending_slots = 0
    approved_slots = 0
    missing_slots: list[dict[str, Any]] = []
    for spu_id, entry in handoff_by_spu.items():
        for material_type, kind in ((31, 'white'), (36, 'transparent')):
            if kind not in entry['kinds']:
                continue
            for sku_id in entry['skuIds']:
                found = [item for item in readback.get(cell_text(sku_id), []) if int(item.get('materialType') or 0) == material_type and int(item.get('order') or 0) == 1]
                status = int(found[0].get('status') or 0) if found else 0
                if status == 3:
                    pending_slots += 1
                elif status == 4:
                    approved_slots += 1
                else:
                    missing_slots.append({'skuId': cell_text(sku_id), 'spuId': spu_id, 'materialType': material_type, 'status': status})
    if submitted_pairs:
        status_text = 'submitted-with-failures' if failures else 'submitted-for-manual-verification'
    else:
        status_text = 'no-op-with-failures' if failures else 'no-op'
    return {'status': status_text, 'shopName': _shop_identity(seller)['shopName'], 'submittedSlots': slot_results, 'skipped': skipped, 'failures': failures, 'readback': {'pendingSkuSlots': pending_slots, 'approvedSkuSlots': approved_slots, 'missingSlots': missing_slots}, 'manualVerificationRequired': True, 'manualVerificationMessage': 'Cutout slots were uploaded and bound; platform audit is asynchronous. Read back each SKU slot before claiming completion and never present pending as approved.'}


def _short_title_workbook_bytes(rows):
    for sku_id, title in rows:
        if not valid_short_title(title):
            raise ValueError(f'SKUID {sku_id} short-title length {weighted_length(title)} is outside 16-30; Han=2, other characters=1')
    template = Path(__file__).resolve().parents[1] / 'assets' / '商品导入短标题模板.xlsx'
    namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    ET.register_namespace('', namespace)
    with zipfile.ZipFile(template) as archive:
        name = 'xl/worksheets/sheet1.xml'
        original = archive.read(name).decode('utf-8')
        sheet = ET.fromstring(original)
        data = sheet.find(f'{{{namespace}}}sheetData')
        if data is None:
            raise ValueError('official short-title template has no sheetData')
        for row in list(data):
            if int(row.attrib['r']) >= 3:
                data.remove(row)
        for index, values in enumerate(rows, 3):
            row = ET.SubElement(data, f'{{{namespace}}}row', {'r': str(index)})
            for column, value in zip(('A', 'B'), values):
                cell = ET.SubElement(row, f'{{{namespace}}}c', {'r': f'{column}{index}', 't': 'inlineStr'})
                inline = ET.SubElement(cell, f'{{{namespace}}}is')
                text = ET.SubElement(inline, f'{{{namespace}}}t')
                text.text = value
                text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        replacement = ET.tostring(data, encoding='unicode')
        updated, count = re.subn(r'<sheetData\b[^>]*>.*?</sheetData>', lambda match: replacement, original, flags=re.S)
        if count != 1:
            raise ValueError('official short-title template sheetData is ambiguous')
        updated, count = re.subn(r'<dimension\b[^>]*/>', f'<dimension ref="A1:B{len(rows) + 2}"/>', updated)
        if count != 1:
            raise ValueError('official short-title template dimension is ambiguous')
        output = BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as merged:
            for entry in archive.infolist():
                merged.writestr(entry, updated.encode('utf-8') if entry.filename == name else archive.read(entry.filename))
        return output.getvalue()

def validate_short_title_workbook(path):
    path = Path(path).resolve()
    content = path.read_bytes()
    template = Path(__file__).resolve().parents[1] / 'assets' / '商品导入短标题模板.xlsx'
    with closing(load_workbook(template, read_only=True)) as workbook:
        headers = list(workbook['Sheet1'].iter_rows(min_row=1, max_row=2, max_col=2, values_only=True))
    invalid = []
    identifiers = set()
    row_count = 0
    with closing(load_workbook(BytesIO(content), read_only=True, data_only=False)) as workbook:
        if workbook.sheetnames != ['Sheet1']:
            raise ValueError('not the official POP short-title upload worksheet')
        sheet = workbook['Sheet1']
        if list(sheet.iter_rows(min_row=1, max_row=2, max_col=2, values_only=True)) != headers:
            raise ValueError('official POP short-title upload headers or instructions changed')
        for row_number, row in enumerate(sheet.iter_rows(min_row=3, values_only=True), 3):
            if all(value is None for value in row):
                continue
            row_count += 1
            sku_id = cell_text(row[0])
            title = row[1] if len(row) > 1 else None
            reasons = []
            if not isinstance(row[0], str) or not sku_id.isascii() or not sku_id.isdigit():
                reasons.append('SKU must be exact numeric text')
            if sku_id in identifiers:
                reasons.append('duplicate SKU')
            identifiers.add(sku_id)
            if not isinstance(title, str) or not valid_short_title(title):
                reasons.append('short-title length must be 16-30; Han=2, all other characters=1')
            if any(value is not None for value in row[2:]):
                reasons.append('unexpected extra columns')
            if reasons:
                invalid.append({'row': row_number, 'skuId': sku_id, 'shortTitle': title, 'length': weighted_length(title), 'reasons': reasons})
    return {'path': str(path), 'sha256': hashlib.sha256(content).hexdigest(), 'valid': bool(row_count) and row_count <= POP_SHORT_TITLE_MAX_ROWS and not invalid, 'rowCount': row_count, 'uniqueSkuCount': len(identifiers), 'rowLimit': POP_SHORT_TITLE_MAX_ROWS, 'invalidRows': invalid, 'lengthRule': '16-30; Han=2, all other characters=1', 'platformImportPerformed': False}

def export_short_title_delivery(runs, output_dir, *, shop_name):
    output = Path(output_dir).resolve()
    shop_name = cell_text(shop_name)
    safe_shop_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', shop_name).strip(' .')
    if not safe_shop_name:
        raise ValueError('short-title delivery requires the confirmed shop name')
    expected = []
    values = {}
    sources = []
    signatures = []
    template = Path(__file__).resolve().parents[1] / 'assets' / '商品导入短标题模板.xlsx'
    with closing(load_workbook(template, read_only=True)) as workbook:
        headers = list(workbook['Sheet1'].iter_rows(min_row=1, max_row=2, max_col=2, values_only=True))
    for prepared, directory in runs:
        if prepared.source_type != 'jdo-pop':
            raise ValueError('short-title delivery requires a frozen POP scope')
        directory = Path(directory).resolve()
        signatures.append(_task_signature(prepared))
        expected.extend(sku for job in prepared.jobs for sku in job.short_title_sku_ids)
        for index, rows in frozen_scope_batches(prepared, output):
            batch = _subset_prepared(prepared, rows)
            batch_dir = directory / f'批次{index:03d}'
            state_path = batch_dir / '.state/task.json'
            if not state_path.is_file():
                continue
            state = _load_state(state_path)
            allowed_signatures = {_task_signature(batch), _task_signature(route_jingmai_batch_images(batch)[0])}
            if state.get('task_signature') not in allowed_signatures or state.get('business_mode') != 'pop':
                raise ValueError('short-title source task signature or business mode mismatch')
            state_rows = []
            for job in batch.jobs:
                titles = state.get('jobs', {}).get(job.spu_id, {}).get('short_titles', {})
                state_rows.extend((sku, titles[sku]) for sku in job.short_title_sku_ids if valid_short_title(titles.get(sku)))
            path = batch_dir / '商品导入短标题模板_已回填.xlsx'
            if not path.is_file():
                if state_rows:
                    raise ValueError('short-title source workbook is missing; preserve state and repair local output')
                continue
            content = path.read_bytes()
            with closing(load_workbook(BytesIO(content), read_only=True, data_only=False)) as workbook:
                if workbook.sheetnames != ['Sheet1']:
                    raise ValueError('short-title source worksheet mismatch')
                sheet = workbook['Sheet1']
                if list(sheet.iter_rows(min_row=1, max_row=2, max_col=2, values_only=True)) != headers:
                    raise ValueError('short-title source headers mismatch')
                actual = []
                for row in sheet.iter_rows(min_row=3, values_only=True):
                    if all(value is None for value in row):
                        continue
                    if len(row) < 2 or not isinstance(row[0], str) or any(value is not None for value in row[2:]):
                        raise ValueError('short-title source rows must contain exact text SKU and title')
                    actual.append((row[0], row[1]))
                if actual != state_rows:
                    raise ValueError('short-title workbook differs from frozen task values or SKU order')
            for sku, title in actual:
                if sku in values:
                    raise ValueError('duplicate SKU across short-title sources; do not silently deduplicate')
                values[sku] = title
            sources.append({'path': str(path), 'sha256': hashlib.sha256(content).hexdigest(), 'statePath': str(state_path), 'stateSha256': _file_sha256(state_path)})
    if len(set(expected)) != len(expected):
        raise ValueError('duplicate SKU in frozen short-title scopes')
    missing = [sku for sku in expected if sku not in values]
    rows = [(sku, values[sku]) for sku in expected if sku in values]
    fingerprint = hashlib.sha256(json.dumps({'shopName': shop_name, 'signatures': signatures, 'rows': rows}, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    groups = list(_chunks(rows, POP_SHORT_TITLE_MAX_ROWS))
    planned_files = []
    for index, group in enumerate(groups, 1):
        suffix = f'_{index:03d}' if len(groups) > 1 else ''
        path = output / f'{safe_shop_name}_短标题维护表_{len(group)}SKU_{fingerprint[:16]}{suffix}.xlsx'
        content = _short_title_workbook_bytes(group)
        if path.exists() and path.read_bytes() != content:
            raise ValueError('existing short-title delivery was modified; do not overwrite user changes')
        planned_files.append((path, content))
    output.mkdir(parents=True, exist_ok=True)
    for path, content in planned_files:
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(content)
    files = [str(path) for path, _ in planned_files]
    for path in files:
        if not validate_short_title_workbook(path)['valid']:
            raise ValueError('final short-title workbook validation failed; do not deliver this file')
    message = '短标题表已生成；离线导出不证明已导入，请由自动导入流程核对任务回执：\n' + '\n'.join(files) if files else '没有可交付的短标题文件；缺失SKU保持待处理。'
    if missing:
        message += f'\n另有{len(missing)}个计划SKU缺少短标题，不计为完成。'
    result = {'status': 'partial-titles' if missing else 'ready-for-import' if rows else 'no-titles', 'shortTitleFiles': files, 'rowCount': len(rows), 'plannedRowCount': len(expected), 'missingSkuIds': missing, 'splitReason': '官方POP短标题模板每份最多10000行' if len(groups) > 1 else None, 'deliveryMessage': message, 'manualImportRequired': False, 'sources': sources, 'fingerprint': fingerprint, 'files': [{'path': str(path), 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)} for path, content in planned_files]}
    _save_state(output / '.state' / f'short-title-delivery-{fingerprint}.json', result)
    return result

@exclusive_pop_run
def run_deliver_short_titles(args):
    output = Path(args.output_dir).resolve()
    directories = [Path(path).resolve() for path in args.run_dir]
    if len(set(directories)) != len(directories):
        raise ValueError('duplicate source run directory')
    runs = []
    identity = None
    with ExitStack() as stack:
        for directory in sorted(directories):
            if not (directory / AUTO_MAINTAIN_PLAN_NAME).is_file():
                raise ValueError('source run has no frozen POP plan')
            if directory != output:
                stack.enter_context(pop_execution_lock(directory))
        for directory in directories:
            payload = json.loads((directory / AUTO_MAINTAIN_PLAN_NAME).read_text(encoding='utf-8'))
            seller = _shop_identity(payload.get('shopIdentity') or {})
            if seller['shopName'] != args.expected_shop_name or (identity is not None and seller != identity):
                raise ValueError('short-title source shop identity mismatch')
            identity = seller
            prepared, _, _, _ = load_pop_auto_maintain_plan(directory, seller, payload.get('targetSpuId'))
            runs.append((prepared, directory))
        return {**export_short_title_delivery(runs, output, shop_name=identity['shopName']), 'shopIdentity': identity}

def _prepared_from_args(args) -> PreparedSource:
    return prepare_standard_source(args.source[0], getattr(args, 'sheet', None))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='京东商品素材 Agent 无插件本地运行时')
    sub = parser.add_subparsers(dest='command', required=True)
    prepare_cutout = sub.add_parser('prepare-cutout', help='Verify/cache pinned local segmentation weights before business execution')
    prepare_cutout.add_argument('--model', choices=('birefnet-general-lite', 'birefnet-general'), default='birefnet-general-lite')
    prepare_cutout.add_argument('--download', action='store_true')
    local_cutout = sub.add_parser('cutout-local', help='Offline PNG alpha extraction; no merchant writes')
    local_cutout.add_argument('--source', type=Path, required=True)
    local_cutout.add_argument('--output', type=Path, required=True)
    local_cutout.add_argument('--model', choices=('birefnet-general-lite', 'birefnet-general'), default='birefnet-general-lite')
    local_cutout.add_argument('--alpha-matting', action='store_true')
    audit = sub.add_parser('audit-pop-coverage')
    audit.add_argument('--detail',action='store_true',help='仅维护者需要完整技术字段时使用；普通回查返回计数与报告路径。')
    audit.add_argument('--profile', required=True)
    audit.add_argument('--expected-shop-name', required=True)
    audit.add_argument('--title-workbook', nargs='*', type=Path, default=[])
    audit.add_argument('--output-dir', required=True, type=Path)
    reconcile = sub.add_parser('reconcile-receipts')
    reconcile.add_argument('--output-dir', required=True, type=Path)
    reconcile.add_argument('--profile')
    validate_titles = sub.add_parser('validate-short-titles')
    validate_titles.add_argument('--source', required=True, type=Path)
    deliver = sub.add_parser('deliver-short-titles')
    deliver.add_argument('--run-dir', required=True, nargs='+', type=Path)
    deliver.add_argument('--output-dir', required=True, type=Path)
    deliver.add_argument('--expected-shop-name', required=True)
    inspect = sub.add_parser('inspect-source')
    inspect.add_argument('--source', nargs='+', required=True, type=Path)
    inspect.add_argument('--business-mode', choices=('pop',), default='pop')
    inspect.add_argument('--sheet')
    split = sub.add_parser('split-source')
    split.add_argument('--source', nargs='+', required=True, type=Path)
    split.add_argument('--business-mode', choices=('pop',), default='pop')
    split.add_argument('--sheet')
    split.add_argument('--output-dir', required=True, type=Path)
    generate = sub.add_parser('generate')
    generate.add_argument('--source', nargs='+', required=True, type=Path)
    generate.add_argument('--business-mode', choices=('pop',), default='pop')
    generate.add_argument('--sheet')
    generate.add_argument('--reference-dir', required=True, type=Path)
    generate.add_argument('--output-dir', required=True, type=Path)
    generate.add_argument('--spu-concurrency', type=int, default=5)
    generate.add_argument('--image-concurrency', type=int)
    generate.add_argument('--timeout', type=float, default=600)
    generate.add_argument('--existing-url-export', nargs='+', type=Path, default=[])
    generate.add_argument('--agent-text-file', type=Path)
    generate.add_argument('--scene-model', help='Scene-only override; default six eligible channels (five-model pool + Oxygen-Product-Pro). Product-Pro is scene/selling-only, forbidden for cutouts.')
    generate.add_argument('--image-model', help='Non-scene override; default white=five-model pool, selling=six-channel pool. Product-Pro must never be selected for white/transparent.')
    generate.add_argument('--text-model', help='网关文本模型显式 opt-in；默认不调用网关文本，文本由 agent 按 SKILL 规则自拟并通过 --agent-text-file 注入。')
    fill = sub.add_parser('fill-template')
    fill.add_argument('--manifest', required=True, type=Path)
    fill.add_argument('--url-export', required=True, nargs='+', type=Path)
    fill.add_argument('--output', required=True, type=Path)
    fill.add_argument('--template', type=Path)
    plan_auto = sub.add_parser('plan-auto-maintain')
    plan_auto.add_argument('--business-mode', choices=('pop',), default='pop')
    plan_auto.add_argument('--output-dir', required=True, type=Path)
    plan_auto.add_argument('--profile')
    plan_auto.add_argument('--expected-shop-name')
    plan_auto.add_argument('--target-spu-id')
    plan_auto.add_argument('--exclude-spu-id', action='append', default=[], help='用户明确不维护的SPU，可重复；不进入计划、驳回修复和属性补齐。')
    plan_auto.add_argument('--refresh', action='store_true')
    plan_auto.add_argument('--include-full-score', action='store_true', help='对信息分90+的SPU也直查8类素材槽缺口；已达标短标题不重生。')
    plan_auto.add_argument('--include-off-shelf-spu', action='append', default=[], help='把指定已下架 SPU 也纳入计划（按商品编码显式确认，不走在售发现）。')
    generate_auto = sub.add_parser('generate-auto-maintain')
    generate_auto.add_argument('--business-mode', choices=('pop',), default='pop')
    generate_auto.add_argument('--output-dir', required=True, type=Path)
    generate_auto.add_argument('--profile')
    generate_auto.add_argument('--expected-shop-name')
    generate_auto.add_argument('--target-spu-id')
    generate_auto.add_argument('--confirm', required=True)
    generate_auto.add_argument('--spu-concurrency', type=int, default=5)
    generate_auto.add_argument('--image-concurrency', type=int)
    generate_auto.add_argument('--timeout', type=float, default=600)
    generate_auto.add_argument('--agent-text-file', type=Path)
    generate_auto.add_argument('--scene-model', help='Scene-only override; default six eligible channels (five-model pool + Oxygen-Product-Pro). Product-Pro is scene/selling-only, forbidden for cutouts.')
    generate_auto.add_argument('--image-model', help='Non-scene override; default white=five-model pool, selling=six-channel pool. Product-Pro must never be selected for white/transparent.')
    generate_auto.add_argument('--text-model', help='网关文本模型显式 opt-in；默认不调用网关文本，文本由 agent 按 SKILL 规则自拟并通过 --agent-text-file 注入。')
    generate_auto.add_argument('--model-cutout-images', action='store_true', default=True, help='生成白底图并本地衍生透明图（默认开启）；失败的槽位写入 batchImageHandoff 交京麦批量图兜底。')
    generate_auto.add_argument('--reference-override', action='append', default=[], help='按 SPU 覆盖参考图，格式 SPUID=本地图片路径；用于主图含人物/道具时改用裁好的纯商品图。')
    generate_auto.add_argument('--batch-image-handoff', action='store_true', help='跳过模型白底/透明，全部交京麦批量图（原默认行为）。')
    attrs = sub.add_parser('plan-missing-attrs', help='Inventory missing category attributes (product detail x category schema); read-only')
    attrs.add_argument('--profile', required=True)
    attrs.add_argument('--expected-shop-name', required=True)
    attrs.add_argument('--output-dir', type=Path, required=True)
    attrs.add_argument('--no-model', action='store_true', help='Disable current-key text-model inference for options not inferable by rules')
    attrs.add_argument('--origin', help='Explicit 产地 area ids, e.g. 15,1262 (province,city); otherwise same-shop majority')
    attrs.add_argument('--agent-attrs-file', type=Path)
    attrs.add_argument('--product-id', action='append', default=[])
    complete = sub.add_parser('complete-product-attrs', help='Submit planned CategoryGroupList patches and verify via product-apply readback')
    complete.add_argument('--profile', required=True)
    complete.add_argument('--expected-shop-name', required=True)
    complete.add_argument('--output-dir', type=Path, required=True)
    complete.add_argument('--confirm', required=True)
    complete.add_argument('--product-id', action='append', default=[], help='Limit to planned productIds (canary)')
    repair = sub.add_parser('repair-rejected', help='Fresh-byte per-SKU image repair with exact durable receipts')
    repair.add_argument('--profile', required=True)
    repair.add_argument('--expected-shop-name', required=True)
    repair.add_argument('--output-dir', type=Path, required=True)
    repair.add_argument('--confirm', required=True)
    repair.add_argument('--image-concurrency', type=int, default=20)
    repair.add_argument('--timeout', type=float, default=180)
    repair.add_argument('--joyagent-adapter', type=Path)
    repair.add_argument('--reference-override', action='append', default=[], help='SKUID=trusted-local-product-image')
    repair.add_argument('--max-model-requests',type=int,help='本次已批准的模型请求上限；包含失败响应/质量重试，不是最终扣费。')
    repair.add_argument('--repair-kind',action='append',choices=tuple(IMAGE_SUFFIXES),help='仅修这些类型的已驳回槽位，可重复；付费修复必须显式指定。')
    repair.add_argument('--paid-generation',action=argparse.BooleanOptionalAction,default=False,help='默认只走免费路径/申诉；另获本次费用批准后显式开启模型修复。')
    repair.add_argument('--profile-dir', help='Own shop Chrome profile; enables Jingmai batch cutout first for rejected white/transparent')
    repair.add_argument('--jingmai-first', action=argparse.BooleanOptionalAction, default=True)
    repair.add_argument('--jingmai-ledger', type=Path)
    repair.add_argument('--exclude-spu-id', dest='excluded_spu_ids', action='append', default=[], help='用户明确不维护的SPU，可重复。')
    auto = sub.add_parser('auto-maintain')
    auto.add_argument('--business-mode', choices=('pop',), default='pop')
    auto.add_argument('--output-dir', type=Path)
    auto.add_argument('--category-id', type=int)
    auto.add_argument('--category-name')
    auto.add_argument('--profile')
    auto.add_argument('--expected-shop-name')
    auto.add_argument('--confirm', required=True)
    auto.add_argument('--upload-mode', choices=('auto', 'cli', 'browser'), default='auto')
    auto.add_argument('--profile-dir', type=Path, help='Own verified shop Chrome user-data directory; required for automatic title import/batch fallback')
    auto.add_argument('--title-poll-seconds', type=int, default=60)
    auto.add_argument('--joyagent-adapter', type=Path)
    auto.add_argument('--complete-attrs', action=argparse.BooleanOptionalAction, default=True, help='Inventory and complete missing category attributes after materials/titles')
    auto.add_argument('--agent-attrs-file', type=Path, help='Host-evidenced legal attribute choices, no external model call')
    auto.add_argument('--max-repair-model-requests',type=int,help='本次已批准的驳回修复模型请求上限，不影响普通新图。')
    auto.add_argument('--repair-kind',action='append',choices=tuple(IMAGE_SUFFIXES),help='仅限制驳回修复类型，不扩大原冻结范围。')
    auto.add_argument('--paid-repairs',action=argparse.BooleanOptionalAction,default=False,help='默认驳回修复免费；本次额外修复范围/费用已批准才开启。普通新素材费用独立。')
    auto.add_argument('--repair-rejected', action=argparse.BooleanOptionalAction, default=True, help='One bounded fresh-byte repair pass; disable only for a frozen legacy scope')
    auto.add_argument('--verification-mode', choices=('submit-only', 'strict'), default='submit-only')
    auto.add_argument('--spu-concurrency', type=int, default=50)
    auto.add_argument('--image-concurrency', type=int, default=20)
    auto.add_argument('--timeout', type=float, default=600)
    auto.add_argument('--target-spu-id')
    auto.add_argument('--exclude-spu-id', action='append', default=[], help='用户明确不维护的SPU，可重复；不进入计划、驳回修复和属性补齐。')
    auto.add_argument('--include-full-score', action='store_true', help='无冻结计划时对信息分90+的SPU也直查素材缺口。')
    auto.add_argument('--include-off-shelf-spu', action='append', default=[], help='无冻结计划时把指定已下架 SPU 也纳入维护（按商品编码显式确认）。')
    auto.add_argument('--reference-override', action='append', default=[], help='按 SPU 覆盖参考图，格式 SPUID=本地图片路径；用于主图含人物/道具时改用裁好的纯商品图。')
    auto.add_argument('--exclude-binding', action='append', default=[], help='字段级排除绑定，格式 SPUID:素材类型(31/32/33/36/1002)；用于已人工申诉接管的驳回槽位，整槽不重绑。')
    auto.add_argument('--skip-transparent', action='store_true', default=False)
    auto.add_argument('--agent-text-file', type=Path)
    auto.add_argument('--scene-model', help='Scene-only override; default six eligible channels (five-model pool + Oxygen-Product-Pro). Product-Pro is scene/selling-only, forbidden for cutouts.')
    auto.add_argument('--image-model', help='Non-scene override; default white=five-model pool, selling=six-channel pool. Product-Pro must never be selected for white/transparent.')
    auto.add_argument('--text-model', default='agent', help='auto: discover/probe current-key text models and generate in a shared20 request pool; agent: agent-text-file only; explicit model: legacy opt-in single route')
    auto.add_argument('--model-cutout-images', action='store_true', default=True, help='生成白底图并本地衍生透明图（默认开启）；失败的槽位写入 batchImageHandoff 交京麦批量图兜底。')
    auto.add_argument('--batch-image-handoff', action='store_true', help='跳过模型白底/透明，全部交京麦批量图（原默认行为）。')
    cutouts = sub.add_parser('bind-external-cutouts')
    cutouts.add_argument('--business-mode', choices=('pop',), default='pop')
    cutouts.add_argument('--output-dir', required=True, type=Path)
    cutouts.add_argument('--profile')
    cutouts.add_argument('--expected-shop-name')
    cutouts.add_argument('--target-spu-id')
    cutouts.add_argument('--confirm', required=True)
    sub.add_parser('provider-info')
    return parser

def _unknown_write_payload(args) -> dict[str, Any]:
    output = str(Path(args.output_dir).resolve())
    command = f'python scripts/merchant.py run materials -- reconcile-receipts --output-dir "{output}"'
    profile = cell_text(getattr(args, 'profile', None))
    if profile:
        command += f' --profile {profile}'
    return {'status': 'paused-unknown-write',
            'nextAction': '部分写入结果未确认；保留原任务和回执，先执行恢复命令核对，不要重复提交。',
            'recoveryCommand': command}

def audit_cli_summary(payload,estimate,report,delivery):
    summary={'status':'audited','message':'只读回查完成，未执行修复或付费；完整明细在原报告。',
             'resultFile':str(report),'report':str(report),'issueCounts':payload.get('issueCounts',{}),
             'generationEstimate':{k:v for k,v in estimate.items() if not isinstance(v,(list,dict))},
             'sourceIssueCount':len(estimate.get('sourceIssues') or []),'appealFiles':delivery.get('appealFiles',[])}
    for key in ('onlineProductCount','onlineSkuCount','allSiblingSkuCount','healthSkuCount'):
        if key in payload:summary[key]=payload[key]
    for key in ('materialDeficitSkuIds','rejectedSkuIds','pendingSkuIds','shortTitleIssueSkuIds','unscoredSkuIds','manualAppealSkuIds'):
        if isinstance(payload.get(key),list):summary[key+'Count']=len(payload[key])
    return summary


def merchant_result_summary(payload, output_dir, command):
    from pop_safety import atomic_json
    from heideng_merchant.safety import redact
    path = Path(output_dir).resolve()/'.state'/('merchant-result-'+command+'.json')
    atomic_json(path, redact(payload))
    keys = ('status','skuCount','spuCount','noPaidGeneration','remainingImageSlotCount','manualAppealRequired','browserRequired','planReused','verificationMode','manualVerificationRequired','manualVerificationMessage')
    summary = {key: payload[key] for key in keys if key in payload}
    from heideng_merchant.merchant_experience import task_summary
    summary.update(task_summary(payload))
    summary['resultFile'] = str(path)
    for key in ('assetGroupCount','failedAssetGroupCount','submittedSkuSlotCount','liveReusedSkuSlotCount'):
        if key in payload:summary[key]=payload[key]
    stats=payload.get('modelStats') or {}
    if isinstance(stats,dict) and isinstance(stats.get('attempts'),dict):summary['modelRequestAttemptCount']=sum(stats['attempts'].values())
    for key in ('batches','rows','reconciledUploads','reconciledBindings','unresolvedUploads','unresolvedBindings'):
        if isinstance(payload.get(key), list):summary[key+'Count'] = len(payload[key])
    for key in ('coverage','externalImages','rejectedRepairs','shortTitleDelivery','productAttributes'):
        detail = payload.get(key)
        if isinstance(detail, dict):summary[key] = {k:v for k,v in detail.items() if k=='status' or (isinstance(v,(int,bool)) and not isinstance(v,str))}
    return summary


def main(argv: list[str] | None=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, 'batch_image_handoff', False):
        args.model_cutout_images = False
    if args.command == 'prepare-cutout':
        from pop_cutout import prepare_model
        print(json.dumps(prepare_model(args.model, download=args.download), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'cutout-local':
        from pop_cutout import make_cutout, CutoutConfig
        print(json.dumps(make_cutout(args.source, args.output, config=CutoutConfig(args.model, args.alpha_matting)), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'provider-info':
        print(json.dumps({**asdict(PROVIDER), 'variant': VARIANT_ID, 'skillVersion': SKILL_VERSION}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'fill-template':
        print(fill_material_template(args.manifest, args.url_export, args.output, args.template))
        return 0
    if args.command == 'deliver-short-titles':
        payload = run_deliver_short_titles(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if payload['missingSkuIds'] else 0
    if args.command == 'audit-pop-coverage':
        client = JdoClient(args.profile, args.output_dir / '.state' / 'jdo-runtime')
        payload = audit_pop_coverage(client, args.expected_shop_name, args.title_workbook)
        report = args.output_dir.resolve() / 'POP全量覆盖核验.json'
        _save_state(report, payload)
        delivery = export_pop_image_appeals(payload, args.output_dir)
        estimate=audit_generation_summary(report)
        _save_state(report,{**payload,'generationEstimate':estimate})
        result={**payload,'appealFiles':delivery['appealFiles'],'generationEstimate':estimate,'report':str(report)} if args.detail else audit_cli_summary(payload,estimate,report,delivery)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    if args.command == 'reconcile-receipts':
        client = JdoClient(args.profile, args.output_dir / '.state' / 'jdo-runtime')
        payload = reconcile_run_receipts(client, args.output_dir)
        print(json.dumps(merchant_result_summary(payload,args.output_dir,args.command), ensure_ascii=False, indent=2))
        return 0 if not payload['unresolvedUploads'] and not payload['unresolvedBindings'] else 2
    if args.command == 'validate-short-titles':
        payload = validate_short_title_workbook(args.source)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload['valid'] else 2
    if args.command == 'plan-auto-maintain':
        payload = run_plan_auto_maintain(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'generate-auto-maintain':
        try:
            payload = run_generate_auto_maintain(args)
        except JdoWriteUncertainError:
            print(json.dumps(_unknown_write_payload(args), ensure_ascii=False))
            return 3
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload['status'] == 'generated-local' else 2
    if args.command in {'plan-missing-attrs', 'complete-product-attrs'}:
        import pop_attrs
        output = Path(args.output_dir);output.mkdir(parents=True, exist_ok=True)
        client = JdoClient(args.profile, output / '.state' / 'jdo-runtime')
        identity = _shop_identity(client.seller_info())
        if identity['shopName'] != args.expected_shop_name:
            raise ValueError('Shop identity mismatch; no attribute work performed')
        plan_path = output / 'attr-plan.json'
        if args.command == 'plan-missing-attrs':
            pool = None
            try:plan = pop_attrs.inventory(client, identity, origin=args.origin, text_pool=pool, skip_attrs=pop_attrs.platform_broken_attrs(output), product_ids=args.product_id or None, agent_choices=pop_attrs.load_agent_choices(args.agent_attrs_file))
            finally:
                if pool is not None:pool.close()
            pop_attrs._save(plan_path, plan)
            print(json.dumps({key: plan[key] for key in ('productCount', 'categoryCount', 'missingProductCount', 'originDefaults')} | {'planned': len(plan['plans']), 'needsConfirmation': len(plan['needsConfirmation']), 'blocked': len(plan['blocked']), 'plan': str(plan_path)}, ensure_ascii=False, indent=2))
            return 0
        if args.confirm != 'AUTO_MAINTAIN':
            raise ValueError('complete-product-attrs requires --confirm AUTO_MAINTAIN')
        if json.loads(plan_path.read_text(encoding='utf-8'))['shopIdentity'] != identity:
            raise ValueError('Attribute plan belongs to another shop')
        summary = pop_attrs.submit_and_verify(client, plan_path, product_ids=args.product_id or None)
        print(json.dumps({key: value for key, value in summary.items() if key != 'results'}, ensure_ascii=False, indent=2))
        return 0 if summary['allVerified'] else 2
    if args.command == 'repair-rejected':
        from pop_repair import run_rejected_repairs
        payload = run_rejected_repairs(args, sys.modules[__name__])
        print(json.dumps(merchant_result_summary(payload,args.output_dir,args.command), ensure_ascii=False, indent=2))
        return 0 if payload['status'] in {'no-rejections', 'repairs-submitted-awaiting-review'} else 2
    if args.command == 'auto-maintain':
        try:
            payload = run_auto_maintain(args)
        except JdoWriteUncertainError:
            print(json.dumps(_unknown_write_payload(args), ensure_ascii=False))
            return 3
        print(json.dumps(merchant_result_summary(payload,args.output_dir,args.command), ensure_ascii=False, indent=2))
        return 2 if payload['status'] == 'maintenance-incomplete' or payload['browserRequired'] or payload.get('shortTitleDelivery', {'status': 'no-titles' if payload['status'] == 'no-work' else 'unknown'})['status'] not in {'verified', 'no-titles'} else 0
    if args.command == 'bind-external-cutouts':
        try:
            payload = run_bind_external_cutouts(args)
        except JdoWriteUncertainError:
            print(json.dumps(_unknown_write_payload(args), ensure_ascii=False))
            return 3
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload['status'] in {'submitted-for-manual-verification', 'no-op', 'no-cutout-slots'} else 2
    prepared = _prepared_from_args(args)
    if args.command == 'inspect-source':
        print(json.dumps({'sourceType': prepared.source_type, 'sheet': prepared.sheet_name, 'rows': len(prepared.rows), 'spus': len(prepared.jobs), 'filteredRows': prepared.filtered_rows, 'duplicateRows': prepared.duplicate_rows, 'splitSpuCounts': [len({row.spu_id for row in chunk}) for chunk in split_rows_by_spu(prepared.rows)]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'split-source':
        for path in write_split_sources(prepared, args.output_dir):
            print(path.resolve())
        return 0
    result = generate_batch(prepared, args.reference_dir, args.output_dir, spu_concurrency=args.spu_concurrency, image_concurrency=args.image_concurrency, timeout=args.timeout, existing_url_exports=args.existing_url_export, agent_text=load_agent_text(args.agent_text_file) if getattr(args, 'agent_text_file', None) else None, scene_image_model=getattr(args, 'scene_model', None), image_model=getattr(args, 'image_model', None), text_model=getattr(args, 'text_model', None))
    payload = asdict(result)
    for key in ('output_dir', 'manifest_path', 'short_title_path', 'failure_path'):
        payload[key] = str(payload[key]) if payload[key] else None
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.completed_spus else 2
if __name__ == '__main__':
    raise SystemExit(main())
