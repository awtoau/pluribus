#!/usr/bin/env python3
"""Exhaustive LIFTER fidelity check over the whole fuzz corpus (issue #37, P6).

For every fuzz target we have BOTH the original design
(`diamond-fuzz/targets/<name>/fuzz.v`) and its vendor bitstream
(`.../impl1/fuzz_impl1.bit`).  This driver formally checks that the netlist the
pluribus lifter RECOVERS from the bitstream is functionally equivalent to that
original design:

    bitstream --(native decode)--> .config --(machxo2_lift)--> recovered netlist
    then  yosys sequential equivalence  recovered  vs  original fuzz.v

Zero-diff across the corpus is the exhaustive proof that the lifter is faithful,
analogous to the decoder's corpus parity.  Failures are a precise lifter-defect
map (which target, and the nature of the discrepancy).

Buckets
-------
  * logic       — fuzz.v is behavioural RTL or instantiates only plain LUT4/FF
                  primitives.  Run yosys `equiv_induct` (unbounded temporal
                  induction) recovered-vs-original.
                    - equivalent
                    - not_equivalent   (lifter defect; nature captured)
                    - error            (flow/reference build failure)
  * hard_ip     — fuzz.v instantiates a hard primitive (PLL / EBR / EFB / OSC /
                  SED / DDR / distributed-RAM / carry / IO-register / config).
                  "Logic equivalence" is meaningless here; the LUT/FF lifter does
                  not reproduce these as logic.  We decode + lift and record what
                  hard IP the recovery captured (PLL/EBR/sysCONFIG), bucketed by
                  the requested primitive family.
  * no_bit      — no built `.bit` (counted, never silently dropped).

Parallelised at the bitstream level (independent per target) with a process
pool: each worker builds ONE MachXO2Lift (routing graph) and reuses it across a
shard of targets.  pytrellis + yosys are the heavy lifting; the driver itself is
thin.

Runs under python3.15t (NoGIL).  Trellis paths (TRELLIS_BUILD / TRELLIS_DBROOT)
default to the free-threaded pytrellis build + prjtrellis DB; override via env.

Usage:
  python3.15t scripts/lifter_equiv_corpus.py            # whole corpus
  python3.15t scripts/lifter_equiv_corpus.py --workers 12
  python3.15t scripts/lifter_equiv_corpus.py --only re_edge_pin66 dp8kc_x1
  python3.15t scripts/lifter_equiv_corpus.py --limit 50
Logs:   tmp/lifter_equiv_corpus.log   (summary)
        tmp/lifter_equiv_corpus.jsonl (one JSON result per target)
"""

import argparse
import json
import os
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, REPO)
sys.path.insert(0, SCRIPTS)

# ---- Trellis paths come from the env (free-threaded pytrellis build + DB),
# with the repo's relative default; an explicit environment always wins.
os.environ.setdefault("TRELLIS_BUILD", "tmp/prjtrellis/libtrellis/build")
os.environ.setdefault("TRELLIS_DBROOT", "tmp/prjtrellis/database")

DEVICE = "LCMXO2-1200"
PACKAGE = "TQFP100"
TARGETS_DIR = os.path.join(REPO, "diamond-fuzz", "targets")
WORK_DIR = os.path.join(REPO, "tmp", "lifter_equiv_work")

# ---------------------------------------------------------------------------
# Target classification.  A target is LOGIC-tractable iff its fuzz.v top module
# instantiates NO vendor primitive at all (pure behavioural RTL) OR only plain
# LUT/FF primitives that the LUT/FF lifter is designed to reproduce.  Anything
# else is hard IP (or a primitive the LUT/FF lifter does not model as logic:
# carry chains, distributed RAM, ROM, IO registers, ...).
LOGIC_PRIMS = {
    "LUT4",
    "FD1S3AX", "FD1S3BX", "FD1S3DX", "FD1S3IX", "FD1S3JX",
    "FD1P3AX", "FD1P3BX", "FD1P3DX", "FD1P3IX", "FD1P3JX",
    "VHI", "VLO", "GND", "VCC",
}

