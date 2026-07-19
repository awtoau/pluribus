#!/usr/bin/env python3
"""GOWIN differential-fuzz harness — vendor-flow cross-check (issue #66).

The VENDOR-flow analogue of scripts/gowin_lec.py.  Where gowin_lec.py drives the
OPEN flow (yosys synth_gowin -> nextpnr-himbaechel -> gowin_pack), this drives
the *vendor* Gowin EDA (`gw_sh`) to produce the reference `.fs`, then validates
the pluribus decode against THREE independent oracles:

    source.v ── gw_sh (GowinSynthesis + place&route + bitgen) ──► vendor top.fs
                                                                       │
        (1) our decode  : scripts/gowin_unpack.py (apycula chipdb) ────┤
        (2) apicula ref : apycula.gowin_unpack -o  (apicula's own codegen)
        (3) vendor truth: impl/gwsynthesis/top.vg (the vendor's own netlist)
                                                                       │
        ORACLE B  our-decode <-> apicula-decode : must MATCH in the cell census
                  — proves pluribus is a *faithful* apycula front end (any drift
                  here is a pluribus-side bug, not a chipdb gap).
        ORACLE A  recovered-logic <-> source : the pluribus lifter recovers the
                  used LUT logic; its z_used LUTs are classified (XOR/AND/OR/...)
                  and compared to the source's expected function set.  The
                  vendor's default-programmed *unused* fabric shows up as phantom
                  cells (see FINDING) which are quantified as the decode gap.

FINDING (GW1N-2, characterised by this harness)
-----------------------------------------------
The Gowin vendor bitstream writes a *default fuse pattern* into every UNUSED
slice and IO pad.  apycula's reverse-engineered GW1N-2 chipdb cannot tell those
defaults apart from real cells, so a near-empty design decodes with ~1726
phantom `DFFS` and ~118 phantom `IBUF` cells.  Open-flow (gowin_pack) bitstreams
zero their unused resources, so they decode clean — which is why gowin_lec.py
passes 7/7 while the raw vendor netlist cannot be LEC'd wholesale.  pluribus's
decoder reproduces apycula's decode EXACTLY (oracle B always matches), so the
gap lives in the shared chipdb, not in pluribus.  The *used* logic is still
recovered correctly: for combinational designs the single z_used LUT classifies
to the exact source function (oracle A logic-recovery PASS).

Environment
-----------
  GOWINHOME              vendor EDA root (default /mnt/2tb/gowin), has IDE/bin/gw_sh
  GOWIN_LICENSE          local node-locked .lic (default $GOWINHOME/gowin.lic)
  GOWIN_FREETYPE_PRELOAD libfreetype to LD_PRELOAD around the gw_sh font ABI
                         mismatch (default /usr/lib64/libfreetype.so.6.20.6)
  APICULA_PYTHONPATH     apycula install carrying the GW1N-2 chipdb
                         (default /mnt/2tb/git_mirror/YosysHQ/apicula)
  PLURIBUS_GOWIN_PYTHON  interpreter with apycula (default oss-cad-suite py3bin)
  QT_QPA_PLATFORM        offscreen (gw_sh is headless)

The one-time host setup (license path in the vendor's gwlicense.ini) is applied
automatically when GOWIN_LICENSE points at a readable .lic — see ensure_license().

Usage:
    python3.15t scripts/gowin_fuzz.py                 # full sweep, GW1N-2
    python3.15t scripts/gowin_fuzz.py --only xor and  # a subset
    python3.15t scripts/gowin_fuzz.py --keep          # keep the work dir
    python3.15t scripts/gowin_fuzz.py --device GW1N-1 # (vendor data must exist)
"""

import argparse
import json
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
from load import classify_lut                      # noqa: E402
from lifters.gowin_lift import GowinLift            # noqa: E402

