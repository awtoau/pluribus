#!/usr/bin/env python3
"""Diamond round-trip completeness check (pluribus issue #38, P7) -- PROTOTYPE.

Proves (or disproves) that the recovered netlist reconstitutes the design:

    original.bit --native-decode--> orig.config --lift--> recovered.v
        --Diamond(PAR+Bitgen)--> bitstream' --native-decode--> new.config
        --compare--> orig.config

Two comparison levels are reported per sample:

  * FUNCTIONAL  -- does recovered.v synthesise in Diamond at all, and does the
                   re-decoded netlist carry the same *placement-invariant*
                   fingerprint (multiset of LUT INITs, FF configs, used-cell
                   counts) as the original decode?  Diamond P&R is
                   nondeterministic so tile coordinates and raw bits will
                   differ -- this is the achievable bar.
  * STRUCTURAL  -- raw residual: symmetric-difference of the two configs'
                   (tile,arc/enum/word) line sets, plus .bit byte Hamming.
                   Reported as a quality metric; do not expect 0 without full
                   LOCATE/routing constraints.

Diamond is single-seat and slow: builds run ONE AT A TIME, sequentially, with
NO sleeps/timeouts.  Fresh project per sample via `prj_project new` (no
dependency on the repo's aw21.sty strategy file).

Env (all have sane defaults for this machine):
  TRELLIS_DBROOT  prjtrellis database root (tiledata + device tilegrid + iodb)
  TRELLIS_BUILD   pytrellis build dir (free-threaded for python3.14t/3.15t)
  TRELLIS_DEVICE  device name (default LCMXO2-1200)
  DIAMONDC        diamondc binary
  LM_LICENSE_FILE Diamond licence file

Logs to tmp/diamond_roundtrip.log.  Leaves all intermediates under
tmp/rtcheck/<sample>/ for inspection.
"""
import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

# ---- configuration ---------------------------------------------------------
# Trellis build/DB from the env (repo-relative default); explicit env wins.
DBROOT = os.environ.get("TRELLIS_DBROOT", "tmp/prjtrellis/database")
BUILD = os.environ.get("TRELLIS_BUILD", "tmp/prjtrellis/libtrellis/build")
DEVICE = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")
DEVICE_FULL = os.environ.get("TRELLIS_DEVICE_FULL", "LCMXO2-1200HC-5TG100C")

# Diamond install from the env (DIAMONDDIR / LM_LICENSE_FILE); no baked paths.
_DIAMOND = os.environ.get("DIAMONDDIR", "")
DIAMONDC = os.environ.get("DIAMONDC",
                          os.path.join(_DIAMOND, "bin", "lin64", "diamondc"))
LICENSE = os.environ.get("LM_LICENSE_FILE",
                         os.path.join(_DIAMOND, "license", "license.dat"))

TARGETS = REPO / "diamond-fuzz" / "targets"
WORKROOT = REPO / "tmp" / "rtcheck"
LOG = REPO / "tmp" / "diamond_roundtrip.log"

_logfh = None


def log(msg=""):
    print(msg, flush=True)
    if _logfh:
        _logfh.write(str(msg) + "\n")
        _logfh.flush()


# ---- pipeline steps --------------------------------------------------------
def native_decode(bit_path, out_config):
    """original/derived .bit -> prjtrellis .config (pure-Python native decode)."""
    import native_config
    text, pb, bram = native_config.config_from_file(
        str(bit_path), device=DEVICE, db_root=DBROOT)
    Path(out_config).write_text(text)
    return text, pb


def lift(config_path, out_v):
    """orig.config -> recovered.v structural netlist; returns the Design."""
    from lifters import machxo2_lift as mx
    _lift, _pc, design = mx.lift_netlist(
        str(config_path), str(out_v), DEVICE,
        target=Path(config_path).stem, source="native-decode",
        build_dir=BUILD, dbroot=DBROOT)
    return design