import re as _re
# Instantiation of a vendor primitive: an all-caps cell name at line start
# followed by a `#(param)` or an instance identifier.  Names can be as short as
# two chars (IB, OB, BB), so require >=2 total.
_PRIM_RE = _re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*(#\s*\(|[a-zA-Z_])")
# families for hard-IP bucketing (prefix match on the primitive name)
_HARDIP_FAMILY = [
    ("EHXPLL", "pll"), ("PLLREFCS", "pll"),
    ("DP8KC", "ebr"), ("PDPW8KC", "ebr"), ("SP8KC", "ebr"), ("DP16", "ebr"),
    ("FIFO", "ebr"),
    ("EFB", "efb"),
    ("OSCH", "osc"), ("OSCJ", "osc"),
    ("SEDF", "sed"),
    ("PCNTR", "pcntr"),
    ("DPR16", "dram"), ("SPR16", "dram"),
    ("ROM", "rom"),
    ("CCU2", "carry"),
    ("IDDR", "ddr"), ("ODDR", "ddr"), ("IFS1", "ioreg"), ("OFS1", "ioreg"),
    ("IFS1S", "ioreg"), ("ECLK", "clk_ip"), ("CLKDIVC", "clk_ip"),
    ("DCCA", "clk_ip"), ("DCMA", "clk_ip"), ("CLKFBBUFA", "clk_ip"),
    ("ILVDS", "lvds"), ("LVDSOB", "lvds"), ("BCLVDSO", "lvds"),
    ("JTAGF", "config"), ("START", "config"), ("SGSR", "config"),
    ("BBPD", "iobuf"), ("BBPU", "iobuf"), ("BBW", "iobuf"), ("BCINRD", "iobuf"),
    ("INRDB", "iobuf"), ("IBPD", "iobuf"), ("IBPU", "iobuf"),
    ("OBCO", "iobuf"), ("OBZ", "iobuf"), ("OBZPU", "iobuf"),
    # bare 2-char IO buffers (input / output / bidirectional) with delay,
    # tristate or LVCMOS-variant config — IO hard cells, not fabric logic.
    ("BB", "iobuf"), ("IB", "iobuf"), ("OB", "iobuf"),
]


def instantiated_prims(fuzz_v_text):
    """Uppercase primitive names instantiated in a fuzz.v (module head aside)."""
    prims = set()
    for ln in fuzz_v_text.splitlines():
        m = _PRIM_RE.match(ln)
        if not m:
            continue
        name = m.group(1)
        if name in ("BLOCK", "IOBUF", "LOCATE", "FREQUENCY"):
            continue
        prims.add(name)
    return prims


def classify(prims):
    """Return ('logic', None) or ('hard_ip', family)."""
    hard = prims - LOGIC_PRIMS
    if not hard:
        return "logic", None
    # family of the "most significant" hard primitive
    for name in sorted(hard):
        for pref, fam in _HARDIP_FAMILY:
            if name.startswith(pref):
                return "hard_ip", fam
    return "hard_ip", "other:" + ",".join(sorted(hard))


# ---------------------------------------------------------------------------
# Gold (reference) simulation models for the plain logic primitives that some
# behavioural-adjacent fuzz.v files instantiate.  Diamond LUT/FF primitives are
# not in yosys's cell libraries, so we supply behavioural equivalents.  In this
# corpus their set/reset/enable controls are tied inactive, so exact reset
# semantics never gate the result; the models are nonetheless faithful.
GOLD_PRIM_LIB = r"""
module LUT4 (input A, B, C, D, output Z);
  parameter init = 16'h0000;
  assign Z = init[{D, C, B, A}];
endmodule
module FD1S3AX (input CK, D, output reg Q); always @(posedge CK) Q <= D; endmodule
module FD1S3BX (input CK, D, PD, output reg Q);
  always @(posedge CK or posedge PD) if (PD) Q <= 1'b1; else Q <= D; endmodule
module FD1S3DX (input CK, D, CD, output reg Q);
  always @(posedge CK or posedge CD) if (CD) Q <= 1'b0; else Q <= D; endmodule
module FD1S3IX (input CK, D, CD, output reg Q);
  always @(posedge CK) if (CD) Q <= 1'b0; else Q <= D; endmodule
module FD1S3JX (input CK, D, PD, output reg Q);
  always @(posedge CK) if (PD) Q <= 1'b1; else Q <= D; endmodule
module FD1P3AX (input CK, D, SP, output reg Q);
  always @(posedge CK) if (SP) Q <= D; endmodule
module FD1P3BX (input CK, D, SP, PD, output reg Q);
  always @(posedge CK or posedge PD) if (PD) Q <= 1'b1; else if (SP) Q <= D; endmodule
module FD1P3DX (input CK, D, SP, CD, output reg Q);
  always @(posedge CK or posedge CD) if (CD) Q <= 1'b0; else if (SP) Q <= D; endmodule
module FD1P3IX (input CK, D, SP, CD, output reg Q);
  always @(posedge CK) if (CD) Q <= 1'b0; else if (SP) Q <= D; endmodule
module FD1P3JX (input CK, D, SP, PD, output reg Q);
  always @(posedge CK) if (PD) Q <= 1'b1; else if (SP) Q <= D; endmodule
"""

# Recovered-netlist primitive models (LUT4 with INIT already in the fabric's
# {D,C,B,A} truth-table convention; MachXO2 fabric FF).
GATE_PRIM_LIB = r"""module LUT4 #(parameter [15:0] INIT = 16'h0000)
  (input A, B, C, D, output Z);
  assign Z = INIT[{D, C, B, A}];
endmodule
module MACHXO2_FF #(parameter REGSET = "RESET", parameter SD = "0",
                    parameter GSR = "DISABLED")
  (input CLK, CE, LSR, D, output reg Q);
  localparam INIT = (REGSET == "SET") ? 1'b1 : 1'b0;
  initial Q = INIT;
  always @(posedge CLK) if (LSR) Q <= INIT; else if (CE) Q <= D;
endmodule
"""


# ---------------------------------------------------------------------------
# .pad parsing: Diamond's "Pinout by Port Name" table maps each top-level port
# to its physical pin and buffer direction.
def parse_pad_ports(pad_path):
    ports = {}
    inblock = False
    with open(pad_path) as fh:
        for ln in fh:
            if ln.startswith("Pinout by Port Name"):
                inblock = True
                continue
            if not inblock:
                continue
            if ln.startswith("| Port Name") or ln.startswith("+"):
                continue
            if ln.startswith("|"):
                cols = [x.strip() for x in ln.strip().strip("|").split("|")]
                name, pinbank, buf = cols[0], cols[1], cols[2]
                if "_OUT" in buf:
                    direction = "output"
                elif "_IN" in buf:
                    direction = "input"
                else:
                    direction = "inout"
                if "_BIDI" in buf:
                    direction = "inout"
                ports[name] = {"pin": pinbank.split("/")[0], "dir": direction,
                               "buf": buf}
            elif ln.strip() == "" and ports:
                break
    return ports


# ---------------------------------------------------------------------------
# Per-worker global lift (built once, reused across the worker's shard).
_LIFT = None
_IODB_PINMAP = None


def _worker_init():
    global _LIFT, _IODB_PINMAP
    from lifters import machxo2_lift as ML
    _LIFT = ML.MachXO2Lift(DEVICE)
    iodb = ML.load_iodb(DEVICE)
    _IODB_PINMAP = iodb["packages"][PACKAGE]


def _decode_and_lift(bit_path, cfg_path):
    """native decode bitstream -> .config, then lift -> (pc, design)."""
    import native_config
    text, pb, bram = native_config.config_from_file(
        bit_path, device=DEVICE, db_root=os.environ["TRELLIS_DBROOT"])
    with open(cfg_path, "w") as fh:
        fh.write(text)
    pc = _LIFT.parse_config(cfg_path)
    design = _LIFT.recover_netlist(pc)
    return pc, design, pb, bram


def _build_recovered_verilog(design, ports, extra_inputs=()):
    """Emit `module fuzz` for the recovered netlist with named ports wired to the
    recovered fabric nets.  Resolves the single global clock (which the direct
    lift leaves unmerged across the chip-edge clock spine) by bridging each
    undriven FF clock net to the sole clock input pad.  `extra_inputs` are
    reference-only input port names (dead inputs Diamond eliminated) declared as
    dangling gate inputs so yosys equiv_make can match port sets.  Returns
    (verilog, meta)."""
    from lifters import machxo2_lift as ML
    for name, info in ports.items():
        site = _IODB_PINMAP.get(info["pin"])
        info["site"] = site
        info["net"] = None
        if site:
            d = "in" if info["dir"] == "input" else "out"
            info["net"] = ML.pad_net(design, _LIFT, site["row"], site["col"],
                                     site["pio"], d)
            if info["dir"] == "inout" and not info["net"]:
                info["net"] = ML.pad_net(design, _LIFT, site["row"],
                                         site["col"], site["pio"], "in")

    driven = set()
    for lt in design.luts:
        if lt["z"]:
            driven.add(lt["z"])
    for ff in design.ffs:
        if ff["q"]:
            driven.add(ff["q"])
    consumed = set()
    for lt in design.luts:
        for p in ("a", "b", "c", "d"):
            if lt[p]:
                consumed.add(lt[p])
    for ff in design.ffs:
        if ff["d"]:
            consumed.add(ff["d"])

    inpad_nets = {n: i["net"] for n, i in ports.items()
                  if i["dir"] in ("input", "inout") and i.get("net")}
    ff_clk = set(ff["clk"] for ff in design.ffs
                 if ff["clk"] not in ("1'b0", "1'b1"))
    undriven_clk = ff_clk - driven - set(inpad_nets.values())
    clk_pad_cands = [n for n, net in inpad_nets.items() if net not in consumed]

    bridge = {}
    meta = {"clock_bridged": 0, "clock_unbridged": 0}
    if undriven_clk and len(clk_pad_cands) == 1:
        for cn in undriven_clk:
            bridge[cn] = clk_pad_cands[0]
        meta["clock_bridged"] = len(undriven_clk)
    elif undriven_clk:
        meta["clock_unbridged"] = len(undriven_clk)

    portdecls = [f"  {i['dir']} {n}" for n, i in ports.items()]
    portdecls += [f"  input {n}" for n in extra_inputs if n not in ports]
    L = [GATE_PRIM_LIB, "module fuzz("]
    L.append(",\n".join(portdecls) + ");")
    for nn in design.all_nets:
        L.append(f"  wire {nn};")

    # Diagnostic: output ports whose recovered fabric net has no driver — the
    # signature of a net-merge gap (e.g. a top-edge vertical span-2 longline that
    # the direct lift fails to canonicalize), as opposed to a genuine logic mismatch.
    driven_out = set(driven) | set(inpad_nets.values()) | set(bridge)
    undriven_outputs = [n for n, i in ports.items()
                        if i["dir"] == "output"
                        and (not i.get("net") or i["net"] not in driven_out)]
    meta_undriven = undriven_outputs
    for n, i in ports.items():
        if i["dir"] in ("input", "inout") and i.get("net"):
            L.append(f"  assign {i['net']} = {n};")
    for cn, pn in bridge.items():
        L.append(f"  assign {cn} = {ports[pn]['net']};")
    for n, i in ports.items():
        if i["dir"] == "output" and i.get("net"):
            L.append(f"  assign {n} = {i['net']};")
    for lt in design.luts:
        a = lt["a"] or "1'b0"
        b = lt["b"] or "1'b0"
        c = lt["c"] or "1'b0"
        dd = lt["d"] or "1'b0"
        z = lt["z"] or (lt["name"] + "_z")
        init = format(int(lt["init"], 2), "04x")
        if not lt["z"]:
            L.append(f"  wire {z};")
        L.append(f"  LUT4 #(.INIT(16'h{init})) {lt['name']} "
                 f"(.A({a}),.B({b}),.C({c}),.D({dd}),.Z({z}));")
    for ff in design.ffs:
        L.append(
            f"  MACHXO2_FF #(.REGSET(\"{ff['regset']}\"),.SD(\"{ff['sd']}\"),"
            f".GSR(\"{ff['gsr']}\")) {ff['name']} "
            f"(.CLK({ff['clk']}),.CE({ff['ce']}),.LSR({ff['lsr']}),"
            f".D({ff['d']}),.Q({ff['q']}));")
    L.append("endmodule")
    meta["n_lut"] = len(design.luts)
    meta["n_ff"] = len(design.ffs)
    meta["undriven_outputs"] = meta_undriven
    return "\n".join(L), meta


_EQ_SCRIPT = """\
read_verilog -sv {goldlib} {gold}
hierarchy -top fuzz
flatten
proc
opt -full
design -stash gold
read_verilog -sv {gate}
hierarchy -top fuzz
flatten
proc
opt -full
design -stash gate
design -copy-from gold -as gold fuzz
design -copy-from gate -as gate fuzz
equiv_make gold gate equiv
hierarchy -top equiv
clean
equiv_simple
equiv_induct
equiv_status
"""


def _run_yosys_equiv(gold_v, gate_v, workdir):
    os.makedirs(workdir, exist_ok=True)
    goldlib = os.path.join(workdir, "goldlib.v")
    gold = os.path.join(workdir, "gold.v")
    gate = os.path.join(workdir, "gate.v")
    ys = os.path.join(workdir, "eq.ys")
    with open(goldlib, "w") as fh:
        fh.write(GOLD_PRIM_LIB)
    with open(gold, "w") as fh:
        fh.write(gold_v)
    with open(gate, "w") as fh:
        fh.write(gate_v)
    with open(ys, "w") as fh:
        fh.write(_EQ_SCRIPT.format(goldlib=goldlib, gold=gold, gate=gate))
    res = subprocess.run(["yosys", ys], capture_output=True, text=True)
    out = res.stdout + res.stderr
    with open(os.path.join(workdir, "yosys.log"), "w") as fh:
        fh.write(out)

    errors = [l for l in out.splitlines() if l.strip().startswith("ERROR")]
    if "Equivalence successfully proven!" in out:
        return "equivalent", {"yosys_tail": out.splitlines()[-3:]}
    if errors:
        return "error", {"reason": "yosys_error", "errors": errors[:4]}
    # count unproven equiv cells
    reason = "unproven"
    for l in out.splitlines():
        if "unproven" in l and "$equiv" in l:
            reason = l.strip()
    return "not_equivalent", {"reason": reason,
                              "yosys_tail": out.splitlines()[-6:]}


def _sanitize_portset(names):
    return set(names)


def process_target(name):
    """Full per-target flow.  Returns a result dict (never raises)."""
    tdir = os.path.join(TARGETS_DIR, name)
    fuzz_v = os.path.join(tdir, "fuzz.v")
    bit = os.path.join(tdir, "impl1", "fuzz_impl1.bit")
    pad = os.path.join(tdir, "impl1", "fuzz_impl1.pad")
    res = {"target": name}
    try:
        if not os.path.exists(fuzz_v):
            res.update(bucket="skip", status="no_fuzz_v")
            return res
        fuzz_text = open(fuzz_v).read()
        prims = instantiated_prims(fuzz_text)
        kind, family = classify(prims)
        res["prims"] = sorted(prims)
        res["family"] = family

        if not os.path.exists(bit):
            res.update(bucket="no_bit", status="no_bit", kind=kind)
            return res

        workdir = os.path.join(WORK_DIR, name)
        os.makedirs(workdir, exist_ok=True)
        cfg = os.path.join(workdir, "recovered.config")
        pc, design, pb, bram = _decode_and_lift(bit, cfg)

        if kind == "hard_ip":
            from lifters import machxo2_lift as ML
            hip = ML.hardip_summary(pc)
            captured = {
                "plls": len(hip["plls"]), "ebr": len(hip["ebr"]),
                "efb_blocks": len(getattr(pb, "efb_blocks", []) or []),
                "bram_blocks": len(bram or []),
                "sysconfig": hip["sysconfig"],
                "luts": len(design.luts), "ffs": len(design.ffs),
            }
            # Did the decode+lift capture hard IP of the requested family?
            fam_ok = {
                "pll": captured["plls"] > 0,
                "ebr": captured["ebr"] > 0 or captured["bram_blocks"] > 0,
                "efb": captured["efb_blocks"] > 0,
            }.get(family, None)
            res.update(bucket="hard_ip", status="decoded", kind="hard_ip",
                       captured=captured, family_captured=fam_ok)
            return res

        # --- logic bucket: build recovered verilog + yosys equivalence ---
        ports = parse_pad_ports(pad) if os.path.exists(pad) else {}
        if not ports:
            res.update(bucket="logic", status="error",
                       reason="no_pad_ports")
            return res

        # yosys equiv_make needs identical port-name sets on both sides.
        #   - OUTPUT ports must match exactly (a missing/extra driven pad means
        #     the recovery lost or invented an output — a real defect).
        #   - Diamond legitimately eliminates dead INPUT ports (e.g. a LUT with
        #     INIT=0 ignoring its inputs); those gold-only inputs are declared as
        #     dangling gate inputs so the interfaces line up.
        #   - A pad input the reference never declared is unexpected (bus-bit
        #     renaming etc.) — flag it rather than guess.
        gold_dirs = _module_port_dirs(fuzz_text)
        extra_inputs = ()
        if gold_dirs is not None:
            gold_out = {n for n, d in gold_dirs.items()
                        if d in ("output", "inout")}
            pad_out = {n for n, i in ports.items()
                       if i["dir"] in ("output", "inout")}
            if gold_out != pad_out:
                res.update(bucket="logic", status="error",
                           reason="output_port_mismatch",
                           gold_outputs=sorted(gold_out),
                           pad_outputs=sorted(pad_out))
                return res
            pad_not_gold = [n for n in ports if n not in gold_dirs]
            if pad_not_gold:
                res.update(bucket="logic", status="error",
                           reason="pad_port_not_in_reference",
                           extra_pad_ports=sorted(pad_not_gold))
                return res
            extra_inputs = tuple(n for n, d in gold_dirs.items()
                                 if d == "input" and n not in ports)

        gate_v, meta = _build_recovered_verilog(design, ports, extra_inputs)
        res["meta"] = meta

        status, detail = _run_yosys_equiv(fuzz_text, gate_v, workdir)
        # Distinguish a net-merge/routing-recovery gap (dangling recovered output
        # net) from a genuine logic mismatch in the defect map.
        if status == "not_equivalent" and meta.get("undriven_outputs"):
            detail["reason"] = ("net_merge_gap: undriven recovered output net(s) "
                                + ",".join(meta["undriven_outputs"]))
            detail["defect_class"] = "net_merge_gap"
        elif status == "not_equivalent":
            detail["defect_class"] = "logic_mismatch"
        res.update(bucket="logic", status=status, **detail)
        return res
    except Exception as e:
        res.update(bucket=res.get("bucket", "logic"), status="error",
                   reason="exception", exc=str(e),
                   tb=traceback.format_exc().splitlines()[-4:])
        return res


_PORTDECL_RE = _re.compile(r"module\s+fuzz\s*\((.*?)\)\s*;", _re.S)


def _module_port_dirs(fuzz_text):
    """Best-effort {port_name: direction} from an ANSI `module fuzz(...)` header.
    Direction defaults to the last-seen keyword (ANSI headers may omit it on
    subsequent same-direction ports, e.g. `output wire a, b`)."""
    m = _PORTDECL_RE.search(fuzz_text)
    if not m:
        return None
    body = m.group(1)
    kw = {"input", "output", "inout", "wire", "reg", "logic", "signed"}
    dirs = {}
    cur = None
    for tok in body.replace("\n", " ").split(","):
        tok = tok.strip()
        if not tok:
            continue
        low = tok.split()
        for w in low:
            if w in ("input", "output", "inout"):
                cur = w
                break
        ids = [i for i in _re.findall(r"[A-Za-z_]\w*", tok) if i not in kw]
        if ids:
            dirs[ids[-1]] = cur or "input"
    return dirs or None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int,
                    default=min(12, os.cpu_count() or 4))
    ap.add_argument("--only", nargs="*", help="only these target names")
    ap.add_argument("--limit", type=int, help="cap number of targets")
    ap.add_argument("--logic-only", action="store_true",
                    help="skip hard_ip decode (faster; logic bucket only)")
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    if args.only:
        targets = list(args.only)
    else:
        targets = sorted(d for d in os.listdir(TARGETS_DIR)
                         if os.path.isdir(os.path.join(TARGETS_DIR, d)))
    if args.limit:
        targets = targets[:args.limit]

    if args.logic_only:
        keep = []
        for t in targets:
            fv = os.path.join(TARGETS_DIR, t, "fuzz.v")
            if not os.path.exists(fv):
                continue
            k, _ = classify(instantiated_prims(open(fv).read()))
            if k == "logic":
                keep.append(t)
        targets = keep

    print(f"[lifter-equiv] {len(targets)} targets, {args.workers} workers "
          f"(python {sys.version.split()[0]}, gil={sys._is_gil_enabled()})",
          flush=True)

    jsonl_path = os.path.join(REPO, "tmp", "lifter_equiv_corpus.jsonl")
    results = []
    with open(jsonl_path, "w") as jf:
        with ProcessPoolExecutor(max_workers=args.workers,
                                 initializer=_worker_init) as ex:
            futs = {ex.submit(process_target, t): t for t in targets}
            done = 0
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                jf.write(json.dumps(r) + "\n")
                done += 1
                if done % 100 == 0 or done == len(targets):
                    print(f"[lifter-equiv]   {done}/{len(targets)}", flush=True)

    _summarize(results)


