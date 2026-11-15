"""New-HOME C1/C2 API smoke using only synthetic browser/backend/DNS/bytes."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heideng_merchant.safety import clean_environment, file_sha, atomic_json

CHILD = r'''import sys,socket,json
from pathlib import Path
from unittest.mock import patch
installed, source, home = map(Path, sys.argv[1:4])
sys.path[:0] = [str(installed), str(source)]
from heideng_merchant import short_title_results, short_title_result_transport, short_title_result_browser, short_title_result_state, short_title_imports, short_title_import_browser, cli, distribution
from tests import test_short_title_imports as original
from tests.short_title_result_fixtures import TransportFactory
from tests.test_short_title_rpc_methods import QualifiedFactory
modules = (short_title_results, short_title_result_transport, short_title_result_browser, short_title_result_state, short_title_imports, short_title_import_browser, cli)
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in modules)
socket.socket.connect = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
socket.create_connection = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
socket.getaddrinfo = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('synthetic-only-network-blocked'))
state = home / '.heideng-merchant'
client, _, _, _, manager, root = original.ShortTitleImportsTests().make(state)
manager.approve(root['importId'], root['fingerprint'], confirmed=True)
factory = QualifiedFactory(state)
wire = TransportFactory()
transport = short_title_result_transport.ResultTransport(resolver=wire.resolver, connection_factory=wire, clock=lambda:1000)
browser = short_title_import_browser.ShortTitleImportBrowser(manager, root['importId'], factory=lambda:factory, headless=True, result_transport=transport)
browser.open()
page = factory.driver.context.page
try:
 page.fault = 'create-timeout'
 assert manager.execute(root['importId'], browser)['status'] == 'unknown'
 assert manager.recover(root['importId'], browser)['submittedBatchCount'] == 1
 raw = page.complete()
 wire.response.body = raw
 wire.response.headers[1] = ('Content-Length', str(len(raw)))
 result = manager.collect_results(root['importId'], browser)
 assert result['currentTaskAnchorMatched'] and result['currentResultSourceVerified']
 assert result['rowResultsVerified'] and not result['actualTitlesVerified'] and not result['healthVerified'] and not result['imported'] and not result['retryAuthorized']
 with patch('heideng_merchant.cli.OfficialClient',return_value=client),patch('heideng_merchant.cli.ShortTitleImports',return_value=manager):
  rows = cli.run(cli.parser().parse_args(['--home',str(home),'short-title-import-rows','--import-id',root['importId'],'--view','results','--page-size','1']))
  assert rows['total'] == 1 and rows['items'][0]['outcome'] == 'success' and rows['items'][0]['proposedShortTitle'] and not rows['items'][0]['actualTitleVerified']
 page.result_dom = ['7000000001 处理中 成功：0 失败：0']
 pending = manager.collect_results(root['importId'], browser)
 assert not pending['rowResultsVerified'] and pending['currentTaskAnchorMatched'] and not pending['currentResultSourceVerified']
 assert len(wire.requests) == 1
 raw = page.complete(outcome='失败',reason='标题不合规则')
 wire.response.body = raw
 wire.response.headers[1] = ('Content-Length',str(len(raw)))
 assert manager.collect_results(root['importId'], browser)['rowResultsVerified']
 assert manager.rows(root['importId'],view='results')['items'][0]['outcome'] == 'failed'
 manager.execute(root['importId'], browser)
 assert (page.uploads,page.creates) == (1,1)
 assert len(wire.requests) == 2
finally:
 browser.close()
assert distribution.busy(state) and not client.posts
from heideng_merchant.safety import SafetyError
try:
 manager.plans.ops._assert_resolved(manager.record(root['importId'])['scope']['shop'])
except SafetyError:
 pass
else:
 raise AssertionError('same-shop pending title must quarantine other writes')
for file in state.rglob('*.json'):
 assert 'synthetic-only-private' not in file.read_text(encoding='utf-8-sig')
print(json.dumps({'status':'passed','installedModulePaths':True,'nativeUploadCalls':1,'nativeCreateCalls':1,'originalResultGets':2,'lostCreateAckRecoveredWithoutReplay':True,'fullOriginalRowResult':True,'pendingNeverRetransmits':True,'failureNotRetryAuthorized':True,'updateGateStillBusy':True,'sameShopOtherWritesQuarantined':True,'qualifiedNativeMethods':True,'actualBrowserLaunched':False,'realMerchantCalls':0,'paidModels':0,'actualTitlesVerified':False,'healthVerified':False,'imported':False,'CLIWorkerIntegrated':True,'NativeWorkerExercised':False}))
'''

def main():
 archive = ROOT / 'dist/heideng-ops-agent-merchant-0.1.0.zip'
 sha = file_sha(archive)
 base = ROOT / '.agent-work/short-title-result-audit'
 base.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ht-result-') as directory:
  home = Path(directory)
  env = clean_environment(home)
  child = home / 'installed.py'
  child.write_text(CHILD,encoding='utf-8')
  stages = [('install',[sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]),('chain',[sys.executable,'-I','-X','utf8','-B',child,home/'.codex/skills/heideng-ops-agent-merchant',ROOT,home])]
  for stage,args in stages:
   run = subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=300)
   (base/(stage+'.log')).write_bytes(run.stdout+run.stderr)
   if run.returncode:
    print(json.dumps({'installedC1C2':'failed','stage':stage,'exitCode':run.returncode}))
    return 1
   if stage == 'chain':
    result = json.loads(run.stdout)
 assert file_sha(archive) == sha
 record = {'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'result':result,'merchantAutomaticImportComplete':False,'goalComplete':False}
 atomic_json(base/'installed-short-title-results-smoke.json',record)
 print(json.dumps(record))
 return 0

if __name__ == '__main__':
 raise SystemExit(main())
