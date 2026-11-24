#!/usr/bin/env python3
"""POP 店铺后台浏览器任务：短标题导入、京麦批量抠图。

只复用店铺自己的 Chrome 配置（不复制 Cookie、不读凭据），窗口放到屏幕外，
不抢占用户正在使用的浏览器。Playwright 为可选依赖：缺失时给出明确安装命令。
"""
import argparse
import json
import sys
import re
import hashlib
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

WARE_LIST_URL = 'https://wares-jdm.jd.com/ware/wareList?activeTab=OnsaleWare&businessModel=0'
MATERIAL_URL = 'https://wares-jdm.jd.com/ware/wareList/materialCenter/materialScene?activeTab=OnsaleWare&businessModel=0'
OFFSCREEN = '--window-position=-32000,-32000'


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
        args=['--profile-directory=Default', '--no-first-run', OFFSCREEN],
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

def _observe_identity(page, expected_shop_name, expected_shop_id):
    if not expected_shop_name or not expected_shop_id:
        raise ValueError('Explicit expected shop name/id are required before browser writes')
    evidence = {'name': False, 'id': False}
    def response(resp):
        if not any(api in resp.url for api in ('gmall.vender.data.get', 'VenderIdentityViewService', 'LoginFacadeService')):
            return
        def visit(value):
            if isinstance(value, dict):
                if value.get('shopName') == expected_shop_name:
                    evidence['name'] = True
                for key in ('venderId', 'vendorId', 'shopId'):
                    if str(value.get(key, '')) == str(expected_shop_id):
                        evidence['id'] = True
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value[:50]: visit(child)
        try: visit(resp.json())
        except Exception: pass
    page.on('response', response)
    return evidence


def _open_short_titles(page, evidence, wait_ms):
    page.goto(WARE_LIST_URL, wait_until='domcontentloaded', timeout=90000)
    page.wait_for_timeout(wait_ms)
    if 'login' in page.url.lower() or not evidence['id']:
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


def batch_receipt_path(workbook, digest):
    return Path(workbook).parent / '.state' / ('title-import-' + digest[:16] + '.json')


def completed_batch(receipt, rows):
    if not receipt.get('taskId') or receipt.get('taskFinished') is False:
        return False
    success, failed = receipt.get('successRows'), receipt.get('failedRows')
    if type(success) is not int or type(failed) is not int or min(success,failed)<0 or success+failed != rows:
        return False
    if receipt.get('status') == 'import-completed':
        return failed == 0
    return receipt.get('status') == 'import-failed' and failed > 0 and receipt.get('creationAccepted') is True


