"""fastops helpers are bit-identical to the np.unique calls they replace (#145)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import fastops as F  # noqa: E402


@pytest.mark.parametrize("n,hi", [(0, 5), (1, 5), (1000, 7), (50000, 10**12)])
@pytest.mark.parametrize("dt", [np.int32, np.int64])
def test_unique_family(n, hi, dt):
    a = np.random.default_rng(n).integers(0, hi, n).astype(dt)
    u = np.unique(a)
    assert np.array_equal(u, F.unique(a)) and F.unique(a).dtype == u.dtype
    for x, y in zip(np.unique(a, return_counts=True), F.unique_counts(a)):
        assert np.array_equal(x, y) and x.dtype == y.dtype
    for x, y in zip(np.unique(a, return_inverse=True), F.unique_inverse(a)):
        assert np.array_equal(x, y) and x.dtype == y.dtype


def test_rows_and_mark():
    k = np.random.default_rng(3).integers(-1, 30, (2000, 2))
    u, i = np.unique(k, axis=0, return_inverse=True)
    v, j = F.unique_rows2_inverse(k)
    assert np.array_equal(u, v) and np.array_equal(i.reshape(-1), j)
    idx = np.random.default_rng(4).integers(0, 500, 3000).astype(np.int32)
    assert np.array_equal(np.unique(idx), F.mark_unique(idx, 500))
