"""Shared test fixtures.

`terra_mcp.gcs` keeps process-lifetime state on purpose: the resolved backend,
a cached `storage.Client`, a `requests.Session` and refreshed credentials. That
is right for a long-lived server and wrong for a test suite, where almost every
test patches `storage.Client` and would otherwise inherit the previous test's
mock. Reset it around every test.
"""

import pytest

from terra_mcp import gcs


def _reset():
    gcs.set_backend("auto")  # also clears the cached JSON client
    gcs._session = None
    gcs._credentials = None


@pytest.fixture(autouse=True)
def reset_gcs_state():
    _reset()
    yield
    _reset()
