#!/usr/bin/env python3
"""POP 店铺后台浏览器任务：短标题导入、京麦批量抠图。

只复用店铺自己的浏览器配置。后台任务最小化启动，保留正常的桌面窗口位置。
"""
import argparse
import json
import sys
import re
import hashlib
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit, urlunsplit
from pathlib import Path
from pop_title_dispatch import batch_receipt_path, completed_batch, submit_title_batches, submit_title_source

WARE_LIST_URL = 'https://wares-jdm.jd.com/ware/wareList?activeTab=OnsaleWare&businessModel=0'
MATERIAL_URL = 'https://wares-jdm.jd.com/ware/wareList/materialCenter/materialScene?activeTab=OnsaleWare&businessModel=0'


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit('需要 Playwright：python -m pip install playwright && python -m playwright install chromium') from error
    return sync_playwright


def browser_profile_lock(profile_dir):
    from heideng_merchant.state import FileLock, merchant_home

    identity = hashlib.sha256(str(Path(profile_dir).resolve()).encode('utf-8')).hexdigest()
    return FileLock(merchant_home() / 'browser-locks' / f'{identity}.lock', timeout=45)


def _open(playwright, profile_dir: str, viewport=(1600, 950)):
    from heideng_merchant.mature_runtime import browser_profile_channel
    channel = browser_profile_channel(profile_dir)
    return playwright.chromium.launch_persistent_context(
        profile_dir, channel=channel, headless=False,
        args=['--profile-directory=Default', '--no-first-run', '--start-minimized'],
        viewport={'width': viewport[0], 'height': viewport[1]},
    )


def _save_receipt(path, value):
    from pop_safety import atomic_json
    atomic_json(path, value)

def short_title_drawer(page):
    return page.locator('[class*=drawer]').filter(has_text='创建导入任务').filter(visible=True).first


def parse_short_title_task(text, expected_rows, task_id=None):
    ids = re.findall(r'(?<!\d)\d{6,}(?!\d)', text)
    found = task_id if task_id and task_id in ids else ids[0] if not task_id and ids else None
    if not found:
        return {'status': 'unknown', 'taskId': task_id, 'successRows': 0, 'failedRows': 0}
    success = re.search(r'成功\s*[：:]?\s*(\d+)', text)
    failed = re.search(r'失败\s*[：:]?\s*(\d+)', text)
    count = int(success.group(1)) if success else 0
    failures = int(failed.group(1)) if failed else 0
    done = any(word in text for word in ('已完成', '已结束', '全部失败', '部分失败', '执行失败'))
    status = 'import-pending'
    if done:
        status = 'import-failed' if failures or count != expected_rows else 'import-completed'
    return {'status': status, 'taskId': found, 'taskFinished':done, 'successRows': count, 'failedRows': failures}


def created_task_id(value):
    """Only actual instance-ID fields from the accepted create response; never generic jobId."""
    found=set()
    def visit(x):
        if isinstance(x,dict):
            for key in ('taskId','taskInstanceId','batchJobId','jobInstanceId','jobExecId'):
                if re.fullmatch(r'\d{6,}',str(x.get(key,''))):found.add(str(x[key]))
            for child in x.values():visit(child)
        elif isinstance(x,list):
            for child in x:visit(child)
    visit(value)
    return next(iter(found)) if len(found)==1 else None

def source_identifier(value):
    """Hash only the uploaded object identity, never persist a credential-bearing URL."""
    if not isinstance(value,str):return None
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.netloc:return None
    normalized=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def upload_source_identifiers(value):
    hashes=set()
    def visit(x):
        if isinstance(x,str):
            digest=source_identifier(x)
            if digest:hashes.add(digest)
        elif isinstance(x,dict):
            for k,v in x.items():
                if k in {'data','url','fileUrl','filePath','path','result'}:visit(v)
        elif isinstance(x,list):
            for v in x:visit(v)
    visit(value)
    return sorted(hashes)

