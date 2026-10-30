#!/usr/bin/env python3.15t
"""Simulate the lifted third-party EP4CGX150 image (flat emit or RTL) and run the first checks (#165).

  python3.15t scripts/cycloneiv_clean_image_sim.py prep                       split over-long lines of tmp/image_sim/{flat,rtl}.v -> *_s.v
  python3.15t scripts/cycloneiv_clean_image_sim.py lint  --src flat|rtl [--sim verilator|iverilog]
  python3.15t scripts/cycloneiv_clean_image_sim.py run   --src flat|rtl --sim verilator|iverilog --cycles N [--plan same|ratio] [--tag T]
  python3.15t scripts/cycloneiv_clean_image_sim.py check --tag T               scrambler / CRC checks on a run's group trace
Inputs from scripts/cycloneiv_clean_image_build.py (tmp/image_sim/nl.pkl, flat.v, rtl.v).  Everything under tmp/image_sim/, counts only in the log
tmp/logs/image_sim.log.  The emit models M9K / MAC itself and has no PLL: global clock-buffer sources are module inputs driven by the testbench.
Heavy steps run under a stall guard (60 s without output = kill + last line + loadavg) and an RSS cap; no vendor sim libraries are used.
"""
import argparse
import collections
import itertools
import json
import logging
import os
import pickle
import re
import resource
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
W = os.path.join(REPO, "tmp", "image_sim")
LOG = os.path.join(REPO, "tmp", "logs", "image_sim.log")
log = logging.getLogger("image_sim")
SEED_AT, RUN_AT, RUN_CYC = 300, 340, 1100    # forced-strobe experiment: seed asserted at edge 300, released at 340, 1100 clocks observed
STALL_S = 60            # no output line for 60 s = hung (repo rule for host processes)
LONG_LINE = 20000       # verilator: > 40000 tokens on a line is an error; split at statement boundaries well under that
MEM_GB = 16
THREADS = 6


def sh(cmd, tag, overall_s, cwd=None, env=None):
    """Run cmd, stream output to the log; kill on STALL_S silence or overall_s.  -> (rc, seconds, peak_rss_mb, last_line)."""
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, env=env)
    state = {"last": "", "t": time.time()}
    out = []

    def pump():
        for line in p.stdout:
            state["last"], state["t"] = line.rstrip(), time.time()
            out.append(line)
            if not re.search(r"SELRANGE|^\s*\.\.\.|^\d+ \||^\s+\||^\s+\^", line):
                log.info("[%s] %s", tag, line.rstrip())
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    import psutil
    root = psutil.Process(p.pid)
    why, peak, cpu_prev, cpu_t, seen = None, 0.0, 0.0, time.time(), {}
    while th.is_alive():
        th.join(1.0)
        try:
            procs = [root] + root.children(recursive=True)
            peak = max(peak, sum(q.memory_info().rss for q in procs if q.is_running()) / 2**20)
            for q in procs:                                   # cumulative CPU per pid (finished children keep their last value)
                try:
                    seen[q.pid] = max(seen.get(q.pid, 0.0), sum(q.cpu_times()[:2]))
                except psutil.Error:
                    pass
            cpu = sum(seen.values())
        except psutil.Error:
            cpu = cpu_prev
        if cpu > cpu_prev + 0.5:
            cpu_prev, cpu_t = cpu, time.time()
        # stall = no output line AND no CPU progress in the process tree for STALL_S (compilers are silent but busy)
        if time.time() - state["t"] > STALL_S and time.time() - cpu_t > STALL_S:
            why = f"stall: no output and no CPU progress for {STALL_S}s"
        if time.time() - t0 > overall_s:
            why = f"overall limit {overall_s}s"
        if peak > MEM_GB * 1024:
            why = f"RSS cap {MEM_GB} GB"
        if why:
            for q in [root] + root.children(recursive=True):
                q.kill()
            log.error("[%s] KILLED %s; last line %r; loadavg %s", tag, why, state["last"], os.getloadavg())
            break
    p.wait()
    return p.returncode if not why else -9, time.time() - t0, peak, state["last"], "".join(out)