GOWINHOME = os.environ.get("GOWINHOME", "/mnt/2tb/gowin")
GW_SH = str(Path(GOWINHOME) / "IDE" / "bin" / "gw_sh")
GWLIC_INI = Path(GOWINHOME) / "IDE" / "bin" / "gwlicense.ini"
GOWIN_LICENSE = os.environ.get("GOWIN_LICENSE", str(Path(GOWINHOME) / "gowin.lic"))
FREETYPE = os.environ.get("GOWIN_FREETYPE_PRELOAD",
                          "/usr/lib64/libfreetype.so.6.20.6")
QT_PLUGINS = Path(GOWINHOME) / "IDE" / "plugins" / "qt"

APICULA_PP = os.environ.get("APICULA_PYTHONPATH",
                            "/mnt/2tb/git_mirror/YosysHQ/apicula")
GOWIN_PY = os.environ.get(
    "PLURIBUS_GOWIN_PYTHON",
    "/home/dan/opt/oss-cad-suite/py3bin/python3")

# ── target device (vendor part / apycula chipdb / package) ────────────────────
# GW1N-2 (== GW1N-1P5C die) is issue #66's subject and is the family whose device
# data ships with this vendor EDA install.  QFN48 GPIO pins picked to avoid the
# JTAG / config-dedicated pads (3,8-11,13,28,29,34,35 ...).
DEVICES = {
    "GW1N-2": dict(part="GW1N-LV2QN48C6/I5", name="GW1N-2", package="QFN48",
                   pins=dict(clk=31, a=20, b=21, s=22, rst=22,
                             q0=23, q1=24, q2=27, q=23,
                             st0=23, st1=24, st2=27)),
    # GW1N-1 kept for completeness; the vendor EDA here has NO GW1N-1 device
    # data, so vendor builds will fail cleanly and be reported as VENDOR-ERR.
    "GW1N-1": dict(part="GW1N-LV1QN48C6/I5", name="GW1N-1", package="QFN48",
                   pins=dict(clk=10, a=11, b=13, s=8, rst=11,
                             q0=5, q1=6, q2=7, q=5, st0=5, st1=6, st2=7)),
}


# ── design corpus (mirrors gowin_lec.py) ──────────────────────────────────────
class Design:
    def __init__(self, name, verilog, ports, expect_fns=None, min_ffs=0,
                 combinational=False):
        self.name = name
        self.verilog = verilog
        self.ports = ports                 # port-name -> pin-key in DEVICES[...]["pins"]
        self.expect_fns = expect_fns or []
        self.min_ffs = min_ffs
        self.combinational = combinational


