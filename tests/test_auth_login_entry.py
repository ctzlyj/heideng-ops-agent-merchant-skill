"""HD-002: the executed login action must open passport, not the home page."""
import json,tempfile,unittest
from pathlib import Path
from heideng_merchant.auth_browser import PlaywrightBrowser
from heideng_merchant.auth_browser_host import HostControllerBrowser
from heideng_merchant.auth_broker import public_status
from heideng_merchant.auth_flow import eligible_identity_source
from tests.test_auth_browser import Factory

LOGIN_URL='https://passport.shop.jd.com/login/index.action'

class LoginEntryTests(unittest.TestCase):
 def test_host_open_login_action_supplies_actual_login_page(self):
  with tempfile.TemporaryDirectory() as d:
   actions=[]
   def controller(command,**options):
    actions.append(json.loads(options['input'])['action'])
    result={'ok':True,'owned':True,'isolated':True,'contextId':'fixture-context'}
    return type('Result',(),{'returncode':0,'stdout':json.dumps(result).encode()})()
   browser=HostControllerBrowser(Path(d),'a'*24,'test-shop',['python','fixture.py'],runner=controller)
   browser.open_jingmai()
   self.assertEqual(actions[0]['kind'],'open_login')
   self.assertEqual(actions[0].get('url'),LOGIN_URL)
   self.assertEqual(actions[0]['target'],'test-shop')

 def test_standalone_browser_first_navigation_is_actual_login_page(self):
  factory=Factory();browser=PlaywrightBrowser('test-shop',factory=lambda:factory,headless=True)
  browser.open_jingmai()
  try:self.assertEqual(factory.driver.browser.contexts[0].page.urls,[LOGIN_URL])
  finally:browser.close()

 def test_login_guidance_does_not_instruct_extra_homepage_login_click(self):
  result=public_status({'taskId':'a'*24,'status':'running','stage':'waiting_login'})
  self.assertNotIn('\u5148\u70b9\u51fb',result['userAction'])

 def test_login_page_does_not_expand_identity_source_trust(self):
  self.assertFalse(eligible_identity_source(LOGIN_URL))

if __name__=='__main__':unittest.main()
