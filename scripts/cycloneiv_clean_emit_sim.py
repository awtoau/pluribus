#!/usr/bin/env python3.15t
"""Functional equivalence of the clean emit (lifters/cycloneiv_clean/emit.py) against the Quartus post-fit simulation netlist (#165).

  python3.15t scripts/cycloneiv_clean_emit_sim.py --names gx150_rb_000,... [--stride N --limit N] [--cycles 300] [--tag T]
Per design: iverilog compiles TB + emitted module + postfit.vo + Quartus eda/sim_lib/cycloneiv_atoms.v; the TB applies the same random vectors
(fixed seed) to both and compares every comparable output after each rising edge.
  comparable output  GT output port whose ball is an emitted output pad with a decoded driver; the rest are counted (not compared, not passed).
  inputs             GT input ports <-> emitted `pad_<ball>`; GT clock ports (input feeding a clkctrl) drive one shared clock.
  port correspondence for the clock-buffer sources (emitted `u_clkbuf_out_*` / `u_clk_buffer_*`, ball not mapped by the decoders) is read from the
                     GT routing.rcf (root element of net `<port>~inputclkctrl` / `<port>~input`): oracle-supplied, reported as such.
  all other undecoded source inputs are tied 0.
Result per design: pass (comparable > 0, 0 mismatching outputs), fail (a mismatch), none (no comparable output); features of every failing
design are enumerated (GT FF controls non-idle = undecoded in the emit, HIO output pads, ...).  Log tmp/logs/cycloneiv_clean_emit_sim.log.
"""
import argparse
import collections
import concurrent.futures as cf
import glob
import json
import logging
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_emit_sim")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_emit_sim.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
WORK = os.path.join(OUT, "emit_sim")
ATOMS = "/mnt/2tb/opt/altera/quartus-25.1/quartus/eda/sim_lib/cycloneiv_atoms.v"       # Quartus 25.1 simulation library (vendor)
PRIMS = "/mnt/2tb/opt/altera/quartus-25.1/quartus/eda/sim_lib/altera_primitives.v"     # dffeas
ATOMS_NOPLL = os.path.join(WORK, "cycloneiv_atoms_nopll.v")   # regenerated when HOLD_SAFE changes (file name carries the mode)


def sim_libs():
    """cycloneiv_atoms.v without the cycloneiv_pll module (iverilog rejects its scalar/vector port declarations); derived, regenerated if missing."""
    if not os.path.exists(ATOMS_NOPLL):
        text = open(ATOMS).read()
        a, b = text.index("module cycloneiv_pll (inclk"), text.rindex("endmodule // cycloneiv_pll") + len("endmodule // cycloneiv_pll")
        text = text[:a] + text[b:]
        for pin in ("combout", "cout") if HOLD_SAFE else ():          # 1 ps lcell output delay (hold-safe GT, see HALF)
            text = text.replace(f"and ({pin}, {pin}_tmp, 1'b1) ;", f"and #1 ({pin}, {pin}_tmp, 1'b1) ;")
        open(ATOMS_NOPLL, "w").write(text)
    return [ATOMS_NOPLL, PRIMS]



# hold-safe GT: lcell outputs delayed 1 ps (zero-delay GT samples data that is derived from the clock pad after the edge: delta race, verified on rb_118);
# TB half period HALF ps >> the deepest LUT path
HALF = 10
HOLD_SAFE = False          # --hold-safe: HALF 2000, lcell outputs delayed 1 ps in the GT library and -DLUT_DELAY=#1 in the emit
WARMUP = 6                  # cycles before comparing: FF pipelines settle (power-up 0 in both models)
# iverilog compile of a 5 k-cell post-fit netlist + run of 300 cycles measured ~1-2 s; 3x worst cold = stall backstop
RUN_LIMIT_S = 120


def run_tool(cmd):
    """iverilog/vvp under the repo guard (60 s stall, RUN_LIMIT_S overall); returncode -9 and .timed_out on expiry (#122)."""
    import heavy_guard
    return heavy_guard.guarded(cmd, os.path.basename(cmd[0]), log, overall_s=RUN_LIMIT_S)