def _summarize(results):
    from collections import Counter, defaultdict
    buckets = Counter(r.get("bucket") for r in results)
    logic = [r for r in results if r.get("bucket") == "logic"]
    logic_status = Counter(r.get("status") for r in logic)
    hard = [r for r in results if r.get("bucket") == "hard_ip"]
    hard_fam = Counter(r.get("family") for r in hard)
    hard_fam_ok = defaultdict(lambda: [0, 0])  # family -> [captured, checkable]
    for r in hard:
        fc = r.get("family_captured")
        if fc is not None:
            hard_fam_ok[r["family"]][1] += 1
            if fc:
                hard_fam_ok[r["family"]][0] += 1

    lines = []
    lines.append("=" * 70)
    lines.append("LIFTER FIDELITY — corpus equivalence verdict")
    lines.append("=" * 70)
    lines.append(f"targets processed : {len(results)}")
    for b, n in buckets.most_common():
        lines.append(f"  bucket {b:10s}: {n}")
    lines.append("")
    lines.append("LOGIC bucket (yosys sequential equivalence vs original):")
    for s, n in logic_status.most_common():
        lines.append(f"  {s:16s}: {n}")
    neq = [r for r in logic if r.get("status") == "not_equivalent"]
    err = [r for r in logic if r.get("status") == "error"]
    if neq:
        dc = Counter(r.get("defect_class", "?") for r in neq)
        lines.append("")
        lines.append(f"NOT-EQUIVALENT ({len(neq)})  [lifter defect map]:")
        for cls, n in dc.most_common():
            lines.append(f"  defect_class {cls:18s}: {n}")
        lines.append("  --- targets ---")
        for r in sorted(neq, key=lambda x: (x.get("defect_class", ""),
                                            x["target"])):
            lines.append(f"  {r['target']:40s} [{r.get('defect_class','?')}] "
                         f"{r.get('reason','')}")
    if err:
        lines.append("")
        lines.append(f"ERRORS ({len(err)})  [flow / reference issues]:")
        ec = Counter(r.get("reason") for r in err)
        for reason, n in ec.most_common():
            lines.append(f"  {reason:24s}: {n}")
        for r in sorted(err, key=lambda x: x["target"])[:40]:
            lines.append(f"    {r['target']:40s} {r.get('reason','')}")
    lines.append("")
    lines.append("HARD-IP bucket (not logic-liftable; decode/param capture):")
    for fam, n in hard_fam.most_common():
        cap = hard_fam_ok.get(fam)
        extra = ""
        if cap and cap[1]:
            extra = f"  (family config captured {cap[0]}/{cap[1]})"
        lines.append(f"  {str(fam):10s}: {n}{extra}")
    lines.append("=" * 70)

    text = "\n".join(lines)
    print(text, flush=True)
    with open(os.path.join(REPO, "tmp", "lifter_equiv_corpus.log"), "w") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