def split_long(src, dst, brk=(), brk_names_only=True):
    """Split lines > LONG_LINE at '; ' (statement boundaries: the M9K `initial begin a; b; ... end` lines).
    brk = LUT names on a dependent self loop (an inverting ring of one LUT oscillates in zero time): the self pin is tied 1'b0 in that LUT's assign."""
    n = 0
    pend = {f"assign `LUT_DELAY {b} = ": b for b in brk}
    with open(src) as f, open(dst, "w") as g:
        for line in f:
            if len(line) > LONG_LINE:
                n += 1
                line = line.replace("; ", ";\n")
            for k, b in pend.items():
                if line.startswith(k):
                    head, tail = line.split("[", 1)
                    line = head + "[" + tail.replace(b + ",", "1'b0,").replace(b + "}", "1'b0}")
            if not brk_names_only and line.startswith("assign `LUT_DELAY w_"):      # RTL: the same one-LUT inverter rings are `w_N = ~w_N`
                line = re.sub(r"^(assign `LUT_DELAY (w_\d+)) = ~\2;", r"\1 = ~1'b0;", line)
            g.write(line)
    return n


def self_loops(nl):
    """LUTs whose function depends on their own output pin (dependent-edge self loops of cycloneiv_clean_loops); also the multi-node loops."""
    import cycloneiv_clean_loops as Lp
    _a, dep = Lp.graph(nl)
    cs = Lp.sccs(dep)
    return sorted({c[0][1] for c in cs if len(c) == 1 and c[0][0] == "lc"}), [c for c in cs if len(c) > 1 or c[0][0] != "lc"]


def cmd_prep(a):
    brk, multi = self_loops(load_nl())
    log.info("prep: self-loop LUTs broken in flat (self pin tied 0): %d; other dependent loops left: %d", len(brk), len(multi))
    for k in ("flat", "rtl"):
        s = os.path.join(W, k + ".v")
        if os.path.exists(s):
            log.info("prep %s: %d long lines split", k, split_long(s, os.path.join(W, k + "_s.v"), brk if k == "flat" else (), k == "flat"))


def top_vsrc(a):
    return os.path.join(W, a.src + "_s.v")


