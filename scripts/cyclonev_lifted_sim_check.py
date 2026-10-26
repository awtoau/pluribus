#!/usr/bin/env python3.15t
"""Functional gate: simulate our lifted Verilog against the Quartus post-fit netlist (build.vo).

- Q = corpus/cyclonev/<d>/quartus/simulation/questa/build.vo on models: our cell models below
  (lcell, io, clkena), Altera's dffeas (altera_primitives.v), the plain vendor RAM/MLAB models
  (cyclonev_atoms.v + altera_lnsim.sv, extracted by cyclonev_lnsim_extract.py) and OUR cyclonev_mac
  (lifters/data/cyclonev_mac_model.v; the vendor DSP atom is encrypted).
- L = lifted Verilog.  Default: re-lifted from decomp.bt with the CURRENT lifter (load.py +
  verilog.py into tmp/simcheck/), never the corpus lifted.v (it can be stale).
- S = the design's src/*.v.  Q vs S validates the models (model check); no S sample = unchecked.
  DSP designs also compare L vs S directly (the DSP model is ours, so Q alone is not independent).
- Stimulus: reset preamble (data all-1, then all-0, clock pulsed), then seeded random vectors;
  clock inputs (feed dffeas/clkena/RAM clk0,clk1) change in a 2nd phase.  Model check counts after the preamble.
- `synthesis full_case` src: RTL sim latches where synthesis does not, so no model check.
- Scoring per output bit per sample, Q vs L:
  ok | wrong (both 0/1, differ) | missing (Q 0/1, L X/Z or no lifted port) | xq (Q X: not scored).
  PASS = ok > 0, wrong == 0, missing == 0, model wrong == 0 (DSP: also L vs S wrong == 0).
- --sim questa: Q on the vendor libraries only (precompiled cyclonev_ver etc., incl. the encrypted
  PLL / DSP atoms; scripts/questa.py); L's cyclonev_mac / RAM instances bind to the vendor atoms too.
  Same stimulus and scoring.  Default (iverilog) sends PLL designs to Questa: their atoms are encrypted.
- PLL: free-running refclk (Quartus reference frequency); the nresync input is a reset held, then
  toggled rarely; data changes and samples sit >= PLL_GUARD_PS from every refclk / VCO half-edge.
  L runs our FPLL model (lifters/data/cyclonev_fpll_model.v); the M/N/C decode is also scored against
  the Quartus defparams.  No Questa -> FAIL.  An atom with no model is FAIL, not skipped.
- Blocking stage of scripts/cyclonev_verify_all.py (`lifted_sim`): any FAIL / ERROR fails the run.
Usage: python3.15t scripts/cyclonev_lifted_sim_check.py [<design> ...] [--all] [--no-relift] [--jobs N]
       [--sim iverilog|questa]
Log: tmp/logs/cyclonev_lifted_sim_check.log
"""
import argparse
import os
import random
import re
import subprocess
import tempfile
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
CORPUS = REPO / "corpus" / "cyclonev"
WORK = REPO / "tmp" / "simcheck"
LOG = REPO / "tmp" / "logs" / "cyclonev_lifted_sim_check.log"
SIMLIB = Path("/mnt/2tb/opt/altera/quartus-25.1/quartus/eda/sim_lib")
PRIMS = SIMLIB / "altera_primitives.v"
DEVICE = "5CEBA4U19C8"
FPLL_MODEL = REPO / "lifters" / "data" / "cyclonev_fpll_model.v"
MAC_MODEL = REPO / "lifters" / "data" / "cyclonev_mac_model.v"
PLL_GUARD_PS = 200   # vendor vs our VCO edges differ by <= a few ps (1 ps rounding); 200 ps keeps samples clear
PLL_SAMPLES = 8      # samples per re-alignment window
PLL_RST_TOGGLE = 16  # reset input toggles with probability 1/16 per window (relock exercised)
MODELS = """`timescale 1ps/1ps
module cyclonev_lcell_comb(dataa,datab,datac,datad,datae,dataf,datag,cin,sharein,combout,sumout,cout,shareout);
  input dataa,datab,datac,datad,datae,dataf,datag,cin,sharein; output combout,sumout,cout,shareout;
  parameter lut_mask = 64'h0, extended_lut = "off", shared_arith = "off", dont_touch = "off", lpm_type = "cyclonev_lcell_comb";
  function lutx(input [5:0] ix); integer k, i; reg r0, r1, m; begin
    if (^ix !== 1'bx) lutx = lut_mask[ix]; else begin   // fast path; X: 1 iff every match agrees
    r0 = 0; r1 = 0;
    for (k = 0; k < 64; k = k + 1) begin
      m = 1;
      for (i = 0; i < 6; i = i + 1) if (ix[i] !== 1'bx && ix[i] !== 1'bz && ix[i] !== k[i]) m = 0;
      if (m) begin if (lut_mask[k]) r1 = 1; else r0 = 1; end
    end
    lutx = (r1 && r0) ? 1'bx : r1;
    end
  end endfunction
  // arithmetic: f0 = mask[15:0](a,b,c,d), f2 = mask[47:32](a,b,c,f), in2 = sharein or !f2
  wire f0 = lutx({2'b00, datad, datac, datab, dataa});
  wire f2 = lutx({2'b10, dataf, datac, datab, dataa});
  wire in2 = (shared_arith == "on") ? sharein : !f2;
  assign combout = lutx({dataf,datae,datad,datac,datab,dataa});
  assign sumout = cin ^ f0 ^ in2;
  assign cout = (cin & f0) | (cin & in2) | (f0 & in2);
  assign shareout = lutx({2'b10, datad, datac, datab, dataa});
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
  parameter ena_register_power_up="high", test_syn="high";
  assign outclk = inclk; assign enaout = ena;
endmodule
"""
SUPPORTED = {"cyclonev_lcell_comb", "cyclonev_io_ibuf", "cyclonev_io_obuf", "cyclonev_clkena", "dffeas",
             "cyclonev_ram_block", "cyclonev_mlab_cell",     # RAM/MLAB: plain vendor models (lnsim extract)
             "cyclonev_mac"}                                 # DSP: our model (lifters/data/cyclonev_mac_model.v)
