"""Reviewed fresh-byte rejected-slot repair with exact, durable submission receipts."""
import hashlib
import json
import os
import time
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event

def _save(path, value):
    from pop_safety import atomic_json
    atomic_json(path, value)

def adapter_argv(template, reference, output, prompt):
    if not isinstance(template,list) or not template or any(not isinstance(x,str) for x in template):
        raise ValueError('JoyAgent adapter must be a JSON argv array, never a shell string')
    joined=' '.join(template)
    if not all('{'+k+'}' in joined for k in ('reference','output','prompt')):
        raise ValueError('Adapter must accept reference, prompt and output placeholders')
    return [x.replace('{reference}',str(reference)).replace('{output}',str(output)).replace('{prompt}',prompt) for x in template]

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

PRODUCT_TEXT_REJECTION='禁止出现文字信息'

def product_text_appeal(kind, slot):
    # Product consistency first: white/transparent show only the actual product, so this rejection
    # means the product's own printed text. Never erase/alter the product; appeal, no regeneration.
    return kind in {'white','transparent'} and any(PRODUCT_TEXT_REJECTION in str(reason) for reason in slot.get('auditReasons') or [])

def scoped_repair_rows(rows, authorized_sku_ids, excluded_bindings, agent, excluded_spu_ids=()):
    skip_spus={str(s) for s in excluded_spu_ids or ()}
    rows=[r for r in rows if str(r.get('productId')) not in skip_spus]
    allowed=set(map(str,authorized_sku_ids)) if authorized_sku_ids is not None else {str(r['skuId']) for r in rows}
    excluded={(str(spu),int(kind)) for spu,kind in excluded_bindings}
    targets=[]
    for row in rows:
        if str(row['skuId']) not in allowed:continue
        kinds=[k for k in agent.IMAGE_SUFFIXES if k in row['slots'] and row['slots'][k]['state']=='rejected' and (str(row['productId']),agent.JDO_MATERIAL_SLOTS[k][0]) not in excluded]
        appeal=[k for k in kinds if product_text_appeal(k,row['slots'][k])]
        if kinds:targets.append({**row,'repairKinds':[k for k in kinds if k not in appeal],'appealKinds':appeal})
    return targets

def export_product_text_appeals(scope, targets, out, agent):
    records=[]
    names={'white':'白底图','transparent':'透明图'}
    for row in targets:
        sku=str(row['skuId'])
        for kind in row.get('appealKinds') or []:
            slot=agent.JDO_MATERIAL_SLOTS[kind];old=[m for m in scope['originals'][sku] if (int(m['materialType']),int(m['order']))==slot][0]
            records.append({'skuId':sku,'productId':str(row['productId']),'skuName':str(row.get('skuName') or ''),'materialType':slot[0],'order':slot[1],'status':5,'materialName':names[kind],'imageUrl':agent._material_value(old),'auditDesc':'；'.join(row['slots'][kind].get('auditReasons') or [])+'（商品本身印刷文字：按商品一致性第一原则不修改商品、不重复生图，转申诉）'})
    if not records:return None
    report={'shopIdentity':scope['shopIdentity'],'checkedAt':scope.get('checkedAt') or 'frozen-repair-scope','scopeNote':'商品本身印刷文字导致的禁止出现文字信息驳回；保持商品一致性，不去字不重生图，未代发申诉。','appealRows':records}
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

