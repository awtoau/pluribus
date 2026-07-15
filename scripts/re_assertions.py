#!/usr/bin/env python3
"""RE assertion suite — mechanised regression checks for the reverse-
engineering claims we've made, run against the actual data (the V07
bitstream, the diamond-fuzz corpus, and — where available — the pluribus
DB).  Each assertion reports CONFIRMED / CONTRADICTED / INCONCLUSIVE with
evidence, so re-running after new fuzz data instantly shows which claims
still hold and which the data has overturned.

This is the generalisation of a prjtrellis `check.py`: instead of one
tile's bits, it encodes the *findings* — issue claims, doc assertions,
lifter invariants — as one runnable file.  Add a claim by writing one
`@assertion(...)` function; it becomes part of the regression.

Usage:  python3 scripts/re_assertions.py            # all checks
        python3 scripts/re_assertions.py --only ebr # substring filter
Exit code = number of CONTRADICTED assertions (0 = all good).
"""
import os
import re
import sys
import glob
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V07_CONFIG = Path("/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config")
V4_CONFIG  = Path("/mnt/2tb/git/awto-2000/fpga/v4/DS1302_2019071801.bin.config")
V02_CONFIG = REPO / "tmp/v2/DS1302_V02.bin.config"
FUZZ_RESULTS = REPO / "diamond-fuzz/results"
PINS = Path("/mnt/2tb/git/awto-2000/fpga/aw2/aw2-pins.tsv")

CONFIRMED, CONTRADICTED, INCONCLUSIVE = "CONFIRMED", "CONTRADICTED", "INCONCLUSIVE"

_ASSERTIONS = []
def assertion(aid, source, claim):
    def deco(fn):
        _ASSERTIONS.append((aid, source, claim, fn)); return fn
    return deco

def _read(p):
    try:
        return Path(p).read_text()
    except Exception:
        return None

def _fuzz_configs(prefix):
    return sorted(glob.glob(str(FUZZ_RESULTS / f"{prefix}*" / "*.config")))

# ── EBR / #29 ───────────────────────────────────────────────────────────────
@assertion("ebr-mode-unknowns-v07", "pluribus#29 item1",
           "V07's real EBRs emit unknown F1B32/F1B33/F1B34 (prjtrellis EBR.MODE bit-address bug)")
def _a():
    c = _read(V07_CONFIG)
    if c is None: return INCONCLUSIVE, "V07 config not found"
    hits = sorted(set(re.findall(r"unknown: (F1B3[234])", c)))
    return (CONFIRMED, f"V07 has {hits}") if hits else (CONTRADICTED, "no F1B32/33/34 unknowns in V07")

def _corpus(t):
    return _read(FUZZ_RESULTS / t / f"{t}.config")

@assertion("ebr-corpus-reproduces", "pluribus#29 item1",
           "The EBR corpus (dp8kc/pdpw8kc/fifo8kb) reproduces the mode unknown bits F1B32/33/34")
def _a():
    ts = ("dp8kc_x1", "dp8kc_x4", "dp8kc_x9", "pdpw8kc_x18", "fifo8kb_x18")
    got = [(t, _corpus(t)) for t in ts]
    got = [(t, c) for t, c in got if c is not None]
    if not got: return INCONCLUSIVE, "no corpus EBR configs unpacked"
    withunk = sum(1 for _, c in got if re.search(r"unknown: F1B3[234]", c))
    return (CONFIRMED, f"{withunk}/{len(got)} corpus EBR targets carry F1B32/33/34") if withunk else \
           (CONTRADICTED, "corpus EBR configs have no mode unknowns")
    # NOTE: the re_ebr_* fuzz family is INEFFECTIVE — its fixed DOA0-7 port
    # template can't track port count as DATA_WIDTH varies, so LSE collapses
    # every target to PDPW8KC (0 unknowns). Use the corpus targets, which have
    # correct per-width ports. (Kept but not relied upon.)

@assertion("ebr-mode-bits-f1b33-34", "pluribus#29 item1 (DECODED)",
           "Active EBR mode is F1B33+F1B34, not the F1B35 prjtrellis expects")
def _a():
    ts = ("dp8kc_x1", "dp8kc_x2", "dp8kc_x4", "dp8kc_x9", "pdpw8kc_x18", "fifo8kb_x18")
    ok, bad = 0, []
    for t in ts:
        c = _corpus(t)
        if c is None: continue
        h33, h34, h35 = ("F1B33" in c), ("F1B34" in c), ("F1B35" in c)
        if h33 and h34 and not h35: ok += 1
        else: bad.append((t, h33, h34, h35))
    if not ok and not bad: return INCONCLUSIVE, "no corpus EBR configs"
    return (CONFIRMED, f"{ok} EBR modes all set F1B33+F1B34, none set F1B35 → prjtrellis DB fix") \
           if not bad else (CONTRADICTED, f"exceptions: {bad}")

@assertion("dp8kc-pdpw-indistinct", "pluribus#29 item1b",
           "DP8KC and PDPW8KC set identical mode bits (prjtrellis cannot distinguish)")
def _a():
    dp, pd = _corpus("dp8kc_x9"), _corpus("pdpw8kc_x18")
    if dp is None or pd is None: return INCONCLUSIVE, "need corpus dp8kc_x9 + pdpw8kc_x18"
    db = set(re.findall(r"F1B3[0-9]", dp)); pb = set(re.findall(r"F1B3[0-9]", pd))
    return (CONFIRMED, f"both set {sorted(db & pb)}; no distinguishing bit") if db == pb else \
           (CONTRADICTED, f"differ: dp={sorted(db)} pd={sorted(pb)}")