def recover_backend_task(rows,upload_hashes,created_at):
    found=set()
    for row in rows:
        digest=source_identifier(row.get('jobExecFileSrc'))
        if digest not in upload_hashes:continue
        stamp=row.get('jobExecTimeStart')
        try:
            stamp=float(stamp)
            if stamp>100000000000:stamp/=1000
        except (TypeError,ValueError):
            try:stamp=datetime.strptime(str(stamp),'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
            except ValueError:continue
        if not -5<=stamp-created_at<=120:continue
        task=created_task_id(row)
        if task:found.add(task)
    return next(iter(found)) if len(found)==1 else None

def recover_import_task(rows,filename,created_at):
    """Recovery requires file identity AND creation window, not a newly visible numeric ID."""
    found=set()
    for text in rows:
        if not re.search(r'(?<![\w.-])'+re.escape(filename)+r'(?![\w.-])',text):continue
        date=re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',text)
        if not date:continue
        stamp=datetime.strptime(date.group(),'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
        if not 0<=stamp-created_at<=120:continue
        ids=re.findall(r'(?<!\d)\d{6,}(?!\d)',text)
        if len(ids)==1:found.add(ids[0])
    return next(iter(found)) if len(found)==1 else None

def _official_host(url, hosts):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None,443) and parsed.hostname in hosts)
    except (TypeError,ValueError):
        return False


def _identity_method(url):
    if not _official_host(url, {'api.m.jd.com','sff.jd.com','wares-jdm.jd.com','jingmai.jd.com'}):
        return None
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    # On the JD RPC transport, method identifies the operation; functionId may
    # separately identify the gateway. Never match arbitrary query parameter values.
    identifiers = query.get('method',[]) or query.get('functionId',[])
    if identifiers and parsed.path not in ('/api', '/api/', '/'):
        return None
    if not identifiers:
        identifiers = [parsed.path.rstrip('/').rsplit('/',1)[-1]]
    if len(identifiers) != 1:
        return None
    method = identifiers[0]
    if method == 'gmall.vender.data.get':
        return 'vendor-identity'
    if any(part in ('VenderIdentityViewService','LoginFacadeService') for part in method.split('.')):
        return 'current-shop-envelope'
    return None


def _current_shop_pair(payload, method):
    if not isinstance(payload,dict) or payload.get('success') is False or payload.get('code',200) not in (200,'200',0,'0'):
        return None
    body = payload.get('data',payload)
    if not isinstance(body,dict):
        return None
    # Explicit current identity objects only. A product row or a member of a shops list
    # can describe a different store and cannot establish the active account.
    records = [body.get('currentShop'),body.get('currentShopInfo')]
    if method == 'vendor-identity':
        records.extend([body,body.get('shopBaseInfo')])
    pairs = set()
    for item in records:
        if not isinstance(item,dict) or 'shopId' not in item or 'shopName' not in item:
            continue
        sid, name = item['shopId'], item['shopName']
        if type(sid) not in (str,int) or not re.fullmatch('[0-9]+',str(sid)) or not isinstance(name,str) or not name:
            return None
        pairs.add((str(sid),name))
    return pairs.pop() if len(pairs) == 1 else None


def _has_shop_identity(page, evidence):
    return (evidence.get('name') is True and evidence.get('id') is True and not evidence.get('conflict')
            and _official_host(page.url, {'wares-jdm.jd.com'}) and 'login' not in page.url.lower())


def _observe_identity(page, expected_shop_name, expected_shop_id):
    if not isinstance(expected_shop_name,str) or not expected_shop_name or not re.fullmatch('[0-9]+',str(expected_shop_id)):
        raise ValueError('Explicit expected shop name/id are required before browser writes')
    evidence = {'name':False,'id':False,'conflict':False,'document':0}
    requests = {}
    sequence = 0
    def reset(frame):
        if frame is page.main_frame:
            evidence.update(name=False,id=False,conflict=False,document=evidence['document']+1)
            requests.clear()
    def started(request):
        nonlocal sequence
        if request.resource_type not in ('xhr','fetch') or not _identity_method(request.url):
            return
        try:
            if request.frame is not page.main_frame or not _official_host(page.url,{'wares-jdm.jd.com'}):
                return
        except Exception:
            return  # A service-worker request may have no owning page frame.
        if len(requests) >= 128:
            requests.clear()
        sequence += 1
        evidence.update(name=False,id=False)
        requests[id(request)] = (request,sequence)
    def response(resp):
        request = resp.request
        owner = requests.pop(id(request),None)
        if not owner or owner[0] is not request or owner[1] != sequence:
            return
        method = _identity_method(resp.url)
        document = evidence['document']
        try:
            if (not method or request.frame is not page.main_frame or not _official_host(page.url,{'wares-jdm.jd.com'})
                    or resp.status != 200):
                return
            pair = _current_shop_pair(resp.json(),method)
        except Exception:
            pair = None
        if document != evidence['document'] or owner[1] != sequence:
            return
        matches = pair == (str(expected_shop_id),expected_shop_name)
        evidence.update(name=matches,id=matches,conflict=evidence['conflict'] or (pair is not None and not matches))
    page.on('framenavigated',reset)
    page.on('request',started)
    page.on('response', response)
    return evidence


