"""Immortalize long-lived shared read-only objects under free-threaded CPython.

Why this exists
---------------
In a free-threaded build (PEP 703), every thread that touches a shared object
does an INCREF/DECREF on it.  For a big structure read by many worker threads
-- the routing graph, the CRAM buffer, the tile DB -- those refcount writes all
land on the same cache line and serialise the workers.  Immortalizing the
object (PEP 683) makes INCREF/DECREF genuine no-ops on it, removing the
contention entirely.

Which primitive
---------------
`_Py_SetImmortal` (via ctypes) is the right tool, and is exported from
libpython in every free-threaded build (3.13t/3.14t/3.15t).  It is exactly what
CPython itself calls to immortalize None/True/small ints/interned strings.

Rejected alternatives:
  * hand-rolling the refcount-header write (our old probe) -- build-specific
    offsets, and incomplete: it skips ob_tid and the GC-untrack that
    _Py_SetImmortal performs.
  * `PyUnstable_SetImmortal` (public, 3.15a6+) -- refuses any object that is
    not uniquely referenced by the calling thread, and refuses str outright.
    It is designed for immortalizing at creation; it no-ops on an
    already-built, already-shared graph, which is precisely our case.
  * `PyUnstable_Object_EnableDeferredRefcount` (public, 3.14+) -- deferred
    reference counting, a different mechanism.  It returns 0 for anything that
    is not a GC-tracked container, so it cannot help the CRAM bytes buffer at
    all.

Safety
------
Immortalization is permanent and one-way: an immortal object is never freed.
That is correct for process-lifetime roots and a LEAK for anything transient.
Only ever call this at a "freeze point" -- after a shared read-only structure
is fully built and before worker threads fan out.  Never immortalize per-run
or per-bitstream state (pluribus rebuilds that on every run).
"""
import ctypes
import sys
import types

_SET = None
_IS = None
try:  # present in every free-threaded build; absent on some GIL builds
    _SET = ctypes.pythonapi._Py_SetImmortal
    _SET.argtypes = [ctypes.py_object]
    _SET.restype = None
    _IS = ctypes.pythonapi.PyUnstable_IsImmortal
    _IS.argtypes = [ctypes.py_object]
    _IS.restype = ctypes.c_int
except AttributeError:  # pragma: no cover - depends on the build
    _SET = _IS = None

# Never immortalize these: modules/classes/functions are either already
# immortal (static types) or shared machinery we have no business freezing.
_SKIP = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType,
         types.MethodType, type)
# Leaves: immortalize the object itself but do not try to walk inside it.
_LEAF = (str, bytes, bytearray, int, float, complex, bool, type(None))


def available():
    """True if this interpreter exposes the immortalization entry point."""
    return _SET is not None


def gil_disabled():
    """True on a free-threaded build with the GIL actually off."""
    return not sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else False


def is_immortal(obj):
    return bool(_IS(obj)) if _IS is not None else False


def immortalize(obj):
    """Immortalize a single object (no-op if unsupported).  Returns `obj`."""
    if _SET is not None:
        _SET(obj)
    return obj


def immortalize_tree(root, limit=None):
    """Immortalize `root` and everything reachable from it.  Returns the count.

    Walks dicts, sequences/sets, and plain objects (via __dict__ / __slots__).
    Cycle-safe.  Intended for a fully-built, read-only structure at a freeze
    point -- see the module docstring's Safety note.
    """
    if _SET is None:
        return 0
    seen = set()
    stack = [root]
    n = 0
    while stack:
        o = stack.pop()
        oid = id(o)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(o, _SKIP):
            continue
        _SET(o)
        n += 1
        if limit is not None and n >= limit:
            break
        if isinstance(o, _LEAF):
            continue
        if isinstance(o, dict):
            for k, v in o.items():
                stack.append(k)
                stack.append(v)
        elif isinstance(o, (list, tuple, set, frozenset)):
            stack.extend(o)
        else:
            d = getattr(o, "__dict__", None)
            if isinstance(d, dict):
                stack.append(d)
            for klass in type(o).__mro__:
                for slot in getattr(klass, "__slots__", ()) or ():
                    try:
                        stack.append(getattr(o, slot))
                    except AttributeError:
                        pass
    return n
