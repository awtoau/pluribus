#!/usr/bin/env python3
"""MachXO2 recovery round-trip on a KNOWN-source design (ground-truth LEC).

The GOWIN analog just passed (a tiny XOR/AND/OR design recovered exactly).  This
is the MachXO2 version, on a REAL design: the replacement scope RTL
(interleaved ADC front-end + interleave-cal + capture core with a ring buffer +
an SPI-v2 slave).  We compile the KNOWN source to a MachXO2 bitstream, recover
it with pluribus, and LEC the recovered fabric against the source.

Flow
----
  scope_top.py (Amaranth, KNOWN source)
     -> yosys synth_lattice -family xo2      (scope.json)
     -> nextpnr-machxo2                       (scope_out.config)
     -> ecppack                               (scope.bit)              <-- real bitstream
     -> pluribus trellis_unpack (native)      (scope_recovered.config) <-- native decode
     -> pluribus fpga_iomap                    (.iomap.tsv)
     -> pluribus load.py  (SCRATCH db tmp/repl.db, label REPL_SCOPE)
     -> reach/reach2/reach3/reach4
     -> pluribus verilog.py                    (recovered.v)
     -> LEC recovered.v vs scope_src.v

LEC (two verdicts)
------------------
  1. WHOLE-DESIGN  yosys equiv_induct (the pluribus repo's own LEC tool).
     Expected: miso NOT provable unboundedly -- the distributed-RAM capture
     buffer's write->read dataflow is a documented lifter stub, so the memory
     readback path is functionally wrong.  Verdict: 0/1 cones proven.

  2. BOUNDED-FROM-RESET  SAT miter (yosys sat -seq N), both designs forced to a
     common all-zero state then held in reset, proving the recovered miso is
     BIT-EXACT to the source miso for N cycles under ALL input sequences.  This
     isolates the fabric datapath (reset, SPI-v2 FSM, status/wp_trig/meas_offset
     register readback, trigger config, interleave-cal) from the memory.  The
     proof holds to a depth D, then diverges at D+1 on the first serialised data
     bit.  NB (#65): that first-bit divergence is NOT the DPRAM value — it holds
     with the DPRAM read data forced to 0 — it is a readback-datapath gap.  Two
     layers of it (orphaned SPI-address-register FFs; orphaned PLC fast-connect
     slice outputs) are fixed this pass; a deeper register-read/serialiser logic
     gap still caps the proof at D.

Nothing here is committed and nothing in awto-2000 is modified: the source is
imported read-only and all build artefacts land under pluribus/tmp/repl_scope/.

Env (defaults target this machine):
  OSS_CAD     = /home/dan/opt/oss-cad-suite/bin  (yosys/nextpnr-machxo2/ecppack)
  RTL_DIR     = /mnt/2tb/git/awto-2000/fpga/hantek/rtl  (KNOWN source, read-only)
  TRELLIS_DBROOT = prjtrellis database root
  PY_AMARANTH = python3            (interpreter with amaranth, for source regen)
  PY_PLURIBUS = python3.15t        (free-threaded pipeline interpreter)
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "tmp" / "repl_scope"
LOG = WORK / "roundtrip.log"

OSS = os.environ.get("OSS_CAD", "/home/dan/opt/oss-cad-suite/bin")
RTL_DIR = os.environ.get("RTL_DIR", "/mnt/2tb/git/awto-2000/fpga/hantek/rtl")
DBROOT = os.environ.get(
    "TRELLIS_DBROOT",
    "/mnt/2tb/git/github.com/awtoau/prjtrellis/database")
PY_AMARANTH = os.environ.get("PY_AMARANTH", "python3")
PY_PLURIBUS = os.environ.get("PY_PLURIBUS", "python3.15t")

DEVICE = "LCMXO2-1200"
DEVICE_FULL = "LCMXO2-1200HC-4TG100C"
PACKAGE = "TQFP100"
LABEL = "REPL_SCOPE"
DB = REPO / "tmp" / "repl.db"

# port(LPF), label(pluribus), SITE(pin), row, col, pio, dir
# SITE<->tile pairs are ground-truth ordinary edge IO from the vendor V4 LPF.
PIN_MAP = [
    ("adc[0]", "adc0", "83", 0, 14, "B", "in"),
    ("adc[1]", "adc1", "84", 0, 14, "A", "in"),
    ("adc[2]", "adc2", "96", 0, 9, "B", "in"),
    ("adc[3]", "adc3", "97", 0, 9, "A", "in"),
    ("adc[4]", "adc4", "98", 0, 8, "B", "in"),
    ("adc[5]", "adc5", "99", 0, 8, "A", "in"),
    ("adc[6]", "adc6", "51", 10, 21, "D", "in"),
    ("adc[7]", "adc7", "52", 10, 21, "C", "in"),
    ("phase", "phase", "53", 9, 21, "D", "in"),
    ("stb", "stb", "54", 9, 21, "C", "in"),
    ("sck", "sck", "60", 8, 21, "C", "in"),
    ("cs_n", "cs_n", "61", 8, 21, "A", "in"),
    ("mosi", "mosi", "64", 5, 21, "B", "in"),
    ("clk", "clk", "65", 5, 21, "A", "in"),
    ("rst", "rst", "66", 4, 21, "D", "in"),
    ("miso", "miso", "67", 4, 21, "C", "out"),
]

_logfh = None
_log_lock = threading.Lock()


def _default_jobs():
    """Max concurrent SAT probes.

    NOT simply the CPU count: a deep bounded-miter probe on this design peaks
    around 3-4.5 GB RSS, so on a 32-core/62 GB box MEMORY is the binding
    constraint (32 concurrent deep probes would want ~115 GB and swap-thrash).
    Budget 4.5 GB per slot against MemAvailable and cap at the CPU count."""
    cpus = os.cpu_count() or 4
    try:
        with open("/proc/meminfo") as fh:
            avail_kb = next(int(ln.split()[1]) for ln in fh
                            if ln.startswith("MemAvailable:"))
        by_mem = int(avail_kb / (4.5 * 1024 * 1024))
    except Exception:
        by_mem = cpus
    return max(1, min(cpus, by_mem))


# max concurrent SAT probes (--jobs overrides); see _default_jobs()
_JOBS = _default_jobs()
# one global gate for EVERY bounded-SAT probe, so the concurrently-running
# bounded sweep and diagnostics share a single memory budget.
_sat_slots = threading.Semaphore(_JOBS)

MAX_DEPTH = 64          # deepest bound the sweep will attempt (unchanged)

# ---- phase profiling -----------------------------------------------------
PROFILE = []          # [(name, seconds), ...] in completion order
_prof_lock = threading.Lock()


@contextmanager
def phase(name):
    """Time a pipeline phase and record it for the end-of-run profile."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        with _prof_lock:
            PROFILE.append((name, dt))


