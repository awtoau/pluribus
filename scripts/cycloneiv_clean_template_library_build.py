#!/usr/bin/env python3.15t
"""#188: bulk harness-stripped template library -- generalizes cycloneiv_clean_pattern_stripper_poc.py
(one construct) to ~70 small constructs, each built with Quartus, lifted, stripped to a bare template
(leaf count + exact truth table, no pad names/coordinates/instance names -- see the PoC's docstring for
the method). Logic-gate combinations x width, small arithmetic (add/sub/compare), muxes, priority
encoders. Each construct stays small (variety of shape, not individual complexity) so each Quartus
build stays in the PoC's ~10-15s range.

Two separate phases, each with its OWN concurrency cap -- found by measurement (2026-10-31) that fusing
them under one --jobs number overloads the second phase: Quartus BUILD (external subprocess, short CPU +
I/O) and the Python-side STRIP (emit.Builder(...).run(), measured standalone: 27s wall, 1.6 GB RSS for a
single tiny 2-input specimen -- real fixed per-call cost, not negligible, regardless of specimen size)
are fundamentally different workloads and do not share a safe concurrency number.
  Phase 1 (--jobs, default 18): all Quartus builds complete first, via the sanctioned pattern
  (cycloneiv_fuzz.py ~255-266) -- ThreadPoolExecutor of external subprocesses, gated per-task by
  heavy_guard.wait_available, whole batch under heavy_guard.heavy_lock (its own cgroup + hard memory cap,
  #124). Confirmed NOT the bottleneck even at 18-way.
  Phase 2 (--strip-workers, default 6): strip_one runs over the resulting bitstreams afterward, at its
  own smaller cap -- 6 is the one number actually observed fast in practice (run 1, before the two
  phases were fused back together and hit the 56 GB lease budget ceiling at 10 concurrent strip_one
  calls: 10 x the OLD borrowed-from-the-DJI-gate 5.2 GB figure). PER_STRIP_GB below is sized from the
  real measurement instead.
Do NOT raise LEASE_BUDGET_GB or shrink the per-strip GB figure to force more concurrency through the
budget ceiling -- that gate did its job correctly (caught a real oversubscription); the fix is fewer
concurrent strip_one calls, not a bigger or falsely-cheap budget.

  python3.15t scripts/cycloneiv_clean_template_library_build.py [--jobs N] [--strip-workers N] [--resume]
Log tmp/logs/cycloneiv_clean_template_library_build.log. Builds corpus/cycloneiv/tlib_<name>/ per
construct (gitignored like every other cycloneiv fuzz specimen, src/+design.toml tracked). Writes the
stripped library to reference/template_library.json (tracked -- derived-but-small, same role as
reference/*.tsv ledgers, not a multi-MB corpus build output). --resume skips specimens whose dir already
has rebuild.json status=ok (built, not stripped -- the library JSON is always rebuilt from scratch).
"""
import argparse
import itertools
import json
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("template_library_build")
DEVICE = "EP4CGX150DF31C7"
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10}
OUT = Path(REPO) / "reference" / "template_library.json"

# Verilog reduction-operator form per sub-gate: unambiguous, no string surgery.  The two 1-bit sub-gate
# results are combined by a 2-input boolean function applied bit-wise -- expressed as a ternary over the
# 4-row truth table (also unambiguous: no risk of misreading a reduction operator as a binary infix one).
REDUCE_OPS = {"AND": "&", "OR": "|", "XOR": "^", "NAND": "~&", "NOR": "~|", "XNOR": "~^"}
COMBINE_FN = {"AND": lambda x, y: x & y, "OR": lambda x, y: x | y, "XOR": lambda x, y: x ^ y,
              "NAND": lambda x, y: 1 - (x & y), "NOR": lambda x, y: 1 - (x | y), "XNOR": lambda x, y: 1 - (x ^ y)}


