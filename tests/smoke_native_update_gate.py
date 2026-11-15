"""Fresh merchant installation, actual version switches, synthetic business only."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import json,sys,uuid,socket
from pathlib import Path
from unittest.mock import patch
installed,source,home,archive,mode=map(Path,sys.argv[1:6])
sys.path[:0]=[str(installed),str(source)]
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
from heideng_merchant import distribution,video_delivery,update_gate,cli,VERSION
from heideng_merchant.safety import SafetyError,read_json,atomic_json,file_sha
from tests.test_video_delivery import VideoDeliveryTests
from tests.video_delivery_fixtures import Client
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (distribution,video_delivery,update_gate,cli))
state=home/'.heideng-merchant';manifest=home/'manifest.json';info=home/'smoke-info.json'
def blocked(fn):
 try:fn()
 except SafetyError:return
 raise AssertionError('required update/write refusal missing')
if str(mode)=='updated':
 assert VERSION=='0.2.0';prior=read_json(info);m=Path(prior['manifest']);c=Client(read_json(m)['video']['technicalEvidence']['bytes']);s=video_delivery.VideoDelivery(state,c,transfer=c.transfer)
 assert distribution.busy(state)
 cancelled=cli.run(cli.parser().parse_args(['--home',str(home),'video-delivery-cancel','--session-id',prior['sessionId'],'--fingerprint',prior['fingerprint'],'--confirm']));assert cancelled['status']=='cancelled'
 with patch('heideng_merchant.video_delivery.preflight_video',side_effect=VideoDeliveryTests().probe):
  p=s.prepare('merchant-test',m,'video-owned');assert p['runtimeVersion']=='0.2.0' and p['sessionId']!=prior['sessionId'];s.approve(p['sessionId'],p['fingerprint'],confirmed=True);r=s.execute(p['sessionId'])
 assert r['status']=='ready' and len(c.allocations)==len(c.transfers)==len(c.saves)==1
 assert not distribution.busy(state);assert distribution.rollback(installed,state)['version']=='0.1.0';assert distribution.verify_install(installed)['valid']
 print(json.dumps({'status':'passed','newVersionReplanned':True,'knownCompletedRollbackAllowed':True}));raise SystemExit(0)
assert VERSION=='0.1.0'
fixture=home/'synthetic-upgrade-source';fixture.mkdir();_,raw=distribution.validate_archive(archive)
for name,content in raw.items():
 if name==distribution.MANIFEST:continue
 dest=fixture/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
(fixture/'VERSION').write_text('0.2.0');init=fixture/'heideng_merchant/__init__.py';init.write_text(init.read_text().replace('"0.1.0"','"0.2.0"'));registry=read_json(fixture/'registry.json');registry['version']='0.2.0';atomic_json(fixture/'registry.json',registry)
upgrade=distribution.build_bundle(fixture,home/'synthetic-0.2.0.zip','0.2.0');sha=file_sha(upgrade)
if str(mode)=='unknown':
 assert distribution.install_archive(upgrade,installed,state,expected_sha=sha)['version']=='0.2.0';assert distribution.rollback(installed,state)['version']=='0.1.0'
helper=VideoDeliveryTests();root,m,c,old=helper.make(home);s=video_delivery.VideoDelivery(state,c,transfer=c.transfer);s.ops.connect('merchant-test','synthetic-store','1')
with patch('heideng_merchant.video_delivery.preflight_video',side_effect=helper.probe):p=s.prepare('merchant-test',m,'video-owned')
if str(mode)=='unknown':
 s.approve(p['sessionId'],p['fingerprint'],confirmed=True);c.fault='transfer-timeout'
 with patch('heideng_merchant.video_delivery.preflight_video',side_effect=helper.probe):r=s.execute(p['sessionId'])
 assert r['status']=='unknown' and distribution.busy(state)
 stage=installed.parent/('.heideng-ops-agent-merchant.stage-'+uuid.uuid4().hex);backup=installed.parent/('.heideng-ops-agent-merchant.backup-'+uuid.uuid4().hex);stage.mkdir();(stage/'marker').write_text('preserve recovery')
 atomic_json(state/'install-journal.json',{'target':str(installed),'stage':str(stage),'backup':str(backup)});journal=(state/'install-journal.json').read_bytes();before=distribution.verify_install(installed)
 blocked(lambda:distribution.install_archive(upgrade,installed,state,expected_sha=sha));blocked(lambda:distribution.rollback(installed,state));blocked(lambda:s.cancel(p['sessionId'],p['fingerprint'],confirmed=True))
 assert (stage/'marker').read_text()=='preserve recovery' and (state/'install-journal.json').read_bytes()==journal and distribution.verify_install(installed)==before
 assert len(c.allocations)==len(c.transfers)==1 and not c.saves
 print(json.dumps({'status':'passed','unknownBlockedInstallRollbackRecoveryCancel':True,'recoveryEvidenceUnchanged':True}));raise SystemExit(0)
args=['--home',str(home),'video-delivery-cancel','--session-id',p['sessionId'],'--fingerprint',p['fingerprint']]
blocked(lambda:cli.run(cli.parser().parse_args(args)));assert cli.run(cli.parser().parse_args([*args,'--confirm']))['status']=='cancelled'
with patch('heideng_merchant.video_delivery.preflight_video',side_effect=helper.probe):stale=s.prepare('merchant-test',m,'video-owned')
assert stale['sessionId']!=p['sessionId'];s.approve(stale['sessionId'],stale['fingerprint'],confirmed=True);assert not distribution.busy(state)
assert distribution.install_archive(upgrade,installed,state,expected_sha=sha)['version']=='0.2.0'
blocked(lambda:s.execute(stale['sessionId']));assert not c.allocations and not c.transfers and not c.saves
atomic_json(info,{**stale,'manifest':str(m)});print(json.dumps({'status':'passed','confirmedLocalCancel':True,'upgradeAllowedBeforeAttempt':True,'staleRuntimeBlockedDispatch':True}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);out=ROOT/'.agent-work/native-update-gate-audit';out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='hu-') as d:
  root=Path(d);child=root/'smoke.py';child.write_text(CHILD,encoding='utf-8');results={}
  for mode in ('unknown','cancel'):
   home=root/mode;home.mkdir();env=clean_environment(home);installed=home/'.codex/skills/heideng-ops-agent-merchant'
   def run(args,label):
    r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180);(out/(label+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'installed update gate smoke failed: '+label;return json.loads(r.stdout)
   run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],mode+'-install')
   results[mode]=run([sys.executable,'-I','-X','utf8','-B',child,installed,ROOT,home,archive,mode],mode+'-gate')
   if mode=='cancel':results['updated']=run([sys.executable,'-I','-X','utf8','-B',child,installed,ROOT,home,archive,'updated'],'new-runtime-replan')
  assert file_sha(archive)==sha
  record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'installedModulePathsAsserted':True,'actualLocalUpdateRollbackRecovery':True,'syntheticUpgradeFixtureOnly':'0.2.0','mockedTechnicalPreflight':True,'realMerchantAuthorization':'not-run','realMerchantApi':'not-run','paidModelCalls':0,'results':results};atomic_json(out/'installed-native-update-gate-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
