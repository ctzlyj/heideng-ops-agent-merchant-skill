import unittest
from tests import test_short_title_browser as fixtures
from heideng_merchant.safety import SafetyError
from heideng_merchant.short_title_browser_contract import response_bytes

class BrowserBodyContractTests(unittest.TestCase):
 def test_decoded_compressed_json_is_not_compared_with_encoded_content_length(self):
  import tempfile,gzip
  with tempfile.TemporaryDirectory() as d:
   page=fixtures.Page(d);response=fixtures.Response(page,fixtures.IDENTITY,{'data':{'shopName':'synthetic-store','venderId':'1','shopId':'3','shopType':'POP'}});raw=response.body();encoded=gzip.compress(raw)
   response.header_value=lambda name:'application/json' if name=='content-type' else 'gzip' if name=='content-encoding' else str(len(encoded)) if name=='content-length' else None
   parsed=response_bytes(response,page);self.assertEqual(parsed[0],raw)
 def test_browser_body_completion_error_is_not_valid_json_proof(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   page=fixtures.Page(d);response=fixtures.Response(page,fixtures.IDENTITY,{})
   def failed():raise RuntimeError('synthetic response interrupted')
   response.finished=failed
   with self.assertRaises(SafetyError):response_bytes(response,page)

 def test_synthetic_template_is_repeatable_across_zip_clock_ticks(self):
  import time
  from tests.short_title_fixtures import template
  first=template();time.sleep(2.1);self.assertEqual(first,template())

 def test_current_health_audit_uses_existing_owned_install_guard(self):
  import tempfile
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(d);b.open()
   try:out=ShopMaterialAudit(d,c).audit('merchant-test',install_guard=b.install_lock);self.assertTrue(out['scoreSourceComplete']);self.assertTrue(b.install_lock.acquired)
   finally:b.close()
 def test_unheld_or_wrong_path_guard_is_not_an_install_lock_bypass(self):
  import tempfile
  from pathlib import Path
  from heideng_merchant.state import FileLock
  from heideng_merchant.shop_material_audit import ShopMaterialAudit
  with tempfile.TemporaryDirectory() as d:
   c,s,p,f,b=fixtures.ShortTitleBrowserTests().make(d);audit=ShopMaterialAudit(d,c);guard=FileLock(Path(d)/'install.lock')
   with self.assertRaises(SafetyError):audit.audit('merchant-test',install_guard=guard)
   with FileLock(Path(d)/'other.lock') as other:
    with self.assertRaises(SafetyError):audit.audit('merchant-test',install_guard=other)

if __name__=='__main__':unittest.main()
