"""Receipt-backed orchestration for POP shop maintenance. Imports are lazy to retain offline commands."""
from pathlib import Path
import json

def complete_short_title_import(args, delivery, seller, client, agent=None):
    if agent is None:
        import jd_material_agent as agent
    files=delivery.get('shortTitleFiles') or []
    result={**delivery,'manualImportRequired':False,'platformTitleImportVerified':False,'imports':[]}
    incomplete = bool(delivery.get('missingSkuIds')) or delivery.get('plannedRowCount',delivery.get('rowCount',0)) > delivery.get('rowCount',0)
    if not files:
        result['status']='partial-titles' if incomplete else 'no-titles';return result
    if not getattr(args,'profile_dir',None):
        from heideng_merchant.mature_runtime import registered_browser_profile
        directory=registered_browser_profile(getattr(args,'profile',None),seller)
        if directory:args.profile_dir=str(directory)
    if not getattr(args,'profile_dir',None):
        result.update(status='blocked-browser-profile',nextAction='Provide this verified shop browser --profile-dir to finish automatic import; do not ask the user to reupload a delivered table.')
        return result
    from pop_browser import import_short_titles
    from openpyxl import load_workbook
    import hashlib
    import_files=[]
    for path in files:
        if not Path(path).is_file():
            import_files.append(path)
            continue
        book=load_workbook(path,read_only=True,data_only=True)
        rows=[(str(row[0]),str(row[1])) for row in book.active.iter_rows(min_row=3,values_only=True) if row and row[0]];book.close()
        if len(rows)<=5000:
            import_files.append(path)
            continue
        for offset in range(0,len(rows),5000):
            content=agent._short_title_workbook_bytes(rows[offset:offset+5000])
            chunk=Path(args.output_dir)/'.state/title-import-chunks'/(hashlib.sha256(content).hexdigest()[:20]+'.xlsx')
            chunk.parent.mkdir(parents=True,exist_ok=True)
            if chunk.exists() and chunk.read_bytes()!=content:raise ValueError('Import chunk was edited; preserve and reconcile')
            if not chunk.exists():chunk.write_bytes(content)
            import_files.append(str(chunk))
    for path in import_files:
        try:
            receipt=import_short_titles(str(args.profile_dir),path,expected_shop_name=seller['shopName'],expected_shop_id=seller['shopId'],poll_seconds=getattr(args,'title_poll_seconds',60))
        except Exception as error:
            receipt={'status':'blocked-import','failureClass':type(error).__name__,'reason':'Import/login/task readback failed; inspect owned receipt before retrying'}
        result['imports'].append(receipt)
        # A finished task with a few platform-rejected rows must not block later chunks;
        # only an unknown/refused/pending task stops (no replay of an uncertain write).
        row_failures=receipt['status']=='import-failed' and receipt.get('creationAccepted') and receipt.get('taskId') and int(receipt.get('successRows') or 0)>0
        if receipt['status']!='import-completed' and not row_failures:
            result['status']=receipt['status'];return result
    failed_rows=sum(int(r.get('failedRows') or 0) for r in result['imports'] if r['status']=='import-failed')
    if failed_rows:
        # One automatic repair pass: rewrite only the rejected rows (e.g. sensitive words) and import them.
        try:
            repair=repair_failed_title_rows(args,result['imports'],files,seller,agent)
            result['rowRepair']=repair
            if repair.get('receipt',{}).get('status')=='import-completed':failed_rows=max(0,failed_rows-repair['rows'])
            elif repair.get('receipt',{}).get('status')=='import-failed':failed_rows=max(0,failed_rows-int(repair['receipt'].get('successRows') or 0))
        except Exception as error:
            result['rowRepair']={'status':'blocked','failureClass':type(error).__name__,'reason':str(error)[:200]}
    result['status']='import-completed-with-row-failures' if failed_rows else 'import-completed-awaiting-review'
    if failed_rows:result['platformFailedRows']=failed_rows
    try:
        audit=agent.audit_pop_coverage(client,seller['shopName'], product_ids=getattr(args,'_maintenance_product_ids',None), authorized_sku_ids=getattr(args,'_maintenance_sku_ids',None))
        from openpyxl import load_workbook
        target=set()
        for path in files:
            if not Path(path).is_file():continue
            book=load_workbook(path,read_only=True,data_only=True)
            target.update(str(row[0]) for row in book.active.iter_rows(min_row=3,values_only=True) if row and row[0]);book.close()
        issues=set(audit.get('shortTitleIssueSkuIds') or [])
        # Task counts prove import processing; health readback separately proves title acceptance.
        if target and not issues.intersection(target) and not set(audit.get('unscoredSkuIds') or []).intersection(target) and target.issubset({str(r['skuId']) for r in audit.get('rows',[])}):
            result.update(status='verified',platformTitleImportVerified=True,deliveryMessage='Short titles were imported and platform issues cleared; files are archive copies, not a request for manual upload.')
    except Exception:
        result['nextAction']='Import task completed; platform verification unavailable, do not resubmit.'
    if incomplete:
        result.update(status='partial-titles', platformTitleImportVerified=False, nextAction='Some frozen planned SKU titles are missing; complete only missing rows before claiming full verification')
    return result


def _strip_words(title,words):
    for word in sorted(words,key=len,reverse=True):title=title.replace(word,'')
    return ' '.join(title.split())

def repair_failed_title_rows(args,imports,files,seller,agent):
    from pop_browser import short_title_row_failures,sensitive_words,import_short_titles
    from openpyxl import load_workbook
    import hashlib
    titles={}
    for path in files:
        book=load_workbook(path,read_only=True,data_only=True)
        titles.update({str(r[0]):str(r[1]) for r in book.active.iter_rows(min_row=3,values_only=True) if r and r[0]});book.close()
    failures={}
    for receipt in imports:
        if receipt.get('status')=='import-failed' and receipt.get('resultFileUrl'):failures.update(short_title_row_failures(receipt['resultFileUrl']))
    fixed={};left={}
    used=set(titles.values())
    for sku,reason in failures.items():
        words=sensitive_words(reason);old=titles.get(sku,'')
        candidate=_strip_words(old,words) if words else ''
        if candidate and agent.valid_short_title(candidate) and candidate not in used and not any(w in candidate for w in words):
            fixed[sku]=candidate;used.add(candidate)
        else:left[sku]=reason
    out={'failedRows':len(failures),'rows':len(fixed),'unresolved':left}
    if not fixed:return out
    content=agent._short_title_workbook_bytes(sorted(fixed.items()))
    path=Path(args.output_dir)/'.state/title-import-chunks'/('repair-'+hashlib.sha256(content).hexdigest()[:16]+'.xlsx')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(content)
    out['receipt']=import_short_titles(str(args.profile_dir),str(path),expected_shop_name=seller['shopName'],expected_shop_id=seller['shopId'],poll_seconds=getattr(args,'title_poll_seconds',60))
    return out

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