# Step limits (lift / iverilog / vvp), https://github.com/awto-au/awto-dan/issues/53:
# - STALL_S: no CPU progress for 60 s = hung (primary guard).
# - OVERALL_S: backstop = 3x the measured cold worst step; measurement in awtoau/pluribus#121.
STALL_S = 60
OVERALL_S = 125
STEP_LOG = []       # (tool, seconds) of every finished step
PREAMBLE_CLOCKS = 4  # clock pulses per reset level (all-1, all-0) before the model check starts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heavy_guard  # noqa: E402
# Designs in parallel: RAM-derived (heavy_guard.JOB_GB), capped at 8 so the shared box keeps cores.
JOBS = heavy_guard.workers_for("cyclonev_sim_job", cap=8)
GB_PER_JOB = 0.5    # RAM gate per job; covers a Questa vsim child, whose RSS is unmeasured


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
        m = re.search(rf"^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*{re.escape(n)}\s*;", body, re.M)
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


def clock_inputs(vo, ins):
    """Input ports whose buffered signal is a register clock (directly or through a clkena)."""
    clk_nets = set(re.findall(r"\.(?:clk|clk0|clk1|inclk)\((\\\S+)\s*\)", vo))
    out = set()
    for n, w in ins:
        for i in range(w):
            sig = f"\\{n}[{i}]~input_o" if w > 1 else f"\\{n}~input_o"
            if sig in clk_nets:
                out.add(n)
    return out


def kind_of(vo):
    """Design kind from the atoms in build.vo; the first match wins."""
    if "cyclonev_fractional_pll" in vo:
        return "PLL"
    if re.search(r"^cyclonev_mac\s", vo, re.M):
        return "DSP"
    if re.search(r"^cyclonev_ram_block\s", vo, re.M):
        return "M10K"
    if re.search(r"^cyclonev_mlab_cell\s", vo, re.M):
        return "MLAB"
    reg = bool(re.search(r"^dffeas\s", vo, re.M))
    carry = bool(re.search(r"\.(sumout|cout)\((?!\))", vo))
    return {(0, 0): "combinational", (0, 1): "carry", (1, 0): "registered", (1, 1): "registered+carry"}[(reg, carry)]


def coverage(vo):
    """(covered, reason) from the cell types in build.vo."""
    cells = set(re.findall(r"^\s*(cyclonev_\w+|dffeas\w*)\s", vo, re.M))
    gaps = sorted(cells - SUPPORTED)
    return (not gaps, ",".join(gaps))


def _cpu_s(pid):
    """utime+stime (clock ticks) of a process; None once it is gone."""
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])
    except (OSError, IndexError):
        return None


