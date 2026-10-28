"""Sort-based numpy helpers (perf pass, docs/perf-pass.md; #145).

np.unique on large int arrays takes numpy's hash path (1.2 s on 2.85 M int64); sort + diff is ~30x faster.
All results are identical to the np.unique call they replace, including order: values ascending,
inverse/counts indexed by that order.  PLURIBUS_UNIQUE=legacy routes every helper to np.unique (A/B).
"""
import os

import numpy as np

LEGACY = os.environ.get("PLURIBUS_UNIQUE") == "legacy"   # A/B: delegate to np.unique


def unique(a):
    """== np.unique(a): ascending sorted distinct values, same dtype.  Input is not modified."""
    a = np.asarray(a).ravel()
    if LEGACY:
        return np.unique(a)
    if a.size == 0:
        return a.copy()
    s = np.sort(a)
    keep = np.empty(s.size, bool)
    keep[0] = True
    np.not_equal(s[1:], s[:-1], out=keep[1:])
    return s[keep]


def unique_counts(a):
    """== np.unique(a, return_counts=True): (ascending values, int64 counts)."""
    a = np.asarray(a).ravel()
    if LEGACY:
        return np.unique(a, return_counts=True)
    if a.size == 0:
        return a.copy(), np.zeros(0, np.intp)
    s = np.sort(a)
    keep = np.empty(s.size, bool)
    keep[0] = True
    np.not_equal(s[1:], s[:-1], out=keep[1:])
    idx = np.flatnonzero(keep)
    return s[idx], np.diff(np.append(idx, s.size))


def unique_inverse(a):
    """== np.unique(a, return_inverse=True): (ascending values, int64 inverse with a == u[inv])."""
    a = np.asarray(a).ravel()
    if LEGACY:
        u, inv = np.unique(a, return_inverse=True)
        return u, inv.reshape(-1)
    if a.size == 0:
        return a.copy(), np.zeros(0, np.intp)
    o = np.argsort(a, kind="stable")
    s = a[o]
    keep = np.empty(s.size, bool)
    keep[0] = True
    np.not_equal(s[1:], s[:-1], out=keep[1:])
    inv = np.empty(a.size, np.intp)
    inv[o] = np.cumsum(keep) - 1
    return s[keep], inv


def unique_rows2_inverse(key):
    """== np.unique(key, axis=0, return_inverse=True) for an (n, 2) int array: rows in lexicographic
    order, inverse per row (int64, 1-D)."""
    key = np.asarray(key)
    if LEGACY:
        u, inv = np.unique(key, axis=0, return_inverse=True)
        return u, inv.reshape(-1)
    o = np.lexsort((key[:, 1], key[:, 0]))
    s = key[o]
    keep = np.empty(len(s), bool)
    if len(s):
        keep[0] = True
        keep[1:] = (s[1:] != s[:-1]).any(axis=1)
    inv = np.empty(len(key), np.intp)
    inv[o] = np.cumsum(keep) - 1
    return s[keep], inv


def mark_unique(idx, size):
    """Sorted distinct values of non-negative ints idx < size, via a mark array (O(n + size), no sort)."""
    m = np.zeros(size, bool)
    m[idx] = True
    return np.flatnonzero(m)