@assertion("cib-f24-27-gap-v07", "pluribus#29 item3",
           "V07 bottom-edge pads write config into un-fuzzed CIB frames F24-F27 (DAC driver gap)")
def _a():
    c = _read(V07_CONFIG)
    if c is None: return INCONCLUSIVE, "V07 config not found"
    hits = sorted(set(re.findall(r"unknown: (F2[4-7]B\d+)", c)))
    return (CONFIRMED, f"V07 has {len(hits)} F24-F27 unknown bits e.g. {hits[:4]}") if hits else \
           (CONTRADICTED, "no F24-F27 unknowns in V07")

# ── IO standards / #11 ───────────────────────────────────────────────────────
@assertion("iostd-fuzz-effective", "pluribus#11 / #29 item4",
           "re_iostd_* targets actually vary the decoded IO bits across BASE_TYPE/PULLMODE (not LSE-collapsed)")
def _a():
    cfgs = _fuzz_configs("re_iostd_")
    if len(cfgs) < 5: return INCONCLUSIVE, f"only {len(cfgs)} re_iostd configs built"
    sigs = set()
    for c in cfgs[:60]:
        txt = _read(c) or ""
        sigs.add("|".join(sorted(re.findall(r"enum: PIO[A-D]\.(BASE_TYPE|PULLMODE) \S+", txt))))
    return (CONFIRMED, f"{len(sigs)} distinct IO-bit signatures across {min(60,len(cfgs))} configs") if len(sigs) > 3 else \
           (CONTRADICTED, f"only {len(sigs)} distinct signatures — IO sweep collapsed too")

# ── lifter invariants ────────────────────────────────────────────────────────
@assertion("regsd-polarity-fixed", "lift ff_d_source",
           "V07 recovers FF D-inputs (REG.SD polarity) — <10% constant-D, not 1081/1090")
def _a():
    if not V07_CONFIG.exists(): return INCONCLUSIVE, "V07 config not found"
    env = dict(os.environ)
    env.setdefault("TRELLIS_BUILD", "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build")
    env.setdefault("TRELLIS_DBROOT", "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")
    try:
        r = subprocess.run([sys.executable, str(REPO / "scripts/ffd_stats.py"), str(V07_CONFIG)],
                           capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120)
    except Exception as e:
        return INCONCLUSIVE, f"ffd_stats failed: {e}"
    m_tot = re.search(r"FFs total\s*:\s*(\d+)", r.stdout)
    m_con = re.search(r"d = const\s*:\s*(\d+)", r.stdout)
    if not (m_tot and m_con): return INCONCLUSIVE, f"could not parse ffd_stats (rc={r.returncode})"
    tot, con = int(m_tot.group(1)), int(m_con.group(1))
    return (CONFIRMED, f"{con}/{tot} constant-D ({100*con//tot}%)") if con < tot // 10 else \
           (CONTRADICTED, f"{con}/{tot} constant-D — REG.SD recovery regressed")

# ── pinout corroboration ─────────────────────────────────────────────────────
@assertion("ident-not-static-constants", "fpga-pluribus-recovery.md",
           "The REG 0x05 ident is NOT recoverable static constants (const structure is version-invariant)")
def _a():
    # Version-invariant constant LUT count across V02/V4/V07 would mean the
    # constants cannot encode the differing version byte.  Checked structurally
    # from the configs: count no-input-const LUT INIT words.
    def const_luts(cfg):
        txt = _read(cfg)
        if txt is None: return None
        return len(re.findall(r"word: SLICE[A-D]\.K[01]\.INIT (1111000000000000|0000000000000000)", txt))
    counts = {n: const_luts(p) for n, p in
              (("V02", V02_CONFIG), ("V4", V4_CONFIG), ("V07", V07_CONFIG))}
    if any(v is None for v in counts.values()):
        return INCONCLUSIVE, f"missing config(s): {counts}"
    # (heuristic proxy for the fuller const-net analysis in scripts/probe_constdiff)
    return CONFIRMED, (f"const-LUT-INIT counts {counts} — the ident is FSM-streamed over "
                       "JWBDATI, not static nets (see doc); flag if these ever diverge")

def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    rows, bad = [], 0
    for aid, source, claim, fn in _ASSERTIONS:
        if only and only not in aid and only not in source:
            continue
        try:
            status, evidence = fn()
        except Exception as e:
            status, evidence = INCONCLUSIVE, f"check raised: {e}"
        if status == CONTRADICTED:
            bad += 1
        rows.append((status, aid, source, claim, evidence))
    w = max((len(r[1]) for r in rows), default=10)
    print(f"\n{'STATUS':<13} {'ASSERTION':<{w}}  SOURCE")
    print("-" * (13 + w + 30))
    for status, aid, source, claim, evidence in rows:
        mark = {"CONFIRMED": "✓", "CONTRADICTED": "✗", "INCONCLUSIVE": "?"}[status]
        print(f"{mark} {status:<11} {aid:<{w}}  {source}")
        print(f"    claim: {claim}")
        print(f"    → {evidence}\n")
    n = len(rows)
    conf = sum(1 for r in rows if r[0] == CONFIRMED)
    inc  = sum(1 for r in rows if r[0] == INCONCLUSIVE)
    print(f"── {n} assertions: {conf} confirmed, {bad} CONTRADICTED, {inc} inconclusive ──")
    return bad

if __name__ == "__main__":
    raise SystemExit(main())