def run(cmd, env=None, cwd=REPO, overall_s=None):
    """Run a step; kill on STALL (no CPU progress for STALL_S) or on the OVERALL backstop.

    The compile and the sim print nothing until they finish, so output silence cannot show a hang;
    CPU time not advancing does.  Backstop: OVERALL_S (see the limits note at the constants).
    """
    import time
    overall_s = overall_s or OVERALL_S
    out_f = tempfile.TemporaryFile(mode="w+")
    err_f = tempfile.TemporaryFile(mode="w+")
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=out_f, stderr=err_f, text=True)
    t0 = last_t = time.monotonic()
    last_cpu = -1
    why = None
    while p.poll() is None:
        try:
            p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        cpu = _cpu_s(p.pid)
        if cpu is not None and cpu != last_cpu:
            last_cpu, last_t = cpu, now
        if now - last_t > STALL_S:
            why = f"stalled {now - last_t:.0f}s with no CPU progress (limit {STALL_S}s, loadavg {os.getloadavg()[0]:.1f})"
        elif now - t0 > overall_s:
            why = f"exceeded {overall_s}s overall (loadavg {os.getloadavg()[0]:.1f})"
        if why:
            p.kill()
            p.wait()
            return None, f"{Path(str(cmd[0])).name}: {why}"
    out_f.seek(0)
    err_f.seek(0)
    r = subprocess.CompletedProcess(cmd, p.returncode, out_f.read(), err_f.read())
    STEP_LOG.append((Path(str(cmd[0])).name, time.monotonic() - t0))
    return r, None


def oscillator_enables(vo):
    """Input ports that, held at 0, silence a zero-delay inverting self-loop in build.vo.

    An lcell whose own output feeds back so that out_next = !out for some other-input value
    (`q = ~(q & x)`) never settles in a zero-delay sim: Quartus and lifted both spin.  Holding the
    enable input at 0 leaves the loop quiescent; the oscillating phase has no reference to compare.
    """
    out = set()
    for m in re.finditer(r"cyclonev_lcell_comb\s+(\S+)\s*\((.*?)\);(.*?)lut_mask = 64'h([0-9A-Fa-f]+)", vo, re.S):
        body, mask = m.group(2), int(m.group(4), 16)
        co = re.search(r"\.combout\((\\\S+)\s*\)", body)
        if not co:
            continue
        ports = {}
        for letter in "abcdef":
            pm = re.search(rf"\.data{letter}\((!?)\s*(\S+?)\s*\)", body)
            ports[letter] = (pm.group(1) == "!", pm.group(2)) if pm else (False, "gnd")
        selfp = [k for k, (_n, net) in ports.items() if net == co.group(1)]
        if not selfp:
            continue
        free = [k for k, (_n, net) in ports.items() if k not in selfp and net not in ("gnd", "vcc")]

        def oscillates(fixed):
            for bits in range(1 << len(free)):
                val = {k: (ports[k][1] == "vcc") ^ ports[k][0] for k in "abcdef" if k not in free and k not in selfp}
                val.update({k: (bits >> i) & 1 for i, k in enumerate(free)})
                for k in free:
                    if k in fixed:
                        val[k] = fixed[k]

                def nxt(sv):
                    v = dict(val)
                    for k in selfp:
                        v[k] = sv ^ ports[k][0]
                    return (mask >> sum(v[k] << i for i, k in enumerate("abcdef"))) & 1
                if nxt(0) == 1 and nxt(1) == 0:
                    return True
            return False
        if not oscillates({}):
            continue
        for k in free:
            mi = re.match(r"\\(\w+)(?:\[\d+\])?~input_o$", ports[k][1])
            if mi and not oscillates({k: int(ports[k][0])}):    # net 0 = port bit `neg`
                out.add(mi.group(1))
                break
    return out


def relift(design, out):
    """decomp.bt -> load.py -> verilog.py with the current lifter; returns an error string or None."""
    lift_db = out.parent / "lift.db"         # per design: parallel jobs never share a SQLite writer
    if lift_db.exists():
        lift_db.unlink()                      # derived; always rebuilt
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=str(lift_db))
    label = f"simcheck_{design}"
    for name, cmd in (("load", ["python3.15t", "load.py", "--lifter", "cyclonev", "--device", DEVICE,
                                "--label", label, "--config", CORPUS / design / "decomp.bt"]),
                      ("verilog", ["python3.15t", "verilog.py", "--bitstream", label, "--top", design,
                                   "--out", out])):
        r, err = run(cmd, env=env)
        if err or r.returncode:
            return f"{name}: {err or (r.stderr or r.stdout).strip().splitlines()[-1:]}"
    return None


def src_files(d):
    src = sorted((d / "src").glob("*.v")) + sorted((d / "src").glob("*.sv"))
    text = "".join(p.read_text() for p in src)
    libs = []
    if "lpm_" in text:
        libs.append(SIMLIB / "220model.v")
    if re.search(r"\balt\w+\s*#|\bscfifo|\bdcfifo", text):
        libs.append(SIMLIB / "altera_mf.v")
    return src, libs


