"""Full original-MP4 decode in an isolated PyAV child; never rewrites media."""
from __future__ import annotations
import hashlib,json,math,os,struct,sys
from fractions import Fraction
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError,file_sha,is_linked
from heideng_merchant.video_runtime import VideoRuntime
from heideng_merchant.image_probe import probe_image

MAX_RAW_BYTES=500*1024*1024
MAX_FRAME_PIXELS=4096*4096
MAX_TOTAL_PIXELS=12_000_000_000
MAX_DURATION_MS=180_000
MAX_FRAMES=21_600
MAX_COVER_BYTES=3_000_000
POLICY='mp4-full-decode-v1'


def _source(path,maximum):
    path=Path(path).absolute()
    if is_linked(path) or not path.is_file():raise SafetyError('original-local-media-file-required')
    size=path.stat().st_size
    if not 0<size<=maximum:raise SafetyError('media-source-exceeds-local-byte-bound')
    digest=hashlib.sha256();total=0
    with path.open('rb') as stream:
        while True:
            chunk=stream.read(min(1024*1024,maximum-total+1))
            if not chunk:break
            total+=len(chunk)
            if total>maximum:raise SafetyError('media-source-exceeds-local-byte-bound')
            digest.update(chunk)
    if total!=size:raise SafetyError('media-source-changed-during-hash')
    return path.resolve(),size,digest.hexdigest()


def _boxes(stream,start,end,budget):
    position=start
    while position<end:
        budget[0]+=1
        if budget[0]>10_000 or end-position<8:raise SafetyError('invalid-or-oversized-mp4-box-layout')
        stream.seek(position);header=stream.read(8)
        length,kind=struct.unpack('>I4s',header);header_size=8
        if length==1:
            if end-position<16:raise SafetyError('truncated-mp4-box')
            length=struct.unpack('>Q',stream.read(8))[0];header_size=16
        elif length==0:length=end-position
        if length<header_size or position+length>end:raise SafetyError('truncated-mp4-box')
        yield kind,position+header_size,position+length
        position+=length


def check_mp4_layout(path,size):
    """Bound container structure and reject external track data before decoding."""
    with Path(path).open('rb') as stream:
        budget=[0];top=list(_boxes(stream,0,size,budget));types=[t[0] for t in top]
        if not types or types[0]!=b'ftyp' or types.count(b'ftyp')!=1 or types.count(b'moov')!=1 or b'mdat' not in types or b'moof' in types:
            raise SafetyError('complete-nonfragmented-mp4-required')
        _,start,end=top[0]
        if not 8<=end-start<=4096 or (end-start)%4:raise SafetyError('invalid-mp4-brand-box')
        stream.seek(start);brands=stream.read(end-start)
        if not any(brand in [brands[:4],*[brands[i:i+4] for i in range(8,len(brands),4)]] for brand in (b'isom',b'iso2',b'mp41',b'mp42',b'avc1')):
            raise SafetyError('unsupported-mp4-brand')
        references=[]
        def visit(start,end,depth=0):
            if depth>8:raise SafetyError('mp4-box-nesting-exceeds-bound')
            for kind,left,right in _boxes(stream,start,end,budget):
                if kind in (b'moov',b'trak',b'mdia',b'minf',b'dinf'):visit(left,right,depth+1)
                elif kind==b'dref':
                    if right-left<8:raise SafetyError('invalid-mp4-data-reference')
                    stream.seek(left);version,count=struct.unpack('>II',stream.read(8))
                    entries=list(_boxes(stream,left+8,right,budget))
                    if version!=0 or count!=1 or len(entries)!=1:raise SafetyError('unsupported-mp4-data-reference')
                    kind,a,b=entries[0];stream.seek(a)
                    if kind!=b'url ' or b-a!=4 or stream.read(4)!=b'\0\0\0\1':raise SafetyError('external-mp4-data-reference-not-allowed')
                    references.append(True)
        for kind,left,right in top:
            if kind==b'moov':visit(left,right)
        if not references:raise SafetyError('self-contained-mp4-tracks-required')


def _int(value,low,high):return type(value) is int and low<=value<=high


