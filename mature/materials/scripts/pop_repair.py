"""Reviewed fresh-byte rejected-slot repair with exact, durable submission receipts."""
import hashlib
import json
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event

def _save(path, value):
    from pop_safety import atomic_json
    atomic_json(path, value)


def repair_references(rows, sources, overrides, granularity='spu'):
    """Use one evidenced representative per SPU unless SKU scope was requested."""
    def source(sku):
        return str(overrides.get(sku) or sources.get(sku, {}).get('logo') or '')

    result = {}
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row['productId']), []).append(str(row['skuId']))
    for skus in grouped.values():
        explicit = {str(overrides[sku]) for sku in skus if sku in overrides}
        if granularity == 'spu' and len(explicit) > 1:
            raise ValueError('同一 SPU 的指定参考图存在冲突，请明确一张代表图或选择逐 SKU。')
        representative = next((sku for sku in skus if sku in overrides),
                              next((sku for sku in skus if source(sku)), skus[0]))
        for sku in skus:
            chosen = representative if granularity == 'spu' else sku
            reference = source(chosen) or chosen
            result[sku] = (chosen, f'sku:{sku}|{reference}' if granularity == 'sku' else reference)
    return result


def repair_request_budget(output, limit, error_type):
    """Persist dispatch reservations; the repair run and model already hold their write locks."""
    path = output / 'image-request-budget.json'
    if path.exists():
        budget = json.loads(path.read_text(encoding='utf-8'))
    else:
        attempted = sum(json.loads(receipt.read_text(encoding='utf-8')).get('status') in
                        {'received', 'intent', 'unknown', 'rejected'}
                        for receipt in (output / 'shared').glob('*/*.request.json'))
        budget = {'reserved': attempted, 'limit': limit}

    if limit is not None:
        budget['limit'] = limit
    _save(path, budget)

    def reserve():
        maximum = budget['limit']
        if maximum is not None and budget['reserved'] >= maximum:
            raise error_type('model-request-budget-exhausted；同一任务的累计请求额度已用完。')
        budget['reserved'] += 1
        _save(path, budget)

    return reserve, budget

def request_repair_image(agent, model, kind, prompt, reference, adapter, temporary, timeout, *, repair_scope=None):
    # One paid response receipt, reusing the existing repair directory; no automatic re-submission.
    temporary=Path(temporary);path=temporary.with_suffix('.request.json')
    source=Path(reference)
    identity=hashlib.sha256(json.dumps([kind,prompt,str(source.resolve()),agent._file_sha256(source) if source.is_file() else None,adapter],ensure_ascii=False).encode()).hexdigest()
    saved=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if saved and saved.get('fingerprint')!=identity:raise agent.JdoWriteUncertainError('原图片请求输入已改变，先核对原回执，不重提。')
    if saved.get('status')=='received':
        if temporary.is_file() and agent._file_sha256(temporary)==saved.get('sha256'):return temporary.read_bytes()
        raise agent.JdoWriteUncertainError('原图片响应文件缺失或改变，未再次付费。')
    if saved.get('status') in ('intent','unknown'):raise agent.JdoWriteUncertainError('原图片请求结果待核对，未再次付费。')
    if saved.get('status')=='rejected':raise ValueError('原请求已明确审核拒绝；由Agent设计新提示词，不重复旧请求。')
    if model is None:
        raise agent.ModelRequestLimitError('当前维修范围没有新增生图批准；请先核对缺项')
    selected = model.select_image_model() if callable(getattr(type(model),'select_image_model',None)) else 'gpt-image-2.5'
    _save(temporary.with_suffix('.prompt.json'),{'fingerprint':identity,'kind':kind,'prompt':prompt,'model':selected})
    saved={'status':'intent','fingerprint':identity,'model':selected,'size':agent.MATERIAL_IMAGE_SIZE}
    if repair_scope:saved['repairScope']=repair_scope
    _save(path,saved)
    try:
        content = agent.request_material_image(model,kind,prompt,source,model=selected)
    except agent.ModelModerationBlocked:
        _save(path,{**saved,'status':'rejected'});raise
    except agent.ModelRequestLimitError:
        _save(path,{**saved,'status':'not-dispatched'});raise
    except Exception:
        _save(path,{**saved,'status':'unknown'})
        raise agent.JdoWriteUncertainError('原图片请求结果待核对，不切换模型重复发送。') from None
    temporary.write_bytes(content)
    _save(path,{**saved,'status':'received','sha256':agent._file_sha256(temporary)})
    return content

def assert_no_unresolved_images(receipts, spu, kind, sku_ids, agent):
    family=lambda k:'white' if k in ('white','transparent') else k
    for receipt in receipts:
        scope=receipt.get('repairScope') or {}
        if not scope or (str(scope.get('spuId'))==str(spu) and family(scope.get('kind'))==family(kind) and set(map(str,scope.get('skuIds') or [])) & set(map(str,sku_ids))):
            raise agent.JdoWriteUncertainError('同槽位原图片请求未确认；更换参考图不能绕过原回执重提。')

def submit_repair_request(client,request,path,agent):
    from pop_safety import fingerprint
    path=Path(path);request={**request,'fingerprint':fingerprint(request['body'])}
    saved=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if saved and saved.get('request')!=request:raise agent.JdoWriteUncertainError('Repair request changed; preserve original receipt')
    if not saved:
        saved={'status':'intent','request':request};_save(path,saved)
        try:
            response=client.bind_sku_materials(request['body'])
            saved.update(status='submitted',responseAccepted=True);_save(path,saved)
        except agent.JdoPermissionError:
            saved.update(status='rejected',reason='Official permission denied');_save(path,saved);raise
        except Exception:
            saved.update(status='unknown',reason='Submission result unknown');_save(path,saved)
    try:
        ids=request['skuIds'];rows=[row for start in range(0,len(ids),50) for row in client.sku_materials(ids[start:start+50],[request['materialType']],2 if int(request['materialType'])==1002 else 1)]
        returned=[str(r.get('skuId')) for r in rows]
        if len(returned)!=len(ids) or set(returned)!=set(ids):raise ValueError('Incomplete repair readback')
        status,reason=agent._evaluate_binding_request(request,{str(r['skuId']):r.get('materials',[]) for r in rows})
        if status=='mismatch':status='unknown'
        if status=='failed':status='rejected'
    except Exception:status,reason='unknown','Exact repair readback unavailable'
    saved.update(status=status,reason=reason);_save(path,saved)
    if status=='unknown':raise agent.JdoWriteUncertainError('Unknown repair result; do not replay')
    return saved

