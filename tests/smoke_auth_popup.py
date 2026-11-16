"""Real SDK, synthetic multi-tab login; every browser request is intercepted."""
import importlib.metadata
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from heideng_merchant.auth_browser import PlaywrightBrowser
from heideng_merchant.auth_flow import AuthFlow
from heideng_merchant.safety import atomic_json
from tests.test_auth_flow import FakeClient
import tempfile

class Launcher:
 def __init__(self):
  self.controller=sync_playwright().start();self.chromium=self;self.blocked=0;self.fulfilled=0
 def launch(self,**kwargs):
  browser=self.controller.chromium.launch(**kwargs);self.channel=kwargs.get('channel');original=browser.new_context
  def context(**options):
   ctx=original(**options)
   def intercept(route):
    url=urlsplit(route.request.url)
    if url.hostname=='jingmai.jd.com' and url.path=='/':
     route.fulfill(content_type='text/html',body="""<html><body><button id="login" onclick="window.open('/jdm/home','_blank')">Synthetic login</button></body></html>""")
    elif url.hostname=='jingmai.jd.com' and url.path=='/jdm/home':
     route.fulfill(content_type='text/html',body='<html><body>Test workbench<script>fetch("/identity");</script></body></html>')
    elif url.hostname=='jingmai.jd.com' and url.path=='/identity':
     route.fulfill(content_type='application/json',body=json.dumps({'data':{'shopName':'smoke-test-shop-full','venderId':'1','shopType':'0','token':'synthetic-only'}}))
    elif url.hostname=='open-oauth.jd.com' and url.path.startswith('/oauth2/'):
     route.fulfill(content_type='text/html',body='<html><title>same-context-popup</title></html>')
    else:
     self.blocked+=1;route.abort();return
    self.fulfilled+=1
   ctx.route('**/*',intercept);return ctx
  browser.new_context=context;return browser
 def stop(self):self.controller.stop()
class Factory:
 def start(self):return Launcher()

browser=PlaywrightBrowser('alias',factory=Factory,headless=True)
with tempfile.TemporaryDirectory() as d:
 client=FakeClient();flow=AuthFlow(Path(d),'a'*24,'merchant-popup-a1','alias',client,browser)
 try:
  flow.tick();landing=browser.page;context=browser.context
  with context.expect_page() as opened:landing.locator('#login').click()
  popup=opened.value;popup.wait_for_load_state('domcontentloaded')
  for _ in range(40):
   flow.tick()
   if flow.data['stage']=='waiting_shop_confirmation':break
  assert flow.data['stage']=='waiting_shop_confirmation'
  assert len(context.pages)==2 and len(client.calls)==0
  candidate=flow.status()['identityCandidates'][0]
  assert candidate['shopName']=='smoke-test-shop-full' and candidate['venderId']=='1'
  assert candidate['fingerprint'] in browser.identity_pages and browser.identity_pages[candidate['fingerprint']] is popup
  landing.close()
  flow.confirm_shop(candidate['fingerprint'],candidate['shopName'],candidate['venderId'])
  flow.tick()
  assert len([c for c in client.calls if c[0]=='login'])==1
  for _ in range(40):
   flow.tick()
   if flow.data['stage']=='waiting_oauth':break
  assert flow.data['stage']=='waiting_oauth'
  assert browser.context is context and browser.page is popup and popup.title()=='same-context-popup'
  assert len(context.pages)==1 and not popup.is_closed()
  assert 'synthetic-only' not in json.dumps(browser.public_observation())
  assert 'fake-private' not in json.dumps(flow.status())
  assert browser.controller.blocked==0
  record={'status':'passed','systemBrowser':browser.controller.channel,'playwrightVersion':importlib.metadata.version('playwright'),'headless':True,'allRequestsIntercepted':True,'interceptedRequestCount':browser.controller.fulfilled,'popupIdentityObserved':True,'aliasConfirmedInOriginalTask':True,'closedLandingTabRecovered':True,'oauthOnIdentityPopup':True,'sameContext':True,'loginProcessCount':1,'sensitiveStateNotPublished':True,'realMerchantOAuth':'not-run','realCredentials':'none'}
 finally:
  flow.cancel()
 record['ownedBrowserClosed']=browser.browser is None
atomic_json(Path('.agent-work/auth-smoke/popup-evidence.json'),record)
print(json.dumps(record))