def _open_short_titles(page, evidence, wait_ms):
    page.goto(WARE_LIST_URL, wait_until='domcontentloaded', timeout=90000)
    page.wait_for_timeout(wait_ms)
    if not _has_shop_identity(page,evidence):
        raise RuntimeError('Target shop browser identity/login could not be verified; no submission')
    page.locator('.batch-dropdown-link').hover()
    with page.expect_response(lambda r: 'batchJobService.queryByPage' in r.url, timeout=20000) as loaded:
        page.get_by_text('批量设置短标题', exact=True).filter(visible=True).first.click()
    if loaded.value.json().get('code') not in (200,'200'):
        raise RuntimeError('Short-title task list is unavailable; no upload attempted')
    drawer = short_title_drawer(page)
    drawer.wait_for(state='visible', timeout=15000)
    return drawer


def _task_rows(drawer):
    return drawer.locator('tbody tr').all_inner_texts()










def import_short_titles(profile_dir, workbook, **options):
    from pop_title_dispatch import import_workbook
    return import_workbook(_import_short_title_batch, profile_dir, workbook, **options)


def _import_short_title_batch(*args, **kwargs):
    from pop_title_dispatch import import_short_title_batch
    return import_short_title_batch(sys.modules[__name__], *args, **kwargs)


def _visit_title_batch(*args, **kwargs):
    from pop_title_dispatch import visit_title_batch
    return visit_title_batch(sys.modules[__name__], *args, **kwargs)


def short_title_row_failures(result_url, timeout=60):
    """{sku: reason} for failed rows in the platform import result workbook."""
    import io, httpx
    from openpyxl import load_workbook
    response = httpx.get(result_url, timeout=timeout)
    response.raise_for_status()
    raw = response.content
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        rows = list(book.active.iter_rows(values_only=True))
    finally:
        book.close()
    header = [str(x or '') for x in rows[0]] if rows else []
    try:
        si, ri, ei = header.index('SKUID'), header.index('执行结果'), header.index('失败原因')
    except ValueError:
        return {}
    failures={}
    seen=set()
    for row in rows[1:]:
        if len(row)<=max(si,ri,ei) or not row[si]:continue
        sku=str(row[si]).strip()
        if sku in seen:
            failures.pop(sku,None)
            continue
        seen.add(sku)
        if str(row[ri]).strip() in ('失败','导入失败','执行失败','处理失败'):
            failures[sku]=str(row[ei] or '')
    return failures


def sensitive_words(reason):
    """Words from '包含敏感词【["中华","烟"]】'."""
    match = re.search(r'敏感词【(\[.*?\])】', reason or '')
    if not match:
        return []
    try:
        return [str(x) for x in json.loads(match.group(1))]
    except ValueError:
        return re.findall(r'"([^"]+)"', match.group(1))


def validate_batch_receipt(value):
    if value.get('code') not in (200, '200'):
        raise ValueError('Batch task did not return an accepted business receipt')
    return {'code': 200, 'accepted': True}

def batch_coverage(targets,chunks):
    target=set(map(str,targets))
    accepted={str(s) for c in chunks if c.get('status')=='task-accepted' for s in c.get('skuIds',[])}
    unresolved=[c for c in chunks if c.get('status') in {'intent','unknown'}]
    missing=target-accepted
    status='batch-unknown' if unresolved else 'task-accepted' if target and not missing else 'batch-incomplete'
    return {'status':status,'acceptedSkuIds':sorted(accepted),'missingSkuIds':sorted(missing),'unresolvedAttemptIds':[c.get('attemptId') for c in unresolved]}

