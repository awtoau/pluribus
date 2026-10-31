#!/usr/bin/env python3.15t
"""#188 stripper PoC: one isolated construct (a function feeding an OR gate, Dan's worked example) built
and lifted, then strip the IO/placement harness Quartus needed to synthesize it, leaving only the bare
LUT/FF cone that implements the pattern -- a reusable template, independent of which pads/placement a
later occurrence of the same pattern happens to use.

Not a matcher: this is the stripper half only (#188 scope).  The template is the cone's leaf set (as
KIND, e.g. "2 pad inputs") plus its exact truth table (patterns.cone_tt) -- pad names, LE coordinates and
instance names are the harness and are dropped.

  python3.15t scripts/cycloneiv_clean_pattern_stripper_poc.py   # log tmp/logs/cycloneiv_clean_pattern_stripper_poc.log
Builds corpus/cycloneiv/strip_or_poc/ (gitignored like every other cycloneiv fuzz specimen).
"""
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("pattern_stripper_poc")
DEVICE = "EP4CGX150DF31C7"
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10}
NAME = "strip_or_poc"

# Dan's worked example: a small function (here, a 3-input AND) feeding an OR gate with a 4th input.
# out = (a & b & c) | d.  Minimal IO, registered output so Quartus doesn't optimize it away to a pad.
TOP = '''module top(input clk, input a, input b, input c, input d, output q);
  reg r;
  always @(posedge clk) r <= (a & b & c) | d;
  assign q = r;
endmodule
'''


def build():
    import cycloneiv_fuzz as fz
    import toolchain
    d = Path(REPO) / "corpus" / "cycloneiv" / NAME
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    (d / "src" / "top.v").write_text(TOP)
    qsf = ['set_location_assignment PIN_A11 -to clk', 'set_global_assignment -name AUTO_GLOBAL_CLOCK OFF',
           'set_global_assignment -name SEED 1']
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "#188 stripper PoC: (a & b & c) | d, function feeding an OR gate"\n'
        f'exercises = ["pattern_stripper_poc"]\nqsf = {json.dumps(qsf)}\ndevice = "{DEVICE}"\n')
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
            raise SystemExit(f"{NAME}: {step} failed")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    json.dump({"status": "ok", "elapsed_s": round(time.time() - t0, 1)}, open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s build ok %.0fs", NAME, time.time() - t0)
    return d / "bitstream.rbf"


def strip(rbf):
    """Harness-strip: find the one FF whose D cone's leaves are all pads (the construct's real inputs,
    no harness logic beyond them), and report its template = (leaf KINDs, exact truth table) -- no pad
    names, no LE coordinates, no instance names.  That is the stripped pattern."""
    from lifters.cycloneiv_clean import emit, patterns as PT
    import heavy_guard
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_clean_strip_poc", log):
        cx = emit.Ctx()
        nl = emit.Builder(cx, str(rbf), None).run()
    D = PT.Design(nl)
    templates = []
    for F in D.clocked:
        leaves = sorted(D.support(F["d"]))
        kinds = [D.kind(s) for s in leaves]
        if not all(k == "pad" for k in kinds):
            continue          # harness/clock-domain FFs, or anything reading another FF -- not this isolated construct
        tt = PT.cone_tt(D, F["d"], leaves)
        templates.append(dict(ff=F["name"], n_leaves=len(leaves), kinds=kinds, tt=tt, tt_hex=f"{tt:x}"))
    return templates


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pattern_stripper_poc.log"))])
    import heavy_guard
    with heavy_guard.lease(6, "cyc4_pattern_stripper_poc", log):
        rbf = build()
        templates = strip(rbf)
    # Expected: exactly one all-pad-leaf FF, 4 leaves, truth table = (a&b&c)|d over some leaf order.
    expect_tt_options = []
    for perm in __import__("itertools").permutations(range(4)):
        def f(bits, perm=perm):
            v = [0, 0, 0, 0]
            for i, p in enumerate(perm):
                v[p] = bits[i]
            a, b, c, dd = v
            return (a & b & c) | dd
        tt = 0
        for i in range(16):
            bits = [(i >> j) & 1 for j in range(4)]
            if f(bits):
                tt |= 1 << i
        expect_tt_options.append(tt)
    result = dict(n_templates=len(templates), templates=templates,
                  matches_expected=any(t["n_leaves"] == 4 and t["tt"] in expect_tt_options for t in templates))
    log.info("RESULT %s", json.dumps(result, indent=1))
    out = Path(REPO) / "tmp" / "logs" / "cycloneiv_clean_pattern_stripper_poc_result.json"
    json.dump(result, open(out, "w"), indent=1)
    print(json.dumps(result, indent=1))
    return 0 if result["matches_expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