def submit_title_batches(profile_dir, batches, importer, options, *, ledger_path=None):
    """Dispatch in frozen order. Each child retains its own original receipt."""
    planned = [{**item, 'receiptPath':str(batch_receipt_path(item['path'],item['sha256']))} for item in batches]
    imports = []
    result = {'plannedBatches':planned,'imports':imports,'rowCount':sum(b['rowCount'] for b in planned),
              'successRows':0,'failedRows':0,'status':'import-pending'}
    old_imports=[]
    if ledger_path:
        result.update(kind='short-title-import-batches',sha256=planned[0]['sourceSha256'],shopName=options['expected_shop_name'],
                      shopId=str(options['expected_shop_id']),receiptPath=str(ledger_path))
        if ledger_path.exists():
            old=json.loads(ledger_path.read_text(encoding='utf-8'))
            if any(old.get(k)!=result[k] for k in ('kind','sha256','shopName','shopId','plannedBatches')):
                raise ValueError('Original batch receipt does not match this source, shop or plan; no upload')
            old_imports=old.get('imports',[])
            for batch in old_imports:
                if not Path(batch['receiptPath']).is_file() and batch.get('dispatchState') != 'before-upload':
                    return {**old,'status':'unknown','reason':'Original batch receipt missing; reconcile original task'}
        if not ledger_path.exists() and not options.get('dry_run'):
            _save_receipt(ledger_path,result)
    for batch in planned:
        if ledger_path and not options.get('dry_run'):
            _save_receipt(ledger_path,{**result,'imports':[*imports,{**batch,'status':'dispatch-intent'},*old_imports[len(imports)+1:]]})
        try:
            receipt=importer(profile_dir,batch['path'],**options,expected_sha256=batch['sha256'])
        except Exception as error:
            receipt={'status':'blocked-import','failureClass':type(error).__name__,
                     'reason':'Import or readback did not finish; inspect the original batch receipt before retrying'}
            if isinstance(error,ValueError):
                receipt['reason']=str(error)[:400]
            if not Path(batch['receiptPath']).exists():
                receipt['dispatchState']='before-upload'
        receipt={**receipt,**batch}
        imports.append(receipt)
        done=completed_batch(receipt,batch['rowCount'])
        if done:
            result['successRows']+=receipt['successRows']
            result['failedRows']+=receipt['failedRows']
        if not done and receipt.get('status')!='dry-run':
            result['status']=receipt.get('status','unknown')
            if result['status']=='import-completed':
                result['status']='unknown'
            break
    else:
        result['status']='dry-run' if options.get('dry_run') else 'import-failed' if result['failedRows'] else 'import-completed'
    if ledger_path and not options.get('dry_run'):
        _save_receipt(ledger_path,result)
    return result


def submit_title_source(profile_dir,batches,importer,options,requested=None):
    """A split source has one original ledger, including when the caller supplied its path."""
    from contextlib import ExitStack
    from heideng_merchant.state import FileLock
    first=batches[0]
    source=Path(first['sourcePath']).resolve()
    source_sha=first['sourceSha256']
    default_set=source.parent/'.state'/('title-import-set-'+source_sha[:16]+'.json')
    old_default=batch_receipt_path(source,source_sha)
    if len(batches)==1 and Path(first['path']).resolve()==source:
        if requested:
            raise ValueError('Explicit single-workbook receipt must use the single import entry')
        return submit_title_batches(profile_dir,batches,importer,options)
    original = Path(requested).resolve() if requested else default_set
    protected={source}
    for b in batches:
        child=Path(b['path']).resolve()
        receipt=batch_receipt_path(child,b['sha256'])
        protected.update((child,receipt,Path(str(receipt)+'.lock'),child.parent/'prepare.lock'))
    if original in protected or Path(str(original)+'.lock') in protected or original == Path(str(default_set)+'.lock'):
        raise ValueError('Batch ledger path collides with an original workbook, child receipt or lock')
    if old_default.exists():
        old=json.loads(old_default.read_text(encoding='utf-8'))
        if old.get('kind')=='short-title-import-batches':
            if requested and original!=old_default:
                raise ValueError(f'原表已有导入总账，请沿用：{old_default}')
            original=old_default
    # The standard location points to a custom ledger. Both direct and maintenance
    # entries resolve it without searching other task or merchant directories.
    with ExitStack() as locks:
        locks.enter_context(FileLock(Path(str(default_set)+'.lock'),timeout=45))
        if default_set.exists():
            record=json.loads(default_set.read_text(encoding='utf-8'))
            bound=Path(record['originalLedger']).resolve() if record.get('kind')=='short-title-ledger-reference' else default_set
            if (record.get('sha256')!=source_sha or record.get('shopName')!=options['expected_shop_name']
                    or str(record.get('shopId'))!=str(options['expected_shop_id']) or not bound.is_file()
                    or bound in protected or (requested and original not in (default_set,bound))
                    or (old_default.exists() and old_default!=bound)):
                raise ValueError(f'原表已绑定其他导入总账或原回执缺失，请核对：{bound}')
            original=bound
        if original!=default_set:
            locks.enter_context(FileLock(Path(str(original)+'.lock'),timeout=45))
        if original.exists():
            record=json.loads(original.read_text(encoding='utf-8'))
            old_plan=record.get('plannedBatches') or []
            def signature(plan):
                return [(b['sha256'],b['rowCount'],b['byteCount'],b['sourceSha256']) for b in plan]
            if (record.get('kind')!='short-title-import-batches' or signature(old_plan)!=signature(batches)
                    or record.get('shopName')!=options['expected_shop_name'] or str(record.get('shopId'))!=str(options['expected_shop_id'])):
                raise ValueError(f'导入批次、店铺或文件与原总账不符：{original}')
            # Old task directories take precedence when a second entry selected a different output directory.
            batches=[{k:v for k,v in b.items() if k!='receiptPath'} for b in old_plan]
            if any(not Path(b['path']).is_file() for b in batches):
                raise ValueError(f'原批次文件缺失，请从原总账核对：{original}')
        if original!=default_set and not options.get('dry_run') and not default_set.exists():
            if not original.exists():
                initial={'kind':'short-title-import-batches','sha256':source_sha,'shopName':options['expected_shop_name'],
                         'shopId':str(options['expected_shop_id']),'imports':[],
                         'plannedBatches':[{**b,'receiptPath':str(batch_receipt_path(b['path'],b['sha256']))} for b in batches]}
                _save_receipt(original,initial)
            _save_receipt(default_set,{'kind':'short-title-ledger-reference','originalLedger':str(original),
                         'sha256':source_sha,'shopName':options['expected_shop_name'],'shopId':str(options['expected_shop_id'])})
        return submit_title_batches(profile_dir,batches,importer,options,ledger_path=original)


