"""Receipt-backed orchestration for POP shop maintenance. Imports are lazy to retain offline commands."""
from pathlib import Path
import hashlib
import json


# The two-shop title copier uses these workbook readers and import functions directly.
from pop_title_dispatch import import_delivery as _import_delivery
from pop_title_workflow import _workbook_titles, repair_failed_title_rows


def complete_short_title_import(args, delivery, seller, client, agent=None):
    from heideng_merchant.mature_runtime import registered_browser_profile
    from pop_title_workflow import complete_short_title_import as complete
    return complete(args,delivery,seller,client,agent,
        product_ids=getattr(args,'_maintenance_product_ids',None), sku_ids=getattr(args,'_maintenance_sku_ids',None),
        resolve_profile=registered_browser_profile,repair_handler=repair_failed_title_rows)


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