def run_diamond(work_dir, verilog_path, lpf_text):
    """Fresh Diamond project in work_dir; PAR + Bitgen. Returns (ok, bit, detail).

    `prj_project new` auto-creates the project's own <name>.lpf constraint file,
    so we do NOT `prj_src add` a second one (that collides).  Instead the Tcl
    rewrites that project lpf in-place with `lpf_text` before PAR.  The
    recovered netlist has no ports, so lpf_text is normally empty."""
    work_dir = Path(work_dir)
    tcl = work_dir / "run.tcl"
    # escape braces/backslashes are not expected in our simple LPF text
    lpf_block = ""
    if lpf_text and lpf_text.strip():
        lpf_block = (
            'set _fp [open "fuzz.lpf" w]\n'
            'puts $_fp {%s}\n'
            'close $_fp\n' % lpf_text.strip())
    tcl.write_text(
        'prj_project new -name "fuzz" -impl "impl1" -dev %s -synthesis "lse"\n'
        'prj_src add "%s"\n'
        '%s'
        'prj_run PAR -impl impl1 -forceOne\n'
        'prj_run Export -impl impl1 -task Bitgen\n'
        'prj_project save\n'
        'prj_project close\n'
        % (DEVICE_FULL, Path(verilog_path).name, lpf_block))

    impl = work_dir / "impl1"
    diamond_log = work_dir / "diamond.log"
    env = dict(os.environ)
    env["LM_LICENSE_FILE"] = LICENSE
    with open(diamond_log, "w") as fh:
        proc = subprocess.run(
            [DIAMONDC, "run.tcl"], stdout=fh, stderr=subprocess.STDOUT,
            cwd=str(work_dir), env=env)
    bit = impl / "fuzz_impl1.bit"
    detail = diamond_diagnosis(diamond_log)
    if proc.returncode != 0 and not bit.exists():
        return False, None, detail or f"diamondc exit {proc.returncode}"
    if not bit.exists():
        return False, None, detail or "no .bit produced"
    return True, bit, detail or "ok"


def diamond_diagnosis(log_path):
    """Extract the most telling error/warning lines from Diamond logs.

    Scans the top-level diamondc log plus the synthesis/map/par logs in impl1/,
    since front-end rejections land in synthesis.log, not the driver log."""
    work = Path(log_path).parent
    texts = []
    for p in [Path(log_path),
              work / "impl1" / "synthesis.log",
              work / "impl1" / "fuzz_impl1.log",
              work / "impl1" / "fuzz.log"]:
        if p.exists():
            texts.append(p.read_text(errors="replace"))
    if not texts:
        return "log missing"
    txt = "\n".join(texts)
    hits = []
    for ln in txt.splitlines():
        low = ln.lower()
        if any(k in low for k in (
                "error", "cannot", "undefined", "unknown module", "empty",
                "no logic", "no ports", "no valid", "failed", "black box",
                "blackbox", "not found")):
            ln = ln.strip()
            if ln and ln not in hits:
                hits.append(ln)
    return " | ".join(hits[:8])


# ---- comparison ------------------------------------------------------------
def _parse(cfg_path):
    import compare_config
    return compare_config.parse_config(str(cfg_path))


def fingerprint(cfg_path):
    """Placement-invariant functional fingerprint of a decoded config.

    Collapses tile coordinates: what matters is the multiset of LUT INITs,
    the multiset of FF/slice enum settings, and gross used-cell counts."""
    tiles = _parse(cfg_path)
    lut_inits = Counter()
    enum_vals = Counter()
    arc_shapes = Counter()
    n_tiles = 0
    for name, td in tiles.items():
        if name == "_meta":
            continue
        n_tiles += 1
        for k, v in td.words.items():
            if "INIT" in k:
                lut_inits[v] += 1
        for k, v in td.enums.items():
            # keep the enum name suffix (bel-relative), drop tile coords
            enum_vals[(td.tile_type, k, v)] += 1
        for (sink, src) in td.arcs:
            arc_shapes[(td.tile_type, sink.split(".")[-1],
                        src.split(".")[-1])] += 1
    return {
        "n_tiles": n_tiles,
        "lut_inits": lut_inits,
        "enum_vals": enum_vals,
        "arc_shapes": arc_shapes,
    }


