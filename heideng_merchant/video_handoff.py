"""Byte-bound local video handoff. Bindable is readiness, never a shop write."""
from __future__ import annotations
import hashlib,json,os,re,tempfile
from pathlib import Path
from .safety import SafetyError,atomic_json,file_sha,is_linked,read_json,redact,safe_join
from .state import FileLock,merchant_home
from .video_probe import probe_video,probe_video_cover,validate_evidence,_source

REVIEW_KEYS={'sha256','coverSha256','listingFingerprint','technicalPass','visualPass','voiceConfirmed'}


def listing_fingerprint(manifest):
    return hashlib.sha256(json.dumps({k:v for k,v in manifest.items() if k!='video'},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _manifest(path):
    path=Path(path).absolute()
    if is_linked(path):raise SafetyError('linked-video-manifest-not-allowed')
    path=path.resolve()
    with path.open('rb') as stream:original=stream.read(64*1024*1024+1)
    if len(original)>64*1024*1024:raise SafetyError('video-manifest-too-large')
    try:value=json.loads(original)
    except (ValueError,UnicodeDecodeError):raise SafetyError('invalid-video-manifest-json') from None
    if not isinstance(value,dict) or value.get('merchantPackageSchemaVersion')!=1:raise SafetyError('merchant-listing-manifest-required')
    if redact(value)!=value:raise SafetyError('credentials-not-allowed-in-video-manifest')
    return path,value,original


def _review(review,sha,cover_sha,listing):
    if review is None:return {},False
    if not isinstance(review,dict) or set(review)-REVIEW_KEYS or redact(review)!=review:raise SafetyError('video-review-shape-invalid')
    if review.get('sha256')!=sha:raise SafetyError('video-review-hash-mismatch')
    for key in ('technicalPass','visualPass','voiceConfirmed'):
        if key in review and type(review[key]) is not bool:raise SafetyError('video-review-boolean-required')
    for key,value in (('coverSha256',cover_sha),('listingFingerprint',listing)):
        if key in review and review[key]!=value:raise SafetyError('video-review-context-mismatch')
    confirmed=bool(cover_sha) and review.get('coverSha256')==cover_sha and review.get('listingFingerprint')==listing
    return dict(review),bool(confirmed and review.get('visualPass') is True and review.get('voiceConfirmed') is True)


def _checked_copy(source,dest,sha,size):
    if is_linked(source):raise SafetyError('linked-original-video-or-cover')
    count=0
    with Path(source).open('rb') as original,Path(dest).open('xb') as target:
        while True:
            chunk=original.read(min(1024*1024,size-count+1))
            if not chunk:break
            count+=len(chunk)
            if count>size:raise SafetyError('original-video-or-cover-size-changed')
            target.write(chunk)
        target.flush();os.fsync(target.fileno())
    if count!=size or file_sha(dest)!=sha or _source(source,size)[1:]!=(size,sha):raise SafetyError('original-video-or-cover-changed-during-copy')


def _publish(stage,dest,sha):
    if dest.exists():
        if file_sha(dest)!=sha:raise SafetyError('existing-content-addressed-video-file-changed')
        return
    # Same-filesystem hard link creates a name atomically without overwriting.
    try:os.link(stage,dest)
    except FileExistsError:
        if file_sha(dest)!=sha:raise SafetyError('video-file-publication-conflict') from None
    except OSError:raise SafetyError('atomic-local-video-publication-unavailable') from None


def attach_video(manifest_path,video,cover=None,review=None,*,state=None):
    manifest_path,manifest,_=_manifest(manifest_path);root=manifest_path.parent
    state=Path(state) if state is not None else merchant_home()
    with FileLock(safe_join(root,'.video-handoff.lock'),timeout=5):
        manifest_path,manifest,original=_manifest(manifest_path);listing=listing_fingerprint(manifest)
        video=Path(video).absolute()
        technical=probe_video(state,video);sha=technical['sha256'];validate_evidence(technical,sha,video.stat().st_size)
        cover_info=None
        if cover:
            cover=Path(cover).absolute();cover_info=probe_video_cover(state,cover)
        cover_sha=cover_info['sha256'] if cover_info else None
        feedback,bindable=_review(review,sha,cover_sha,listing)
        context=bool(cover_sha and feedback.get('coverSha256')==cover_sha and feedback.get('listingFingerprint')==listing)
        visual=context and feedback.get('visualPass') is True;voice=context and feedback.get('voiceConfirmed') is True
        relative='video/'+sha+'.mp4'
        info={'schemaVersion':2,'origin':'user-supplied','localPath':relative,'sha256':sha,'bindable':bindable,'taskId':None,'upstreamRepository':'ctzlyj/jd-pop-main-video-skill','listingFingerprint':listing,'technicalEvidence':technical,'review':{'technical':'verified-full-decode','visual':'confirmed' if visual else 'pending','voice':'confirmed' if voice else 'pending'},'reviewEvidence':feedback}
        if cover_info:
            suffix={'PNG':'.png','JPG':'.jpg','WEBP':'.webp'}[cover_info['format']]
            name='video/'+cover_sha+suffix;info.update(coverPath=name,coverSha256=cover_sha,coverEvidence=cover_info)
        with tempfile.TemporaryDirectory(prefix='.video-handoff-',dir=root) as temporary:
            stage=Path(temporary);_checked_copy(video,stage/'video.mp4',sha,technical['bytes'])
            if cover_info:_checked_copy(cover,stage/'cover',cover_sha,cover_info['bytes'])
            if manifest_path.read_bytes()!=original:raise SafetyError('listing-manifest-changed-during-video-review')
            destination=safe_join(root,relative);destination.parent.mkdir(exist_ok=True)
            _publish(stage/'video.mp4',destination,sha)
            if cover_info:_publish(stage/'cover',safe_join(root,name),cover_sha)
            if file_sha(destination)!=sha or (cover_info and file_sha(safe_join(root,name))!=cover_sha):raise SafetyError('published-video-or-cover-hash-mismatch')
            if manifest_path.read_bytes()!=original:raise SafetyError('listing-manifest-changed-before-video-handoff')
            manifest['video']=info;atomic_json(manifest_path,manifest)
        return manifest


def preflight_video(manifest_path,*,state=None):
    """Re-decode before future upload/bind; a cached bindable boolean is not proof."""
    manifest_path,manifest,_=_manifest(manifest_path);root=manifest_path.parent
    state=Path(state) if state is not None else merchant_home()
    with FileLock(safe_join(root,'.video-handoff.lock'),timeout=5):
        manifest_path,manifest,original=_manifest(manifest_path);info=manifest.get('video',{})
        if not isinstance(info,dict) or info.get('schemaVersion')!=2 or info.get('bindable') is not True or info.get('listingFingerprint')!=listing_fingerprint(manifest):raise SafetyError('video-handoff-not-reviewed-for-current-listing')
        sha=info.get('sha256');cover_sha=info.get('coverSha256')
        if not all(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) for value in (sha,cover_sha)):raise SafetyError('video-handoff-original-hashes-required')
        video=safe_join(root,info.get('localPath',''));cover=safe_join(root,info.get('coverPath',''))
        if file_sha(video)!=sha or file_sha(cover)!=cover_sha:raise SafetyError('video-handoff-original-bytes-changed')
        _,confirmed=_review(info.get('reviewEvidence'),sha,cover_sha,info['listingFingerprint'])
        if not confirmed:raise SafetyError('video-handoff-confirmation-evidence-required')
        technical=probe_video(state,video);cover_info=probe_video_cover(state,cover)
        if _source(video,technical['bytes'])[1:]!=(technical['bytes'],sha) or _source(cover,cover_info['bytes'])[1:]!=(cover_info['bytes'],cover_sha):raise SafetyError('video-handoff-original-changed-during-preflight')
        if technical!=info.get('technicalEvidence') or cover_info!=info.get('coverEvidence') or manifest_path.read_bytes()!=original:raise SafetyError('video-handoff-decode-evidence-changed')
        return {'status':'locally-reviewed','video':info,'shopWrites':0,'generationCalls':0}
