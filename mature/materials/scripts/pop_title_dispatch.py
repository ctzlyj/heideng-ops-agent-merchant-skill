"""Receipt-backed dispatch for complete original short-title workbooks."""
import json
import re
import time
import hashlib
from pathlib import Path
from pop_safety import atomic_json as _save_receipt


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
            from pop_title_io import redact
            receipt={'status':'blocked-import','failureClass':type(error).__name__,
                     'reason':'Import or readback did not finish; inspect the original batch receipt before retrying'}
            if str(error).strip():
                receipt['reason']=redact(str(error).strip().splitlines()[0])[:400]
            if not Path(batch['receiptPath']).exists():
                receipt['dispatchState']='before-upload'
                receipt['nextAction']='宿主恢复本店专用浏览器与原文件导入入口，再继续本批；尚无上传请求。'
            else:
                receipt['nextAction']='先读原批上传或创建任务的回执，核对真实导入任务；结果不明时仅回查。'
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
    from pop_title_io import FileLock
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

def import_workbook(importer, profile_dir, workbook, *, wait_ms=12000, dry_run=False, expected_shop_name=None,
                        expected_shop_id=None, receipt_path=None, poll_seconds=60, expected_sha256=None):
    from pop_title_batches import prepare_import_batches, PriorImportReceipt
    path=Path(workbook)
    options=dict(wait_ms=wait_ms,dry_run=dry_run,expected_shop_name=expected_shop_name,
                 expected_shop_id=expected_shop_id,poll_seconds=poll_seconds)
    if expected_sha256 is not None:
        # The workflow already froze and validated the complete set before any upload.
        return importer(profile_dir,workbook,**options,expected_sha256=expected_sha256,receipt_path=receipt_path)
    if receipt_path and Path(receipt_path).resolve()==path.resolve():
        raise ValueError('Receipt path collides with the original workbook')
    if receipt_path and Path(receipt_path).exists():
        try:
            old=json.loads(Path(receipt_path).read_text(encoding='utf-8'))
            if not isinstance(old,dict):raise ValueError()
        except (ValueError,UnicodeError):
            raise ValueError('指定的回执位置已有其他文件或锁，未提交：'+str(receipt_path)) from None
        if old.get('kind') not in ('short-title-import-batches','short-title-ledger-reference'):
            return importer(profile_dir,workbook,**options,receipt_path=receipt_path,reconcile_only=True)
    try:
        batches=prepare_import_batches([path],path.parent)
    except PriorImportReceipt as original:
        result=importer(profile_dir,str(original.workbook_path),**options,receipt_path=original.receipt_path,
                                        expected_sha256=original.sha256,reconcile_only=True)
        if Path(original.workbook_path).resolve() != path.resolve():
            return {'status':'prior-batch-reconciliation','originalBatch':result,'receiptPath':str(original.receipt_path)}
        return result
    if len(batches)==1 and Path(batches[0]['path']).resolve()==path.resolve():
        batch=batches[0]
        target=receipt_path or batch_receipt_path(path,batch['sha256'])
        return {**importer(profile_dir,workbook,**options,expected_sha256=batch['sha256'],receipt_path=target),
                **batch,'receiptPath':str(target)}
    return submit_title_source(profile_dir,batches,importer,options,requested=receipt_path)

def visit_title_batch(adapter, playwright,profile_dir,path,content,receipt_path,saved,validation,wait_ms,dry_run,
                       expected_shop_name,expected_shop_id,poll_seconds):
    context = adapter._open(playwright, profile_dir)
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
        evidence = adapter._observe_identity(page, expected_shop_name, expected_shop_id)
        drawer = adapter._open_short_titles(page, evidence, wait_ms)
        if dry_run: return {'status': 'dry-run', 'identityVerified': True}
        task_id = saved.get('taskId')
        if not saved:
            before = set(re.findall(r'(?<!\d)\d{6,}(?!\d)', '\n'.join(adapter._task_rows(drawer))))
            if not adapter._has_shop_identity(page,evidence):
                raise RuntimeError('目标网页身份在导入前已变化，尚未上传。')
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
            upload_hashes=adapter.upload_source_identifiers(upload_value)
            saved.update(status='uploaded',uploadSourceHashes=upload_hashes)
            _save_receipt(receipt_path,saved)
            drawer.get_by_text(path.name, exact=True).wait_for(state='visible', timeout=20000)
            if not adapter._has_shop_identity(page,evidence):
                return {**saved,'status':'blocked-import','reason':'文件上传后网页身份已变化，未创建导入任务。'}
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
                task_id=adapter.created_task_id(value)
                saved.update(status='import-pending', creationAccepted=True)
                if task_id:saved['taskId']=task_id
                _save_receipt(receipt_path,saved)
                drawer.get_by_text('刷新列表', exact=True).click()
                page.wait_for_timeout(2000)
                if not task_id:task_id=adapter.recover_backend_task(backend_rows,saved.get('uploadSourceHashes',[]),saved['createdAt'])
                # Never use jobId (30034 task definition) as a created task ID.
                if task_id:
                    saved.update(taskId=task_id, status='import-pending')
                    _save_receipt(receipt_path,saved)
            except Exception:
                saved['status'] = 'unknown'
                _save_receipt(receipt_path, saved)
                return {**saved, 'reason': 'Import result unknown; inspect this shop task list before retrying'}
        if not task_id and saved.get('uploadSourceHashes') and 'beforeTaskIds' in saved:
            recovered=adapter.recover_backend_task(backend_rows,saved.get('uploadSourceHashes',[]),saved['createdAt'])
            if recovered and recovered not in saved['beforeTaskIds']:
                task_id=recovered;saved.update(taskId=task_id,status='import-pending',creationAccepted=True);_save_receipt(receipt_path,saved)
        if not task_id:
            saved['status'] = 'unknown'
            _save_receipt(receipt_path, saved)
            return {**saved, 'reason': 'Original task ID unavailable; never resubmit automatically'}
        deadline = time.monotonic() + poll_seconds
        result = {'status': 'unknown', 'taskId': task_id}
        while True:
            rows = [row for row in adapter._task_rows(drawer) if re.search(r'(?<!\d)' + re.escape(task_id) + r'(?!\d)', row)]
            if len(rows) == 1: result = adapter.parse_short_title_task(rows[0], validation['rowCount'], task_id)
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

