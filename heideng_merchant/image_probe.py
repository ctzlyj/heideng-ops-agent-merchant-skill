"""Decode original image bytes in a Pillow-only isolated child, without rewriting."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError
from heideng_merchant.image_runtime import ImageRuntime

MAX_RAW_BYTES=3_000_000
MAX_FRAME_PIXELS=50_000_000
MAX_TOTAL_PIXELS=100_000_000
FORMATS={'PNG','JPG','GIF','WEBP'}

def probe_image(state,raw):
 if not isinstance(raw,bytes) or not raw or len(raw)>=MAX_RAW_BYTES:raise SafetyError('image-source-exceeds-local-byte-bound')
 runtime=ImageRuntime(state);runtime.ensure();result=runtime._run([str(runtime.python()),'-I','-B',str(Path(__file__).resolve())],runtime.home(),30,input_data=raw)
 try:info=json.loads(result)
 except (ValueError,TypeError):raise SafetyError('image-probe-response-invalid') from None
 if not isinstance(info,dict) or set(info)!={'sha256','format','width','height','bytes','frames'} or info['sha256']!=hashlib.sha256(raw).hexdigest() or info['bytes']!=len(raw) or info['format'] not in FORMATS or any(isinstance(info[k],bool) or not isinstance(info[k],int) or info[k]<=0 for k in ('width','height','frames')) or info['width']*info['height']>MAX_FRAME_PIXELS:raise SafetyError('decoded-image-evidence-mismatch')
 return info

def main():
 try:
  import io,warnings
  from PIL import Image
  raw=sys.stdin.buffer.read(MAX_RAW_BYTES+1)
  if not raw or len(raw)>=MAX_RAW_BYTES:raise SafetyError('image-source-size-invalid')
  Image.MAX_IMAGE_PIXELS=MAX_FRAME_PIXELS
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(io.BytesIO(raw)) as image:
    width,height=image.size;fmt='JPG' if image.format=='JPEG' else image.format;frames=getattr(image,'n_frames',1)
    if fmt not in FORMATS or width<=0 or height<=0 or width*height>MAX_FRAME_PIXELS or not 1<=frames<=1024:raise SafetyError('unsupported-or-oversized-image')
    image.verify()
   pixels=0
   with Image.open(io.BytesIO(raw)) as image:
    for frame in range(frames):
     image.seek(frame);pixels+=image.width*image.height
     if pixels>MAX_TOTAL_PIXELS:raise SafetyError('animated-image-pixel-budget-exceeded')
     image.load()
  result={'sha256':hashlib.sha256(raw).hexdigest(),'format':fmt,'width':width,'height':height,'bytes':len(raw),'frames':frames}
 except Exception:print('{"error":"invalid-or-unsupported-image"}');return 2
 print(json.dumps(result,separators=(',',':')));return 0
if __name__=='__main__':raise SystemExit(main())
