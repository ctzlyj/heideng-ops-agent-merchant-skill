"""Read-only owned login observation; no repeated navigation while scanning."""
import tempfile, unittest
from heideng_merchant.safety import SafetyError
from tests import test_short_title_browser as source_fixture
from tests.test_short_title_browser import Response, IDENTITY

class WorkerAuthenticationObservationTests(unittest.TestCase):
 def make(self, d):
  return source_fixture.ShortTitleBrowserTests().make(d)
 def status(self, browser):
  self.assertTrue(callable(getattr(browser, 'authentication_status', None)), 'worker needs a safe read-only login observation')
  return browser.authentication_status()
 def test_login_identity_observed_without_navigation_or_capture(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open()
   try:
    page=f.driver.context.page;urls=list(page.urls)
    for _ in range(3):
     b.poll();out=self.status(b)
     self.assertEqual(out['status'],'identity-observed');self.assertTrue(out['currentIdentityVerified'])
     self.assertFalse(out['approvalReady']);self.assertFalse(out['writeExecutionAvailable'])
    self.assertEqual(page.urls,urls);self.assertFalse(page.clicks);self.assertFalse(c.posts)
   finally:b.close()
 def test_scanning_waits_for_fresh_owned_response_without_reloading(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);f.driver.context.new_page=lambda: self.empty_page(f.driver.context,d);b.open()
   try:
    page=f.driver.context.page;urls=list(page.urls)
    for _ in range(3):b.poll();self.assertEqual(self.status(b)['status'],'awaiting-login')
    page.emit(Response(page,IDENTITY,{'data':{'shopName':'synthetic-store','venderId':'1','shopId':'3','shopType':'POP'}}))
    self.assertEqual(self.status(b)['status'],'identity-observed');self.assertEqual(page.urls,urls)
   finally:b.close()
 def empty_page(self, context, d):
  from tests.test_short_title_browser import Page
  page=Page(d);page.identities=[];context.page=page;context.pages.append(page);return page
 def test_stale_unregistered_and_unowned_response_do_not_authenticate(self):
  for kind in ('stale','unregistered','unowned','split','non-pop'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,s,p,f,b=self.make(d);f.driver.context.new_page=lambda:self.empty_page(f.driver.context,d);b.open()
    try:
     page=f.driver.context.page;value={'data':{'shopName':'synthetic-store','venderId':'1','shopId':'3','shopType':'POP'}}
     if kind=='split':value={'data':[{'shopName':'synthetic-store'},{'venderId':'1','shopId':'3','shopType':'POP'}]}
     if kind=='non-pop':value['data']['shopType']='1'
     r=Response(object() if kind=='unowned' else page,IDENTITY,value)
     if kind=='stale':r.request.timing['startTime']=999999
     if kind=='unregistered':b._response(r)
     else:page.emit(r)
     self.assertFalse(self.status(b)['currentIdentityVerified']);self.assertFalse(page.clicks)
    finally:b.close()
 def test_foreign_identity_revokes_login_observation(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open()
   try:
    self.assertTrue(self.status(b)['currentIdentityVerified']);page=f.driver.context.page
    page.emit(Response(page,IDENTITY,{'data':{'shopName':'other-synthetic','venderId':'2','shopId':'2','shopType':'POP'}}))
    self.assertEqual(self.status(b)['status'],'identity-mismatch');self.assertFalse(self.status(b)['currentIdentityVerified'])
   finally:b.close()
 def test_login_observation_is_not_reused_as_capture_proof(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=self.make(d);b.open()
   try:
    self.assertTrue(self.status(b)['currentIdentityVerified']);f.driver.context.page.identities=[]
    with self.assertRaises(SafetyError):b.capture()
    self.assertFalse(f.driver.context.page.clicks)
   finally:b.close()