def run_rejected_repairs(args,agent=None):
    if agent is None:
        import jd_material_agent as agent
    if args.confirm!='AUTO_MAINTAIN':raise ValueError('Repair requires authorized AUTO_MAINTAIN confirmation')
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
            _save(freeze,scope)
        authorized=getattr(args,'authorized_sku_ids',None)
        excluded=getattr(args,'excluded_bindings',[])
        skip_spus=sorted(map(str,getattr(args,'excluded_spu_ids',None) or []))
        scope_identity={'authorizedSkuIds':sorted(map(str,authorized)) if authorized is not None else None,'excludedBindings':sorted([str(spu),int(kind)] for spu,kind in excluded)}
        if skip_spus:scope_identity['excludedSpuIds']=skip_spus
        guard_path=out/'authorization-scope.json'
        if guard_path.exists() and json.loads(guard_path.read_text(encoding='utf-8'))!=scope_identity:
            raise ValueError('Repair authorization scope changed; use a new reviewed directory')
        _save(guard_path,scope_identity)
        scoped=scoped_repair_rows(scope['rows'],authorized,excluded,agent,skip_spus)
        appeal_delivery=export_product_text_appeals(scope,scoped,out,agent)
        jingmai={'status':'not-configured'}
        if getattr(args,'profile_dir',None) and getattr(args,'jingmai_first',True):
            # User rule: rejected white/transparent use Jingmai's own batch cutout first; only slots
            # already tried there (rejected again / preview failed) go to the model + neural cutout.
            handled,jingmai=run_jingmai_first(args,scope,scoped,out,identity,agent)
            scoped=[{**row,'repairKinds':[k for k in row['repairKinds'] if (str(row['skuId']),k) not in handled]} for row in scoped]
        targets=[row for row in scoped if row['repairKinds']]
        if not targets:
            status='jingmai-submitted-awaiting-review' if jingmai.get('submittedSlots') else 'appeal-only' if appeal_delivery else 'no-rejections'
            result={'status':status,'rows':[],'shopName':identity['shopName'],'productTextAppeals':appeal_delivery,'jingmaiFirst':jingmai}
            if appeal_delivery or jingmai.get('tasks'):_save(out/'repair-result.json',result)
            return result
        key=os.environ.get(agent.PROVIDER.api_key_env)
        if not key:raise ValueError('Local model key missing; never paste it into chat')
        adapter=json.loads(Path(args.joyagent_adapter).read_text(encoding='utf-8')) if getattr(args,'joyagent_adapter',None) else None
        if adapter is not None:
            adapter_argv(adapter, Path('reference.png'), Path('output.png'), 'prompt')
            if 'JoyAgent-image(JoyAgent)' not in ' '.join(adapter): raise ValueError('Explicit JoyAgent-image model required')
        overrides={}
        for value in getattr(args,'reference_override',[]) or []:
            sku,separator,path=value.partition('=')
            if not separator or sku not in scope['skuSources'] or not Path(path).is_file():raise ValueError('Reference override must name a frozen SKU and readable local image')
            overrides[sku]=Path(path)
        category=client.resolve_category();write_lock=Lock();model=agent.ModelClient(key,image_concurrency=min(20,getattr(args,'image_concurrency',20)),timeout=getattr(args,'timeout',180))
        model.cancel_event=Event()
        text_checker=None
        try:
            import pop_attrs as _pa
            text_checker=_pa.VisionAttrModel(key)
            if not text_checker.models:text_checker.close();text_checker=None
        except Exception:text_checker=None
        def shared_assets(key,members,kind):
            # One SPU + one SKU reference => one fresh image for every sibling rejected with it.
            spu,_,ref_id=key;lead=members[0];group=out/'shared'/hashlib.sha256(json.dumps([spu,ref_id],ensure_ascii=False).encode()).hexdigest()[:20]
            group.mkdir(parents=True,exist_ok=True);reference=overrides.get(lead['skuId']) or group/'reference.jpg'
            if not reference.is_file():
                url=agent._jd_image_url(scope['skuSources'][lead['skuId']].get('logo'))
                if not url:raise ValueError('Reliable SKU reference missing')
                agent._download_reference(url,reference,getattr(args,'timeout',180))
            image=group/(kind+('.png' if kind=='transparent' else '.jpg'))
            generated=group/('white.jpg' if kind=='transparent' else image.name)
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
                    prompt=agent.image_prompt('white' if kind=='transparent' else kind,scope['skuSources'][lead['skuId']].get('skuName'))
                    prompt+=' Only the complete actual product. No people, limbs, props, collage, labels or marketing text; preserve physical product artwork.'
                    if kind in ('white','transparent'):prompt+=WHITE_REPAIR_HINT
                    if kind in ('scene1','scene2'):prompt+=SCENE_REPAIR_HINT
                    try:
                        content=agent.request_material_image(model,'white' if kind=='transparent' else kind,prompt,reference,model='pool')
                    except Exception:
                        if adapter is None or kind=='selling':raise ValueError('Image generation blocked; configure an authorized JoyAgent adapter or a reliable reference override') from None
                        temporary=group/(kind+'-adapter.png')
                        argv=adapter_argv(adapter,reference,temporary,prompt)
                        completed=subprocess.run(argv,shell=False,capture_output=True,timeout=getattr(args,'timeout',180))
                        if completed.returncode or not temporary.is_file():raise ValueError('JoyAgent adapter failed; no upload performed')
                        content=temporary.read_bytes()
                    agent.normalize_jpeg(content,generated,pure_white=kind in {'white','transparent'})
                    if kind in ('scene1','scene2') and image_has_text(generated,text_checker):
                        # Platform rejects scene images with any text; one regeneration, then do not upload.
                        content=agent.request_material_image(model,kind,prompt+' 上一张出现了文字/贴片，必须完全去掉。',reference,model='pool')
                        agent.normalize_jpeg(content,generated)
                        if image_has_text(generated,text_checker):
                            generated.unlink(missing_ok=True);raise ValueError('Regenerated scene still contains text; not uploaded')
                    if kind in ('white','transparent'):
                        # One retry when the local gate sees cropping/blur; a shared image fans out to many SKUs.
                        issues=white_quality_issues(generated)
                        if issues:
                            content=agent.request_material_image(model,'white',prompt+' 上一张不合格：'+','.join(issues)+'，请重新生成完整、清晰、居中的商品。',reference,model='pool')
                            agent.normalize_jpeg(content,generated,pure_white=True)
                            if white_quality_issues(generated):
                                generated.unlink(missing_ok=True);raise ValueError('Regenerated white failed local completeness/sharpness gate; not uploaded')
                if kind=='transparent' and not image.is_file():
                    try:
                        if route=='magenta':raise ValueError('neural cutout already rejected for this slot')
                        agent.make_transparent(generated,image,quality='fast' if route=='regen-fast' else 'neural')
                        if not agent.valid_material_image(image,'transparent'):raise ValueError('cutout structurally invalid')
                    except Exception:
                        # Neural failed/unprepared (or fast cut broke): generate on magenta and colour-key it.
                        image.unlink(missing_ok=True);magenta=group/'magenta.jpg'
                        if not magenta.is_file():
                            prompt=agent.image_prompt('white',scope['skuSources'][lead['skuId']].get('skuName')).replace('#FFFFFF','#FF00FF').replace('纯白','纯洋红')+' 背景必须是纯洋红色#FF00FF，均匀无渐变无阴影，商品本身不得含洋红色描边。'+WHITE_REPAIR_HINT
                            content=agent.request_material_image(model,'white',prompt,generated if generated.is_file() else reference,model='pool')
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
                if receipt_path.exists():
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
                return results+[{'skuId':sku,'kind':kind,'status':record['status'],'receiptReused':True} for sku in saved['request']['skuIds']]
            group,reference,image=shared_assets(key,fresh,kind)
            digest=agent._file_sha256(image);slot=agent.JDO_MATERIAL_SLOTS[kind]
            old_urls={}
            for row in fresh:
                old=[m for m in scope['originals'][row['skuId']] if (int(m['materialType']),int(m['order']))==slot][0]
                old_urls[row['skuId']]=agent._material_value(old)
            for index,old_url in enumerate(sorted(set(old_urls.values()))):
                old_file=group/(kind+'-rejected-original-'+hashlib.sha256(old_url.encode()).hexdigest()[:12]+image.suffix)
                if not old_file.exists():agent._download_reference(old_url,old_file,getattr(args,'timeout',180))
                if digest==agent._file_sha256(old_file):raise ValueError('Rejected image bytes cannot be replayed')
            upload_path=group/(kind+'-upload.json')
            with write_lock:
                if model.cancel_event.is_set():raise agent.JdoWriteUncertainError('Repair stopped after unknown write; reconcile before any new write')
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
                        upload['status']='unknown';_save(upload_path,upload);model.cancel_event.set();raise agent.JdoWriteUncertainError('Repair upload result unknown') from None
                    if resp.get('imgName')!=upload_file.name or not resp.get('imgUrl'):
                        upload['status']='unknown';_save(upload_path,upload);model.cancel_event.set();raise agent.JdoWriteUncertainError('Repair upload response cannot identify original file')
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
                    model.cancel_event.set();raise
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
            ref_id=str(overrides.get(row['skuId']) or scope['skuSources'][row['skuId']].get('logo') or row['skuId'])
            for kind in row['repairKinds']:
                lane=ref_id+('|'+transparent_route(row) if kind=='transparent' else '')
                work.setdefault((row['productId'],kind,lane),[]).append(row)
        work=[((spu,kind,ref_id),kind,members) for (spu,kind,ref_id),members in sorted(work.items())]
        work=[((k[0],None,k[2]),kind,m) for k,kind,m in work]
        records=[];errors=[]
        try:
            with ThreadPoolExecutor(max_workers=min(20,len(work))) as pool:
                futures={pool.submit(process,item):item[2][0]['skuId'] for item in work}
                for future in as_completed(futures):
                    try:records.extend(future.result())
                    except agent.JdoWriteUncertainError:
                        model.cancel_event=__import__('threading').Event();model.cancel_event.set()
                        errors.append({'skuId':futures[future],'status':'unknown','reason':'Preserve receipt and reconcile exact request before retrying'})
                    except Exception as error:errors.append({'skuId':futures[future],'status':'blocked','failureClass':type(error).__name__,'reason':str(error)[:200] or 'Repair did not complete; inspect reference, adapter and owned receipts'})
        finally:model.close()
        result={'status':'repair-incomplete' if errors or any(r['status']=='rejected' for r in records) else 'repairs-submitted-awaiting-review','shopName':identity['shopName'],'rows':records,'errors':errors,'modelStats':model.image_model_stats(),'allApproved':bool(records) and not errors and all(r['status']=='approved' for r in records),'productTextAppeals':appeal_delivery,'jingmaiFirst':jingmai}
        _save(out/'repair-result.json',result);return result


def install_joyagent_fallback(client,template,output_dir,timeout=180):
    raise RuntimeError('company-generation-fallback-forbidden; external-image-provider-is-LTS4AI-only')