def vo_ports(path):
    """-> (top, ins, outs, buses): ins / outs are bit-expanded names (`da[3]` for a bus bit), buses = {name: width} (scalar ports are not in it)."""
    t = open(path).read()
    m = re.search(r"^module (\w+)", t, re.M)
    head = t[t.index("module "):t.index(");", t.index("module "))]
    ports = {p.strip() for p in head[head.index("(") + 1:].replace("\n", " ").split(",")}
    ins, outs, buses = [], [], {}
    for kind, hi, lo, name in re.findall(r"^(input|output)\s*(?:\[(\d+):(\d+)\])?\s*(\S+);", t, re.M):
        if name not in ports:
            continue
        names = [name] if not hi else [f"{name}[{k}]" for k in range(int(lo), int(hi) + 1)]
        if hi:
            buses[name] = int(hi) - int(lo) + 1
        (ins if kind == "input" else outs).extend(names)
    return m[1], ins, outs, buses


def run_one(cx, d, cycles, seed):
    from lifters.cycloneiv_clean import emit, tracer as T
    import cycloneiv_clean_emit_check as C
    name = os.path.basename(d)
    wd = os.path.join(WORK, name)
    os.makedirs(wd, exist_ok=True)
    nl = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), name, 2).run()
    mine_v = os.path.join(wd, "emit.v")
    open(mine_v, "w").write(emit.verilog(nl))
    top, ins, outs, buses = vo_ports(os.path.join(d, "postfit.vo"))
    pins = C.parse_pin(os.path.join(d, "build.pin"))
    nets = T.parse_rcf(os.path.join(d, "routing.rcf"))
    clock_ports, srcmap = set(), {}
    for n in nets:
        nm = n["name"]
        if nm.endswith("~inputclkctrl") and any(dd[2].startswith("CLK") for dd in n["dests"]):
            clock_ports.add(nm[:-13])             # a clkctrl port that only feeds CLRN / data is driven as data (clock edge and clear edge would coincide)
        if nm.endswith("~input") and any(dd[2].startswith("CLK") for dd in n["dests"]):
            clock_ports.add(nm[:-6])                  # clock pad routed through the fabric straight to a block clock pin (M9K / MAC)
        if (nm.endswith("~input") or nm.endswith("~inputclkctrl")) and n["roots"] and n["roots"][0][0] in ("CLKBUF_OUT", "CLK_BUFFER"):
            r = n["roots"][0]
            srcmap[f"u_{r[0].lower()}_{r[1]}_{r[2]}_{r[3]}_{r[4]}"] = nm.replace("~inputclkctrl", "").replace("~input", "")
    ports = {io["ball"]: io for io in nl.ios}
    conn, gt_in = [], []
    for p in ins:
        gt_in.append(p)
    # TB
    lines = ["`timescale 1ps/1ps", "module tb;", "reg clk = 0;"]
    bus_of = lambda p: p.split("[")[0] if "[" in p else None
    for p in ins:
        if bus_of(p) is None and p not in clock_ports:
            lines.append(f"reg r_{p} = 0;")
    for bname, bw in buses.items():
        if any(q.startswith(bname + "[") for q in ins):
            lines.append(f"reg [{bw - 1}:0] r_{bname} = 0;")
        if any(q.startswith(bname + "[") for q in outs):
            lines.append(f"wire [{bw - 1}:0] g_{bname}, m_{bname};")
    gt_conn = [f".{p}({'clk' if p in clock_ports else 'r_' + p})" for p in ins if bus_of(p) is None]
    gt_conn += [f".{b}(r_{b})" for b in buses if any(q.startswith(b + "[") for q in ins)]
    comparable, uncomp = [], collections.Counter()
    for p in outs:
        ball = pins.get(p, (None,))[0]
        io = ports.get(ball)
        if io is not None and io["dir"] == "output" and io.get("drv") is not None:
            if bus_of(p) is None:
                lines.append(f"wire g_{p}, m_{p};")
                gt_conn.append(f".{p}(g_{p})")
            comparable.append((p, ball))
        else:
            if bus_of(p) is None:
                lines.append(f"wire g_{p};")
                gt_conn.append(f".{p}(g_{p})")
            uncomp["no_pad" if io is None else "undecoded_driver" if io["dir"] == "output" else "dir_" + str(io["dir"])] += 1
    gt_conn += [f".{b}(g_{b})" for b in buses if any(q.startswith(b + "[") for q in outs)]
    lines.append(f"{top} gt(" + ", ".join(gt_conn) + ");")
    m_conn = []
    for io in nl.ios:
        p = next((q for q, (b, _) in pins.items() if b == io["ball"]), None)
        if io["dir"] == "input":
            m_conn.append(f".pad_{io['ball']}(" + ("clk" if p in clock_ports else f"r_{p}" if p in ins else "1'b0") + ")")
        elif io["dir"] == "output":
            m_conn.append(f".pad_{io['ball']}(" + (f"m_{p}" if (p, io['ball']) in comparable else "") + ")")
        else:
            m_conn.append(f".pad_{io['ball']}()")
    tied = 0
    for u in sorted(nl.srcs):
        p = srcmap.get(u)
        if p is not None:
            m_conn.append(f".{u}(" + ("clk" if p in clock_ports else f"r_{p}") + ")")
        else:
            m_conn.append(f".{u}(1'b0)")
            tied += 1
    lines.append("cyc4_top dut(" + ", ".join(m_conn) + ");")
    lines += ["integer cyc, bad, n;", f"integer seed = {seed};",
              f"reg [{len(comparable) or 1}:0] badp = 0;",
              "initial begin", "bad = 0;", f"for (cyc = 0; cyc < {cycles}; cyc = cyc + 1) begin"]
    for p in ins:
        if bus_of(p) is None and p not in clock_ports:
            lines.append(f"  r_{p} = $random(seed);")
    for b in buses:
        if any(q.startswith(b + "[") for q in ins):
            lines.append(f"  r_{b} = $random(seed);")
    lines += [f"  #{HALF} clk = 1; #{HALF};", f"  if (cyc >= {WARMUP}) begin"]
    for i, (p, ball) in enumerate(comparable):
        lines.append(f"    if (g_{p} !== m_{p}) begin badp[{i}] = 1; bad = bad + 1; end")
    lines += ["  end", f"  clk = 0; #{HALF};", "end",
              f'$display("RESULT comparable={len(comparable)} bad_events=%0d bad_ports=%0d", bad, $countones(badp));']
    lines += ['$finish;', 'end', 'endmodule']
    tb = os.path.join(wd, "tb.v")
    open(tb, "w").write("\n".join(lines) + "\n")
    vvp = os.path.join(wd, "sim.vvp")
    res = dict(design=name, comparable=len(comparable), uncomparable=dict(uncomp), tied_sources=tied, srcmap=len(srcmap))
    try:
        c = run_tool(["iverilog", "-g2012", "-o", vvp, *(["-DLUT_DELAY=#1"] if HOLD_SAFE else []), tb, mine_v, os.path.join(d, "postfit.vo"), *sim_libs()])
        if c.timed_out:
            res.update(status="timeout", err=f"iverilog exceeded the guard ({RUN_LIMIT_S}s overall / 60 s stall)")
            return res
        if c.returncode:
            res.update(status="compile_error", err=c.stderr[:300])
            return res
        r = run_tool(["vvp", vvp])
        if r.timed_out:
            res.update(status="timeout", err=f"vvp exceeded the guard ({RUN_LIMIT_S}s overall / 60 s stall)")
            return res
    except OSError as e:
        res.update(status="tool_missing", err=str(e))
        return res
    m = re.search(r"RESULT comparable=(\d+) bad_events=(\d+) bad_ports=(\d+)", r.stdout)
    if not m:
        res.update(status="no_result", err=(r.stdout + r.stderr)[-300:])
        return res
    res["bad_ports"], res["bad_events"] = int(m[3]), int(m[2])
    res["status"] = "none" if not comparable else "pass" if int(m[2]) == 0 else "fail"
    # features of the design for failing-scope enumeration
    lcs, lc_name, ffs, ff_name, qnet = C.parse_gt(d)
    ctl = collections.Counter()
    for G in ffs.values():
        con = G["con"]
        for p, idle in (("ena", "vcc"), ("clrn", "vcc"), ("sclr", "gnd"), ("sload", "gnd"), ("aload", "gnd")):
            if con.get(p, idle) != idle:
                ctl[p] += 1
        if con.get("clk", "").startswith("!"):
            ctl["clk_inverted"] += 1
    res["features"] = dict(gt_ffs=len(ffs), gt_lcells=len(lcs), ff_ctl=dict(ctl), emit_ffs=len(nl.ffs), emit_luts=len(nl.luts),
                           hio_undecoded_outputs=uncomp.get("undecoded_driver", 0), srcs_undecoded=len(nl.srcs))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--names")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cycles", type=int, default=300)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--tag", default="x")
    ap.add_argument("--hold-safe", action="store_true", help="HALF 2000 ps, lcell outputs delayed 1 ps in GT and emit (clock-pad-as-data designs)")
    a = ap.parse_args()
    global HALF, HOLD_SAFE, ATOMS_NOPLL
    if a.hold_safe:
        HALF, HOLD_SAFE = 2000, True
        ATOMS_NOPLL = os.path.join(WORK, "cycloneiv_atoms_nopll_hs.v")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    if a.names:
        ds = [os.path.join(a.root, n) for n in a.names.split(",")]
    else:
        ds = []
        for d in sorted(glob.glob(os.path.join(a.root, "*"))):
            if all(os.path.exists(os.path.join(d, f)) for f in ("bitstream.rbf", "routing.rcf", "postfit.vo", "build.pin")):
                try:
                    if json.load(open(os.path.join(d, "rebuild.json"))).get("status") != "ok" or "EP4CGX150" not in open(os.path.join(d, "routing.rcf")).read(600):
                        continue
                except (OSError, ValueError):
                    continue
                ds.append(d)
        ds = ds[::a.stride]
        ds = ds[:a.limit] if a.limit else ds
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.6)
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_clean_emit_sim", log):
        cx = emit.Ctx()
        cx.st.edge_ids([0], [0])
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(run_one, cx, d, a.cycles, a.seed): d for d in ds}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=60, return_when=cf.FIRST_COMPLETED)
                if not done:
                    log.error("stall: no design finished in 60 s (%d pending, load %s)", len(pending), os.getloadavg())
                    raise SystemExit(3)
                for f in done:
                    try:
                        r = f.result()
                    except Exception as e:      # a design that cannot be simulated is a result, not a skip
                        import traceback
                        log.error("%s: %s\n%s", futs[f], e, traceback.format_exc())
                        r = dict(design=os.path.basename(futs[f]), status="error", err=f"{type(e).__name__}: {e}")
                    rows.append(r)
                    log.info("%s %s comparable=%s bad_ports=%s %s", r["design"], r["status"], r.get("comparable"), r.get("bad_ports"), r.get("err", ""))
    st = collections.Counter(r["status"] for r in rows)
    log.info("SIM %d designs: %s %.0fs", len(rows), dict(st), time.time() - t0)
    fail = [r for r in rows if r["status"] == "fail"]
    scope = collections.Counter()
    for r in fail:
        f = r["features"]
        scope["ff_ctl_nonidle" if sum(f["ff_ctl"].values()) else "ff_ctl_idle"] += 1
        scope["has_ffs" if f["gt_ffs"] else "combinational"] += 1
    log.info("failing designs by feature: %s", dict(scope))
    json.dump(dict(status=dict(st), fail_scope=dict(scope), cycles=a.cycles, rows=rows), open(os.path.join(OUT, f"emit_sim_{a.tag}.json"), "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
