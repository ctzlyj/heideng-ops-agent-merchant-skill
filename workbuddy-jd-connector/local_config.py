"""Print a machine-local cli.json for a development checkout on a supported JD platform."""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess


def configuration(state):
    script = Path(__file__).resolve().with_name('card.py')
    arguments = ['python', '-I', '-B', str(script), '--core', str(script.parents[1]),
                 '--state', str(state.expanduser().resolve())]
    arch = platform.machine().lower()
    if os.name == 'nt' and arch in ('amd64', 'x86_64'):
        system, quote = 'win32', subprocess.list2cmdline
    elif platform.system() == 'Darwin' and arch == 'arm64':
        system, quote = 'darwin', shlex.join
    else:
        raise ValueError('京东官方 CLI 尚未发行适用于本机的二进制。')
    commands = {key: {system: quote([*arguments, action])}
                for key, action in [('init', 'prepare'), ('auth', 'auth'),
                                    ('status', 'status'), ('unAuth', 'unAuth')]}
    return {**commands, 'runtime': {'type': 'python', 'version': '3.11'},
            'authUrlDomain': 'open-oauth.jd.com',
            'statusMatchJson': {'status': 'ready', 'matched': True}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home()/'.heideng-wb-jd-card')
    options = parser.parse_args()
    try:
        print(json.dumps(configuration(options.state), ensure_ascii=True, indent=2))
    except ValueError as error:
        parser.exit(2, f'{error}\n')