def _track_evidence(track,audio=False):
    keys={'codec','samples','sampleRate','channels','frames','startMs','endMs','durationMs'} if audio else {'codec','width','height','frames','startMs','endMs','durationMs'}
    if not isinstance(track,dict) or set(track)!=keys:return False
    if track['codec'] not in (('aac',) if audio else ('h264',)):return False
    if not all(_int(track[k],0,MAX_DURATION_MS+250) for k in ('startMs','endMs','durationMs')):return False
    if track['startMs']>250 or not 0<track['durationMs']<=MAX_DURATION_MS or track['endMs']-track['startMs']!=track['durationMs']:return False
    if not _int(track['frames'],1,MAX_FRAMES):return False
    if audio:return _int(track['samples'],1,18_000_000) and _int(track['sampleRate'],8000,96000) and _int(track['channels'],1,2) and abs(track['samples']*1000/track['sampleRate']-track['durationMs'])<=2
    return _int(track['width'],1,4096) and _int(track['height'],1,4096) and track['width']*track['height']*track['frames']<=MAX_TOTAL_PIXELS and track['frames']*1000/track['durationMs']<=120.1


def validate_evidence(info,sha,size):
    if not isinstance(info,dict) or set(info)!={'schemaVersion','policy','sha256','bytes','container','video','audio','decodedAll'} or type(info['schemaVersion']) is not int or info['schemaVersion']!=1 or info['policy']!=POLICY or info['sha256']!=sha or type(info['bytes']) is not int or info['bytes']!=size or info['container']!='mp4' or info['decodedAll'] is not True or not _track_evidence(info['video']):
        raise SafetyError('decoded-video-evidence-mismatch')
    if info['audio'] is not None and (not _track_evidence(info['audio'],True) or abs(info['video']['endMs']-info['audio']['endMs'])>250):
        raise SafetyError('decoded-audio-evidence-mismatch')
    return info


def probe_video(state,path):
    path,size,sha=_source(path,MAX_RAW_BYTES);check_mp4_layout(path,size)
    runtime=VideoRuntime(state);runtime.ensure()
    raw=runtime._run([str(runtime.python()),'-I','-B',str(Path(__file__).resolve())],runtime.home(),120,input_data=json.dumps({'path':str(path),'sha256':sha,'bytes':size}).encode())
    try:info=json.loads(raw)
    except (ValueError,TypeError):raise SafetyError('video-probe-response-invalid') from None
    validate_evidence(info,sha,size)
    if _source(path,MAX_RAW_BYTES)[1:]!=(size,sha):raise SafetyError('video-source-changed-during-decode')
    return info


def probe_video_cover(state,path):
    path,size,sha=_source(path,MAX_COVER_BYTES-1)
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise SafetyError('static-video-cover-image-required')
    raw=path.read_bytes();info=probe_image(state,raw)
    if info['frames']!=1 or info['format'] not in ('PNG','JPG','WEBP') or info['sha256']!=sha or info['bytes']!=size or _source(path,MAX_COVER_BYTES-1)[1:]!=(size,sha):
        raise SafetyError('video-cover-evidence-mismatch')
    return info


def _milliseconds(time):return round(time*1000)


