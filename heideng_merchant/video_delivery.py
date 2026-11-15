"""Approved, receipt-bound native video allocation/transfer/save; never generation."""
from __future__ import annotations
import json,math,os,re,time,uuid
from pathlib import Path
from . import VERSION
from .operations import Operations,digest,_same_identity
from .safety import SafetyError,read_json,atomic_json,safe_join,file_sha,redact
from .state import FileLock
from .official import validate_profile
from .video_handoff import preflight_video,listing_fingerprint
from .video_contract import ALLOC,VIDEOS,SKILL,card,zone,read,native_id,validate_input,id_value
from .video_transfer import UploadGrant,transfer_video,TransferNotDispatched
from .verification import business_payload,pagination_total

ACTIVE={'allocating','allocated','transferring','transferred','saving','saved','unknown'}
STAGES={'allocate','renew','transfer','save'}


def _path(state,session_id,folder='video-sessions',suffix='.json'):
    if not isinstance(session_id,str) or not re.fullmatch('[a-f0-9]{24}',session_id):raise SafetyError('native-video-session-id-required')
    return safe_join(state,folder+'/'+session_id+suffix)


def _once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    try:
        with path.open('x',encoding='utf-8') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:raise SafetyError('native-video-original-record-already-exists') from None


def _valid_time(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _session_scope(scope):
    required={'schemaVersion','shop','manifestPath','video','zoneId','allocation','saveData','cards','originPolicy','limits','generationCalls','executions'}
    optional=set(scope)-required if isinstance(scope,dict) else set()
    if not isinstance(scope,dict) or not required<=set(scope) or optional not in (set(),{'runtimeVersion','planNonce'}) or type(scope['schemaVersion']) is not int or scope['schemaVersion']!=1:raise SafetyError('native-video-original-scope-incomplete')
    if optional and (not isinstance(scope['runtimeVersion'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',scope['runtimeVersion']) or not isinstance(scope['planNonce'],str) or not re.fullmatch('[a-f0-9]{32}',scope['planNonce'])):raise SafetyError('native-video-plan-version-proof-invalid')
    shop=scope['shop'];video=scope['video'];allocation=scope['allocation'];saved=scope['saveData']
    if not isinstance(shop,dict) or set(shop)!={'profile','venderId','shopId','shopName'} or any(not isinstance(v,str) or not v.strip() for v in shop.values()):raise SafetyError('native-video-original-shop-incomplete')
    validate_profile(shop['profile']);native_id(shop['venderId']);native_id(shop['shopId'])
    if not isinstance(scope['manifestPath'],str) or not scope['manifestPath'] or not isinstance(video,dict) or video.get('bindable') is not True or any(not isinstance(video.get(k),str) or not re.fullmatch('[a-f0-9]{64}',video[k]) for k in ('sha256','coverSha256','listingFingerprint')) or not isinstance(video.get('technicalEvidence'),dict) or type(video['technicalEvidence'].get('bytes')) is not int or video['technicalEvidence']['bytes']<=0:raise SafetyError('native-video-original-source-proof-incomplete')
    from .video_probe import validate_evidence
    validate_evidence(video['technicalEvidence'],video['sha256'],video['technicalEvidence']['bytes'])
    if not isinstance(scope['zoneId'],str) or not scope['zoneId'] or allocation!={'zoneId':scope['zoneId'],'fileName':video['sha256']+'.mp4','fileSize':video['technicalEvidence']['bytes'],'videoType':1}:raise SafetyError('native-video-original-allocation-scope-invalid')
    if not isinstance(saved,dict) or set(saved)!={'videoName','videoDesc','videoType','videoSize'} or not isinstance(saved['videoName'],str) or not saved['videoName'].strip() or len(saved['videoName'])>18 or saved['videoDesc']!='商品主图展示' or type(saved['videoType']) is not int or saved['videoType']!=1 or saved['videoSize']!=allocation['fileSize']:raise SafetyError('native-video-original-save-scope-invalid')
    cards=scope['cards'];executions=scope['executions']
    if not isinstance(cards,dict) or set(cards)!={ALLOC,VIDEOS,'read'} or any(not isinstance(c,dict) or not isinstance(c.get('inputSchema'),dict) for c in cards.values()) or not isinstance(executions,dict) or set(executions)!={ALLOC,VIDEOS} or any(not isinstance(e,dict) or e.get('transport')!='official-source-stdin' for e in executions.values()):raise SafetyError('native-video-original-contract-incomplete')
    if scope['originPolicy']!='official-issued-public-https-only-no-redirect-no-auth-headers' or scope['limits']!={'newAllocation':1,'knownIdRenewal':1,'fullTransfer':1,'save':1} or type(scope['generationCalls']) is not int or scope['generationCalls']!=0 or redact(scope)!=scope:raise SafetyError('native-video-original-policy-invalid')


def _session_evidence(state,value):
    ident=value['sessionId'];fingerprint=value['fingerprint'];shop=value['scope']['shop'];attempted=False
    fields={'attempts':{'stage','startedAt','approvalSha256'},'receipts':{'stage','receipt'},'anchors':{'stage','originalReceiptSha256'},'approvals':{'approvalId','approval'}}
    for kind,extra in fields.items():
        folder='video-session-'+kind+'/'+ident;root=safe_join(state,folder)
        if not root.exists():continue
        if not root.is_dir():raise SafetyError('native-video-unreviewed-evidence-layout')
        for entry in root.iterdir():
            path=safe_join(state,folder+'/'+entry.name)
            if not path.is_file() or path.suffix!='.json' or (not re.fullmatch('[a-f0-9]{32}',path.stem) if kind=='approvals' else path.stem not in STAGES):raise SafetyError('native-video-unreviewed-evidence-entry')
            record=read_json(path)
            if not isinstance(record,dict) or set(record)!={'sessionId','fingerprint','shop'}|extra or record['sessionId']!=ident or record['fingerprint']!=fingerprint or record['shop']!=shop or redact(record)!=record:raise SafetyError('native-video-unreviewed-evidence-record')
            if kind=='approvals':
                approval=record['approval']
                if record['approvalId']!=path.stem or not isinstance(approval,dict) or set(approval)!={'confirmed','fingerprint','expiresAt'} or approval['confirmed'] is not True or approval['fingerprint']!=fingerprint or not _valid_time(approval['expiresAt']):raise SafetyError('native-video-unreviewed-approval-record')
            else:
                attempted=True
                if record['stage']!=path.stem:raise SafetyError('native-video-unreviewed-evidence-stage')
                if kind=='attempts' and (not _valid_time(record['startedAt']) or not isinstance(record['approvalSha256'],str) or not re.fullmatch('[a-f0-9]{64}',record['approvalSha256'])):raise SafetyError('native-video-unreviewed-attempt-record')
                if kind=='receipts' and not isinstance(record['receipt'],dict):raise SafetyError('native-video-unreviewed-receipt-record')
                if kind=='anchors' and (not isinstance(record['originalReceiptSha256'],str) or not re.fullmatch('[a-f0-9]{64}',record['originalReceiptSha256'])):raise SafetyError('native-video-unreviewed-anchor-record')
    return attempted


def _load(state,session_id):
    value=read_json(_path(state,session_id))
    if not isinstance(value,dict) or value.get('sessionId')!=session_id or digest(value.get('scope'))!=value.get('fingerprint') or value['fingerprint'][:24]!=session_id:raise SafetyError('native-video-session-scope-changed')
    if value.get('status') not in ACTIVE|{'prepared','ready','rejected','cancelled'} or not isinstance(value.get('receipts'),dict):raise SafetyError('native-video-session-state-invalid')
    _session_scope(value['scope']);attempted=_session_evidence(state,value)
    if 'approval' in value:
        approval_id=value.get('approvalId')
        if not isinstance(approval_id,str) or not re.fullmatch('[a-f0-9]{32}',approval_id):raise SafetyError('original-native-video-parent-approval-required')
        approved=read_json(safe_join(state,'video-session-approvals/'+session_id+'/'+approval_id+'.json'))
        if not isinstance(approved,dict) or approved!={'sessionId':session_id,'fingerprint':value['fingerprint'],'approvalId':approval_id,'approval':value['approval'],'shop':value['scope']['shop']} or digest(approved)!=value.get('approvalSha256'):raise SafetyError('original-native-video-parent-approval-changed')
    for stage,expected in value['receipts'].items():
        if stage not in STAGES:raise SafetyError('native-video-unreviewed-receipt-stage')
        record=read_json(safe_join(state,'video-session-receipts/'+session_id+'/'+stage+'.json'))
        if not isinstance(record,dict) or set(record)!={'sessionId','fingerprint','stage','receipt','shop'} or record['sessionId']!=session_id or record['fingerprint']!=value['fingerprint'] or record['stage']!=stage or record['shop']!=value['scope']['shop'] or digest(record)!=expected or redact(record)!=record:raise SafetyError('independent-original-native-video-receipt-changed')
        anchor=read_json(safe_join(state,'video-session-anchors/'+session_id+'/'+stage+'.json'))
        if not isinstance(anchor,dict) or anchor!={'sessionId':session_id,'fingerprint':value['fingerprint'],'stage':stage,'originalReceiptSha256':expected,'shop':value['scope']['shop']}:raise SafetyError('native-video-original-receipt-anchor-changed')
    missing=[]
    for stage in ('allocate','renew','transfer','save'):
        marker=read_json(safe_join(state,'video-session-attempts/'+session_id+'/'+stage+'.json'))
        evidence=any(safe_join(state,folder+'/'+session_id+'/'+stage+'.json').exists() for folder in ('video-session-receipts','video-session-anchors'))
        if evidence and (stage not in value['receipts'] or marker is None):raise SafetyError('native-video-original-stage-evidence-incomplete-no-replay')
        if marker is not None:
            if marker.get('sessionId')!=session_id or marker.get('fingerprint')!=value['fingerprint'] or marker.get('stage')!=stage or marker.get('approvalSha256')!=value.get('approvalSha256') or marker.get('shop')!=value['scope']['shop']:raise SafetyError('native-video-original-attempt-marker-changed')
            if stage not in value['receipts']:missing.append(stage)
    cancellation=read_json(safe_join(state,'video-session-cancellations/'+session_id+'.json'))
    if cancellation is not None or value['status']=='cancelled':
        if value['status']!='cancelled' or missing or value['receipts'] or not isinstance(cancellation,dict) or set(cancellation)!={'sessionId','fingerprint','shop','cancelledAt'} or not _valid_time(cancellation['cancelledAt']) or cancellation['sessionId']!=session_id or cancellation['fingerprint']!=value['fingerprint'] or cancellation['shop']!=value['scope']['shop'] or digest(cancellation)!=value.get('cancellationSha256'):raise SafetyError('original-unattempted-video-cancellation-required')
    if missing:value.update(status='unknown',unknownStage=missing[0])
    if value['status']=='prepared' and attempted:value.update(status='unknown',unknownStage='original-stage-state-contradiction')
    needed={'allocated':{'allocate'},'transferred':{'allocate','transfer'},'saved':{'allocate','transfer','save'},'ready':{'allocate','transfer','save'},'rejected':{'allocate','transfer','save'}}
    if not needed.get(value['status'],set())<=set(value['receipts']):raise SafetyError('native-video-stage-original-receipts-incomplete')
    return value


def assert_video_resolved(state,shop,exclude=None):
    journals={p.stem for p in (Path(state)/'video-sessions').glob('*.json')};orphans={}
    for folder in ('video-session-attempts','video-session-receipts','video-session-anchors','video-session-approvals'):
        for directory in (Path(state)/folder).glob('*'):
            if not directory.is_dir():raise SafetyError('native-video-evidence-layout-unprovable')
            files=list(directory.glob('*.json'))
            if not files or directory.name in journals:continue
            for path in files:
                record=read_json(safe_join(state,folder+'/'+directory.name+'/'+path.name))
                if not isinstance(record,dict):raise SafetyError('orphaned-native-video-evidence-unprovable')
                orphans.setdefault(directory.name,[]).append(record)
    for records in orphans.values():
        owners=[]
        for record in records:
            owner=record.get('shop')
            if not isinstance(owner,dict) or any(not isinstance(owner.get(key),str) or not owner[key].strip() for key in ('profile','venderId','shopId','shopName')):raise SafetyError('orphaned-native-video-every-record-owner-required')
            validate_profile(owner['profile']);native_id(owner['venderId']);native_id(owner['shopId']);owners.append(owner)
        if not owners or any(owner!=owners[0] for owner in owners):raise SafetyError('orphaned-native-video-evidence-missing-original-journal')
        owner=owners[0]
        if owner.get('profile')==shop['profile'] or all(str(owner.get(k))==str(shop[k]) for k in ('venderId','shopId')):raise SafetyError('same-shop-orphaned-native-video-outcome-unresolved')
    for path in sorted((Path(state)/'video-sessions').glob('*.json')):
        row=read_json(path);subject=row.get('scope',{}).get('shop',{}) if isinstance(row,dict) else {}
        if not subject:raise SafetyError('unprovable-native-video-session-shop')
        same=subject.get('profile')==shop['profile'] or all(str(subject.get(k))==str(shop[k]) for k in ('venderId','shopId'))
        if same and path.stem!=exclude:
            value=_load(state,path.stem)
            attempted=any((Path(state)/'video-session-attempts'/path.stem/(stage+'.json')).exists() for stage in STAGES)
            if value['status'] in ACTIVE or value['status']=='prepared' and attempted:raise SafetyError('same-shop-native-video-outcome-unresolved')


class VideoDelivery:
    def __init__(self,state,client,*,transfer=None):
        self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client);self.transfer=transfer or transfer_video

    def _receipt(self,session,stage):
        if stage not in session['receipts']:return None
        return read_json(safe_join(self.state,'video-session-receipts/'+session['sessionId']+'/'+stage+'.json'))['receipt']

    def _record(self,session,stage,receipt):
        record={'sessionId':session['sessionId'],'fingerprint':session['fingerprint'],'stage':stage,'receipt':receipt,'shop':session['scope']['shop']}
        if redact(record)!=record:raise SafetyError('private-native-video-receipt-refused')
        if not self._marker(session,stage).is_file():raise SafetyError('native-video-original-attempt-before-receipt-required')
        sha=digest(record)
        _once(safe_join(self.state,'video-session-receipts/'+session['sessionId']+'/'+stage+'.json'),record)
        _once(safe_join(self.state,'video-session-anchors/'+session['sessionId']+'/'+stage+'.json'),{'sessionId':session['sessionId'],'fingerprint':session['fingerprint'],'stage':stage,'originalReceiptSha256':sha,'shop':session['scope']['shop']})
        session['receipts'][stage]=sha

    def _marker(self,session,stage):return safe_join(self.state,'video-session-attempts/'+session['sessionId']+'/'+stage+'.json')

    def _start(self,session,stage,status):
        if stage in session['receipts'] or any(safe_join(self.state,folder+'/'+session['sessionId']+'/'+stage+'.json').exists() for folder in ('video-session-receipts','video-session-anchors')):raise SafetyError('native-video-acknowledged-stage-no-replay')
        _once(self._marker(session,stage),{'sessionId':session['sessionId'],'fingerprint':session['fingerprint'],'stage':stage,'startedAt':time.time(),'approvalSha256':session.get('approvalSha256'),'shop':session['scope']['shop']})
        session['status']=status;self._save(session)

    def _save(self,session):atomic_json(_path(self.state,session['sessionId']),session)

    def _body(self,scope,jd):
        schema=scope['cards'][VIDEOS]['inputSchema']['properties']['zoneVideoDTO']['properties']['jdVideoId']
        return {'zoneVideoDTO':{**scope['saveData'],'jdVideoId':id_value(schema,jd)}}

    def _cards(self,shop):return {key:card(self.client,shop,key) for key in (ALLOC,VIDEOS,'read')}

    def _source(self,session):
        scope=session['scope'];result=preflight_video(scope['manifestPath'],state=self.state)
        if result['video']!=scope['video']:raise SafetyError('approved-native-video-source-or-review-changed')
        return safe_join(Path(scope['manifestPath']).parent,scope['video']['localPath'])

    def _check(self,session,*,media=True):
        scope=session['scope'];shop=scope['shop'];approval=session.get('approval',{})
        try:live=(Path(__file__).resolve().parents[1]/'VERSION').read_text(encoding='utf-8-sig').strip()
        except OSError:raise SafetyError('native-video-runtime-version-unavailable') from None
        if scope.get('runtimeVersion')!=VERSION or live!=VERSION:raise SafetyError('native-video-runtime-changed-rebuild-unattempted-plan-and-approval')
        if approval.get('confirmed') is not True or approval.get('fingerprint')!=session['fingerprint'] or isinstance(approval.get('expiresAt'),bool) or not isinstance(approval.get('expiresAt'),(int,float)) or not math.isfinite(approval['expiresAt']) or approval['expiresAt']<=time.time():raise SafetyError('native-video-exact-unexpired-parent-approval-required')
        if not _same_identity(self.client.identity(shop['profile']),shop):raise SafetyError('native-video-approved-shop-changed')
        self.ops._assert_resolved(shop,exclude_video_session=session['sessionId'])
        zone(self.client,shop,scope['zoneId'])
        if self._cards(shop)!=scope['cards']:raise SafetyError('native-video-capability-changed')
        if media:self._source(session)
        if approval['expiresAt']<=time.time():raise SafetyError('native-video-approval-expired-during-preflight')
        return approval['expiresAt']

    def prepare(self,profile,manifest,zone_id,*,name=None):
        with FileLock(self.state/'install.lock'),FileLock(self.state/'video-sessions.lock'):
            shop={k:self.ops.shop(profile)[k] for k in ('profile','venderId','shopId','shopName')};self.ops._assert_resolved(shop)
            if not _same_identity(self.client.identity(profile),shop):raise SafetyError('native-video-planning-shop-changed')
            manifest=Path(manifest).absolute();video=preflight_video(manifest,state=self.state)['video'];selected=zone(self.client,shop,zone_id);cards=self._cards(shop)
            if name is None:name=str(read_json(manifest).get('sourceProduct',{}).get('title') or '商品主图展示')[:18]
            if not isinstance(name,str) or not name.strip() or name!=name.strip() or len(name)>18 or any(ord(c)<32 for c in name) or redact(name)!=name:raise SafetyError('native-video-approved-name-required')
            allocation={'zoneId':selected['zoneId'],'fileName':video['sha256']+'.mp4','fileSize':video['technicalEvidence']['bytes'],'videoType':1};validate_input(cards[ALLOC],allocation)
            save_data={'videoName':name,'videoDesc':'商品主图展示','videoType':1,'videoSize':allocation['fileSize']}
            scope={'schemaVersion':1,'runtimeVersion':VERSION,'shop':shop,'manifestPath':str(manifest.resolve()),'video':video,'zoneId':selected['zoneId'],'allocation':allocation,'saveData':save_data,'cards':cards,'originPolicy':'official-issued-public-https-only-no-redirect-no-auth-headers','limits':{'newAllocation':1,'knownIdRenewal':1,'fullTransfer':1,'save':1},'generationCalls':0}
            sample=self._body(scope,'1');validate_input(cards[VIDEOS],{'zoneId':scope['zoneId']},sample)
            query_sample={'zoneId':scope['zoneId'],'videoType':1,'scopeSet':['BASE'],'page':1,'pageSize':10,'videoIdSet':[id_value(cards['read']['inputSchema']['properties']['videoIdSet'].get('items',{}),'1')]};validate_input(cards['read'],query_sample)
            if listing_fingerprint(read_json(manifest))!=video['listingFingerprint']:raise SafetyError('native-video-manifest-changed-during-planning')
            if not callable(getattr(self.client,'plan_execution',None)) or not callable(getattr(self.client,'allocate_video_upload',None)):raise SafetyError('native-video-confidential-official-transport-required')
            scope['executions']={ALLOC:self.client.plan_execution({'url':ALLOC,'method':'GET','params':allocation,'skillId':SKILL},profile=profile),VIDEOS:self.client.plan_execution({'url':VIDEOS,'method':'POST','params':{'zoneId':scope['zoneId']},'body':sample,'skillId':SKILL},profile=profile)}
            if any(v.get('transport')!='official-source-stdin' for v in scope['executions'].values()) or redact(scope)!=scope:raise SafetyError('native-video-final-deadline-stdin-contract-required')
            intent=digest({'shop':shop,'sourceSha256':video['sha256'],'listingFingerprint':video['listingFingerprint']})
            for p in sorted((self.state/'video-sessions').glob('*.json')):
                old=_load(self.state,p.stem)
                if old.get('intent')==intent and old['status']!='cancelled':
                    old_scope={k:v for k,v in old['scope'].items() if k not in ('manifestPath','planNonce','runtimeVersion')};new_scope={k:v for k,v in scope.items() if k not in ('manifestPath','planNonce','runtimeVersion')}
                    if old_scope!=new_scope:raise SafetyError('preserve-original-native-video-intent-no-reallocation')
                    return self._public(old)
            scope['planNonce']=uuid.uuid4().hex
            fingerprint=digest(scope);session={'sessionId':fingerprint[:24],'fingerprint':fingerprint,'intent':intent,'scope':scope,'status':'prepared','createdAt':time.time(),'receipts':{}}
            _once(_path(self.state,session['sessionId']),session);return self._public(session)

    def approve(self,session_id,fingerprint,*,confirmed=False,ttl_seconds=900):
        with FileLock(_path(self.state,session_id,suffix='.lock')):
            session=_load(self.state,session_id)
            if session['status']!='prepared' or fingerprint!=session['fingerprint'] or confirmed is not True or type(ttl_seconds) is not int or not 30<=ttl_seconds<=3600:raise SafetyError('native-video-exact-parent-confirmation-required')
            session['approval']={'confirmed':True,'fingerprint':fingerprint,'expiresAt':time.time()+ttl_seconds};session['approvalId']=uuid.uuid4().hex
            record={'sessionId':session_id,'fingerprint':fingerprint,'approvalId':session['approvalId'],'approval':session['approval'],'shop':session['scope']['shop']}
            _once(safe_join(self.state,'video-session-approvals/'+session_id+'/'+session['approvalId']+'.json'),record);session['approvalSha256']=digest(record)
            self._save(session);return self._public(session)

    def cancel(self,session_id,fingerprint,*,confirmed=False):
        initial=_load(self.state,session_id)
        with FileLock(self.state/'install.lock'),FileLock(_path(self.state,session_id,suffix='.lock')),FileLock(self.state/('shop-'+initial['scope']['shop']['venderId']+'.lock')):
            session=_load(self.state,session_id)
            if confirmed is not True or fingerprint!=session['fingerprint'] or session['status']!='prepared' or session['receipts'] or any(self._marker(session,stage).exists() for stage in STAGES) or any(safe_join(self.state,folder+'/'+session_id+'/'+stage+'.json').exists() for folder in ('video-session-receipts','video-session-anchors') for stage in STAGES):raise SafetyError('only-exact-unattempted-native-video-plan-can-be-cancelled')
            record={'sessionId':session_id,'fingerprint':fingerprint,'shop':session['scope']['shop'],'cancelledAt':time.time()}
            _once(safe_join(self.state,'video-session-cancellations/'+session_id+'.json'),record);session.update(status='cancelled',cancellationSha256=digest(record));self._save(session);return self._public(session)

    def _grant(self,session,renew=False):
        scope=session['scope'];shop=scope['shop'];params=dict(scope['allocation']);original=self._receipt(session,'allocate');stage='renew' if renew else 'allocate'
        if renew:
            properties=scope['cards'][ALLOC]['inputSchema']['properties'];params.update(jdVideoId=id_value(properties.get('jdVideoId'),original['jdVideoId']),breakPointFlag=True)
        validate_input(scope['cards'][ALLOC],params);deadline=self._check(session)
        operation={'url':ALLOC,'method':'GET','params':params,'skillId':SKILL}
        if self.client.plan_execution(operation,profile=shop['profile'])!=scope['executions'][ALLOC]:raise SafetyError('native-video-allocation-transport-changed')
        self._start(session,stage,'allocating')
        try:
            grant=self.client.allocate_video_upload(shop['profile'],params,write_authorized=True,expected_execution=scope['executions'][ALLOC],expected_shop=shop,authorization_expires_at=deadline)
            if not isinstance(grant,UploadGrant) or renew and grant.jd_video_id!=original['jdVideoId']:raise SafetyError('renewed-grant-original-video-id-mismatch')
            if not renew:
                for entry in (self.state/'video-sessions').glob('*.json'):
                    if entry.stem==session['sessionId']:continue
                    other=_load(self.state,entry.stem);owner=other['scope']['shop']
                    if all(owner[k]==shop[k] for k in ('venderId','shopId')) and self._receipt(other,'allocate') and self._receipt(other,'allocate')['jdVideoId']==grant.jd_video_id:raise SafetyError('existing-native-video-id-requires-explicit-reuse-not-transfer')
            self._record(session,stage,{'jdVideoId':grant.jd_video_id});session['status']='allocated';self._save(session);return grant
        except Exception:session.update(status='unknown',unknownStage=stage);self._save(session);return None

    def execute(self,session_id):
        initial=_load(self.state,session_id)
        with FileLock(self.state/'install.lock'),FileLock(_path(self.state,session_id,suffix='.lock')),FileLock(self.state/('shop-'+initial['scope']['shop']['venderId']+'.lock')):
            session=_load(self.state,session_id)
            if session['status']=='unknown' or session['status'] in ('allocating','transferring','saving','cancelled'):raise SafetyError('native-video-original-outcome-unknown-no-replay')
            if session['status'] in ('saved','ready','rejected'):return self._refresh(session)
            self._check(session);grant=None
            if session['status']=='prepared':grant=self._grant(session)
            elif session['status']=='allocated':grant=self._grant(session,True)
            if session['status']=='unknown':return self._public(session)
            if session['status']=='allocated':
                scope=session['scope'];deadline=self._check(session);path=self._source(session)
                try:
                    receipt=self.transfer(grant,path,scope['video']['sha256'],scope['allocation']['fileSize'],deadline,before_dispatch=lambda:self._start(session,'transfer','transferring'))
                    if not isinstance(receipt,dict) or set(receipt)!={'jdVideoId','httpStatus','sentBytes','originalSha256','responseSha256','responseBytes','singleAttempt','storageVerified'} or not isinstance(receipt.get('responseSha256'),str) or not re.fullmatch('[0-9a-f]{64}',receipt['responseSha256']) or type(receipt.get('responseBytes')) is not int or not 0<=receipt['responseBytes']<=65536:raise SafetyError('exact-nonprivate-native-video-transfer-receipt-required')
                    if receipt.get('jdVideoId')!=self._receipt(session,'allocate')['jdVideoId'] or receipt.get('originalSha256')!=scope['video']['sha256'] or receipt.get('sentBytes')!=scope['allocation']['fileSize'] or receipt.get('singleAttempt') is not True or receipt.get('storageVerified') is not False or type(receipt.get('httpStatus')) is not int or not 200<=receipt['httpStatus']<300:raise SafetyError('native-video-transfer-receipt-does-not-match-approved-source')
                    self._record(session,'transfer',receipt);session['status']='transferred';self._save(session)
                except TransferNotDispatched:
                    if self._marker(session,'transfer').exists():session.update(status='unknown',unknownStage='transfer')
                    else:session.update(status='allocated',lastFailure='transfer-not-dispatched')
                    self._save(session);return self._public(session)
                except Exception:session.update(status='unknown',unknownStage='transfer');self._save(session);return self._public(session)
            if session['status']=='transferred':
                scope=session['scope'];shop=scope['shop'];deadline=self._check(session);allocated=self._receipt(session,'allocate');body=self._body(scope,allocated['jdVideoId']);params={'zoneId':scope['zoneId']};validate_input(scope['cards'][VIDEOS],params,body)
                operation={'url':VIDEOS,'method':'POST','params':params,'body':body,'skillId':SKILL}
                if self.client.plan_execution(operation,profile=shop['profile'])!=scope['executions'][VIDEOS]:raise SafetyError('native-video-save-transport-changed')
                self._start(session,'save','saving')
                try:
                    result=self.client.invoke(shop['profile'],VIDEOS,method='POST',params=params,body=body,skill_id=SKILL,write_authorized=True,expected_execution=scope['executions'][VIDEOS],expected_shop=shop,authorization_expires_at=deadline);data=business_payload(result)
                    if not isinstance(data,dict):raise SafetyError('original-native-video-save-acknowledgement-required')
                    vid=native_id(data.get('videoId'));jd=native_id(data['jdVideoId']) if 'jdVideoId' in data else None
                    if jd is not None and jd!=allocated['jdVideoId']:raise SafetyError('original-video-save-receipt-id-mismatch')
                    self._record(session,'save',{'videoId':vid,'responseJdVideoId':jd});session['status']='saved';self._save(session)
                except Exception:session.update(status='unknown',unknownStage='save');self._save(session);return self._public(session)
            return self._refresh(session)

    def _query(self,session,*,by_jd=False):
        scope=session['scope'];shop=scope['shop'];current=card(self.client,shop,'read')
        if current!=scope['cards']['read']:raise SafetyError('native-video-readback-capability-changed')
        key='jdVideoIdSet' if by_jd else 'videoIdSet';value=self._receipt(session,'allocate')['jdVideoId'] if by_jd else self._receipt(session,'save')['videoId'];schema=current['inputSchema']['properties'].get(key,{}).get('items',{})
        params={'zoneId':scope['zoneId'],'videoType':1,'scopeSet':['BASE'],'page':1,'pageSize':10,key:[id_value(schema,value)]};validate_input(current,params)
        response=read(self.client,shop,VIDEOS,params);rows=business_payload(response)
        if not isinstance(rows,list) or pagination_total(response)!=len(rows) or len(rows)>1 or any(not isinstance(r,dict) for r in rows):raise SafetyError('exact-original-native-video-readback-required')
        if not rows:return None
        row=rows[0];expected_jd=self._receipt(session,'allocate')['jdVideoId'];saved=self._receipt(session,'save')
        if native_id(row.get('jdVideoId'))!=expected_jd or saved and native_id(row.get('videoId'))!=saved['videoId'] or row.get('videoName')!=scope['saveData']['videoName'] or row.get('videoSize')!=scope['allocation']['fileSize'] or type(row.get('videoType')) is not int or row['videoType']!=1 or type(row.get('status')) is not int or row['status'] not in (1,2,3,4,5):raise SafetyError('original-native-video-metadata-fields-mismatch')
        if row['status'] in (2,4):
            clocks=[scope['video']['technicalEvidence']['video']['endMs']]
            if scope['video']['technicalEvidence'].get('audio'):clocks.append(scope['video']['technicalEvidence']['audio']['endMs'])
            duration=row.get('duration')
            if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0 or not math.floor(min(clocks)/1000)<=duration<=math.ceil(max(clocks)/1000):raise SafetyError('native-video-original-duration-readback-mismatch')
        result={k:row.get(k) for k in ('videoId','jdVideoId','videoName','videoSize','videoType','duration','status')}
        index=row.get('indexImage')
        if isinstance(index,str) and re.fullmatch(r'(?:jfs/[A-Za-z0-9_./-]+|https://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]+)',index) and '..' not in index:result['indexImage']=index
        return result

    def _refresh(self,session):
        row=self._query(session)
        if row is None:session.update(status='saved',metadataVerified=False,metadata=None)
        else:
            session.update(metadataVerified=True,metadata=row,observedAt=time.time())
            session['status']='rejected' if row['status']==5 else 'ready' if row['status'] in (2,4) else 'saved'
        self._save(session);return self._public(session,refreshed=True)

    def status(self,session_id,*,refresh=False):
        with FileLock(self.state/'install.lock'),FileLock(_path(self.state,session_id,suffix='.lock')):
            session=_load(self.state,session_id)
            if refresh and session['status'] in ('saved','ready','rejected'):return self._refresh(session)
            if refresh and session['status']=='unknown' and self._receipt(session,'allocate'):
                try:session['unknownObservation']=self._query(session,by_jd=True)
                except Exception:session['unknownObservationState']='unavailable-or-contradictory'
                self._save(session)
            return self._public(session)

    def _public(self,session,*,refreshed=False):
        allocation=self._receipt(session,'allocate');saved=self._receipt(session,'save');metadata=session.get('metadata') or {}
        return {'sessionId':session['sessionId'],'fingerprint':session['fingerprint'],'runtimeVersion':session['scope'].get('runtimeVersion'),'status':session['status'],'unknownStage':session.get('unknownStage'),'videoId':saved['videoId'] if saved else None,'jdVideoId':allocation['jdVideoId'] if allocation else None,'storageVerified':refreshed and session.get('metadataVerified') is True,'metadataHistoricallyVerified':session.get('metadataVerified') is True,'observedAt':session.get('observedAt'),'remoteOriginalBytesVerified':False,'transcodeReady':refreshed and metadata.get('status') in (2,4),'auditApproved':refreshed and metadata.get('status')==4,'auditStatus':metadata.get('status') if refreshed else None,'cachedAuditStatus':metadata.get('status'),'videoName':session['scope']['saveData']['videoName'],'approvalExpiresAt':session.get('approval',{}).get('expiresAt'),'generationCalls':0,'skuBinding':'not-performed'}
