#!/usr/bin/env python3.15t
"""Simulate lifted.v against the Quartus post-fit functional netlist (build.vo) with iverilog.

Behavioural check of the lifter's Verilog, independent of the structural postfit compare.
- DUT-A: corpus/cyclonev/<design>/quartus/simulation/questa/build.vo with the minimal models below
  (the vendor cyclonev_atoms.v is encrypted, iverilog cannot read it).  Models: 6-input
  cyclonev_lcell_comb (combout = lut_mask[{f,e,d,c,b,a}], the `!` on a port is an inversion in
  the netlist), io ibuf/obuf, clkena, dffeas.  Any other cell type -> "unsupported", no verdict.
- DUT-B: corpus/cyclonev/<design>/lifted.v (module renamed), ports named by pin (build.pin)
- Stimulus: seeded random vectors on the inputs, outputs compared after each settle; state
  carries across vectors, so latches are exercised.  X on either side is counted, not compared.
- `--zero a,b`: inputs forced to 0 (a zero-delay oscillating loop never settles).
Usage: python3.15t scripts/cyclonev_lifted_sim_check.py <design> [--steps N] [--zero x,...]
Log: tmp/logs/cyclonev_lifted_sim_check.log
"""
import argparse
import random
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "cyclonev_lifted_sim_check.log"
PRIMS = Path("/mnt/2tb/opt/altera/quartus-25.1/quartus/eda/sim_lib/altera_primitives.v")
MODELS = """`timescale 1ps/1ps
module cyclonev_lcell_comb(dataa,datab,datac,datad,datae,dataf,datag,cin,sharein,combout,sumout,cout,shareout);
  input dataa,datab,datac,datad,datae,dataf,datag,cin,sharein; output combout,sumout,cout,shareout;
  parameter lut_mask = 64'h0, extended_lut = "off", shared_arith = "off";
  function lutx(input [5:0] ix); integer k, i; reg r0, r1, m; begin
    r0 = 0; r1 = 0;
    for (k = 0; k < 64; k = k + 1) begin
      m = 1;
      for (i = 0; i < 6; i = i + 1) if (ix[i] !== 1'bx && ix[i] !== 1'bz && ix[i] !== k[i]) m = 0;
      if (m) begin if (lut_mask[k]) r1 = 1; else r0 = 1; end
    end
    lutx = (r1 && r0) ? 1'bx : r1;
  end endfunction
  assign combout = lutx({dataf,datae,datad,datac,datab,dataa});
  assign sumout = 1'b0; assign cout = 1'b0; assign shareout = 1'b0;
endmodule
module cyclonev_io_ibuf(i,ibar,dynamicterminationcontrol,o);
  input i,ibar,dynamicterminationcontrol; output o; parameter bus_hold="false", simulate_z_as="z";
  assign o = i;
endmodule
module cyclonev_io_obuf(i,oe,dynamicterminationcontrol,seriesterminationcontrol,parallelterminationcontrol,devoe,o,obar);
  input i,oe,dynamicterminationcontrol,devoe; input [15:0] seriesterminationcontrol,parallelterminationcontrol;
  output o,obar; parameter open_drain_output="false", shift_series_termination_control="false", bus_hold="false";
  assign o = i; assign obar = ~i;
endmodule
module cyclonev_clkena(inclk,ena,outclk,enaout);
  input inclk,ena; output outclk,enaout; parameter clock_type="auto", ena_register_mode="always enabled", disable_mode="low";
  assign outclk = inclk; assign enaout = ena;
endmodule
"""
SUPPORTED = {"cyclonev_lcell_comb", "cyclonev_io_ibuf", "cyclonev_io_obuf", "cyclonev_clkena", "dffeas"}
IVERILOG_LIMIT_S = 60   # compile ~1 s, run <5 s for 2000 vectors on a one-LAB design; 60 s = hung


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def ports_of_vo(text, top):
    """{name: (dir, width)} from the top module of build.vo."""
    hdr = text.split(f"module {top} (", 1)[1].split(");", 1)[0]
    names = [n.strip() for n in hdr.replace("\n", " ").split(",")]
    body = text.split(");", 1)[1]
    out = {}
    for n in names:
        m = re.search(rf"^\s*(input|output)\s*(\[(\d+):(\d+)\])?\s*{re.escape(n)}\s*;", body, re.M)
        out[n] = (m.group(1), int(m.group(3)) + 1 if m.group(2) else 1)
    return out