def testbench(design, ports, pins, lports, ins, outs, clocks, steps, seed, zero, invert, with_src, dsp=False,
              pll=None):
    pin_of = {(n, i): pins.get(f"{n}[{i}]") or (pins.get(n) if w == 1 else None)
              for n, w in ins + outs for i in range(w)}
    lw = [(n, i, w, pin_of[(n, i)], ports[n][0]) for n, w in ins + outs for i in range(w)
          if pin_of[(n, i)] in lports]
    lout = {(n, i): p for n, i, _w, p, dr in lw if dr == "output"}
    tb = ["`timescale 1ps/1ps", "module tb;"]
    tb += [f"  reg [{w-1}:0] {n} = 0;" for n, w in ins]   # defined at t=0: no X->0 edge on a negedge register
    tb += [f"  wire [{w-1}:0] {n}, s_{n};" for n, w in outs]
    tb.append(f"  {design} u_q ({', '.join(f'.{n}({n})' for n in ports)});")
    if with_src:
        tb.append(f"  {design}_src u_s ({', '.join(f'.{n}({n})' if ports[n][0] == 'input' else f'.{n}(s_{n})' for n in ports)});")
    for n, i, w, p, dr in lw:
        if dr == "output":
            tb.append(f"  wire b_{p}; reg seen_{p} = 0;")
        else:
            inv = "~" if (invert == "all" or p in invert.split(",")) else ""
            tb.append(f"  wire b_{p} = {inv}{n}[{i}];")
    tb.append(f"  {design}_lifted u_l ({', '.join(f'.{p}(b_{p})' for _n, _i, _w, p, _d in lw)});")
    tb.append("  integer ok = 0, wrong = 0, missing = 0, xq = 0, m_ok = 0, m_wrong = 0, m_x = 0, ls_ok = 0, ls_wrong = 0;")
    tb.append("  reg mchk = 0;")
    tb.append("  task check; begin")
    for n, w in outs:
        for i in range(w):
            q = f"{n}[{i}]"
            tb.append(f"    if ({q} !== 1'b0 && {q} !== 1'b1) xq = xq + 1;")
            p = lout.get((n, i))
            if p is None:
                tb.append("    else missing = missing + 1;")
            else:
                tb.append(f"    else if (b_{p} !== 1'b0 && b_{p} !== 1'b1) missing = missing + 1;"
                          f" else if ({q} === b_{p}) ok = ok + 1;"
                          f" else begin wrong = wrong + 1; if (!seen_{p}) begin seen_{p} = 1; $display(\"BAD {p}\"); end end")
            if with_src and dsp and p is not None:       # DSP: lifted vs the design's own RTL (model-independent)
                tb.append(f"    if (mchk && ^{{b_{p}, s_{n}[{i}]}} !== 1'bx) begin"
                          f" if (b_{p} === s_{n}[{i}]) ls_ok = ls_ok + 1; else ls_wrong = ls_wrong + 1; end")
            if with_src:
                tb.append(f"    if (!mchk) ; else if (^{{{q}, s_{n}[{i}]}} === 1'bx) m_x = m_x + 1;"
                          f" else if ({q} === s_{n}[{i}]) m_ok = m_ok + 1; else m_wrong = m_wrong + 1;")
    tb.append("  end endtask")
    rnd = random.Random(seed)
    if pll:
        tb += pll_stimulus(ins, zero, steps, rnd, pll)
        tb += ["    $finish;", "  end", "endmodule"]
        return "\n".join(tb) + "\n", sum(1 for k in pin_of if k[0] in dict(outs) and lout.get(k) is None)
    data = [(n, w) for n, w in ins if n not in clocks]
    clk = [(n, w) for n, w in ins if n in clocks]
    tb.append("  initial begin")
    tb += [f"    {n} = 0;" for n, _w in ins]
    tb.append("    #1000; check;")
    # preamble: data all-1 then all-0 with clock pulses (applies an active-high or active-low reset);
    # the model check starts after it: src regs are X until reset, Quartus regs power up 0
    for level in (1, 0):
        for _ in range(PREAMBLE_CLOCKS):
            for n, w in data:
                tb.append(f"    {n} = {0 if n in zero else (1 << w) - 1 if level else 0};")
            tb.append("    #1000; check;")          # data settles before the clock edge (no race)
            for v in ((1, 0) if clk else ()):
                tb += [f"    {n} = {v if v == 0 else (1 << w) - 1};" for n, w in clk]
                tb.append("    #1000; check;")
    tb.append("    mchk = 1;")
    for _ in range(steps):
        for group in (data, clk):
            if not group:
                continue
            for n, w in group:
                tb.append(f"    {n} = {w}'d{0 if n in zero else rnd.getrandbits(w)};")
            tb.append("    #1000; check;")
    tb.append('    $display("RESULT ok=%0d wrong=%0d missing=%0d xq=%0d model_ok=%0d model_wrong=%0d model_x=%0d ls_ok=%0d ls_wrong=%0d",'
              ' ok, wrong, missing, xq, m_ok, m_wrong, m_x, ls_ok, ls_wrong);')
    tb += ["    $finish;", "  end", "endmodule"]
    return "\n".join(tb) + "\n", sum(1 for k in pin_of if k[0] in dict(outs) and lout.get(k) is None)