def ensure_batch_request_new(targets,ids,chunks):
    target=set(map(str,targets));selected=set(map(str,ids))
    if not selected or not selected.issubset(target):raise ValueError('Batch request escaped exact target SKU scope')
    submitted={str(s) for c in chunks if c.get('status') in {'intent','unknown','task-accepted'} for s in c.get('skuIds',[])}
    if selected.intersection(submitted):raise ValueError('Batch request overlaps accepted or unresolved SKU attempt; do not replay')

def save_batch_receipt(path,targets,chunk):
    path=Path(path);saved=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'targetSkuIds':list(map(str,targets)),'chunks':[]}
    if set(saved.get('targetSkuIds',[]))!=set(map(str,targets)):raise ValueError('Batch target scope changed')
    chunks=saved.setdefault('chunks',[]);attempt=chunk.get('attemptId')
    matches=[i for i,c in enumerate(chunks) if attempt and c.get('attemptId')==attempt]
    if matches:
        previous=chunks[matches[0]]
        if previous.get('skuIds')!=chunk.get('skuIds'):raise ValueError('Batch attempt SKU scope changed')
        chunks[matches[0]]=chunk
    else:chunks.append(chunk)
    saved.update(batch_coverage(targets,chunks));_save_receipt(path,saved)
    return saved

