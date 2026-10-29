#!/usr/bin/env python3.15t
"""LUT INIT specimens for the clean O1 oracle (#165).  Ground truth = which rbf cells change when a LUT INIT bit is set.

Method: S LUTs (one per LAB, fixed LCCOMB sites, chained so synthesis keeps them) on EP4CGX150.  Design t (0..13) flips INIT
bit k of site i (vs the base INIT BASE_MASK) iff bit t of code(i,k) = ((i+1) << 4) | k.  A cell that flips between
base and design t carries bit t of its code, so 14 builds identify (site, INIT bit) of every flipped cell exactly.
BASE_MASK and every flipped variant depend on all four LUT inputs (constant or 1-input masks change the routing: 424 stray cells measured).
Black box: quartus_map / fit / asm / cpf only.  No pluribus geometry is read; legal LAB sites = fitter probe (cycloneiv_device_grid.py).

  python3.15t scripts/cycloneiv_clean_lut_specimens.py build [--sites 1023] [--jobs 2]
  python3.15t scripts/cycloneiv_clean_lut_specimens.py real gx150_rb_000 ...   # corpus designs rebuilt with the sof kept
  python3.15t scripts/cycloneiv_clean_lut_specimens.py analyse        # -> tmp/cycloneiv_clean/lut_specimens/observed.npz
Log: tmp/logs/cycloneiv_clean_lut_specimens.log
"""
import argparse
import json
import logging
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import plane as P  # noqa: E402
from lifters.cycloneiv_clean import sofio as S  # noqa: E402

OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "lut_specimens")
LABS = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_labs.json")   # source: fitter probe (error 171016), 9,360 legal LAB sites
DEVICE = "EP4CGX150DF31C7"
BASE_MASK = 0x0001           # depends on all 4 inputs; so does BASE_MASK ^ {AAAA, CCCC, F0F0, FF00, FFFF} (checked offline)
BITS = 14                    # code bits: 10 site-id bits + 4 INIT-bit-index bits
SEED = 165
# First-run backstops (no measurement for a chained 1,023-LUT design yet): map 180 s, fit 600 s, asm 60 s, cpf 10 s.
# On expiry cycloneiv_fuzz.run logs the step, elapsed time and loadavg and the design fails.  Cut to 3x measured after the first run.
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10}
log = logging.getLogger("lut_specimens")


def pick_sites(n):
    """n LABs (X, Y) and LE index (N = 2 * le), every LAB column and row covered (hard error otherwise)."""
    labs = [tuple(x) for x in json.load(open(LABS))["labs"]]
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(labs), n, replace=False)
    sites = [(labs[i][0], labs[i][1], int(rng.integers(0, 16))) for i in sorted(idx)]
    full = len({s[0] for s in sites}) == len({x for x, _ in labs}) and len({s[1] for s in sites}) == len({y for _, y in labs})
    if n >= 500 and not full:
        raise SystemExit("site sample misses a LAB column or row; change SEED")
    return sites


def verilog(sites, masks):
    L = ["module top(input a, b, c, d, output y);"]
    L += [f"  wire w{i};" for i in range(1, len(sites) + 1)]
    for i, m in enumerate(masks):
        src = "a" if i == 0 else f"w{i}"
        dst = "y" if i == len(sites) - 1 else f"w{i + 1}"
        L.append(f"  cycloneive_lcell_comb #(.lut_mask(16'h{m:04X}), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) "
                 f"u{i} (.dataa({src}), .datab(b), .datac(c), .datad(d), .combout({dst}));")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def masks_for(t, n):
    """Design t: INIT of site i = BASE_MASK with bit k flipped iff bit t of code(i, k); t = None -> the base design."""
    if t is None:
        return [BASE_MASK] * n
    return [BASE_MASK ^ sum((((((i + 1) << 4) | k) >> t) & 1) << k for k in range(16)) for i in range(n)]


def build_one(name, sites, masks):
    d = os.path.join(OUT, name)
    qsf = [f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * le} -to u{i}" for i, (x, y, le) in enumerate(sites)]
    return build_project(d, name, verilog(sites, masks), qsf)