DESIGNS = [
    Design("xor",
           "module top (input a, input b, output q);\n"
           "  assign q = a ^ b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["XOR"], combinational=True),
    Design("and",
           "module top (input a, input b, output q);\n"
           "  assign q = a & b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["AND"], combinational=True),
    Design("or",
           "module top (input a, input b, output q);\n"
           "  assign q = a | b;\nendmodule\n",
           {"a": "a", "b": "b", "q": "q"},
           expect_fns=["OR"], combinational=True),
    Design("inv",
           "module top (input a, output q);\n"
           "  assign q = ~a;\nendmodule\n",
           {"a": "a", "q": "q"},
           expect_fns=["INV"], combinational=True),
    Design("mux",
           "module top (input a, input b, input s, output q);\n"
           "  assign q = s ? b : a;\nendmodule\n",
           {"a": "a", "b": "b", "s": "s", "q": "q"},
           expect_fns=["MUX"], combinational=True),
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


# ── vendor licence / gw_sh plumbing ───────────────────────────────────────────
def ensure_license(log):
    """Point the vendor gwlicense.ini at the local node-locked .lic.

    gw_sh reads `<bindir>/gwlicense.ini` and parses lic="...": a `host:port`
    value queries a (here unreachable) license server, any other value is
    treated as a local .lic file (check_from_local).  We rewrite the ini to the
    local file iff it is not already pointing at a readable local .lic.  A single
    .orig backup of the vendor default is kept.
    """
    if not os.path.exists(GOWIN_LICENSE):
        return (False, f"no local license at GOWIN_LICENSE={GOWIN_LICENSE}")
    cur = ""
    if GWLIC_INI.exists():
        m = re.search(r'lic\s*=\s*"(.*)"', GWLIC_INI.read_text())
        cur = m.group(1) if m else ""
    if cur == GOWIN_LICENSE and os.path.exists(cur):
        return (True, f"gwlicense.ini already -> {cur}")
    if not GWLIC_INI.parent.exists():
        return (False, f"vendor bin dir missing: {GWLIC_INI.parent}")
    backup = GWLIC_INI.with_suffix(".ini.orig")
    if GWLIC_INI.exists() and not backup.exists():
        shutil.copy2(GWLIC_INI, backup)
        log.write(f"[license] backed up {GWLIC_INI} -> {backup}\n")
    GWLIC_INI.write_text(f'[license]\nlic="{GOWIN_LICENSE}"\n')
    log.write(f"[license] set {GWLIC_INI} -> {GOWIN_LICENSE}\n")
    return (True, f"gwlicense.ini set -> {GOWIN_LICENSE}")


def gw_env(xdg):
    """Clean, minimal env for gw_sh: the bundled Qt 5.15.14 mixes badly with the
    host's Qt 5.15.18 plugins, so we run env-clean and force the bundled platform
    plugin dir; LD_PRELOAD works around the font-lib symbol mismatch."""
    return {
        "HOME": os.environ.get("HOME", "/root"),
        "PATH": "/usr/bin:/bin",
        "GOWINHOME": GOWINHOME,
        "LD_PRELOAD": FREETYPE,
        "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        "QT_QPA_PLATFORM_PLUGIN_PATH": str(QT_PLUGINS / "platforms"),
        "QT_PLUGIN_PATH": str(QT_PLUGINS),
        "XDG_RUNTIME_DIR": str(xdg),
    }


def _run(cmd, cwd, env=None, log=None, full_env=False):
    e = env if full_env else {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=str(cwd), env=e, capture_output=True, text=True)
    if log is not None:
        log.write(f"\n$ {' '.join(str(c) for c in cmd)}\n{r.stdout}{r.stderr}")
    return r.returncode, r.stdout + r.stderr


def vendor_build(d: Design, dev, wd: Path, xdg: Path, log):
    """Drive gw_sh: source.v (+ .cst) -> impl/pnr/top.fs.  Returns (fs, err)."""
    (wd / "top.v").write_text(d.verilog)
    cst = "".join(f'IO_LOC "{port}" {dev["pins"][key]};\n'
                  for port, key in d.ports.items())
    (wd / "top.cst").write_text(cst)
    (wd / "build.tcl").write_text(
        f'set_device -name {dev["name"]} {dev["part"]}\n'
        "add_file top.v\nadd_file top.cst\n"
        "set_option -output_base_name top\nset_option -top_module top\n"
        "run all\n")
    xdg.mkdir(parents=True, exist_ok=True)
    rc, _ = _run([GW_SH, "build.tcl"], wd, env=gw_env(xdg), log=log,
                 full_env=True)
    fs = wd / "impl" / "pnr" / "top.fs"
    if rc != 0 or not fs.exists():
        return None, f"gw_sh run all rc={rc} (fs missing)"
    return fs, ""


# ── decode: pluribus (our) + apicula (reference) ──────────────────────────────
def our_decode(fs: Path, dev, wd: Path, log):
    gwc = wd / "top.gwconfig"
    if gwc.exists():
        gwc.unlink()
    env = {**os.environ, "PYTHONPATH": APICULA_PP}
    rc, _ = _run([GOWIN_PY, str(REPO / "scripts" / "gowin_unpack.py"),
                  str(fs), str(gwc), "-d", dev["name"], "-p", dev["package"]],
                 wd, env=env, log=log)
    return (gwc if rc == 0 and gwc.exists() else None)


def apicula_decode(fs: Path, dev, wd: Path, log):
    refv = wd / "apicula_ref.v"
    if refv.exists():
        refv.unlink()
    env = {**os.environ, "PYTHONPATH": APICULA_PP}
    rc, _ = _run([GOWIN_PY, "-m", "apycula.gowin_unpack",
                  "-d", dev["name"], "-o", str(refv), str(fs)],
                 wd, env=env, log=log)
    return (refv if rc == 0 and refv.exists() else None)


# ── cell census (the common comparison currency) ──────────────────────────────
_PRIM_RE = re.compile(
    r"\b(LUT[1-4]|DFF[NSRPCE]*|IBUF|OBUF|IOBUF|TBUF|ALU|MUX2[A-Z0-9_]*)\b")


def census_gwconfig(gwc: Path):
    lut = dff = ibuf = obuf = iobuf = alu = 0
    for ln in gwc.read_text().splitlines():
        if ln.startswith("lut "):
            init = ln.split()[4]
            if set(init) not in ({"0"}, {"1"}):
                lut += 1
        elif ln.startswith("dff "):
            dff += 1
        elif ln.startswith("iob "):
            mode = ln.split()[4]
            if "IOBUF" in mode:
                iobuf += 1
            elif "OBUF" in mode:
                obuf += 1
            else:
                ibuf += 1
        elif ln.startswith("hardip ") and " ALU " in ln:
            alu += 1
    return dict(lut=lut, dff=dff, ibuf=ibuf, obuf=obuf, iobuf=iobuf, alu=alu)


def census_refv(refv: Path):
    """Cell census from apicula's own reference Verilog (instantiations)."""
    txt = refv.read_text()
    lut = dff = ibuf = obuf = iobuf = alu = 0
    for tok in _PRIM_RE.findall(txt):
        if tok.startswith("LUT"):
            lut += 1
        elif tok.startswith("DFF"):
            dff += 1
        elif tok == "IOBUF":
            iobuf += 1
        elif tok == "OBUF":
            obuf += 1
        elif tok in ("IBUF", "TBUF"):
            ibuf += 1
        elif tok == "ALU":
            alu += 1
    return dict(lut=lut, dff=dff, ibuf=ibuf, obuf=obuf, iobuf=iobuf, alu=alu)


def census_vendor_vg(vg: Path):
    """Ground-truth cell census from the vendor's own synthesis netlist."""
    txt = vg.read_text()
    n = lambda rx: len(re.findall(rx, txt))
    return dict(
        lut=n(r"\bLUT[1-4]\b"),
        dff=n(r"\bDFF[NSRPCE]*\b"),
        ibuf=n(r"\bIBUF\b"),
        obuf=n(r"\bOBUF\b"),
        iobuf=n(r"\bIOBUF\b"),
        alu=n(r"\bALU\b"),
    )


# ── LUT-function classification (the oracle-A currency) ───────────────────────
def is_2to1_mux(init: str) -> bool:
    """True iff the 16-bit LUT (over its active inputs) is a 2:1 mux for SOME
    wiring.  classify_lut only tries 3 of the 6 (sel,data0,data1) orderings, so a
    mux with swapped data inputs lands in COMBO3 — this checks all six (ported
    verbatim from scripts/gowin_lec.py)."""
    import itertools
    v = int(init, 2)
    act = [pos for pos in range(4)
           if any(((v >> p) & 1) != ((v >> (p ^ (1 << pos))) & 1)
                  for p in range(16))]
    if len(act) != 3:
        return False
    for sel in act:
        d = [p for p in act if p != sel]
        for i0, i1 in ((d[0], d[1]), (d[1], d[0])):
            good = True
            for bits in itertools.product((0, 1), repeat=3):
                a = dict(zip(act, bits))
                p = sum(a[pos] << pos for pos in act)
                if ((v >> p) & 1) != (a[i1] if a[sel] else a[i0]):
                    good = False
                    break
            if good:
                return True
    return False


def classify_fn(init16: str) -> str:
    """Function head for a 16-bit INIT, resolving the mux case classify_lut
    under-reports (COMBO3 that is really a 2:1 mux)."""
    head = re.match(r"[A-Z0-9]+", classify_lut(init16)).group(0)
    if head.startswith("COMBO") and is_2to1_mux(init16):
        return "MUX"
    return head


_VG_LUT_RE = re.compile(
    r"\bLUT([1-4])\s+(\S+)\s*\(.*?defparam\s+\2\.INIT\s*=\s*(\d+)'h([0-9a-fA-F]+)",
    re.S)


# Bare logic-gate primitives GowinSynthesis emits that P&R maps 1:1 onto an
# (inverting/selecting) physical LUT — so the recovered LUT is the faithful
# realisation.  Map them to the function head classify_fn would give that LUT.
_VG_GATE_RE = re.compile(r"\b(INV|MUX2(?:_[A-Z0-9]+)?)\s+\S+\s*\(")
_VG_GATE_FN = {"INV": "INV"}          # MUX2* handled by prefix below


def vendor_lut_fns(vg: Path):
    """Classified function heads for every LUT the VENDOR placed, read from its
    own netlist.  A LUT{k} INIT is 2**k bits; tile it up to the 16-bit width
    classify_fn expects (the extra inputs are don't-cares, exactly as apycula
    pads a sub-LUT4 into a LUT4 slice).  Bare INV/MUX2 gates are counted as the
    LUT function they physically become after place & route."""
    txt = vg.read_text()
    fns = []
    for width, _name, _initw, inithex in _VG_LUT_RE.findall(txt):
        nbits = 2 ** int(width)
        val = int(inithex, 16) & ((1 << nbits) - 1)
        bits = f"{val:0{nbits}b}"          # MSB-first, nbits wide
        while len(bits) < 16:              # tile the truth table into 16 bits
            bits = bits + bits
        fns.append(classify_fn(bits[:16]))
    for gate in _VG_GATE_RE.findall(txt):
        fns.append("MUX" if gate.startswith("MUX2") else _VG_GATE_FN[gate])
    return fns


# ── pluribus lifter: recover logic, isolate the used LUTs ─────────────────────
def lift_recover(gwc: Path, device):
    lift = GowinLift(device)
    pc = lift.parse_config(str(gwc))
    d = lift.recover_netlist(pc)
    used = []
    for lt in d.luts:
        if not lt["z_used"]:
            continue
        used.append(classify_fn(lt["init"]))
    return dict(
        n_ff=len(d.ffs),
        n_lut_nonconst=len(d.luts),
        n_lut_used=len(used),
        used_fns=used,
        n_pad=len(d.pads),
    )


# ── per-design verdict ────────────────────────────────────────────────────────
def compare_census(a, b, keys=("lut", "dff", "ibuf", "obuf", "iobuf", "alu")):
    return [k for k in keys if a.get(k, 0) != b.get(k, 0)]


def run_design(d: Design, dev, device, root: Path, log):
    wd = root / d.name
    wd.mkdir(parents=True, exist_ok=True)
    xdg = root / "xdg"
    log.write(f"\n{'='*66}\n=== {d.name} ({device}) ===\n{'='*66}\n")

    res = {"name": d.name}

    fs, err = vendor_build(d, dev, wd, xdg, log)
    if fs is None:
        res.update(verdict="VENDOR-ERR", detail=err)
        return res

    gwc = our_decode(fs, dev, wd, log)
    refv = apicula_decode(fs, dev, wd, log)
    if gwc is None:
        res.update(verdict="DECODE-ERR", detail="our gowin_unpack failed")
        return res

    ours = census_gwconfig(gwc)
    apic = census_refv(refv) if refv is not None else None
    vg = wd / "impl" / "gwsynthesis" / "top.vg"
    truth = census_vendor_vg(vg) if vg.exists() else None
    rec = lift_recover(gwc, device)

    res["census_ours"] = ours
    res["census_apicula"] = apic
    res["census_vendor"] = truth
    res["recovered"] = rec

    # Oracle B: our decode must match apicula's own decode (faithful front end).
    if apic is None:
        oracleB, b_detail = "APICULA-ERR", "apicula gowin_unpack -o failed"
    else:
        bdiffs = compare_census(ours, apic)
        oracleB = "MATCH" if not bdiffs else "DIVERGE"
        b_detail = "identical census" if not bdiffs else \
            "; ".join(f"{k}: ours={ours[k]} apicula={apic[k]}" for k in bdiffs)
    res["oracleB"], res["oracleB_detail"] = oracleB, b_detail

    # Oracle A: recovered used-logic vs the source's boolean function.
    #
    #   Combinational designs synth to a SINGLE physical LUT — so the recovered
    #   z_used LUT is the whole design, and classifying its truth table against
    #   the source function is a genuine (if small) LEC of the combinational core.
    #
    #   Registered designs split the source across LUTs + DFF sync-set/reset +
    #   IOLOGIC (e.g. anchor: a&b -> DFFR, a|b -> DFFS, a^b -> the one XOR LUT),
    #   and the real FFs share the slice bel space with ~1725 phantom-default
    #   DFFS, so a whole-netlist LEC is not achievable — reported, not gated.
    have = Counter(rec["used_fns"])                 # mux-aware (classify_fn)
    want = Counter(d.expect_fns)
    vlut = Counter(vendor_lut_fns(vg)) if vg.exists() else Counter()
    phantom_dff = ours["dff"] - (truth["dff"] if truth else 0)
    phantom_ibuf = ours["ibuf"] - (truth["ibuf"] if truth else 0)
    res["phantom_dff"], res["phantom_ibuf"] = phantom_dff, phantom_ibuf
    res["vendor_lut_fns"] = sorted(vlut.elements())

    if d.combinational:
        logic_ok = (have == want)                   # the LUT IS the whole design
        oracleA = "LOGIC-EXACT" if logic_ok else "LOGIC-DIVERGE"
        a_detail = (f"recovered LUT={sorted(have.elements())} "
                    f"source={sorted(want.elements())}; "
                    f"phantom dff={phantom_dff} ibuf={phantom_ibuf}")
    else:
        # informational: the recovered LUTs are a correct SUBSET of the vendor's
        # placed logic (the rest folded into FF controls).
        subset_ok = not (have - vlut) if vlut else True
        oracleA = "LOGIC-PARTIAL" if subset_ok else "LOGIC-DIVERGE"
        a_detail = (f"recovered LUTs={sorted(have.elements())} "
                    f"vendor placed={sorted(vlut.elements())} "
                    f"source={sorted(want.elements())}; "
                    f"real FFs indistinguishable from {phantom_dff} phantom DFFS")
    res["oracleA"], res["oracleA_detail"] = oracleA, a_detail

    # Verdict: EXACT needs a faithful decode (B) AND a clean, LEC-able bitstream
    # (no phantom-default excess) — unreachable on raw vendor bitstreams.  The
    # achievable best is a faithful decode with the used logic recovered.
    clean = (phantom_dff <= 0 and phantom_ibuf <= 0)
    if oracleB not in ("MATCH", "APICULA-ERR"):
        res["verdict"] = "PLURIBUS-BUG"             # our decode != apicula's
    elif oracleA == "LOGIC-DIVERGE":
        res["verdict"] = "LOGIC-DIVERGE"
    elif clean and oracleA == "LOGIC-EXACT":
        res["verdict"] = "EXACT"
    else:
        res["verdict"] = "FAITHFUL+GAP"             # decode + used logic ok; only
                                                    # the vendor-default gap left
    res["detail"] = f"B:{oracleB} | A:{oracleA} | {a_detail}"
    return res


# ── driver ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="run only these designs")
    ap.add_argument("--device", default="GW1N-2", choices=sorted(DEVICES),
                    help="target device / apycula chipdb (default GW1N-2)")
    ap.add_argument("--keep", action="store_true", help="keep the work dir")
    ap.add_argument("--log", default=str(REPO / "tmp" / "gowin_fuzz.log"))
    ap.add_argument("--json", default=str(REPO / "tmp" / "gowin_fuzz.json"))
    args = ap.parse_args()

    (REPO / "tmp").mkdir(exist_ok=True)
    log = open(args.log, "w")

    if not os.path.exists(GW_SH):
        sys.exit(f"ERROR: gw_sh not found at {GW_SH} (set GOWINHOME)")
    ok, msg = ensure_license(log)
    print(f"[gw_sh]   {GW_SH}")
    print(f"[license] {msg}")
    if not ok:
        print("  WARNING: license not configured — vendor builds will fail.")

    dev = DEVICES[args.device]
    designs = [d for d in DESIGNS if not args.only or d.name in args.only]
    root = Path(tempfile.mkdtemp(prefix="gowin_fuzz_", dir=str(REPO / "tmp")))

    print(f"\n  device={args.device} part={dev['part']} pkg={dev['package']}\n")
    hdr = f"  {'design':<8} {'verdict':<14} {'oracleB':<8} detail"
    print(hdr)
    print("  " + "-" * len(hdr))

    results = []
    for d in designs:
        r = run_design(d, dev, args.device, root, log)
        results.append(r)
        print(f"  {d.name:<8} {r['verdict']:<14} {r.get('oracleB', '-'):<8} "
              f"{r.get('detail', '')[:118]}")

    n = len(results)
    exact = sum(1 for r in results if r["verdict"] == "EXACT")
    n_comb = sum(1 for d in designs if d.combinational)
    comb_ok = sum(1 for r, d in zip(results, designs)
                  if d.combinational and r.get("oracleA") == "LOGIC-EXACT")
    diverge = sum(1 for r in results if r.get("oracleA") == "LOGIC-DIVERGE")
    faithful = sum(1 for r in results if r.get("oracleB") == "MATCH")
    built = sum(1 for r in results
                if r["verdict"] not in ("VENDOR-ERR", "DECODE-ERR"))
    print(f"\n  === summary ({args.device}) ===")
    print(f"  designs                       : {n}  ({built} built by gw_sh)")
    print(f"  our-decode == apicula (B)     : {faithful}/{built}  (faithful front end)")
    print(f"  combinational logic exact (A) : {comb_ok}/{n_comb}  (recovered LUT == source fn)")
    print(f"  logic divergences (A)         : {diverge}/{built}")
    print(f"  EXACT full-netlist match      : {exact}/{built}  (blocked by the decode gap below)")
    gaps = [r for r in results if r.get("phantom_dff", 0) > 0]
    if gaps:
        pd = max(r["phantom_dff"] for r in gaps)
        pi = max(r.get("phantom_ibuf", 0) for r in gaps)
        print(f"  DECODE GAP (vendor defaults): up to {pd} phantom DFFS + "
              f"{pi} phantom IBUF per bitstream")
        print("    -> apycula GW1N-2 chipdb cannot distinguish the vendor's")
        print("       default-programmed unused slices/IO from real cells.")
    print(f"\n  log:  {args.log}")

    with open(args.json, "w") as fh:
        json.dump({"device": args.device, "part": dev["part"],
                   "results": results}, fh, indent=2)
    print(f"  json: {args.json}")

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"  work dir kept: {root}")
    log.close()
    bug = any(r["verdict"] == "PLURIBUS-BUG" for r in results)
    sys.exit(1 if (bug or built == 0) else 0)


if __name__ == "__main__":
    main()
