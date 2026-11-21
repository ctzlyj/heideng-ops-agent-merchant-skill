"""Run the production fee receipt path with a synthetic merchant decision."""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from heideng_merchant.fee_consent import confirm_fee
from heideng_merchant.state import merchant_home


@contextmanager
def confirmed_fee(terms, *, state=None):
    with tempfile.TemporaryDirectory() as directory:
        state = Path(state or directory)
        with patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME': str(state)}):
            yield signed_fixture(terms)


def isolated_fees(fn):
    @wraps(fn)
    def test(*args, **kwargs):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME': directory}):
            return fn(*args, **kwargs)
    return test


def signed_fixture(terms):
    with tempfile.TemporaryDirectory() as directory, patch('heideng_merchant.fee_consent._ask_merchant', return_value=True):
        return confirm_fee(terms, merchant_home(), Path(directory)/'decision.json',
            max_requests=terms['maxRequests'], billing=terms['billing'],
            price=terms if terms['billing']=='amount' else None)
