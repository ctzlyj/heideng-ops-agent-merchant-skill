import json,unittest
from pathlib import Path
from heideng_merchant.auth_browser import PlaywrightBrowser

class Page:
 def __init__(self):self.urls=[];self.handlers={};self.closed=False
 def on(self,event,handler):self.handlers[event]=handler
 def goto(self,url,**kw):self.urls.append(url)
 def wait_for_timeout(self,n):pass
 def is_closed(self):return self.closed
 def locator(self,selector):return self
 def inner_text(self,**kw):return '请扫码登录测试店'
class Context:
 def __init__(self):self.page=Page();self.closed=False
 def new_page(self):return self.page
 def close(self):self.closed=True
class Browser:
 def __init__(self):self.contexts=[];self.closed=False
 def new_context(self,**kw):c=Context();self.contexts.append(c);return c
 def close(self):self.closed=True
class Driver:
 def __init__(self):self.chromium=self;self.browser=Browser();self.stopped=False
 def launch(self,**kw):return self.browser
 def stop(self):self.stopped=True
class Factory:
 def __init__(self):self.driver=Driver()
 def start(self):return self.driver
class Response:
 url='https://jingmai.jd.com/api/identity?token=fake-private'
 class Request:resource_type='fetch';method='GET'
 request=Request()
 def header_value(self,name):return 'application/json' if name=='content-type' else '100'
 def json(self):return {'data':{'shopName':'测试店','venderId':'1','access_token':'fake-private'}}

class BrowserTests(unittest.TestCase):
 def test_task_owned_context_reused_for_oauth_and_closed(self):
  factory=Factory();browser=PlaywrightBrowser('测试店','1',factory=lambda:factory,headless=True);browser.open_jingmai();page=factory.driver.browser.contexts[0].page;page.handlers['response'](Response());browser.poll()
  self.assertEqual(browser.proof()['venderId'],'1');browser.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=fake-private')
  self.assertEqual(len(factory.driver.browser.contexts),1);self.assertEqual(len(page.urls),2);self.assertNotIn('fake-private',json.dumps(browser.public_observation()));browser.close();self.assertTrue(factory.driver.browser.closed);self.assertTrue(factory.driver.stopped)
 def test_oauth_url_is_not_exposed_in_observation(self):
  factory=Factory();b=PlaywrightBrowser('测试店','1',factory=lambda:factory,headless=True);b.open_jingmai();b.navigate_oauth('https://open-oauth.jd.com/oauth2/to_login?state=fake-private');self.assertNotIn('fake-private',json.dumps(b.public_observation()));b.close()

if __name__=='__main__':unittest.main()

class BrowserEnvironmentTests(unittest.TestCase):
 def test_system_browser_locations_survive_without_personal_login_env(self):
  from heideng_merchant.safety import clean_environment
  env=clean_environment(Path('test-only-home'),{'ProgramFiles':'C:/Program Files','ProgramFiles(x86)':'C:/Program Files (x86)','JD_LLM_API_KEY':'synthetic','LOCALAPPDATA':'personal-login-data'})
  self.assertEqual(env.get('ProgramFiles'),'C:/Program Files');self.assertEqual(env.get('ProgramFiles(x86)'),'C:/Program Files (x86)');self.assertNotIn('JD_LLM_API_KEY',env);self.assertNotEqual(env['LOCALAPPDATA'],'personal-login-data')