def import_short_titles(profile_dir, workbook, *, wait_ms=12000, dry_run=False, expected_shop_name=None,
                        expected_shop_id=None, receipt_path=None, poll_seconds=60, expected_sha256=None):
    from pop_title_batches import prepare_import_batches, PriorImportReceipt
    path=Path(workbook)
    options=dict(wait_ms=wait_ms,dry_run=dry_run,expected_shop_name=expected_shop_name,
                 expected_shop_id=expected_shop_id,poll_seconds=poll_seconds)
    if expected_sha256 is not None:
        # The workflow already froze and validated the complete set before any upload.
        return _import_short_title_batch(profile_dir,workbook,**options,expected_sha256=expected_sha256,receipt_path=receipt_path)
    if receipt_path and Path(receipt_path).resolve()==path.resolve():
        raise ValueError('Receipt path collides with the original workbook')
    if receipt_path and Path(receipt_path).exists():
        try:
            old=json.loads(Path(receipt_path).read_text(encoding='utf-8'))
            if not isinstance(old,dict):raise ValueError()
        except (ValueError,UnicodeError):
            raise ValueError('指定的回执位置已有其他文件或锁，未提交：'+str(receipt_path)) from None
        if old.get('kind') not in ('short-title-import-batches','short-title-ledger-reference'):
            return _import_short_title_batch(profile_dir,workbook,**options,receipt_path=receipt_path,reconcile_only=True)
    try:
        batches=prepare_import_batches([path],path.parent)
    except PriorImportReceipt as original:
        result=_import_short_title_batch(profile_dir,str(original.workbook_path),**options,receipt_path=original.receipt_path,
                                        expected_sha256=original.sha256,reconcile_only=True)
        if Path(original.workbook_path).resolve() != path.resolve():
            return {'status':'prior-batch-reconciliation','originalBatch':result,'receiptPath':str(original.receipt_path)}
        return result
    if len(batches)==1 and Path(batches[0]['path']).resolve()==path.resolve():
        batch=batches[0]
        target=receipt_path or batch_receipt_path(path,batch['sha256'])
        return {**_import_short_title_batch(profile_dir,workbook,**options,expected_sha256=batch['sha256'],receipt_path=target),
                **batch,'receiptPath':str(target)}
    return submit_title_source(profile_dir,batches,_import_short_title_batch,options,requested=receipt_path)