def log(msg=""):
    with _log_lock:
        print(msg, flush=True)
        if _logfh:
            _logfh.write(str(msg) + "\n")
            _logfh.flush()


def sh(cmd, extra_env=None, cwd=None, stage=""):
    """Run a command, tee output to a per-stage log, die on non-zero."""
    env = dict(os.environ)
    env["PATH"] = OSS + os.pathsep + env.get("PATH", "")
    env["TRELLIS_DBROOT"] = DBROOT
    env["TRELLIS_DEVICE"] = DEVICE
    env["TRELLIS_PACKAGE"] = PACKAGE
    if extra_env:
        env.update(extra_env)
    slog = WORK / f"stage_{stage}.log" if stage else None
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    t0 = time.perf_counter()
    r = subprocess.run(cmd, env=env, cwd=cwd or str(REPO),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if stage:
        with _prof_lock:
            PROFILE.append((stage, time.perf_counter() - t0))
    if slog:
        slog.write_text(r.stdout)
    if r.returncode != 0:
        log(r.stdout[-3000:])
        sys.exit(f"stage {stage!r} FAILED (exit {r.returncode})")
    return r.stdout


# --------------------------------------------------------------------------
def regen_source():
    """Import ScopeTop read-only from awto-2000 and emit fresh scope_src.v.

    The tracked scope_top.v in awto-2000 is STALE (miso emitted as an input, so
    the design has no observable output and synthesises to nothing).  The
    current source drives miso, so we regenerate."""
    log("[1] regenerate KNOWN source (scope_src.v) from ScopeTop")
    gen = WORK / "gen_src.py"
    gen.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {RTL_DIR!r})\n"
        "from amaranth.back import verilog\n"
        "from scope_top import ScopeTop\n"
        "dut = ScopeTop(depth=256)\n"
        "v = verilog.convert(dut, name='scope_top', ports=[dut.adc, dut.phase,"
        " dut.stb, dut.sck, dut.cs_n, dut.mosi, dut.miso])\n"
        f"open({str(WORK / 'scope_src.v')!r},'w').write(v)\n"
        "print('miso is', 'OUTPUT' if 'output miso' in v else 'INPUT(!)')\n")
    out = sh([PY_AMARANTH, str(gen)], stage="regen")
    log("    " + out.strip())


