#!/usr/bin/env python3
"""Anlogic EG4 round-trip LEC harness — Pluribus issue #76.

The Anlogic adapter for the unified verification skeleton.  Drives the vendor
Tang Dynasty tool (``td``) to build a reference bitstream from a known source,
decodes it with ``scripts/anlogic_unpack.py``, lifts it with the Anlogic lifter
and checks that the recovered LUT INITs classify to the correct logic functions.

Because Anlogic routing is not yet decoded (``arcs`` stay empty, see lifters/
anlogic_lift.py), the only available verification is a **FN check**: the truth
table of every recovered (non-constant) LUT is classified and compared against
the function the source implements.  For single-LUT combinational designs this
is a genuine (if small) LEC — the LUT *is* the whole design.

Flow (per design)
-----------------
  source.v
    ─ yosys synth_anlogic ──────────────────────────────────── top.json
    ─ TD ``td`` (tcl script) synth+PnR+bitgen ──────────────── impl/pnr/top.bit
    ─ scripts/anlogic_unpack.py --db $ANLOGIC_DB ───────────── top.anloconfig
    ─ lifters/anlogic_lift.py ──────────────────────────────── LUT INITs
    ─ FN check vs expected function set                         PASS / FAIL

Verdict levels
--------------
  PASS          recovered LUT functions match the source (FN check)
  FAIL          recovered LUT functions diverge from the source
  VENDOR-ERR    TD build failed (license / install / bad CST)
  DECODE-ERR    anlogic_unpack.py failed or returned empty config
  SKIP-FN       design has no expected FN set (registered designs — verdict is
                informational only, reports what was recovered)

The TD tool is NOT included in the repo; it must be installed separately.
The fuse DB (``$ANLOGIC_DB``) is decoded from the TD arch DB by
``scripts/anlogic_dbdecode.py`` (see boards/fnirsi-eg4s20/README.md).

Environment
-----------
  TD_HOME         root of the TD installation.  The binary is at
                  $TD_HOME/bin/td.  Default: the bundled sources/tang-dynasty
                  td_rhel release.
  TD_LICENSE      path to the Anlogic node-locked .lic (default:
                  sources/tang-dynasty/Anlogic_202003.lic).
  ANLOGIC_DB      decoded fuse DB directory (from anlogic_dbdecode.py).
                  Required for LUT-INIT recovery.  If absent the FN check is
                  skipped and the harness only validates the build/unpack flow.
  OSS_CAD         oss-cad-suite bin dir (yosys).  Default /home/dan/opt/oss-cad-suite/bin.
  PY_PLURIBUS     free-threaded pluribus interpreter.  Default python3.15t.

Usage::

    python3 scripts/anlogic_roundtrip.py
    python3 scripts/anlogic_roundtrip.py --only xor and
    python3 scripts/anlogic_roundtrip.py --keep
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ for verify_common
from load import classify_lut                    # noqa: E402
from lifters.anlogic_lift import AnlogicLift     # noqa: E402
from verify_common import (                      # noqa: E402  (#76)
    run_cmd, is_2to1_mux, classify_fn)

# ── Tool paths ───────────────────────────────────────────────────────────────

_SRC_TD = (REPO / "sources" / "tang-dynasty" / "td_rhel" /
           "TD_RELEASE_March2020_r4.6.4" / "bin" / "td")
TD_HOME = Path(os.environ.get("TD_HOME",
               str(_SRC_TD.parent.parent)))
TD_BIN  = TD_HOME / "bin" / "td"
TD_LICENSE = Path(os.environ.get(
    "TD_LICENSE",
    str(REPO / "sources" / "tang-dynasty" / "Anlogic_202003.lic")))
ANLOGIC_DB = os.environ.get("ANLOGIC_DB", "")
OSS_CAD    = os.environ.get("OSS_CAD", "/home/dan/opt/oss-cad-suite/bin")
PY         = os.environ.get("PY_PLURIBUS", "python3.15t")

# ── Target device ─────────────────────────────────────────────────────────────
# EG4S20BG256 (Sipeed Lichee Tang / FNIRSI 2D15P).  BGA256 pin designators
# for safe user-IO (non-JTAG / non-config banks).  These can be overridden
# per-design via the Design.pins dict.
DEVICE   = "EG4S20BG256"
FAMILY   = "eagle_s20"
# A small set of known-good BGA256 IO ball designators (BANK2, LVCMOS33).
# Override ANLOGIC_PINS env to use different balls if the defaults conflict.
_DEFAULT_PINS = {
    "clk": "P7", "rst": "P6",
    "a": "N5", "b": "M5", "s": "L5",
    "q": "K5", "q0": "K5", "q1": "J5", "q2": "H5",
    "st0": "K5", "st1": "J5", "st2": "H5",
}


# ── Design corpus ─────────────────────────────────────────────────────────────
class Design:
    def __init__(self, name, verilog, ports, expect_fns=None, min_ffs=0):
        self.name = name
        self.verilog = verilog
        self.ports = ports          # port-name -> pin-key in _DEFAULT_PINS
        self.expect_fns = expect_fns or []
        self.min_ffs = min_ffs


DESIGNS = [
    Design("xor",
           "module top (input a, input b, output q);\n"
           "  assign q = a ^ b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["XOR"]),
    Design("and",
           "module top (input a, input b, output q);\n"
           "  assign q = a & b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["AND"]),
    Design("or",
           "module top (input a, input b, output q);\n"
           "  assign q = a | b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["OR"]),
    Design("inv",
           "module top (input a, output q);\n"
           "  assign q = ~a;\nendmodule\n",
           {"a": "a", "q": "q"},
           expect_fns=["INV"]),
    Design("mux",
           "module top (input a, input b, input s, output q);\n"
           "  assign q = s ? b : a;\nendmodule\n",
           {"a": "a", "b": "b", "s": "s", "q": "q"},
           expect_fns=["MUX"]),
    Design("anchor",
           "module top (input clk, input a, input b,\n"
           "            output reg q0, output reg q1, output reg q2);\n"
           "  always @(posedge clk) begin\n"
           "    q0 <= a ^ b; q1 <= a & b; q2 <= a | b;\n"
           "  end\nendmodule\n",
           {"clk": "clk", "a": "a", "b": "b",
            "q0": "q0", "q1": "q1", "q2": "q2"},
           expect_fns=["XOR", "AND", "OR"], min_ffs=3),
    Design("fsm",
           "module top (input clk, input rst, output reg [2:0] st);\n"
           "  always @(posedge clk)\n"
           "    if (rst) st <= 3'b001; else st <= {st[1:0], st[2]};\n"
           "endmodule\n",
           {"clk": "clk", "rst": "rst",
            "st[0]": "st0", "st[1]": "st1", "st[2]": "st2"},
           min_ffs=3),
]


# ── Tang Dynasty plumbing ──────────────────────────────────────────────────────

def _td_env():
    """Minimal environment for the vendor ``td`` binary."""
    e = {
        "HOME":    os.environ.get("HOME", "/root"),
        "PATH":    "/usr/bin:/bin",
        "TD_HOME": str(TD_HOME),
    }
    if TD_LICENSE.exists():
        e["ANLOGIC_LICENSE_FILE"] = str(TD_LICENSE)
    return e


def vendor_build(d: Design, wd: Path, log):
    """Run TD synth+PnR+bitgen; return (bit_path, error_string)."""
    (wd / "top.v").write_text(d.verilog)

    cst_lines = []
    for port, pin_key in d.ports.items():
        pin = _DEFAULT_PINS.get(pin_key, pin_key)
        cst_lines.append(f'IO_LOC "{port}" {pin};')
        cst_lines.append(f'IO_PORT "{port}" IO_TYPE=LVCMOS33;')
    (wd / "top.cst").write_text("\n".join(cst_lines) + "\n")

    # TD 4.x headless Tcl flow
    (wd / "build.tcl").write_text(
        f"open_project -name proj -dir .\n"
        f"set_device {DEVICE} -device_version B\n"
        "add_file -type verilog top.v\n"
        "create_constraint -type cst top.cst\n"
        "set_option -output_base_name top\n"
        "set_option -top_module top\n"
        "run all\n")

    log.write(f"\n=== td build: {d.name} ===\n")
    rc, out = run_cmd([str(TD_BIN), "build.tcl"], wd,
                      env=_td_env(), log=log, full_env=True)
    log.write(out[-4000:] if len(out) > 4000 else out)

    bit = wd / "impl" / "pnr" / "top.bit"
    if rc != 0 or not bit.exists():
        return None, f"td rc={rc} (bit missing)"
    return bit, ""


# ── Decode ────────────────────────────────────────────────────────────────────

def decode(bit: Path, wd: Path, log):
    """Decode with anlogic_unpack.py; return path to .anloconfig or None."""
    gwc = wd / "top.anloconfig"
    if gwc.exists():
        gwc.unlink()
    cmd = [PY, str(REPO / "scripts" / "anlogic_unpack.py"),
           str(bit), str(gwc), "--device", DEVICE]
    if ANLOGIC_DB:
        cmd += ["--db", ANLOGIC_DB]
    rc, out = run_cmd(cmd, wd, log=log)
    log.write(out[-2000:] if len(out) > 2000 else out)
    return gwc if rc == 0 and gwc.exists() else None


# ── LUT classification ────────────────────────────────────────────────────────

def lift_and_classify(anloconfig: Path):
    """Return classified non-constant LUT function heads from a .anloconfig."""
    lift = AnlogicLift(DEVICE)
    pc   = lift.parse_config(str(anloconfig))
    d    = lift.recover_netlist(pc)
    fns  = []
    for lt in d.luts:
        init = lt.get("init", "0" * 16)
        if set(init) in ({"0"}, {"1"}):
            continue
        # Pad sub-16-bit inits (EG4 uses 16-bit LUT4 truth tables directly)
        if len(init) < 16:
            while len(init) < 16:
                init = init + init
            init = init[:16]
        fns.append(classify_fn(init))
    return fns, len(d.ffs)


# ── Per-design verdict ────────────────────────────────────────────────────────

def run_design(d: Design, root: Path, log):
    wd = root / d.name
    wd.mkdir(parents=True, exist_ok=True)
    log.write(f"\n{'='*60}\n=== {d.name} ===\n{'='*60}\n")

    res = {"name": d.name}

    bit, err = vendor_build(d, wd, log)
    if bit is None:
        res.update(verdict="VENDOR-ERR", detail=err)
        return res

    anloconfig = decode(bit, wd, log)
    if anloconfig is None:
        res.update(verdict="DECODE-ERR", detail="anlogic_unpack failed")
        return res

    if not ANLOGIC_DB:
        res.update(verdict="DECODE-ERR",
                   detail="ANLOGIC_DB not set — cannot recover LUT INITs "
                          "(run scripts/anlogic_dbdecode.py first)")
        return res

    fns, nff = lift_and_classify(anloconfig)
    have = Counter(fns)

    if not d.expect_fns and not d.min_ffs:
        # informational only (registered design, no expected FN set)
        res.update(verdict="SKIP-FN",
                   detail=f"recovered LUT fns={sorted(have.elements())} FFs={nff}")
        return res

    ok = True
    parts = [f"LUT fns={sorted(have.elements())} FFs={nff}"]

    if d.expect_fns:
        want = Counter(d.expect_fns)
        missing = want - have
        fn_ok = not missing
        ok = ok and fn_ok
        parts.append(
            f"expected {sorted(want.elements())} "
            f"{'ok' if fn_ok else f'MISSING {sorted(missing.elements())}'}")

    if d.min_ffs:
        ff_ok = nff >= d.min_ffs
        ok = ok and ff_ok
        parts.append(f"FFs>={d.min_ffs}:{'ok' if ff_ok else 'NO'}")

    res.update(verdict="PASS" if ok else "FAIL",
               detail="; ".join(parts))
    return res


# ── Driver ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="run only these designs by name")
    ap.add_argument("--keep", action="store_true", help="keep the work dir")
    ap.add_argument("--log",
                    default=str(REPO / "tmp" / "anlogic_roundtrip.log"))
    args = ap.parse_args()

    (REPO / "tmp").mkdir(exist_ok=True)
    log = open(args.log, "w")

    if not TD_BIN.exists():
        sys.exit(
            f"ERROR: TD binary not found at {TD_BIN}\n"
            f"Set TD_HOME= or install Tang Dynasty to that path.\n"
            f"  Expected: sources/tang-dynasty/td_rhel/TD_RELEASE_March2020_r4.6.4/bin/td")

    if not shutil.which(f"{OSS_CAD}/yosys"):
        sys.exit(f"ERROR: yosys not found in OSS_CAD={OSS_CAD}")

    print(f"[td]     {TD_BIN}")
    print(f"[device] {DEVICE}  family={FAMILY}")
    if ANLOGIC_DB:
        print(f"[db]     {ANLOGIC_DB}")
    else:
        print("[db]     NOT SET — LUT-INIT recovery disabled "
              "(set ANLOGIC_DB=tmp/anlogic/db)")
    if TD_LICENSE.exists():
        print(f"[lic]    {TD_LICENSE}")
    else:
        print(f"[lic]    NOT FOUND at {TD_LICENSE} — vendor builds will fail")

    designs = [d for d in DESIGNS if not args.only or d.name in args.only]
    root = Path(tempfile.mkdtemp(
        prefix="anlogic_rt_", dir=str(REPO / "tmp")))

    print(f"\n  {'design':<8} {'verdict':<12} detail")
    print("  " + "-" * 72)

    results = []
    for d in designs:
        r = run_design(d, root, log)
        results.append(r)
        print(f"  {d.name:<8} {r['verdict']:<12} {r.get('detail', '')[:80]}")

    n = len(results)
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    n_err  = sum(1 for r in results
                 if r["verdict"] in ("VENDOR-ERR", "DECODE-ERR"))
    n_built = n - n_err
    print(f"\n  {n_pass}/{n_built} designs PASS  ({n_err} build/decode errors)")
    print(f"  log: {args.log}")

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"  work dir kept: {root}")

    log.close()
    sys.exit(0 if n_pass == n_built and n_err == 0 else 1)


if __name__ == "__main__":
    main()
