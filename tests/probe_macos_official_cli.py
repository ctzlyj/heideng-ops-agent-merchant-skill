"""Record a credential-free observation of JD's reported macOS ARM64 release."""
import json
from pathlib import Path
import platform
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli_diagnostics import public_cli_check
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import SafetyError, read_json

ARCHIVE_SHA256 = 'dda5cd6c7aadbfd0ba31a876705445a97108fa60fe1af2c28d28c94775473c54'


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
        return public_cli_check(client)


if __name__ == '__main__':
    print(json.dumps(observe(), ensure_ascii=True))