def cmd_lint(a):
    f = top_vsrc(a)
    if a.sim == "verilator":
        rc, s, rss, last, out = sh(["verilator", "--lint-only", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-WIDTH", f, "--top-module", "cyc4_top"],
                                   "lint_" + a.src, 1200)
        errs = [l for l in out.splitlines() if l.startswith("%Error")]
        log.info("LINT verilator %s: rc=%s errors=%d %.0fs peak RSS %.0f MB", a.src, rc, len(errs), s, rss)
    else:
        rc, s, rss, last, out = sh(["iverilog", "-g2012", "-o", os.path.join(W, a.src + "_lint.vvp"), f], "lint_iv_" + a.src, 1200)
        log.info("LINT iverilog %s: rc=%s %.0fs peak RSS %.0f MB", a.src, rc, s, rss)


# ---------------------------------------------------------------------------------------------------------------------------------------
# testbench
def load_nl():
    return pickle.load(open(os.path.join(W, "nl.pkl"), "rb"))


def clock_plan(nl, plan):
    """-> ({clk source: half period ps}, [reset sources]).  Domain sources = clock pins of FFs; reset sources = async-clear pins of FFs (active low in the emit)."""
    clks = collections.Counter(F["clk"] for F in nl.ffs if F.get("clk") in nl.srcs)
    rsts = collections.Counter(F["aclr"] for F in nl.ffs if F.get("aclr") in nl.srcs)
    rsts = {r: n for r, n in rsts.items() if r not in clks}
    if plan == "same":
        half = {c: 5000 for c in clks}                     # 100 MHz-equivalent, one common clock (no PLL ratio evidenced per buffer)
    else:                                                  # PLL counter ratio 2:1 between the two largest domains (PLL8 c0 : c3 = divider 8 : 16), rest common
        order = [c for c, _ in clks.most_common()]
        half = {c: 5000 for c in clks}
        if len(order) > 1:
            half[order[1]] = 10000
    return half, sorted(rsts), clks, rsts


def domains(nl, clks):
    dom = {c: [F["name"] for F in nl.ffs if F.get("clk") == c] for c in clks}
    return dom


def gen_tb(nl, plan, cycles, groups, tag, pre="pad_", probe=True):
    half, rsts, clks, rcount = clock_plan(nl, plan)
    dom = domains(nl, clks)
    L = ["`timescale 1ps/1ps", "module tb;"]
    for c in half:
        L.append(f"reg {c} = 1'b0;")
    for r in rsts:
        L.append(f"reg {r} = 1'b0;")
    srcs_tied = [s for s in nl.srcs if s not in half and s not in rsts]
    pads = {io["ball"]: io["dir"] for io in nl.ios}
    conn = []
    for b, d in sorted(pads.items()):
        if d == "input":
            L.append(f"reg pad_{b}_r = 1'b0;")
            conn.append(f".{pre}{b}(pad_{b}_r)")
        elif d == "output":
            L.append(f"wire pad_{b}_w;")
            conn.append(f".{pre}{b}(pad_{b}_w)")
        else:
            L.append(f"wire pad_{b}_w;")
            conn.append(f".{pre}{b}(pad_{b}_w)")
    for s in sorted(nl.srcs):
        conn.append(f".{s}(" + (s if s in half or s in rsts else "1'b0") + ")")
    L.append("cyc4_top dut(" + ",\n  ".join(conn) + ");")
    # clocks
    for c, h in half.items():
        L.append(f"always #{h} {c} = ~{c};")
    # reset: low for the first 4 periods of the slowest clock, then released
    hmax = max(half.values())
    for r in rsts:
        L.append(f"initial begin {r} = 1'b0; #{8 * hmax} {r} = 1'b1; end")
    # activity: FF toggles per domain, sampled at the falling edge of each domain clock
    for i, (c, ffs) in enumerate(dom.items()):
        if not probe:
            L.append(f"longint ed{i} = 0; always @(negedge {c}) ed{i} = ed{i} + 1;")
            continue
        n = len(ffs)
        L.append(f"// domain {c}: {n} FFs")
        chunks = [ffs[k:k + 1024] for k in range(0, n, 1024)]
        L.append(f"localparam N{i} = {n};")
        L.append(f"wire [{max(n, 1) - 1}:0] v{i} = {{" + ", ".join("dut." + f for f in ffs) + "};" if n and n < 1024 else
                 f"wire [{max(n, 1) - 1}:0] v{i};")
        if n >= 1024:
            for k, ch in enumerate(chunks):
                lo = k * 1024
                L.append(f"assign v{i}[{lo + len(ch) - 1}:{lo}] = {{" + ", ".join("dut." + f for f in reversed(ch)) + "};")
        L.append(f"reg [{max(n, 1) - 1}:0] p{i} = 0; longint tg{i} = 0, ed{i} = 0, tgw{i} = 0;")
        L.append(f"always @(negedge {c}) begin ed{i} = ed{i} + 1; if (ed{i} > 16) tgw{i} = tgw{i} + $countones(v{i} ^ p{i}); tg{i} = tg{i} + $countones(v{i} ^ p{i}); p{i} = v{i}; end")
    # group traces
    for gi, g in enumerate(groups if probe else []):
        mem = ", ".join("dut." + f for f in reversed(g["ffs"]))
        ena = ("dut." + g["ena"]) if g.get("ena") else "1'b1"
        L.append(f"integer fg{gi}; initial fg{gi} = $fopen(\"{W}/trace_{tag}_g{gi}.txt\", \"w\");")
        L.append(f"always @(negedge {g['clk']}) $fwrite(fg{gi}, \"%0d %b %b %b\\n\", ed{list(dom).index(g['clk'])}, {ena}, {{{mem}}}, dbit);")
    # SPI program (+spi at run time): pads from the SPI trace (data AB11, bit clock AA8, frame AA9, MISO AA7); snapshots of every FF after each transfer
    if probe:
        allv = ", ".join(f"v{i}" for i in reversed(range(len(dom))))
        tot = sum(len(v) for v in dom.values())
        names = [f for v in dom.values() for f in v]
        json.dump(names, open(os.path.join(W, f"ffall_{tag}.json"), "w"))
        L.append(f"wire [{tot - 1}:0] vall = {{{allv}}};")
        L.append(f"integer fsn; initial fsn = $fopen(\"{W}/snap_{tag}.txt\", \"w\");")
        L.append("integer csa, q, per, lbl; reg [23:0] mrise, mfall; reg [7:0] hold;")
        ch = "".join(f" $fwrite(fsn, \"%b\", vall[{min(k + 4095, tot - 1)}:{k}]);" for k in range(0, tot, 4096))
        L.append("task snap(input integer l); begin $fwrite(fsn, \"%0d \", l);" + ch + " $fwrite(fsn, \"\\n\"); end endtask")
        L.append("task spi_byte(input [7:0] b); integer i; begin for (i = 7; i >= 0; i = i - 1) begin"
                 " pad_AB11_r = b[i]; #(q); pad_AA8_r = 1'b1; mrise = {mrise[22:0], pad_AA7_w}; #(2 * q - 1000); mfall = {mfall[22:0], pad_AA7_w}; #1000; pad_AA8_r = 1'b0; #(q); end end endtask")
        L.append("task spi_xfer(input [7:0] op, input [7:0] rg, input [7:0] v); begin"
                 " pad_AA9_r = csa[0]; #(8 * per); spi_byte(op); spi_byte(rg); spi_byte(v); #(8 * per); pad_AA9_r = ~csa[0]; #(16 * per);"
                 " $display(\"SPI op=%h reg=%h val=%h miso_rise=%b miso_fall=%b\", op, rg, v, mrise, mfall); end endtask")
        L.append("initial if ($test$plusargs(\"spi\")) begin")
        L.append("  if (!$value$plusargs(\"cs_active=%d\", csa)) csa = 1;")
        L.append(f"  per = {2 * max(half.values())}; q = 8 * per;")
        L.append("  pad_AA9_r = ~csa[0]; pad_AA8_r = 1'b0; pad_AB11_r = 1'b0;")
        L.append(f"  #{8 * hmax + 200 * 2 * max(half.values())}; snap(0);")
        steps = [("0E", 0, "80"), ("0E", 3, "11"), ("0E", 4, "22"), ("0E", 5, "33"), ("0E", 6, "44"), ("0E", 7, "55"), ("0E", 0, "00"),
                 ("0F", 3, "00"), ("0F", 4, "00"), ("0F", 5, "00"), ("0F", 6, "00"), ("0F", 7, "00"),
                 ("0E", 3, "66"), ("0E", 4, "77"), ("0E", 5, "88"), ("0E", 6, "99"), ("0E", 7, "AA"),
                 ("0F", 3, "00"), ("0F", 4, "00"), ("0F", 5, "00"), ("0F", 6, "00"), ("0F", 7, "00")]
        for k, (op, rg, v) in enumerate(steps, 1):
            L.append(f"  spi_xfer(8'h{op}, 8'h{rg:02X}, 8'h{v}); snap({k});")
        L.append("end")
        # +sweep: command byte 0..255 written to register 3 with a distinct data byte each (which opcodes load which copy of the register)
        L.append("initial if ($test$plusargs(\"sweep\")) begin")
        L.append("  if (!$value$plusargs(\"cs_active=%d\", csa)) csa = 0;")
        L.append(f"  per = {2 * max(half.values())}; q = 8 * per;")
        L.append("  pad_AA9_r = ~csa[0]; pad_AA8_r = 1'b0; pad_AB11_r = 1'b0;")
        L.append(f"  #{8 * hmax + 200 * 2 * max(half.values())}; snap(99);")
        L.append("  for (lbl = 0; lbl < 256; lbl = lbl + 1) begin spi_xfer(lbl[7:0], 8'h03, (lbl * 37 + 1) & 8'hFF); snap(100 + lbl); end")
        L.append("end")
    # forced-strobe experiment (+grp=N): enable forced 1, strobe externals forced to the seed assignment (edges SEED_AT..RUN_AT), then to the run
    # assignment for RUN_CYC clocks; the CRC data external gets a pseudo-random bit per clock.  Control state is internal (no pad in the cones): forced = stimulus, not natural operation.
    L.append("reg dbit = 1'b0; integer gsel, seedv; initial begin if (!$value$plusargs(\"grp=%d\", gsel)) gsel = -1; seedv = 12345; end")
    for gi, g in enumerate(groups if probe else []):
        if not g["seed_assign"] or not g["run_assign"] or not g["ena"]:
            continue
        clk = g["clk"]
        frc = lambda asg: " ".join(f"force dut.{k} = 1'b{v};" for k, v in asg.items() if k not in g["data"])
        dfr = "".join(f" force dut.{k} = dbit;" for k in g["data"])
        L.append(f"initial if (gsel == {gi}) begin")
        L.append(f"  #{SEED_AT * 2 * max(half.values()) + 1000}; force dut.{g['ena']} = 1'b1; {frc(g['seed_assign'])}{dfr}")
        L.append(f"  #{(RUN_AT - SEED_AT) * 2 * max(half.values())}; {frc(g['run_assign'])}")
        L.append(f"  repeat ({RUN_CYC}) begin @(posedge {clk}); #1000; dbit = $random(seedv); end")
        L.append(f"  release dut.{g['ena']}; " + " ".join(f"release dut.{k};" for k in g["ext"]))
        L.append("end")
    outs = sorted(b for b, d in pads.items() if d != "input")
    first = list(dom)[0]
    L.append(f"integer fo; initial fo = $fopen(\"{W}/trace_{tag}_out.txt\", \"w\");")
    L.append(f"always @(negedge {first}) $fwrite(fo, \"%0d %h\\n\", ed0, {{" + ", ".join(f"pad_{b}_w" for b in outs) + "});")
    L.append("integer ncyc;")
    L.append("initial begin")
    L.append(f"  ncyc = {cycles}; void'($value$plusargs(\"cyc=%d\", ncyc)); #(ncyc * {2 * max(half.values())});")
    for i, c in enumerate(dom):
        if probe:
            L.append(f"  $display(\"DOMAIN %0d {c} edges=%0d ffs={len(dom[c])} toggles=%0d toggles_after_16=%0d\", {i}, ed{i}, tg{i}, tgw{i});")
        else:
            L.append(f"  $display(\"DOMAIN %0d {c} edges=%0d ffs={len(dom[c])}\", {i}, ed{i});")
    L.append("  $display(\"SIMDONE\"); $finish;")
    L.append("end")
    L.append("endmodule")
    return "\n".join(L) + "\n", half, rsts, dom


def groups_from_nl(nl):
    """Register groups from the pattern detectors + seed trace: 3 x PRBS15, 4 x PRBS11, CRC-16.  -> list of dicts."""
    from lifters.cycloneiv_clean import patterns as P
    import cycloneiv_clean_seed_trace as ST
    D = P.Design(nl).prepare()
    det = P.detect(nl)
    tags = ST.counter_tags(det)
    gs = []
    for kind in ("lfsr", "parallel"):
        for i, g in enumerate(det[kind]):
            if g["n"] == 5:
                continue
            ffs = g["members"]
            r = ST.trace(D, ffs, 0, tags, None)
            ena = r["controls"]["ena"]
            ext, found, _why = ST.seed_assignments(D, ffs)
            mem = set(ffs)
            run = [dict(zip(ext, b)) for b in itertools.product((0, 1), repeat=len(ext)) if all(ST.ff_const_under(D, f, dict(zip(ext, b)), mem) is None for f in ffs)] if len(ext) <= 14 else []
            seeda = found[0][0] if found else None
            # data external = the one that takes both values among the run assignments (CRC input); the rest are strobe-type
            data = [e for e in ext if len({a[e] for a in run}) > 1] if kind == "parallel" else []
            gs.append(dict(kind=kind, idx=i, n=g["n"], poly=g.get("poly"), match=g.get("match"), ffs=ffs, lock=r.get("lock_state"),
                           seed=[dict(bits=s["bits"], logical=s.get("logical"), fixed=s["fixed"]) for s in (r["seed"] or [])],
                           ena=ena[0] if len(ena) == 1 else None, clk=g["clk"], charpoly=g.get("charpoly"), taps=g.get("taps"), form=g.get("form"),
                           ext=ext, seed_assign=seeda, run_assign=(run[0] if run else None), data=data))
    return gs


def cmd_run(a):
    nl = load_nl()
    tag = a.tag or f"{a.src}_{a.sim}"
    gs = groups_from_nl(nl)
    json.dump(gs, open(os.path.join(W, f"groups_{tag}.json"), "w"), indent=0)
    tb, half, rsts, dom = gen_tb(nl, a.plan, a.cycles, gs, tag, "pad_" if a.src == "flat" else "io_", a.src == "flat")
    tbp = os.path.join(W, f"tb_{tag}.v")
    open(tbp, "w").write(tb)
    src = top_vsrc(a)
    log.info("RUN %s: sim=%s src=%s cycles=%d plan=%s clocks=%d resets=%d groups=%d", tag, a.sim, a.src, a.cycles, a.plan, len(half), len(rsts), len(gs))
    if a.sim == "verilator":
        md = os.path.join(W, f"obj_{tag}")
        rc, s, rss, last, out = sh(["verilator", "--binary", "--timing", "--threads", str(THREADS), "-j", str(THREADS), "-O1", "--x-assign", "0", "--x-initial", "0", "--converge-limit", "100000",
                                    "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-WIDTH", "-Wno-MULTIDRIVEN", "-Wno-TIMESCALEMOD",
                                    "--top-module", "tb", "--Mdir", md, tbp, src], "build_" + tag, a.build_limit)
        log.info("BUILD verilator %s: rc=%s %.0fs peak RSS %.0f MB", tag, rc, s, rss)
        if rc:
            return
        t0 = time.time()
        rc, s, rss, last, out = sh([os.path.join(md, "Vtb")], "run_" + tag, a.run_limit)
    else:
        vvp = os.path.join(W, f"sim_{tag}.vvp")
        rc, s, rss, last, out = sh(["iverilog", "-g2012", "-o", vvp, tbp, src], "build_" + tag, a.build_limit)
        log.info("BUILD iverilog %s: rc=%s %.0fs peak RSS %.0f MB", tag, rc, s, rss)
        if rc:
            return
        rc, s, rss, last, out = sh(["vvp", vvp], "run_" + tag, a.run_limit)
    # cycles/s: simulated edges of the first clock domain per wall second
    edges = [int(m.group(1)) for m in re.finditer(r"edges=(\d+)", out)]
    log.info("SIM %s: rc=%s %.1fs wall, peak RSS %.0f MB, domain edges (falling) %s, cycles/s (domain 0) %.1f", tag, rc, s, rss, edges, (edges[0] / s) if edges and s else 0)
    for m in re.finditer(r"^DOMAIN .*$", out, re.M):
        log.info("%s", m.group(0))


def read_trace(path):
    """-> [(domain edge, ena, state bit-string in `ffs` order, data bit)]  (the TB writes {ffs reversed} so char 0 is the last member: reversed back)."""
    rows = []
    for line in open(path):
        e, ena, st, d = line.split()
        rows.append((int(e), ena == "1", st[::-1], int(d)))
    return rows


def recurrence_ok(poly_mask, streams, n):
    """Every stage stream s satisfies the characteristic-polynomial recurrence sum_k c_k s[t+k] = 0 (c_k = bit k of poly_mask, degree n)."""
    ok = tot = 0
    for s in streams:
        for t in range(len(s) - n):
            x = 0
            for k in range(n + 1):
                if (poly_mask >> k) & 1:
                    x ^= s[t + k]
            tot += 1
            ok += x == 0
    return ok, tot


def lfsr_step(s, taps, mirror):
    """Fibonacci step of the detector's structure on a logical state string: new[0] = s[t0] ^ s[t1], new[i] = s[i-1] (mirror: reversed index order)."""
    n = len(s)
    v = [int(c) for c in s]
    if mirror:
        v = v[::-1]
    nv = [v[taps[0]] ^ v[taps[1]]] + v[:-1]
    if mirror:
        nv = nv[::-1]
    return "".join(map(str, nv))


def crc_step(u, d, n=16, poly=0x1021):
    fb = ((u >> (n - 1)) & 1) ^ d
    return ((u << 1) & ((1 << n) - 1)) ^ (poly if fb else 0)


def cmd_check(a):
    """Per group on the forced-strobe traces (forced_<tag>_g<i>.txt from `forced`): seed held, then sequence vs polynomial for RUN_CYC clocks."""
    tag = a.tag
    gs = json.load(open(os.path.join(W, f"groups_{tag}.json")))
    out = []
    for gi, g in enumerate(gs):
        f = os.path.join(W, f"forced_{tag}_g{gi}.txt")
        if not os.path.exists(f):
            continue
        rows = read_trace(f)
        n, lock = g["n"], g["lock"]
        seed = [s["bits"] for s in g["seed"]]
        sd = [r for r in rows if SEED_AT + 3 <= r[0] < RUN_AT]
        run = [r for r in rows if RUN_AT + 2 <= r[0] <= RUN_AT + RUN_CYC - 4]       # the last clocks straddle the force release
        r = dict(group=gi, kind=g["kind"], n=n, poly=g["poly"], ext=g["ext"], data_ext=g["data"], seed_rows=len(sd), run_rows=len(run),
                 seed_held=sum(1 for x in sd if x[2] in seed), ena_forced_ok=all(x[1] for x in sd + run))
        if g["kind"] == "lfsr":
            lg = lambda s: "".join(str(int(b) ^ int(m)) for b, m in zip(s, lock))
            L = [lg(x[2]) for x in run]
            r["logical_seed_expected"] = [s["logical"] for s in g["seed"]]
            r["seed_logical_ok"] = sum(1 for x in sd if lg(x[2]) in r["logical_seed_expected"])
            r["distinct_states"] = len(set(L))
            streams = [[int(s[k]) for s in L] for k in range(n)]
            pm = g["charpoly"]
            r["recurrence_charpoly"] = recurrence_ok(pm, streams, n)
            r["recurrence_reciprocal"] = recurrence_ok(int(bin(pm)[2:][::-1], 2), streams, n)
            for mir in (False, True):
                r[f"step_match_mirror={mir}"] = (sum(1 for i in range(len(L) - 1) if lfsr_step(L[i], g["taps"], mir) == L[i + 1]), len(L) - 1)
            r["first_run_state_is_seed"] = bool(L and L[0] in r["logical_seed_expected"]) or bool(run and run[0][2] in seed)
        else:
            S = [x[2] for x in run]
            res = {}
            for name, rev in (("member_i=bit_i", False), ("member_i=bit_n-1-i", True)):
                val = lambda s: int((s[::-1] if not rev else s), 2)
                ok = sum(1 for i in range(len(run) - 1) if val(S[i + 1]) == crc_step(val(S[i]), run[i][3]))
                res[name] = (ok, len(run) - 1)
            r["crc16_ccitt_steps_exact"] = res
            r["seed_state_zero"] = sum(1 for x in sd if not any(int(c) for c in x[2]))
            r["distinct_states"] = len(set(S))
        out.append(r)
        log.info("GROUP %s", json.dumps(r))
    json.dump(out, open(os.path.join(W, f"check_{tag}.json"), "w"), indent=1)


def cmd_forced(a):
    """Run the built binary once per group with +grp=i and keep that group's trace."""
    md = os.path.join(W, f"obj_{a.tag}")
    gs = json.load(open(os.path.join(W, f"groups_{a.tag}.json")))
    for gi, g in enumerate(gs):
        if not (g["seed_assign"] and g["run_assign"] and g["ena"]):
            log.info("forced g%d: no seed/run assignment or enable (%s): skipped", gi, g["ext"])
            continue
        rc, s, rss, last, out = sh([os.path.join(md, "Vtb"), f"+grp={gi}", f"+cyc={RUN_AT + RUN_CYC + 50}"], f"run_forced_{gi}", 600)
        os.replace(os.path.join(W, f"trace_{a.tag}_g{gi}.txt"), os.path.join(W, f"forced_{a.tag}_g{gi}.txt"))
        log.info("forced g%d: rc=%s %.1fs", gi, rc, s)


def spi_regs(nl, spi, addrs):
    """addr -> [(enable, [(ff, bit, inv)])] from the SPI trace result: capture FFs of each enable, bit = chain tap - 1, inv = D inverts the tap."""
    ff = {F["name"]: F for F in nl.ffs}
    lut = {L["name"]: L for L in nl.luts}
    tap = {n: i for i, n in enumerate(spi["chain"]["ffs"])}
    by = collections.defaultdict(list)
    for F in nl.ffs:
        if F.get("ena"):
            by[F["ena"]].append(F["name"])
    out = {}
    for a in addrs:
        ents = []
        for e in spi["register_map"][hex(a)]:
            mem = []
            for n in by.get(e["enable"], []):
                d = ff[n]["d"]
                if d in tap:
                    mem.append((n, tap[d] - 1, 0))
                elif d in lut:
                    L = lut[d]
                    ps = [p for p in L["pins"] if p in tap]
                    if len(ps) != 1 or any(p not in ("1'b1", "1'b0") and p not in tap for p in L["pins"]):
                        continue
                    k = L["pins"].index(ps[0])
                    idx = lambda v: sum(((v if j == k else (1 if p == "1'b1" else 0)) << j) for j, p in enumerate(L["pins"]))
                    o0, o1 = (L["init"] >> idx(0)) & 1, (L["init"] >> idx(1)) & 1
                    if o0 != o1:
                        mem.append((n, tap[ps[0]] - 1, int(o0 == 1)))
            ents.append((e["enable"], mem))
        out[a] = ents
    return out


def cmd_spi(a):
    """Analyse a +spi run: register values per snapshot (reg 0..7 groups), FFs that changed per transfer, read-back bytes."""
    tag = a.tag
    nl = load_nl()
    spi = json.load(open(os.path.join(REPO, "tmp", "dji_spi", "image.json")))
    names = json.load(open(os.path.join(W, f"ffall_{tag}.json")))
    idx = {n: i for i, n in enumerate(names)}
    snaps = {}
    for line in open(os.path.join(W, f"snap_{tag}.txt")):
        l, v = line.split()
        snaps[int(l)] = "".join(v[i:i + 4096][::-1] for i in range(0, len(v), 4096))     # chunks of 4096 bits, each MSB first; bit k = names[k]
    regs = spi_regs(nl, spi, range(8))
    dom_of = {}
    for F in nl.ffs:
        dom_of[F["name"]] = F.get("clk")
    res = {"snapshots": len(snaps), "ffs": len(names)}
    labels = ["idle", "W r0=80", "W r3=11", "W r4=22", "W r5=33", "W r6=44", "W r7=55", "W r0=00", "R r3", "R r4", "R r5", "R r6", "R r7", "W' r3=66", "W' r4=77", "W' r5=88", "W' r6=99", "W' r7=AA", "R' r3", "R' r4", "R' r5", "R' r6", "R' r7"]
    regset = {n for ents in regs.values() for _e, m in ents for n, _b, _i in m}

    def regvals(s):
        vals = {}
        for ad, ents in regs.items():
            vals[ad] = [sum((int(s[idx[n]]) ^ inv) << bit for n, bit, inv in mem) if len(mem) == 8 else None for _en, mem in ents]
        return vals
    rows = []
    for k in sorted(snaps):
        s = snaps[k]
        prev = snaps.get(k - 1)
        diff = [i for i in range(len(names)) if prev and s[i] != prev[i]]
        if k >= 99:
            continue
        rows.append(dict(step=k, label=labels[k] if k < len(labels) else str(k), ffs_changed=len(diff), changed_in_regs0_7=sum(1 for i in diff if names[i] in regset),
                         changed_by_domain=dict(collections.Counter(dom_of[names[i]] for i in diff)),
                         reg_values={hex(ad): [None if x is None else f"{x:02x}" for x in v] for ad, v in regvals(s).items()}))
        log.info("SPISTEP %s", json.dumps(rows[-1]))
    res["rows"] = rows
    if 99 in snaps:
        c0, c1, both = [], [], []
        for k in range(256):
            v = regvals(snaps[100 + k])[3]
            data = (k * 37 + 1) & 255
            l0, l1 = v[0] == data, len(v) > 1 and v[1] == data
            if l0:
                c0.append(k)
            if l1:
                c1.append(k)
        res["sweep_reg3"] = dict(ops_loading_copy0=[f"{k:02x}" for k in c0], ops_loading_copy1=[f"{k:02x}" for k in c1])
        log.info("SWEEP reg3: %s", json.dumps(res["sweep_reg3"]))
    res["ffs_changed_any_step"] = len({i for k in snaps if k and k - 1 in snaps and k < 99 for i in range(len(names)) if snaps[k][i] != snaps[k - 1][i]})
    json.dump(res, open(os.path.join(W, f"spi_{tag}.json"), "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "lint", "run", "forced", "check", "spi"])
    ap.add_argument("--src", choices=["flat", "rtl"], default="flat")
    ap.add_argument("--sim", choices=["verilator", "iverilog"], default="verilator")
    ap.add_argument("--cycles", type=int, default=2000)
    ap.add_argument("--plan", choices=["same", "ratio"], default="same")
    ap.add_argument("--tag")
    ap.add_argument("--build-limit", type=int, default=1800)
    ap.add_argument("--run-limit", type=int, default=1800)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    log.info("load %s, free %s", os.getloadavg(), open("/proc/meminfo").read().splitlines()[2])
    {"prep": cmd_prep, "lint": cmd_lint, "run": cmd_run, "forced": cmd_forced, "check": cmd_check, "spi": cmd_spi}[a.cmd](a)


if __name__ == "__main__":
    main()
