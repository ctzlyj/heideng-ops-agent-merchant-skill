"""New-HOME default-managed repair worker acceptance; all business responses synthetic."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,json,socket,unittest
from pathlib import Path
from unittest.mock import patch
installed,source=map(Path,sys.argv[1:3]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_repair as repair,short_title_worker_state as original,short_title_worker as core,short_title_worker_broker,short_title_worker_service,cli,short_title_imports
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (repair,original,core,short_title_worker_broker,short_title_worker_service,cli,short_title_imports))
from tests import test_short_title_worker as fixture,test_short_title_browser as source_fixture
from tests.short_title_import_fixtures import ImportFactory
connect=socket.socket.connect
socket.socket.connect=lambda self,address: connect(self,address) if address[0]=='127.0.0.1' else (_ for _ in ()).throw(AssertionError('external socket forbidden'))
def make(self,d,tick=None):
 c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d);binding=original.runtime_binding();j=original.create_job(d,p['planId'],c,binding,source_id=b.session_id);run=original.begin_run(d,j);native=ImportFactory(d)
 w=core.ShortTitleWorker(d,j['workerId'],run['runId'],client=c,source_factory=lambda:f,import_factory=lambda:native,clock=lambda:1000,headless=True)
 assert w.runtime_verifier()==binding
 return w,c,j,run,f,native
with patch.object(fixture.WorkerLifecycleTests,'make',make):
 suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_short_title_repair_worker.RepairCommandTests.test_actual_loopback_prepares_and_approves_exact_child_on_original_owner_no_second_native_attempt');out=unittest.TextTestRunner(verbosity=1).run(suite)
 if not out.wasSuccessful():raise SystemExit(1)
suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_short_title_failure_repair.FailureRepairTests.test_prepare_is_fresh_failed_only_preserves_all_originals_and_parent_approval_not_inherited','tests.test_short_title_failure_repair.FailureRepairTests.test_same_business_content_refreshes_current_reads_but_never_creates_second_child_intent']);out=unittest.TextTestRunner(verbosity=1).run(suite)
if not out.wasSuccessful():raise SystemExit(1)
args=cli.parser().parse_args(['short-title-repair-rows','--import-id','a'*24,'--repair-plan-id','b'*24,'--view','siblings']);assert args.view=='siblings'
print(json.dumps({'status':'passed','methods':3,'installedModules':True,'defaultManagedVerifier':True,'realOwnedLoopback':True,'parentNativeAttempts':1,'nativeChildAttempts':0,'freshFailureNeedRead':True,'exactNewApprovalRecorded':True,'allFiveOriginalSiblingsPreserved':True,'sameContentChildIntentDeduplicated':True,'prefixDeletionRefused':True,'nativeChildImportComplete':False,'retryAuthorized':False,'formalAuditVerified':False,'portalVerified':False,'imported':False,'realMerchantCalls':0,'paidModels':0,'goalComplete':False}))
'''
def main():
 archive=Path(sys.argv[1]).absolute();sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='hd-repair-') as d:
  home=Path(d);env=clean_environment(home);target=home/'.codex/skills/heideng-ops-agent-merchant'
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],env=env,cwd=ROOT,capture_output=True,timeout=90)
  if out.returncode:raise RuntimeError('repair-install-smoke-failed')
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B','-c',CHILD,target,ROOT],env=env,cwd=ROOT,capture_output=True,timeout=240)
  if out.returncode:sys.stderr.write(out.stderr.decode('utf-8','replace'));return out.returncode
  receipt={'archiveSha256':sha,'freshHomeInstall':True,'result':json.loads(out.stdout),'goalComplete':False};atomic_json(ROOT/'.agent-work/short-title-failure-repair/installed-smoke.json',receipt);print(json.dumps(receipt));return 0
if __name__=='__main__':raise SystemExit(main())
