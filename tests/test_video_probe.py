import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError

def box(kind,payload):return (len(payload)+8).to_bytes(4,'big')+kind+payload

def structural_mp4(external=False):
 dref=box(b'dref',b'\0'*4+(1).to_bytes(4,'big')+box(b'url ',b'\0\0\0'+(b'\0' if external else b'\1')+(b'https://invalid.example/' if external else b'')))
 track=box(b'trak',box(b'mdia',box(b'minf',box(b'dinf',dref))))
 return box(b'ftyp',b'isom\0\0\0\0isom')+box(b'mdat',b'synthetic')+box(b'moov',track)

def evidence(raw):
 return {'schemaVersion':1,'policy':'mp4-full-decode-v1','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'container':'mp4','video':{'codec':'h264','width':64,'height':64,'frames':30,'startMs':0,'endMs':1000,'durationMs':1000},'audio':None,'decodedAll':True}

class VideoProbeBoundaryTests(unittest.TestCase):
 def test_parent_rejects_decoder_hash_or_shape_mismatch(self):
  from heideng_merchant.video_probe import probe_video
  raw=structural_mp4()
  class Runtime:
   def ensure(self):return {'status':'ready'}
   def python(self):return Path('synthetic-python')
   def home(self):return Path('.')
   def _run(self,*args,**kw):return json.dumps(evidence(raw)|{'sha256':'0'*64}).encode()
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.video_probe.VideoRuntime',return_value=Runtime()):
   path=Path(d)/'clip.mp4';path.write_bytes(raw)
   with self.assertRaises(SafetyError):probe_video(Path(d)/'state',path)
 def test_external_data_reference_rejected_before_runtime(self):
  from heideng_merchant.video_probe import probe_video
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.video_probe.VideoRuntime') as runtime:
   path=Path(d)/'clip.mp4';path.write_bytes(structural_mp4(True))
   with self.assertRaises(SafetyError):probe_video(Path(d)/'state',path)
   runtime.assert_not_called()
 def test_truncated_container_rejected_before_runtime(self):
  from heideng_merchant.video_probe import probe_video
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.video_probe.VideoRuntime') as runtime:
   path=Path(d)/'clip.mp4';path.write_bytes(structural_mp4()[:-1])
   with self.assertRaises(SafetyError):probe_video(Path(d)/'state',path)
   runtime.assert_not_called()
 def test_parent_detects_source_change_during_decoder(self):
  from heideng_merchant.video_probe import probe_video
  raw=structural_mp4()
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'clip.mp4';path.write_bytes(raw)
   class Runtime:
    def ensure(self):return {'status':'ready'}
    def python(self):return Path('synthetic-python')
    def home(self):return Path('.')
    def _run(self,*a,**kw):path.write_bytes(raw+b'changed');return json.dumps(evidence(raw)).encode()
   with patch('heideng_merchant.video_probe.VideoRuntime',return_value=Runtime()):
    with self.assertRaises(SafetyError):probe_video(Path(d)/'state',path)

class VideoRuntimeBoundaryTests(unittest.TestCase):
 def test_video_runtime_isolated_pinned_hashed_and_existing_pools_untouched(self):
  from heideng_merchant.video_runtime import VideoRuntime
  calls=[];urls=[]
  class Result:returncode=0;stdout=b'{"av":"16.1.0"}';stderr=b''
  def runner(args,**kw):
   calls.append((args,kw))
   if '--require-hashes' in args:kw['requirements']=Path(args[args.index('-r')+1]).read_text()
   if 'venv' in args:
    p=Path(args[-1])/('Scripts/python.exe' if os.name=='nt' else 'bin/python');p.parent.mkdir(parents=True);p.write_bytes(b'synthetic interpreter')
    site=p.parent.parent/('Lib/site-packages' if os.name=='nt' else 'lib/python3.12/site-packages');(site/'av').mkdir(parents=True);(site/'av/__init__.py').write_text('# synthetic decoder')
   return Result()
  def metadata(url):
   urls.append(url);return {'info':{'version':'16.1.0','license_expression':'BSD-3-Clause'},'urls':[{'packagetype':'bdist_wheel','digests':{'sha256':'a'*64}}]}
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);old=state/'runtime/browser-runtime.json';old.parent.mkdir();old.write_text('{"sentinel":"keep"}');image=state/'runtime/image-runtime.json';image.write_text('{"sentinel":"image"}')
   runtime=VideoRuntime(state,runner=runner,metadata=metadata);self.assertEqual(runtime.ensure()['status'],'ready')
   self.assertEqual(urls,['https://pypi.org/pypi/av/16.1.0/json']);self.assertEqual(old.read_text(),'{"sentinel":"keep"}');self.assertEqual(image.read_text(),'{"sentinel":"image"}')
   install=[(args,kw) for args,kw in calls if '--only-binary=:all:' in args][0]
   self.assertIn('--require-hashes',install[0]);self.assertIn('--no-deps',install[0]);self.assertIn('av==16.1.0 --hash=sha256:'+'a'*64,install[1]['requirements'])
   self.assertTrue(all('JD_LLM_API_KEY' not in kw['env'] for _,kw in calls));self.assertTrue(any('import av' in arg for args,_ in calls for arg in args))

