"""immortalize — opt shared read-only objects out of reference counting.

In free-threaded CPython (PEP 703, python3.13t+), every thread that touches a
shared object performs an INCREF/DECREF on it.  For a large structure read by
many worker threads, those refcount writes are atomic read-modify-writes that
all land on the same cache lines, which then ping-pong between cores.  The
contention does not merely cap scaling -- it can invert it, making more
threads *slower* than one.

Immortalizing an object (PEP 683) sets its refcount to a permanent sentinel:
INCREF/DECREF become no-ops, the object's cache lines become read-only-shared,
and the contention disappears.

THIS IS AN EXPERT TOOL.  Read the safety notes before use:

  * Immortalization is PERMANENT and ONE-WAY.  An immortal object is never
    freed.  There is no un-immortalize -- after skipping refcounts, the true
    count is unknowable, so reversal cannot exist safely.
  * Only immortalize PROCESS-LIFETIME objects.  Immortalizing per-request /
    per-iteration data is a memory leak, one object graph at a time.
    (immortalize_tree warns via ResourceWarning when the same call site keeps
    freezing -- see `repeat_call_warning`.)
  * Immortality is NOT immutability.  An immortal dict can still be mutated,
    and concurrent mutation is still a data race.  This tool is for structures
    that are read-only after a known "freeze point".
  * The binding uses CPython's exported-but-private `_Py_SetImmortal` symbol
    (the same routine CPython itself runs when it immortalizes objects at
    runtime, e.g. interned strings; `None`/`True`/small ints are born immortal
    at build time).  It is not a public API.  Measured across standard
    Linux/macOS/Windows builds it is ctypes-visible on 3.14+ (including
    3.14t/3.15t) but NOT on 3.12/3.13/3.13t (unexported before 3.14), and
    some redistributions (e.g. python-build-standalone) never export it.
    `available()` reports whether the running interpreter exposes it;
    everything degrades to a no-op when it does not.

Typical usage -- the freeze-point idiom::

    graph = build_big_shared_graph()      # fully built, read-only from here on

    import immortalize
    immortalize.immortalize_tree(graph, strict=True)   # freeze point

    start_worker_threads(graph)           # refcount-contention-free reads

Diagnostics (all zero-cost unless called):

    immortalize.probe(graph)      # has this structure seen cross-thread use?
    immortalize.stats()           # what has been frozen, from where

VENDORED COPY of the `immortalize` package v0.2.0
(https://github.com/awtoau/immortalize) so the pipeline has no pip
dependency.  Keep in sync with the package -- fix bugs THERE first, then
re-vendor.  Local addition: `gil_disabled` alias (the pipeline's original
name for is_free_threaded).
"""
from __future__ import annotations

import ctypes
import io
import sys
import threading
import types
import warnings
import weakref
from typing import Any

__version__ = "0.2.0"

__all__ = [
    "available",
    "is_free_threaded",
    "is_immortal",
    "immortalize",
    "immortalize_tree",
    "probe",
    "stats",
    "UnsafeToImmortalize",
]

_SET = None
_IS = None
try:
    _SET = ctypes.pythonapi._Py_SetImmortal
    _SET.argtypes = [ctypes.py_object]
    _SET.restype = None
except AttributeError:  # pragma: no cover - depends on the build
    _SET = None
try:
    # Public since 3.14; on older interpreters is_immortal() falls back to a
    # refcount-threshold heuristic.
    _IS = ctypes.pythonapi.PyUnstable_IsImmortal
    _IS.argtypes = [ctypes.py_object]
    _IS.restype = ctypes.c_int
except AttributeError:  # pragma: no cover - depends on the build
    _IS = None

# Never immortalize these: modules/functions/classes are shared machinery
# (some already handled by deferred refcounting), and freezing them adds
# nothing but surprise.  Weakref proxies are skipped because merely touching
# a dead proxy's type protocol raises ReferenceError.
_SKIP = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType,
         types.MethodType, type,
         weakref.ProxyType, weakref.CallableProxyType, weakref.ref)
_EXACT_CONTAINERS = (dict, list, tuple, set, frozenset)
# Leaves: immortalize the object itself but do not walk inside it.
_LEAF = (str, bytes, bytearray, memoryview, int, float, complex, bool,
         type(None), range)

# Types that are essentially always a mistake to freeze: they pin big hidden
# graphs (frames pin every local; tracebacks pin frames), represent live OS
# resources whose finalizers will never run, or are synchronisation machinery.
_SUSPICIOUS = (types.FrameType, types.TracebackType, types.GeneratorType,
               types.CoroutineType, types.AsyncGeneratorType, io.IOBase,
               type(threading.Lock()), type(threading.RLock()))


def _suspicious_reason(obj: Any) -> str | None:
    if isinstance(obj, _SUSPICIOUS):
        return type(obj).__name__
    sock_cls = getattr(sys.modules.get("socket"), "socket", None)
    if sock_cls is not None and isinstance(obj, sock_cls):
        return "socket"
    if hasattr(type(obj), "__del__"):
        return f"{type(obj).__name__} (defines __del__; finalizer will never run)"
    return None