def read_repair_status(client, directory, agent):
    """Read the original bound values by SKU without reconstructing or submitting a write."""
    from heideng_merchant.safety import read_json
    identity = agent._shop_identity(client.seller_info())
    scope = read_json(directory / 'repair-scope.json', {})
    if identity != scope.get('shopIdentity'):
        raise ValueError('原任务与当前官方店铺身份不一致')
    receipt_paths = sorted((directory / 'shared-bindings').glob('*.json'))
    receipt_paths += sorted(directory.glob('*/*-binding.json'))
    rows = []
    for path in receipt_paths:
        saved = read_json(path, {})
        request = saved.get('request', {})
        sku_ids = list(map(str, request['skuIds']))
        if not set(sku_ids).issubset(scope['originals']):
            raise ValueError('绑定回执超出原维修范围')
        reads = agent._query_binding_materials(client, sku_ids)
        for sku in sku_ids:
            single = {**request, 'skuIds':[sku]}
            if 'preservedMaterialsBySku' in request:
                single['preservedMaterialsBySku'] = {sku:request['preservedMaterialsBySku'].get(sku, [])}
            status, reason = agent._evaluate_binding_request(single, reads)
            status = {'mismatch':'unknown','failed':'rejected'}.get(status, status)
            rows.append({'skuId':sku,'materialType':request['materialType'],'status':status,
                         'reason':reason,'receipt':str(path)})
    unknown_images = [str(path) for path in (directory/'shared').glob('*/*.request.json')
                      if read_json(path, {}).get('status') in ('intent','unknown')]
    if unknown_images or any(row['status'] == 'unknown' for row in rows):
        status = 'unknown'
    elif not rows:
        status = 'no-binding-receipts'
    elif any(row['status'] == 'rejected' for row in rows):
        status = 'repair-incomplete'
    elif any(row['status'] == 'pending' for row in rows):
        status = 'repairs-submitted-awaiting-review'
    else:
        status = 'verified' if all(row['status'] == 'approved' for row in rows) else 'submitted'
    result = {'status':status,'shopName':identity['shopName'],'shopIdentity':identity,
              'rows':rows,'unknownImageReceipts':unknown_images,'writesPerformed':False,
              'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    _save(directory/'.state/repair-readback.json', result)
    return result


PRODUCT_TEXT_REJECTION='禁止出现文字信息'

def product_text_appeal(kind, slot, override=None, *, current_url=None):
    rejected=kind in {'white','transparent'} and any(PRODUCT_TEXT_REJECTION in str(reason) for reason in slot.get('auditReasons') or [])
    if not rejected:return False
    entry=override or {}
    # The audit reason alone does not prove product printing. Host-reviewed extra generated text
    # can be repaired; actual product printing remains unchanged and goes to appeal.
    reviewed=(entry.get('textOrigin')=='generated' and bool(entry.get('evidence')) and bool(entry.get('rejectedImageUrl')))
    return not (reviewed and (current_url is None or current_url==entry['rejectedImageUrl']))

def scoped_repair_rows(rows, authorized_sku_ids, excluded_bindings, agent, excluded_spu_ids=(), repair_kinds=None, image_prompts=None):
    selected=set(repair_kinds or agent.IMAGE_SUFFIXES)
    if not selected.issubset(agent.IMAGE_SUFFIXES):raise ValueError('未知修复类型，未生成或提交')
    skip_spus={str(s) for s in excluded_spu_ids or ()}
    rows=[r for r in rows if str(r.get('productId')) not in skip_spus]
    allowed=set(map(str,authorized_sku_ids)) if authorized_sku_ids is not None else {str(r['skuId']) for r in rows}
    excluded={(str(spu),int(kind)) for spu,kind in excluded_bindings}
    targets=[]
    for row in rows:
        if str(row['skuId']) not in allowed:continue
        kinds=[k for k in agent.IMAGE_SUFFIXES if k in selected and k in row['slots'] and row['slots'][k]['state']=='rejected' and (str(row['productId']),agent.JDO_MATERIAL_SLOTS[k][0]) not in excluded]
        appeal=[k for k in kinds if product_text_appeal(k,row['slots'][k],(image_prompts or {}).get(str(row['productId']),{}).get(k))]
        if kinds:targets.append({**row,'repairKinds':[k for k in kinds if k not in appeal],'appealKinds':appeal})
    return targets

def export_product_text_appeals(scope, targets, out, agent):
    records=[]
    names={'white':'白底图','transparent':'透明图'}
    for row in targets:
        sku=str(row['skuId'])
        for kind in row.get('appealKinds') or []:
            slot=agent.JDO_MATERIAL_SLOTS[kind];old=[m for m in scope['originals'][sku] if (int(m['materialType']),int(m['order']))==slot][0]
            records.append({'skuId':sku,'productId':str(row['productId']),'skuName':str(row.get('skuName') or ''),'materialType':slot[0],'order':slot[1],'status':5,'materialName':names[kind],'imageUrl':agent._material_value(old),'auditDesc':'；'.join(row['slots'][kind].get('auditReasons') or [])+'（需Agent看图核实文字来源：商品本体印刷误驳回走申诉；模型额外文字由Agent重设本任务提示词修复）'})
    if not records:return None
    report={'shopIdentity':scope['shopIdentity'],'checkedAt':scope.get('checkedAt') or 'frozen-repair-scope','scopeNote':'文字驳回待核实来源，未代发申诉。真实商品印刷保持不变；额外生成文字可按当前任务提示词重新设计。','appealRows':records}
    return agent.export_pop_image_appeals(report,Path(out)/'product-text-appeals')

CUTOUT_DAMAGE='抠图损坏'
CONTENT_REASONS=('文字','人物','模特','肢体','道具','拼接','不完整','模糊','虚化','背景未抠干净','未顶边')

def image_has_text(path, vision):
    """Vision check for any visible text/badges in a regenerated scene image. None = unavailable."""
    if vision is None:return None
    import base64
    raw=Path(path).read_bytes()
    try:
        r=vision.http.post('/chat/completions',json={'model':vision.models[0],'max_tokens':400,'stream':False,'messages':[{'role':'user','content':[
            {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(raw).decode()}},
            {'type':'text','text':'这张商品场景图中，除商品本体自带的印刷外，是否有任何额外文字、数字、标签、徽章、贴片或水印？只输出JSON：{"text":true/false}'}]}]})
        from pop_text import parse_json
        return bool(parse_json((r.json().get('choices') or [{}])[0].get('message',{}).get('content')).get('text'))
    except Exception:
        return None

SCENE_REPAIR_HINT=(' 场景图严禁出现任何文字、数字、标签、价格、卖点贴片、图标、徽章、边框或水印；只有商品与真实环境。'
                   '参考图上的营销文字和贴片不得照搬。')