def _import_short_title_batch(profile_dir: str, workbook: str, *, wait_ms: int=12000, dry_run: bool=False,
                              expected_shop_name=None, expected_shop_id=None, receipt_path=None,
                              poll_seconds=60, expected_sha256=None, reconcile_only=False) -> dict:
    """Import exactly once, using the drawer's input, persisted intent and real task readback."""
    path = Path(workbook)
    if not path.is_file():
        raise ValueError(f'短标题维护表不存在：{path}')
    from jd_material_agent import validate_short_title_workbook
    try: validation = validate_short_title_workbook(path)
    except Exception as error: raise ValueError('Invalid official short-title workbook') from None
    if not validation['valid'] and not (reconcile_only and validation['rowCount'] and not validation['invalidRows']):
        raise ValueError('Short-title workbook validation failed; no upload')
    from pop_title_batches import IMPORT_MAX_ROWS, IMPORT_MAX_BYTES
    if not reconcile_only and (validation['rowCount'] > IMPORT_MAX_ROWS or path.stat().st_size > IMPORT_MAX_BYTES):
        raise ValueError('Browser import limit is 5000 rows / 5MB; split before submission')
    digest = validation['sha256']
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Planned short-title workbook changed; no upload')
    receipt_path = Path(receipt_path or batch_receipt_path(path, digest))
    from heideng_merchant.state import FileLock
    with FileLock(Path(str(receipt_path)+'.lock'), timeout=45), browser_profile_lock(profile_dir):
        saved = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
        if (receipt_path.exists() and (not saved or saved.get('sha256') != digest or saved.get('shopName') != expected_shop_name
                                       or str(saved.get('shopId')) != str(expected_shop_id))):
            raise ValueError('Import receipt identity/fingerprint mismatch; no replay')
        if reconcile_only and not saved:
            raise ValueError('Original import receipt unavailable; no replay')
        if not dry_run and (completed_batch(saved,validation['rowCount']) and
                            (saved['status']=='import-completed' or saved.get('resultFileUrl'))
                            or saved.get('status') in ('upload-refused','create-refused') or saved.get('createRefused')):
            return saved
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError('Workbook changed since validation; no upload')
        sync_playwright = _playwright()
        with sync_playwright() as playwright:
            return _visit_title_batch(playwright,profile_dir,path,content,receipt_path,saved,validation,wait_ms,dry_run,
                                      expected_shop_name,expected_shop_id,poll_seconds)


