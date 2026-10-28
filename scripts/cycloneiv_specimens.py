#!/usr/bin/env python3.15t
"""Cyclone IV GX specimen fuzzer: EXACT block -> output-wire entries from minimal designs (issue #141).

A specimen = 2 pinned LUTs, one net between them, built with Quartus (bitstream + post-fit RCF).
Its base twin = same placement, l2 fed from the pin instead of l1 (no LUT->LUT net).  diff = fired
(block, source-record) pairs of the specimen minus the base: always-on config groups and the
default-programmed mux columns cancel (identical placement), the one net's path survives.  Every
RCF wire->wire edge is one mux; matching diff pairs to edges (dst tile window + src record
type/tile window + chain consistency, unique or nothing) gives block -> output record EXACTLY -
no voting.  A decoy inside the windows makes an edge AMBIGUOUS (skipped), never wrongly matched;
a path mux the asm decode never fires leaves its edge NO-CANDIDATE (counted, a coverage gap).
Methodology: brute-force enumeration (docs/recovery-process.md); a tile-class entry stands only
while every specimen of the class agrees; one disagreement demotes the class to per-tile entries.

  python3.15t scripts/cycloneiv_specimens.py gen                       # write design dirs
  python3.15t scripts/cycloneiv_specimens.py build [--match 'gx????_c00*'] [--jobs 6]
  python3.15t scripts/cycloneiv_specimens.py solve [--match 'gxspec_*'] [--force]
  python3.15t scripts/cycloneiv_specimens.py verify
  python3.15t scripts/cycloneiv_specimens.py merge                     # -> phys_map.json (+ li_map scrub)
Log tmp/logs/cycloneiv_specimens.log; per-specimen results tmp/cycloneiv/specimens/solved/.
Needs tmp/ddb/stingray4_dec_*.npy + stingray4_rt_nodes.npy (cycloneiv_asm_decode prepare,
cycloneiv_ddb_routing nodes).
"""
import argparse
import collections
import fnmatch
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import heavy_guard  # noqa: E402

log = logging.getLogger("cycloneiv_specimens")
CORPUS = REPO / "corpus" / "cycloneiv"
WORK = REPO / "tmp" / "cycloneiv" / "specimens"
PHYS_MAP = REPO / "lifters" / "data" / "cycloneiv_ep4cgx150_phys_map.json"
LI_MAP = REPO / "lifters" / "data" / "cycloneiv_ep4cgx150_li_map.json"
DEVICE = "EP4CGX150DF31C7"
XM, YM = 8, 4            # tile class = (x % XM) * YM + y % YM (cycloneiv_phys_trace)
XMIRROR = 115            # vendor x = XMIRROR - fitter x (docs/cycloneiv-ddb-format.md)
BATCH_MIN_GB = 20        # free RAM before the batch starts (house rule / #122)
JOB_MIN_GB = 8           # floor per job start: a specimen Quartus chain peaks ~1.3 GB, 20+ run wide
POSITIONS = 3            # tiles per class a generalisation must agree on
# driver -> sink displacements: short R4 / C4 both ways, a diagonal, R24 / C16 reach
DISPS = [(3, 0), (-3, 0), (0, 3), (0, -3), (5, 3), (20, 0), (-20, 0), (0, 14), (0, -14)]
# matching windows, (|dx|max, |dy|max).  DST: mux block tile vs the wire's RCF coordinate.
# The RCF names a wire by its DRIVER end, so the driver mux is within ~1 tile of that coordinate
# (measured: R4 mux at dx -1..0, C4 at dy -1; wider windows let an unrelated same-source block
# match as a unique decoy - the first same-tile conflict, 2026-10-28).  SRC: source record node
# tile vs the source wire's RCF coordinate (home tile vs driver-dependent alias, small offsets).
DST_WIN = {"R4": (1, 1), "C4": (1, 1), "R24": (2, 2), "C16": (2, 2), "LOCAL_INTERCONNECT": (0, 1)}
SRC_WIN = {"R4": (5, 2), "C4": (2, 5), "R24": (25, 2), "C16": (2, 17), "LE_BUFFER": (2, 1)}
# RCF type -> vendor name families that may carry it (cross-type naming quirk, ddb-format doc)
SRC_FAMS = {"R4": ("H4", "V4"), "C4": ("V4", "H4"), "R24": ("H24", "V16"), "C16": ("V16", "H24")}
LEBUF_FAMS = range(16, 48)   # node-table families of the LE_BUFFER records (one per LAB each)
LOOSE_POOL_MAX = 40          # unknown-type srcs (IO ring) match only in a near-clean diff pool


def tclass(x, y):
    return (x % XM) * YM + (y % YM)