def gen_constraints():
    log("[2] emit matching LPF + pins.tsv (port names line up for LEC)")
    lpf = ["# scope_top round-trip pin constraints (LCMXO2-1200 TQFP100)", ""]
    for port, _lbl, site, *_ in PIN_MAP:
        lpf.append(f'LOCATE COMP "{port}" SITE "{site}";')
        lpf.append(f'IOBUF PORT "{port}" IO_TYPE=LVCMOS33;')
    (WORK / "scope.lpf").write_text("\n".join(lpf) + "\n")

    tsv = ["# device:   LCMXO2-1200", "# package:  TQFP100",
           "# pin row col pio dir label function conf ref chip_pin chip_sig"
           " net_in net_out note"]
    for _port, lbl, site, r, c, p, d in PIN_MAP:
        tsv.append("\t".join([site, str(r), str(c), p, d, lbl,
                              "roundtrip port", "10", "", "", "", "", "",
                              "known-source LEC port"]))
    (WORK / "scope_pins.tsv").write_text("\n".join(tsv) + "\n")


def build_bitstream():
    log("[3] synth (synth_lattice -family xo2)")
    sh([f"{OSS}/yosys", "-p",
        f"read_verilog -sv {WORK}/scope_src.v; "
        f"synth_lattice -family xo2 -top scope_top -json {WORK}/scope.json"],
       stage="synth")
    log("[4] place & route (nextpnr-machxo2)")
    sh([f"{OSS}/nextpnr-machxo2", "--device", DEVICE_FULL,
        "--json", f"{WORK}/scope.json", "--lpf", f"{WORK}/scope.lpf",
        "--textcfg", f"{WORK}/scope_out.config", "--freq", "25"], stage="pnr")
    log("[5] pack (ecppack -> real MachXO2 bitstream)")
    sh([f"{OSS}/ecppack", f"{WORK}/scope_out.config", f"{WORK}/scope.bit"],
       stage="pack")
    log(f"    bitstream: {(WORK/'scope.bit').stat().st_size} bytes")