class VideoEvidenceStrictnessTests(unittest.TestCase):
 def test_child_shape_counts_clocks_and_audio_are_fail_closed(self):
  from copy import deepcopy
  from heideng_merchant.video_probe import validate_evidence
  raw=structural_mp4();good=evidence(raw)
  mutations=[lambda r:r.update(decodedAll=False),lambda r:r.update(schemaVersion=True),lambda r:r.update(extra='unexpected'),lambda r:r['video'].update(frames=True),lambda r:r['video'].update(width=5000),lambda r:r['video'].update(frames=999999),lambda r:r['video'].update(durationMs=0),lambda r:r['video'].update(codec='unverified-codec'),lambda r:r['video'].update(startMs=999),lambda r:r['video'].update(frames=121),lambda r:r.update(audio={'codec':'aac'})]
  for mutate in mutations:
   with self.subTest(mutation=mutate):
    info=deepcopy(good);mutate(info)
    with self.assertRaises(SafetyError):validate_evidence(info,good['sha256'],len(raw))
 def test_invalid_cover_bytes_are_not_a_decode_receipt(self):
  from heideng_merchant.video_probe import probe_video_cover
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.video_probe.probe_image',side_effect=SafetyError('invalid-or-unsupported-image')):
   path=Path(d)/'cover.png';path.write_bytes(b'not-a-picture')
   with self.assertRaises(SafetyError):probe_video_cover(Path(d)/'state',path)

class VideoInstalledIntegrityTests(unittest.TestCase):
 def test_modified_decoder_refused_before_import_even_if_version_unchanged(self):
  from heideng_merchant.video_runtime import VideoRuntime
  calls=[]
  class Result:returncode=0;stdout=b'{"av":"16.1.0"}';stderr=b''
  def runner(args,**kw):
   calls.append(args)
   if 'venv' in args:
    root=Path(args[-1]);p=root/('Scripts/python.exe' if os.name=='nt' else 'bin/python');p.parent.mkdir(parents=True);p.write_bytes(b'synthetic interpreter')
    site=root/('Lib/site-packages' if os.name=='nt' else 'lib/python3.12/site-packages');(site/'av').mkdir(parents=True);(site/'av/__init__.py').write_text('# original synthetic decoder')
   return Result()
  with tempfile.TemporaryDirectory() as d:
   runtime=VideoRuntime(Path(d),runner=runner,metadata=lambda u:{'info':{'version':'16.1.0','license_expression':'BSD-3-Clause'},'urls':[{'packagetype':'bdist_wheel','digests':{'sha256':'a'*64}}]});runtime.ensure()
   python=Path(d)/json.loads(runtime.receipt.read_text())['python'];venv=python.parent.parent;init=next(venv.glob('**/av/__init__.py'));init.write_text('# replaced decoder without version change');calls.clear()
   self.assertEqual(runtime.status()['status'],'not-prepared');self.assertFalse(calls,'unverified decoder was imported')
   with self.assertRaises(SafetyError):runtime.ensure()
