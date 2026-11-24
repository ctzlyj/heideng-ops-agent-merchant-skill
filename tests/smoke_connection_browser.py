"""Exercise the bundled connection controller in a real local browser without a merchant login."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from heideng_merchant.host_connection_controller import CHANNELS
from heideng_merchant.mature_runtime import child_environment, source_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', choices=CHANNELS, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    linker, _ = source_path('connection', package_root=root)
    with tempfile.TemporaryDirectory(prefix='heideng-connection-smoke-') as temporary:
        state = Path(temporary)
        inherited = {k:v for k,v in os.environ.items() if not k.startswith(('HEIDENG_','JDO_'))}
        env = child_environment(state, inherited)
        result = subprocess.run([sys.executable, '-I', '-B', str(root/'scripts/mature_entry.py'), str(linker),
                                 'browser-check', '--channel', args.channel], cwd=state, env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=90)
    if not result.stdout.strip():
        raise RuntimeError('isolated browser check did not return a receipt')
    result = json.loads(result.stdout)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
