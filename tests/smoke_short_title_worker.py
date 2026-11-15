"""Fresh-HOME installed worker smoke. Synthetic business; actual owned loopback IPC."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,json,socket,threading,unittest
from pathlib import Path
from unittest.mock import patch
installed,source=map(Path,sys.argv[1:3]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_worker as core,short_title_worker_state as original,short_title_worker_service as service,short_title_worker_gate as gate,short_title_worker_broker as broker,cli
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (core,original,service,gate,broker,cli))
from tests import test_short_title_worker as fixture,test_short_title_browser as source_fixture,test_short_title_worker_loopback as ipc
from tests.short_title_import_fixtures import ImportFactory
# Use the real managed-install binding and the production default verifier.
def make(self,d,tick=None):
 c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d);binding=original.runtime_binding();j=original.create_job(d,p['planId'],c,binding,source_id=b.session_id);r=original.begin_run(d,j);native=ImportFactory(d)
 w=core.ShortTitleWorker(d,j['workerId'],r['runId'],client=c,source_factory=lambda:f,import_factory=lambda:native,clock=lambda:1000,headless=True)
 assert w.runtime_verifier()==binding
 return w,c,j,r,f,native
with patch.object(fixture.WorkerLifecycleTests,'make',make):
 suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_short_title_worker_loopback.WorkerLoopbackTests.test_actual_loopback_once_only_native_actions_on_browser_owner');out=unittest.TextTestRunner(verbosity=1).run(suite)
 if not out.wasSuccessful():raise SystemExit(1)
print(json.dumps({'status':'passed','installedModules':True,'defaultManagedInstallVerifier':True,'actualLoopbackIPC':True,'ownerThreadNativeActions':True,'nativeUploadCalls':1,'nativeCreateCalls':1,'duplicateExecuteNotReplayed':True,'realBrowser':False,'realMerchantCalls':0,'paidModels':0,'C3Complete':False,'goalComplete':False}))
'''
def main():
 archive=Path(sys.argv[1]);sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='merchant-worker-smoke-') as d:
  home=Path(d);env=clean_environment(home);target=home/'.codex/skills/heideng-ops-agent-merchant'
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],env=env,cwd=ROOT,capture_output=True,timeout=90)
  if out.returncode:raise RuntimeError('worker-smoke-install-failed')
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B','-c',CHILD,target,ROOT],env=env,cwd=ROOT,capture_output=True,timeout=120)
  if out.returncode:
   sys.stderr.write(out.stderr.decode('utf-8','replace'));return out.returncode
  receipt={'archiveSha256':sha,'freshHomeInstall':True,'result':json.loads(out.stdout),'goalComplete':False}
  atomic_json(ROOT/'.agent-work/short-title-worker/installed-smoke.json',receipt);print(json.dumps(receipt));return 0
if __name__=='__main__':raise SystemExit(main())
