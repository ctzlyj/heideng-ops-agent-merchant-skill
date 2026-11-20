"""Exact receipt and per-SKU write safety. No browser, credentials or side effects."""
import copy
import hashlib
import json
import time
import uuid
from pathlib import Path

def fingerprint(body):
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

def missing_only_requests(requests, snapshot):
    result=[]
    for source in requests:
        request=copy.deepcopy(source);kind=int(request['materialType']);entries=[];preserved={}
        for row in request['body']['skuMaterials']:
            sku=str(row['skuId'])
            if sku not in snapshot:raise ValueError('Incomplete exact SKU readback; do not write')
            old=[m for m in snapshot[sku] if int(m.get('materialType') or 0)==kind]
            orders=[int(m.get('order') or 0) for m in old]
            if len(set(orders))!=len(orders):raise ValueError('Duplicate remote material slots; do not write')
            if any(int(m.get('status') or 0) not in (3,4,5) for m in old):raise ValueError('Unknown remote status; reconcile before writing')
            targets=[m for m in row['materials'] if int(m['order']) not in orders]
            if not targets:continue
            if kind == 1002:
                # This endpoint replaces and reindexes the SKU's entire selling-point group.
                # Carry forward the exact approved values whenever a missing point is added.
                if any(int(item.get('status') or 0) != 4 for item in old):
                    continue
                group = list(targets)
                for item in old:
                    contents = (item.get('textMaterial') or {}).get('contents') or []
                    if len(contents) != 1 or not isinstance(contents[0], str) or not contents[0]:
                        raise ValueError('Approved selling point contents cannot be preserved')
                    group.append({'skuId': row['skuId'], 'materialType': kind, 'order': int(item['order']),
                                  'textMaterial': {'contents': [contents[0]]}})
                targets = sorted(group, key=lambda item: int(item['order']))
                if not 2 <= len(targets) <= 3 or [int(item['order']) for item in targets] != list(range(1, len(targets) + 1)):
                    raise ValueError('Selling points must be a complete ordered 2-3 point group')
                old = []
            entries.append({**row,'materials':targets});preserved[sku]=old
        if not entries:continue
        request['fullSiblingSkuIds']=list(source['skuIds'])
        request['skuIds']=[str(row['skuId']) for row in entries]
        request['preservedMaterialsBySku']=preserved
        request['body']={'skuMaterials':entries};request['fingerprint']=fingerprint(request['body'])
        result.append(request)
    return result

def receipt_request(spu_id, material_type, receipt):
    request=receipt.get('request')
    if request:return request
    chunks=receipt.get('chunks') or []
    rows=[row for chunk in chunks for row in (chunk.get('body') or {}).get('skuMaterials',[])]
    if not rows:return None
    body={'skuMaterials':rows}
    if receipt.get('fingerprint') and receipt['fingerprint']!=fingerprint(body):return None
    return {'spuId':spu_id,'materialType':int(material_type),'skuIds':[str(r['skuId']) for r in rows],
            'body':body,'fingerprint':fingerprint(body),'preservedMaterialsBySku':receipt.get('preservedMaterialsBySku')}

def _zone_image_match(client,name,entry,file,agent):
    # Read-only proof for a lost upload response: exactly one image-space file with this
    # unique run filename, identical byte size, created no earlier than our submission.
    finder=getattr(client,'find_zone_images',None)
    if finder is None or not file.is_file() or entry.get('sha256')!=agent._file_sha256(file):return ''
    try:rows=[r for r in finder(name) if r.get('imgName')==name]
    except Exception:return ''
    if len(rows)!=1:return ''
    row=rows[0];submitted=int(entry.get('submittedAt') or 0)*1000
    if int(row.get('imgSize') or -1)!=file.stat().st_size or not submitted or int(row.get('createdTime') or 0)<submitted:return ''
    try:return agent._jd_image_url(row.get('imgUrl'))
    except ValueError:return ''

