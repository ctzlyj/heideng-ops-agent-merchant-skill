from pathlib import Path
import tempfile
import unittest

from tests.pop_psd_contract import run_contract


class SharedPopPsdTest(unittest.TestCase):
    def test_source_install_builds_and_reopens_a_layered_price_label(self):
        with tempfile.TemporaryDirectory() as state:
            run_contract(Path(state), merchant=Path(__file__).resolve().parents[1])
