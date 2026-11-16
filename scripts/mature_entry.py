"""Run one provenance-selected mature Python entry in an isolated child."""
import runpy, sys, os
from contextlib import nullcontext
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from heideng_merchant.mature_runtime import install_network_guard
from heideng_merchant.safety import SafetyError
if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    script = Path(sys.argv[1]).resolve()
    if not script.is_relative_to(root/'mature'):
        raise SafetyError('mature-entry-outside-package')
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *sys.argv[2:]]
    install_network_guard()
    from heideng_merchant.state import FileLock
    state=os.environ.get('HEIDENG_MERCHANT_HOME')
    if not state:
        # Direct help/preparation still uses the same merchant namespace, not a new gate.
        from heideng_merchant.state import merchant_home
        from heideng_merchant.mature_runtime import child_environment
        state=str(merchant_home())
        environment=child_environment(Path(state))
        environment['HEIDENG_MERCHANT_PACKAGE']=str(root)
        os.environ.clear();os.environ.update(environment)
    # Detached pipeline workers keep a lease themselves. The idle connector service
    # instead uses its original idle-only shutdown/activity guard during an update.
    service=script == root/'mature/connection/app/server.py'
    lease=nullcontext() if service else FileLock(Path(state)/'install.lock',shared=True)
    with lease:
        runpy.run_path(str(script), run_name='__main__')
