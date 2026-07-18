#!/usr/bin/env python3
"""LUT INIT bit-order convention — regression guard for #63.

A MachXO2 LUT INIT is stored MSB-first: the 16-char string s has
``s[k] = f(15 - k)``, so the truth value for input index ``idx = a+2b+4c+8d`` is
``f(idx) = s[15 - idx]`` and the integer form is ``int(s, 2)`` (bit p = f(p)).
A stray reversal (``int(s[::-1], 2)`` / indexing the MSB-first string as if it
were LSB-first) evaluates ``f(~x)`` — every input complemented — silently
swapping INV<->BUF, AND<->NOR, OR<->NAND (XOR/XNOR are complement-invariant and
hide the bug). That regression (#63) made recovered logic wrong for every
non-symmetric LUT and was invisible to the self-consistency LEC.

Anchor: the fuzz target ``re_edge_pin64`` (``t <= ~t``) has a single-input LUT
whose INIT is exactly ``0000000011111111`` and which MUST be an inverter — that
observation fixes the convention these tests encode.

These test the two MSB-first entry points: ``classify_lut`` (the structured-fn
path emit uses) and ``_lut_init_to_case`` (the COMBO emit path, which reverses
to LSB-first before the LSB-first ``_simplify_lut`` helper).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from load import classify_lut                       # noqa: E402
from verilog import _lut_init_to_case               # noqa: E402


def _build_msb_first(f):
    """MSB-first INIT string for truth function f(idx): string[k] = f(15 - k)."""
    return "".join(str(f(15 - k) & 1) for k in range(16))


def _emit_expr(init_msb, a, b, c, d):
    """RHS expression _lut_init_to_case emits for a simplifiable (<=2-live) LUT."""
    lines = _lut_init_to_case(init_msb, "z", a, b, c, d)
    assert len(lines) == 1, lines                     # simplifiable -> single assign
    return lines[0].split("=", 1)[1].strip().rstrip(";").strip()


# idx bit weights: a=1, b=2, c=4, d=8
_A = lambda i: i & 1
_B = lambda i: (i >> 1) & 1
_C = lambda i: (i >> 2) & 1
_D = lambda i: (i >> 3) & 1

# (truth function, expected classify tag, expected emitted expr, nets a,b,c,d)
_CASES = [
    (lambda i: _A(i),                 "BUF(a)",     "x",        ("x", "NC", "NC", "NC")),
    (lambda i: _A(i) ^ 1,             "INV(a)",     "~x",       ("x", "NC", "NC", "NC")),
    (lambda i: _D(i) ^ 1,             "INV(d)",     "~x",       ("NC", "NC", "NC", "x")),
    (lambda i: _A(i) & _B(i),         "AND(a,b)",   "x & y",    ("x", "y", "NC", "NC")),
    (lambda i: _A(i) | _B(i),         "OR(a,b)",    "x | y",    ("x", "y", "NC", "NC")),
    (lambda i: _A(i) ^ _B(i),         "XOR(a,b)",   "x ^ y",    ("x", "y", "NC", "NC")),
    (lambda i: (_A(i) & _B(i)) ^ 1,   "NAND(a,b)",  "~(x & y)", ("x", "y", "NC", "NC")),
    (lambda i: (_A(i) | _B(i)) ^ 1,   "NOR(a,b)",   "~(x | y)", ("x", "y", "NC", "NC")),
    (lambda i: (_A(i) ^ _B(i)) ^ 1,   "XNOR(a,b)",  "~(x ^ y)", ("x", "y", "NC", "NC")),
]


def test_inverter_anchor():
    """re_edge_pin64 ground truth: 0000000011111111 is an inverter, not a buffer."""
    assert classify_lut("0000000011111111") == "INV(d)"
    assert _emit_expr("0000000011111111", "NC", "NC", "NC", "x") == "~x"


def test_classify_lut_convention():
    for f, want_tag, _expr, _nets in _CASES:
        s = _build_msb_first(f)
        assert classify_lut(s) == want_tag, (want_tag, s, classify_lut(s))


def test_emit_convention():
    for f, _tag, want_expr, (a, b, c, d) in _CASES:
        s = _build_msb_first(f)
        assert _emit_expr(s, a, b, c, d) == want_expr, (want_expr, s)


def test_no_stray_reversal():
    """A buffer and an inverter must be distinguished (guards the #63 swap)."""
    buf = _build_msb_first(lambda i: _A(i))
    inv = _build_msb_first(lambda i: _A(i) ^ 1)
    assert classify_lut(buf) == "BUF(a)"
    assert classify_lut(inv) == "INV(a)"


def test_localparam_fallback_is_msb_first():
    """A >2-live LUT falls to a localparam literal — it must be the raw MSB-first INIT."""
    s = _build_msb_first(lambda i: _A(i) & _B(i) & _C(i))   # 3 live -> not simplifiable
    lines = _lut_init_to_case(s, "z", "x", "y", "w", "NC")
    assert any(f"16'b{s}" in ln for ln in lines), lines
