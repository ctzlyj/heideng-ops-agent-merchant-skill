"""Receipt-backed orchestration for POP shop maintenance. Imports are lazy to retain offline commands."""
from pathlib import Path
import hashlib
import json


def _workbook_titles(path):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet=book['Sheet1']
        sheet.reset_dimensions()
        return {str(sku):str(title) for sku,title in sheet.iter_rows(min_row=3,max_col=2,values_only=True) if sku}
    finally:
        book.close()


def _import_options(args, seller):
    return {'expected_shop_name':seller['shopName'],'expected_shop_id':seller['shopId'],
            'poll_seconds':getattr(args,'title_poll_seconds',60)}


def _import_delivery(args, files, seller, agent, export_reports=()):
    from itertools import groupby
    from heideng_merchant.safety import file_sha
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


def complete_short_title_import(args, delivery, seller, client, agent=None):
    if agent is None:
        import jd_material_agent as agent
    files=delivery.get('shortTitleFiles') or []
    result={**delivery,'manualImportRequired':False,'platformTitleImportVerified':False,'imports':[]}
    incomplete = bool(delivery.get('missingSkuIds')) or delivery.get('plannedRowCount',delivery.get('rowCount',0)) > delivery.get('rowCount',0)
    if not files:
        result['status']='partial-titles' if incomplete else 'no-titles'
        return result
    if not getattr(args,'profile_dir',None):
        from heideng_merchant.mature_runtime import registered_browser_profile
        directory=registered_browser_profile(getattr(args,'profile',None),seller)
        if directory:args.profile_dir=str(directory)
    if not getattr(args,'profile_dir',None):
        result.update(status='blocked-browser-profile',nextAction='Provide this verified shop browser --profile-dir to finish automatic import; do not ask the user to reupload a delivered table.')
        return result
    try:
        submitted=_import_delivery(args,files,seller,agent,delivery.get('files') or ())
    except (ValueError,OSError) as error:
        return {**result,'status':'blocked-import','failureClass':type(error).__name__,'reason':str(error)[:400]}
    result.update(submitted)
    result['preparedRows']=sum(b['rowCount'] for b in submitted.get('plannedBatches',[]))
    result['platformAcceptedRows']=sum(r['rowCount'] for r in result['imports'] if r.get('creationAccepted') is True)
    if result['imports'] and result['imports'][-1].get('nextAction'):
        result['nextAction']=result['imports'][-1]['nextAction']
    from pop_browser import completed_batch
    if (submitted['status'] not in ('import-completed','import-failed') or
            len(result['imports'])!=len(submitted['plannedBatches']) or
            not all(completed_batch(r,r['rowCount']) for r in result['imports'])):
        return result
    failed_rows=submitted['failedRows']
    if failed_rows:
        result['initialImportCounts']={'successRows':submitted['successRows'],'failedRows':failed_rows}
        try:
            repair=repair_failed_title_rows(args,result['imports'],files,seller,agent)
        except Exception as error:
            reason=str(error)[:400] if isinstance(error,(ValueError,OSError)) else '原失败行的明细或回执暂不可核验，请沿原任务继续'
            repair={'status':'blocked','failureClass':type(error).__name__,'reason':reason}
        result['rowRepair']=repair
        attempts=repair.get('imports',[])
        repaired=sum(r['successRows'] for r in attempts if completed_batch(r,r.get('rowCount')))
        unconfirmed=sum(r.get('rowCount',0) for r in attempts
                        if not completed_batch(r,r.get('rowCount')) and r.get('dispatchState')!='before-upload'
                        and not r.get('createRefused') and r.get('status')!='upload-refused')
        if repair.get('status')=='prior-batch-reconciliation':
            repaired=0
            unconfirmed=repair.get('rows',0)
        failed_rows-=repaired
        unconfirmed=min(unconfirmed,failed_rows)
        result.update(successRows=submitted['successRows']+repaired,failedRows=failed_rows-unconfirmed,
                      platformFailedRows=failed_rows-unconfirmed,unresolvedRows=failed_rows,unconfirmedRepairRows=unconfirmed)
        if failed_rows:
            result.update(status='import-completed-with-row-failures')
            if repair.get('status') in ('unknown','import-pending','blocked-import','prior-batch-reconciliation','blocked'):
                result.update(status=repair['status'],nextAction='Reconcile the original repair batch before retrying',
                              reason=repair.get('reason') or '返修批次尚未全部核对，请沿原回执继续')
            return result
    result['status']='import-completed-awaiting-review'
    if incomplete:
        result.update(status='partial-titles',nextAction='Some frozen planned SKU titles are missing; complete only missing rows')
        return result
    try:
        audit=agent.audit_pop_coverage(client,seller['shopName'], product_ids=getattr(args,'_maintenance_product_ids',None), authorized_sku_ids=getattr(args,'_maintenance_sku_ids',None))
        target=set()
        for batch in submitted['plannedBatches']:
            path=Path(batch['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=batch['sha256']:
                return result
            target.update(_workbook_titles(path))
        issues=set(audit.get('shortTitleIssueSkuIds') or [])
        if target and not issues.intersection(target) and not set(audit.get('unscoredSkuIds') or []).intersection(target) and target.issubset({str(r['skuId']) for r in audit.get('rows',[])}):
            result.update(status='verified',platformTitleImportVerified=True,deliveryMessage='Short titles were imported and platform issues cleared; files are archive copies, not a request for manual upload.')
    except Exception:
        result['nextAction']='Import task completed; platform verification unavailable, do not resubmit.'
    return result


def _strip_words(title,words):
    for word in sorted(words,key=len,reverse=True):title=title.replace(word,'')
    return ' '.join(title.split())


def repair_failed_title_rows(args,imports,files,seller,agent):
    from pop_browser import short_title_row_failures, sensitive_words, batch_receipt_path
    from pop_safety import atomic_json
    from pop_title_batches import save_import_workbook
    from heideng_merchant.state import FileLock
    # A single repair pass is tied to the original shop and platform tasks. Changing
    # or expiring result URLs on a later run cannot create a second repair plan.
    scope={'shopName':seller['shopName'],'shopId':str(seller['shopId']),
           'batches':[[r['sha256'],r['taskId']] for r in imports]}
    digest=hashlib.sha256(json.dumps(scope,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    directory=Path(args.output_dir)/'.state/title-import-chunks'
    plan=directory/('repair-plan-'+digest+'.json')
    with FileLock(plan.with_suffix('.lock'),timeout=45):
        if plan.exists():
            out=json.loads(plan.read_text(encoding='utf-8'))
            if out.get('scope')!=scope:raise ValueError('Repair scope changed')
            path=directory/('repair-'+out['sha256'][:16]+'.xlsx')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=out['sha256']:
                raise ValueError('Original repair workbook changed')
        else:
            fixed={}; left={}; used=set(); evidence={}; originals={}
            for receipt in imports:
                path=Path(receipt['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['sha256']:
                    raise ValueError('Original submitted workbook changed')
                rows=_workbook_titles(path)
                originals.update(rows)
                used.update(rows.values())
                if receipt['status']!='import-failed' or not receipt.get('resultFileUrl'):
                    continue
                failures=short_title_row_failures(receipt['resultFileUrl'])
                if len(failures)>receipt['failedRows'] or not set(failures).issubset(rows):
                    raise ValueError('Platform failed rows do not match their original import batch')
                evidence.update(failures)
            for sku,old in originals.items():
                if sku not in evidence:continue
                reason=evidence[sku]
                words=[word for word in sensitive_words(reason) if word and word in old]
                candidate=_strip_words(old,words) if words else ''
                if candidate and candidate!=old and agent.valid_short_title(candidate) and candidate not in used and not any(word in candidate for word in words):
                    fixed[sku]=candidate;used.add(candidate)
                else:left[sku]=reason
            out={'failedRows':sum(r['failedRows'] for r in imports),'evidencedRows':len(evidence),
                 'rows':len(fixed),'unresolved':left,'scope':scope}
            if not fixed:return {**out,'status':'no-repairable-rows','imports':[]}
            content=agent._short_title_workbook_bytes(list(fixed.items()))
            if list(fixed)!=sorted(fixed):
                old_content=agent._short_title_workbook_bytes(sorted(fixed.items()))
                old_hash=hashlib.sha256(old_content).hexdigest()
                old_path=directory/('repair-'+old_hash[:16]+'.xlsx')
                if old_path.exists() and batch_receipt_path(old_path,old_hash).exists():
                    content=old_content
            out['sha256']=hashlib.sha256(content).hexdigest()
            path=directory/('repair-'+out['sha256'][:16]+'.xlsx')
            save_import_workbook(path,content)
            atomic_json(plan,out)
        submission=_import_delivery(args,[str(path)],seller,agent)
        return {**out,'status':submission['status'],'reason':submission.get('reason',''),'plannedBatches':submission.get('plannedBatches',[]),
                'imports':submission['imports'],'receipt':submission['imports'][0] if len(submission.get('plannedBatches',[]))==1 and submission['imports'] else submission}

def finish_external_images(args,handoff,seller,client,agent):
    if not handoff:return {'status':'no-external-images','tasks':[],'blocked':[]}
    from pop_browser import submit_batch_cutout
    from pop_safety import fingerprint
    ids=sorted({str(s) for e in handoff for s in e['skuIds']})
    if not getattr(args,'profile_dir',None):
        return {'status':'blocked-external-images','tasks':[],'blocked':[{'reason':'Own verified --profile-dir required for exact batch fallback; no browser write was attempted'}]}
    try: current=agent._query_binding_materials(client,ids)
    except Exception as error:
        return {'status':'blocked-external-images','tasks':[],'blocked':[{'reason':'Complete platform readback unavailable; no fallback submission','failureClass':type(error).__name__}]}
    eligible=[];blocked=[]
    for entry in handoff:
        for sku in entry['skuIds']:
            materials=current[str(sku)]
            white=[m for m in materials if int(m.get('materialType') or 0)==31 and int(m.get('order') or 0)==1]
            transparent=[m for m in materials if int(m.get('materialType') or 0)==36 and int(m.get('order') or 0)==1]
            if transparent:continue  # rejected slots belong to the fresh repair strategy
            if white and int(white[0].get('status') or 0)==4:eligible.append(str(sku))
            else:blocked.append({'skuId':str(sku),'reason':'No approved white source; finish model/JoyAgent white or wait for white review'})
    tasks=[]
    if eligible:
        if not getattr(args,'profile_dir',None):blocked.append({'reason':'Own verified browser --profile-dir required for SKU-white cutouts'})
        else:
            receipt=Path(args.output_dir)/'.state'/('batch-'+fingerprint({'skuIds':eligible})[:16]+'.json')
            if receipt.exists():
                saved=json.loads(receipt.read_text(encoding='utf-8'));tasks.append(saved)
                from pop_browser import batch_coverage
                coverage=batch_coverage(eligible,saved.get('chunks',[]))
                if coverage['missingSkuIds'] or saved.get('status')!='task-accepted':blocked.append({'reason':'Batch only partially accepted or unknown; preserve accepted chunks and reconcile before retrying','missingSkuIds':coverage['missingSkuIds']})
            else:
                try:
                    task=submit_batch_cutout(str(args.profile_dir),mode='sku-white',max_pages=max(1,(len(handoff)+9)//10),expected_shop_name=seller['shopName'],expected_shop_id=seller['shopId'],target_sku_ids=eligible,receipt_path=receipt)
                    tasks.append(task)
                    if task['status']!='task-accepted':blocked.append({'reason':'Batch target coverage incomplete','missingSkuIds':task.get('missingSkuIds',[])})
                except Exception as error:blocked.append({'reason':'Batch submission not proven accepted','failureClass':type(error).__name__})
    return {'status':'blocked-external-images' if blocked else 'external-images-submitted' if tasks else 'no-external-images','tasks':tasks,'blocked':blocked}
