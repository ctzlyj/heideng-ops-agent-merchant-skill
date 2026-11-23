"""Frozen migration scope; old builtin business contracts are retired, not product claims."""
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment
MODULES=['test_safety','test_distribution','test_mature_runtime','test_mature_connection','test_mature_materials','test_mature_eol','test_mature_release_refs','test_mature_refresh','test_mature_diagnosis','test_mature_diagnosis_full','test_mature_image','test_runtime_dependencies','test_mature_leases','test_mature_review_regressions','test_mature_listing','test_mature_publish_reuse','test_mature_listing_extra','test_mature_collection','test_mature_collection_transport','test_mature_comparison']
MODULES += ['test_connection_single_flow', 'test_field_9mv_connection', 'test_audit_connection_contracts', 'test_update_loop']

MODULES += ['test_category_gallery', 'test_category_image_recovery', 'test_category_sku_edit', 'test_category_fees']

MODULES += ['test_listing_feasibility', 'test_commercial_task_context', 'test_executable_budget']

MODULES += ['test_sample_delivery', 'test_sample_comparison', 'test_sample_upload_state']

MODULES.append('test_dual_commercial_images')

def main():
    source_only='--source-only' in sys.argv
    with tempfile.TemporaryDirectory(prefix='merchant-mature-offline-') as home:
        env=clean_environment(Path(home));env['PYTHONIOENCODING']='utf-8'
        code="""import sys,socket,ipaddress,unittest
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
original=socket.socket.connect
def only_local(self,address):
 if isinstance(address,tuple):
  try:local=ipaddress.ip_address(address[0]).is_loopback
  except ValueError:local=address[0]=='localhost'
  if not local:raise RuntimeError('offline suite: external network forbidden')
 return original(self,address)
socket.socket.connect=only_local
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.'+name) for name in sys.argv[1:])
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
        guard='from tests.source_only import pause_bundle_fixtures;pause_bundle_fixtures();' if source_only else ''
        result=subprocess.run([sys.executable,'-I','-B','-c',"import sys;sys.path.insert(0,"+repr(str(ROOT))+");"+guard+code,*MODULES],cwd=ROOT,env=env)
        return result.returncode
if __name__=='__main__':raise SystemExit(main())