def pin_map(pin_text):
    """{'x[3]': 'N2'} from build.pin."""
    m = {}
    for line in pin_text.splitlines():
        p = [c.strip() for c in line.split(":")]
        if len(p) > 3 and p[2] in ("input", "output") and p[1]:
            m[p[0]] = p[1]
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--zero", default="", help="comma list of input signals held at 0")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trace", type=int, default=0, help="print the first N steps (inputs, Quartus outputs, lifted outputs)")
    ap.add_argument("--invert-inputs", default="",
                    help="comma list of lifted pins driven complemented, or all (diagnostic)")
    a = ap.parse_args()
    d = REPO / "corpus" / "cyclonev" / a.design
    vo = (d / "quartus" / "simulation" / "questa" / "build.vo").read_text()
    ports = ports_of_vo(vo, a.design)
    pins = pin_map((d / "build.pin").read_text())
    lifted = (d / "lifted.v").read_text()
    work = REPO / "tmp" / "simcheck" / a.design
    work.mkdir(parents=True, exist_ok=True)
    (work / "lifted_r.v").write_text(re.sub(rf"\bmodule {a.design}\b", f"module {a.design}_lifted", lifted, count=1))
    lports = set(re.findall(r"^\s*(?:input|output|inout)\s+wire\s+(\w+)", lifted, re.M))
    zero = set(filter(None, a.zero.split(",")))
    ins = [(n, w) for n, (dr, w) in ports.items() if dr == "input"]
    outs = [(n, w) for n, (dr, w) in ports.items() if dr == "output"]
    bits_in = [(n, i, w) for n, w in ins for i in range(w)]
    bit_ref = lambda n, i, w: f"{n}[{i}]" if w > 1 else n
    # pin name of each bit; a bit with no pin (optimised away by Quartus) is not compared
    pin_of = {}
    for n, w in ins + outs:
        for i in range(w):
            pin_of[(n, i)] = pins.get(f"{n}[{i}]") or (pins.get(n) if w == 1 else None)
    miss = [k for k, v in pin_of.items() if v is None or v not in lports]
    tb = [f"`timescale 1ps/1ps", "module tb;"]
    for n, w in ins:
        tb.append(f"  reg [{w-1}:0] {n};")
    for n, w in outs:
        tb.append(f"  wire [{w-1}:0] {n};")
    tb.append(f"  {a.design} u_q ({', '.join(f'.{n}({n})' for n in ports)});")
    lw = []
    for n, w in ins + outs:
        for i in range(w):
            p = pin_of[(n, i)]
            if p and p in lports:
                lw.append((n, i, w, p, ports[n][0]))
    for n, i, w, p, dr in lw:
        if dr == "output":
            tb.append(f"  wire b_{p}; reg seen_{p} = 0;")
        else:
            tb.append(f"  wire b_{p} = {'~' if (a.invert_inputs == 'all' or p in a.invert_inputs.split(',')) else ''}{n}[{i}];")
    tb.append(f"  {a.design}_lifted u_l ({', '.join(f'.{p}(b_{p})' for _n, _i, _w, p, _d in lw)});")
    rnd = random.Random(a.seed)
    tb.append("  integer ok = 0, bad = 0, xs = 0;")
    tb.append("  initial begin")
    for n, w in ins:
        tb.append(f"    {n} = 0;")
    tb.append("    #1000;")
    for _ in range(a.steps):
        for n, w in ins:
            v = 0 if n in zero else rnd.getrandbits(w)
            tb.append(f"    {n} = {w}'d{v};")
        tb.append("    #1000;")
        if a.trace and _ < a.trace:
            sig = [f"{n}" for n, _w in ins] + [f"{n}" for n, _w in outs]
            tb.append('    $display("T ' + " ".join(f"{s}=%b" for s in sig) + " L:" +
                      " ".join(f"{p}=%b" for _n, _i, _w, p, dr in lw if dr == "output") + '", ' +
                      ", ".join(sig + [f"b_{p}" for _n, _i, _w, p, dr in lw if dr == "output"]) + ");")
        for n, i, w, p, dr in lw:
            if dr == "output":
                tb.append(f"    if (^{{{n}[{i}], b_{p}}} === 1'bx) xs = xs + 1; "
                          f"else if ({n}[{i}] === b_{p}) ok = ok + 1; else begin bad = bad + 1; if (!seen_{p}) begin seen_{p} = 1; $display(\"BAD {p}\"); end end")
    tb.append('    $display("RESULT ok=%0d bad=%0d x=%0d", ok, bad, xs);')
    tb.append("    $finish;")
    tb.append("  end")
    tb.append("endmodule")
    (work / "tb.v").write_text("\n".join(tb) + "\n")
    cells = set(re.findall(r"^\s*(cyclonev_\w+|dffeas)\s", vo, re.M))
    if cells - SUPPORTED:
        log(f"{a.design}: unsupported cell types {sorted(cells - SUPPORTED)}: no verdict")
        return 4
    (work / "models.v").write_text(MODELS)
    exe = work / "sim.vvp"
    cmd = ["iverilog", "-g2012", "-o", str(exe), str(work / "tb.v"),
           str(d / "quartus" / "simulation" / "questa" / "build.vo"), str(work / "models.v"), str(PRIMS), str(work / "lifted_r.v")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=IVERILOG_LIMIT_S)
        if r.returncode:
            log(f"{a.design}: iverilog compile failed: {r.stderr.strip()[-400:]}")
            return 2
        r = subprocess.run(["vvp", str(exe)], capture_output=True, text=True, timeout=IVERILOG_LIMIT_S)
    except subprocess.TimeoutExpired:
        log(f"{a.design}: exceeded {IVERILOG_LIMIT_S}s (expected < 10 s): oscillating loop? use --zero")
        return 3
    res = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")]
    for ln in r.stdout.splitlines():
        if ln.startswith("T "):
            log(ln)
    bads = [ln[4:].strip() for ln in r.stdout.splitlines() if ln.startswith("BAD ")]
    log(f"{a.design}: {res[-1] if res else r.stdout[-300:]} steps={a.steps} zero={sorted(zero)} "
        f"uncompared_bits={len(miss)} ({miss[:6]}) bad_pins={bads}")
    return 0 if res and " bad=0 " in res[-1] else 1


if __name__ == "__main__":
    sys.exit(main())
