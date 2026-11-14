import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from playwright.sync_api import sync_playwright
from heideng_merchant.auth_browser import PlaywrightBrowser
from heideng_merchant.safety import atomic_json

class Launcher:
 def __init__(self):self.controller=sync_playwright().start();self.chromium=self;self.blocked=0
 def launch(self,**kwargs):
  browser=self.controller.chromium.launch(**kwargs);self.channel=kwargs.get('channel');original=browser.new_context
  def context(**options):
   ctx=original(**options)
   def intercept(route):
    from urllib.parse import urlsplit
    url=urlsplit(route.request.url)
    if url.hostname=='jingmai.jd.com' and url.path=='/':
     route.fulfill(content_type='text/html',body='<html><body>Test login<script>fetch("/identity");</script></body></html>')
    elif url.hostname=='jingmai.jd.com' and url.path=='/identity':
     route.fulfill(content_type='application/json',body=json.dumps({'data':{'shopName':'smoke-test-shop','venderId':'1','token':'synthetic-only'}}))
    elif url.hostname=='open-oauth.jd.com':
     route.fulfill(content_type='text/html',body='<html><title>same-context</title></html>')
    else:self.blocked+=1;route.abort()
   ctx.route('**/*',intercept);return ctx
  browser.new_context=context;return browser
 def stop(self):self.controller.stop()
class Factory:
 def start(self):return Launcher()

b=PlaywrightBrowser('smoke-test-shop','1',factory=Factory,headless=True)
try:
 b.open_jingmai()
 for _ in range(20):
  b.poll()
  if b.proof():break
 assert b.proof()['venderId']=='1'
 ctx=b.context
 ctx.add_cookies([{'name':'synthetic_test','value':'not-a-real-credential','domain':'open-oauth.jd.com','path':'/','secure':True}])
 b.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=synthetic-only')
 assert b.context is ctx and len(ctx.pages)==1
 assert b.page.evaluate('document.cookie')=='synthetic_test=not-a-real-credential'
 assert 'synthetic-only' not in json.dumps(b.public_observation())
 assert b.controller.blocked==0
 record={'status':'passed','systemBrowser':b.controller.channel,'headless':True,'allRequestsIntercepted':True,'sameContext':True,'responseIdentityProof':True,'oauthStateNotPublished':True,'realMerchantOAuth':'not-run','realCredentials':'none'}
finally:b.close()
record['ownedBrowserClosed']=b.browser is None
atomic_json(Path('.agent-work/auth-smoke/browser-evidence.json'),record)
print(json.dumps(record))