def _freq_mhz(t):
    v, u = re.match(r"([\d.]+)\s*(\w+)", t).groups()
    return float(v) * {"mhz": 1.0, "ghz": 1e3, "khz": 1e-3}[u.lower()]


def pll_timing(vo, ins):
    """Stimulus timing for a PLL design -> dict, or (None, reason).

    refclk / reset inputs: ports whose buffer feeds the refclk_select clkin / FRACTIONAL_PLL nresync.
    Window W = NR refclk periods (VCO re-aligns to refclk every NR = N / gcd(M, N)); one data change and
    PLL_SAMPLES samples per window, each >= PLL_GUARD_PS from every refclk and VCO half-edge.
    """
    from fractions import Fraction
    from math import gcd
    ref = _freq_mhz(re.search(r"FRACTIONAL_PLL \.reference_clock_frequency = \"([^\"]+)\"", vo).group(1))
    vco = _freq_mhz(re.search(r"FRACTIONAL_PLL \.output_clock_frequency = \"([^\"]+)\"", vo).group(1))
    period = round(1e6 / ref)
    if abs(period - 1e6 / ref) > 1e-6:
        return None, f"refclk period {1e6 / ref} ps is not whole"
    ratio = Fraction(vco / ref).limit_denominator(64)
    nr, mr = ratio.denominator, ratio.numerator
    win = nr * period
    edges = [k * period / 2 for k in range(2 * nr + 1)] + [j * win / (2 * mr) for j in range(2 * mr + 1)]
    score = lambda t: min(abs(t - e) for e in edges)
    k = PLL_SAMPLES + 1
    picks = []
    for i in range(k):
        lo, hi = int(i * win / k), int((i + 1) * win / k)
        best = max(range(lo, hi), key=score)
        if score(best) < PLL_GUARD_PS:
            return None, f"no sample slot >= {PLL_GUARD_PS} ps from the clock edges in [{lo}, {hi})"
        picks.append(best)

    def feeding(nets):
        return {n for n, w in ins for i in range(w)
                if (f"\\{n}[{i}]~input_o" if w > 1 else f"\\{n}~input_o") in nets}
    refclk = feeding({x for m in re.finditer(r"\.clkin\(\{([^}]*)\}\)", vo)
                      for x in re.findall(r"(\\\S+~input_o)", m.group(1))})
    rst = feeding(set(re.findall(r"\.nresync\((\\\S+)\s*\)", vo)))
    if not refclk:
        return None, "no refclk input found"
    return {"period": period, "win": win, "change": picks[0], "samples": picks[1:], "refclk": refclk,
            "rst": rst - refclk, "mr": mr, "nr": nr}, None


def pll_stimulus(ins, zero, steps, rnd, t):
    """Stimulus lines for a PLL design (see pll_timing); same preamble levels as the generic one."""
    p, w = t["period"], t["win"]
    out = []
    for r in sorted(t["refclk"]):
        out.append(f"  always begin {r} = 1; #{p // 2}; {r} = 0; #{p - p // 2}; end")
    data = [(n, wd) for n, wd in ins if n not in t["refclk"]]
    out.append("  initial begin")
    level = {}

    def window(values):
        lines = [f"    #{t['change']};"]
        lines += [f"    {n} = {wd}'d{0 if n in zero else values[n]};" for n, wd in data]
        last = t["change"]
        for s in t["samples"]:
            lines.append(f"    #{s - last}; check;")
            last = s
        lines.append(f"    #{w - last};")
        return lines
    for lv in (1, 0):
        for _ in range(PREAMBLE_CLOCKS):
            level = {n: (1 << wd) - 1 if lv else 0 for n, wd in data}
            out += window(level)
    out.append("    mchk = 1;")
    for _ in range(steps):
        for n, wd in data:
            if n in t["rst"]:
                if rnd.randrange(PLL_RST_TOGGLE) == 0:
                    level[n] = level[n] ^ ((1 << wd) - 1)
            else:
                level[n] = rnd.getrandbits(wd)
        out += window(level)
    out.append('    $display("RESULT ok=%0d wrong=%0d missing=%0d xq=%0d model_ok=%0d model_wrong=%0d model_x=%0d ls_ok=%0d ls_wrong=%0d",'
               ' ok, wrong, missing, xq, m_ok, m_wrong, m_x, ls_ok, ls_wrong);')
    return out


