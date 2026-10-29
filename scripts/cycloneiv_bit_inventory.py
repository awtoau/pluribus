#!/usr/bin/env python3.15t
"""Cyclone IV GX150 configuration-bit inventory (read-only, issue #141).

Every cell of the (frame, v) plane (+ header frame) is attributed to ONE class, first match wins:
  1 cell config (LUT INIT / LE bits)   2 asm.ddb routing   3 raw-diff specimen bits
  4 hard-IP / IO regions by geometry   5 stream overhead   6 unclassified
Reports die-wide TOTAL bits per class (A) and the SET bits of an image per class (B).
No new decoder: geometry, Dec.active and the specimen tables are used as they are.

  python3.15t scripts/cycloneiv_bit_inventory.py --image <path.bin|.rbf> --record
--record appends one line to docs/coverage-history.jsonl (the coverage-over-time ledger); use it every run.
Log tmp/logs/cycloneiv_bit_inventory.log; JSON tmp/cycloneiv_bit_inventory.json.  Peak RSS ~4 GB.
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
log = logging.getLogger("bit_inventory")

NV = 6368            # bits per frame (796 bytes * 8)
LANE_V = 6344        # v < LANE_V: lane-model data; 6344..6351 lane tail; 6352.. CRC bytes (CRAM frames)
DROP_F = 30000
PRE_POST_BITS = (32 * 8, 59 * 8)      # preamble 0xFF x32, postamble 0xFF x59 (docs/cycloneiv-bitstream.md)
# LOCAL_LINE specimen grids: evidence rows in the family DB (PLURIBUS_SQLITE_PATH), keyed by the file they
# were migrated from (scripts/claims_register.py); the JSON path is only a fallback for a DB without them.
FORCED = ["evidence/cycloneiv/cycloneiv_forced_lab.json", "evidence/cycloneiv/cycloneiv_forced_lab_58x30.json",
          "evidence/cycloneiv/cycloneiv_forced_lab_37x60.json", "evidence/cycloneiv/cycloneiv_forced_lab_100x75.json"]
FORCED_LAB = [(10, 10), (58, 30), (37, 60), (100, 75)]


def forced_table(rel_path):
    """{pair: {src, snk, hop, on: [flat...]}} from evidence rows; JSON fallback."""
    import evidence_io_bridge as eb
    tab = eb.specimen_table("cycloneiv", "EP4CGX150", rel_path)
    if tab is not None:
        return tab
    p = REPO / rel_path
    if not p.exists():
        raise SystemExit(f"no evidence rows for {rel_path} in the DB and no JSON fallback at {p}")
    log.warning("%s: read from JSON (no evidence rows in the DB; run scripts/claims_register.py --family cycloneiv)", rel_path)
    return json.loads(p.read_text())
COL_LO = 19          # column band starts at FX-19 (specimen bits reach FX-19); pitch 35 so FX+16/17 spill into the next band
ROW_PHASE0 = 68      # tile row band of y = [VY-68, VY+1] (70 v): approximate binning, see doc

CLASSES = [  # id, name, evidence tier
    ("1a", "LUT INIT (16 bits x 16 LE x 9360 LAB)", "verified"),
    ("1b", "LE-used bit", "partial"),
    ("1c", "LAB clock-polarity bit", "partial"),
    ("1d-a", "LAB blkrba named REG/OUT/IN bits (vendor name only; table in vendor-analysis, not committed)", "decoded"),
    ("1d-b", "LAB blkrba named control bits RSCNT/RSMUX/ROWCLK (positions miss the measured control cells)", "refuted"),
    ("2a", "asm routing: cells of groups FIRED in this image", "decoded"),
    ("2b", "asm routing: cells in groups/blocks not fired in this image", "table-only"),
    ("3", "LOCAL_LINE specimen bits at the 4 specimen LABs (measured)", "specimen"),
    ("3t", "LOCAL_LINE specimen bits translated to all other LABs", "predicted"),
    ("4a", "periphery frames 1..36 (IO ring, clocks, PLL, misc)", "unknown"),
    ("4f", "M9K data cells at sites with an exact offset check", "verified"),
    ("4g", "M9K data cells at the other sites (per-site offset rule)", "sampled"),
    ("4h", "M9K control cells (knob pairs) at the sites where measured", "measured"),
    ("4i", "M9K control cells at the other sites (offset rule)", "predicted"),
    ("4b", "M9K columns (8): cells outside the data tables and the control cells found", "unknown"),
    ("4c", "multiplier columns (4)", "unknown"),
    ("4d", "IOL / IOR columns (+ 4 frames before col 0)", "unknown"),
    ("4e", "IO row tiles (y=0, y=91) of LAB columns", "unknown"),
    ("5a", "header frame 0", "mixed"),
    ("5b", "CRAM frame CRC-16 bytes", "verified"),
    ("5c", "lane-tail byte (v 6344..6351, CRAM frames)", "unknown"),
    ("6", "unclassified (LAB-column cells no decoder claims)", "unknown"),
]
CID = {c[0]: i + 1 for i, c in enumerate(CLASSES)}


def need_ram(gb=6):
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            avail = int(ln.split()[1]) / 1e6
            if avail < gb:
                raise SystemExit(f"MemAvailable {avail:.1f} GB < {gb} GB: not running")
            log.info("MemAvailable %.1f GB", avail)
            return


class Inv:
    def __init__(self, geom, nfr, nper):
        self.g, self.nfr, self.nper = geom, nfr, nper
        self.cls = np.zeros(nfr * NV, np.uint8)
        self.claimed_by = collections.Counter()   # (class, previous class) overlaps
        xs = sorted(geom.FX)
        self.xs = xs
        self.lo = np.array([geom.FX[x] - COL_LO for x in xs], np.int64)
        fr = np.arange(nfr)
        i = np.searchsorted(self.lo, fr, "right") - 1
        self.colx = np.where((fr >= nper), np.where(i >= 0, np.array(xs)[np.clip(i, 0, None)], 0), -1)
        self.colx[0] = -1
        v = np.arange(NV)
        y = np.floor_divide(v - (geom.vy0 - ROW_PHASE0), geom.vpitch)
        self.rowy = np.where(v < LANE_V, y, -1)

    def claim(self, flat, name, mask_ok=None):
        flat = np.unique(np.asarray(flat, np.int64))
        flat = flat[(flat >= 0) & (flat < len(self.cls))]
        prev = self.cls[flat]
        free = prev == 0
        for p, n in zip(*np.unique(prev[~free], return_counts=True)):
            self.claimed_by[(name, CLASSES[p - 1][0])] += int(n)
        self.cls[flat[free]] = CID[name]
        return int(free.sum()), len(flat)


def lab_tiles(g):
    xs = [x for x in sorted(g.kind) if g.kind[x] == "LAB"]
    return np.array([(x, y) for x in xs for y in range(1, g.ymax)], np.int64)


def le_grid(g, tiles):
    """per (tile, LE): anchor frame, anchor v, sign -> flat arrays."""
    fx = np.array([g.FX[int(x)] for x in tiles[:, 0]], np.int64)
    vy = g.vy0 + g.vpitch * tiles[:, 1]
    dn = np.array([g.DN[i] for i in range(16)], np.int64)
    sg = np.array([-1 if i % 2 else 1 for i in range(16)], np.int64)
    f = np.repeat(fx[:, None], 16, 1)
    v = vy[:, None] + dn[None, :]
    return f, v, np.broadcast_to(sg, f.shape)


def m9k_data_cells(g, nfr):
    """(verified flat cells, rule-predicted flat cells) of the M9K data tables over all 720 sites.
    Base tables x9 (9216 cells) and x1 (8192) at X23Y40 + per-site (FX[x]-FX[23], vpitch*(y-40)); a site is
    verified only where a recorded random-init check matched exactly AND its offset equals the rule."""
    import sqlite3
    import dbtools
    conn = sqlite3.connect(f"file:{dbtools.family_db('cycloneiv')}?mode=ro", uri=True)
    get = lambda n: json.loads(conn.execute("select result from evidence where family='cycloneiv' and kind='derived-table' "
                                            "and name=?", (n,)).fetchone()[0])["file"]
    try:
        c9 = np.array(list(get("cycloneiv_m9k_hmap9.json")["cells"].values()), np.int64)
        c1 = np.array(list(get("cycloneiv_m9k_hmap1.json")["cells"].values()), np.int64)
        offs = get("m9k-site-offsets")
    finally:
        conn.close()
    f1 = set(map(tuple, c1.tolist()))
    is1 = np.array([tuple(c) in f1 for c in c9.tolist()])
    cols = sorted(x for x in g.kind if g.kind[x] == "M9K")
    ver, evi = [], []
    ok_sites = {}
    for x in cols:
        for y in range(1, g.ymax):
            rule = (g.FX[x] - g.FX[23], g.vpitch * (y - 40))
            k = f"x{x}_y{y}"
            ok9 = bool((x, y) == (23, 40) or (offs.get(k + "_x9", {}).get("exact") and offs[k + "_x9"]["offset"] == list(rule)))
            ok1 = bool(ok9 or (offs.get(k + "_x1", {}).get("exact") and offs[k + "_x1"]["offset"] == list(rule)))
            flat = (c9[:, 0] + rule[0]) * NV + c9[:, 1] + rule[1]
            inb = (c9[:, 0] + rule[0] >= 0) & (c9[:, 0] + rule[0] < nfr) & (c9[:, 1] + rule[1] >= 0) & (c9[:, 1] + rule[1] < LANE_V)
            assert inb.all(), (x, y)
            v_mask = np.full(len(c9), ok9) | (ok1 & is1)
            ver.append(flat[v_mask])
            evi.append(flat[~v_mask])
            ok_sites[(x, y)] = "x9" if ok9 else "x1" if ok1 else None
    return np.concatenate(ver), np.concatenate(evi), ok_sites


def m9k_control_cells(g, nfr):
    """(measured flat, predicted flat): control cells found by knob pairs, in measured sites vs the offset rule elsewhere."""
    import sqlite3
    import dbtools
    conn = sqlite3.connect(f"file:{dbtools.family_db('cycloneiv')}?mode=ro", uri=True)
    row = conn.execute("select result from evidence where family='cycloneiv' and name='m9k-control-cells'").fetchone()
    conn.close()
    if not row:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    d = json.loads(row[0])["file"]
    cells = np.array(sorted({tuple(c) for v in d["cells_by_knob"].values() for c in v["set"] + v["clear"]}), np.int64)
    meas = {tuple(x) for x in d["sites"]}
    m, p = [], []
    for x in sorted(c for c in g.kind if g.kind[c] == "M9K"):
        for y in range(1, g.ymax):
            flat = (cells[:, 0] + g.FX[x] - g.FX[23]) * NV + cells[:, 1] + g.vpitch * (y - 40)
            (m if (x, y) in meas else p).append(flat)
    return np.concatenate(m), np.concatenate(p)


LEDGER = REPO / "docs/coverage-history.jsonl"
# Fallback tier label per class when the DB holds no claims (verified = vendor-oracle compare, evidence =
# mapping without per-bit oracle, unknown = nothing; 5a split by the header counts). With claims present the
# ledger line carries the tier x status breakdown read from the claims table (provenance-schema.md).
# Tier names follow docs/provenance-and-feedback.md (statuses) and docs/recovery-process.md "Patterns and certainty":
#   verified   = oracle-verified (vendor post-fit compare) | measured = raw diff / observed at that cell or site
#   sampled    = verified-by-sampling (pattern, >= N scopes incl. extremes, 0 refutations) | predicted = pattern-predicted, below that bar
#   statistical = last-resort fit, unverified, its own tier | glossary: docs/provenance-and-feedback.md "Glossary"
#   decoded    = decoded-untested (vendor decode, nothing tested at the cell) | suspect / refuted = a pattern with a miss / contradicted
# Patterns are revocable: a miss moves the class to suspect/refuted and its bits out of the verified tiers.
# unknown_projected = the part of "unknown" whose cells are set in NONE of the held bitstreams (triage frequency, not a
# claim, never pattern-predicted). It is a SUB-LINE of unknown, never subtracted from it. Bitmap: scripts/cycloneiv_ever_set.py.
TIER_KEYS = ("verified", "measured", "sampled", "predicted", "statistical", "decoded", "suspect", "refuted", "unknown")
UNKNOWN_CLASSES = ("4a", "4b", "4c", "4d", "4e", "5c", "6")
LEDGER_TIER = {}     # class id -> tier; filled from the DB at run start by load_verdicts() (provenance/tiering.py), never hand-set
VERDICT = {}


def load_verdicts():
    """Tier per class from the claims/evidence in the family DB: the rule in provenance/tiering.py."""
    import db
    from provenance import tiering
    with db.engine().connect() as conn:
        for cid in [c[0] for c in CLASSES] + ["5d"]:
            v = tiering.class_verdict(conn, "cycloneiv", "EP4CGX150", cid)
            VERDICT[cid] = v
            LEDGER_TIER[cid] = v["tier"]
    for cid, v in VERDICT.items():
        if cid in BASIS:
            BASIS[cid] = (BASIS[cid][0], f"n={v['n']} misses={v['misses']}; {v['rule']}")
        else:
            BASIS[cid] = ("", f"n={v['n']} misses={v['misses']}; {v['rule']}")
        log.info("tier %-3s %-9s n=%-5d misses=%-3d %s", cid, v["tier"], v["n"], v["misses"], v["rule"])


BASIS = {  # class -> (what backs it, sample n / misses)
    "1a": ("LUT mask vs Quartus post-fit netlist (oracle compare)", "301 designs, 5,354,496 bits / 0 miss"),
    "1b": ("pattern-predicted rule from LE positions; 14 misses on one design, claim status suspect", "1,018 LEs / 14 miss"),
    "1c": ("statistical fit over clock lines + one isolated cell (pattern-predicted, open)", "5,442 lines / fit Jaccard 0.85"),
    "1d-b": ("blkrba control names: positions miss every measured clock-polarity/ena/aclr/sclr cell; refuting rows, claim refuted", "8 measured cells / 0 on a name"),
    "1d-a": ("vendor ddb decode (blkrba) of per-LAB bit positions; position law validated on the 256 LUT cells (4,749,088 mask bits vs .vo, 0 wrong); non-LUT names carry no exact evidence", "300 designs, LUT cells only"),
    "2a": ("decoded from vendor asm tables, (frame,v) map inferred; decoded-untested, not rule-verified", "held-out routing score 17.1% of pips"),
    "2b": ("same vendor tables, groups not fired in the image; decoded-untested, not rule-verified", "none"),
    "3": ("raw-diff specimens at the 4 specimen LABs", "4 LABs x 240 pairs"),
    "3t": ("pattern ll-translate-v1 fitted at X10Y10, confirmed at 3 other LABs; below the 2-D bar (N=5); edge rows/columns outside scope", "4 LABs x 240 pairs / 0 miss"),
    "4f": ("measured: M9K data cells at sites with an exact random-init diff", "112 sites / 0 miss"),
    "4g": ("verified-by-sampling: M9K per-site (frame,v) offset rule, all 8 columns, rows 1..90 incl. extremes", "120 site checks / 0 miss"),
    "4h": ("M9K knob pairs (output register, address clear, read-during-write, output clock enable) replicated at 3 sites", "3 sites / 0 miss, null rename = 0 bits"),
    "4i": ("same cells at the other sites by the per-site offset rule; 3 positions, below the 2-D bar (N=5)", "3 sites / 0 miss"),
    "5a": ("header: sync+CRC verified; format fields and constants observed; option bits unknown", "-"),
    "5b": ("CRC-16 recomputed over the frame data", "6,154 frames"),
    "5d": ("constant 0xFF fill per the documented format", "-"),
}


def git(*args):
    import subprocess
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()


def record(out, hdr_ver, hdr_known, hdr_unk, commit=None, ts=None, source="live", dirty=None):
    """Append ONE line to the coverage ledger (single O_APPEND write; existing lines never rewritten)."""
    import datetime
    import os
    classes = []
    for r in out["rows"]:
        t = r["total"]
        if r["id"] == "5a":
            tv = {"verified": hdr_ver, "measured": hdr_known, "unknown": hdr_unk}
        else:
            tier = LEDGER_TIER.get(r["id"], "unknown")
            tv = {tier: t}
            if r["id"] in UNKNOWN_CLASSES:
                tv = {"unknown": t}
        assert sum(tv.values()) == t, r["id"]
        classes.append(dict(id=r["id"], name=r["name"], tier_label=r["tier"], die_bits=t,
                            **{k: tv.get(k, 0) for k in TIER_KEYS}, unknown_projected=r.get("projected", 0), image_set=r["set"],
                            basis=BASIS.get(r["id"], ("", ""))[0], sample=BASIS.get(r["id"], ("", ""))[1]))
    commit = commit or git("rev-parse", "HEAD")
    if dirty is None:
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    line = dict(ts=ts or datetime.datetime.now().astimezone().isoformat(timespec="seconds"), commit=commit,
                subject=git("log", "-1", "--format=%s", commit), dirty=dirty, source=source, die_bits=out["die_bits"], **{k: out[k] for k in TIER_KEYS}, unknown_projected=out["unknown_projected"], image_set_total=out["set_total"], ever_set_n=out.get("ever_set_n"), classes=classes)
    assert sum(line[k] for k in TIER_KEYS) == line["die_bits"]
    # tier x status per class from the claims table (real rows only); also mirrored into coverage_ledger
    import evidence_io_bridge as eb
    tiers_by_class = eb.ledger_tiers("cycloneiv", "EP4CGX150", commit, [(r["id"], r["total"]) for r in out["rows"]])
    if tiers_by_class:
        line["claims"] = tiers_by_class
        for c in classes:
            c["tiers"] = tiers_by_class.get(c["id"], {})
    data = (json.dumps(line, separators=(",", ":")) + "\n").encode()
    fd = os.open(LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    log.info("recorded ledger line for %s -> %s", line["commit"][:9], LEDGER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--record", action="store_true", help="append one line to docs/coverage-history.jsonl (run after every checklist item)")
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/cycloneiv_bit_inventory.log", "w")])
    need_ram(6)
    import heavy_guard
    with heavy_guard.lease(heavy_guard.JOB_GB["cyc4_bit_inventory"], "cyc4_bit_inventory", log):
        run(a)


def run(a):
    load_verdicts()
    import cycloneiv_corpus as cc
    import cycloneiv_decompress as cd
    import cycloneiv_geom as cg
    import cycloneiv_asm_decode as ad
    from cycloneiv_le_locate import DK

    g = cg.load(cg.die_of("EP4CGX150"))
    raw = Path(a.image).read_bytes()
    plane = cc.cram_plane(raw, g)
    nfr, nv = plane.shape
    assert nv == NV, nv
    info = {}
    u = cd.decompress(raw, info)
    F, nper, ncram = info["frame"], info["periphery_frames"], info["cram_frames"]
    assert F * 8 == NV and nper + ncram == nfr
    keys = plane.keys
    log.info("plane %d x %d, %d set bits (frames 1.. excl. CRC bytes); periphery %d, CRAM %d", nfr, NV, len(keys), nper, ncram)
    inv = Inv(g, nfr, nper)
    tiles = lab_tiles(g)
    log.info("LAB tiles %d (%d columns)", len(tiles), len(set(tiles[:, 0].tolist())))

    # ---- 1: cell config -------------------------------------------------------------------
    f0, v0, sg = le_grid(g, tiles)
    lut = np.concatenate([((f0 + df) * NV + v0 + sg * dv).ravel() for df, dv in DK])
    n1a = inv.claim(lut, "1a")
    leu = ((f0 - 8) * NV + v0 - sg).ravel()
    inv.claim(leu, "1b")
    fx = np.array([g.FX[int(x)] for x in tiles[:, 0]], np.int64)
    vy = g.vy0 + g.vpitch * tiles[:, 1]
    inv.claim((fx - 6) * NV + vy - 30, "1c")
    import cycloneiv_blkrba_lab as bl
    nl = bl.nonlut_positions()
    if nl["a"]:   # (dx, dy) per tile: frame = FX + dy - 15, v = vy0 + 70*Y + 2 - dx  (TEST 1, #165)
        for k in ("a", "b"):
            inv.claim(np.concatenate([(fx + dy - 15) * NV + vy + 2 - dx for dx, dy in nl[k]]), f"1d-{k}")
    else:
        log.warning("1d: blkrba table not found (vendor-analysis, local only); class 1d stays empty")
    log.info("class 1 claimed: %s", {k: int((inv.cls == CID[k]).sum()) for k in ("1a", "1b", "1c", "1d-a", "1d-b")})

    # ---- 2: asm routing -------------------------------------------------------------------
    dec = ad.Dec()
    gids, _grec, blk = dec.active(plane)
    log.info("fired groups %d, distinct blocks %d of %d", len(gids), len(set(blk.tolist())), dec.nblocks)
    fg = np.zeros(len(dec.gsize), bool)
    fg[gids] = True
    pf, pvv, gid = np.asarray(dec.pf), np.asarray(dec.pv), np.asarray(dec.gid)
    pos = np.load(REPO / "tmp/ddb/stingray4_asm_pos.npy", mmap_mode="r")
    assert len(pos) == len(pf), (len(pos), len(pf))
    asm_any = np.zeros(nfr * NV, bool)
    fired = np.zeros(nfr * NV, bool)
    dropped_pos, n_drop, CH = [], 0, 5_000_000
    for s in range(0, len(pf), CH):
        p, q = pf[s:s + CH].astype(np.int64), pvv[s:s + CH].astype(np.int64)
        ok = (p >= 0) & (p < nfr) & (q >= 0) & (q < NV)
        flat = p[ok] * NV + q[ok]
        asm_any[flat] = True
        fired[flat[fg[gid[s:s + CH]][ok]]] = True
        n_drop += int((~ok).sum())
        if (~ok).any():
            dropped_pos.append(np.unique(np.asarray(pos[s:s + CH])[~ok]))
    dpos = np.unique(np.concatenate(dropped_pos)) if dropped_pos else np.zeros(0, np.int64)
    log.info("asm entries %d; placed cells %d (fired %d); entries with no plane cell %d (%d distinct asm bits)",
             len(pf), int(asm_any.sum()), int(fired.sum()), n_drop, len(dpos))
    inv.claim(np.flatnonzero(fired), "2a")
    inv.claim(np.flatnonzero(asm_any & ~fired), "2b")
    afx = json.load(open(REPO / "tmp/ddb/stingray4_dec_afx.json"))
    moved = sorted(int(x) for x, b in afx.items() if int(x) in g.FX and b != g.FX[int(x)])
    del pf, pvv, gid

    # ---- 3: specimens ---------------------------------------------------------------------
    pats, rel = [], None
    for fp, (lx, ly) in zip(FORCED, FORCED_LAB):
        tab = forced_table(fp)
        cur = {}
        for r in tab.values():
            cur[(r["src"], r["snk"], r["hop"][4])] = tuple(sorted((b // NV - g.FX[lx], b % NV - (g.vy0 + g.vpitch * ly)) for b in r["on"]))
        if rel is None:
            rel = cur
        agree = sum(1 for k in cur if rel.get(k) == cur[k])
        log.info("specimen LAB X%dY%d: %d pairs, %d identical to X10Y10 after FX/VY translation", lx, ly, len(cur), agree)
        pats.append((lx, ly, len(cur), agree))
    universe = sorted({b for p in rel.values() for b in p})
    role = collections.Counter()
    bit_pairs = collections.defaultdict(set)
    for k, p in rel.items():
        for b in p:
            bit_pairs[b].add(k)
    n_by_src = collections.Counter(k[0] for k in rel)
    for b, ps in bit_pairs.items():
        srcs, snks = {k[0] for k in ps}, {k[1] for k in ps}
        if len(ps) == 1:
            role["pair-unique (sink input-mux select for one src)"] += 1
        elif len(srcs) == 1 and len(ps) == n_by_src[next(iter(srcs))]:
            role["source-LE bit (set for every pair of one src)"] += 1
        elif len(snks) == 1:
            role["sink-shared (one sink, several src)"] += 1
        else:
            role["other"] += 1
    fxa = np.array([g.FX[int(x)] for x in tiles[:, 0]], np.int64)
    vya = g.vy0 + g.vpitch * tiles[:, 1]
    spec_cells = np.concatenate([((fxa + df) * NV + vya + dv) for df, dv in universe])
    prior = inv.cls[np.unique(spec_cells)]
    spec_overlap = {CLASSES[c - 1][0]: int(n) for c, n in zip(*np.unique(prior[prior > 0], return_counts=True))}
    meas = np.concatenate([((g.FX[lx] + np.array([d[0] for d in universe])) * NV + g.vy0 + g.vpitch * ly + np.array([d[1] for d in universe]))
                           for lx, ly in FORCED_LAB])
    n3 = inv.claim(meas, "3")
    n3t = inv.claim(spec_cells, "3t")
    spec_new = (n3[0] + n3t[0], n3[1] + n3t[1])
    # full-pattern matches of the image: all 4 bits of a (src, snk) specimen set at a LAB
    match_pairs, per_snk = 0, collections.Counter()
    labs_hit = np.zeros(len(tiles), bool)
    snk_hits = collections.defaultdict(lambda: np.zeros(len(tiles), np.int16))
    for (src, snk, port), p in rel.items():
        m = np.ones(len(tiles), bool)
        for df, dv in p:
            m &= plane.has(fxa + df, vya + dv)
        match_pairs += int(m.sum())
        labs_hit |= m
        snk_hits[snk] += m
    for snk, arr in snk_hits.items():
        for n in arr.tolist():
            per_snk[min(n, 3)] += 1
    log.info("specimen: %d cells/LAB, new cells %d of %d, overlap with earlier classes %s",
             len(universe), spec_new[0], spec_new[1], spec_overlap)

    # ---- 4/5: region + overhead -----------------------------------------------------------
    cls2 = inv.cls.reshape(nfr, NV)
    kind = np.array(["x"] * nfr, object)
    for f in range(nfr):
        kind[f] = "per" if 1 <= f < nper else "hdr" if f == 0 else (g.kind[int(inv.colx[f])] if inv.colx[f] in g.kind else "IOL")
    ff = lambda k: np.flatnonzero(kind == k)
    cell = lambda fr, vlo, vhi: (fr[:, None] * NV + np.arange(vlo, vhi)[None, :]).ravel()
    inv.claim(cell(ff("per"), 0, NV), "4a")
    m9k_ver, m9k_evi, m9k_sites = m9k_data_cells(g, nfr)
    inv.claim(m9k_ver, "4f")
    inv.claim(m9k_evi, "4g")
    c_meas, c_pred = m9k_control_cells(g, nfr)
    inv.claim(c_meas, "4h")
    inv.claim(c_pred, "4i")
    log.info("M9K data: %d sites, verified-check x9 %d / x1-only %d / rule-only %d; cells verified %d, predicted %d", len(m9k_sites),
             sum(v == "x9" for v in m9k_sites.values()), sum(v == "x1" for v in m9k_sites.values()),
             sum(v is None for v in m9k_sites.values()), len(m9k_ver), len(m9k_evi))
    inv.claim(cell(ff("M9K"), 0, LANE_V), "4b")
    inv.claim(cell(ff("MUL"), 0, LANE_V), "4c")
    inv.claim(np.concatenate([cell(ff("IOL"), 0, LANE_V), cell(ff("IOR"), 0, LANE_V)]), "4d")
    labf = ff("LAB")
    vio = np.flatnonzero((inv.rowy == 0) | (inv.rowy == g.ymax))
    inv.claim((labf[:, None] * NV + vio[None, :]).ravel(), "4e")
    inv.claim(cell(np.array([0]), 0, NV), "5a")
    crc = np.concatenate([cell(np.arange(nper, nfr), 6352, NV)])
    inv.claim(crc, "5b")
    inv.claim(cell(np.arange(nper, nfr), LANE_V, 6352), "5c")
    free = inv.cls == 0
    inv.cls[free] = CID["6"]
    log.info("claim overlaps (later class lost to earlier): %s", dict(inv.claimed_by))

    # ---- counts ---------------------------------------------------------------------------
    setmask = np.zeros(nfr * NV, bool)
    setmask[keys] = True
    spec_set_all = int(setmask[np.unique(spec_cells)].sum())
    hdr = u[cd.PREAMBLE:cd.PREAMBLE + F]
    hdr_set = int(np.unpackbits(np.frombuffer(hdr, np.uint8)).sum())
    crc_set = 0
    for fr in range(nper, nfr):
        b = cd.PREAMBLE + fr * F + F - 2
        crc_set += int(np.unpackbits(np.frombuffer(u[b:b + 2], np.uint8)).sum())
    tot = np.bincount(inv.cls, minlength=len(CLASSES) + 1)
    sets = np.bincount(inv.cls[setmask], minlength=len(CLASSES) + 1)
    sets[CID["5a"]] += hdr_set        # header and CRC bytes are not in the plane keys
    sets[CID["5b"]] += crc_set
    die_bits = int(tot.sum()) + sum(PRE_POST_BITS)
    set_all = int(sets.sum()) + sum(PRE_POST_BITS)
    rows = []
    for (cid, name, tier), t, s in zip(CLASSES, tot[1:], sets[1:]):
        rows.append(dict(id=cid, name=name, tier=tier, total=int(t), set=int(s), pct_die=100 * t / die_bits))
    rows.append(dict(id="5d", name="preamble + postamble (0xFF fill, outside frames)", tier="constant",
                     total=sum(PRE_POST_BITS), set=sum(PRE_POST_BITS), pct_die=100 * sum(PRE_POST_BITS) / die_bits))
    T = {r["id"]: r["total"] for r in rows}
    S = {r["id"]: r["set"] for r in rows}
    # header frame split (docs/cycloneiv-bitstream.md "Format"): sync+CRC16 verified 24; flag/length/family/variant 41
    # known; lanes 5-7 constant 1 (120) and 0xFF fill (6024) constant; option bits 159 unknown
    HDR_VER, HDR_KNOWN, HDR_UNK = 24, 41 + 120 + 6024, 159
    ever = REPO / "databases" / "cycloneiv" / "ever_set.npy"
    ever_n = None
    if ever.exists():
        import sqlite3
        import dbtools
        seen = np.unpackbits(np.load(ever, mmap_mode="r"))[:nfr * NV].astype(bool)
        c_ = sqlite3.connect(f"file:{dbtools.family_db('cycloneiv')}?mode=ro", uri=True)
        meta = json.loads(c_.execute("select result from evidence where name='ever-set-bitmap'").fetchone()[0])["file"]
        c_.close()
        ever_n = meta["n_designs"]
        for r_ in rows:
            if r_["id"] in UNKNOWN_CLASSES:
                r_["projected"] = int(((inv.cls == CID[r_["id"]]) & ~seen).sum())
                BASIS[r_["id"]] = (f"geometry-located region, no decoder; {r_['projected']:,} of its bits are set in none of {ever_n:,} held designs "
                                   f"(triage sub-line, projected unused, not a claim); the rest are set in some design (live unknown)",
                                   f"{ever_n:,} designs / 0 set the projected bits")
    tot_t = dict.fromkeys(TIER_KEYS, 0)
    tot_proj = 0
    for r_ in rows:
        if r_["id"] == "5a":
            tot_t["verified"] += HDR_VER; tot_t["measured"] += HDR_KNOWN; tot_t["unknown"] += HDR_UNK
        elif r_["id"] in UNKNOWN_CLASSES:
            tot_proj += r_.get("projected", 0); tot_t["unknown"] += r_["total"]
        else:
            tot_t[LEDGER_TIER.get(r_["id"], "unknown")] += r_["total"]
    assert sum(tot_t.values()) == die_bits, tot_t
    # ---- unknown regions: one partition of classes 4a-4e, 5c, 6 ------------------------------
    unknown_ids = [CID[k] for k in ("4a", "4b", "4c", "4d", "4e", "5c", "6")]
    u2 = np.isin(inv.cls, unknown_ids).reshape(nfr, NV)
    s2 = setmask.reshape(nfr, NV)
    lab_core = np.flatnonzero((inv.rowy >= 1) & (inv.rowy <= g.ymax - 1))
    phase = (np.arange(NV) - (g.vy0 - ROW_PHASE0)) % g.vpitch
    stripe = lab_core[(phase[lab_core] >= 31) & (phase[lab_core] <= 39)]
    rest = lab_core[~((phase[lab_core] >= 31) & (phase[lab_core] <= 39))]
    off = np.full(nfr, -1, np.int64)
    for f in labf:
        off[f] = f - inv.lo[inv.xs.index(int(inv.colx[f]))]
    regions = []

    def add(name, fr, vv, ntile):
        sub = u2[np.ix_(fr, vv)]
        regions.append(dict(name=name, unknown=int(sub.sum()), set=int((sub & s2[np.ix_(fr, vv)]).sum()), tiles=ntile))

    allv = np.arange(NV)
    add("M9K columns (8), all rows", ff("M9K"), np.arange(LANE_V), 8)
    add("multiplier columns (4), all rows", ff("MUL"), np.arange(LANE_V), 4)
    add("periphery frames 1..36", ff("per"), allv, 0)
    add("IOL/IOR columns (+4 pre-col frames)", np.concatenate([ff("IOL"), ff("IOR")]), np.arange(LANE_V), 2)
    add("LAB columns, IO rows y0/y91", labf, vio, 104 * 2)
    add("lane-tail byte (CRAM frames)", np.arange(nper, nfr), np.arange(LANE_V, 6352), 0)
    add("LAB core, control stripe (v phase 31..39, all frames)", labf, stripe, len(tiles))
    for lo_o, hi_o in ((0, 11), (12, 19), (20, 22), (23, 32), (33, 34)):
        fr = labf[(off[labf] >= lo_o) & (off[labf] <= hi_o)]
        add(f"LAB core, frames FX{lo_o - COL_LO:+d}..FX{hi_o - COL_LO:+d} (excl. stripe)", fr, rest, len(tiles))
    regions.sort(key=lambda r: -r["unknown"])
    for r in regions:
        r["per_tile"] = r["unknown"] / r["tiles"] if r["tiles"] else None
    six = (inv.cls == CID["6"]).reshape(nfr, NV)
    ph_tot = np.bincount(phase[lab_core], weights=six[labf][:, lab_core].sum(0), minlength=g.vpitch)
    six_off = {o: int(six[labf[off[labf] == o]][:, lab_core].sum()) for o in range(35)}
    n_ll = len(tiles)
    moved_lab = [x for x in moved if g.kind[x] == "LAB"]
    out = dict(image_set_bits_in_plane=int(len(keys)), header_set=hdr_set, crc_set=crc_set, die_bits=die_bits,
               set_total=set_all, rows=rows, ever_set_n=ever_n, unknown_projected=tot_proj, **tot_t,
               fired_groups=int(len(gids)), blocks=int(dec.nblocks),
               asm_entries=int(len(dec.gsize)), asm_entries_dropped=n_drop, asm_bits_unplaced=int(len(dpos)),
               afx_moved_columns=moved, afx_moved_lab_columns=moved_lab, specimen_labs=pats, specimen_cells_per_lab=len(universe),
               specimen_roles=dict(role), specimen_overlap_prior=spec_overlap, specimen_universe_set_in_image=spec_set_all,
               specimen_full_matches=match_pairs, specimen_labs_with_match=int(labs_hit.sum()),
               specimen_sink_match_hist=[per_snk[i] for i in range(4)],
               claim_overlaps={f"{a}<-{b}": n for (a, b), n in inv.claimed_by.items()},
               regions=regions, class6_by_offset=six_off, class6_by_vphase=[int(x) for x in ph_tot])
    json.dump(out, open(REPO / "tmp/cycloneiv_bit_inventory.json", "w"), indent=1)
    if a.record:
        record(out, HDR_VER, HDR_KNOWN, HDR_UNK)

    P = log.info
    P("%-4s %12s  %-13s  %-95s  %s", "class", "bits", "tier", "what backs it", "sample n / misses")
    for r in rows:
        if r["id"] in BASIS:
            P("%-4s %12d  %-13s  %-95s  %s", r["id"], r["total"], LEDGER_TIER.get(r["id"], "mixed"), *BASIS[r["id"]])
    P("=== (A) die-wide TOTAL bits per class; die = %d bits (handbook 39,425,016) ===", die_bits)
    P("%-4s %-58s %-9s %12s %12s %7s", "id", "class", "tier", "total", "image set", "% die")
    for r in rows:
        P("%-4s %-58s %-9s %12d %12d %6.2f%%", r["id"], r["name"], LEDGER_TIER.get(r["id"], r["tier"]), r["total"], r["set"], r["pct_die"])
    P("2c   asm bits with no plane cell (outside partition): %d distinct, %d entries", len(dpos), n_drop)
    P("HEADLINE exact (verified + measured) %d = %.2f%%; rule verified by sampling (not exact per cell, not in headline) %d = %.2f%%",
      tot_t["verified"] + tot_t["measured"], 100 * (tot_t["verified"] + tot_t["measured"]) / die_bits,
      tot_t["sampled"], 100 * tot_t["sampled"] / die_bits)
    P("tiers: " + "; ".join(f"{k} {v} = {100 * v / die_bits:.2f}%" for k, v in tot_t.items())
      + f"; of which unknown projected unused (never set in {ever_n} designs) {tot_proj} = {100 * tot_proj / die_bits:.2f}%")
    P("(B) image set bits: plane %d + header %d + crc %d + pre/post %d = %d", len(keys), hdr_set, crc_set, sum(PRE_POST_BITS), set_all)
    sv, se = S["1a"] + S["5b"], S["4f"] + S["1b"] + S["1c"] + S["1d-a"] + S["1d-b"] + S["2a"] + S["2b"] + S["3"] + S["3t"] + S["4g"]   # se: evidence + predicted
    P("    verified-class set bits %d (%.1f%%), other-evidence %d (%.1f%%), unknown-class %d (%.1f%%; header/pre/post excluded)",
      sv, 100 * sv / set_all, se, 100 * se / set_all, set_all - sv - se - S["5a"] - T["5d"],
      100 * (set_all - sv - se - S["5a"] - T["5d"]) / set_all)
    P("    in 1a %d, 1b %d, 1c %d, 1d-a %d, 1d-b %d, 2a %d, 2b %d, 3 %d, 3t %d, 4* %d, 5b %d, 5c %d, 6 %d", S["1a"], S["1b"], S["1c"], S["1d-a"], S["1d-b"], S["2a"], S["2b"], S["3"], S["3t"],
      sum(S[k] for k in ("4a", "4b", "4c", "4d", "4e")), S["5b"], S["5c"], S["6"])
    P("asm: groups fired %d, blocks %d; entries with no plane cell %d; columns whose asm base != FX: %d (LAB %d: %s)",
      len(gids), dec.nblocks, n_drop, len(moved), len(moved_lab), moved_lab)
    P("specimen: %d cells per LAB, roles %s; new cells %s; overlap with earlier classes %s; image set bits in the translated universe %d",
      len(universe), dict(role), spec_new, spec_overlap, spec_set_all)
    P("specimen full 4-bit matches in image: %d (LAB, pair) over %d LABs with >=1; (LAB, sink) match-count hist 0/1/2/3+ srcs %s",
      match_pairs, int(labs_hit.sum()), [per_snk[i] for i in range(4)])
    P("unknown regions (one partition):")
    for r in regions:
        P("  %-58s unknown %10d  set %9d  per-tile %s", r["name"], r["unknown"], r["set"], None if r["per_tile"] is None else round(r["per_tile"], 1))
    P("class 6 per LAB-core frame offset (offset 0 = FX-19): %s", six_off)
    P("class 6 per v phase (0..69): %s", [int(x) for x in ph_tot])


if __name__ == "__main__":
    main()
