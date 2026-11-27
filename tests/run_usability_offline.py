"""Bounded merchant usability verification, not all mature business reacceptance."""
import subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment
MODULES=['test_task_image_prompts','test_field_9mv_connection','test_field_9mv_materials','test_mature_image','test_field_material_contracts','test_field_install_contracts','test_audit_contracts','test_audit_connection_contracts','test_audit_handoff_contracts','test_merchant_experience','test_connection_experience','test_connection_service_lifecycle','test_merchant_usability','test_merchant_key_input','test_merchant_usability_upgrade','test_mature_connection','test_mature_materials','test_runtime_dependencies','test_mature_runtime','test_mature_release_refs','test_install_entry','test_update_loop']

MODULES.append('test_field_commerce')
MODULES.append('test_commerce_handoff')
MODULES += ['test_owned_copy_decisions','test_shop_copy_batch','test_shop_copy_repair']
MODULES += ['test_copy_materials','test_copy_field_receipts','test_refresh_selection','test_refresh_gallery_evidence','test_refresh_upload_recovery']

MODULES += ['test_workbuddy_expert', 'test_expert_guidance', 'test_expert_mcp', 'test_jd_card_runtime']

def main():
    source_only='--source-only' in sys.argv
    modules=[*MODULES,'test_source_install','test_gallery_patch','test_overlay_preview','test_mac_merchant_runtime',
             'test_connection_browser_runtime','test_mac_login_receipt','test_connection_local_timeout',
             'test_short_title_import_batches','test_shop_workspace','test_owned_product_copy','test_shop_copy_delivery',
             'test_shop_copy_entry','test_shop_locations','test_freight_page_draft','test_material_browser_identity']
    with tempfile.TemporaryDirectory(prefix='merchant-usability-offline-') as d:
        env=clean_environment(Path(d));env['PYTHONIOENCODING']='utf-8'
        code="""import sys,socket,ipaddress,unittest
original=socket.socket.connect
def only_loopback(self,address):
 if isinstance(address,tuple):
  try:allowed=ipaddress.ip_address(address[0]).is_loopback
  except ValueError:allowed=address[0]=='localhost'
  if not allowed:raise RuntimeError('usability offline suite forbids external network')
 return original(self,address)
socket.socket.connect=only_loopback
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.'+n) for n in sys.argv[1:])
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
        guard='from tests.source_only import pause_bundle_fixtures;pause_bundle_fixtures();' if source_only else ''
        return subprocess.run([sys.executable,'-I','-B','-c','import sys;sys.path.insert(0,'+repr(str(ROOT))+');'+guard+code,*modules],cwd=ROOT,env=env).returncode
if __name__=='__main__':raise SystemExit(main())
