"""Synthetic-only producer used by the owned isolated video QA smoke."""
import av,json,math,struct,sys
from fractions import Fraction
from pathlib import Path
request=json.loads(sys.stdin.buffer.read());root=Path(request['root']);root.mkdir(parents=True,exist_ok=True)
for audio in (False,True):
 path=root/('with-audio.mp4' if audio else 'silent.mp4')
 with av.open(str(path),'w',format='mp4') as out:
  video=out.add_stream('libx264',rate=30);video.width=64;video.height=64;video.pix_fmt='yuv420p'
  if audio:voice=out.add_stream('aac',rate=48000);voice.layout='stereo'
  for n in range(30):
   frame=av.VideoFrame(64,64,'yuv420p');frame.pts=n;frame.time_base=Fraction(1,30)
   for p in frame.planes:p.update(bytes([32+n*3])*p.buffer_size)
   for packet in video.encode(frame):out.mux(packet)
   if audio:
    sound=av.AudioFrame(format='fltp',layout='stereo',samples=1600);sound.sample_rate=48000;sound.time_base=Fraction(1,48000);sound.pts=n*1600
    data=b''.join(struct.pack('f',0.1*math.sin(2*math.pi*440*(n*1600+i)/48000)) for i in range(1600))
    for p in sound.planes:p.update(data)
    for packet in voice.encode(sound):out.mux(packet)
  for packet in video.encode():out.mux(packet)
  if audio:
   for packet in voice.encode():out.mux(packet)
print(json.dumps({'synthetic':True,'files':['with-audio.mp4','silent.mp4']}))