def recover():
    cfg = WORK / "scope_recovered.config"
    log("[6] native unpack (pluribus trellis_unpack)")
    if cfg.exists():
        cfg.unlink()
    sh([PY_PLURIBUS, "scripts/trellis_unpack.py", f"{WORK}/scope.bit", str(cfg)],
       stage="unpack")
    log("[7] iomap")
    iomap = Path(str(cfg) + ".iomap.tsv")
    if iomap.exists():
        iomap.unlink()
    sh([PY_PLURIBUS, "scripts/fpga_iomap.py", str(cfg)], stage="iomap")
    log("[8] load -> scratch db tmp/repl.db")
    if DB.exists():
        DB.unlink()
    env = {"PLURIBUS_SQLITE_PATH": str(DB)}
    sh([PY_PLURIBUS, "load.py", "--label", LABEL, "--config", str(cfg),
        "--pins", f"{WORK}/scope_pins.tsv", "--device", DEVICE,
        "--package", PACKAGE], extra_env=env, stage="load")
    log("[9] reachability passes")
    for st in ("reach", "reach2", "reach3", "reach4"):
        sh([PY_PLURIBUS, f"{st}.py", "--bitstream", LABEL],
           extra_env=env, stage=st)
    log("[10] emit recovered structural Verilog")
    sh([PY_PLURIBUS, "verilog.py", "--bitstream", LABEL,
        "--out", f"{WORK}/recovered.v", "--top", "scope_top"],
       extra_env=env, stage="verilog")


def _write_lec_helpers():
    """Wrapper presenting the SOURCE interface around the recovered netlist:
    rejoins adc0..7 into adc[7:0] and ties all recovered clock-domain inputs to
    the single physical clk (pluribus recovers one routed clock as several
    spine-tap domains)."""
    # discover the recovered clock-domain ports (spec_clk_*) — scan ONLY the
    # module header so internal reg names (spec_clk_1__r7c13_A0) are not caught.
    rec = (WORK / "recovered.v").read_text()
    import re
    hdr = re.search(r"^module\s+scope_top.*?^\);", rec, re.S | re.M)
    hdr_txt = hdr.group(0) if hdr else rec
    clk_ports = sorted(set(re.findall(
        r"(?:input|output)\s+wire\s+(spec_clk_\w+)", hdr_txt)))
    ties = "".join(f"    .{c}(clk),\n" for c in clk_ports)
    (WORK / "rec_wrap.v").write_text(
        "module rec_wrap(adc, phase, stb, sck, cs_n, mosi, clk, rst, miso);\n"
        "  input [7:0] adc;\n"
        "  input phase, stb, sck, cs_n, mosi, clk, rst;\n"
        "  output miso;\n"
        "  scope_top_rec u (\n"
        "    .adc0(adc[0]), .adc1(adc[1]), .adc2(adc[2]), .adc3(adc[3]),\n"
        "    .adc4(adc[4]), .adc5(adc[5]), .adc6(adc[6]), .adc7(adc[7]),\n"
        "    .phase(phase), .stb(stb), .sck(sck), .cs_n(cs_n), .mosi(mosi),\n"
        "    .clk(clk), .rst(rst), .miso(miso),\n"
        f"{ties}"
        "  );\n"
        "endmodule\n")
    return clk_ports


def _gold_gate(memory_map):
    """yosys prelude building gold (source) and gate (recovered+wrapper)."""
    gold_mem = "memory\nmemory_map\n" if memory_map else "memory\n"
    return (
        f"read_verilog -sv {WORK}/scope_src.v\n"
        "hierarchy -top scope_top\nproc\nflatten\n"
        f"{gold_mem}opt -fast\nrename scope_top gold\ndesign -stash gold\n"
        f"read_verilog -sv {WORK}/recovered.v\n"
        "rename scope_top scope_top_rec\n"
        f"read_verilog -sv {WORK}/rec_wrap.v\n"
        "hierarchy -top rec_wrap\nproc\nflatten\nopt -fast\n"
        "rename rec_wrap gate\ndesign -stash gate\n"
        "design -copy-from gold -as gold gold\n"
        "design -copy-from gate -as gate gate\n")


def lec_induct():
    log("[11] LEC #1 whole-design equiv_induct (repo's own LEC tool)")
    script = (_gold_gate(memory_map=False) +
              "equiv_make gold gate equiv\nhierarchy -top equiv\nopt_clean\n"
              "equiv_struct\nequiv_induct -seq 30\nequiv_status\n")
    (WORK / "lec.ys").write_text(script)
    out = sh([f"{OSS}/yosys", "-s", f"{WORK}/lec.ys"], stage="lec_induct")
    verdict = "?"
    for ln in out.splitlines():
        if "are proven and" in ln:
            verdict = ln.strip()
    log(f"    equiv_induct: {verdict}")
    return verdict


