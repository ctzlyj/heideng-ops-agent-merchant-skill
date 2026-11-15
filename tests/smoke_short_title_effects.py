"""Installed original effects smoke: synthetic sources only, no real browser/API."""
import json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,socket,json
from pathlib import Path
from unittest.mock import patch
installed,source,home=map(Path,sys.argv[1:4]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_verification,short_title_effect_state,short_title_imports,short_title_import_browser,short_title_result_state,short_title_shop_gate,cli,distribution
modules=(short_title_verification,short_title_effect_state,short_title_imports,short_title_import_browser,short_title_result_state,short_title_shop_gate,cli)
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in modules)
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
socket.getaddrinfo=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
from tests import test_short_title_effect_sources as fixture
state=home/'.heideng-merchant';c,m,r,b,p,calls,title=fixture.OwnedOriginalEffectReadTests().setup(state)
try:
 first=m.collect_effects(r['importId'],b)
 assert first['C3ReceiptPersisted'] and first['actualTitlesVerified'] and first['currentEffectSourceVerified']
 assert len(first['rows'])==5 and first['rows'][0]['actualShortTitle']==title
 assert not first['formalAuditVerified'] and not first['healthVerified'] and not first['portalVerified'] and not first['imported'] and not first['retryAuthorized']
 with patch('heideng_merchant.cli.OfficialClient',return_value=c),patch('heideng_merchant.cli.ShortTitleImports',return_value=m):
  before=len(calls)
  rows=cli.run(cli.parser().parse_args(['--home',str(home),'short-title-import-rows','--import-id',r['importId'],'--view','effects','--page-size','1']))
  assert len(calls)==before and rows['total']==5 and rows['items'][0]['actualTitleVerified']
 original=state/'short-title-effect-observations'/r['importId']/'000001.json';raw=original.read_bytes()
 receipt=state/'short-title-effect-receipts'/r['importId']/'000001.json';receipt.unlink()
 restored=m.collect_effects(r['importId'],b)
 assert restored['effectObservationSequence']==2 and original.read_bytes()==raw and receipt.is_file()
 p.result_dom=['7000000001 处理中 成功：0 失败：0'];m.collect_results(r['importId'],b)
 pending=m.collect_effects(r['importId'],b)
 assert pending['rows'][0]['processingOutcome']=='unknown' and not pending['actualTitlesVerified'] and not pending['retryAuthorized']
 m.execute(r['importId'],b)
 assert (p.uploads,p.creates)==(1,1) and not c.posts
 status=m.status(r['importId'])
 assert status['effectEvidenceHistorical'] and not status['currentEffectSourceVerified'] and not status['imported']
 assert distribution.busy(state)
 for file in state.rglob('*.json'):
  text=file.read_text(encoding='utf-8-sig');assert 'synthetic-only-private' not in text and 'SYNTHETIC_ONLY_DO_NOT_PERSIST' not in text
 result={'status':'passed','installedModulePaths':True,'nativeUploadCalls':p.uploads,'nativeCreateCalls':p.creates,'originalSiblingRows':5,'originalTargetRows':1,'oldObservationRetained':True,'missingReceiptRecovered':True,'CLIHistoricalRows':True,'newC2PrefixPreservesHistory':True,'pendingNeverRetransmits':True,'actualTitleNativeFieldRead':True,'formalAuditVerified':False,'healthVerified':False,'portalVerified':False,'imported':False,'retryAuthorized':False,'CLIWorkerIntegrated':False,'actualBrowserLaunched':False,'realMerchantCalls':0,'paidModels':0,'goalComplete':False}
finally:b.close()
print(json.dumps(result))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='merchant-effects-smoke-') as directory:
  home=Path(directory);env=clean_environment(home)
  installed=home/'.codex/skills/heideng-ops-agent-merchant'
  install=subprocess.run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],cwd=ROOT,env=env,capture_output=True,timeout=60)
  if install.returncode:raise RuntimeError('effects-smoke-offline-install-failed')
  child=subprocess.run([sys.executable,'-I','-X','utf8','-B','-c',CHILD,installed,ROOT,home],cwd=ROOT,env=env,capture_output=True,timeout=120)
  if child.returncode:
   sys.stderr.write(child.stderr.decode('utf-8','replace'));return child.returncode
  result=json.loads(child.stdout)
  receipt={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'result':result,'C3Complete':False,'merchantAutomaticImportComplete':False,'goalComplete':False}
  atomic_json(ROOT/'.agent-work/short-title-c3/installed-effects-smoke.json',receipt)
  print(json.dumps(receipt));return 0
if __name__=='__main__':raise SystemExit(main())