# ---------------------------------------------------------------- generate / build
def verilog(with_net):
    l2in = "n" if with_net else "a"
    return ("module top(input a, output y, output y1);\n  wire n;\n"
            '  cycloneiv_lcell_comb #(.lut_mask(16\'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))\n'
            "    l1 (.dataa(a), .combout(n));\n"
            '  cycloneiv_lcell_comb #(.lut_mask(16\'h5555), .sum_lutc_input("datac"), .dont_touch("on"))\n'
            f"    l2 (.dataa({l2in}), .combout(y));\n"
            "  assign y1 = n;\nendmodule\n")


def snap(x, y, labset):
    """Nearest legal LAB to (x, y), or None."""
    for r in range(3):
        ring = sorted((abs(dx) + abs(dy), dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1))
        for _c, dx, dy in ring:
            if (x + dx, y + dy) in labset:
                return (x + dx, y + dy)
    return None


def labs_grid():
    labs = sorted(tuple(t) for t in json.loads(
        (REPO / "lifters" / "data" / "cycloneiv_ep4cgx150_labs.json").read_text())["labs"])
    return labs, set(labs)


def is_edge(x, y):
    return x <= 1 or x >= 116 or y <= 1 or y >= 90


def disp_tag(dx, dy):
    return f"{'r' if dx >= 0 else 'l'}{abs(dx)}{'u' if dy >= 0 else 'd'}{abs(dy)}"


