"""Record a credential-free observation of JD's reported macOS ARM64 release."""
import json
from hashlib import sha256
import io
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli_diagnostics import public_cli_check
from heideng_merchant.official import BASE, OfficialClient
from heideng_merchant.safety import SafetyError, clean_environment, read_json

ARCHIVE_SHA256 = 'dda5cd6c7aadbfd0ba31a876705445a97108fa60fe1af2c28d28c94775473c54'
SOURCE_SHA256 = 'abcc6fe5a354d14c4a9b99a221d0b682759d77e8200fc3922f0c1ce32e86a0b2'


def archive_controls(client, root):
    """Run only an uncached public GET from the unmodified release, with standard trust checks."""
    archive = client.policy()['artifacts']['binaries']['macos-arm64']
    raw = client.download(BASE + archive['path'])
    if sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise SafetyError('official-release-control-hash-mismatch')
    extracted = root / 'jd-release'
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        tar.extractall(extracted, filter='data')
    executable = extracted / archive['executable']
    system_trust = {}
    for name, path in (('SSL_CERT_FILE', '/etc/ssl/cert.pem'), ('SSL_CERT_DIR', '/etc/ssl/certs'),
                       ('OPENSSL_CONF', '/etc/ssl/openssl.cnf')):
        if Path(path).exists():
            system_trust[name] = path
    cases = [('release-root', extracted, {}), ('binary-directory', executable.parent, {}),
             ('explicit-tmpdir', extracted, {'TMPDIR': tempfile.gettempdir()})]
    if system_trust:
        cases.append(('macos-system-trust', extracted, system_trust))
    try:
        import certifi
    except ImportError:
        pass
    else:
        if Path(certifi.where()).is_file():
            cases.append(('python-trust-bundle', extracted, {'SSL_CERT_FILE': certifi.where()}))
    results = {}
    cases.append(('release-readme-install', None, {}))
    for name, cwd, additions in cases:
        with tempfile.TemporaryDirectory(prefix='clean-cli-', dir=root) as tmp:
            env = clean_environment(Path(tmp))
            env.update(additions, JDO_HOME=str(Path(tmp) / '.jdo-cli'))
            binary = executable
            if cwd is None:
                # The vendor's README puts both bin/ and the CLI state under ~/.jdo-cli.
                # Reproduce it only in this empty disposable home with no account inputs.
                cwd = Path(tmp)
                installed = cwd / '.jdo-cli'
                with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
                    tar.extractall(installed, filter='data')
                binary = installed / archive['executable']
                init = subprocess.run([str(binary), 'init', '--skip-network'], cwd=cwd, env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                if init.returncode:
                    results[name] = 'offline-init-failed'
                    continue
            proc = subprocess.run([str(binary), '--endpoint', 'https://mcp-open.jd.com',
                                   'update', 'check', '--timeout', '12'],
                                  cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=30)
            try:
                payload = json.loads(proc.stdout)
            except ValueError:
                payload = {}
            if proc.returncode == 0 and payload.get('ok') is True and payload.get('cacheUsed') is False:
                results[name] = 'remote-policy-received'
            elif '[errno 2]' in str(payload.get('networkError', '')).lower():
                results[name] = 'file-not-found'
            else:
                results[name] = 'not-verified'
    return results


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
            result['unmodifiedReleaseControls'] = archive_controls(client, Path(state))
        return result


if __name__ == '__main__':
    print(json.dumps(observe(), ensure_ascii=True))