def compare_configs(orig_cfg, new_cfg):
    """Return dict of functional + structural comparison metrics."""
    fa, fb = fingerprint(orig_cfg), fingerprint(new_cfg)

    def cdiff(a, b):
        # symmetric difference of two Counters (multiset)
        keys = set(a) | set(b)
        return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)

    lut_match = fa["lut_inits"] == fb["lut_inits"]
    enum_res = cdiff(fa["enum_vals"], fb["enum_vals"])
    arc_res = cdiff(fa["arc_shapes"], fb["arc_shapes"])

    # structural: raw line-set symmetric difference over the whole config text
    def lineset(p):
        s = set()
        for ln in Path(p).read_text().splitlines():
            ln = ln.strip()
            if ln.startswith((".tile", "arc:", "enum:", "word:", "unknown:")):
                s.add(ln)
        return s
    la, lb = lineset(orig_cfg), lineset(new_cfg)
    struct_residual = len(la ^ lb)

    return {
        "orig_luts": dict(fa["lut_inits"]),
        "new_luts": dict(fb["lut_inits"]),
        "lut_init_match": lut_match,
        "enum_residual": enum_res,
        "arc_residual": arc_res,
        "struct_residual": struct_residual,
        "orig_tiles": fa["n_tiles"],
        "new_tiles": fb["n_tiles"],
    }


# ---- per-sample driver -----------------------------------------------------
def orig_lpf(target_dir):
    p = Path(target_dir) / "fuzz.lpf"
    return p.read_text() if p.exists() else ""


def process(sample, do_diamond=True, control=False):
    """Run the full round-trip for one sample target path (relative to TARGETS).

    control=True: instead of the lifter's recovered.v, re-build the ORIGINAL
    fuzz.v through the same harness.  This is the reference upper bound -- it
    proves the build+decode+compare machinery and measures the residual that
    P&R nondeterminism alone produces for a genuinely-passing round-trip."""
    tdir = TARGETS / sample
    name = sample.replace("/", "__") + ("__control" if control else "")
    bit = tdir / "impl1" / "fuzz_impl1.bit"
    log("\n" + "=" * 72)
    log(f"[sample] {sample}" + ("  (CONTROL: original fuzz.v)" if control else ""))
    if not bit.exists():
        log(f"  SKIP: original bit missing at {bit}")
        return {"sample": sample, "status": "no-orig-bit"}

    work = WORKROOT / name
    work.mkdir(parents=True, exist_ok=True)
    orig_cfg = work / "orig.config"
    recovered_v = work / "fuzz.v"           # Diamond wants a plain name

    # 1. native-decode original
    _, pb = native_decode(bit, orig_cfg)
    log(f"  decoded original: frames={pb.frames_read}/{pb.num_frames} "
        f"crc={pb.crc_verified}")

    if control:
        # reference path: rebuild the original RTL, compare decode(rebuild) to
        # decode(original).  Same design => functional fingerprint must match;
        # residual is pure P&R nondeterminism.
        recovered_v.write_text((tdir / "fuzz.v").read_text())
        ok, newbit, detail = run_diamond(work, recovered_v, orig_lpf(tdir))
        rec = {"sample": sample + " [control]", "status": "control"}
        rec["diamond_ok"] = ok
        rec["diamond_detail"] = detail
        if not ok:
            log(f"  CONTROL DIAMOND FAILED: {detail}")
            rec["status"] = "control-fail"
            return rec
        new_cfg = work / "new.config"
        native_decode(newbit, new_cfg)
        cmp = compare_configs(orig_cfg, new_cfg)
        rec.update(cmp)
        log(f"  FUNCTIONAL: lut_init_match={cmp['lut_init_match']} "
            f"orig_luts={cmp['orig_luts']} new_luts={cmp['new_luts']}")
        log(f"  STRUCTURAL: enum_residual={cmp['enum_residual']} "
            f"arc_residual={cmp['arc_residual']} "
            f"config_line_residual={cmp['struct_residual']} "
            f"(tiles {cmp['orig_tiles']}->{cmp['new_tiles']})")
        return rec

    # 2. lift -> recovered.v
    design = lift(orig_cfg, recovered_v)
    n_lut, n_ff = len(design.luts), len(design.ffs)
    n_ports = _count_ports(recovered_v)
    log(f"  lifted: LUT4={n_lut} FF={n_ff} nets={len(design.all_nets)} "
        f"arcs={design.n_arcs}  top-level ports emitted={n_ports}")

    rec = {"sample": sample, "luts": n_lut, "ffs": n_ff,
           "ports": n_ports, "status": "lifted"}

    if not do_diamond:
        rec["status"] = "lifted-only"
        return rec

    # 3. Diamond round-trip on the emitted Verilog.
    # The recovered netlist has no top-level ports, so no LPF is meaningful
    # (nothing to LOCATE); pass an empty constraint set.
    ok, newbit, detail = run_diamond(work, recovered_v, "")
    rec["diamond_ok"] = ok
    rec["diamond_detail"] = detail
    if not ok:
        log(f"  DIAMOND FAILED: {detail}")
        rec["status"] = "resynth-fail"
        return rec
    log(f"  Diamond produced bitstream': {newbit}")

    # 4. decode bitstream' and compare
    new_cfg = work / "new.config"
    native_decode(newbit, new_cfg)
    cmp = compare_configs(orig_cfg, new_cfg)
    rec.update(cmp)
    rec["status"] = "roundtrip"
    log(f"  FUNCTIONAL: lut_init_match={cmp['lut_init_match']} "
        f"orig_luts={cmp['orig_luts']} new_luts={cmp['new_luts']}")
    log(f"  STRUCTURAL: enum_residual={cmp['enum_residual']} "
        f"arc_residual={cmp['arc_residual']} "
        f"config_line_residual={cmp['struct_residual']} "
        f"(tiles {cmp['orig_tiles']}->{cmp['new_tiles']})")
    return rec