def import_short_title_batch(adapter, profile_dir: str, workbook: str, *, wait_ms: int=12000, dry_run: bool=False,
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
    from pop_title_io import FileLock
    with FileLock(Path(str(receipt_path)+'.lock'), timeout=45), adapter.browser_profile_lock(profile_dir):
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
        sync_playwright = adapter._playwright()
        with sync_playwright() as playwright:
            return adapter._visit_title_batch(playwright,profile_dir,path,content,receipt_path,saved,validation,wait_ms,dry_run,
                                      expected_shop_name,expected_shop_id,poll_seconds)

def _import_options(args, seller):
    return {'expected_shop_name':seller['shopName'],'expected_shop_id':seller['shopId'],
            'poll_seconds':getattr(args,'title_poll_seconds',60)}

def import_delivery(args, files, seller, agent, export_reports=()):
    from itertools import groupby
    from pop_title_io import file_sha
    from pop_browser import import_short_titles, submit_title_source, completed_batch, _import_short_title_batch
    from pop_title_batches import prepare_import_batches, PriorImportReceipt
    options = _import_options(args, seller)
    original={Path(r['path']).resolve():r['sha256'] for r in export_reports if r.get('path') and r.get('sha256')}
    for filename in files:
        path=Path(filename).resolve()
        if path in original and file_sha(path)!=original[path]:
            raise ValueError(f'短标题留档与原导出回执的 SHA256 不符，本次未提交：{path}')
    try:
        batches = prepare_import_batches(files, args.output_dir, agent=agent)
    except PriorImportReceipt as original:
        checked = _import_short_title_batch(str(args.profile_dir),str(original.workbook_path),**options,
                                            expected_sha256=original.sha256,receipt_path=original.receipt_path,reconcile_only=True)
        return {'status':'prior-batch-reconciliation','imports':[checked], 'originalReceipt':str(original.receipt_path),
                'successRows':0,'failedRows':0,'nextAction':'Reconcile the original batch before changing its scope'}
    if any(original.get(Path(b['sourcePath']).resolve(),b['sourceSha256'])!=b['sourceSha256'] for b in batches):
        raise ValueError('短标题留档在规划期间发生变化，本次未提交')
    result={'plannedBatches':list(batches),'imports':[],'successRows':0,'failedRows':0,
            'rowCount':sum(b['rowCount'] for b in batches),'status':'import-completed'}
    offset=0
    for source,group in groupby(batches,key=lambda b:b['sourcePath']):
        group=list(group)
        try:
            part=submit_title_source(str(args.profile_dir),group,import_short_titles,options)
        except (OSError,ValueError) as error:
            result.update(status='blocked-import',reason=str(error)[:400])
            break
        result['plannedBatches'][offset:offset+len(group)]=part['plannedBatches']
        offset+=len(group)
        result['imports'].extend(part['imports'])
        result['successRows']+=part.get('successRows',0)
        result['failedRows']+=part.get('failedRows',0)
        if (part['status'] not in ('import-completed','import-failed') or len(part['imports'])!=len(part['plannedBatches'])
                or not all(completed_batch(r,r['rowCount']) for r in part['imports'])):
            reason=part.get('reason') or (part['imports'][-1].get('reason') if part['imports'] else '')
            result.update(status=part['status'],reason=reason or '原导入批次尚未全部对账')
            break
    else:
        result['status']='import-failed' if result['failedRows'] else 'import-completed'
    result['plannedBatchCount']=len(batches)
    return result
