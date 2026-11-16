"""Local-only immutable video publication. Candidates never become the active manifest video until both gates pass.
The lock is released by the OS on process termination. Complete orphan files can be reused; partial copies stay in the run candidate directory.
"""
from __future__ import annotations
import copy, hashlib, json, os, re, shutil, uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from PIL import Image
from check_main_video import probe, evaluate, VideoInfo

class PublicationError(RuntimeError):pass

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def read(path,default=None):
    p=Path(path);return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else default

def save(path,data):
    p=Path(path);tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=1),encoding='utf-8');os.replace(tmp,p)

def validate_run_id(run_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',str(run_id)):raise PublicationError('非法runId')

def create_run(root,mode,run_id=None):
    root=Path(root).resolve();run_id=run_id or datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:10];validate_run_id(run_id)
    base=root/'.main-video/runs'/run_id
    if not base.resolve().is_relative_to(root):raise PublicationError('运行目录越界')
    base.mkdir(parents=True,exist_ok=True);candidate=base/'candidate';candidate.mkdir(exist_ok=True)
    if not (base/'run.json').exists():save(base/'run.json',{'runId':run_id,'mode':mode,'createdAt':datetime.now().astimezone().isoformat()})
    return candidate

def run_id_of(candidate):return Path(candidate).parent.name

@contextmanager
def publication_lock(root):
    p=Path(root)/'.main-video/publication.lock';p.parent.mkdir(exist_ok=True)
    f=p.open('a+b');f.seek(0,2)
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise PublicationError('同一package正在发布，请稍后重试')
    try:yield
    finally:
        f.seek(0)
        if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()

def media_info(path,probe_video):
    x=probe_video(Path(path))
    if isinstance(x,tuple):seconds,width,height=x
    else:seconds,width,height=x.seconds,x.width,x.height
    info=VideoInfo(Path('candidate.mp4'),int(width),int(height),float(seconds),Path(path).stat().st_size)
    errors,_=evaluate(info)
    if errors:raise PublicationError('候选规范未通过：'+'；'.join(errors))
    return {'durationSeconds':int(round(seconds)),'durationSecondsExact':float(seconds),'width':int(width),'height':int(height),'sizeBytes':Path(path).stat().st_size}

def commit_manifest(path,data,staging_dir):
    """Final transaction step: write+fsync and parse a local staging file, then one atomic replacement."""
    path=Path(path);tmp=Path(staging_dir)/'manifest-publish.tmp'
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=1);f.flush();os.fsync(f.fileno())
        if read(tmp)!=data:raise PublicationError('manifest临时文件校验失败')
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def install_file(tmp,target,expected):
    """Never replace an existing different file, even though the final rename is atomic."""
    target=Path(target)
    if target.exists():
        if sha256(target)!=expected:raise PublicationError(f'同runId目标文件已存在但内容不同：{target.name}')
        return False
    os.replace(tmp,target);return True

def verify_record(root,v):
    root=Path(root).resolve();errors=[]
    for key,hkey in [('localPath','sha256'),('coverLocalPath','coverSha256')]:
        if not v.get(key):errors.append(f'缺少{key}');continue
        p=(root/v[key]).resolve()
        if not p.is_relative_to(root) or not p.is_file():errors.append(f'{key}越界或文件缺失');continue
        if not v.get(hkey) or sha256(p)!=v[hkey]:errors.append(f'{key} SHA256不一致或缺失')
    return {'ok':not errors,'errors':errors,'runId':v.get('runId')}

def verify_handoff(root):
    return verify_record(root,(read(Path(root) / 'manifest.json',{}) or {}).get('video') or {})

def completed_run(root,run_id,video,cover):
    m=read(Path(root) / 'manifest.json',{});active=m.get('video') or {}
    rows=[active]+list(m.get('videoHistory') or [])
    journal=read(Path(root) / '.main-video/runs' / run_id / 'candidate/publication.json',{})
    if journal.get('status')=='published':rows.append(journal.get('video') or {})
    found=next((v for v in rows if v.get('runId')==run_id),None)
    if not found:return None
    if not found.get('bindable') or not verify_record(root,found)['ok']:raise PublicationError('已完成发布记录校验失败，停止')
    if video.is_file() and sha256(video)!=found.get('sha256'):raise PublicationError('同runId候选视频已改变')
    if cover.is_file() and sha256(cover)!=found.get('coverSha256'):raise PublicationError('同runId候选封面已改变')
    return {'ok':True,'replayed':True,'active':active.get('runId')==run_id,'video':found,'manifest':str(Path(root) / 'manifest.json')}