def white_quality_issues(path):
    """Local pre-upload gate for regenerated white images (platform: 商品不完整/图片模糊/未顶边)."""
    from PIL import Image, ImageFilter
    import numpy as np
    with Image.open(path) as opened:rgb=np.asarray(opened.convert('RGB').resize((800,800))).astype(int)
    fg=(255-rgb).max(axis=2)>18;issues=[]
    if not fg.any():return ['empty']
    ys,xs=np.nonzero(fg);box=(xs.min(),ys.min(),xs.max(),ys.max())
    # Product touching the 100px inset border means the generator cropped it (pure-white canvas is 600px inset).
    if box[0]<=101 or box[1]<=101 or box[2]>=698 or box[3]>=698:
        edge=np.concatenate([fg[101,100:700],fg[698,100:700],fg[100:700,101],fg[100:700,698]])
        if edge.mean()>0.02:issues.append('cropped-edge')
    if fg.mean()<0.06:issues.append('too-small')
    gray=Image.fromarray(rgb.astype('uint8')).convert('L')
    lap=np.asarray(gray.filter(ImageFilter.FIND_EDGES)).astype(float)[fg]
    if lap.size and lap.var()<60:issues.append('blurry')
    return issues

WHITE_REPAIR_HINT=(' 必须展示完整商品，四周留白，商品任何部分不得被画面裁切；画面清晰锐利、无虚化。'
                   '只保留商品本体：去掉衣物、填充物、撒落的纸屑/装饰、手、人物、道具和背景，不能把商品使用状态画进来。')

def transparent_route(row):
    """User routing table for a rejected transparent slot.
    reuse-white   : only 抠图损坏 and white approved -> cut the approved white again (no generation)
    regen-neural  : 抠图损坏 + other reasons -> fresh white + neural cutout
    regen-fast    : content reasons only, or white also rejected -> fresh white + fast legacy cutout"""
    t=row['slots'].get('transparent',{});w=row['slots'].get('white',{})
    reasons=[x for a in t.get('auditReasons') or [] for x in str(a).split(';')]
    damage=any(CUTOUT_DAMAGE in x for x in reasons)
    other=any(CUTOUT_DAMAGE not in x and x.strip() for x in reasons)
    if damage and not other and w.get('state')=='approved':return 'reuse-white'
    if damage:return 'regen-neural'
    return 'regen-fast'

def magenta_cutout(source, output, tolerance=60):
    """Last resort: product generated on pure magenta (#FF00FF) -> colour key to alpha."""
    from PIL import Image
    import numpy as np
    with Image.open(source) as opened:rgb=np.array(opened.convert('RGB').resize((800,800))).astype(int)
    dist=np.sqrt((rgb[...,0]-255)**2+(rgb[...,1])**2+(rgb[...,2]-255)**2)
    alpha=np.clip((dist-tolerance*0.5)/(tolerance*0.5)*255,0,255).astype('uint8')
    # De-spill magenta fringe on semi-transparent edges.
    edge=(alpha>0)&(alpha<255);g=rgb[...,1];rgb[...,0]=np.where(edge,np.minimum(rgb[...,0],g+40),rgb[...,0]);rgb[...,2]=np.where(edge,np.minimum(rgb[...,2],g+40),rgb[...,2])
    if (alpha>0).mean()<0.03 or (alpha==0).mean()<0.05:raise ValueError('magenta key failed: no clear foreground/background split')
    Image.fromarray(np.dstack([rgb.clip(0,255).astype('uint8'),alpha]),'RGBA').save(output,'PNG',optimize=True)
    return {'status':'generated-local','backend':'magenta-key','modelCalls':0}

def jingmai_ledger_path(identity, override=None):
    # Shop-level, across run directories: a slot gets the platform's own cutout once, then neural/model.
    if override:return Path(override)
    return Path.home()/'.jd-material-pop'/'jingmai-first'/(str(identity['venderId'])+'.json')

def jingmai_mode(kinds, white_state):
    kinds=set(kinds)
    if kinds=={'white','transparent'}:return 'white-main+transparent-main'
    if kinds=={'white'}:return 'white-main'
    return 'transparent-sku-white' if white_state=='approved' else 'transparent-main'

def plan_jingmai_first(scoped, scope, ledger):
    """Rejected white/transparent never tried with Jingmai batch cutout -> mode -> {spu:[sku]}."""
    attempts=ledger.get('attempts',{});plans={}
    for row in scoped:
        # Routing table (2026-11-01): Jingmai only for transparent whose sole reason is 抠图损坏 with an
        # approved white; content-rejected white/transparent are regenerated instead.
        sku=str(row['skuId']);kinds=[k for k in row['repairKinds'] if k=='transparent' and transparent_route(row)=='reuse-white' and sku+':'+k not in attempts]
        if not kinds:continue
        mode='transparent-sku-white'
        plans.setdefault(mode,{}).setdefault(str(row['productId']),[]).append(sku)
    return plans

def run_jingmai_first(args, scope, scoped, out, identity, agent, submit=None):
    """Submit Jingmai batch cutout first; return (sku,kind) pairs handled now (excluded from model repair)."""
    from pop_safety import atomic_json
    if submit is None:
        from pop_browser import submit_jingmai_repair_batch as submit
    path=jingmai_ledger_path(identity,getattr(args,'jingmai_ledger',None))
    ledger=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'shopIdentity':identity,'attempts':{},'tasks':[]}
    if ledger.get('shopIdentity',{}).get('venderId')!=identity['venderId']:raise ValueError('Jingmai ledger belongs to another shop')
    handled=set();summary={'ledger':str(path),'submittedSlots':0,'previewFailedSlots':0,'blockedTasks':0,'tasks':[]}
    plans=plan_jingmai_first(scoped,scope,ledger)
    for mode,spus in sorted(plans.items()):
        kinds=('white','transparent') if mode=='white-main+transparent-main' else ('white',) if mode=='white-main' else ('transparent',)
        items=sorted(spus.items())
        for start in range(0,len(items),10):
            chunk=dict(items[start:start+10]);tid=hashlib.sha256(json.dumps([mode,chunk],sort_keys=True).encode()).hexdigest()[:20]
            receipt=out/'jingmai-tasks'/(tid+'.json');receipt.parent.mkdir(parents=True,exist_ok=True)
            skus=[s for v in chunk.values() for s in v]
            result=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
            for attempt in range(2):
                if result is not None:break
                try:
                    result=submit(str(args.profile_dir),chunk,mode,expected_shop_name=identity['shopName'],expected_shop_id=identity['venderId'],receipt_path=receipt)
                except Exception as error:
                    # No receipt means nothing was sent; one clean retry is safe.
                    result=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else ({'status':'blocked','failureClass':type(error).__name__,'reason':str(error)[:200]} if attempt else None)
            status=result.get('status')
            if status in ('intent','unknown'):
                # Uncertain platform write: never replay, never overwrite with a model image this run.
                handled.update((s,k) for s in skus for k in kinds);summary['blockedTasks']+=1
            elif status in ('task-accepted','nothing-eligible'):
                failed=set(map(str,(result.get('previewFailures') or {}).keys()))
                accepted=set(map(str,result.get('skuIds') or []))-failed
                for s in skus:
                    for k in kinds:
                        old=[m for m in scope['originals'][s] if (int(m['materialType']),int(m['order']))==agent.JDO_MATERIAL_SLOTS[k]]
                        ledger['attempts'][s+':'+k]={'status':'submitted' if s in accepted else 'preview-failed','mode':mode,'task':tid,'rejectedUrl':agent._material_value(old[0]) if old else None,'at':int(time.time())}
                        if s in accepted:handled.add((s,k));summary['submittedSlots']+=1
                        else:summary['previewFailedSlots']+=1
                ledger['tasks'].append({'task':tid,'mode':mode,'status':status,'spuIds':list(chunk),'acceptedSkuIds':sorted(accepted)})
                path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,ledger)
            else:
                # Jingmai-first is mandatory: a blocked task holds its slots this round (no model fallback).
                handled.update((s,k) for s in skus for k in kinds);summary['blockedTasks']+=1
            summary['tasks'].append({'task':tid,'mode':mode,'status':status,'skuCount':len(skus),'reason':result.get('reason')})
    return handled,summary

