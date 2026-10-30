#!/usr/bin/env python3.15t
"""Validate the structured RTL lift (lifters/cycloneiv_clean/rtl.py) on corpus designs (#165).

  python3.15t scripts/cycloneiv_clean_rtl_check.py [--names a,b,...] [--sample N] [--cycles 200] [--vo] [--tag T]
Per design:
  (i)   functional equivalence, iverilog, same random vectors: recovered RTL vs the flat emit (every output pad), and with --vo vs the Quartus
        post-fit .vo (via cycloneiv_clean_emit_sim.run_one with the RTL substituted for the flat text; pads named pad_<ball> for that run).
        Stimulus: data pads change every step, pads in the clock / async-clear support of any FF change one at a time (hazard-free).
  (ii)  structure vs the ORIGINAL source (src/top.v): registers (bits), adders (count + widths), comparators, multipliers (MAC), M9K, counters, FSMs
        reported as matched / missing / extra / wrong per construct kind.  Random-LUT specimens carry no word-level structure, so
        recovered counters / FSMs / adders there count as extra (precision), not as hits.
  (iii) readability: lines of the RTL vs the flat emit, constructs recovered per line.
Sample = lift-ready names (reference/lift_ready.tsv) spread evenly over the name families, primary group first; failing scopes are enumerated.
Log tmp/logs/cycloneiv_clean_rtl_check.log, results tmp/cycloneiv_clean/rtl_check_<tag>.json, RTL texts tmp/rtl/<name>.rtl.v (untracked).
"""
import argparse
import collections
import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import heavy_guard  # noqa: E402
log = logging.getLogger("cycloneiv_clean_rtl_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_rtl_check.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
WORK = os.path.join(REPO, "tmp", "rtl")
HOLD_STEP = 2000                           # ps compare spacing in hold-safe mode (1 ps per LUT level x depth << 2 ns)
STEP = 10                                  # ps between stimulus and compare: zero-delay models settle in the same time step
RUN_LIMIT_S = 120                          # 3x the cold worst case of a 5 k-cell iverilog compile + 400 steps (~1-2 s measured by emit_sim)


# ---- source metrics ------------------------------------------------------------------------------------------------------------------
def src_metrics(d):
    t = open(os.path.join(d, "src", "top.v")).read()
    t = re.sub(r"//[^\n]*", "", t)
    ports = {}
    for m in re.finditer(r"\b(?:input|output|wire|reg)\s*(?:\[(\d+):(\d+)\])?\s*(\w+)", t):
        if m[1]:
            ports.setdefault(m[3], int(m[1]) - int(m[2]) + 1)
    regs = len(re.findall(r"\bdffeas\b", t)) + sum((int(m[1]) - int(m[2]) + 1) if m[1] else 1 for m in re.finditer(r"\breg\s*(?:\[(\d+):(\d+)\])?\s*\w+\s*[;,=]", t))
    adders, cmps = [], 0
    for m in re.finditer(r"assign\s+(\w+)\s*=\s*([^;]*);", t):
        rhs = m[2]
        if re.search(r"\w\s*[+]\s*\w", rhs):
            adders.append(("add", max([ports.get(x, 1) for x in re.findall(r"[A-Za-z_]\w*", rhs)] or [1])))
        elif re.search(r"\w\s*-\s*\w", rhs):
            adders.append(("sub", max([ports.get(x, 1) for x in re.findall(r"[A-Za-z_]\w*", rhs)] or [1])))
        if re.search(r"[<>]=?", rhs):
            cmps += 1
    for m in re.finditer(r"<=\s*([^;]*);", t):
        if re.search(r"\w\s*\+\s*\w", m[1]):
            adders.append(("add", 0))
    ctr = len(re.findall(r"(\w+)\s*<=\s*\1\s*[+-]", t))
    return dict(reg_bits=regs, arith=adders, cmps=cmps, mults=len(re.findall(r"\*", t)) + t.count("cycloneiv_mac_mult"),
                m9k=t.count("cycloneiv_ram_block") + len(re.findall(r"\baltsyncram\b", t)), counters=ctr, fsm=len(re.findall(r"\bcase[xz]?\s*\(", t)),
                lut_inst=len(re.findall(r"\bcycloneiv_lcell_comb\b", t)) + len(re.findall(r"localparam \[15:0\] M\d+", t)))


def score_structure(sm, rep):
    """matched / missing / extra / wrong per construct kind (source vs recovered)."""
    out = {}

    def cnt(kind, src, rec, wrong=0):
        m = min(src, rec) - wrong
        out[kind] = dict(matched=max(m, 0), missing=max(src - rec, 0), extra=max(rec - src, 0), wrong=wrong)
    rec_bits = rep["reg_bits"] + sum(1 for _ in [])
    cnt("register_bits", sm["reg_bits"], rep["reg_bits"] + rep.get("fsm_state_bits", 0))
    src_add = [w for k, w in sm["arith"] if k == "add"]
    src_sub = [w for k, w in sm["arith"] if k == "sub"]
    rec_w = rep.get("adder_widths", [])
    wrong = 0
    if src_add and rec_w:
        # width: source result width includes the carry (a + b -> max(w) bits operands); recovered width is the operand width
        sw = sorted(src_add)
        rw = sorted(rec_w)
        wrong = sum(1 for a, b in zip(sw, rw) if a not in (b, b + 1))
    cnt("adders", len(src_add), rep["adders"], wrong)
    cnt("subtractors", len(src_sub), rep["subtractors"])
    cnt("comparators", sm["cmps"], rep["comparators"])
    cnt("macs", sm["mults"], rep["mac"])
    cnt("m9k", sm["m9k"], rep["m9k"])
    cnt("lut_cells", sm["lut_inst"], rep["flat_luts"])
    cnt("counters", sm["counters"], rep["counters"])
    cnt("fsms", sm["fsm"], rep["fsms"])
    return out


# ---- simulation ----------------------------------------------------------------------------------------------------------------------
def clock_pads(nl):
    """Pads (and undecoded sources) reaching an FF clock / async clear through LUTs only."""
    lut = {L["name"]: L for L in nl.luts}
    co = {f"co_{L['x']}_{L['y']}_{L['le']}": L for L in nl.luts}
    seen, stack, pads = set(), [], set()
    for F in nl.ffs:
        stack += [F.get("clk"), F.get("aclr")]
    while stack:
        s = stack.pop()
        if not s or s in seen:
            continue
        seen.add(s)
        L = lut.get(s) or co.get(s)
        if L is not None:
            stack += list(L["pins"])
        else:
            pads.add(s)
    return pads


def make_tb(nl, mod_a, mod_b, pa, pb, cycles, seed, wd, flat="", step=STEP):
    # inout pads: weak TB drive (a floating pad reads x in the flat model, which the minimised RTL can mask)
    undriven = [f"pad_{io['ball']}" for io in nl.ios if io["dir"] not in ("input", "output")]
    ins = [f"pad_{io['ball']}" for io in nl.ios if io["dir"] == "input"] + undriven + sorted(nl.srcs)
    # output pads with no driver (undecoded) that logic still reads are floating (x in the flat model): forced from the TB in both models
    floating = [f"pad_{io['ball']}" for io in nl.ios if io["dir"] == "output" and f"assign pad_{io['ball']} =" not in flat]
    outs = [f"pad_{io['ball']}" for io in nl.ios if io["dir"] == "output" and f"pad_{io['ball']}" not in floating]
    pins_conn = list(ins)
    ins += floating
    ckp = clock_pads(nl)
    L = ["`timescale 1ps/1ps", "module tb;", "integer cyc, bad, badx, i, seed;"]
    L += [f"reg i_{n} = 0;" for n in ins]
    L += [f"wire w_{n}; assign (weak0, weak1) w_{n} = i_{n};" for n in undriven]     # inout ports need a net; a weak TB drive shows only while the DUT releases (z)
    L += [f"wire a_{n}, b_{n};" for n in outs]
    conn = lambda pre, tag: ", ".join([f".{n.replace('pad_', pre) if n.startswith('pad_') else n}({'w_' if n in undriven else 'i_'}{n})" for n in pins_conn] +
                                      [f".{n.replace('pad_', pre)}({tag}_{n})" for n in outs])
    L.append(f"{mod_a} ua({conn(pa, 'a')});")
    L.append(f"{mod_b} ub({conn(pb, 'b')});")
    L += [f"initial begin seed = {seed}; bad = 0; badx = 0;"]
    L += [f"force ua.{n} = i_{n}; force ub.{n.replace('pad_', pb)} = i_{n};" for n in floating]
    L += [ f"for (cyc = 0; cyc < {cycles}; cyc = cyc + 1) begin"]
    for n in ins:
        if n not in ckp:
            L.append(f"  i_{n} = $random(seed);")
    L.append(f"  #{step};")
    L.append("  " + " ".join(f"if (a_{n} !== b_{n}) bad = bad + 1;" for n in outs[:0]))
    cmp_ = "".join(f"if (a_{n} !== b_{n}) begin bad = bad + 1; if ($isunknown(a_{n})) badx = badx + 1; end " for n in outs)
    L.append("  " + cmp_)
    for n in sorted(ckp & set(ins)):
        L.append(f"  i_{n} = ~i_{n}; #{step}; {cmp_}")
        L.append(f"  i_{n} = ~i_{n}; #{step}; {cmp_}")
    L += ["end", f'$display("RESULT outputs={len(outs)} clocks={len(ckp & set(ins))} bad=%0d badx=%0d", bad, badx);', "$finish;", "end", "endmodule"]
    p = os.path.join(wd, "tb.v")
    open(p, "w").write("\n".join(L) + "\n")
    return p, len(outs)


def run_iv(files, wd, tag, defs=()):
    vvp = os.path.join(wd, f"{tag}.vvp")
    try:
        c = heavy_guard.guarded(["iverilog", "-g2012", "-o", vvp, *defs, *files], "iverilog", log, overall_s=RUN_LIMIT_S)
        if c.timed_out:
            return "timeout", f"iverilog exceeded the guard ({RUN_LIMIT_S}s overall / 60 s stall)"
        if c.returncode:
            return "compile_error", c.stderr[:400]
        r = heavy_guard.guarded(["vvp", vvp], "vvp", log, overall_s=RUN_LIMIT_S)
        if r.timed_out:
            return "timeout", f"vvp exceeded the guard ({RUN_LIMIT_S}s overall / 60 s stall)"
    except OSError as e:
        return "tool_missing", str(e)
    m = re.search(r"RESULT outputs=(\d+) clocks=(\d+) bad=(\d+) badx=(\d+)", r.stdout)
    if not m:
        return "no_result", (r.stdout + r.stderr)[-300:]
    return ("none" if int(m[1]) == 0 else "pass" if int(m[3]) == 0 else "x_in_flat" if int(m[3]) == int(m[4]) else "fail"), dict(outputs=int(m[1]), clocks=int(m[2]), bad=int(m[3]), flat_x=int(m[4]))


def one(cx, d, cycles, seed):
    from lifters.cycloneiv_clean import emit, rtl
    name = os.path.basename(d)
    wd = os.path.join(WORK, name)
    os.makedirs(wd, exist_ok=True)
    try:
        nl = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), name, 2).run()
    except SystemExit as e:                    # decoder die(): a result for this design, not an abort of the run
        return dict(design=name, eq_flat="emit_exit", eq_info=str(e))
    flat = emit.verilog(nl)
    t0 = time.time()
    text, rep = rtl.lift(nl, "io_", "cyc4_rtl")
    lift_s = time.time() - t0
    fv, rv = os.path.join(wd, "flat.v"), os.path.join(WORK, f"{name}.rtl.v")
    open(fv, "w").write(flat)
    open(rv, "w").write(text)
    res = dict(design=name, report=rep, flat_lines=flat.count("\n"), rtl_lines=text.count("\n"), lift_s=round(lift_s, 2))
    # async clear / clock driven by logic: zero-delay evaluation order (vector vs per-FF updates) changes glitches, not function -> hold-safe delays
    lutn = {L_["name"] for L_ in nl.luts}
    delayed = any((F_.get("aclr") in lutn) or (F_.get("clk") in lutn) for F_ in nl.ffs)
    tb, nout = make_tb(nl, "cyc4_top", "cyc4_rtl", "pad_", "io_", cycles, seed, wd, flat, HOLD_STEP if delayed else STEP)
    st, info = run_iv([tb, fv, rv], wd, "eq", ["-DLUT_DELAY=#1"] if delayed else [])
    res["hold_safe"] = delayed
    res["eq_flat"], res["eq_info"] = st, info
    try:
        res["src"] = src_metrics(d)
        res["structure"] = score_structure(res["src"], rep)
    except OSError:
        res["structure"] = None
    return res


