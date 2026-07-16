#!/usr/bin/env python3
"""Probe: figure out the free-threaded PyObject refcount layout and verify we
can immortalize an object + enable deferred refcounting, on whatever interpreter
runs this.  Prints the discovered offsets so the benchmark can reuse them.

NOTE: this offset-based header write is a diagnostic ONLY.  It is intentionally
kept to document the layout, but it is NOT the way to immortalize in
production: it writes ob_ref_local/ob_ref_shared but skips ob_tid and the
GC-untrack that CPython's own _Py_SetImmortal performs, and the offsets are
build-specific.  The production path is `ft_immortal` (repo root), which calls
the exported _Py_SetImmortal via ctypes -- correct, complete, offset-free.
"""
import ctypes
import sys

print(f"python {sys.version}")
print(f"getrefcount(None) = {sys.getrefcount(None)}  (0x{sys.getrefcount(None):x})")

# --- inspect None's header bytes to locate ob_ref_local / ob_ref_shared -----
none_addr = id(None)
buf = (ctypes.c_ubyte * 40).from_address(none_addr)
raw = bytes(buf)
print("None header bytes (first 40):", raw.hex(" "))

# Interpret candidate fields under the assumed free-threaded layout:
#   ob_tid u64 @0, ob_flags u16 @8, ob_mutex u8 @10, ob_gc_bits u8 @11,
#   ob_ref_local u32 @12, ob_ref_shared i64 @16, ob_type ptr @24
def rd_u32(off):
    return ctypes.c_uint32.from_address(none_addr + off).value
def rd_i64(off):
    return ctypes.c_int64.from_address(none_addr + off).value

print(f"@12 ob_ref_local(u32) = {rd_u32(12)}  (0x{rd_u32(12):x})")
print(f"@16 ob_ref_shared(i64) = {rd_i64(16)}")
print(f"@24 ptr = 0x{ctypes.c_uint64.from_address(none_addr+24).value:x}  "
      f"(type(None) id = 0x{id(type(None)):x})")

# --- deferred refcount lever ------------------------------------------------
fn = getattr(ctypes.pythonapi, "PyUnstable_Object_EnableDeferredRefcount", None)
print("\nEnableDeferredRefcount present:", fn is not None)
if fn is not None:
    fn.argtypes = [ctypes.py_object]
    fn.restype = ctypes.c_int
    fs = frozenset({1, 2, 3})
    r = fn(fs)
    print(f"  EnableDeferredRefcount(frozenset) -> {r}")
    lst = [1, 2, 3]
    print(f"  EnableDeferredRefcount(list)      -> {fn(lst)}")
    d = {"a": 1}
    print(f"  EnableDeferredRefcount(dict)      -> {fn(d)}")
    ba = bytearray(4)
    print(f"  EnableDeferredRefcount(bytearray) -> {fn(ba)}")
    tup = (1, 2, 3)
    print(f"  EnableDeferredRefcount(tuple)     -> {fn(tup)}")

# --- immortalization by copying None's ref fields ---------------------------
IMMORTAL_LOCAL = rd_u32(12)
IMMORTAL_SHARED = rd_i64(16)

def immortalize(obj):
    addr = id(obj)
    ctypes.c_uint32.from_address(addr + 12).value = IMMORTAL_LOCAL
    ctypes.c_int64.from_address(addr + 16).value = IMMORTAL_SHARED

target = ["hot", "shared", "data"]
before = sys.getrefcount(target)
immortalize(target)
after = sys.getrefcount(target)
print(f"\nimmortalize(list): getrefcount {before} -> {after} "
      f"(immortal sentinel = {sys.getrefcount(None)})")
# stress: many incref/decref should not change it
for _ in range(1000):
    x = target
    del x
print(f"  after 1000 ref churn: getrefcount = {sys.getrefcount(target)}")
print("  immortal OK" if sys.getrefcount(target) == sys.getrefcount(None)
      else "  immortal FAILED")
