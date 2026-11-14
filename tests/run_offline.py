"""Fresh HOME, no real credentials, no socket networking in the test process."""
import os,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from heideng_merchant.safety import clean_environment

def main():
 if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
 with tempfile.TemporaryDirectory(prefix='merchant-offline-suite-') as home:
  env=clean_environment(Path(home));env['PYTHONUTF8']='1'
  code="import sys,socket,unittest; from pathlib import Path; sys.path.insert(0,str(Path.cwd())); socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline network forbidden')); socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline network forbidden')); suite=unittest.defaultTestLoader.discover('tests'); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
  result=subprocess.run([sys.executable,'-I','-B','-c',code],cwd=root,env=env)
  return result.returncode
if __name__=='__main__':raise SystemExit(main())