def workflow_quota_exhausted(client, failed_spus):
    return bool(getattr(client,'quota_exhausted',False)) and not (getattr(client,'joyagent_fallback_satisfied',False) and failed_spus==0)

def check_repair_scope_subset(original,current,rows):
    kinds={'white':31,'transparent':36,'scene1':32,'scene2':32,'selling':33}
    def pairs(meta):
        ids=set(map(str,meta['authorizedSkuIds'])) if meta.get('authorizedSkuIds') is not None else {str(r['skuId']) for r in rows}
        if not ids.issubset({str(r['skuId']) for r in rows}):raise ValueError('修复SKU超出原快照')
        skip=set(map(str,meta.get('excludedSpuIds') or []));excluded={(str(p),int(k)) for p,k in meta.get('excludedBindings') or []}
        selected=set(meta.get('repairKinds') or kinds)
        if not selected.issubset(kinds):raise ValueError('未知修复类型')
        return {(str(r['skuId']),k) for r in rows if str(r['skuId']) in ids and str(r['productId']) not in skip for k in selected if (str(r['productId']),kinds[k]) not in excluded}
    if not pairs(current).issubset(pairs(original)):raise ValueError('修复范围扩大；保留原回执，新增范围需另行核准')


def reconcile_prompt_bindings(out, image_prompts, agent, client):
    # Prompt revisions never rewrite an old submission. Reconcile pending/unknown originals first.
    from pop_safety import fingerprint
    known={}
    paths=[*(Path(out)/'shared-bindings').glob('*.json'),*Path(out).glob('*/*-binding.json')]
    for path in paths:
        saved=json.loads(path.read_text(encoding='utf-8'));request=saved.get('request')
        if not isinstance(request,dict):raise agent.JdoWriteUncertainError('原修复回执缺少请求，不通过换提示词重提。')
        spu=str(request.get('spuId'));entries=image_prompts.get(spu,{})
        kinds=[kind for kind in entries if agent.JDO_MATERIAL_SLOTS[kind][0]==request.get('materialType')]
        if not kinds:continue
        if request.get('fingerprint')!=fingerprint(request.get('body')):raise agent.JdoWriteUncertainError('原请求指纹不符，未新生图。')
        if saved.get('reason')=='Official permission denied':raise agent.JdoPermissionError('原绑定权限仍需核实，不通过换提示词付费重试。')
        if saved.get('status') not in ('approved','rejected'):
            saved=submit_repair_request(client,request,path,agent)
        for item in request['body']['skuMaterials']:
            sku=str(item['skuId'])
            if str(item['productId'])!=spu:raise agent.JdoWriteUncertainError('原修复请求跨商品，未新生图。')
            for kind in kinds:
                slot=agent.JDO_MATERIAL_SLOTS[kind]
                for material in item['materials']:
                    if (int(material['materialType']),int(material['order']))==slot:
                        known.setdefault((sku,kind),set()).add(agent._material_value(material))
    return known