def publish(root,run_id,video,cover,metadata,probe_video=probe):
    root=Path(root).resolve();validate_run_id(run_id);candidate=root/'.main-video/runs'/run_id/'candidate'
    video,cover=Path(video).resolve(),Path(cover).resolve()
    if not candidate.resolve().is_relative_to(root) or not video.is_relative_to(candidate.resolve()) or not cover.is_relative_to(candidate.resolve()):raise PublicationError('视频和封面必须在本runId候选目录')
    qc=metadata.get('qc') or {}
    auto=qc.get('automatic') or {}
    manual_fallback=(metadata.get('specificationPassed') is True and auto.get('status')=='unavailable' and (auto.get('detail') or {}).get('automaticStatus')=='unavailable'
                     and qc.get('manualOverride')=='automatic_unavailable' and auto.get('pass') is False)
    if metadata.get('bindable') is not True or (not manual_fallback and auto.get('pass') is not True) or (qc.get('manual') or {}).get('pass') is not True:
        raise PublicationError('没有有效自动质检或服务不可用的目视替代证据，不发布候选')
    with publication_lock(root):
        done=completed_run(root,run_id,video,cover)
        if done:return done
    if not video.is_file() or not cover.is_file():raise PublicationError('候选文件缺失')
    video_hash,cover_hash=sha256(video),sha256(cover);info=media_info(video,probe_video)
    try:
        with Image.open(cover) as im:cover_size=im.size;im.verify()
    except Exception as e:raise PublicationError('候选封面无效') from e
    if min(cover_size)<=0:raise PublicationError('候选封面无效')
    mode=metadata.get('mode','ai')
    if mode not in ('ai','material'):raise PublicationError('未知视频模式')
    stem=f'主图视频_{"AI带货" if mode=="ai" else "素材拼接"}_{run_id}'
    folder=root/'视频';target=folder/(stem+'.mp4');target_cover=folder/(stem+'_封面.jpg');manifest=root/'manifest.json'
    if not folder.resolve().is_relative_to(root):raise PublicationError('正式视频目录越界')
    tmp_video=candidate/'publish-video.tmp.mp4';tmp_cover=candidate/'publish-cover.tmp.jpg';created=[]
    with publication_lock(root):
        snapshot=manifest.read_bytes();before=json.loads(snapshot.decode('utf-8-sig'));before_hash=hashlib.sha256(snapshot).hexdigest()
        done=completed_run(root,run_id,video,cover)
        if done:return done
        journal=candidate/'publication.json'
        save(journal,{'status':'preparing','runId':run_id,'beforeManifestSha256':before_hash,'videoSha256':video_hash,'coverSha256':cover_hash})
        try:
            # Complete orphan targets from an interrupted attempt are checked and reused.
            if not target.exists():
                shutil.copyfile(video,tmp_video)
                with tmp_video.open('r+b') as f:os.fsync(f.fileno())
                if sha256(tmp_video)!=video_hash or media_info(tmp_video,probe_video)!=info:raise PublicationError('视频临时复制/媒体校验失败')
            elif sha256(target)!=video_hash:raise PublicationError('目标视频同名但内容不同')
            if not target_cover.exists():
                shutil.copyfile(cover,tmp_cover)
                with tmp_cover.open('r+b') as f:os.fsync(f.fileno())
                if sha256(tmp_cover)!=cover_hash:raise PublicationError('封面临时复制校验失败')
                with Image.open(tmp_cover) as im:im.verify()
            elif sha256(target_cover)!=cover_hash:raise PublicationError('目标封面同名但内容不同')
            folder.mkdir(exist_ok=True)
            if install_file(tmp_video,target,video_hash):created.append(target)
            if install_file(tmp_cover,target_cover,cover_hash):created.append(target_cover)
            if sha256(target)!=video_hash or sha256(target_cover)!=cover_hash:raise PublicationError('正式文件发布校验失败')
            if sha256(manifest)!=before_hash:raise PublicationError('manifest被其他流程改变，停止，保留旧版本')
            new=copy.deepcopy(before);old=new.get('video')
            if old:
                history=new.setdefault('videoHistory',[])
                if old not in history:history.append(copy.deepcopy(old))
            v={**copy.deepcopy(metadata),**info,'localPath':target.relative_to(root).as_posix(),'coverLocalPath':target_cover.relative_to(root).as_posix(),
               'sha256':video_hash,'coverSha256':cover_hash,'runId':run_id,'generatedBy':'jd-main-video-batch','generatedAt':datetime.now().astimezone().isoformat()}
            v.setdefault('voiceReviewRequired',bool(metadata.get('voiceover')))
            new['video']=v;commit_manifest(manifest,new,candidate)
            # A receipt failure after the commit cannot invalidate valid published files.
            try:save(journal,{'status':'published','runId':run_id,'video':v})
            except OSError:pass
            return {'ok':True,'replayed':False,'video':v,'manifest':str(manifest)}
        except Exception as error:
            latest=read(manifest,{})
            if (latest.get('video') or {}).get('runId')==run_id and verify_handoff(root)['ok']:
                return {'ok':True,'replayed':True,'video':latest['video'],'manifest':str(manifest)}
            # Only remove fully verified new files installed by this attempt; never old files.
            for path in created:
                expected=video_hash if path==target else cover_hash
                if path.is_relative_to(folder) and path.exists() and sha256(path)==expected:path.unlink()
            try:save(journal,{'status':'failed','runId':run_id,'errorType':type(error).__name__})
            except OSError:pass
            raise PublicationError(f'发布未完成，旧manifest和旧文件保留：{type(error).__name__}') from error
        finally:
            tmp_video.unlink(missing_ok=True);tmp_cover.unlink(missing_ok=True)