# PEP 683 immortal refcounts are enormous on every implementation (2**32-ish
# on 64-bit builds, saturated high values on 32-bit).  Anything above this
# threshold is not a countable reference total from real code.
_IMMORTAL_REFCNT_FLOOR = 2 ** 28

_stats_lock = threading.Lock()
_tree_calls = 0
_objects_frozen = 0
_call_sites: dict[tuple[str, int], int] = {}

#: immortalize_tree emits a ResourceWarning when one call site has frozen this
#: many times (the classic leak: freezing per-iteration data in a loop).
#: Set to 0 or None to disable.
repeat_call_warning: int | None = 5


class UnsafeToImmortalize(ValueError):
    """Raised by immortalize_tree(strict=True) BEFORE anything is frozen.

    `findings` maps a reason string to the number of offending objects.
    """

    def __init__(self, findings: dict[str, int]):
        self.findings = findings
        detail = ", ".join(f"{v}x {k}" for k, v in sorted(findings.items()))
        super().__init__(
            f"refusing to immortalize: structure contains {detail}. "
            f"Freezing these leaks OS resources, pins hidden object graphs, "
            f"or freezes synchronisation primitives; nothing was frozen.")


def available() -> bool:
    """True if this interpreter exposes the immortalization entry point.

    When False, :func:`immortalize` and :func:`immortalize_tree` are no-ops
    and :func:`is_immortal` may under-report.
    """
    return _SET is not None


def is_free_threaded() -> bool:
    """True on a free-threaded (PEP 703) build with the GIL actually off.

    Immortalization still *works* on GIL builds (PEP 683 landed in 3.12) and
    is useful there to stop refcount writes from dirtying copy-on-write pages
    in fork-based servers -- but the refcount-*contention* motivation only
    exists when this returns True.
    """
    fn = getattr(sys, "_is_gil_enabled", None)
    return not fn() if fn is not None else False


def is_immortal(obj: Any) -> bool:
    """True if `obj` is immortal (PEP 683)."""
    if _IS is not None:
        return bool(_IS(obj))
    return sys.getrefcount(obj) > _IMMORTAL_REFCNT_FLOOR


def immortalize(obj: Any) -> Any:
    """Immortalize a single object.  Returns `obj` for chaining.

    PERMANENT: the object will never be freed.  Only call this on objects
    that live for the remainder of the process.  No-op when
    :func:`available` is False.
    """
    if _SET is not None:
        _SET(obj)
    return obj


def _iter_tree(root: Any, limit: int | None = None):
    """Yield `root` and everything reachable from it, pre-order, cycle-safe.

    Shared by immortalize_tree / probe / the strict pre-flight so they all see
    exactly the same objects.  An object whose type protocol misbehaves is
    yielded but not walked into; skip-types are neither yielded nor walked.
    """
    seen = set()
    stack = [root]
    n = 0
    while stack:
        o = stack.pop()
        oid = id(o)
        if oid in seen:
            continue
        seen.add(oid)
        try:
            if isinstance(o, _SKIP):
                continue
            if limit is not None and n >= limit:
                return
            yield o
            n += 1
            if isinstance(o, _LEAF):
                continue
            if isinstance(o, dict):
                for k, v in o.items():
                    stack.append(k)
                    stack.append(v)
            elif isinstance(o, (list, tuple, set, frozenset)):
                stack.extend(o)
            # Subclasses of the builtin containers can also carry instance
            # attributes, so they fall through to the attribute walk too.
            if type(o) not in _EXACT_CONTAINERS:
                d = getattr(o, "__dict__", None)
                if isinstance(d, dict):
                    stack.append(d)
                for klass in type(o).__mro__:
                    slots = getattr(klass, "__slots__", ()) or ()
                    if isinstance(slots, str):
                        slots = (slots,)
                    for slot in slots:
                        try:
                            stack.append(getattr(o, slot))
                        except AttributeError:
                            pass
        except Exception:
            continue


def _record_tree_call(n_frozen: int) -> None:
    global _tree_calls, _objects_frozen
    try:
        f = sys._getframe(2)
        site = (f.f_code.co_filename, f.f_lineno)
    except Exception:
        site = ("<unknown>", 0)
    with _stats_lock:
        _tree_calls += 1
        _objects_frozen += n_frozen
        count = _call_sites[site] = _call_sites.get(site, 0) + 1
    if repeat_call_warning and count == repeat_call_warning:
        warnings.warn(
            f"immortalize_tree has now been called {count} times from "
            f"{site[0]}:{site[1]} -- immortalization is permanent, so "
            f"freezing per-iteration data leaks its entire object graph "
            f"every call.  Freeze process-lifetime structures once, at a "
            f"freeze point.",
            ResourceWarning, stacklevel=3)


