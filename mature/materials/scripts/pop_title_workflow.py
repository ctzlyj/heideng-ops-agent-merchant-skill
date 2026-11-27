"""Complete and repair imported titles against the original batch receipts."""
from pathlib import Path
import hashlib
import json
from pop_title_dispatch import import_delivery as _import_delivery

def _workbook_titles(path):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet=book['Sheet1']
        sheet.reset_dimensions()
        return {str(sku):str(title) for sku,title in sheet.iter_rows(min_row=3,max_col=2,values_only=True) if sku}
    finally:
        book.close()

def _strip_words(title,words):
    for word in sorted(words,key=len,reverse=True):title=title.replace(word,'')
    return ' '.join(title.split())

def repair_failed_title_rows(args,imports,files,seller,agent):
    from pop_browser import short_title_row_failures, sensitive_words, batch_receipt_path
    from pop_safety import atomic_json
    from pop_title_batches import save_import_workbook
    from pop_title_io import FileLock
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

def complete_short_title_import(args, delivery, seller, client, agent=None, *, product_ids=None, sku_ids=None, resolve_profile=None, repair_handler=None):
    if agent is None:
        import jd_material_agent as agent
    files=delivery.get('shortTitleFiles') or []
    result={**delivery,'manualImportRequired':False,'platformTitleImportVerified':False,'imports':[]}
    incomplete = bool(delivery.get('missingSkuIds')) or delivery.get('plannedRowCount',delivery.get('rowCount',0)) > delivery.get('rowCount',0)
    if not files:
        result['status']='partial-titles' if incomplete else 'no-titles'
        return result
    if not getattr(args,'profile_dir',None) and resolve_profile is not None:
        directory=resolve_profile(getattr(args,'profile',None),seller)
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
            repair=(repair_handler or repair_failed_title_rows)(args,result['imports'],files,seller,agent)
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
        audit=agent.audit_pop_coverage(client,seller['shopName'], product_ids=product_ids, authorized_sku_ids=sku_ids)
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
