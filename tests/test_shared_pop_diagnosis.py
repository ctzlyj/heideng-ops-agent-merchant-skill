"""Exercise the public install and merchant-authorized L1 and L2 diagnosis entries."""
from pathlib import Path
import tempfile
import unittest

from tests.pop_diagnosis_contract import run_contract


class SharedPopDiagnosisTest(unittest.TestCase):
    def test_inspect_and_validate_with_synthetic_official_reads(self):
        with tempfile.TemporaryDirectory() as state:
            run_contract(Path(state), merchant=Path(__file__).resolve().parents[1])