def immortalize_tree(root: Any, *, limit: int | None = None,
                     strict: bool = False) -> int:
    """Immortalize `root` and everything reachable from it.  Returns the count.

    Walks dicts (keys and values), lists/tuples/sets/frozensets, and plain
    objects via ``__dict__`` and ``__slots__``.  Leaf types (str, bytes,
    numbers, ...) are immortalized but not walked into.  Modules, functions,
    methods and classes are skipped entirely.  Cycle-safe.

    PERMANENT and one-way: every visited object will never be freed.  Only
    call this at a freeze point on a fully built, read-only,
    process-lifetime structure.  `limit` is a hard cap: no more than `limit`
    objects are immortalized (a safety valve for unexpectedly huge graphs);
    when the cap is reached the walk stops and the structure is only
    partially immortalized.

    `strict=True` runs a validate-then-commit pre-flight: the tree is walked
    WITHOUT freezing anything, and if it contains objects that are almost
    always a mistake to freeze (open files, generators/coroutines, frames,
    tracebacks, locks, sockets, or anything defining ``__del__`` -- whose
    finalizer would never run), :class:`UnsafeToImmortalize` is raised and
    NOTHING is frozen.  Costs a second walk; recommended at freeze points.
    The two passes are not atomic: if another thread mutates the structure
    between them, added objects are frozen unvalidated -- consistent with the
    freeze-point contract (the structure must already be read-only).

    An object that misbehaves during the walk (a raising ``__dict__``
    property, exotic proxies, ...) is skipped rather than aborting the walk
    half-way through an irreversible operation.

    The classic misuse -- freezing per-iteration data in a loop -- triggers a
    ResourceWarning once one call site reaches `repeat_call_warning` calls.

    Returns 0 (and does nothing) when :func:`available` is False.
    """
    if strict:
        # Runs even when immortalization is unavailable, so a dev box on a
        # build without the symbol still gets the lint instead of hitting
        # UnsafeToImmortalize for the first time in production.
        findings: dict[str, int] = {}
        for o in _iter_tree(root, limit):
            reason = _suspicious_reason(o)
            if reason is not None:
                findings[reason] = findings.get(reason, 0) + 1
        if findings:
            raise UnsafeToImmortalize(findings)
    if _SET is None:
        return 0
    n = 0
    for o in _iter_tree(root, limit):
        _SET(o)
        n += 1
    _record_tree_call(n)
    return n


def stats() -> dict[str, Any]:
    """Running totals of what immortalize_tree has frozen, and from where.

    Zero overhead except one lock/counter update per immortalize_tree call
    (freeze points, never hot paths).  Single-object :func:`immortalize`
    calls are not tracked.
    """
    with _stats_lock:
        sites = {f"{fn}:{ln}": c for (fn, ln), c in _call_sites.items()}
        return {
            "tree_calls": _tree_calls,
            "objects_frozen": _objects_frozen,
            "call_sites": sites,
        }


def probe(root: Any, *, sample: int | None = 100_000) -> dict[str, Any]:
    """Retrospective sharing report for a structure -- free, read-only.

    Free-threaded CPython latches state bits in an object's shared refcount
    field when it is touched by a non-owner thread (weakrefs latch it too).
    This walks up to `sample` objects and reads that breadcrumb -- no copies,
    no extra threads, under a microsecond per object (~70 ms per 100k).

    CALL IT FROM THE THREAD THAT BUILT THE STRUCTURE.  The probe's own walk
    takes references to every object it inspects; probed from any other
    thread, those are foreign references and every object reports (false)
    shared evidence.

    Latch persistence varies by access path: subscript (``d[k]``, ``lst[i]``),
    attribute reads and list iteration latch permanently; dict-view iteration
    (``values()``/``items()``) only shows evidence while the foreign
    references are still held -- so probing after workers have exited
    under-reports.  Probe while workers are running (from the owner thread)
    for the truest picture:

      * ``immortal_fraction``  -- already frozen
      * ``shared_evidence_fraction`` -- non-immortal objects whose header
        shows cross-thread refcounting (or weakrefs; conservative over-report)

    Run it after your workers have exercised the structure: a high
    shared-evidence fraction on a mortal structure means its refcount words
    are being written from multiple threads -- the precondition for the
    contention this package removes.

    Only meaningful on 64-bit free-threaded builds; elsewhere returns
    ``{"supported": False, ...}``.
    """
    if not (is_free_threaded() and ctypes.sizeof(ctypes.c_void_p) == 8):
        return {"supported": False,
                "reason": "needs a 64-bit free-threaded build"}
    n = imm = evid = 0
    for o in _iter_tree(root, sample):
        n += 1
        if is_immortal(o):
            imm += 1
        elif ctypes.c_int64.from_address(id(o) + 16).value != 0:
            evid += 1
    mortal = n - imm
    return {
        "supported": True,
        "objects_sampled": n,
        "immortal": imm,
        "immortal_fraction": (imm / n) if n else 0.0,
        "shared_evidence": evid,
        "shared_evidence_fraction": (evid / mortal) if mortal else 0.0,
    }


# pluribus pipeline compatibility: original vendored name for is_free_threaded
gil_disabled = is_free_threaded