def _combine_expr(combine_op, bit_a, bit_b):
    """2-bit-input boolean function as a Verilog expression over 1-bit wires bit_a/bit_b, built from its
    own truth table so the operator choice can't be misparsed as the wrong arity."""
    fn = COMBINE_FN[combine_op]
    rows = [fn(a, b) for a in (0, 1) for b in (0, 1)]  # index = (bit_a<<1)|bit_b
    if rows == [0, 0, 0, 1]:
        return f"({bit_a} & {bit_b})"
    if rows == [0, 1, 1, 1]:
        return f"({bit_a} | {bit_b})"
    if rows == [0, 1, 1, 0]:
        return f"({bit_a} ^ {bit_b})"
    if rows == [1, 1, 1, 0]:
        return f"(~({bit_a} & {bit_b}))"
    if rows == [1, 0, 0, 0]:
        return f"(~({bit_a} | {bit_b}))"
    if rows == [1, 0, 0, 1]:
        return f"(~({bit_a} ^ {bit_b}))"
    raise AssertionError(f"unreachable combine_op {combine_op}")


def gen_logic_combo_specimens():
    """gate(w1 inputs) combined-with gate(remaining inputs), w = 2..6 total.  Widths split roughly in
    half between the two sub-gates; combining gate drawn from the same 6-op set.  Each sub-gate is a
    Verilog reduction op over its own named-input bus; the two 1-bit sub-results are combined via
    _combine_expr (truth-table-derived, not a guessed operator string)."""
    specs = []
    for w in range(2, 7):
        w1 = max(1, w // 2)
        w2 = w - w1
        for inner_op in ("AND", "OR", "XOR"):
            for combine_op in REDUCE_OPS:
                label = f"logic_w{w}_{inner_op.lower()}{w1}_{combine_op.lower()}{w2}"
                ports = ", ".join(f"input i{i}" for i in range(w))
                busA = "{" + ", ".join(f"i{i}" for i in range(w1)) + "}" if w1 > 1 else "i0"
                if w2 == 0:
                    expr = f"({REDUCE_OPS[inner_op]}{busA})"
                else:
                    busB = "{" + ", ".join(f"i{i}" for i in range(w1, w)) + "}" if w2 > 1 else f"i{w1}"
                    expr = _combine_expr(combine_op, f"({REDUCE_OPS[inner_op]}{busA})", f"({REDUCE_OPS[inner_op]}{busB})")
                rtl = (f"module top(input clk, {ports}, output q);\n  reg r;\n"
                       f"  always @(posedge clk) r <= {expr};\n  assign q = r;\nendmodule\n")
                specs.append(dict(name=label, rtl=rtl, n_inputs=w, kind="logic"))
    return specs


def gen_arith_specimens():
    specs = []
    for w in (4, 8):
        a = ", ".join(f"input [{w - 1}:0] a" for _ in range(1))
        rtl_add = (f"module top(input clk, input [{w - 1}:0] a, input [{w - 1}:0] b, output [{w}:0] q);\n"
                   f"  reg [{w}:0] r;\n  always @(posedge clk) r <= a + b;\n  assign q = r;\nendmodule\n")
        rtl_sub = (f"module top(input clk, input [{w - 1}:0] a, input [{w - 1}:0] b, output [{w}:0] q);\n"
                   f"  reg [{w}:0] r;\n  always @(posedge clk) r <= a - b;\n  assign q = r;\nendmodule\n")
        rtl_ge = (f"module top(input clk, input [{w - 1}:0] a, input [{w - 1}:0] b, output q);\n"
                  f"  reg r;\n  always @(posedge clk) r <= (a >= b);\n  assign q = r;\nendmodule\n")
        rtl_gt = (f"module top(input clk, input [{w - 1}:0] a, input [{w - 1}:0] b, output q);\n"
                  f"  reg r;\n  always @(posedge clk) r <= (a > b);\n  assign q = r;\nendmodule\n")
        rtl_eq = (f"module top(input clk, input [{w - 1}:0] a, input [{w - 1}:0] b, output q);\n"
                  f"  reg r;\n  always @(posedge clk) r <= (a == b);\n  assign q = r;\nendmodule\n")
        specs += [
            dict(name=f"add_w{w}", rtl=rtl_add, n_inputs=2 * w, kind="arith"),
            dict(name=f"sub_w{w}", rtl=rtl_sub, n_inputs=2 * w, kind="arith"),
            dict(name=f"cmp_ge_w{w}", rtl=rtl_ge, n_inputs=2 * w, kind="arith"),
            dict(name=f"cmp_gt_w{w}", rtl=rtl_gt, n_inputs=2 * w, kind="arith"),
            dict(name=f"cmp_eq_w{w}", rtl=rtl_eq, n_inputs=2 * w, kind="arith"),
        ]
    return specs


def gen_mux_specimens():
    specs = []
    # 2:1 mux, data widths 1 and 4
    for w in (1, 4):
        if w == 1:
            rtl = ("module top(input clk, input sel, input a, input b, output q);\n  reg r;\n"
                   "  always @(posedge clk) r <= sel ? a : b;\n  assign q = r;\nendmodule\n")
            n_in = 3
        else:
            rtl = (f"module top(input clk, input sel, input [{w - 1}:0] a, input [{w - 1}:0] b, output [{w - 1}:0] q);\n"
                   f"  reg [{w - 1}:0] r;\n  always @(posedge clk) r <= sel ? a : b;\n  assign q = r;\nendmodule\n")
            n_in = 2 * w + 1
        specs.append(dict(name=f"mux2_w{w}", rtl=rtl, n_inputs=n_in, kind="mux"))
    # 4:1 mux, 1-bit data
    rtl4 = ("module top(input clk, input [1:0] sel, input a, input b, input c, input d, output q);\n  reg r;\n"
            "  always @(posedge clk) case (sel) 2'd0: r <= a; 2'd1: r <= b; 2'd2: r <= c; default: r <= d; endcase\n"
            "  assign q = r;\nendmodule\n")
    specs.append(dict(name="mux4_w1", rtl=rtl4, n_inputs=6, kind="mux"))
    return specs


def gen_priority_encoder_specimens():
    specs = []
    for w in (4, 6):
        ports = ", ".join(f"input i{i}" for i in range(w))
        bits = max(1, (w - 1).bit_length())
        cases = "\n".join(f"    else if (i{i}) r <= {bits}'d{i};" for i in range(w))
        rtl = (f"module top(input clk, {ports}, output [{bits - 1}:0] q);\n  reg [{bits - 1}:0] r;\n"
               f"  always @(posedge clk)\n    if (i0) r <= {bits}'d0;\n{cases}\n    else r <= {bits}'d{w};\n"
               f"  assign q = r;\nendmodule\n")
        specs.append(dict(name=f"prio_enc_w{w}", rtl=rtl, n_inputs=w, kind="prio_enc"))
    return specs


def gen_fsm_specimens():
    # Two small Moore FSMs: a 3-state traffic-light-style sequencer, and a 2-state toggle-on-condition.
    rtl_seq3 = ("module top(input clk, input rst, input go, output [1:0] q);\n  reg [1:0] st;\n"
                "  always @(posedge clk)\n    if (rst) st <= 2'd0;\n    else case (st)\n"
                "      2'd0: st <= go ? 2'd1 : 2'd0;\n      2'd1: st <= 2'd2;\n      2'd2: st <= 2'd0;\n"
                "      default: st <= 2'd0;\n    endcase\n  assign q = st;\nendmodule\n")
    rtl_toggle = ("module top(input clk, input rst, input cond, output q);\n  reg st;\n"
                  "  always @(posedge clk)\n    if (rst) st <= 1'b0;\n    else if (cond) st <= ~st;\n"
                  "  assign q = st;\nendmodule\n")
    return [dict(name="fsm_seq3", rtl=rtl_seq3, n_inputs=3, kind="fsm"),
            dict(name="fsm_toggle", rtl=rtl_toggle, n_inputs=2, kind="fsm")]


def all_specimens():
    specs = gen_logic_combo_specimens() + gen_arith_specimens() + gen_mux_specimens() + gen_priority_encoder_specimens() + gen_fsm_specimens()
    seen, out = set(), []
    for s in specs:
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        out.append(s)
    return out


def already_built_ok(name):
    d = Path(REPO) / "corpus" / "cycloneiv" / f"tlib_{name}"
    rj = d / "rebuild.json"
    if not rj.exists():
        return False
    try:
        return json.load(open(rj)).get("status") == "ok"
    except (json.JSONDecodeError, OSError):
        return False


def build_one(name, rtl):
    import cycloneiv_fuzz as fz
    import toolchain
    d = Path(REPO) / "corpus" / "cycloneiv" / f"tlib_{name}"
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    (d / "src" / "top.v").write_text(rtl)
    qsf = ['set_location_assignment PIN_A11 -to clk', 'set_global_assignment -name AUTO_GLOBAL_CLOCK OFF',
           'set_global_assignment -name SEED 1']
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "#188 template library: {name}"\n'
        f'exercises = ["template_library"]\nqsf = {json.dumps(qsf)}\ndevice = "{DEVICE}"\n')
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"] + qsf
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            log.error("%s: %s FAILED, skipping", name, step)
            shutil.rmtree(q, ignore_errors=True)
            return None
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    json.dump({"status": "ok", "elapsed_s": round(time.time() - t0, 1)}, open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s build ok %.1fs", name, time.time() - t0)
    return d / "bitstream.rbf"


# Measured 2026-10-31 (python3.15t, one tiny 2-input specimen, zero other load): emit.Builder(...).run()
# standalone RSS 1.6 GB. NOT heavy_guard.JOB_GB["cyc4_clean_gate_base"]+4*["cyc4_clean_gate_worker"] (5.2 GB)
# -- that figure is the DJI-image-scale gate's own sizing, wrong for a specimen this small; using it is
# what let 10 concurrent strip_one calls (10 x 5.2 = 52 GB) hit the 56 GB LEASE_BUDGET_GB ceiling.
PER_STRIP_GB = 2.0   # 1.6 GB measured + headroom, same rounding margin as PER_BUILD_GB


def strip_one(name, kind, rbf):
    from lifters.cycloneiv_clean import emit, patterns as PT
    import heavy_guard
    with heavy_guard.lease(PER_STRIP_GB, "cyc4_clean_tlib_strip", log):
        cx = emit.Ctx()
        nl = emit.Builder(cx, str(rbf), None).run()
    D = PT.Design(nl)
    out = []
    for F in D.clocked:
        leaves = sorted(D.support(F["d"]))
        kinds = [D.kind(s) for s in leaves]
        if not all(k == "pad" for k in kinds):
            continue
        tt = PT.cone_tt(D, F["d"], leaves)
        out.append(dict(source=name, kind=kind, ff=F["name"], n_leaves=len(leaves), tt=tt, tt_hex=f"{tt:x}"))
    return out


# Per-build RAM gate for wait_available (NOT a heavy_guard.JOB_GB key: no key here fits a Quartus
# map/fit/asm/cpf chain on a specimen this small -- "unmeasured jobs are absent on purpose" per this
# project's own rule on JOB_GB).  2.0 GB = docs/performance.md's measured quartus_fit 1.06 GB + quartus_map
# 0.53 GB RSS for a single small design (cyclonev_corpus_build.py row), rounded up for asm/cpf headroom.
PER_BUILD_GB = 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=18,
                     help="concurrent Quartus builds (phase 1) -- confirmed not the bottleneck at this size class, separate from --strip-workers")
    ap.add_argument("--strip-workers", type=int, default=6,
                     help="concurrent strip_one/emit.Builder.run() calls (phase 2) -- 6 is the only number actually observed fast in practice; raising this re-risks the 56 GB lease budget ceiling, see module docstring")
    ap.add_argument("--resume", action="store_true",
                     help="skip specimens whose corpus/cycloneiv/tlib_<name>/rebuild.json already says status=ok (strip_one still re-runs on their existing bitstream.rbf, since the library JSON is rebuilt from scratch every run)")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_template_library_build.log"))])
    import heavy_guard
    specs = all_specimens()
    log.info("built %d specimen definitions, jobs=%d strip_workers=%d resume=%s", len(specs), a.jobs, a.strip_workers, a.resume)
    failed_lock = __import__("threading").Lock()
    failed = []
    t_start = time.time()

    # Phase 1: all Quartus builds (or resume-skips), --jobs concurrency.  No strip_one here -- that was
    # the bug (fusing a cheap-and-fast subprocess phase with an expensive pure-Python phase under one
    # shared concurrency number let phase 2 pile up and hit the lease budget ceiling).
    def build_phase(s):
        if a.resume and already_built_ok(s["name"]):
            rbf = Path(REPO) / "corpus" / "cycloneiv" / f"tlib_{s['name']}" / "bitstream.rbf"
            log.info("%s: resume -- already built, reusing %s", s["name"], rbf)
            return s["name"], s["kind"], rbf
        heavy_guard.wait_available(log, s["name"], PER_BUILD_GB)
        rbf = build_one(s["name"], s["rtl"])
        if rbf is None:
            with failed_lock:
                failed.append(s["name"])
            return s["name"], s["kind"], None
        return s["name"], s["kind"], rbf

    with heavy_guard.heavy_lock("cyc4_template_library_build", log):
        with ThreadPoolExecutor(a.jobs) as ex:
            built = list(ex.map(build_phase, specs))
    t_build_done = time.time()
    log.info("phase 1 (build) done: %d specimens, %d failed, %.0fs", len(specs), len(failed), t_build_done - t_start)

    # Phase 2: strip_one over every successfully-built bitstream, --strip-workers concurrency (its own
    # cap, independent of --jobs -- see module docstring for why these must not share one number).
    library_lock = __import__("threading").Lock()
    library = []
    to_strip = [(name, kind, rbf) for name, kind, rbf in built if rbf is not None]

    def strip_phase(item):
        name, kind, rbf = item
        templates = strip_one(name, kind, rbf)
        if not templates:
            log.warning("%s: no all-pad-leaf FF found (harness absorbed the construct or it has >1 FF stage)", name)
        with library_lock:
            library.extend(templates)

    with ThreadPoolExecutor(a.strip_workers) as ex:
        list(ex.map(strip_phase, to_strip))
    elapsed = time.time() - t_start
    log.info("phase 2 (strip) done: %d specimens, %.0fs", len(to_strip), time.time() - t_build_done)
    # de-dup identical (n_leaves, tt) templates from different sources (e.g. AND-combine variants that
    # reduce to the same function) but keep every source label that produced it, for provenance.  Dedup
    # keys internally on the raw int `tt` (fine as a dict/sort key at any size); the JSON OUTPUT carries
    # only tt_hex, not the raw int -- a 16-leaf cone's tt is a 1<<65536-valued int whose decimal repr
    # exceeds CPython's int-to-str digit limit (a deliberate DoS guard) and json.dump crashes trying to
    # serialize it.  tt_hex has no such limit; anything reading this file back parses int(tt_hex, 16).
    by_key = {}
    for t in library:
        key = (t["n_leaves"], t["tt"])
        by_key.setdefault(key, {"n_leaves": t["n_leaves"], "tt_hex": t["tt_hex"], "sources": [], "_sort_tt": t["tt"]})
        by_key[key]["sources"].append({"source": t["source"], "kind": t["kind"], "ff": t["ff"]})
    dedup = sorted(by_key.values(), key=lambda t: (t["n_leaves"], t["_sort_tt"]))
    for t in dedup:
        del t["_sort_tt"]
    result = dict(n_specimens=len(specs), n_failed=len(failed), failed=failed, n_raw_templates=len(library),
                  n_unique_templates=len(dedup), elapsed_s=round(elapsed, 1), templates=dedup)
    OUT.parent.mkdir(exist_ok=True)
    json.dump(result, open(OUT, "w"), indent=1)
    log.info("RESULT specimens=%d failed=%d raw_templates=%d unique_templates=%d elapsed=%.0fs -> %s",
              len(specs), len(failed), len(library), len(dedup), elapsed, OUT)
    print(json.dumps({k: v for k, v in result.items() if k != "templates"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