def _visit_title_batch(playwright,profile_dir,path,content,receipt_path,saved,validation,wait_ms,dry_run,
                       expected_shop_name,expected_shop_id,poll_seconds):
    context = _open(playwright, profile_dir)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        backend_rows=[]
        def task_response(resp):
            if 'batchJobService.queryByPage' not in resp.url:return
            try:
                data=resp.json().get('data') or {}
                backend_rows[:] = data.get('batchJobRecordDtoList') or []
            except Exception:pass
        page.on('response',task_response)
        evidence = _observe_identity(page, expected_shop_name, expected_shop_id)
        drawer = _open_short_titles(page, evidence, wait_ms)
        if dry_run: return {'status': 'dry-run', 'identityVerified': True}
        task_id = saved.get('taskId')
        if not saved:
            before = set(re.findall(r'(?<!\d)\d{6,}(?!\d)', '\n'.join(_task_rows(drawer))))
            # The page has other upload inputs. Only this drawer owns short-title import.
            saved = {'status':'upload-intent','sha256':validation['sha256'],'rowCount':validation['rowCount'],
                     'byteCount':len(content),'path':str(path),'receiptPath':str(receipt_path),
                     'shopName':expected_shop_name,'shopId':str(expected_shop_id),'createdAt':int(time.time()),
                     'beforeTaskIds':sorted(before)}
            _save_receipt(receipt_path,saved)
            try:
                with page.expect_response(lambda r: 'file.upload' in r.url, timeout=25000) as uploaded:
                    drawer.locator('input[type=file]').first.set_input_files({
                        'name':path.name,'mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':content})
                upload_value=uploaded.value.json()
            except Exception:
                saved.update(status='unknown',reason='Original file upload response unknown; preserve this receipt')
                _save_receipt(receipt_path,saved)
                return saved
            if upload_value.get('code') not in (200,'200'):
                saved.update(status='upload-refused',reason='Platform refused file upload; import not submitted')
                _save_receipt(receipt_path,saved)
                return saved
            upload_hashes=upload_source_identifiers(upload_value)
            saved.update(status='uploaded',uploadSourceHashes=upload_hashes)
            _save_receipt(receipt_path,saved)
            drawer.get_by_text(path.name, exact=True).wait_for(state='visible', timeout=20000)
            saved.update(status='intent', createdAt=int(time.time()))
            _save_receipt(receipt_path, saved)
            try:
                # A click is not a receipt; require the real createImportJob business response.
                with page.expect_response(lambda r: 'batchJobService.createImportJob' in r.url, timeout=25000) as pending:
                    drawer.get_by_role('button', name='确定导入', exact=True).click()
                value = pending.value.json()
                if value.get('code') not in (200, '200'):
                    saved.update(status='import-failed', createRefused=True)
                    _save_receipt(receipt_path, saved)
                    return {**saved, 'reason': 'Platform refused import task'}
                task_id=created_task_id(value)
                saved.update(status='import-pending', creationAccepted=True)
                if task_id:saved['taskId']=task_id
                _save_receipt(receipt_path,saved)
                drawer.get_by_text('刷新列表', exact=True).click()
                page.wait_for_timeout(2000)
                if not task_id:task_id=recover_backend_task(backend_rows,saved.get('uploadSourceHashes',[]),saved['createdAt'])
                # Never use jobId (30034 task definition) as a created task ID.
                if task_id:
                    saved.update(taskId=task_id, status='import-pending')
                    _save_receipt(receipt_path,saved)
            except Exception:
                saved['status'] = 'unknown'
                _save_receipt(receipt_path, saved)
                return {**saved, 'reason': 'Import result unknown; inspect this shop task list before retrying'}
        if not task_id and saved.get('uploadSourceHashes') and 'beforeTaskIds' in saved:
            recovered=recover_backend_task(backend_rows,saved.get('uploadSourceHashes',[]),saved['createdAt'])
            if recovered and recovered not in saved['beforeTaskIds']:
                task_id=recovered;saved.update(taskId=task_id,status='import-pending',creationAccepted=True);_save_receipt(receipt_path,saved)
        if not task_id:
            saved['status'] = 'unknown'
            _save_receipt(receipt_path, saved)
            return {**saved, 'reason': 'Original task ID unavailable; never resubmit automatically'}
        deadline = time.monotonic() + poll_seconds
        result = {'status': 'unknown', 'taskId': task_id}
        while True:
            rows = [row for row in _task_rows(drawer) if re.search(r'(?<!\d)' + re.escape(task_id) + r'(?!\d)', row)]
            if len(rows) == 1: result = parse_short_title_task(rows[0], validation['rowCount'], task_id)
            if result['status'] in {'import-completed', 'import-failed'} or time.monotonic() >= deadline: break
            drawer.get_by_text('刷新列表', exact=True).click()
            page.wait_for_timeout(3000)
        for row in backend_rows:
            # Keep the platform's per-row result file so failed rows can be repaired precisely.
            if str(row.get('jobExecId')) == str(task_id) and row.get('jobExecFileRst'):
                result['resultFileUrl'] = row['jobExecFileRst']
        saved.update(result, checkedAt=int(time.time()))
        _save_receipt(receipt_path, saved)
        return saved
    finally:
        context.close()


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
            if not evidence['id'] or 'login' in page.url.lower():
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
                if evidence['id'] or 'login' in page.url.lower():break
                page.wait_for_timeout(2000)
            if 'login' in page.url.lower() or not evidence['id']:
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