def run_rejected_repairs(args,agent=None):
    if agent is None:
        import jd_material_agent as agent
    if args.confirm!='AUTO_MAINTAIN':raise ValueError('Repair requires authorized AUTO_MAINTAIN confirmation')
    limit=getattr(args,'max_model_requests',None)
    if limit is not None and (type(limit) is not int or limit<0):raise ValueError('模型请求上限必须为非负整数')
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    with agent.pop_execution_lock(out):
        client=agent.JdoClient(args.profile,out/'.state/jdo-runtime');seller=client.seller_info()
        identity=agent._shop_identity(seller)
        if identity['shopName']!=args.expected_shop_name:raise ValueError('Repair shop identity mismatch')
        freeze=out/'repair-scope.json'
        if freeze.exists():
            scope=json.loads(freeze.read_text(encoding='utf-8'))
            if scope['shopIdentity']!=identity:raise ValueError('Frozen repair belongs to another shop')
        else:
            audit=agent.audit_pop_coverage(client,args.expected_shop_name,product_ids=getattr(args,'authorized_product_ids',None),authorized_sku_ids=getattr(args,'authorized_sku_ids',None))
            rows=audit['rows'];products=sorted({r['productId'] for r in rows})
            sku_rows=[];groups=list(agent._chunks(products,10))
            with ThreadPoolExecutor(max_workers=1 if len(groups)<=2 else agent.READ_CONCURRENCY) as reader:
                for found in reader.map(client.skus,groups):sku_rows.extend(found)
            originals=agent._query_binding_materials(client,[r['skuId'] for r in rows])
            scope={'shopIdentity':identity,'rows':rows,'skuSources':{str(r['skuId']):{'logo':r.get('skuImage') or r.get('logo'),'skuName':r.get('skuName')} for r in sku_rows},'originals':originals}
            scope['referenceGranularity'] = getattr(args, 'reference_granularity', None) or 'spu'
            _save(freeze,scope)
        from heideng_merchant.merchant_tasks import register_repair_task
        register_repair_task(out, identity, args.profile)
        granularity = scope.get('referenceGranularity', 'legacy')
        if getattr(args, 'reference_granularity', None) not in (None, granularity):
            raise ValueError('续跑须使用原修复粒度，保留已有请求和回执。')
        authorized=getattr(args,'authorized_sku_ids',None)
        excluded=getattr(args,'excluded_bindings',[])
        skip_spus=sorted(map(str,getattr(args,'excluded_spu_ids',None) or []))
        scope_identity={'authorizedSkuIds':sorted(map(str,authorized)) if authorized is not None else None,'excludedBindings':sorted([str(spu),int(kind)] for spu,kind in excluded)}
        if skip_spus:scope_identity['excludedSpuIds']=skip_spus
        selected_kinds=getattr(args,'repair_kind',None) or getattr(args,'repair_kinds',None)
        if selected_kinds:scope_identity['repairKinds']=sorted(set(selected_kinds))
        guard_path=out/'authorization-scope.json'
        original_scope=json.loads(guard_path.read_text(encoding='utf-8')) if guard_path.exists() else scope_identity
        check_repair_scope_subset(original_scope,scope_identity,scope['rows'])
        _save(guard_path,scope_identity)
        image_prompts=agent.load_image_prompts(args.image_prompts_file,[r['productId'] for r in scope['rows']]) if getattr(args,'image_prompts_file',None) else {}
        scoped=scoped_repair_rows(scope['rows'],authorized,excluded,agent,skip_spus,repair_kinds=selected_kinds,image_prompts=image_prompts)
        prompt_targets={(str(row['productId']),kind) for row in scoped for kind in row['repairKinds']}
        active_prompts={spu:{kind:entry for kind,entry in kinds.items() if (spu,kind) in prompt_targets} for spu,kinds in image_prompts.items()}
        active_prompts={spu:kinds for spu,kinds in active_prompts.items() if kinds}
        known_revision_urls=reconcile_prompt_bindings(out,active_prompts,agent,client) if active_prompts else {}
        appeal_delivery=export_product_text_appeals(scope,scoped,out,agent)
        image_review=[];proven_product_appeal=False
        for row in scoped:
            for kind in row['appealKinds']:
                entry=image_prompts.get(str(row['productId']),{}).get(kind) or {}
                slot=agent.JDO_MATERIAL_SLOTS[kind]
                matches=[m for m in scope['originals'][str(row['skuId'])] if (int(m['materialType']),int(m['order']))==slot and int(m.get('status') or 0)==5]
                if entry.get('textOrigin')=='product' and entry.get('evidence') and len(matches)==1 and entry.get('rejectedImageUrl')==agent._material_value(matches[0]):
                    proven_product_appeal=True;continue
                image_review.append({'spuId':str(row['productId']),'skuId':str(row['skuId']),'kind':kind,'imageUrl':agent._material_value(matches[0]) if len(matches)==1 else '', 'nextAction':'Agent查看驳回图和参考图：额外生成文字改任务提示词；商品本体印刷误驳回走申诉。'})
        review_fields={'imageReviewRequired':image_review,'manualAppealRequired':proven_product_appeal,'needsMerchantAction':proven_product_appeal}
        if image_review:review_fields['needsAgentAction']=True

        jingmai={'status':'not-configured'}
        if not getattr(args,'profile_dir',None):
            from heideng_merchant.mature_runtime import registered_browser_profile
            directory=registered_browser_profile(args.profile,identity)
            if directory:args.profile_dir=str(directory)
        if getattr(args,'profile_dir',None) and getattr(args,'jingmai_first',True):
            # User rule: rejected white/transparent use Jingmai's own batch cutout first; only slots
            # already tried there (rejected again / preview failed) go to the model + neural cutout.
            handled,jingmai=run_jingmai_first(args,scope,scoped,out,identity,agent)
            scoped=[{**row,'repairKinds':[k for k in row['repairKinds'] if (str(row['skuId']),k) not in handled]} for row in scoped]
        targets=[row for row in scoped if row['repairKinds']]
        overrides={}
        for value in getattr(args,'reference_override',[]) or []:
            sku,separator,path=value.partition('=')
            if not separator or sku not in scope['skuSources'] or not Path(path).is_file():raise ValueError('Reference override must name a frozen SKU and readable local image')
            overrides[sku]=Path(path)
        references = repair_references(targets, scope['skuSources'], overrides, granularity)
        source_group_count=len({(str(row['productId']),kind,references[str(row['skuId'])][1]) for row in targets for kind in row['repairKinds']})
        paid_groups = {(str(row['productId']), kind, references[str(row['skuId'])][1])
                       for row in targets for kind in row['repairKinds']
                       if kind != 'transparent' or ('white' not in row['repairKinds'] and transparent_route(row) != 'reuse-white')}
        units = sorted(f'{spu}/{kind}/{hashlib.sha256(ref.encode()).hexdigest()[:16]}' for spu,kind,ref in paid_groups)
        fee_scope = {'task': 'repair-rejected', 'shopIdentity': identity,
                     'directory': str(out.resolve()), 'referenceGranularity': granularity,
                     'targets': {str(r['skuId']): sorted(r['repairKinds']) for r in targets}}
        approval_file = getattr(args, 'fee_approval_file', None)
        approval = json.loads(Path(approval_file).read_text(encoding='utf-8-sig')) if approval_file else {}
        # Previous versions froze this precise target set without a model field: only 2.5 was available then.
        if approval.get('scope') != fee_scope:
            fee_scope.update(agent.model_scope())
            fee_scope['imageSize'] = agent.MATERIAL_IMAGE_SIZE
        quote = {**agent.image_credit_quote(dict.fromkeys(units, agent.MATERIAL_IMAGE_SIZE)),
                 'scope': fee_scope, 'units': units, 'estimatedPaidImageCount': len(units),
                 'amount': None, 'actualAmount': None, 'provider': 'LTS4AI',
                 'nextAction': '优先复用已有素材。本次信息分图为 1K，两款模型均按 3 积分/张报价，按剩余图位确认。'}
        if not targets:
            status='needs-image-review' if image_review else 'jingmai-submitted-awaiting-review' if jingmai.get('submittedSlots') else 'appeal-only' if appeal_delivery else 'no-rejections'
            result={'status':status,'rows':[],'shopName':identity['shopName'],'productTextAppeals':appeal_delivery,'jingmaiFirst':jingmai,
                    **review_fields,
                    'noPaidGeneration':bool(getattr(args,'no_paid_generation',not getattr(args,'paid_generation',False)))}
            if appeal_delivery or jingmai.get('tasks'):_save(out/'repair-result.json',result)
            return result
        if getattr(args,'no_paid_generation',not getattr(args,'paid_generation',False)):
            # A saved key is not permission to expand this explicitly free repair.
            remaining=[{'spuId':str(row['productId']),'skuId':str(row['skuId']),'kinds':list(row['repairKinds'])} for row in targets]
            result={'status':'partial-free-repair','rows':[],'shopName':identity['shopName'],
                    'productTextAppeals':appeal_delivery,'jingmaiFirst':jingmai,'remainingTargets':remaining,
                    'remainingImageSlotCount':sum(len(row['kinds']) for row in remaining),
                    'pendingReviewCount':int(jingmai.get('submittedSlots') or 0),'noPaidGeneration':True,
                    **review_fields,
                    'feeQuote':quote,'paidRequestCount':None,'estimatedPaidImageCount':len(paid_groups),'referenceGranularity':granularity,
                    'sourceGroupCount':source_group_count,'nextAction':'免费路径已执行并保留回执；Agent先核实文字来源。核对剩余SKU/槽位，在已有费用范围内重设本任务提示词继续；仅新增费用才另行确认。'}
            _save(out/'repair-result.json',result)
            return result
        if not selected_kinds:
            result={**review_fields,'status':'repair-scope-required','rows':[],'jingmaiFirst':jingmai,'productTextAppeals':appeal_delivery,
                    'remainingTargets':[{'spuId':str(r['productId']),'skuId':str(r['skuId']),'kinds':r['repairKinds']} for r in targets],
                    'nextAction':'付费修复须由宿主按已批准目标传repair-kind；未读取Key、未调用模型。'}
            _save(out/'repair-result.json',result)
            return result
        if units:
            if not approval_file:
                return {**review_fields, 'status':'fee-approval-required', 'needsMerchantAction':True,
                        'feeQuote':quote, 'estimatedPaidImageCount':len(units), 'rows':[]}
            from heideng_merchant.image_budget import validate_approval
            validate_approval(approval, scope=fee_scope, units=units)
            if limit is not None and limit > approval['maxRequests']:
                raise ValueError('请求上限超出商家已批准范围')
            limit = min(limit, approval['maxRequests']) if limit is not None else approval['maxRequests']
        else:
            limit = 0
        adapter = None
        if getattr(args, 'joyagent_adapter', None):
            raise ValueError('商家图片仅使用该商家的 LTS4AI 授权，不切换外部适配器')
        prior_image_receipts=[]
        for path in (out/'shared').glob('*/*.request.json'):
            receipt=json.loads(path.read_text(encoding='utf-8'))
            if receipt.get('status') in ('intent','unknown'):prior_image_receipts.append(receipt)
        category = client.resolve_category()
        write_lock = Lock()
        cancel_event = Event()
        reserve, budget = repair_request_budget(out, limit, agent.ModelRequestLimitError)
        model = None
        text_checker = None
        if units:
            from heideng_merchant.mature_image import merchant_key
            key = os.environ.get(agent.PROVIDER.api_key_env) or merchant_key()
            model = agent.ModelClient(key,image_concurrency=min(20,getattr(args,'image_concurrency',20)),timeout=getattr(args,'timeout',180))
            model.image_models = tuple(fee_scope.get('models') or ['gpt-image-2.5'])
            model.max_model_requests = limit
            model.reserve_persistent_request = reserve
            model.cancel_event = cancel_event
            try:
                import pop_attrs as _pa
                text_checker = _pa.VisionAttrModel(key)
                if not text_checker.models:
                    text_checker.close()
                    text_checker = None
            except Exception:
                text_checker = None
        def shared_assets(key,members,kind):
            # One SPU + one SKU reference => one fresh image for every sibling rejected with it.
            spu,_,ref_id=key;lead=members[0]
            repair_scope={'spuId':str(spu),'kind':kind,'skuIds':[str(r['skuId']) for r in members]}
            assert_no_unresolved_images(prior_image_receipts,spu,kind,repair_scope['skuIds'],agent)
            group=out/'shared'/hashlib.sha256(json.dumps([spu,ref_id],ensure_ascii=False).encode()).hexdigest()[:20]
            reference_sku = references[str(lead['skuId'])][0]
            group.mkdir(parents=True,exist_ok=True);reference=overrides.get(reference_sku) or group/'reference.jpg'
            with generation_locks.setdefault(str(reference), Lock()):
                if not reference.is_file():
                    url=agent._jd_image_url(scope['skuSources'].get(reference_sku, {}).get('logo'))
                    if not url:raise ValueError('Reliable SKU reference missing')
                    agent._download_reference(url,reference,getattr(args,'timeout',180))
            image=group/(kind+('.png' if kind=='transparent' else '.jpg'))
            generated=group/('white.jpg' if kind=='transparent' else image.name)
            linked_white = kind == 'transparent' and all('white' in member['repairKinds'] for member in members)
            if linked_white:
                white_ref = references[str(lead['skuId'])][1]
                revision = agent.image_prompt_revision(image_prompts.get(str(spu),{}).get('white'),request_only=True)
                if revision:
                    white_ref += '|prompt:' + revision
                white_group = hashlib.sha256(json.dumps([spu,white_ref],ensure_ascii=False).encode()).hexdigest()[:20]
                generated = out / 'shared' / white_group / 'white.jpg'
                if not agent.valid_material_image(generated,'white'):
                    raise ValueError('先完成同款白底图，再本地衍生透明图')
            route=transparent_route(lead) if kind=='transparent' else None
            # Escalation ladder per slot (shop ledger): jingmai -> neural -> magenta key.
            if kind=='transparent' and cutout_ledger.get('attempts',{}).get(lead['skuId']+':transparent-neural'):route='magenta'
            with generation_locks.setdefault(str(generated),Lock()):
                if route=='reuse-white' and not generated.is_file():
                    # Only 抠图损坏 and the white is approved: re-cut the approved white, no generation.
                    approved=[m for m in scope['originals'][lead['skuId']] if (int(m['materialType']),int(m['order']))==agent.JDO_MATERIAL_SLOTS['white'] and int(m.get('status') or 0)==4]
                    if approved:
                        try:agent._download_reference(agent._material_value(approved[0]),generated,getattr(args,'timeout',180))
                        except Exception:generated.unlink(missing_ok=True)
                    if not generated.is_file():
                        raise ValueError('无法读取已通过的白底来源，未为透明图新增付费请求')
                if not generated.is_file():
                    entry=image_prompts.get(str(spu),{}).get(kind)
                    if entry:prompt=entry['prompt']
                    else:
                        prompt=agent.image_prompt('white' if kind=='transparent' else kind,scope['skuSources'][lead['skuId']].get('skuName'))
                        prompt+=' Only the complete actual product. No people, limbs, props, collage, labels or marketing text; preserve physical product artwork.'
                        if kind in ('white','transparent'):prompt+=WHITE_REPAIR_HINT
                        if kind in ('scene1','scene2'):prompt+=SCENE_REPAIR_HINT
                    _save(group/(kind+'-prompt.json'),{'source':'host-task' if entry else 'mature-default','prompt':prompt,'revision':agent.image_prompt_revision(entry),'spuId':str(spu),'skuIds':repair_scope['skuIds']})
                    content=request_repair_image(agent,model,'white' if kind=='transparent' else kind,prompt,reference,adapter,group/(kind+'-adapter.png'),getattr(args,'timeout',180),repair_scope=repair_scope)
                    agent.normalize_jpeg(content,generated,pure_white=kind in {'white','transparent'})
                    if kind in ('scene1','scene2') and image_has_text(generated,text_checker):
                        # Platform rejects scene images with any text; one regeneration, then do not upload.
                        generated.unlink(missing_ok=True)  # Never leave a known-invalid candidate reusable after interruption.
                        content=request_repair_image(agent,model,kind,prompt+' 上一张出现了文字/贴片，必须完全去掉。',reference,None,group/(kind+'-text-retry.png'),getattr(args,'timeout',180),repair_scope=repair_scope)
                        agent.normalize_jpeg(content,generated)
                        if image_has_text(generated,text_checker):
                            generated.unlink(missing_ok=True);raise ValueError('Regenerated scene still contains text; not uploaded')
                    if kind in ('white','transparent'):
                        # One retry when the local gate sees cropping/blur; a shared image fans out to many SKUs.
                        issues=white_quality_issues(generated)
                        if issues:
                            generated.unlink(missing_ok=True)  # A capped/unknown retry must not leave rejected local bytes reusable.
                            content=request_repair_image(agent,model,'white',prompt+' 上一张不合格：'+','.join(issues)+'，请重新生成完整、清晰、居中的商品。',reference,None,group/(kind+'-quality-retry.png'),getattr(args,'timeout',180),repair_scope=repair_scope)
                            agent.normalize_jpeg(content,generated,pure_white=True)
                            remaining_quality_issues=white_quality_issues(generated)
                            if remaining_quality_issues:
                                generated.unlink(missing_ok=True);raise ValueError('Regenerated white failed local completeness/sharpness gate; not uploaded; checks='+','.join(remaining_quality_issues))
                if kind=='transparent' and not image.is_file():
                    try:
                        if route=='magenta' and not linked_white:raise ValueError('neural cutout already rejected for this slot')
                        agent.make_transparent(generated,image,quality='fast' if route=='regen-fast' else 'neural')
                        if not agent.valid_material_image(image,'transparent'):raise ValueError('cutout structurally invalid')
                    except Exception:
                        # Neural failed/unprepared (or fast cut broke): generate on magenta and colour-key it.
                        image.unlink(missing_ok=True);magenta=group/'magenta.jpg'
                        if linked_white or route == 'reuse-white':
                            raise ValueError('本地透明图未通过质检，保留原素材等待核对') from None
                        if not magenta.is_file():
                            entry=image_prompts.get(str(spu),{}).get(kind)
                            prompt=(entry['prompt'] if entry else agent.image_prompt('white',scope['skuSources'][lead['skuId']].get('skuName'))).replace('#FFFFFF','#FF00FF').replace('纯白','纯洋红')+' 背景必须是纯洋红色#FF00FF，均匀无渐变无阴影，商品本身不得含洋红色描边。'+('' if entry else WHITE_REPAIR_HINT)
                            content=request_repair_image(agent,model,'white',prompt,generated if generated.is_file() else reference,None,group/(kind+'-magenta-response.png'),getattr(args,'timeout',180),repair_scope=repair_scope)
                            from PIL import Image as _I
                            from io import BytesIO as _B
                            _I.open(_B(content)).convert('RGB').save(magenta,'JPEG',quality=95)
                        magenta_cutout(magenta,image)
            if not agent.valid_material_image(image,kind):raise ValueError('New repair asset failed structural validation')
            return group,reference,image

        def process(item):
            key,kind,members=item;spu=key[0];results=[]
            fresh=[]
            for row in members:
                receipt_path=out/row['skuId']/(kind+'-binding.json')
                if receipt_path.exists() and not image_prompts.get(str(spu),{}).get(kind):
                    saved=json.loads(receipt_path.read_text(encoding='utf-8'))
                    with write_lock:record=submit_repair_request(client,saved['request'],receipt_path,agent)
                    results.append({'skuId':row['skuId'],'kind':kind,'status':record['status'],'receiptReused':True})
                else:fresh.append(row)
            if not fresh:return results
            group_id=hashlib.sha256(json.dumps([spu,kind,key[2]],ensure_ascii=False).encode()).hexdigest()[:20]
            receipt_path=out/'shared-bindings'/(group_id+'.json');receipt_path.parent.mkdir(parents=True,exist_ok=True)
            if receipt_path.exists():
                saved=json.loads(receipt_path.read_text(encoding='utf-8'))
                with write_lock:record=submit_repair_request(client,saved['request'],receipt_path,agent)
                active={str(row['skuId']) for row in fresh}
                return results+[{'skuId':sku,'kind':kind,'status':record['status'],'receiptReused':True} for sku in saved['request']['skuIds'] if str(sku) in active]
            # Frozen rejection is not proof of a current rejection. Read before paying for a new asset.
            live=agent._query_binding_materials(client,[str(r['skuId']) for r in fresh]);still_rejected=[]
            slot_type,slot_order=agent.JDO_MATERIAL_SLOTS[kind]
            for row in fresh:
                sku=str(row['skuId'])
                found=[m for m in live[sku] if int(m.get('materialType') or 0)==slot_type and int(m.get('order') or 0)==slot_order]
                active=[m for m in found if int(m.get('status') or 0) in (3,4)]
                if active:
                    status='pending' if any(int(m.get('status') or 0)==3 for m in active) else 'approved'
                    results.append({'skuId':sku,'kind':kind,'status':status,'liveReuse':True});continue
                old={agent._material_value(m) for m in scope['originals'][sku] if (int(m['materialType']),int(m['order']))==(slot_type,slot_order) and int(m.get('status') or 0)==5}
                old.update(known_revision_urls.get((sku,kind),set()))
                value=agent._material_value(found[0]) if len(found)==1 else ''
                text_appeal=product_text_appeal(kind,{'auditReasons':[m.get('auditDesc') or m.get('reason') or '' for m in found]},image_prompts.get(str(spu),{}).get(kind),current_url=value)
                if len(found)!=1 or int(found[0].get('status') or 0)!=5 or not value or value not in old or text_appeal:
                    reason='当前文字来源需核实，Agent先查看原图，未盲目生图或重绑' if text_appeal else '原驳回槽位已改变或来源不唯一，未生图或重绑'
                    results.append({'skuId':sku,'kind':kind,'status':'skipped-changed','reason':reason,'imageUrl':value});continue
                still_rejected.append({**row,'_repairOriginalValue':value})
            fresh=still_rejected
            if not fresh:return results
            group,reference,image=shared_assets(key,fresh,kind)
            digest=agent._file_sha256(image);slot=agent.JDO_MATERIAL_SLOTS[kind]
            old_urls={}
            for row in fresh:
                old_urls[row['skuId']]=row['_repairOriginalValue']
            for index,old_url in enumerate(sorted(set(old_urls.values()))):
                old_file=group/(kind+'-rejected-original-'+hashlib.sha256(old_url.encode()).hexdigest()[:12]+image.suffix)
                if not old_file.exists():agent._download_reference(old_url,old_file,getattr(args,'timeout',180))
                if digest==agent._file_sha256(old_file):raise ValueError('Rejected image bytes cannot be replayed')
            upload_path=group/(kind+'-upload.json')
            with write_lock:
                if cancel_event.is_set():raise agent.JdoWriteUncertainError('Repair stopped after unknown write; reconcile before any new write')
                upload=json.loads(upload_path.read_text(encoding='utf-8')) if upload_path.exists() else {}
                if upload and upload.get('sha256')!=digest:raise agent.JdoWriteUncertainError('Repair upload bytes changed')
                if upload.get('status') in ('intent','unknown'):raise agent.JdoWriteUncertainError('Repair upload outcome unknown; do not replay')
                if not upload:
                    upload={'status':'intent','sha256':digest};_save(upload_path,upload)
                    try:
                        upload_file=group/(spu+'_'+kind+'_'+digest[:12]+image.suffix)
                        if not upload_file.exists(): upload_file.write_bytes(image.read_bytes())
                        resp=client.upload_image(upload_file,category)
                    except Exception:
                        upload['status']='unknown';_save(upload_path,upload);cancel_event.set();raise agent.JdoWriteUncertainError('Repair upload result unknown') from None
                    if resp.get('imgName')!=upload_file.name or not resp.get('imgUrl'):
                        upload['status']='unknown';_save(upload_path,upload);cancel_event.set();raise agent.JdoWriteUncertainError('Repair upload response cannot identify original file')
                    upload.update(status='accepted',url=agent._jd_image_url(resp['imgUrl']));_save(upload_path,upload)
                ids=[row['skuId'] for row in fresh];current=agent._query_binding_materials(client,ids)
                selected=[]
                for sku in ids:
                    latest=[m for m in current[sku] if (int(m['materialType']),int(m['order']))==slot]
                    if len(latest)==1 and int(latest[0].get('status') or 0)==5 and agent._material_value(latest[0])==old_urls[sku]:selected.append(sku)
                    else:results.append({'skuId':sku,'kind':kind,'status':'skipped-changed'})
                if not selected:return results
                sub={sku:current[sku] for sku in selected}
                request=agent.prepare_rejected_slot_request(spu,selected,sub,sub,kind,upload['url'],allow_manual_appeal_repair=True)
                request['fullSiblingSkuIds']=sibling_ids.get(spu,[])
                _save(group/(kind+'-provenance.json'),{'sourceSha256':agent._file_sha256(reference),'newSha256':digest,'skuIds':selected,'auditReasons':{row['skuId']:row['slots'][kind]['auditReasons'] for row in fresh if row['skuId'] in selected},'request':request})
                try:record=submit_repair_request(client,request,receipt_path,agent)
                except agent.JdoWriteUncertainError:
                    cancel_event.set();raise
                if kind=='transparent':
                    backend=json.loads((group/'transparent.cutout.json').read_text(encoding='utf-8')).get('backend') if (group/'transparent.cutout.json').exists() else ('magenta-key' if (group/'magenta.jpg').exists() else 'fast')
                    if backend not in ('magenta-key','fast','legacy-flood'):
                        with ledger_lock:
                            for sku in selected:cutout_ledger.setdefault('attempts',{})[sku+':transparent-neural']={'task':group.name,'at':int(time.time())}
                            from pop_safety import atomic_json;atomic_json(cutout_ledger_path,cutout_ledger)
            return results+[{'skuId':sku,'kind':kind,'status':record['status']} for sku in selected]
        sibling_ids={}
        for r in scope['rows']:sibling_ids.setdefault(r['productId'],[]).append(r['skuId'])
        cutout_ledger_path=jingmai_ledger_path(identity,getattr(args,'jingmai_ledger',None));ledger_lock=Lock()
        cutout_ledger=json.loads(cutout_ledger_path.read_text(encoding='utf-8')) if cutout_ledger_path.exists() else {'shopIdentity':identity,'attempts':{},'tasks':[]}
        generation_locks={};work={}
        for row in targets:
            ref_id=references[str(row['skuId'])][1]
            for kind in row['repairKinds']:
                lane=ref_id+('|'+transparent_route(row) if kind=='transparent' else '')
                revision=agent.image_prompt_revision(image_prompts.get(str(row['productId']),{}).get(kind),request_only=True)
                if revision:lane+='|prompt:'+revision
                work.setdefault((row['productId'],kind,lane),[]).append(row)
        work=[((spu,kind,ref_id),kind,members) for (spu,kind,ref_id),members in sorted(work.items())]
        work=[((k[0],None,k[2]),kind,m) for k,kind,m in work]
        records=[];errors=[]
        try:
            with ThreadPoolExecutor(max_workers=min(20,len(work))) as pool:
                independent = [item for item in work if not (item[1]=='transparent' and all('white' in row['repairKinds'] for row in item[2]))]
                dependent = [item for item in work if item not in independent]
                for phase in (independent, dependent):
                    futures={pool.submit(process,item):item[2][0]['skuId'] for item in phase}
                    for future in as_completed(futures):
                        try:records.extend(future.result())
                        except agent.JdoWriteUncertainError:
                            cancel_event.set()
                            errors.append({'skuId':futures[future],'status':'unknown','reason':'Preserve receipt and reconcile exact request before retrying'})
                        except Exception as error:errors.append({'skuId':futures[future],'status':'blocked','failureClass':type(error).__name__,'reason':str(error)[:200] or 'Repair did not complete; inspect reference, adapter and owned receipts'})
        finally:
            if model is not None:
                model.close()
            if text_checker is not None:
                text_checker.close()
        result={**review_fields,'imagePromptRevisions':[{'spuId':spu,'kind':kind,'sha256':agent.image_prompt_revision(entry)} for spu,kinds in image_prompts.items() for kind,entry in kinds.items()], 'requestLimit':limit,'assetGroupCount':len(work),'failedAssetGroupCount':len(errors),'liveReusedSkuSlotCount':sum(1 for r in records if r.get('liveReuse')),'submittedSkuSlotCount':sum(1 for r in records if not r.get('liveReuse') and r.get('status') in ('submitted','pending','approved')),'status':'repair-incomplete' if image_review or errors or any(r['status'] in ('rejected','skipped-changed','unknown') for r in records) else 'repairs-submitted-awaiting-review','shopName':identity['shopName'],'rows':records,'errors':errors,'modelStats':model.image_model_stats() if model is not None else {'usage':{},'attempts':{},'failures':{}},'allApproved':bool(records) and not errors and not appeal_delivery and not image_review and all(r['status']=='approved' for r in records),'productTextAppeals':appeal_delivery,'jingmaiFirst':jingmai}
        result['requestBudget'] = budget
        _save(out/'repair-result.json',result);return result


def install_joyagent_fallback(client,template,output_dir,timeout=180):
    raise RuntimeError('company-generation-fallback-forbidden; external-image-provider-is-LTS4AI-only')