def simulate(sim, work, files, with_src):
    """Compile + run -> (status, stdout_lines, err).  status: "ok" | "compile" (failed) | "run" (failed)."""
    if sim == "questa":
        import questa
        stage, ok, text = questa.compile_and_run(work / "questa", files, "tb")
        lines = [ln[2:] if ln.startswith("# ") else ln for ln in text.splitlines()]
        if stage == "vlog" and not ok:
            err = [ln for ln in lines if "Error" in ln]
            return "compile", lines, "vlog: " + (err[0] if err else text[-300:]).strip()
        if not ok and not any(ln.startswith("RESULT") for ln in lines):
            err = [ln for ln in lines if "Error" in ln or "Fatal" in ln or "KILLED" in ln]
            return "run", lines, f"{stage}: " + (err[0] if err else text[-300:]).strip()
        return "ok", lines, None
    r, err = run(["iverilog", "-g2012", "-o", work / "sim.vvp"] + files)
    if err:
        return "run", [], f"iverilog {err}"
    if r.returncode:
        return "compile", [], f"iverilog: {r.stderr.strip()[-300:]}"
    r, err = run(["vvp", work / "sim.vvp"])
    if err:
        return "run", [], f"vvp {err} (oscillating loop? --zero)"
    return "ok", r.stdout.splitlines(), None


def check_design(design, steps=2000, seed=1, zero=(), invert="", do_relift=True, sim="iverilog"):
    """One design -> result dict; status PASS | FAIL | NOT_BUILT | ERROR."""
    d = CORPUS / design
    res = {"design": design, "status": "ERROR", "reason": "", "ok": 0, "wrong": 0, "missing": 0,
           "xq": 0, "model_ok": 0, "model_wrong": 0, "model_x": 0, "kind": "", "ls_ok": 0, "ls_wrong": 0, "pll_ok": 0, "pll_wrong": 0, "model": "unchecked", "bad_pins": []}
    vo_path = d / "quartus" / "simulation" / "questa" / "build.vo"
    if not vo_path.is_file() or not (d / "decomp.bt").is_file():
        res.update(status="NOT_BUILT", reason="no build.vo / decomp.bt")
        return res
    vo = vo_path.read_text()
    res["kind"] = kind_of(vo)
    covered, gaps = coverage(vo)
    pll = "cyclonev_fractional_pll" in vo
    if pll:
        sim = "questa"                  # vendor PLL atoms are encrypted: only Questa runs them
    if sim == "questa":
        import questa
        if not questa.available():
            res.update(status="FAIL", reason="needs Questa (encrypted vendor atoms); not installed / no licence")
            return res
    elif not covered:
        res.update(status="FAIL", reason=f"no simulation model for {gaps}")
        return res
    res["sim"] = sim
    work = WORK / design
    work.mkdir(parents=True, exist_ok=True)
    lifted_path = work / "lifted.v"
    if do_relift:
        err = relift(design, lifted_path)
        if err:
            res["reason"] = f"relift {err}"
            return res
    else:
        lifted_path = d / "lifted.v"
    lifted = lifted_path.read_text()
    (work / "lifted_r.v").write_text(re.sub(rf"\bmodule {design}\b", f"module {design}_lifted", lifted, count=1))
    ports = ports_of_vo(vo, design)
    pins = pin_map((d / "build.pin").read_text())
    lports = set(re.findall(r"^\s*(?:input|output|inout)\s+wire\s+(\w+)", lifted, re.M))
    ins = [(n, w) for n, (dr, w) in ports.items() if dr == "input"]
    outs = [(n, w) for n, (dr, w) in ports.items() if dr == "output"]
    clocks = clock_inputs(vo, ins)
    osc = oscillator_enables(vo)
    if osc:
        zero = tuple(zero) + tuple(sorted(osc))
        res["osc"] = ",".join(sorted(osc))
    timing = None
    if pll:
        res.update(pll_decode_score(vo, lifted))
        timing, why = pll_timing(vo, ins)
        if timing is None:
            res.update(status="FAIL", reason=f"PLL stimulus: {why}")
            return res
    (work / "models.v").write_text(MODELS)
    src, libs = src_files(d)
    if re.search(r"synthesis\s+full_case", "".join(p.read_text() for p in src)):
        src = []                    # full_case: RTL sim latches where synthesis does not; not a reference
        res["model"] = "src full_case (no reference)"
    (work / "src_r.v").write_text(re.sub(rf"\bmodule {design}\b", f"module {design}_src",
                                         "".join(p.read_text() + "\n" for p in src), count=1))
    dsp = bool(re.search(r"^\s*cyclonev_mac\s", vo, re.M))
    if sim == "questa":             # every atom from the vendor libraries; only our FPLL model added
        base = [work / "tb.v", vo_path, work / "lifted_r.v"]
        libs = []                   # altera_mf / lpm / altera_lnsim: precompiled -L libraries
    else:
        base = [work / "tb.v", vo_path, work / "models.v", PRIMS, work / "lifted_r.v"]
        if re.search(r"^\s*cyclonev_(ram_block|mlab_cell)\s", vo, re.M):
            import cyclonev_lnsim_extract
            base.append(cyclonev_lnsim_extract.extract(out=work / "lnsim_extract.sv", log=lambda m: None))
        if dsp:
            base.append(MAC_MODEL)
    if "pluribus_cv_fpll" in lifted:
        base.append(FPLL_MODEL)
    compiled = None
    lines = []
    for with_src in ((True, False) if src else (False,)):
        tb, n_unported = testbench(design, ports, pins, lports, ins, outs, clocks, steps, seed,
                                   set(zero), invert, with_src, dsp, timing)
        (work / "tb.v").write_text(tb)
        files = base + ([work / "src_r.v"] + libs if with_src else [])
        status, lines, err = simulate(sim, work, files, with_src)
        if status == "ok":
            compiled = with_src
            break
        if status == "run" or not with_src:
            res["reason"] = err
            return res
        res["model"] = "src not simulable"
    line = next((ln for ln in lines if ln.startswith("RESULT")), None)
    if line is None:
        res["reason"] = f"{sim}: no RESULT: {' | '.join(lines[-4:])[-300:]}"
        return res
    res.update({k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)})
    res["bad_pins"] = [ln[4:].strip() for ln in lines if ln.startswith("BAD ")]
    res["unported_out_bits"] = n_unported
    if compiled:
        res["model"] = ("WRONG" if res["model_wrong"] else "ok" if res["model_ok"] else "no comparable sample")
    fail = []
    if res["wrong"] or res["missing"]:
        fail.append("lifted")
    if res["model_wrong"]:
        fail.append("model")
    if dsp and (not compiled or res["ls_wrong"] or not res["ls_ok"]):
        fail.append("lifted vs src")        # DSP: the model is ours, so the reference is the design's own RTL
    if pll and res["pll_wrong"]:
        fail.append("PLL decode")
    if not res["ok"]:
        fail.append("nothing compared")
    res["status"] = "FAIL" if fail else "PASS"
    res["reason"] = ",".join(fail)
    return res


