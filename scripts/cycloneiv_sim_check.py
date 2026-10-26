#!/usr/bin/env python3.15t
"""Behavioural acceptance test for the Cyclone IV LUT decode: decoded Verilog simulated (iverilog)
against the Quartus post-fit netlist, per design; bad output count reported.
Pattern: scripts/cyclonev_lifted_sim_check.py.

- DUT-A: corpus/cycloneiv/<design>/postfit.vo (top module only) + the VENDOR models of the cells it
  uses, cut from quartus/eda/sim_lib/cycloneive_atoms.v (the whole file does not compile in
  iverilog: its PLL model) + altera_primitives.v (dffeas).
- DUT-B: decoded.v.  LUT mask = CRAM bits read with the bit map learnt from the ONE-HOT builds
  only (cycloneiv_fuzz_analyze.py JSON).  NOT decoded yet, taken from the .vo and counted as
  oracle-supplied: which pad drives each LUT input, the output-buffer inversion.  So this checks
  the mask decode end to end (bit positions, polarity, input order), not routing.
- Stimulus: all 16 input vectors, then 64 seeded random ones; X counted, not compared.

  python3.15t scripts/cycloneiv_sim_check.py [--match 'lut_*']
Log: tmp/logs/cycloneiv_sim_check.log; per design tmp/cycloneiv/sim/<design>/
"""
import argparse
import fnmatch
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
LOG = REPO / "tmp" / "logs" / "cycloneiv_sim_check.log"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_fuzz_analyze as fa  # noqa: E402
import toolchain  # noqa: E402

SIMLIB = Path(str(toolchain.quartus_bin())).parent / "eda" / "sim_lib"
# iverilog compile < 1 s, run < 1 s for 80 vectors on one LUT; 60 s = hung (stall rule).
IVERILOG_LIMIT_S = 60


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def vendor_models(names):
    """Cut the named modules (and the cycloneive_* modules they instantiate) from the vendor file."""
    src = (SIMLIB / "cycloneive_atoms.v").read_text(errors="replace")
    starts = {m.group(1): m.start() for m in re.finditer(r"^module\s+(\w+)", src, re.M)}
    out, seen, todo = [], set(), list(names)
    while todo:
        n = todo.pop()
        if n in seen or n not in starts:
            continue
        seen.add(n)
        body = src[starts[n]:src.index("endmodule", starts[n]) + len("endmodule")]
        out.append(body)
        todo += [m for m in re.findall(r"^\s*(cycloneive_\w+)\s", body, re.M) if m in starts]
    return "`timescale 1 ps/1 ps\n" + "\n\n".join(out) + "\n"


def decode_mask(ones, bitmap):
    m = 0
    for k in range(16):
        hits = bitmap.get(str(k)) or bitmap.get(k)
        if not hits or len(hits) != 1:
            return None
        fr, bit, inv = hits[0]
        if ((fr, bit) in ones) != inv:
            m |= 1 << k
    return m