def submit_batch_cutout(profile_dir: str, *, mode: str='sku-white', max_pages: int=1, wait_ms: int=12000,
                        dry_run: bool=False, expected_shop_name=None, expected_shop_id=None, target_sku_ids=(), receipt_path=None) -> dict:
    """提交京麦批量抠图任务。mode=sku-white 用 SKU 白底图抠图（推荐），main-image 用第1张主图。"""
    if mode not in {'sku-white', 'main-image'}:
        raise ValueError('mode 只支持 sku-white 或 main-image')
    sync_playwright = _playwright()
    receipts = []
    with browser_profile_lock(profile_dir), sync_playwright() as playwright:
        context = _open(playwright, profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            seen = []
            evidence = _observe_identity(page, expected_shop_name, expected_shop_id)
            receipt_path = Path(receipt_path) if receipt_path else None
            if not dry_run and receipt_path is None:
                raise ValueError('A durable --receipt-path is required for batch writes')
            if receipt_path and receipt_path.exists():
                raise ValueError('Batch receipt already exists; reconcile before retrying')

            def guard(route):
                if not _has_shop_identity(page,evidence):
                    route.abort()
                    return
                request = route.request
                try:
                    payload = json.loads(request.post_data or '{}')
                except ValueError:
                    route.abort()
                    return
                param = payload.get('param') or {}
                content = param.get('contentMap') or {}
                ids = param.get('businessIdList') or []
                expected_type = '1' if mode == 'sku-white' else '0'
                ok = (str(param.get('srcId')) == '37'
                      and str(content.get('transparentImageUseImageType')) == expected_type
                      and str(content.get('excitMaterialNotReplace')) == '0'
                      and not content.get('whiteImageUseImageType')
                      and len(ids) > 0
                      and (not target_sku_ids or set(map(str, ids)).issubset(set(map(str, target_sku_ids)))))
                seen.append({'ok': ok, 'skuCount': len(ids)})
                if not ok or dry_run:
                    route.abort()
                    return
                existing=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
                ensure_batch_request_new(target_sku_ids or ids,ids,existing.get('chunks',[]))
                attempt_id=uuid.uuid4().hex
                save_batch_receipt(receipt_path,target_sku_ids or ids,{'attemptId':attempt_id,'status':'intent','skuIds':list(map(str,ids)),'mode':mode})
                try:
                    response = route.fetch()
                    value = validate_batch_receipt(response.json())
                except Exception:
                    route.abort()
                    raise RuntimeError('Batch response unknown/refused; preserve intent and stop before another page') from None
                receipts.append({'httpStatus': response.status, **value})
                save_batch_receipt(receipt_path,target_sku_ids or ids,{'attemptId':attempt_id,'status':'task-accepted','skuIds':list(map(str,ids)),'mode':mode,'receipt':receipts[-1]})
                route.fulfill(response=response)

            page.route('**/*createTask*', guard)
            page.goto(MATERIAL_URL, wait_until='domcontentloaded', timeout=90000)
            page.wait_for_timeout(wait_ms)
            if not _has_shop_identity(page,evidence):
                raise RuntimeError('Target shop browser identity could not be verified')
            for number in range(1, max_pages + 1):
                if number > 1 and receipt_path and receipt_path.exists():
                    saved=json.loads(receipt_path.read_text(encoding='utf-8'))
                    accepted=set(saved.get('acceptedSkuIds',[]))
                    if any(c.get('status') in {'intent','unknown'} for c in saved.get('chunks',[])):
                        raise RuntimeError('A batch chunk result is unknown; no further pages submitted')
                if number > 1 and not _next_page(page, number):
                    break
                if number > 1:
                    page.wait_for_timeout(6000)
                if target_sku_ids:
                    selected = page.evaluate("""(ids) => { let count=0; for (const row of document.querySelectorAll('tbody tr')) { const text=row.innerText || ''; if (!ids.some(id => text.includes(id))) continue; const control=row.querySelector('input[type=checkbox]'); if (control && !control.checked) {control.click(); count++;} } return count; }""", list(map(str,target_sku_ids)))
                    if not selected: raise RuntimeError('Exact target SKU selection unavailable; do not select unrelated rows')
                else:
                    page.evaluate("() => { const h = document.querySelector('thead'); const b = h && h.querySelector('input[type=checkbox]'); if (b && !b.checked) b.click(); }")
                page.wait_for_timeout(1500)
                page.evaluate("() => { for (const b of document.querySelectorAll('button')) { if (b.offsetParent !== null && (b.innerText || '').trim() === '批量图片') { b.click(); return; } } }")
                page.wait_for_timeout(3500)
                _configure_dialog(page, mode)
                page.wait_for_timeout(800)
                page.evaluate("() => { for (const b of document.querySelectorAll('button')) { if (b.offsetParent !== null && (b.innerText || '').trim() === '生成预览') { b.click(); return; } } }")
                page.wait_for_timeout(10000)
                page.evaluate("() => { const btns = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null && (b.innerText || '').trim() === '保存'); if (btns.length) btns[btns.length - 1].click(); }")
                page.wait_for_timeout(6000)
                page.keyboard.press('Escape')
                page.wait_for_timeout(1200)
            if dry_run:
                return {'status': 'dry-run', 'mode': mode, 'payloads': seen, 'receipts': []}
            if not seen or not receipts:
                raise RuntimeError('No accepted createTask receipt; task was not proven submitted')
            saved=json.loads(receipt_path.read_text(encoding='utf-8'))
            if any(not item['ok'] for item in seen): saved['status']='batch-incomplete'
            return {**saved, 'mode': mode, 'pages': len(receipts), 'payloads': seen, 'receipts': receipts}
        finally:
            context.close()


JINGMAI_REPAIR_MODES = {
    # Rejected white/transparent: platform's own batch cutout first (srcId=37, never replace approved/pending).
    'transparent-sku-white': {'transparent': 'sku-white'},
    'white-main': {'white': 'main'},
    'transparent-main': {'transparent': 'main'},
    'white-main+transparent-main': {'white': 'main', 'transparent': 'main'},
}


def expected_repair_content(mode):
    plan = JINGMAI_REPAIR_MODES[mode]
    return {
        'transparentImageUseImageType': {'sku-white': '1', 'main': '0'}.get(plan.get('transparent')),
        'transparentImageUseImageIndex': '1' if plan.get('transparent') == 'main' else None,
        'whiteImageUseImageType': '0' if plan.get('white') == 'main' else None,
        'whiteImageUseImageIndex': '1' if plan.get('white') == 'main' else None,
        'excitMaterialNotReplace': '0',
    }


def repair_payload_ok(payload, mode, expected_skus):
    param = payload.get('param') or {}
    content = param.get('contentMap') or {}
    want = expected_repair_content(mode)
    if str(param.get('srcId')) != '37' or int(param.get('taskType') or 0) != 1:
        return False
    if any((None if content.get(k) in (None, '') else str(content.get(k))) != v for k, v in want.items()):
        return False
    if content.get('sceneImageUseImageOneIndex') or content.get('sceneImageUseImageTwoIndex'):
        return False
    return set(map(str, param.get('businessIdList') or [])) == set(map(str, expected_skus)) and bool(expected_skus)


def submit_jingmai_repair_batch(profile_dir, spu_skus, mode, *, expected_shop_name, expected_shop_id,
                                receipt_path, exclude_skus=(), wait_ms=12000, preview_timeout=90, dry_run=False):
    """One Jingmai batch-image task for <=10 SPUs. Preview first; preview failures and excluded SKUs are
    unchecked; createTask must carry exactly the remaining SKUs or it is aborted. Receipt intent precedes send."""
    if mode not in JINGMAI_REPAIR_MODES:
        raise ValueError('unknown Jingmai repair mode')
    spus = [str(s) for s in spu_skus]
    if not spus or len(spus) > 10:
        raise ValueError('one Jingmai batch covers 1-10 SPUs')
    receipt_path = Path(receipt_path)
    if receipt_path.exists():
        raise ValueError('Jingmai batch receipt exists; reconcile it, do not replay')
    all_skus = {str(k) for v in spu_skus.values() for k in v}
    exclude = set(map(str, exclude_skus))
    sync_playwright = _playwright()
    with browser_profile_lock(profile_dir), sync_playwright() as playwright:
        context = _open(playwright, profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            evidence = _observe_identity(page, expected_shop_name, expected_shop_id)
            preview = {}
            state = {'expected': None, 'seen': [], 'receipt': None}

            def on_response(resp):
                body = resp.request.post_data or ''
                if 'sff.jd.com/api' not in resp.url or 'UseImageIndex' not in body or 'businessIdList' in body:
                    return
                try:
                    for item in resp.json().get('data') or []:
                        preview[str(item.get('skuId'))] = item.get('errorMsg') or ''
                except Exception:
                    pass
            page.on('response', on_response)

            def guard(route):
                if not _has_shop_identity(page,evidence):
                    return route.abort()
                try:
                    payload = json.loads(route.request.post_data or '{}')
                except ValueError:
                    return route.abort()
                ok = state['expected'] is not None and repair_payload_ok(payload, mode, state['expected'])
                state['seen'].append({'ok': ok, 'skuIds': sorted(map(str, (payload.get('param') or {}).get('businessIdList') or [])), 'contentMap': (payload.get('param') or {}).get('contentMap')})
                if not ok or dry_run:
                    return route.abort()
                saved = {'status': 'intent', 'mode': mode, 'spuIds': spus, 'skuIds': sorted(state['expected']), 'targetSkuIds': sorted(all_skus),
                         'previewFailures': {k: v for k, v in preview.items() if v},
                         'shopName': expected_shop_name, 'shopId': str(expected_shop_id), 'createdAt': int(time.time())}
                _save_receipt(receipt_path, saved)
                try:
                    response = route.fetch()
                    value = validate_batch_receipt(response.json())
                except Exception:
                    saved['status'] = 'unknown'; _save_receipt(receipt_path, saved)
                    route.abort(); return
                saved.update(status='task-accepted', receipt=value); _save_receipt(receipt_path, saved)
                state['receipt'] = saved
                route.fulfill(response=response)
            page.route('**/*createTask*', guard)
            page.goto(MATERIAL_URL, wait_until='domcontentloaded', timeout=90000)
            page.wait_for_timeout(wait_ms)
            for _ in range(15):
                if _has_shop_identity(page,evidence) or 'login' in page.url.lower():break
                page.wait_for_timeout(2000)
            if not _has_shop_identity(page,evidence):
                raise RuntimeError('Target shop browser identity/login could not be verified; no submission')
            page.locator('input[placeholder*="多个可"]').first.fill(','.join(spus))
            page.get_by_text('查询', exact=True).first.click()
            page.wait_for_timeout(5000)
            checked = page.evaluate(r"""(spus) => { const out=[]; for (const tr of document.querySelectorAll('tr')) { const m=(tr.innerText||'').match(/商品编码：(\d+)/); const cb=tr.querySelector('input[type=checkbox]'); if(!m||!cb) continue; const want=spus.includes(m[1]); if(want!==cb.checked) cb.click(); if(cb.checked) out.push(m[1]); } return [...new Set(out)]; }""", spus)
            if set(checked) != set(spus):
                raise RuntimeError('Exact SPU selection failed; no submission')
            page.get_by_text('批量图片', exact=True).first.click()
            page.wait_for_timeout(3500)
            plan = JINGMAI_REPAIR_MODES[mode]
            configured = page.evaluate(r"""(plan) => {
              const root=document.querySelector('.smart-setting'); if(!root) return 'no dialog';
              const setv=(i,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(i,v);i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));};
              const top=[...root.querySelectorAll('label')].find(l=>(l.innerText||'').includes('不替换')); const p=top&&top.querySelector('input'); if(!p) return 'no protect'; if(!p.checked) p.click();
              for (const [label,src] of Object.entries(plan)) {
                const row=[...root.querySelectorAll('.smart-setting-row')].find(x=>(x.querySelector('.label')?.textContent||'').trim()===(label==='white'?'白底图':'透明图'));
                if(!row) return 'no row '+label;
                const want=label==='white'?(src==='main'?'张主图抠图并填充':'透明图填充'):(src==='main'?'张主图抠图':'使用SKU白底图抠图');
                const lab=[...row.querySelectorAll('label')].find(l=>(l.innerText||'').includes(want)); const c=lab&&lab.querySelector('input'); if(!c) return 'no option '+want; if(!c.checked) c.click();
                if(src==='main'){const i=row.querySelector('input[type=text]'); if(!i) return 'no index'; setv(i,'1');}
              }
              return p.checked?'ok':'protect off';
            }""", plan)
            if configured != 'ok':
                raise RuntimeError('Batch dialog configuration failed: ' + str(configured))
            page.evaluate("()=>{const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim()==='生成预览'&&x.offsetParent);b&&b.click()}")
            deadline = time.monotonic() + preview_timeout
            while time.monotonic() < deadline and not all_skus.issubset(preview):
                page.wait_for_timeout(2000)
            # Each SPU group only renders its first SKU until expanded; expand every group.
            for _ in range(len(spus) + 2):
                clicked = page.evaluate("()=>{const e=[...document.querySelectorAll('span,a,button')].filter(x=>(x.innerText||'').trim()==='展开预览'&&x.offsetParent);if(!e.length)return 0;e[0].click();return e.length}")
                page.wait_for_timeout(1200)
                if not clicked:break
            visible = set(page.evaluate(r"""()=>[...document.querySelectorAll('tr')].filter(t=>t.offsetParent).map(t=>((t.innerText||'').match(/SKU[:：]\s*(\d{8,})/)||[])[1]).filter(Boolean)"""))
            if not all_skus.issubset(visible):
                raise RuntimeError('Preview did not render every target SKU; no submission')
            # The UI only submits fully selected SPU groups; keep every SKU checked and rely on
            # excitMaterialNotReplace="0" so approved/pending siblings are never replaced.
            visible = set(page.evaluate(r"""()=>[...document.querySelectorAll('tr')].filter(t=>t.offsetParent).map(t=>((t.innerText||'').match(/SKU[:：]\s*(\d{8,})/)||[])[1]).filter(Boolean)"""))
            expected = visible
            failures = {k: v for k, v in preview.items() if v}
            if not (expected - set(failures)) & all_skus:
                result = {'status': 'nothing-eligible', 'mode': mode, 'spuIds': spus, 'previewFailures': failures}
                if not dry_run:_save_receipt(receipt_path, result)
                return result
            state['expected'] = expected
            page.evaluate("()=>{const b=[...document.querySelectorAll('button')].filter(x=>(x.innerText||'').trim()==='保存'&&x.offsetParent);b.length&&b[0].click()}")
            page.wait_for_timeout(6000)
            if dry_run:
                return {'status': 'dry-run', 'mode': mode, 'expectedSkuIds': sorted(expected), 'previewFailures': failures, 'payloads': state['seen']}
            if state['receipt'] is None:
                if receipt_path.exists():
                    return json.loads(receipt_path.read_text(encoding='utf-8'))
                raise RuntimeError('No accepted createTask receipt; task was not proven submitted')
            return {**state['receipt'], 'payloads': state['seen']}
        finally:
            context.close()


def _next_page(page, number: int) -> bool:
    direct = page.evaluate("""(n) => {
        const zones = Array.from(document.querySelectorAll('[class*=pagination], [class*=pager]')).filter(el => el.offsetParent !== null);
        for (const zone of zones) {
            for (const el of zone.querySelectorAll('a, li, button, span')) {
                if ((el.innerText || '').trim() === String(n)) { el.click(); return true; }
            }
        }
        return false;
    }""", number)
    if direct:
        return True
    return page.evaluate("""() => {
        const zones = Array.from(document.querySelectorAll('[class*=pagination], [class*=pager]')).filter(el => el.offsetParent !== null);
        for (const zone of zones) {
            for (const el of zone.querySelectorAll('a, li, button, span, i')) {
                const text = (el.innerText || '').trim();
                const cls = (el.className || '') + ' ' + (el.getAttribute('aria-label') || '');
                if (text === '>' || text === '下一页' || /next/i.test(cls)) { el.click(); return true; }
            }
        }
        return false;
    }""")


def _configure_dialog(page, mode: str) -> None:
    page.evaluate("""(mode) => {
        const dialogs = Array.from(document.querySelectorAll('[class*=drawer], [class*=modal], [class*=dialog], [role=dialog]')).filter(el => el.offsetParent !== null);
        const dialog = dialogs.sort((a, b) => b.innerText.length - a.innerText.length)[0];
        if (!dialog) return;
        const controls = Array.from(dialog.querySelectorAll('input'));
        const click = (el) => { if (el && !el.checked) el.click(); };
        const unclick = (el) => { if (el && el.checked) el.click(); };
        const fill = (el) => { if (el) { el.focus(); el.value = '1'; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); el.blur(); } };
        click(controls[0]);
        if (mode === 'sku-white') {
            click(controls[1]);
            unclick(controls[2]);
        } else {
            click(controls[2]);
            fill(controls[3]);
            unclick(controls[1]);
        }
        unclick(controls[4]);
        unclick(controls[5]);
    }""", mode)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='POP 店铺后台浏览器任务：短标题导入 / 京麦批量抠图')
    sub = parser.add_subparsers(dest='command', required=True)
    short = sub.add_parser('import-short-titles')
    short.add_argument('--profile-dir', required=True)
    short.add_argument('--workbook', required=True)
    short.add_argument('--wait-ms', type=int, default=22000)
    short.add_argument('--dry-run', action='store_true')
    cutout = sub.add_parser('batch-cutout')
    cutout.add_argument('--profile-dir', required=True)
    cutout.add_argument('--mode', choices=('sku-white', 'main-image'), default='sku-white')
    cutout.add_argument('--max-pages', type=int, default=1)
    cutout.add_argument('--wait-ms', type=int, default=12000)
    cutout.add_argument('--dry-run', action='store_true')
    for command in (short, cutout):
        command.add_argument('--expected-shop-name', required=True)
        command.add_argument('--expected-shop-id', required=True)
        command.add_argument('--receipt-path', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'import-short-titles':
        result = import_short_titles(args.profile_dir, args.workbook, wait_ms=args.wait_ms, dry_run=args.dry_run, expected_shop_name=args.expected_shop_name, expected_shop_id=args.expected_shop_id, receipt_path=args.receipt_path)
    else:
        result = submit_batch_cutout(args.profile_dir, mode=args.mode, max_pages=args.max_pages,
                                     wait_ms=args.wait_ms, dry_run=args.dry_run, expected_shop_name=args.expected_shop_name, expected_shop_id=args.expected_shop_id, receipt_path=args.receipt_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('status') in {'import-completed', 'task-accepted', 'dry-run'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