def reconcile(client, output_dir, agent):
    output=agent.Path(output_dir);uploads=[];bindings=[];unknown_uploads=[];unknown_bindings=[]
    plan=output/agent.AUTO_MAINTAIN_PLAN_NAME
    if plan.exists():
        frozen=json.loads(plan.read_text(encoding='utf-8'))
        if frozen.get('planHash')!=agent._auto_maintain_plan_hash(frozen):raise ValueError('Frozen reconciliation plan changed')
        if frozen.get('shopIdentity')!=agent._shop_identity(client.seller_info()):raise ValueError('Reconciliation shop does not match the frozen run')
    for batch in sorted(output.glob('批次*')):
        state_path=batch/'.state/task.json';ledger_path=batch/'.state/upload-ledger.json'
        if not state_path.is_file():continue
        state=agent._load_state(state_path);ledger=agent._load_upload_ledger(ledger_path)
        for name,entry in ledger['files'].items():
            if entry.get('status') not in {'intent','unknown'}:continue
            # The material-space upload is separate from SKU binding. A same-type SKU URL
            # never proves this upload happened. Require the saved original upload response.
            response=entry.get('receipt') or {};url=response.get('imgUrl');file=batch/'全部图片'/name
            try:
                confirmed=bool(response.get('imgName')==name and url and file.is_file() and
                               entry.get('sha256')==agent._file_sha256(file))
                if confirmed:
                    url=agent._jd_image_url(url)
                    if not url:confirmed=False
            except ValueError:confirmed=False
            if not confirmed:
                url=_zone_image_match(client,name,entry,file,agent)
                confirmed=bool(url)
            if confirmed:
                entry.update(status='accepted',url=url,reconciledAt=int(agent.time.time()));uploads.append({'file':name,'url':url})
                parsed=agent._kind_from_filename(name)
                if parsed:state['jobs'].setdefault(parsed[0],{}).setdefault('uploaded_urls',{})[parsed[1]]=url
            else:
                entry['status']='unknown';unknown_uploads.append(name)
        agent._save_upload_ledger(ledger_path,ledger)
        for spu,item in state.get('jobs',{}).items():
            for kind,receipt in (item.get('material_bindings') or {}).items():
                if not kind.isdigit() or receipt.get('status') not in {'intent','unknown','submitted'}:continue
                request=receipt_request(spu,kind,receipt)
                reason='Original exact request unavailable'
                status='unknown'
                if request:
                    if request.get('fingerprint') and request['fingerprint']!=fingerprint(request['body']):
                        reason='Saved request fingerprint mismatch'
                    else:
                        ids=request['skuIds'];scope=2 if int(kind)==1002 else 1
                        try:
                            # Platform readback returns at most50 SKUs per request.
                            rows=[row for start in range(0,len(ids),50) for row in client.sku_materials(ids[start:start+50],[int(kind)],scope)]
                            returned=[str(r.get('skuId')) for r in rows]
                            if len(returned)!=len(ids) or set(returned)!=set(ids):raise ValueError('Incomplete exact SKU readback')
                            status,reason=agent._evaluate_binding_request(request,{str(r['skuId']):r.get('materials',[]) for r in rows})
                            if status=='mismatch':status='unknown'
                            elif status=='failed':status='rejected'
                        except Exception:
                            status='unknown';reason='Exact platform readback unavailable or incomplete'
                receipt.update(status=status,reason=reason,reconciledAt=int(agent.time.time()))
                if status=='unknown':unknown_bindings.append({'spuId':spu,'materialType':int(kind),'reason':reason})
                else:bindings.append({'spuId':spu,'materialType':int(kind),'status':status})
        agent._save_state(state_path,state)
    return {'reconciledUploads':uploads,'reconciledBindings':bindings,'unresolvedUploads':unknown_uploads,'unresolvedBindings':unknown_bindings}


def atomic_json(path,value,*,compact=False):
    """Only retries a local atomic rename; never retries a network submission."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    text=json.dumps(value,ensure_ascii=False,separators=(',',':')) if compact else json.dumps(value,ensure_ascii=False,indent=2)
    temporary.write_text(text+'\n',encoding='utf-8')
    for attempt in range(4):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==3:raise
            time.sleep(0.1*(attempt+1))