def build_project(d, name, top_v, extra_qsf, device=DEVICE, vo=False, rcf=False):
    """map / fit / asm / cpf of one project dir; keeps build.sof and build.rbf (uncompressed) in d."""
    import cycloneiv_fuzz as fz
    import toolchain
    if os.path.exists(os.path.join(d, "build.rbf")):
        return name, None
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "src"))
    q = os.path.join(d, "quartus")
    os.makedirs(q)
    open(os.path.join(d, "src", "top.v"), "w").write(top_v)
    qsf = [f'set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {device}",
           "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
           'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
           "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"] + list(extra_qsf)
    if vo:
        qsf += ['set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
                'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation']
    open(os.path.join(q, "build.qsf"), "w").write("\n".join(qsf) + "\n")
    open(os.path.join(q, "build.qpf"), "w").write('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    if vo:       # post-fit netlist kept as ground truth (same command as the corpus builds, cycloneiv_fuzz.py)
        steps.insert(3, ("quartus_eda", [f"{qb}/quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]))
    from pathlib import Path
    for step, cmd in steps:
        if not fz.run(step, cmd, Path(q), Path(d) / "logs", LIMITS):
            return name, step
    if rcf:       # full routing of every net (same export as the corpus builds)
        if not fz.rcf_export(Path(q), Path(d), Path(qb), LIMITS):
            return name, "quartus_cdb"
    shutil.copyfile(os.path.join(q, "build.rbf"), os.path.join(d, "build.rbf"))
    shutil.copyfile(os.path.join(q, "build.sof"), os.path.join(d, "build.sof"))
    if vo:
        import glob
        shutil.copyfile(next(glob.iglob(os.path.join(q, "simulation", "**", "*.vo"), recursive=True)), os.path.join(d, "postfit.vo"))
    shutil.rmtree(q)
    return name, None


def cmd_build(a):
    sites = pick_sites(a.sites)
    json.dump(sites, open(os.path.join(OUT, "sites.json"), "w"))
    jobs = [("base", None)] + [(f"t{t:02d}", t) for t in range(BITS)]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda j: build_one(j[0], sites, masks_for(j[1], len(sites))), jobs))
    bad = [(n, s) for n, s in res if s]
    for n, s in res:
        log.info("%s: %s", n, f"FAILED at {s}" if s else "ok")
    if bad:
        raise SystemExit(f"failed builds: {bad}")


REAL = os.path.join(REPO, "tmp", "cycloneiv_clean", "real_sofs")


def cmd_real(a):
    """Rebuild corpus designs (src + qsf from design.toml) keeping the quartus_asm sof next to the quartus_cpf rbf."""
    import tomllib
    corpus = os.path.join(REPO, "corpus", "cycloneiv")

    def one(name):
        spec = tomllib.load(open(os.path.join(corpus, name, "design.toml"), "rb"))
        top_v = open(os.path.join(corpus, name, "src", "top.v")).read()
        qsf = [x for x in spec.get("qsf", [])]
        return build_project(os.path.join(REAL, name), name, top_v, qsf, spec.get("device", DEVICE))
    os.makedirs(REAL, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, a.names))
    for n, s in res:
        log.info("%s: %s", n, f"FAILED at {s}" if s else "ok")
    if any(s for _, s in res):
        raise SystemExit("failed real builds")


def cmd_analyse(a):
    sites = json.load(open(os.path.join(OUT, "sites.json")))
    n = len(sites)
    base = S.rbf_cram(os.path.join(OUT, "base", "build.rbf"))
    code = np.zeros(base.shape, np.int32)
    flips = []
    for t in range(BITS):
        cur = S.rbf_cram(os.path.join(OUT, f"t{t:02d}", "build.rbf"))
        diff = cur != base
        code |= diff.astype(np.int32) << t
        want = sum(1 for i in range(n) for k in range(16) if (((i + 1) << 4 | k) >> t) & 1)
        flips.append((t, int(diff.sum()), want))
    for t, got, want in flips:
        log.info("design t%02d: flipped cells %d, expected %d%s", t, got, want, "" if got == want else "  MISMATCH")
    r, jm, k = np.nonzero(code)
    c = code[r, jm, k]
    site, bit = (c >> 4) - 1, c & 15
    ok = (site >= 0) & (site < n)
    log.info("cells with a nonzero code %d; decode to a valid site %d", len(c), int(ok.sum()))
    key = site[ok] * 16 + bit[ok]
    if len(np.unique(key)) != len(key):
        log.error("duplicate (site, bit) codes: %d of %d", len(key) - len(np.unique(key)), len(key))
    have = np.zeros((n, 16), bool)
    have[site[ok], bit[ok]] = True
    log.info("(site, bit) pairs observed %d of %d", int(have.sum()), n * 16)
    np.savez(os.path.join(OUT, "observed.npz"), site=site[ok], bit=bit[ok], r=r[ok], j=jm[ok] + 1, k=k[ok],
             sx=np.array([s[0] for s in sites]), sy=np.array([s[1] for s in sites]), le=np.array([s[2] for s in sites]),
             stray_cells=np.array(len(c) - int(ok.sum())))


def main():
    global OUT
    if os.environ.get("LUT_SPEC_OUT"):
        OUT = os.environ["LUT_SPEC_OUT"]      # smoke tests only
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_lut_specimens.log"), mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--sites", type=int, default=1023)
    b.add_argument("--jobs", type=int, default=2)
    b.set_defaults(f=cmd_build)
    r = sp.add_parser("real")
    r.add_argument("names", nargs="+")
    r.add_argument("--jobs", type=int, default=2)
    r.set_defaults(f=cmd_real)
    sp.add_parser("analyse").set_defaults(f=cmd_analyse)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
