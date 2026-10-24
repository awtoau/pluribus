#!/usr/bin/env python3.15t
"""Functional gate: simulate our lifted Verilog against the Quartus post-fit netlist (build.vo).

- Q = corpus/cyclonev/<d>/quartus/simulation/questa/build.vo + the models below (vendor
  cyclonev_atoms.v is encrypted).  dffeas = Altera's own altera_primitives.v.
- L = lifted Verilog.  Default: re-lifted from decomp.bt with the CURRENT lifter (load.py +
  verilog.py into tmp/simcheck/), never the corpus lifted.v (it can be stale).
- S = the design's src/*.v.  Q vs S validates the models (model check); no S sample = unchecked.
- Stimulus: reset preamble (data all-1, then all-0, clock pulsed), then seeded random vectors;
  clock inputs (feed dffeas/clkena) change in a 2nd phase.  Model check counts after the preamble.
- `synthesis full_case` src: RTL sim latches where synthesis does not, so no model check.
- Scoring per output bit per sample, Q vs L:
  ok | wrong (both 0/1, differ) | missing (Q 0/1, L X/Z or no lifted port) | xq (Q X: not scored).
  PASS = ok > 0, wrong == 0, missing == 0, model wrong == 0.
- Not covered (no model; Quartus atom encrypted): RAM (ram_block, mlab_cell), DSP (mac),
  PLL / other hard IP.  Carry (arith lcell) and registers ARE covered.
- Blocking stage of scripts/cyclonev_verify_all.py (`lifted_sim`): any FAIL / ERROR fails the run.
Usage: python3.15t scripts/cyclonev_lifted_sim_check.py [<design> ...] [--all] [--no-relift] [--jobs N]
Log: tmp/logs/cyclonev_lifted_sim_check.log
"""
import argparse
import os
import random
import re
import subprocess
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
SUPPORTED = {"cyclonev_lcell_comb", "cyclonev_io_ibuf", "cyclonev_io_obuf", "cyclonev_clkena", "dffeas"}
NOT_COVERED = {"cyclonev_ram_block": "RAM", "cyclonev_mlab_cell": "RAM", "cyclonev_mac": "DSP"}
STEP_LIMIT_S = 60   # each lift / compile / sim step: < 10 s on a corpus design; 60 s = hung
PREAMBLE_CLOCKS = 4  # clock pulses per reset level (all-1, all-0) before the model check starts
JOBS = 4          # designs in parallel; each is a chain of small subprocesses
GB_PER_JOB = 0.5    # peak child RSS of one design is ~0.06 GB (load.py); RAM gate per job


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
    clk_nets = set(re.findall(r"\.clk\((\\\S+)\s*\)", vo)) | set(re.findall(r"\.inclk\((\\\S+)\s*\)", vo))
    out = set()
    for n, w in ins:
        for i in range(w):
            sig = f"\\{n}[{i}]~input_o" if w > 1 else f"\\{n}~input_o"
            if sig in clk_nets:
                out.add(n)
    return out


def coverage(vo):
    """(covered, reason) from the cell types in build.vo."""
    cells = set(re.findall(r"^\s*(cyclonev_\w+|dffeas\w*)\s", vo, re.M))
    gaps = sorted({NOT_COVERED.get(c, "PLL" if "pll" in c else c) for c in cells - SUPPORTED})
    return (not gaps, ",".join(gaps))


def run(cmd, env=None, cwd=REPO):
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=STEP_LIMIT_S)
    except subprocess.TimeoutExpired:
        return None, f"exceeded {STEP_LIMIT_S}s"
    return r, None


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


def testbench(design, ports, pins, lports, ins, outs, clocks, steps, seed, zero, invert, with_src):
    pin_of = {(n, i): pins.get(f"{n}[{i}]") or (pins.get(n) if w == 1 else None)
              for n, w in ins + outs for i in range(w)}
    lw = [(n, i, w, pin_of[(n, i)], ports[n][0]) for n, w in ins + outs for i in range(w)
          if pin_of[(n, i)] in lports]
    lout = {(n, i): p for n, i, _w, p, dr in lw if dr == "output"}
    tb = ["`timescale 1ps/1ps", "module tb;"]
    tb += [f"  reg [{w-1}:0] {n};" for n, w in ins]
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
    tb.append("  integer ok = 0, wrong = 0, missing = 0, xq = 0, m_ok = 0, m_wrong = 0, m_x = 0;")
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
            if with_src:
                tb.append(f"    if (!mchk) ; else if (^{{{q}, s_{n}[{i}]}} === 1'bx) m_x = m_x + 1;"
                          f" else if ({q} === s_{n}[{i}]) m_ok = m_ok + 1; else m_wrong = m_wrong + 1;")
    tb.append("  end endtask")
    rnd = random.Random(seed)
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
    tb.append('    $display("RESULT ok=%0d wrong=%0d missing=%0d xq=%0d model_ok=%0d model_wrong=%0d model_x=%0d",'
              ' ok, wrong, missing, xq, m_ok, m_wrong, m_x);')
    tb += ["    $finish;", "  end", "endmodule"]
    return "\n".join(tb) + "\n", sum(1 for k in pin_of if k[0] in dict(outs) and lout.get(k) is None)


