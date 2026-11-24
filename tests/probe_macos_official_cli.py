"""Record a credential-free observation of JD's reported macOS ARM64 release."""
import json
from hashlib import sha256
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli_diagnostics import public_cli_check
from heideng_merchant.official import BASE, OfficialClient
from heideng_merchant.safety import SafetyError, clean_environment, read_json

ARCHIVE_SHA256 = 'dda5cd6c7aadbfd0ba31a876705445a97108fa60fe1af2c28d28c94775473c54'
SOURCE_SHA256 = 'abcc6fe5a354d14c4a9b99a221d0b682759d77e8200fc3922f0c1ce32e86a0b2'


def source_control(client, root):
    """Compare only the same credential-free public command. Never install the script for shop tasks."""
    entry = client.policy()['artifacts']['cli']
    if (entry.get('version'), entry.get('path'), entry.get('sha256')) != ('0.3.7', 'cli/jdo-cli', SOURCE_SHA256):
        return 'source-pin-unavailable'
    raw = client.download(BASE + entry['path'])
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise SafetyError('official-source-control-hash-mismatch')
    script = root / 'control-cli'
    script.write_bytes(raw)
    home = root / 'source-home'
    home.mkdir()
    env = clean_environment(home)
    env['JDO_HOME'] = str(home / '.jdo-cli')
    proc = subprocess.run([sys.executable, '-I', '-B', str(script), '--endpoint', 'https://mcp-open.jd.com',
                           'update', 'check', '--timeout', '12'], cwd=home, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=25)
    if proc.returncode:
        return 'command-failed'
    receipt = json.loads(proc.stdout)
    return ('verified' if receipt.get('command') == 'update check' and receipt.get('ok') is True
            and receipt.get('cacheUsed') is False and receipt.get('cliVersion') == '0.3.7' and
            receipt.get('versionPolicy', {}).get('product') == 'jdo-cli' else 'unverified')


def observe():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        return {'status': 'not-tested', 'reason': 'requires-macos-arm64'}
    with tempfile.TemporaryDirectory(prefix='merchant-public-jdo-') as state:
        client = OfficialClient(state)
        try:
            client.install()
        except SafetyError as error:
            if str(error) in ('official-network-unavailable', 'official-platform-not-supported'):
                return {'status': 'not-tested', 'stage': 'download', 'reason': str(error)}
            raise
        receipt = read_json(client.receipt_path)
        if receipt['archiveSha256'] != ARCHIVE_SHA256 or receipt['version'] != '0.3.7':
            return {'status': 'not-tested', 'reason': 'release-no-longer-current'}
        result = public_cli_check(client)
        result['publicPolicyViaPython'] = 'verified'
        if result['status'] != 'verified':
            result['sameVersionOfficialSourceControl'] = source_control(client, Path(state))
        return result


if __name__ == '__main__':
    print(json.dumps(observe(), ensure_ascii=True))
