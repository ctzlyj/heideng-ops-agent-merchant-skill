"""Local product alpha extraction: pinned BiRefNet, cached CPU session, no implicit fallback/download."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import threading
import time
import uuid
from io import BytesIO
from contextlib import contextmanager
import importlib.metadata
from PIL import Image

MODELS = {
    'birefnet-general-lite': {
        'file': 'BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx',
        'sha256': '5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333',
    },
    'birefnet-general': {
        'file': 'BiRefNet-general-epoch_244.onnx',
        'sha256': '58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c',
    },
}
DEFAULT_MODEL = 'birefnet-general-lite'

class CutoutUnavailable(RuntimeError):
    pass

class CutoutQualityError(ValueError):
    pass

@dataclass(frozen=True)
class CutoutConfig:
    model: str = DEFAULT_MODEL
    alpha_matting: bool = False
    cpu_threads: int = 4
    def __post_init__(self):
        if self.model not in MODELS:
            raise ValueError('Only pinned BiRefNet models are approved; never use an implicit rembg default')
        if not 1 <= self.cpu_threads <= 8:
            raise ValueError('CPU cutout thread count must be 1-8, independent of image generation concurrency')

_sessions = {}
_session_lock = threading.Lock()
_inference_gate = threading.BoundedSemaphore(1)
_digest_cache = {}
_alpha_cache = {}
_ALPHA_CACHE_LIMIT = 32

def _sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def _verify_model(path, model):
    path=Path(path).resolve();stat=path.stat();key=(str(path),stat.st_size,stat.st_mtime_ns)
    digest=_digest_cache.get(key)
    if digest is None:
        digest=_sha(path);_digest_cache[key]=digest
    if digest != MODELS[model]['sha256']:
        raise CutoutUnavailable('Local cutout weight checksum differs from the reviewed artifact; preserve it, do not run or overwrite')
    return path

def _model_class(model):
    try:
        if importlib.metadata.version('rembg') != '2.0.85':
            raise CutoutUnavailable('rembg version differs from pinned2.0.85; rerun setup with install-missing')
        from rembg.sessions import sessions_class
        return next(cls for cls in sessions_class if cls.name()==model)
    except (ImportError,StopIteration) as error:
        raise CutoutUnavailable('Install the pinned cutout requirements before preparing local weights') from None

def cached_model_path(model):
    if model not in MODELS:raise ValueError('Unknown cutout model')
    cls=_model_class(model)
    path=cls.resolve_existing(model+'.onnx')
    return Path(path) if path is not None else None

def prepare_model(model=DEFAULT_MODEL, *, download=False):
    """Only an explicit preparation step downloads; merchant write execution never does."""
    if model not in MODELS:raise ValueError('Unknown cutout model')
    cls=_model_class(model);path=cached_model_path(model)
    if path is None:
        if not download:raise CutoutUnavailable('Pinned local cutout model missing; run prepare-cutout --download before starting maintenance')
        # Use the official rembg resolver/pooch transport and its upstream checksum.
        # Then verify SHA256 before ONNX loads any graph. No BRIA/default model selection.
        path=Path(cls.download_models())
    _verify_model(path,model)
    return {'status':'prepared','model':model,'sha256':MODELS[model]['sha256'],'modelBytes':path.stat().st_size,'license':'upstream model cards: MIT','downloadDuringMerchantWrites':False}

def inspect_environment():
    missing=[name for name in ('rembg','onnxruntime','pymatting') if importlib.util.find_spec(name) is None]
    models={}
    # Read-only existence probe: no rembg import, inference, checksum load or network.
    roots=[Path(os.environ.get('REMBG_HOME') or Path.home()/'.rembg'),Path.home()/'.u2net']
    if os.environ.get('U2NET_HOME'):roots.append(Path(os.environ['U2NET_HOME']))
    for model in MODELS:
        candidates=[root/'models'/model/(model+'.onnx') for root in roots]+[root/(model+'.onnx') for root in roots]
        models[model]={'present':any(path.is_file() for path in candidates),'checksumVerified':False}
    return {'defaultModel':DEFAULT_MODEL,'missingDependencies':missing,'models':models,'status':'model-cache-present-unverified' if not missing and models[DEFAULT_MODEL]['present'] else 'prepare-required','maxConcurrentInferences':1,'cpuThreadsPerSession':4,'automaticLegacyFallback':False}

def load_verified_session(config):
    path=cached_model_path(config.model)
    if path is None:raise CutoutUnavailable('Pinned model absent; prepare-cutout before merchant execution')
    # Hash and initialize exactly the same immutable graph snapshot. Never call the
    # rembg constructor/new_session: that constructor invokes download_models again.
    graph=path.read_bytes()
    if hashlib.sha256(graph).hexdigest()!=MODELS[config.model]['sha256']:
        raise CutoutUnavailable('Model byte snapshot checksum mismatch; graph not loaded')
    cls=_model_class(config.model)
    try:
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=config.cpu_threads;options.inter_op_num_threads=1
        options.enable_cpu_mem_arena=False;options.enable_mem_pattern=False;options.log_severity_level=4
        session=cls.__new__(cls)
        session.model_name=config.model
        session.inner_session=ort.InferenceSession(graph,sess_options=options,providers=['CPUExecutionProvider'])
        return session
    except Exception:
        raise CutoutUnavailable('Verified local graph initialization failed; no resolver/download/fallback was used') from None

def run_rembg(image, *, session, config):
    from rembg import remove
    if config.alpha_matting:
        result=remove(image,session=session,alpha_matting=True,alpha_matting_foreground_threshold=240,alpha_matting_background_threshold=15,alpha_matting_erode_size=3,post_process_mask=False)
        if not isinstance(result,Image.Image) or 'A' not in result.mode:raise CutoutQualityError('Matting did not produce alpha')
        return result.getchannel('A')
    return remove(image,session=session,only_mask=True,post_process_mask=False)

def infer_alpha(image,config):
    key=(config.model,config.cpu_threads)
    # Bound combined infer+matting work; do not create20 ONNX sessions for20 gateway jobs.
    with _inference_gate:
        with _session_lock:
            session=_sessions.get(key)
            if session is None:
                # A single worker/session policy also bounds resident model memory when
                # switching between Lite and general or different CPU thread settings.
                _sessions.clear()
                session=load_verified_session(config);_sessions[key]=session
        try:
            return run_rembg(image,session=session,config=config)
        except CutoutQualityError:
            raise
        except Exception as error:
            with _session_lock:_sessions.clear()
            raise CutoutUnavailable('Local inference/matting failed; release memory, inspect preparation/resources and retry only local generation in a new output, never replay merchant writes') from None

def reset_runtime():
    with _inference_gate, _session_lock:
        _sessions.clear();_digest_cache.clear();_alpha_cache.clear()

def validate_alpha(alpha):
    if not isinstance(alpha,Image.Image) or alpha.size!=(800,800) or alpha.mode!='L':
        raise CutoutQualityError('Expected800x800 grayscale alpha')
    if alpha.getextrema()!=(0,255):
        raise CutoutQualityError('Empty/opaque mask or no strong foreground/background')
    if any(alpha.getpixel(point)>5 for point in ((0,0),(799,0),(0,799),(799,799))):
        raise CutoutQualityError('Foreground reaches a frame corner; inspect product source')
    histogram=alpha.histogram();foreground=sum(histogram[128:]);ratio=foreground/(800*800)
    if not .005<=ratio<=.98:raise CutoutQualityError('Implausible foreground area; explicit reviewed mask required')
    return {'foregroundRatio':round(ratio,6),'softAlphaPixelCount':sum(histogram[1:255])}

def _make_cutout_locked(source, output, *, config=None):
    config=config or CutoutConfig();source=Path(source).resolve();output=Path(output).resolve()
    if source==output:raise ValueError('Source and output must differ')
    if output.suffix.lower()!='.png':raise ValueError('Transparent output must be PNG')
    source_bytes=source.read_bytes();source_sha=hashlib.sha256(source_bytes).hexdigest();receipt_path=output.with_suffix('.cutout.json')
    signature={'model':config.model,'alphaMatting':config.alpha_matting,'sourceSha256':source_sha,'engineVersion':1}
    if output.exists() or receipt_path.exists():
        if output.is_file() and receipt_path.is_file():
            saved=json.loads(receipt_path.read_text(encoding='utf-8'))
            if saved.get('signature')==signature and saved.get('outputSha256')==_sha(output):
                return {**saved,'cacheReused':True}
        raise ValueError('Existing cutout/receipt does not match; preserve it and select a new output path')
    with Image.open(BytesIO(source_bytes)) as im:
        if im.size!=(800,800):raise ValueError('Normalize the confirmed source to800x800 before local cutout')
        image=im.convert('RGB')
    started=time.perf_counter();cache_key=(source_sha,config.model,config.alpha_matting,config.cpu_threads)
    # Repair groups often share one regenerated white (same bytes, many SKU groups); the
    # deterministic alpha for identical bytes is inferred once per process instead of serially per group.
    with _session_lock:alpha=_alpha_cache.get(cache_key)
    alpha_reused=alpha is not None
    if alpha is None:
        alpha=infer_alpha(image,config)
    quality=validate_alpha(alpha)
    if not alpha_reused:
        with _session_lock:
            if len(_alpha_cache)>=_ALPHA_CACHE_LIMIT:_alpha_cache.pop(next(iter(_alpha_cache)))
            _alpha_cache[cache_key]=alpha.copy()
    # Preserve exact original merchandise RGB; rembg's foreground-color decontamination
    # must not alter physical artwork or white printing. Use only its alpha channel.
    result=image.convert('RGBA');result.putalpha(alpha)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.tmp.png')
    try:
        result.save(temporary,'PNG',optimize=True)
        if temporary.stat().st_size>3000000:raise CutoutQualityError('Cutout PNG exceeds3MB')
        # Exclusive creation prevents racing output replacement. Receipts must both match on reuse.
        with output.open('xb') as stream:stream.write(temporary.read_bytes())
    finally:
        if temporary.exists():temporary.unlink()
    receipt={'status':'generated-local','backend':config.model,'signature':signature,'sourceSha256':source_sha,'outputSha256':_sha(output),'weightSha256':MODELS[config.model]['sha256'],'rgbPixelsUnchanged':True,'elapsedSeconds':round(time.perf_counter()-started,3),'imageBytes':output.stat().st_size,**quality,'platformWrites':0,'platformAuditVerified':False,'cacheReused':False,'alphaCacheReused':alpha_reused}
    # No-clobber receipt commit: an external concurrent writer is preserved even
    # if it ignores the owned output-pair lock. An orphan output blocks unsafe reuse.
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return receipt

def make_cutout(source, output, *, config=None):
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    lock=output.with_suffix('.cutout.lock');owner=uuid.uuid4().hex
    try:
        with lock.open('x',encoding='utf-8') as stream:stream.write(owner)
    except FileExistsError:
        raise ValueError('Local cutout output pair is busy; verify owner before recovery') from None
    try:
        return _make_cutout_locked(source,output,config=config)
    finally:
        if lock.exists() and lock.read_text(encoding='utf-8')==owner:lock.unlink()


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Offline local cutout; no model API key or merchant writes')
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--model',choices=tuple(MODELS),default=DEFAULT_MODEL);prep.add_argument('--download',action='store_true')
    check=sub.add_parser('inspect')
    cut=sub.add_parser('cut');cut.add_argument('--source',type=Path,required=True);cut.add_argument('--output',type=Path,required=True);cut.add_argument('--model',choices=tuple(MODELS),default=DEFAULT_MODEL);cut.add_argument('--alpha-matting',action='store_true');cut.add_argument('--cpu-threads',type=int,default=4)
    args=parser.parse_args(argv)
    if args.command=='inspect':value=inspect_environment()
    elif args.command=='prepare':value=prepare_model(args.model,download=args.download)
    else:value=make_cutout(args.source,args.output,config=CutoutConfig(args.model,args.alpha_matting,args.cpu_threads))
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