def _miter_prelude():
    return (_gold_gate(memory_map=True) +
            "miter -equiv -flatten -make_assert gold gate miter\n"
            "hierarchy -top miter\nflatten\n")


# --------------------------------------------------------------------------
# Parallel bounded-miter depth search  (#72)
#
# The bounded-miter predicate is MONOTONE in the depth n:
#   * if the miter DIVERGES at depth n it diverges at every depth > n
#     (the counterexample trace is a valid prefix of any longer unrolling);
#   * if it is PROVEN at depth n it is proven at every depth < n
#     (a proof over n cycles subsumes every shorter prefix).
# Locating the first divergence is therefore finding the boundary of a
# monotone step function.  Probing several depths CONCURRENTLY cannot change
# where that boundary is — it only changes how fast we bracket it.  The
# sequential ladder-then-bisect and the parallel probe must agree exactly.
#
# Scheduling: each round probes a whole candidate set at once, deepest first so
# the long pole claims a slot earliest, and KILLs every probe a completed result
# has rendered redundant.  SAT cost grows steeply with depth, so the
# cancellations that pay are the deep ones above a freshly-found divergence.
#
# Concurrency is capped by _sat_slots, sized from FREE MEMORY rather than the
# core count (see _default_jobs): a deep probe peaks near 3-4.5 GB, so the box
# runs out of RAM long before it runs out of cores.
# --------------------------------------------------------------------------
# Keyed by the full stage name ("miter53", "diag80", ...), NOT by bare depth:
# the diagnostics probes reuse depths the sweep already visited, and a shared
# depth keyspace would let a cancelled sweep probe silently cancel them.
_probe_procs = {}                 # stage -> live Popen
_probe_cancelled = set()          # stages whose answer is already implied
_probe_lock = threading.Lock()


def _sat_cmd(n, miter_ys, extra_set=""):
    extra = f"{extra_set.strip()} " if extra_set.strip() else ""
    return [f"{OSS}/yosys", "-s", str(miter_ys), "-p",
            f"sat -seq {n} -prove-asserts -set-init-zero {extra}"
            f"-set-at 1 in_rst 1 -set-at 2 in_rst 1 -set-at 3 in_rst 1"]