def pll_oracle(vo):
    """{counter index: out/ref frequency ratio} from the Quartus defparams of the PLL atoms."""
    ref = _freq_mhz(re.search(r"FRACTIONAL_PLL \.reference_clock_frequency = \"([^\"]+)\"", vo).group(1))
    out = {}
    for m in re.finditer(r"PLL_OUTPUT_COUNTER \.output_clock_frequency = \"([^\"]+)\"", vo):
        idx = re.search(r"PLL_OUTPUT_COUNTER \.output_counter_index = (\d+)", vo[m.end():]).group(1)
        out[int(idx)] = _freq_mhz(m.group(1)) / ref
    return out


def pll_decode_score(vo, lifted):
    """Lifted `decode: M= N= Cc=` comment vs the Quartus defparams -> {pll_ok, pll_wrong} (per counter)."""
    m = re.search(r"decode: M=(\d+) N=(\d+)((?: C\d+=\d+)+)", lifted)
    oracle = pll_oracle(vo)
    ok = wrong = 0
    if m:
        mm, nn = int(m.group(1)), int(m.group(2))
        got = {int(c): int(v) for c, v in re.findall(r"C(\d+)=(\d+)", m.group(3))}
        for idx, ratio in oracle.items():
            if idx in got and abs(mm / nn / got[idx] - ratio) < 1e-9:
                ok += 1
            else:
                wrong += 1
        wrong += len(set(got) - set(oracle))
    else:
        wrong = len(oracle)
    return {"pll_ok": ok, "pll_wrong": wrong}


def fmt(r):
    tot = r["ok"] + r["wrong"] + r["missing"]
    return (f"{r['status']:11s} {r['design']:28s} matched {r['ok']}/{tot} wrong={r['wrong']} "
            f"missing={r['missing']} xq={r['xq']} model={r['model']}"
            f"({r['model_ok']}/{r['model_ok'] + r['model_wrong']})"
            + (f" lifted-vs-src={r['ls_ok']}/{r['ls_ok'] + r['ls_wrong']}" if r["ls_ok"] or r["ls_wrong"] else "")
            + (f" sim={r['sim']}" if r.get("sim") else "")
            + (f" pll-decode={r['pll_ok']}/{r['pll_ok'] + r['pll_wrong']}" if r["pll_ok"] or r["pll_wrong"] else "")
            + f" {r['reason']}"
            + (f" [zero-delay oscillator: input(s) {r['osc']} held 0]" if r.get("osc") else "")
            + (f" bad_pins={r['bad_pins'][:8]}" if r["bad_pins"] else ""))