def _count_ports(vpath):
    """Count top-level module ports in the emitted Verilog (input/output/inout
    inside the non-blackbox module header)."""
    txt = Path(vpath).read_text()
    # crude: count input/output declarations in the recovered_netlist module
    import re
    m = re.search(r"module\s+recovered_netlist\s*(\([^)]*\))?\s*;", txt)
    if not m:
        return 0
    hdr = m.group(1) or ""
    return len(re.findall(r"\b(input|output|inout)\b", hdr))


DEFAULT_SAMPLES = [
    "clkdivc_div2",
    "clkdivc_div4",
    "ccu2d_logic",
    "ccu2d_add",
    "highlevel/syn_keep_wire",
    "highlevel/inferred_shreg_8",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", nargs="*", default=None,
                    help="target paths relative to diamond-fuzz/targets/")
    ap.add_argument("--no-diamond", action="store_true",
                    help="lift only; skip the (slow) Diamond builds")
    ap.add_argument("--control", action="store_true",
                    help="reference upper bound: rebuild ORIGINAL fuzz.v "
                         "through the harness and measure P&R residual")
    args = ap.parse_args()

    global _logfh
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _logfh = open(LOG, "w")

    samples = args.samples or DEFAULT_SAMPLES
    log(f"[cfg] DBROOT={DBROOT}")
    log(f"[cfg] BUILD={BUILD}")
    log(f"[cfg] DEVICE={DEVICE} ({DEVICE_FULL})")
    log(f"[cfg] diamond={'skip' if args.no_diamond else DIAMONDC}")
    log(f"[cfg] samples={samples}")

    results = []
    for s in samples:
        try:
            results.append(process(s, do_diamond=not args.no_diamond,
                                   control=args.control))
        except Exception as e:
            import traceback
            log(f"  EXCEPTION on {s}: {e}")
            log(traceback.format_exc())
            results.append({"sample": s, "status": "exception", "err": str(e)})

    log("\n" + "#" * 72)
    log("# SUMMARY")
    log("#" * 72)
    for r in results:
        log(f"  {r['sample']:32s} {r.get('status'):14s} "
            f"LUT={r.get('luts','-')} FF={r.get('ffs','-')} "
            f"ports={r.get('ports','-')} "
            f"resynth={r.get('diamond_ok','-')} "
            f"struct_resid={r.get('struct_residual','-')}")
        if r.get("diamond_detail") and not r.get("diamond_ok"):
            log(f"      why: {r['diamond_detail'][:160]}")
    return results


if __name__ == "__main__":
    main()
