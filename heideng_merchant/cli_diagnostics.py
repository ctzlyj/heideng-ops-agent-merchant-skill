"""Isolate startup and public HTTPS checks from the merchant's shop session."""
import json
from pathlib import Path
import platform
import subprocess
import tempfile

from .safety import clean_environment, read_json


def runtime_failure(text):
    text = text.lower()
    denied = 'permission denied' in text or 'operation not permitted' in text
    if denied and any(marker in text for marker in ('semctl', 'mach', 'crashpad')):
        return 'local-execution-permission'
    if ('ssl' in text or 'certifi' in text) and ('filenotfounderror' in text or '[errno 2]' in text):
        return 'tls-runtime-file-missing'
    if 'certificate_verify_failed' in text or 'certificate verify failed' in text:
        return 'tls-certificate-verification'
    if '[errno 2]' in text or 'filenotfounderror' in text:
        return 'runtime-file-missing'
    return None


def public_cli_check(client):
    if not client.ready():
        return {'status': 'unavailable', 'stage': 'installation', 'reason': 'official-binary-unverified'}
    executable = str(client.executable())
    installed = read_json(client.receipt_path)
    result = {'platform': client.platform_name, 'architecture': platform.machine(), 'version': installed['version'],
              'archiveSha256': installed['archiveSha256'], 'executableSha256': installed['executableSha256'],
              'loginAttempted': False, 'shopRequests': 0}
    with tempfile.TemporaryDirectory(prefix='heideng-cli-check-') as directory:
        env = clean_environment(Path(directory))
        env['JDO_HOME'] = str(Path(directory) / '.jdo-cli')
        for stage, args in (('process-start', ['--help']),
                            ('public-https', ['--endpoint', 'https://mcp-open.jd.com', 'update', 'check', '--timeout', '12'])):
            try:
                proc = subprocess.run([executable, *args], cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                return {**result, 'status': 'unavailable', 'stage': stage, 'reason': 'timeout'}
            except OSError as exc:
                return {**result, 'status': 'unavailable', 'stage': stage,
                        'reason': 'local-execution-permission' if isinstance(exc, PermissionError) else 'os-start-failed',
                        'errno': exc.errno}
            if proc.returncode:
                reason = runtime_failure(proc.stderr + '\n' + proc.stdout)
                return {**result, 'status': 'unavailable', 'stage': stage, 'exitCode': proc.returncode,
                        'reason': reason or 'official-command-failed'}
            if stage == 'public-https':
                try:
                    receipt = json.loads(proc.stdout)
                except ValueError:
                    receipt = None
                if not (isinstance(receipt, dict) and receipt.get('command') == 'update check' and
                        receipt.get('ok') is True and receipt.get('cacheUsed') is False and
                        receipt.get('cliVersion') == installed['version'] and
                        isinstance(receipt.get('versionPolicy'), dict) and receipt['versionPolicy'].get('product') == 'jdo-cli'):
                    return {**result, 'status': 'unavailable', 'stage': stage, 'reason': 'public-receipt-unverified'}
    return {**result, 'status': 'verified', 'stage': 'public-https'}
