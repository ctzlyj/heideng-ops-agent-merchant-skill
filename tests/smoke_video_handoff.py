"""New HOME, real public decoders and installed CLI; synthetic media, no shop calls."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,atomic_json,file_sha,read_json
from tests.material_fixtures import png

PREPARE=r'''
import sys,json
from pathlib import Path
installed=Path(sys.argv[1]);sys.path.insert(0,str(installed));from heideng_merchant.video_runtime import VideoRuntime
from heideng_merchant.image_runtime import ImageRuntime
# Public decoder installs are separate from socket-disabled commands.
from heideng_merchant.state import merchant_home
state=merchant_home(sys.argv[2]);video=VideoRuntime(state);image=ImageRuntime(state)
assert video.ensure()['status']=='ready' and image.ensure()['status']=='ready'
print(video._run([str(video.python()),'-I','-B',sys.argv[3]],video.home(),90,input_data=json.dumps({'root':sys.argv[4]}).encode()).decode())
'''
SHIM=r'''
import sys,socket
from pathlib import Path
installed=Path(sys.argv[1]);del sys.argv[1];sys.path.insert(0,str(installed))
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline network forbidden'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline network forbidden'))
from heideng_merchant import cli
assert Path(cli.__file__).resolve().is_relative_to(installed.resolve())
class NoShopClient:
 def __init__(self,state):pass
 def invoke(self,*a,**kw):raise AssertionError('shop call forbidden')
cli.OfficialClient=NoShopClient
raise SystemExit(cli.main())
'''

def main():
 bundle=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(bundle)
 with tempfile.TemporaryDirectory(prefix='hv-') as temporary:
  home=Path(temporary);env=clean_environment(home);state=home/'.heideng-merchant';state.mkdir()
  def run(args,code=0):
   r=subprocess.run([str(a) for a in args],env=env,cwd=ROOT,capture_output=True,timeout=600)
   if r.returncode!=code:
    out=ROOT/'.agent-work/video-qa-audit';out.mkdir(parents=True,exist_ok=True);(out/'synthetic-smoke-failure.log').write_bytes(r.stdout+r.stderr)
   assert r.returncode==code,'synthetic installed video smoke failed; ignored diagnostic retained'
   return r.stdout
  run([sys.executable,'-I','-B',ROOT/'install.py','--offline','--home',home,'--archive',bundle,'--sha256',sha])
  installed=home/'.codex/skills/heideng-ops-agent-merchant';prepare=home/'prepare.py';prepare.write_text(PREPARE,encoding='utf-8');media=home/'media'
  run([sys.executable,'-I','-B',prepare,installed,home,ROOT/'tests/video_fixture_producer.py',media])
  shim=home/'offline-cli.py';shim.write_text(SHIM,encoding='utf-8')
  def command(*args,code=0):return json.loads(run([sys.executable,'-I','-B',shim,installed,'--home',home,*args],code))
  assert command('video-runtime-status')['packages']=={'av':'16.1.0'}
  clips={name:command('probe-video','--video',media/name) for name in ('silent.mp4','with-audio.mp4')}
  assert clips['silent.mp4']['audio'] is None and clips['with-audio.mp4']['audio']['samples']>0
  assert all(r['video']['frames']==30 and r['video']['durationMs']==1000 and r['decodedAll'] for r in clips.values())
  manifest=home/'manifest.json';atomic_json(manifest,{'merchantPackageSchemaVersion':1,'sourceProduct':{'title':'synthetic fixture'}});cover=home/'cover.png';cover.write_bytes(png());video=media/'with-audio.mp4';original_sha=file_sha(video)
  pending=command('attach-video','--manifest',manifest,'--video',video,'--cover',cover)['video'];assert not pending['bindable']
  review=home/'review.json';atomic_json(review,{'sha256':original_sha,'coverSha256':file_sha(cover),'listingFingerprint':pending['listingFingerprint'],'visualPass':True,'voiceConfirmed':True,'technicalPass':False})
  reviewed=command('attach-video','--manifest',manifest,'--video',video,'--cover',cover,'--review',review)['video'];assert reviewed['bindable']
  assert command('video-preflight','--manifest',manifest)['status']=='locally-reviewed'
  assert file_sha(home/reviewed['localPath'])==original_sha and file_sha(video)==original_sha
  bad=home/'truncated.mp4';bad.write_bytes(video.read_bytes()[:-1]);assert command('probe-video','--video',bad,code=2)['status']=='blocked'
  raw=bytearray(video.read_bytes());offset=0
  while offset<len(raw):
   size=int.from_bytes(raw[offset:offset+4],'big');kind=raw[offset+4:offset+8]
   if kind==b'mdat':raw[offset+8:offset+size]=b'\0'*(size-8);break
   offset+=size
  corrupt=home/'corrupt-packets.mp4';corrupt.write_bytes(raw);assert command('probe-video','--video',corrupt,code=2)['status']=='blocked'
  recoverable=home/'recoverable-corrupt.mp4';changed=bytearray((media/'silent.mp4').read_bytes());changed[933]^=1;recoverable.write_bytes(changed);assert command('probe-video','--video',recoverable,code=2)['status']=='blocked'
  wrong=home/'cover-bad.png';wrong.write_bytes(b'not-a-cover');old=manifest.read_bytes();assert command('attach-video','--manifest',manifest,'--video',video,'--cover',wrong,code=2)['status']=='blocked';assert manifest.read_bytes()==old
  # Mutated cached proof/bytes cannot be admitted before future native transfer.
  (home/reviewed['localPath']).write_bytes(b'changed-after-review');assert command('video-preflight','--manifest',manifest,code=2)['status']=='blocked'
  receipt=read_json(state/'runtime/video-runtime.json')
  decoder_python=state/receipt['python'];site=decoder_python.parent.parent/('Lib/site-packages' if sys.platform=='win32' else 'lib/python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'/site-packages');init=site/'av/__init__.py';original_init=init.read_bytes()
  init.write_bytes(original_init+b"\nfrom pathlib import Path\nPath('synthetic-unverified-import').write_text('must-not-run')\n")
  assert command('video-runtime-status')['status']=='not-prepared';assert command('video-runtime-prepare',code=2)['status']=='blocked';assert not (state/receipt['home']/'synthetic-unverified-import').exists()
  init.write_bytes(original_init);assert command('video-runtime-status')['status']=='ready'
  record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'realPublicDecoderInstall':True,'decoderVersion':receipt['packages'],'decoderSource':receipt['sources'],'silentAndAACFullDecode':clips,'framesPerVideo':30,'sourceBytesPreserved':True,'callerTechnicalFlagIgnored':True,'corruptPacketAndTruncatedMP4Rejected':True,'recoverableCodecCorruptionRejected':True,'modifiedInstalledDecoderRejectedBeforeImport':True,'badCoverAndChangedOriginalRejected':True,'installedRuntime':True,'realMerchantReads':0,'realMerchantWrites':0,'paidGenerationCalls':0,'visualReview':'synthetic-assertions-only-not-human-commercial-acceptance','nativeVideoUploadAndBinding':'not-implemented-in-this-smoke'}
  atomic_json(ROOT/'.agent-work/video-qa-audit/installed-video-smoke.json',record);print(json.dumps({k:v for k,v in record.items() if k not in ('decoderSource','silentAndAACFullDecode')}))
if __name__=='__main__':main()
