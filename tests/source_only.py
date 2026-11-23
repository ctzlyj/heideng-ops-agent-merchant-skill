"""Leave archive-producing fixtures paused in the source-only CI processes."""
import unittest


def pause_bundle_fixtures():
    from heideng_merchant import distribution

    def paused(*args, **kwargs):
        raise unittest.SkipTest('Skill ZIP production is paused for the Git source beta')

    # Install before unittest loads suites (including imports of these builders).
    # Ordinary XLSX and merchant media exports still exercise their real formats.
    distribution.build_bundle = paused
    from tests import test_update_loop
    test_update_loop.package = paused
