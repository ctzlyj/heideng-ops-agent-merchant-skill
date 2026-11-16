"""Real browser/controller subprocess, intercepted pages, synthetic official client."""
import json,socket,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from heideng_merchant.auth_browser_host import HostControllerBrowser
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.safety import read_json
from tests.test_auth_flow import FakeClient

CONTROLLER = r'''import json,sys
from playwright.sync_api import sync_playwright
request=json.load(sys.stdin);action=request['action'];driver=sync_playwright().start()
browser=driver.chromium.connect_over_cdp(ENDPOINT)
page=None;context_id=None
for context in browser.contexts:
 for candidate in context.pages:
  session=context.new_cdp_session(candidate);info=session.send('Target.getTargetInfo')['targetInfo'];session.detach()
  if info['targetId']==TARGET:
   page=candidate;context_id=info.get('browserContextId');break
if page is None or not context_id:raise RuntimeError('owned fixture page missing')
context=page.context
html='<html><title>task-owned-workbench</title><div id="shop" data-vender="1" data-id="9">actual-shop</div></html>'
def route(handler):
 url=handler.request.url
 if url.startswith('https://new-workbench.example.invalid/'):
  handler.fulfill(content_type='text/html',body=html)
 elif url.startswith('https://open-oauth.jd.com/oauth2/'):
  handler.fulfill(content_type='text/html',body='<html><title>fixture-oauth</title></html>')
 else:handler.abort()
context.route('**/*',route)
result={'contextId':context_id,'owned':True,'isolated':True,'ok':True}
if action['kind']=='open_login':page.goto('https://new-workbench.example.invalid/jdm/home',wait_until='domcontentloaded')
elif action['kind']=='observe':
 result.update(page.evaluate("() => { const s=document.querySelector('#shop'); return {loggedIn:!!s,identity:s?{shopName:s.textContent,venderId:s.dataset.vender,shopId:s.dataset.id}:{},challenge:''}; }"))
elif action['kind']=='open_oauth':page.goto(action['url'],wait_until='domcontentloaded')
elif action['kind']=='close':page.close()
else:raise RuntimeError('unknown fixture action')
print(json.dumps(result))
driver.stop()
'''

class Client(FakeClient):
 def identity(self,profile):return {'venderId':'1','shopId':'9','shopName':'actual-shop','shopType':'POP'}

def main():
 listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()
 with tempfile.TemporaryDirectory(prefix='host-auth-smoke-') as d:
  state=Path(d);driver=sync_playwright().start();browser=driver.chromium.launch(channel='msedge',headless=True,args=['--remote-debugging-port='+str(port)])
  try:
   context=browser.new_context();page=context.new_page();cdp=context.new_cdp_session(page);info=cdp.send('Target.getTargetInfo')['targetInfo'];cdp.detach()
   assert info.get('browserContextId')
   script=state/'fixture-controller.py';script.write_text('ENDPOINT='+repr('http://127.0.0.1:'+str(port))+'\nTARGET='+repr(info['targetId'])+'\n'+CONTROLLER,encoding='utf-8')
   host=HostControllerBrowser(state,'a'*24,'alias',[sys.executable,'-I',str(script)],observe_interval=30)
   client=Client();flow=AuthFlow(state,'a'*24,'merchant-local-a1','alias',client,host)
   flow.tick();flow.tick();assert flow.data['stage']=='waiting_shop_confirmation'
   choice=flow.status()['identityCandidates'][0];flow.confirm_shop(choice['fingerprint'],'actual-shop','1');flow.tick()
   for _ in range(20):
    flow.tick()
    if flow.data['stage']=='waiting_oauth':break
    time.sleep(.05)
   assert flow.data['stage']=='waiting_oauth' and page.title()=='fixture-oauth'
   current=context.new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']
   assert current['browserContextId']==info['browserContextId'] and current['targetId']==info['targetId']
   client.process.returncode=0
   for _ in range(20):
    flow.tick()
    if flow.data['status']=='completed':break
    time.sleep(.05)
   browser.new_browser_cdp_session().send('Browser.getVersion')
   assert flow.data['ready'] and page.is_closed() and len(client.calls)==2, (flow.data['status'],flow.data['stage'],page.is_closed(),len(client.calls),flow.data.get('reason'))
   for path in state.rglob('*.json'):
    assert 'fake-private' not in path.read_text(encoding='utf-8')
   record={'status':'passed','systemBrowser':'msedge','realControllerSubprocess':True,'allPageRequestsIntercepted':True,'nonWhitelistedWorkbenchHandledByHost':True,'samePhysicalContext':True,'samePhysicalPage':True,'aliasConfirmation':True,'syntheticOfficialReceiptVerified':True,'ownedPageClosed':True,'oauthUrlNotPersisted':True,'realMerchantOAuth':'not-run','realCredentials':'none'}
  finally:browser.close();driver.stop()
 print(json.dumps(record))
if __name__=='__main__':main()