def all_designs():
    return sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").is_file())


def run_gate(designs, steps=2000, seed=1, do_relift=True, jobs=JOBS, logf=log, sim="iverilog"):
    """Every design -> list of results; caller decides pass/fail (any FAIL / ERROR = gate fails)."""
    from concurrent.futures import ThreadPoolExecutor
    WORK.mkdir(parents=True, exist_ok=True)

    def one(dsg):
        r = check_design(dsg, steps=steps, seed=seed, do_relift=do_relift, sim=sim)
        logf(fmt(r))
        return r
    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(one, designs))


def run_guarded(designs, steps=2000, seed=1, do_relift=True, jobs=JOBS, logf=log, sim="iverilog"):
    """run_gate under heavy_guard: one heavy batch at a time, RAM for `jobs` lift+sim processes."""
    import logging
    from heavy_guard import heavy_lock, wait_available
    lg = logging.getLogger("cyclonev_lifted_sim_check")
    with heavy_lock("cyclonev_lifted_sim_check", lg):
        wait_available(lg, "cyclonev_lifted_sim_check", min_gb=jobs * GB_PER_JOB)
        return run_gate(designs, steps, seed, do_relift, jobs, logf, sim)


KINDS = ("combinational", "carry", "registered", "registered+carry", "M10K", "MLAB", "DSP", "PLL")


def summary(results, logf=log):
    from collections import Counter
    st = Counter(r["status"] for r in results)
    cov = [r for r in results if r["status"] in ("PASS", "FAIL")]
    ok = sum(r["ok"] for r in cov)
    wrong = sum(r["wrong"] for r in cov)
    miss = sum(r["missing"] for r in cov)
    worst = {}
    for tool, sec in STEP_LOG:
        worst[tool] = max(worst.get(tool, 0), sec)
    logf("slowest step per tool (s): " + ", ".join(f"{k} {v:.1f}" for k, v in sorted(worst.items())))
    logf(f"designs: {dict(st)}")
    logf(f"samples (simulated designs): matched {ok}/{ok + wrong + miss} = "
         f"{100 * ok / max(1, ok + wrong + miss):.1f}%  wrong={wrong} missing={miss}")
    logf("per kind: pass / fail / error / not built (matched / samples; wrong; missing)")
    for k in KINDS:
        rs = [r for r in results if r["kind"] == k]
        if not rs:
            continue
        n = Counter(r["status"] for r in rs)
        o, w, m = (sum(r[f] for r in rs) for f in ("ok", "wrong", "missing"))
        logf(f"  {k:17s} {n['PASS']:4d} / {n['FAIL']:3d} / {n['ERROR']:3d} / {n['NOT_BUILT']:3d}"
             f"   {o}/{o + w + m}; wrong {w}; missing {m}")
    pk = [r for r in results if r["kind"] == "PLL"]
    if pk:
        logf(f"  PLL frequency decode: {sum(r['pll_ok'] for r in pk)}/"
             f"{sum(r['pll_ok'] + r['pll_wrong'] for r in pk)} output counters match Quartus")
    return st.get("FAIL", 0) == 0 and st.get("ERROR", 0) == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--all", action="store_true", help="every corpus design (gate mode)")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--zero", default="", help="comma list of input signals held at 0 (single design)")
    ap.add_argument("--no-relift", action="store_true", help="use corpus lifted.v instead of re-lifting")
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--sim", choices=("iverilog", "questa"), default="iverilog",
                    help="questa: Quartus netlist on the vendor libraries (PLL designs always use questa)")
    ap.add_argument("--invert-inputs", default="",
                    help="comma list of lifted pins driven complemented, or all (diagnostic, single design)")
    a = ap.parse_args()
    designs = all_designs() if a.all or not a.designs else a.designs
    if len(designs) == 1:
        r = check_design(designs[0], a.steps, a.seed, tuple(filter(None, a.zero.split(","))),
                         a.invert_inputs, not a.no_relift, a.sim)
        log(fmt(r))
        return 0 if r["status"] == "PASS" else 1
    import logging
    logging.basicConfig(level=logging.INFO)
    log(f"== sim backend: {a.sim}")
    results = run_guarded(designs, a.steps, a.seed, not a.no_relift, a.jobs, sim=a.sim)
    return 0 if summary(results) else 1


if __name__ == "__main__":
    sys.exit(main())