def check_design(design, steps=2000, seed=1, zero=(), invert="", do_relift=True):
    """One design -> result dict; status PASS | FAIL | NOT_COVERED | NOT_BUILT | ERROR."""
    d = CORPUS / design
    res = {"design": design, "status": "ERROR", "reason": "", "ok": 0, "wrong": 0, "missing": 0,
           "xq": 0, "model_ok": 0, "model_wrong": 0, "model_x": 0, "model": "unchecked", "bad_pins": []}
    vo_path = d / "quartus" / "simulation" / "questa" / "build.vo"
    if not vo_path.is_file() or not (d / "decomp.bt").is_file():
        res.update(status="NOT_BUILT", reason="no build.vo / decomp.bt")
        return res
    vo = vo_path.read_text()
    covered, gaps = coverage(vo)
    if not covered:
        res.update(status="NOT_COVERED", reason=gaps)
        return res
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
    (work / "models.v").write_text(MODELS)
    src, libs = src_files(d)
    if re.search(r"synthesis\s+full_case", "".join(p.read_text() for p in src)):
        src = []                    # full_case: RTL sim latches where synthesis does not; not a reference
        res["model"] = "src full_case (no reference)"
    (work / "src_r.v").write_text(re.sub(rf"\bmodule {design}\b", f"module {design}_src",
                                         "".join(p.read_text() + "\n" for p in src), count=1))
    base = [work / "tb.v", vo_path, work / "models.v", PRIMS, work / "lifted_r.v"]
    compiled = None
    for with_src in ((True, False) if src else (False,)):
        tb, n_unported = testbench(design, ports, pins, lports, ins, outs, clocks, steps, seed,
                                   set(zero), invert, with_src)
        (work / "tb.v").write_text(tb)
        files = base + ([work / "src_r.v"] + libs if with_src else [])
        r, err = run(["iverilog", "-g2012", "-o", work / "sim.vvp"] + files)
        if err:
            res["reason"] = f"iverilog {err}"
            return res
        if r.returncode == 0:
            compiled = with_src
            break
        if not with_src:
            res["reason"] = f"iverilog: {r.stderr.strip()[-300:]}"
            return res
        res["model"] = "src not simulable"
    r, err = run(["vvp", work / "sim.vvp"])
    if err:
        res["reason"] = f"vvp {err} (oscillating loop? --zero)"
        return res
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")), None)
    if line is None:
        res["reason"] = f"vvp: no RESULT: {r.stdout[-300:]}"
        return res
    res.update({k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)})
    res["bad_pins"] = [ln[4:].strip() for ln in r.stdout.splitlines() if ln.startswith("BAD ")]
    res["unported_out_bits"] = n_unported
    if compiled:
        res["model"] = ("WRONG" if res["model_wrong"] else "ok" if res["model_ok"] else "no comparable sample")
    fail = []
    if res["wrong"] or res["missing"]:
        fail.append("lifted")
    if res["model_wrong"]:
        fail.append("model")
    if not res["ok"]:
        fail.append("nothing compared")
    res["status"] = "FAIL" if fail else "PASS"
    res["reason"] = ",".join(fail)
    return res


def fmt(r):
    tot = r["ok"] + r["wrong"] + r["missing"]
    return (f"{r['status']:11s} {r['design']:28s} matched {r['ok']}/{tot} wrong={r['wrong']} "
            f"missing={r['missing']} xq={r['xq']} model={r['model']}"
            f"({r['model_ok']}/{r['model_ok'] + r['model_wrong']}) {r['reason']}"
            + (f" bad_pins={r['bad_pins'][:8]}" if r["bad_pins"] else ""))


def all_designs():
    return sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").is_file())


def run_gate(designs, steps=2000, seed=1, do_relift=True, jobs=JOBS, logf=log):
    """Every design -> list of results; caller decides pass/fail (any FAIL / ERROR = gate fails)."""
    from concurrent.futures import ThreadPoolExecutor
    WORK.mkdir(parents=True, exist_ok=True)

    def one(dsg):
        r = check_design(dsg, steps=steps, seed=seed, do_relift=do_relift)
        logf(fmt(r))
        return r
    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(one, designs))


def run_guarded(designs, steps=2000, seed=1, do_relift=True, jobs=JOBS, logf=log):
    """run_gate under heavy_guard: one heavy batch at a time, RAM for `jobs` lift+sim processes."""
    import logging
    from heavy_guard import heavy_lock, wait_available
    lg = logging.getLogger("cyclonev_lifted_sim_check")
    with heavy_lock("cyclonev_lifted_sim_check", lg):
        wait_available(lg, "cyclonev_lifted_sim_check", min_gb=jobs * GB_PER_JOB)
        return run_gate(designs, steps, seed, do_relift, jobs, logf)


def summary(results, logf=log):
    from collections import Counter
    st = Counter(r["status"] for r in results)
    nc = Counter(r["reason"] for r in results if r["status"] == "NOT_COVERED")
    cov = [r for r in results if r["status"] in ("PASS", "FAIL")]
    ok = sum(r["ok"] for r in cov)
    wrong = sum(r["wrong"] for r in cov)
    miss = sum(r["missing"] for r in cov)
    logf(f"designs: {dict(st)}  not covered by kind: {dict(nc)}")
    logf(f"samples (covered designs): matched {ok}/{ok + wrong + miss} = "
         f"{100 * ok / max(1, ok + wrong + miss):.1f}%  wrong={wrong} missing={miss}")
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
    ap.add_argument("--invert-inputs", default="",
                    help="comma list of lifted pins driven complemented, or all (diagnostic, single design)")
    a = ap.parse_args()
    designs = all_designs() if a.all or not a.designs else a.designs
    if len(designs) == 1:
        r = check_design(designs[0], a.steps, a.seed, tuple(filter(None, a.zero.split(","))),
                         a.invert_inputs, not a.no_relift)
        log(fmt(r))
        return 0 if r["status"] == "PASS" else 1
    import logging
    logging.basicConfig(level=logging.INFO)
    results = run_guarded(designs, a.steps, a.seed, not a.no_relift, a.jobs)
    return 0 if summary(results) else 1


if __name__ == "__main__":
    sys.exit(main())