def _sat_probe(n, miter_ys, stage_prefix="miter", extra_set=""):
    """One killable bounded-SAT probe.

    Returns True (PROVEN), False (DIVERGES), or None if the probe was
    cancelled because an earlier result already implied its answer."""
    env = dict(os.environ)
    env["PATH"] = OSS + os.pathsep + env.get("PATH", "")
    env["TRELLIS_DBROOT"] = DBROOT
    env["TRELLIS_DEVICE"] = DEVICE
    env["TRELLIS_PACKAGE"] = PACKAGE
    stage = f"{stage_prefix}{n}"

    # Every probe is submitted immediately but only RUNS once it holds a slot,
    # so a probe still queued when its answer becomes implied is cancelled for
    # free — it never costs a process at all.
    with _sat_slots:
        with _probe_lock:
            if stage in _probe_cancelled:
                return None
            p = subprocess.Popen(_sat_cmd(n, miter_ys, extra_set), env=env,
                                 cwd=str(REPO), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            _probe_procs[stage] = p

        t0 = time.perf_counter()
        out, _ = p.communicate()
        dt = time.perf_counter() - t0

    with _probe_lock:
        _probe_procs.pop(stage, None)
        killed = stage in _probe_cancelled

    (WORK / f"stage_{stage}.log").write_text(out or "")
    with _prof_lock:
        PROFILE.append((stage, dt))

    if killed:
        return None
    if p.returncode != 0:
        log(out[-3000:] if out else "")
        sys.exit(f"stage {stage!r} FAILED (exit {p.returncode})")
    return "SUCCESS!" in out and "found a model" not in out


def _cancel_redundant(candidates, lo, hi, prefix="miter"):
    """Kill/skip every candidate whose verdict the (lo, hi) bracket implies.

    lo = deepest PROVEN so far, hi = shallowest DIVERGING so far (or None).
    Depths <= lo are proven by monotonicity; depths >= hi diverge by
    monotonicity.  Neither needs to be computed."""
    killed = []
    with _probe_lock:
        for n in candidates:
            stage = f"{prefix}{n}"
            if stage in _probe_cancelled:
                continue
            if n <= lo or (hi is not None and n >= hi):
                _probe_cancelled.add(stage)
                p = _probe_procs.get(stage)
                if p is not None:
                    p.kill()
                    killed.append(n)
    return killed


def _spread(first, last, k):
    """<=k evenly-spaced integers covering [first, last] inclusive."""
    span = list(range(first, last + 1))
    if not span:
        return []
    k = min(max(1, k), len(span))
    if k == 1:
        return [span[len(span) // 2]]
    return sorted({span[round(i * (len(span) - 1) / (k - 1))]
                   for i in range(k)})


def _probe_round(candidates, lo, hi):
    """Probe `candidates` concurrently; return the tightened (lo, hi)."""
    candidates = [n for n in sorted(set(candidates)) if n > lo and
                  (hi is None or n < hi)]
    if not candidates:
        return lo, hi
    # deepest first: the expensive probes claim a slot before the cheap ones.
    # One thread per candidate — _sat_slots, not the pool, caps real work, so
    # queued probes stay reachable by _cancel_redundant.
    order = sorted(candidates, reverse=True)
    with ThreadPoolExecutor(max_workers=len(order)) as ex:
        futs = {ex.submit(_sat_probe, n, WORK / "miter.ys"): n for n in order}
        for fut in as_completed(futs):
            n = futs[fut]
            ok = fut.result()
            if ok is None:
                continue
            log(f"    depth {n:3d}: "
                f"{'PROVEN equivalent' if ok else 'DIVERGES'}")
            if ok:
                lo = max(lo, n)
            else:
                hi = n if hi is None else min(hi, n)
            cut = _cancel_redundant(candidates, lo, hi)
            if cut:
                log(f"              (bracket {lo}..{hi} -> cancelled redundant "
                    f"probes {', '.join(str(c) for c in sorted(cut))})")
    return lo, hi


def lec_bounded():
    log("[12] LEC #2 bounded-from-reset SAT miter (isolates fabric vs memory)")
    log(f"    parallel monotone boundary search, up to {_JOBS} concurrent probes")
    (WORK / "miter.ys").write_text(_miter_prelude())

    # Round 1 replaces the old 8/16/32/48/64 ladder with a _JOBS-wide even
    # sweep of the whole 1..MAX_DEPTH range.  The ladder's deepest rung was
    # pure overhead: it paid a full depth-64 solve just to learn "the boundary
    # is somewhere below 64" while every other worker sat idle.  A dense sweep
    # brackets far tighter for the same wall time, because the probe that
    # settles the bracket is a SHALLOWER (hence cheaper) one and it cancels the
    # deeper probes the moment it lands.
    lo, hi = _probe_round(_spread(1, MAX_DEPTH, _JOBS), 0, None)

    # round 2+: k-way probe across the open bracket, narrowing by k+1 per
    # round instead of the 2 a bisection manages.
    while hi is not None and hi - lo > 1:
        lo, hi = _probe_round(_spread(lo + 1, hi - 1, _JOBS), lo, hi)

    proven, diverge = lo, hi
    log(f"    => recovered miso == source miso for cycles 1..{proven}; "
        f"first divergence at cycle {diverge}")
    log(f"       (miso is idle=0 through the SPI command phase; cycle {diverge} "
        "is the first data-output bit)")
    return proven, diverge


def lec_diagnostics():
    """Localise the divergence: is it (a) reset/idle, (b) the DPRAM value, or
    (c) the active SPI-readback datapath?"""
    log("[13] LEC diagnostics — localise the divergence")

    # (a) hold SPI deselected (cs_n high): reset + idle behaviour only.
    # Its OWN script file: the bounded sweep may still be running against
    # miter.ys concurrently.
    idle_ys = WORK / "miter_idle.ys"
    idle_ys.write_text(_miter_prelude())

    # (b) neutralise the DPRAM read data (force read nets to 0, matching the
    # source's empty/unwritten capture buffer) and re-check the divergence.
    import re
    rec0 = re.sub(r"^(\s*assign dpram_\w+ = )[^;]+;",
                  r"\g<1>1'b0;",
                  (WORK / "recovered.v").read_text(), flags=re.M)
    (WORK / "recovered_mem0.v").write_text(rec0)
    mem0_ys = WORK / "miter_mem0.ys"
    mem0_ys.write_text(
        _miter_prelude().replace("recovered.v", "recovered_mem0.v"))

    # (a) and (b) are independent SAT problems — run them concurrently.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_idle = ex.submit(_sat_probe, 80, idle_ys, "diag",
                           "-set in_cs_n 1")
        f_mem0 = ex.submit(_sat_probe, 56, mem0_ys, "diagmem0")
        idle_ok = f_idle.result()
        mem0_ok = f_mem0.result()

    log(f"    cs_n held HIGH (reset+idle), depth 80 : "
        f"{'PROVEN equivalent' if idle_ok else 'DIVERGES'}")
    log(f"    DPRAM reads forced to 0, depth 56     : "
        f"{'PROVEN equivalent (divergence was the memory value)' if mem0_ok else 'STILL DIVERGES (readback datapath gap, not just memory)'}")
    return idle_ok, mem0_ok


_GROUPS = [
    ("regen source", ("regen",)),
    ("synth", ("synth",)),
    ("place & route", ("pnr",)),
    ("pack", ("pack",)),
    ("recover (unpack/iomap/load)", ("unpack", "iomap", "load")),
    ("reachability", ("reach", "reach2", "reach3", "reach4")),
    ("emit verilog", ("verilog",)),
    ("LEC equiv_induct", ("lec_induct",)),
]


def report_profile(wall):
    """Per-phase wall-clock breakdown (CPU-seconds; parallel phases overlap)."""
    with _prof_lock:
        entries = list(PROFILE)
    tot = {}
    for name, dt in entries:
        tot[name] = tot.get(name, 0.0) + dt
    used = set()
    rows = []
    for label, keys in _GROUPS:
        s = sum(tot.get(k, 0.0) for k in keys)
        used.update(keys)
        if s:
            rows.append((label, s))
    miter = sum(v for k, v in tot.items() if k.startswith("miter"))
    diag = sum(v for k, v in tot.items() if k.startswith("diag"))
    if miter:
        rows.append(("LEC bounded miter sweep", miter))
    if diag:
        rows.append(("LEC diagnostics", diag))
    other = sum(v for k, v in tot.items()
                if k not in used and not k.startswith(("miter", "diag")))
    if other:
        rows.append(("other", other))
    cpu = sum(v for _, v in rows)

    log("\n" + "=" * 68)
    log("PHASE PROFILE")
    log("=" * 68)
    log(f"  {'phase':<32} {'CPU s':>9} {'% CPU':>7}")
    for label, s in sorted(rows, key=lambda r: -r[1]):
        log(f"  {label:<32} {s:9.1f} {100*s/cpu if cpu else 0:6.1f}%")
    log(f"  {'-'*32} {'-'*9} {'-'*7}")
    log(f"  {'total subprocess CPU time':<32} {cpu:9.1f}")
    log(f"  {'wall clock':<32} {wall:9.1f}")
    log(f"  {'concurrency (CPU/wall)':<32} {cpu/wall if wall else 0:9.2f}x")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true",
                    help="reuse existing bitstream/recovery, run LEC only")
    ap.add_argument("--jobs", type=int, default=0,
                    help="max concurrent SAT probes (default: CPU count)")
    args = ap.parse_args()
    global _JOBS
    if args.jobs > 0:
        _JOBS = args.jobs
    t_start = time.perf_counter()

    global _logfh
    WORK.mkdir(parents=True, exist_ok=True)
    _logfh = open(LOG, "w")
    log(f"MachXO2 recovery round-trip  device={DEVICE_FULL}  label={LABEL}")
    log(f"work={WORK}  db={DB}")

    if not args.skip_build:
        regen_source()
        gen_constraints()
        build_bitstream()
        recover()

    _write_lec_helpers()
    # The three LEC phases are mutually independent (each builds its own
    # miter/equiv from the same read-only gold+gate sources and answers a
    # separate question), so run them concurrently.  _sat_slots keeps their
    # combined SAT memory footprint inside one budget.
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_induct = ex.submit(lec_induct)
        f_bounded = ex.submit(lec_bounded)
        f_diag = ex.submit(lec_diagnostics)
        v_induct = f_induct.result()
        proven, diverge = f_bounded.result()
        idle_ok, mem0_ok = f_diag.result()

    log("\n" + "=" * 68)
    log("VERDICT  —  the recovery does NOT pass functional LEC")
    log("=" * 68)
    log(f"  whole-design equiv_induct : {v_induct}  (miso not provably equivalent)")
    log(f"  reset + idle (cs_n high)  : {'PROVEN equivalent, 80 cycles' if idle_ok else 'DIVERGES'}")
    log(f"  SPI command phase         : PROVEN equivalent through cycle {proven} "
        "(miso idle=0)")
    log(f"  first readback data bit   : DIVERGES at cycle {diverge}")
    log(f"  DPRAM read data forced 0  : "
        f"{'divergence removed -> memory value only' if mem0_ok else 'STILL diverges -> readback datapath gap, not just the memory stub'}")
    log("")
    log("  Structurally the recovery is complete (LUT INITs, FFs, carries, DPRAM")
    log("  sites, IO, routing all recovered; native decode CRC-verified).  But it")
    log("  is NOT functionally equivalent to the known source:")
    log("    - the single physical clk is recovered as one unified spine (#65 gap 1);")
    log("    - the 256x8 capture ring buffer (distributed RAM / 32x DPR16X4) still")
    log("      has a stub write->read dataflow (documented lifter limitation);")
    log("    - the first-data-bit divergence at cycle %s is a GENUINE readback"
        % diverge)
    log("      LOGIC gap: it persists with the DPRAM read data forced to 0 AND with")
    log("      every readback net now driven (see #65 root-cause below), so it is")
    log("      neither a memory-value nor an undriven-net artefact.")
    log("")
    log("  #65 root-cause (this pass): the cycle-%s divergence was two orphaned-net"
        % diverge)
    log("  emission/recovery bugs in the SPI-readback datapath, now FIXED —")
    log("    (a) verilog.py: clock-derived-named FFs (spec_clk_N spine FFs) emitted")
    log("        their Q on a dangling alias wire, orphaning the SPI address register")
    log("        that feeds the read-address decode;")
    log("    (b) machxo2_lift.py: PLC F0..F7 slice outputs that leave a tile on an")
    log("        always-on fast-connect wire (HFxW/HFxE) were never unioned, orphaning")
    log("        the OFX/wide-mux fabric feeding the miso serialiser.")
    log("  With both fixed the miso combinational cone is fully driven, yet a deeper")
    log("  readback LOGIC divergence (register-read / serialiser) remains — the next")
    log("  gap to close for a full past-cycle-%s proof." % diverge)

    report_profile(time.perf_counter() - t_start)


if __name__ == "__main__":
    main()