RICH_BYTES = 3000          # decision: --rich keeps designs whose source is >= 3 kB (random-LUT / register networks, not single-cell specimens)


def pick(names_arg, sample, rich=False):
    if names_arg:
        return names_arg.split(",")
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(REPO, "reference", "lift_ready.tsv")) if not l.startswith("#")]
    rows = [r for r in rows if r[0] != "name"]
    root = os.path.join(REPO, "corpus", "cycloneiv")
    grp = {r[0]: (r[1] if len(r) > 1 else "primary") for r in rows
           if not rich or os.path.getsize(os.path.join(root, r[0], "src", "top.v")) >= RICH_BYTES}
    fam = collections.defaultdict(list)
    for n in grp:
        fam[re.sub(r"[0-9]+", "#", re.sub(r"_[0-9a-f]{10}$", "", n))].append(n)
    out, k = [], 0
    pools = {f: sorted(v) for f, v in fam.items()}
    # round-robin across families, primary group first
    for f in pools:
        pools[f].sort(key=lambda n: (grp[n] != "primary", n))
    while len(out) < sample and any(pools.values()):
        for f in sorted(pools):
            if pools[f] and len(out) < sample:
                v = pools[f]
                out.append(v.pop(len(v) // 2) if k % 2 else v.pop(0))
        k += 1
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--cycles", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--rich", action="store_true", help="sample only designs with src/top.v >= RICH_BYTES")
    ap.add_argument("--vo", action="store_true", help="also compare the RTL against the post-fit .vo (emit_sim.run_one with the RTL substituted)")
    ap.add_argument("--tag", default="x")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    root = os.path.join(REPO, "corpus", "cycloneiv")
    ds = [os.path.join(root, n) for n in pick(a.names, a.sample, a.rich)]
    import heavy_guard
    from lifters.cycloneiv_clean import emit, rtl
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.6)
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_clean_rtl_check", log):
        cx = emit.Ctx()
        cx.st.edge_ids([0], [0])
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(one, cx, d, a.cycles, a.seed): d for d in ds}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=60, return_when=cf.FIRST_COMPLETED)
                if not done:
                    log.error("stall: no design finished in 60 s (%d pending, load %s)", len(pending), os.getloadavg())
                    raise SystemExit(3)
                for f in done:
                    try:
                        r = f.result()
                    except Exception as e:                  # an unliftable design is a result, not a skip
                        import traceback
                        log.error("%s: %s\n%s", futs[f], e, traceback.format_exc())
                        r = dict(design=os.path.basename(futs[f]), eq_flat="error", eq_info=f"{type(e).__name__}: {e}")
                    rows.append(r)
                    log.info("%s eq_flat=%s %s lines %s -> %s", r["design"], r["eq_flat"], r.get("eq_info"), r.get("flat_lines"), r.get("rtl_lines"))
        if a.vo:
            import cycloneiv_clean_emit_sim as S
            orig = emit.verilog

            def sweep(key):
                with cf.ThreadPoolExecutor(a.workers) as ex:
                    vfut = {ex.submit(S.run_one, cx, d, a.cycles, a.seed): d for d in ds}
                    for f in cf.as_completed(vfut):
                        n = os.path.basename(vfut[f])
                        try:
                            r = f.result()
                            v = dict(status=r["status"], comparable=r.get("comparable"), bad_ports=r.get("bad_ports"), err=r.get("err"))
                        except Exception as e:
                            v = dict(status="error", err=f"{type(e).__name__}: {e}")
                        next(x for x in rows if x["design"] == n)[key] = v
            sweep("eq_vo_flat")                                    # baseline: the flat emit vs .vo (same stimulus)
            emit.verilog = lambda nl, module="cyc4_top": rtl.lift(nl, "pad_", module)[0]          # run_one compiles the RTL as the DUT
            try:
                sweep("eq_vo")
            finally:
                emit.verilog = orig
    # ---- summary
    st = collections.Counter(r["eq_flat"] for r in rows)
    log.info("EQUIVALENCE rtl vs flat: %s", dict(st))
    if a.vo:
        log.info("EQUIVALENCE flat vs .vo (baseline): %s", dict(collections.Counter(r.get("eq_vo_flat", {}).get("status") for r in rows)))
        log.info("EQUIVALENCE rtl vs .vo: %s", dict(collections.Counter(r.get("eq_vo", {}).get("status") for r in rows)))
        same = sum(1 for r in rows if r.get("eq_vo") and r["eq_vo"].get("status") == r["eq_vo_flat"].get("status") and r["eq_vo"].get("bad_ports") == r["eq_vo_flat"].get("bad_ports"))
        log.info("rtl-vs-.vo result identical to flat-vs-.vo (status and bad ports): %d / %d", same, len(rows))
    tot = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        for k, v in (r.get("structure") or {}).items():
            tot[k].update(v)
    for k, v in tot.items():
        log.info("STRUCTURE %-14s %s", k, dict(v))
    fl = sum(r.get("flat_lines", 0) for r in rows)
    rl = sum(r.get("rtl_lines", 0) for r in rows)
    keys = ("chains", "adders", "subtractors", "comparators", "counters", "bundles", "shift_registers", "fsms", "muxes", "sop", "xor", "tt", "flat_lut_left")
    agg = {k: sum(r["report"][k] for r in rows if "report" in r) for k in keys}
    log.info("READABILITY flat lines %d, rtl lines %d (%.1f%%); constructs %s; flat LUTs %d, flat FFs %d", fl, rl, 100.0 * rl / max(fl, 1), agg,
             sum(r["report"]["flat_luts"] for r in rows if "report" in r), sum(r["report"]["flat_ffs"] for r in rows if "report" in r))
    fails = [r for r in rows if r["eq_flat"] not in ("pass", "none")]
    scope = collections.Counter()
    for r in fails:
        rep = r.get("report", {})
        scope[r["eq_flat"] + (":compile" if r["eq_flat"] == "compile_error" else "")] += 1
        if isinstance(r.get("eq_info"), dict) and r["eq_info"].get("bad") == r["eq_info"].get("flat_x"):
            scope["all_mismatches_have_x_in_flat_model"] += 1
        for k in ("chains", "fsms", "counters", "shift_registers", "m9k", "mac", "loop_luts", "cone_cut"):
            if rep.get(k):
                scope["fail_has_" + k] += 1
    log.info("FAILING scopes (%d designs): %s", len(fails), dict(scope))
    for r in fails[:12]:
        log.info("  fail %s %s %s", r["design"], r["eq_flat"], str(r.get("eq_info"))[:200])
    json.dump(dict(equiv=dict(st), failing_scope=dict(scope), rows=rows, seconds=round(time.time() - t0)), open(os.path.join(OUT, f"rtl_check_{a.tag}.json"), "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