def decode_original(path,sha,size):
    import av
    av.logging.set_level(av.logging.PANIC)
    if _source(path,MAX_RAW_BYTES)[1:]!=(size,sha):raise SafetyError('video-source-changed-before-decode')
    check_mp4_layout(path,size)
    with Path(path).open('rb') as source,av.open(source,mode='r',options={'protocol_whitelist':'','err_detect':'explode'}) as container:
        if not {'mov','mp4'}.intersection(container.format.name.split(',')):raise SafetyError('mp4-container-required')
        videos=list(container.streams.video);audios=list(container.streams.audio)
        if len(videos)!=1 or len(audios)>1 or len(container.streams)!=len(videos)+len(audios):raise SafetyError('one-video-and-at-most-one-audio-track-required')
        streams=videos+audios;records={};total_pixels=0
        for stream in streams:
            cc=stream.codec_context;cc.thread_count=1;cc.options={**cc.options,'err_detect':'explode'}
            if cc.name not in (('h264',) if stream.type=='video' else ('aac',)):raise SafetyError('unsupported-local-video-codec')
            if not stream.duration or not stream.time_base or not 0<stream.duration*stream.time_base<=Fraction(MAX_DURATION_MS,1000):raise SafetyError('bounded-declared-stream-duration-required')
            if stream.type=='video' and (not 0<cc.width<=4096 or not 0<cc.height<=4096 or cc.width*cc.height>MAX_FRAME_PIXELS):raise SafetyError('video-dimensions-exceed-bound')
            if stream.type=='audio' and (not 8000<=cc.sample_rate<=96000 or not 1<=len(cc.layout.channels)<=2):raise SafetyError('audio-format-exceeds-bound')
            records[stream.index]={'stream':stream,'frames':0,'start':None,'end':None,'samples':0}
        for packet in container.demux(*streams):
            if packet.is_corrupt:raise SafetyError('corrupt-media-packet')
            record=records[packet.stream.index];stream=record['stream']
            for frame in packet.decode():
                if frame.is_corrupt or frame.pts is None or frame.time_base is None:raise SafetyError('corrupt-or-unclocked-media-frame')
                start=frame.pts*frame.time_base
                if stream.type=='video':
                    if (frame.width,frame.height)!=(stream.codec_context.width,stream.codec_context.height) or not frame.duration:raise SafetyError('variable-or-unclocked-video-frame')
                    span=frame.duration*frame.time_base;total_pixels+=frame.width*frame.height
                    if total_pixels>MAX_TOTAL_PIXELS:raise SafetyError('video-total-pixel-budget-exceeded')
                else:
                    if frame.sample_rate!=stream.codec_context.sample_rate or frame.samples<=0 or len(frame.layout.channels)!=len(stream.codec_context.layout.channels):raise SafetyError('variable-audio-format')
                    span=Fraction(frame.samples,frame.sample_rate);record['samples']+=frame.samples
                    if record['samples']>18_000_000:raise SafetyError('audio-sample-budget-exceeded')
                    if frame.format.name in ('flt','fltp','dbl','dblp'):
                        channels=1 if frame.format.is_planar else len(frame.layout.channels)
                        for plane in frame.planes:
                            data=bytes(plane)[:frame.samples*frame.format.bytes*channels]
                            code='f' if frame.format.bytes==4 else 'd'
                            if any(not math.isfinite(x[0]) for x in struct.iter_unpack('='+code,data)):raise SafetyError('nonfinite-decoded-audio')
                end=start+span
                if span<=0 or start<0 or end>Fraction(MAX_DURATION_MS+250,1000):raise SafetyError('decoded-media-clock-exceeds-bound')
                if record['start'] is None:
                    if start>Fraction(1,4):raise SafetyError('media-start-gap-exceeds-bound')
                    record['start']=start
                elif abs(start-record['end'])>Fraction(2,1000):raise SafetyError('discontinuous-decoded-media-clock')
                record['frames']+=1;record['end']=end
                if record['frames']>MAX_FRAMES:raise SafetyError('decoded-frame-budget-exceeded')
        results={}
        for record in records.values():
            stream=record['stream'];cc=stream.codec_context
            if not record['frames']:raise SafetyError('empty-media-track')
            measured=record['end']-record['start'];declared=stream.duration*stream.time_base
            if abs(measured-declared)>Fraction(1,10):raise SafetyError('declared-and-decoded-duration-mismatch')
            if stream.type=='video' and stream.frames and stream.frames!=record['frames']:raise SafetyError('declared-and-decoded-frame-count-mismatch')
            result={'codec':cc.name,'frames':record['frames'],'startMs':_milliseconds(record['start']),'endMs':_milliseconds(record['end'])}
            result['durationMs']=result['endMs']-result['startMs']
            if stream.type=='video':result.update(width=cc.width,height=cc.height)
            else:result.update(samples=record['samples'],sampleRate=cc.sample_rate,channels=len(cc.layout.channels))
            results[stream.type]=result
    if _source(path,MAX_RAW_BYTES)[1:]!=(size,sha):raise SafetyError('video-source-changed-during-decode')
    return validate_evidence({'schemaVersion':1,'policy':POLICY,'sha256':sha,'bytes':size,'container':'mp4','video':results['video'],'audio':results.get('audio'),'decodedAll':True},sha,size)


def main():
    try:
        request=json.loads(sys.stdin.buffer.read(32769))
        if not isinstance(request,dict) or set(request)!={'path','sha256','bytes'}:raise SafetyError('video-probe-input-invalid')
        info=decode_original(request['path'],request['sha256'],request['bytes'])
    except Exception:
        print('{"error":"invalid-or-unsupported-original-video"}');return 2
    print(json.dumps(info,separators=(',',':')));return 0

if __name__=='__main__':raise SystemExit(main())
