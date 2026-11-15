"""Fresh installed native-health C3/worker integration, synthetic only."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,json,socket,unittest
from pathlib import Path
from unittest.mock import patch
installed,source=map(Path,sys.argv[1:3]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_health_sources as health,short_title_effect_state as state,short_title_verification as verify,products,short_title_worker_state as original,short_title_worker as core
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (health,state,verify,products,original,core))
from tests import test_short_title_worker as fixture,test_short_title_browser as source_fixture,test_short_title_worker_loopback as ipc
from tests.short_title_import_fixtures import ImportFactory
from heideng_merchant.short_title_contract import source_context
# Exact installed default runtime verifier. Browser and every business response remain fake.
def make(self,d,tick=None):
 c,s,p,f,b=source_fixture.ShortTitleBrowserTests().make(d);binding=original.runtime_binding();j=original.create_job(d,p['planId'],c,binding,source_id=b.session_id);r=original.begin_run(d,j);native=ImportFactory(d)
 _,rows=source_context(d,s.plan(p['planId'])['scope']['auditId']);parents={row['skuId']:row['productId'] for row in rows}
 for row in c.health:
  if str(row['skuId']) in parents:row['productId']=int(parents[str(row['skuId'])]);row['healthScoreId']=int(row['skuId'])
  row['healthScore']=99
 old=c.invoke
 def invoke(profile,url,**kwargs):
  if getattr(native.driver.context,'page',None) is not None and native.driver.context.page.creates:
   for item in c.health:item['improvementList']=[]
  if url==health.DETAIL_URL:
   sku=str(kwargs['params']['healthInfoId']);return {'code':200,'data':{'skuId':int(sku),'productId':int(parents[sku]),'healthScoreId':int(sku),'healthScore':99,'improvementList':[]}}
  return old(profile,url,**kwargs)
 c.invoke=invoke
 w=core.ShortTitleWorker(d,j['workerId'],r['runId'],client=c,source_factory=lambda:f,import_factory=lambda:native,clock=lambda:1000,headless=True)
 assert w.runtime_verifier()==binding
 return w,c,j,r,f,native
with patch.object(fixture.WorkerLifecycleTests,'make',make):
 suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_short_title_worker_loopback.WorkerLoopbackTests.test_actual_loopback_once_only_native_actions_on_browser_owner');out=unittest.TextTestRunner(verbosity=1).run(suite)
 if not out.wasSuccessful():raise SystemExit(1)
# Separate state/projection tests exercise actual new healthy sources and v1/v2 retention.
suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_short_title_health_effects.NativeHealthEffectsTests.test_dual_list_and_all_five_sibling_details_native_health_not_formal_terminal','tests.test_short_title_health_effects.NativeHealthEffectsTests.test_v1_history_kept_but_new_v2_proof_cannot_be_dropped_on_later_observation'])
# No external network is admitted in the two native source tests.
connect=socket.socket.connect
socket.socket.connect=lambda self,address: connect(self,address) if address[0]=='127.0.0.1' else (_ for _ in ()).throw(AssertionError('external socket forbidden'))
result=unittest.TextTestRunner(verbosity=1).run(suite)
if not result.wasSuccessful():raise SystemExit(1)
print(json.dumps({'status':'passed','installedModules':True,'defaultManagedVerifier':True,'realOwnedLoopback':True,'nativeHealthSourceReads':'synthetic-only','methods':3,'v1Preserved':True,'v2DowngradeRefused':True,'allFiveOriginalHealthDetails':True,'formalAuditVerified':False,'portalVerified':False,'healthVerified':False,'imported':False,'retryAuthorized':False,'realMerchantCalls':0,'paidModels':0,'goalComplete':False}))
'''
def main():
 archive=Path(sys.argv[1]);sha=file_sha(archive)
 with tempfile.TemporaryDirectory(prefix='hd-health-') as d:
  home=Path(d);env=clean_environment(home);target=home/'.codex/skills/heideng-ops-agent-merchant'
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha],env=env,cwd=ROOT,capture_output=True,timeout=90)
  if out.returncode:raise RuntimeError('native-health-install-smoke-failed')
  out=subprocess.run([sys.executable,'-I','-X','utf8','-B','-c',CHILD,target,ROOT],env=env,cwd=ROOT,capture_output=True,timeout=180)
  if out.returncode:
   sys.stderr.write(out.stderr.decode('utf-8','replace'));return out.returncode
  receipt={'archiveSha256':sha,'freshHomeInstall':True,'result':json.loads(out.stdout),'goalComplete':False}
  atomic_json(ROOT/'.agent-work/short-title-c3-formal/installed-smoke.json',receipt);print(json.dumps(receipt));return 0
if __name__=='__main__':raise SystemExit(main())
