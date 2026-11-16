"""Real owned Edge resources + worker exit + read-only cleanup controller; no OAuth."""
import json,socket,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from heideng_merchant.auth_browser_host import HostControllerBrowser
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.auth_lifecycle import process_identity
from heideng_merchant.auth_manager import AuthManager
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from tests.test_auth_flow import FakeClient
from tests.test_auth_manager import Client,Runtime

CONTROLLER=r"""import json,sys
from playwright.sync_api import sync_playwright
payload=json.load(sys.stdin);action=payload['action']
if action['kind']=='open_login':raise RuntimeError('synthetic startup interruption')
if action['kind']!='verify_cleanup':raise RuntimeError('only read-only inspection permitted')
driver=sync_playwright().start();browser=driver.chromium.connect_over_cdp(ENDPOINT)
session=browser.new_browser_cdp_session()
contexts=session.send('Target.getBrowserContexts')['browserContextIds']
targets=session.send('Target.getTargets')['targetInfos']
released=CONTEXT not in contexts and all(item['targetId']!=TARGET for item in targets)
print(json.dumps({'ok':True,'taskId':payload['jobId'],'inspectionId':action['id'],'actionIds':action['actionIds'],'owned':True,'inspectionVerified':True,'noLiveTaskResources':released}))
driver.stop()
"""

def main():
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
 with tempfile.TemporaryDirectory(prefix='auth-cleanup-smoke-') as d:
  state=Path(d);driver=sync_playwright().start();browser=driver.chromium.launch(channel='msedge',headless=True,args=['--remote-debugging-port='+str(port)])
  worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
  try:
   context=browser.new_context();page=context.new_page();session=context.new_cdp_session(page);info=session.send('Target.getTargetInfo')['targetInfo'];session.detach()
   controller=state/'fixture-cleanup-controller.py';controller.write_text('ENDPOINT='+repr('http://127.0.0.1:'+str(port))+'\nCONTEXT='+repr(info['browserContextId'])+'\nTARGET='+repr(info['targetId'])+'\n'+CONTROLLER,encoding='utf-8')
   command=[sys.executable,'-I',str(controller)];job='b'*24;profile='merchant-cleanup-a1'
   atomic_json(state/'tasks'/f'{job}.json',{'kind':'shop-auth','taskId':job,'profile':profile,'browserController':command,'browserProvider':'original-linker-host-controller'})
   host=HostControllerBrowser(state,job,'test-shop',command)
   flow=AuthFlow(state,job,profile,'test-shop',FakeClient(),host);result=flow.tick()
   assert result['status']=='failed' and result['cleanupIncomplete'] and not flow.client.calls
   proof=process_identity(worker.pid);assert proof['state']=='alive'
   receipt={'taskId':job,'workerPid':worker.pid,'startedAt':1}
   if proof.get('creationTime') is not None:receipt['processProof']={'pid':worker.pid,'creationTime':proof['creationTime']}
   atomic_json(state/'auth/launches'/f'{job}.json',receipt)
   atomic_json(state/'auth/handles'/f'{job}.json',{**receipt,'brokerStopped':True})
   def forbidden(*args,**options):raise AssertionError('cleanup cannot authorize or launch a worker')
   manager=AuthManager(state,client=Client(),runtime=Runtime(),starter=forbidden,request=lambda *a,**kw:None)
   try:manager.prove_cleanup(job);raise AssertionError('alive worker accepted')
   except SafetyError:pass
   worker.terminate();worker.wait(timeout=5)
   try:manager.prove_cleanup(job);raise AssertionError('live browser context accepted')
   except SafetyError:pass
   assert manager._record(job)['cleanupIncomplete']
   context.close();browser.new_browser_cdp_session().send('Browser.getVersion')
   cleaned=manager.prove_cleanup(job)
   assert cleaned['cleanupVerified'] and cleaned['safeToRestart'] and not cleaned['cleanupIncomplete'] and not cleaned['oauthReplayed']
   assert all('synthetic startup interruption' not in p.read_text(encoding='utf-8') for p in state.rglob('*.json'))
   print(json.dumps({'status':'passed','realWorkerAliveRefused':True,'realBrowserContextAliveRefused':True,'ownedContextReleasedThenVerified':True,'readOnlyControllerSubprocess':True,'originalTaskSafelyRestartable':True,'oauthReplayed':False,'realMerchantOAuth':'not-run','realCredentials':'none'}))
  finally:
   if worker.poll() is None:worker.terminate();worker.wait(timeout=5)
   browser.close();driver.stop()

if __name__=='__main__':main()