def check(name, bitmaps, steps, flip=0):
    d = CORPUS / name
    if not (d / "bitstream.rbf").exists():
        return name, "no build", None
    _, b = fa.load(name)
    vo = b["vo"]
    lut = [(nm, a) for nm, a in vo.atoms.items() if a["type"] == "cycloneive_lcell_comb"]
    if len(lut) != 1 or lut[0][1]["location"] not in bitmaps:
        return name, "no verdict: needs exactly one LUT at a mapped site", None
    lname, la = lut[0]
    mask = decode_mask(b["ones"], bitmaps[la["location"]])
    if mask is None:
        return name, "no verdict: bit map incomplete", None
    mask ^= flip
    # oracle-supplied wiring: LUT input -> pad, LUT -> obuf (with inversion)
    pad_of = {}
    for a in vo.atoms.values():
        if a["type"] == "cycloneive_io_ibuf":
            o = next(n for p, _b, _d, n, _i, _c in a["conns"] if p == "o")
            i = next(n for p, _b, _d, n, _i, _c in a["conns"] if p == "i")
            pad_of[vo.canon(o)] = i
    idx = []
    for port in ("dataa", "datab", "datac", "datad"):
        c = [(n, inv, const) for p, _b, _d, n, inv, const in la["conns"] if p == port]
        if not c:
            idx.append("1'b0")
        elif c[0][2] is not None:
            idx.append(f"1'b{c[0][2]}")
        else:
            n, inv, _ = c[0]
            idx.append(("~" if inv else "") + pad_of[vo.canon(n)])
    comb = next(n for p, _b, _d, n, _i, _c in la["conns"] if p == "combout")
    outs = []
    for a in vo.atoms.values():
        if a["type"] == "cycloneive_io_obuf":
            src = [(n, inv) for p, _b, _d, n, inv, _c in a["conns"] if p == "i"][0]
            o = next(n for p, _b, _d, n, _i, _c in a["conns"] if p == "o")
            if vo.canon(src[0]) == vo.canon(comb):
                outs.append((o, src[1]))
    ins = sorted(p for p, dr in vo.port_dirs.items() if dr == "input")
    pouts = sorted(p for p, dr in vo.port_dirs.items() if dr == "output")
    if not outs:
        return name, "no verdict: LUT drives no output buffer", None
    work = REPO / "tmp" / "cycloneiv" / "sim" / name
    work.mkdir(parents=True, exist_ok=True)
    lines = [f"module top_decoded({', '.join(f'input {p}' for p in ins)}, {', '.join(f'output {p}' for p in pouts)});",
             f"  wire [15:0] mask = 16'h{mask:04x};  // decoded from CRAM",
             f"  wire [3:0] ix = {{{idx[3]}, {idx[2]}, {idx[1]}, {idx[0]}}};  // wiring from .vo (oracle-supplied)",
             "  wire f = mask[ix];"]
    for o, inv in outs:
        port = next((p for p in pouts if vo.canon(p) == vo.canon(o)), None)
        if port is None:
            return name, f"no verdict: obuf output {o} reaches no top-level port", None
        lines.append(f"  assign {port} = {'~' if inv else ''}f;  // obuf inversion from .vo")
    lines.append("endmodule")
    (work / "decoded.v").write_text("\n".join(lines) + "\n")
    rnd = random.Random(1)
    vecs = list(range(1 << len(ins))) + [rnd.getrandbits(len(ins)) for _ in range(steps)]
    tb = ["`timescale 1ps/1ps", "module tb;", f"  reg [{len(ins) - 1}:0] v;",
          *[f"  wire q_{p}, d_{p};" for p in pouts],
          f"  top u_q ({', '.join([f'.{p}(v[{i}])' for i, p in enumerate(ins)] + [f'.{p}(q_{p})' for p in pouts])});",
          f"  top_decoded u_d ({', '.join([f'.{p}(v[{i}])' for i, p in enumerate(ins)] + [f'.{p}(d_{p})' for p in pouts])});",
          "  integer ok = 0, bad = 0, xs = 0;", "  initial begin"]
    for v in vecs:
        tb.append(f"    v = {len(ins)}'d{v}; #1000;")
        for p in pouts:
            tb.append(f"    if (^{{q_{p}, d_{p}}} === 1'bx) xs = xs + 1; else if (q_{p} === d_{p}) ok = ok + 1; else bad = bad + 1;")
    tb += ['    $display("RESULT ok=%0d bad=%0d x=%0d", ok, bad, xs);', "    $finish;", "  end", "endmodule"]
    (work / "tb.v").write_text("\n".join(tb) + "\n")
    cells = {a["type"] for a in vo.atoms.values()} - {"dffeas"}
    (work / "models.v").write_text(vendor_models(cells))
    cmd = ["iverilog", "-g2012", "-o", str(work / "sim.vvp"), str(work / "tb.v"),
           str(fa.top_module_only(d / "postfit.vo")), str(work / "models.v"),
           str(SIMLIB / "altera_primitives.v"), str(work / "decoded.v")]
    import heavy_guard
    r = heavy_guard.guarded(cmd, "iverilog", overall_s=IVERILOG_LIMIT_S)  # #122
    if r.timed_out:
        return name, f"exceeded {IVERILOG_LIMIT_S}s", None
    if r.returncode:
        return name, f"iverilog compile failed: {r.stderr.strip()[-300:]}", None
    r = heavy_guard.guarded(["vvp", str(work / "sim.vvp")], "vvp", overall_s=IVERILOG_LIMIT_S)
    if r.timed_out:
        return name, f"exceeded {IVERILOG_LIMIT_S}s", None
    res = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")]
    if not res:
        return name, f"no RESULT: {r.stdout[-200:]}", None
    ok, bad, xs = (int(x) for x in re.findall(r"=(\d+)", res[-1]))
    return name, f"decoded mask {mask:04x}", (ok, bad, xs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="lut_*")
    ap.add_argument("--json", default=str(REPO / "tmp" / "cycloneiv" / "fuzz_analysis.json"))
    ap.add_argument("--steps", type=int, default=64)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--model", action="store_true",
                    help="bit positions from the LE address model (cycloneiv_le_model.py), any site")
    ap.add_argument("--negative-control", action="store_true",
                    help="flip decoded mask bit 0: every design must then report bad > 0")
    a = ap.parse_args()
    res = json.loads(Path(a.json).read_text())
    if a.model:
        import cycloneiv_le_model as lm
        model = lm.Model(res)

        class ModelMaps(dict):
            def __missing__(self, site):
                raise KeyError(site)

            def __contains__(self, site):
                return bool(re.match(r"LCCOMB_X\d+_Y\d+_N\d+$", site)) and model.lut_bits(site) is not None

            def __getitem__(self, site):
                return model.lut_bits(site)
        bitmaps = ModelMaps()
    else:
        bitmaps = {r["site"]: r["bitmap"] for r in res["lut"] if r.get("bitmap")}
    names = sorted(p.name for p in CORPUS.iterdir() if fnmatch.fnmatch(p.name, a.match))
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda n: check(n, bitmaps, a.steps, 1 if a.negative_control else 0), names))
    tot = [0, 0, 0]
    designs_bad = verdicts = 0
    for name, msg, r in rows:
        if r:
            verdicts += 1
            designs_bad += r[1] > 0
            tot = [x + y for x, y in zip(tot, r)]
        log(f"{name}: {msg} " + (f"ok={r[0]} bad={r[1]} x={r[2]}" if r else ""))
    log(f"SUMMARY{' MODEL' if a.model else ''}{' NEGATIVE-CONTROL' if a.negative_control else ''} match={a.match} {verdicts}/{len(rows)} designs with a verdict; designs with bad outputs {designs_bad}; "
        f"output compares ok={tot[0]} bad={tot[1]} x={tot[2]}")
    if a.negative_control:
        return 0 if verdicts == len(rows) and designs_bad == verdicts else 1
    return 0 if verdicts == len(rows) and designs_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
