from pathlib import Path
import tempfile
import unittest

from tests.pop_video_contract import run_contract


class SharedPopVideoTest(unittest.TestCase):
    def test_public_install_produces_and_verifies_the_same_local_handoff(self):
        with tempfile.TemporaryDirectory() as state:
            run_contract(Path(state), merchant=Path(__file__).resolve().parents[1])