def site_pairs():
    """{tag: (driver_lab, sink_lab)}: POSITIONS interior tiles per tile class x DISPS, plus the
    edge rows of docs/cycloneiv-specimens.md: every edge LAB tile in both roles, kinds repeated
    at the four corners."""
    labs, labset = labs_grid()
    bycls = collections.defaultdict(list)
    for t in labs:
        bycls[tclass(*t)].append(t)
    out = {}
    for cls in sorted(bycls):
        ts = [t for t in bycls[cls] if not is_edge(*t)] or bycls[cls]
        picks = []
        for q in range(POSITIONS):
            p = ts[(q + 1) * len(ts) // (POSITIONS + 1)]
            if p not in picks:
                picks.append(p)
        for pi, (x, y) in enumerate(picks):
            for dx, dy in DISPS:
                sink = snap(x + dx, y + dy, labset)
                if sink is None or sink == (x, y):
                    continue
                out[f"c{cls:02d}p{pi}{disp_tag(dx, dy)}"] = ((x, y), sink)
    # every edge LAB tile, driver (a) and sink (b) roles; inward partner 3 tiles off the edge
    for x, y in labs:
        if not is_edge(x, y):
            continue
        dx = 3 if x <= 1 else -3 if x >= 116 else 0
        dy = 3 if y <= 1 else -3 if y >= 90 else 0
        inward = snap(x + dx, y + dy, labset)
        if inward is None or inward == (x, y):
            continue
        out[f"e{x}_{y}a"] = ((x, y), inward)
        out[f"e{x}_{y}b"] = (inward, (x, y))
    # corners: the full displacement set (kinds 1-8 of the matrix, as far as the die allows)
    for cx, cy in ((1, 1), (1, 90), (116, 1), (116, 90)):
        if (cx, cy) not in labset:
            continue
        for dx, dy in DISPS:
            sink = snap(cx + dx, cy + dy, labset)
            if sink is None or sink == (cx, cy):
                continue
            out[f"k{cx}_{cy}{disp_tag(dx, dy)}"] = ((cx, cy), sink)
    return out


FIXED_OUT, FIXED_OUT2 = "B9", "D11"   # fixed pad for pin-row specimens (fitter's own picks, c00p0r3u0)
FIXED_IN, FIXED_IN2 = "B6", "C5"
LAB_A, LAB_B = (58, 45), (48, 45)     # fixed LUT sites for the pin rows (snapped to legal LABs in gen)


def user_pins():
    """Bonded user-IO pin locations from a built specimen's .pin file."""
    pin = CORPUS / "gxspec_c00p0r3u0" / "build.pin"
    if not pin.exists():
        raise SystemExit("build gxspec_c00p0r3u0 first: pin rows read its build.pin")
    out = []
    for ln in pin.read_text().splitlines():
        parts = [p.strip() for p in ln.split(":")]
        if len(parts) >= 3 and (parts[0].startswith("RESERVED_INPUT") or parts[0] in ("a", "y", "y1")):
            out.append(parts[1])
    return sorted(set(out))


def pin_specs():
    """Rows 6/7 of the matrix: one specimen pair through every bonded pin, both directions.
    pi (pin -> fabric): l1 at LAB_A reads the swept pin; base twin = same placement, constant LUT.
    po (fabric -> pin): l1 at LAB_A drives the swept pin; base twin = same net from LAB_B, so the
    exit path into the pin differs and survives the diff (LAB_A's own defaults become pool noise,
    handled by the windows)."""
    _labs, labset = labs_grid()
    la, lb = snap(*LAB_A, labset), snap(*LAB_B, labset)
    out = {}
    for p in user_pins():
        fo = FIXED_OUT2 if p == FIXED_OUT else FIXED_OUT
        fi = FIXED_IN2 if p == FIXED_IN else FIXED_IN
        tag = p.lower()
        out[f"pi_{tag}"] = {
            "spec": (verilog_one(True), [f"set_location_assignment PIN_{p} -to a",
                                         f"set_location_assignment PIN_{fo} -to y",
                                         f"set_location_assignment LCCOMB_X{la[0]}_Y{la[1]}_N0 -to l1"]),
            "base": (verilog_one(False), [f"set_location_assignment PIN_{fo} -to y",
                                          f"set_location_assignment LCCOMB_X{la[0]}_Y{la[1]}_N0 -to l1"]),
            "purpose": f"pin row 6: PIN_{p} -> fabric (LUT at X{la[0]} Y{la[1]})"}
        out[f"po_{tag}"] = {
            "spec": (verilog_one(True), [f"set_location_assignment PIN_{fi} -to a",
                                         f"set_location_assignment PIN_{p} -to y",
                                         f"set_location_assignment LCCOMB_X{la[0]}_Y{la[1]}_N0 -to l1"]),
            "base": (verilog_one(True), [f"set_location_assignment PIN_{fi} -to a",
                                         f"set_location_assignment PIN_{p} -to y",
                                         f"set_location_assignment LCCOMB_X{lb[0]}_Y{lb[1]}_N0 -to l1"]),
            "purpose": f"pin row 7: fabric -> PIN_{p} (LUT at X{la[0]} Y{la[1]}, base at X{lb[0]} Y{lb[1]})"}
    return out


def verilog_one(with_input):
    """Single-LUT module for the pin rows; without input, a constant LUT holds the placement."""
    if with_input:
        return ("module top(input a, output y);\n"
                '  cycloneiv_lcell_comb #(.lut_mask(16\'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                "    l1 (.dataa(a), .combout(y));\nendmodule\n")
    return ("module top(output y);\n"
            '  cycloneiv_lcell_comb #(.lut_mask(16\'h0000), .sum_lutc_input("datac"), .dont_touch("on"))\n'
            "    l1 (.combout(y));\nendmodule\n")


def gen():
    import datetime
    import toolchain
    m = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    tool_version = m.group(1) if m else "unknown"
    today = datetime.date.today().isoformat()

    def write(name, v, qsf, purpose):
        d = CORPUS / name
        if (d / "routing.rcf").exists():     # provenance rule: never rewrite a built design's record
            return
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(v)
        q = qsf + ["set_global_assignment -name SEED 1",
                   'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
        (d / "design.toml").write_text(
            f'top = "top"\npurpose = "{purpose}"\n'
            f'exercises = {fz.toml_list(["routing", "specimen"])}\nqsf = {fz.toml_list(q)}\n'
            f'device = "{DEVICE}"\ntool = "quartus"\ntool_version = "{tool_version}"\nbuilt = "{today}"\n')

    pairs = site_pairs()
    for tag, ((x1, y1), (x2, y2)) in pairs.items():
        for kind, with_net in (("gxspec", True), ("gxbase", False)):
            write(f"{kind}_{tag}", verilog(with_net),
                  [f"set_location_assignment LCCOMB_X{x1}_Y{y1}_N0 -to l1",
                   f"set_location_assignment LCCOMB_X{x2}_Y{y2}_N0 -to l2"],
                  f"routing specimen LAB X{x1} Y{y1} -> X{x2} Y{y2}"
                  + (" (one net)" if with_net else " (base twin: no net)"))
    ps = pin_specs()
    for tag, s in ps.items():
        write(f"gxspec_{tag}", *s["spec"], s["purpose"])
        write(f"gxbase_{tag}", *s["base"], s["purpose"] + " (base twin)")
    log.info("generated %d designs (%d site pairs + %d pin pairs)", 2 * (len(pairs) + len(ps)), len(pairs), len(ps))


def build(match, jobs, force):
    names = sorted(p.name for p in CORPUS.iterdir()
                   if p.name.startswith(("gxspec_", "gxbase_")) and fnmatch.fnmatch(p.name, match)
                   and (p / "design.toml").exists() and (force or not (p / "routing.rcf").exists()))
    log.info("%d specimen builds, %d jobs", len(names), jobs)
    fz.log.setLevel(logging.INFO)
    for h in log.handlers:
        fz.log.addHandler(h)
    bad = {}

    def one(n):
        if ABORT.exists():
            bad[n] = "aborted"
            return
        heavy_guard.wait_available(log, n, JOB_MIN_GB)
        t0 = time.monotonic()
        f = fz.build_one(n)
        log.info("%s: %s (%.1fs)", n, "ok" if f is None else f"FAIL at {f}", time.monotonic() - t0)
        if f:
            bad[n] = f
    with heavy_guard.heavy_lock("cycloneiv_specimens", log):
        heavy_guard.wait_available(log, "specimen batch", BATCH_MIN_GB)
        with ThreadPoolExecutor(jobs) as ex:
            list(ex.map(one, names))
    log.info("build done %d, failed %d %s", len(names) - len(bad), len(bad), dict(list(bad.items())[:10]))
    return 1 if bad else 0


# ---------------------------------------------------------------- solve
class Solver:
    def __init__(self):
        import cycloneiv_phys_trace as pt
        self.P = pt.Phys(need_map=False)
        self.fam_type = self._fam_types()

    def _fam_types(self):
        P = self.P
        ft = {}
        for f in range(P.nfam):
            lo, hi = int(P.fbounds[f]), int(P.fbounds[f + 1])
            if f in LEBUF_FAMS:
                if hi - lo != 9360:
                    raise SystemExit(f"family {f}: expected 9360 LE_BUFFER records, got {hi - lo}")
                ft[f] = "LEBUF"
                continue
            c = collections.Counter()
            for r in range(lo, min(hi, lo + 64)):
                nm = P.dec.names.get(r)
                m = nm and re.match(r"^(H4|V4|H24|V16)", nm)
                if m:
                    c[m.group(1)] += 1
            ft[f] = c.most_common(1)[0][0] if c else "?"
        return ft

    def fired(self, name):
        """{(block, source record, group)} of non-select fired groups."""
        P = self.P
        plane = cc.load_plane_only(name)
        gids, recs, blocks = P.dec.active(plane)
        keep = P.dec.npred[gids] < P.dec.gsize[gids]
        return set(zip(blocks[keep].tolist(), recs[keep].tolist(), gids[keep].tolist()))

    def gsel(self, G, tx, ty):
        """The fired group's select-entry position relative to the block tile anchor: identifies
        WHICH input of the block fired (a block can hold several muxes sharing second-level bits,
        each driving its own wire - the group, not the block, names the answer)."""
        dec = self.P.dec
        s, n = int(dec.gstart[G]), int(dec.gsize[G])
        b0 = np.asarray(dec.b0[s:s + n])
        j = s + (int(np.argmax(b0 == 1)) if (b0 == 1).any() else 0)
        f0, v0 = self.P.g.anchor(tx, ty)
        return f"{int(dec.pf[j]) - f0},{int(dec.pv[j]) - v0}"

    def src_ok(self, a, s, loose=False):
        """May record s be the wire the RCF names a?  (type family + node-tile window).
        Unknown src types (IO ring) have no model: they match only with loose=True (near-clean
        diff pool), where uniqueness within the dst window still decides alone."""
        P = self.P
        fx, fy = XMIRROR - int(P.vx[s]), int(P.vy[s])
        t = self.fam_type.get(int(P.fam[s]), "?")
        if a[1] == "LE_BUFFER":
            w = SRC_WIN["LE_BUFFER"]
            return t == "LEBUF" and -w[0] <= fx - a[2] <= 0 and abs(fy - a[3]) <= w[1]
        fams = SRC_FAMS.get(a[1])
        if fams is None:
            return loose and t not in ("LEBUF", "H4", "V4", "H24", "V16")
        w = SRC_WIN[a[1]]
        return t in fams and abs(fx - a[2]) <= w[0] and abs(fy - a[3]) <= w[1]

    def solve_one(self, name):
        """-> result dict with exact wire / li observations, or an error marker."""
        P = self.P
        base = name.replace("gxspec_", "gxbase_")
        if not (CORPUS / base / "routing.rcf").exists():
            return {"error": f"{base}: not built"}
        pool = sorted(self.fired(name) - self.fired(base))
        rcf = cc.parse_rcf(CORPUS / name / "routing.rcf")
        # entries are emitted ONLY from the net under test (both ends pinned by the design);
        # other nets' edges still participate in matching for the all-different constraint.
        # Pad-path edges re-routed between twins are real but unanchored - the first per-tile
        # conflicts (2026-10-28) were exactly those, matched to lookalike IO-row LI muxes.
        on_path = self.target_path(name, rcf)
        edges = [(a, b) for lst in rcf.values() for a, b in lst
                 if a[0] == "W" and b[0] == "W" and b[1] in DST_WIN]
        rec, match = {}, {}
        bytile = collections.defaultdict(list)       # block tile -> live (block, src, group) triples
        for B, s, G in pool:
            bytile[(int(P.btx[B]), int(P.bty[B]))].append((B, s, G))
        stats = collections.Counter(edges_total=len(edges), fired_pairs=len(pool))

        loose = len(pool) <= LOOSE_POOL_MAX

        def cands(a, b):
            wx, wy = DST_WIN[b[1]]
            out = []
            for tx in range(b[2] - wx, b[2] + wx + 1):
                for ty in range(b[3] - wy, b[3] + wy + 1):
                    for (B, s, G) in bytile.get((tx, ty), ()):
                        if a in rec:
                            if s == rec[a]:
                                out.append((B, s, G))
                        elif self.src_ok(a, s, loose):
                            out.append((B, s, G))
            return out

        pending = list(edges)
        while True:
            progress, keep = False, []
            for a, b in pending:
                cs = cands(a, b)
                if len(cs) == 1:
                    B, s, G = cs[0]
                    if a in rec and rec[a] != s:
                        return {"error": f"chain conflict at {a}: records {rec[a]} vs {s}"}
                    rec[a] = s
                    match[(a, b)] = (B, s, G)
                    t = (int(P.btx[B]), int(P.bty[B]))
                    bytile[t] = [p for p in bytile[t] if p[0] != B]
                    progress = True
                else:
                    keep.append((a, b))
            pending = keep
            if not progress:
                break
        unmatched = []
        for a, b in pending:
            cs = cands(a, b)
            stats["edge_ambiguous" if len(cs) > 1 else "edge_no_candidate"] += 1
            unmatched.append({"edge": [list(a[1:]), list(b[1:])], "rec_known": a in rec,
                              "cands": [self.pair_info(*c) for c in cs[:8]]})
        wires, lis, bufs = [], [], []
        for (a, b), (B, s, G) in match.items():
            stats["edge_matched"] += 1
            if (a, b) not in on_path:
                stats["off_target_matched"] += 1
                continue
            tx, ty, key = int(P.btx[B]), int(P.bty[B]), str(P.keys[int(P.bkey[B])])
            gs = self.gsel(G, tx, ty)
            if a[1] == "LE_BUFFER":
                bufs.append([a[5] // 2, (int(P.fam[s]) - 16) // 2])   # RCF I//2 = LE = (family-16)//2
            if b[1] == "LOCAL_INTERCONNECT":
                lis.append({"tile": [tx, ty], "key": key, "gsel": gs, "val": [b[3] - ty, b[5]],
                            "dst": list(b[1:]), "src_rec": s})
                continue
            rb = rec.get(b)
            if rb is None:
                stats["out_unresolved"] += 1                   # no downstream mux pinned the output record
                continue
            if rb == s:
                return {"error": f"self-loop at {b}"}
            val = [int(P.fam[rb]), int(P.vx[rb]) - (XMIRROR - tx), int(P.vy[rb]) - ty]
            wires.append({"tile": [tx, ty], "key": key, "gsel": gs, "val": val,
                          "dst": list(b[1:]), "src_rec": s, "out_rec": rb})
        return {"design": name, "stats": dict(stats), "wires": wires, "lis": lis, "lebuf_i_fam": bufs,
                "unmatched": unmatched}

    def target_path(self, name, rcf):
        """The W->W edges of the ONE path under test: from the driver's LE_BUFFER (or the pin) to
        the sink cell's LI / to the pad.  Walked backward from the sink end, so the y1-pad branch
        of net n and every other net stay out of the emitted entries (they still take part in
        matching).  Sink location from the design's own qsf."""
        import tomllib
        t = tomllib.loads((CORPUS / name / "design.toml").read_text())
        locs = {m.group(3): (int(m.group(1)), int(m.group(2)))
                for q in t["qsf"] for m in [re.match(r"set_location_assignment LCCOMB_X(\d+)_Y(\d+)_N\d+ -to (l\d)", q)] if m}
        kind = name[:9]
        if kind == "gxspec_po":
            net, terminal = "y", lambda nd: nd[0] == "W" and nd[1] == "BLOCK_INPUT_MUX"
        elif kind == "gxspec_pi":
            lab = locs["l1"]
            net, terminal = "a~input", lambda nd: nd[0] == "W" and nd[1] == "LOCAL_INTERCONNECT" and (nd[2], nd[3]) == lab
        else:
            lab = locs["l2"]
            net, terminal = "n", lambda nd: nd[0] == "W" and nd[1] == "LOCAL_INTERCONNECT" and (nd[2], nd[3]) == lab
        driver_of = {}
        ends = []
        for a, b in rcf.get(net, ()):
            if b[0] == "W":
                driver_of[b] = a
            if b[0] == "W" and terminal(b):
                ends.append(b)
        out = set()
        for nd in ends:
            while nd in driver_of and driver_of[nd][0] == "W":
                out.add((driver_of[nd], nd))
                nd = driver_of[nd]
        return out

    def pair_info(self, B, s, _G=None):
        P = self.P
        return {"block": int(B), "tile": [int(P.btx[B]), int(P.bty[B])], "key": str(P.keys[int(P.bkey[B])]),
                "src": [int(s), self.fam_type.get(int(P.fam[s]), "?"), XMIRROR - int(P.vx[s]), int(P.vy[s]),
                        P.dec.names.get(int(s), "")]}


def solve(match, force, watch=False):
    """One pass by default.  --watch pipelines with a running build: solves each pair the moment
    both twins have an RCF, streams the incremental aggregate, ends when the build reports done
    and nothing is left (a systematic matching fault then shows after a dozen solves, not after
    the batch)."""
    import threading
    (WORK / "solved").mkdir(parents=True, exist_ok=True)
    build_log = REPO / "tmp" / "logs" / "cycloneiv_specimens_build.out"
    S = None
    done = set() if force else {p.stem for p in (WORK / "solved").glob("gxspec_*.json")}
    t0 = time.time()
    while True:
        ready = sorted(p.name for p in CORPUS.iterdir()
                       if p.name.startswith("gxspec_") and fnmatch.fnmatch(p.name, match)
                       and (p / "routing.rcf").exists()
                       and (CORPUS / p.name.replace("gxspec_", "gxbase_") / "routing.rcf").exists())
        todo = [n for n in ready if n not in done]
        if todo:
            S = S or Solver()

            def one(n):
                r = S.solve_one(n)
                (WORK / "solved" / f"{n}.json").write_text(json.dumps(r, indent=0))
                return n, r
            with ThreadPoolExecutor(8) as ex:
                for i, (n, r) in enumerate(ex.map(one, todo)):
                    if "error" in r:
                        log.info("%s: ERROR %s", n, r["error"])
                    elif i % 50 == 49 or len(todo) <= 8:
                        log.info("%s: %s (%d / %d, %.0fs)", n, r["stats"], i + 1, len(todo), time.time() - t0)
            done.update(todo)
            agg = aggregate(sorted(done))
            abort_check(agg, len(done))
        if not watch:
            break
        built_done = build_log.exists() and "build done" in build_log.read_text()[-2000:]
        if built_done and not todo:
            break
        threading.Event().wait(20)   # poll for newly built pairs; builds take ~15 s each
    if not done:
        log.info("solve: nothing ready")


ABORT = WORK / "ABORT"


def abort_check(agg, n_solved):
    """Fail-fast over the streamed solves: a broken matcher must not consume the batch.
    Kills the running build batch (heavy-lock pid), leaves an ABORT sentinel, hard exit."""
    t = agg["stats"]
    why = None
    if n_solved >= 20 and t.get("edge_matched", 0) == 0:
        why = f"{n_solved} solves, zero matched edges"
    elif n_solved >= 20 and t.get("specimens_error", 0) > 0.5 * n_solved:
        why = f"{t.get('specimens_error')} / {n_solved} specimens errored"
    elif n_solved >= 50 and not (agg["wires"] or agg["lis"] or agg["wires_tile"] or agg["lis_tile"]):
        why = f"{n_solved} solves, zero exact entries"
    if why is None:
        return
    ABORT.write_text(why + "\n")
    log.error("ABORT: %s - killing the build batch", why)
    try:
        pid = int(re.search(r"pid=(\d+)", Path(heavy_guard.LOCK_PATH).read_text()).group(1))
        import psutil
        p = psutil.Process(pid)
        for c in p.children(recursive=True) + [p]:
            c.kill()
        log.error("killed build batch pid %d", pid)
    except Exception as e:                                     # lock free / already gone
        log.error("no build batch killed (%s)", e)
    sys.exit(3)


def aggregate(names):
    """solved/*.json -> exact.json.  The unit of generalisation is (class, block key, GROUP
    select position): one block can hold several muxes sharing second-level bits, each driving
    its own wire, so a key's entry is the LIST of its groups' outputs.  Edge rule
    (docs/cycloneiv-specimens.md): edge-tile observations NEVER pool into a class - always
    per-tile entries.  Interior: a (class|key|gsel) answer needs >= 2 distinct tiles agreeing;
    a single interior tile stays per-tile; a class disagreement demotes that gsel to per-tile
    entries; a SAME-(tile, gsel) disagreement is a decode bug: evidence written, hard exit."""
    obs = {"wires": collections.defaultdict(list), "lis": collections.defaultdict(list)}
    tot = collections.Counter()
    buf_bad = []
    for n in names:
        p = WORK / "solved" / f"{n}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())
        if "error" in r:
            tot["specimens_error"] += 1
            continue
        tot["specimens"] += 1
        tot.update(r["stats"])
        for kind in ("wires", "lis"):
            for o in r[kind]:
                tx, ty = o["tile"]
                obs[kind][(tclass(tx, ty), o["key"])].append((tx, ty, o["gsel"], tuple(o["val"]), n))
        buf_bad += [[n] + b for b in r["lebuf_i_fam"] if b[0] != b[1]]
    out = {"class": {"x_mod": XM, "y_mod": YM}, "wires": {}, "lis": {},
           "wires_tile": {}, "lis_tile": {}, "same_tile_conflicts": [], "class_conflicts": []}
    for kind in ("wires", "lis"):
        for (cls, key), lst in sorted(obs[kind].items()):
            per_tg = collections.defaultdict(set)              # (tile, gsel) -> vals
            for tx, ty, gs, val, n in lst:
                per_tg[((tx, ty), gs)].add(val)
            bad = {k: vs for k, vs in per_tg.items() if len(vs) > 1}
            if bad:
                out["same_tile_conflicts"].append({"kind": kind, "class": cls, "key": key,
                                                   "tiles": {f"{t[0]},{t[1]}|{gs}": sorted(map(list, vs)) for (t, gs), vs in bad.items()},
                                                   "obs": [list(o) for o in lst]})
                continue

            def add_tile(t, val):
                e = out[f"{kind}_tile"].setdefault(f"{t[0]},{t[1]}|{key}", {"val": []})
                if list(val) not in e["val"]:
                    e["val"].append(list(val))
            per_gsel = collections.defaultdict(dict)           # gsel -> {interior tile: val}
            for ((tx, ty), gs), vs in per_tg.items():
                if is_edge(tx, ty):
                    add_tile((tx, ty), next(iter(vs)))         # edge tiles: always their own entries
                else:
                    per_gsel[gs][(tx, ty)] = next(iter(vs))
            vals_out, nobs = [], 0
            for gs, tiles in per_gsel.items():
                vals = set(tiles.values())
                if len(vals) == 1 and len(tiles) >= 2:
                    v = vals.pop()
                    if list(v) not in vals_out:
                        vals_out.append(list(v))
                    nobs += len(tiles)
                elif len(vals) == 1:                           # single interior tile: exact, not generalised
                    for t, v in tiles.items():
                        add_tile(t, v)
                else:
                    out["class_conflicts"].append({"kind": kind, "class": cls, "key": key, "gsel": gs,
                                                   "vals": sorted(map(list, vals)),
                                                   "obs": [list(o) for o in lst if o[2] == gs]})
                    for t, v in tiles.items():
                        add_tile(t, v)
            if vals_out:
                out[kind][f"{cls}|{key}"] = {"val": vals_out, "n": nobs,
                                             "tiles": len({t for ts in per_gsel.values() for t in ts})}
    out["stats"] = dict(tot)
    (WORK / "exact.json").write_text(json.dumps(out, indent=0))
    log.info("aggregate: %d specimens (%d errors); edges matched %d / %d (ambiguous %d, no candidate %d, "
             "output unresolved %d)", tot["specimens"], tot["specimens_error"], tot["edge_matched"],
             tot["edges_total"], tot["edge_ambiguous"], tot["edge_no_candidate"], tot["out_unresolved"])
    log.info("exact entries: wires %d, lis %d; class conflicts %d (-> %d + %d per-tile entries)",
             len(out["wires"]), len(out["lis"]), len(out["class_conflicts"]),
             len(out["wires_tile"]), len(out["lis_tile"]))
    if buf_bad:
        log.info("LE_BUFFER I != family-16 on %d edges (first: %s)", len(buf_bad), buf_bad[:3])
    if out["same_tile_conflicts"]:
        log.error("SAME-TILE conflicts: %d (see %s) - two exact answers for one mux; decode bug, stopping",
                  len(out["same_tile_conflicts"]), WORK / "exact.json")
        sys.exit(2)
    return out


# ---------------------------------------------------------------- verify / merge
def verify():
    S = Solver()
    e = json.loads((WORK / "exact.json").read_text())
    by = collections.defaultdict(collections.Counter)
    for k, v in e["wires"].items():
        for val in v["val"]:
            by[S.fam_type.get(val[0], "?")]["class_entries"] += 1
    for k, v in e["wires_tile"].items():
        for val in v["val"]:
            by[S.fam_type.get(val[0], "?")]["tile_entries"] += 1
    by["LI"]["class_entries"] = sum(len(v["val"]) for v in e["lis"].values())
    by["LI"]["tile_entries"] = sum(len(v["val"]) for v in e["lis_tile"].values())
    for t in sorted(by):
        log.info("  %-6s %s", t, dict(by[t]))
    # edge / pin coverage (docs/cycloneiv-specimens.md reporting format)
    labs, _ = labs_grid()
    edge_all = {t for t in labs if is_edge(*t)}
    touched = set()
    for kind in ("wires_tile", "lis_tile"):
        for k in e[kind]:
            tx, ty = map(int, k.split("|", 1)[0].split(","))
            if (tx, ty) in edge_all:
                touched.add((tx, ty))
    pins_hit = collections.Counter()
    for pfx in ("pi", "po"):
        names = [p.name for p in (WORK / "solved").glob(f"gxspec_{pfx}_*.json")]
        ok = 0
        for n in names:
            r = json.loads((WORK / "solved" / n).read_text())
            ok += bool(r.get("stats", {}).get("edge_matched"))
        pins_hit[pfx + "_solved"] = ok
        pins_hit[pfx + "_built"] = len(names)
    log.info("edge coverage: %d / %d edge LAB tiles touched; pins: in %d / %d, out %d / %d (solved/built)",
             len(touched), len(edge_all), pins_hit["pi_solved"], pins_hit["pi_built"],
             pins_hit["po_solved"], pins_hit["po_built"])
    pm = json.loads(PHYS_MAP.read_text())
    agree = collections.Counter()
    for k, v in e["wires"].items():
        old = pm["wires"].get(k)
        if old is not None and list(old) and not isinstance(old[0], list):
            agree["wires_agree" if list(old) in v["val"] else "wires_DISAGREE"] += 1
    lim = json.loads(LI_MAP.read_text()) if LI_MAP.exists() else {"lis": {}}
    for k, v in e["lis"].items():
        old = lim["lis"].get(k) or pm["lis"].get(k)
        if old is not None and list(old) and not isinstance(old[0], list):
            agree["lis_agree" if list(old) in v["val"] else "lis_DISAGREE"] += 1
    log.info("vs voted maps: %s; class conflicts %d, per-tile entries %d",
             dict(agree), len(e["class_conflicts"]), len(e["wires_tile"]) + len(e["lis_tile"]))


def merge():
    e = json.loads((WORK / "exact.json").read_text())
    if e["same_tile_conflicts"]:
        raise SystemExit("same-tile conflicts present: not merging")
    pm = json.loads(PHYS_MAP.read_text())
    prov = pm.setdefault("provenance", {"wires": {}, "lis": {}})
    n = collections.Counter()
    for kind in ("wires", "lis"):
        for k, v in e[kind].items():
            n[f"{kind}_replaced" if k in pm[kind] else f"{kind}_new"] += 1
            pm[kind][k] = v["val"]
            prov[kind][k] = "specimen"
    for kind in ("wires_tile", "lis_tile"):
        pm[kind] = {k: v["val"] for k, v in e[kind].items()}
        n[kind] = len(pm[kind])
    # scrub voted li_map entries that collide with an exact (class, li index): li_inv is one
    # winner per (class, li); a stale voted key under another block key would race the exact one
    if LI_MAP.exists():
        lim = json.loads(LI_MAP.read_text())
        exact_cls_li = {(k.split("|", 1)[0], val[1]) for k, v in e["lis"].items() for val in v["val"]}
        drop = [k for k, v in lim["lis"].items()
                if (k.split("|", 1)[0], v[1]) in exact_cls_li and f'{k}' not in e["lis"]]
        for k in drop:
            del lim["lis"][k]
        LI_MAP.write_text(json.dumps(lim, indent=0))
        n["li_map_scrubbed"] = len(drop)
    PHYS_MAP.write_text(json.dumps(pm, indent=0))
    log.info("merged into %s: %s", PHYS_MAP, dict(n))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("gen", "build", "solve", "verify", "merge"))
    ap.add_argument("--match", default="*")
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--watch", action="store_true", help="solve: pipeline with a running build")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_specimens.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    if a.cmd == "gen":
        gen()
    elif a.cmd == "build":
        return build(a.match, a.jobs, a.force)
    elif a.cmd == "solve":
        solve(f"gxspec_{a.match}" if not a.match.startswith("gx") else a.match, a.force, a.watch)
    elif a.cmd == "verify":
        verify()
    else:
        merge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
