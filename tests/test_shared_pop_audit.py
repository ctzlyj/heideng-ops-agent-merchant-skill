"""Run the vendored authoritative scope regression through the installed merchant CLI."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.pop_audit_contract import exercise_entry


class SharedPopAuditTest(unittest.TestCase):
    @unittest.skipUnless(all(importlib.util.find_spec(name) is not None for name in
                             ('httpx','requests','openpyxl','PIL','PyInstaller','playwright')),
                         'mature materials runtime required')
    def test_materials_route_returns_only_the_requested_products(self):
        exercise_entry([sys.executable, str(Path(__file__).resolve()), '--installed', '{state}'])


if __name__ == '__main__' and sys.argv[1:2] == ['--installed']:
    state = Path(sys.argv[2])
    skills = state/'skills'
    entry = skills/'heideng-ops-agent-merchant/scripts/merchant.py'
    if not entry.exists():
        install = subprocess.run([sys.executable, str(ROOT/'install.py'), '--state', str(state),
                                  '--skills-dir', str(skills), '--offline', '--no-auto-update'],
                                 capture_output=True)
        if install.returncode:
            sys.stderr.buffer.write(install.stdout + install.stderr)
            sys.exit(install.returncode)
    sys.exit(subprocess.call([sys.executable, str(entry), '--state', str(state),
                              'run', 'materials', '--', *sys.argv[3:]]))
