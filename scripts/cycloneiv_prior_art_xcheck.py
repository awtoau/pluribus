#!/usr/bin/env python3.15t
"""Read-only cross-check: our EP4CE6 LE mask address model vs the 14sea/Cyclone_CRAM_Mapper
address functions.  Their clone is imported at run time from sources/prior-art/ (gitignored,
GPL-3.0-or-later); nothing of theirs is copied into this tree.  Log: tmp/logs/cycloneiv_prior_art_xcheck.log

  python3.15t scripts/cycloneiv_prior_art_xcheck.py
"""
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
THEIRS = REPO / "sources" / "prior-art" / "14sea-cyclone-cram-mapper" / "fuzz"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(THEIRS))
import config as th  # noqa: E402  (14sea fuzz/config.py)
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cycloneiv_prior_art_xcheck.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
_log = LOG.open("w")


def out(s=""):
    print(s)
    _log.write(s + "\n")
    _log.flush()


g = cg.load("ep4ce6")
F = 210
PRE = 32
vmap = cc.vmap_for(F, tuple(g.lane_bytes), tuple(map(tuple, g.lane_swaps)))
bit_of_v = {int(v): b for b, v in enumerate(vmap) if v >= 0}


def ours(x, y, n):
    """{k: (frame, byte, lane)} from our model."""
    mirror = -1 if (n // 2) % 2 else 1
    r = {}
    for k, (df, dv, _inv) in g.dk.items():
        fr = g.FX[x] + df
        v = g.vy0 + g.vpitch * y + g.DN[n // 2] + mirror * dv
        byte, lane = divmod(bit_of_v[v], 8)
        r[k] = (fr, byte, lane)
    return r


def loc(addr):
    rel = addr - PRE
    return rel // F, rel % F


def theirs_pairs(x, y, n):
    """[(pair, ctrl_frame, ctrl_byte, ctrl_bit, data_frame, data_byte)]"""
    rows = []
    bit = th.cram_ctrl_bit(y)
    for p in range(8):
        cf, cb = loc(th.cram_ctrl_addr(x, y, p, n))
        df, db = loc(th.cram_data_addr(x, p))
        rows.append((p, cf, cb, bit, df, db))
    return rows


def main():
    cnt = collections.Counter()
    shift = collections.Counter()
    col = collections.Counter()
    ex = []
    sites = [(x, y, n) for x in th.LAB_X + th.JAILBREAK_LAB_X for y in th.LAB_Y for n in th.LE_N
             if x in g.FX and g.kind[x] == "LAB"]
    for x, y, n in sites:
        o = ours(x, y, n)
        t = theirs_pairs(x, y, n)
        ofr = sorted({v[0] for v in o.values()})
        tfr = sorted({r[1] for r in t})
        cnt["sites"] += 1
        cnt["frame_set_equal"] += ofr == tfr
        col[(x, tfr[0] - ofr[0], tfr[-1] - ofr[-1])] += 1
        # byte/lane: their ctrl byte (and +1) at their ctrl frame vs our bytes in that frame
        for k, (fr, byte, lane) in o.items():
            hit_frame = any(r[1] == fr for r in t)
            cnt["bits"] += 1
            cnt["bit_frame_hit"] += hit_frame
            for r in t:
                if r[1] == fr:
                    cnt["bit_byte_hit"] += (byte in (r[2], r[2] + 1))
                    cnt["bit_byte_lane_hit"] += (byte in (r[2], r[2] + 1) and lane == r[3])
                    cnt["bit_data_byte_hit"] += (byte in (r[5], r[5] + 1))
                    shift[(byte - r[2])] += 1
    out(f"sites compared (their 28 LAB columns x 18 rows x 16 LEs, restricted to our LAB cols): {cnt['sites']}")
    out(f"sites where the 8 frames of their pairs == the 8 frames of our mask bits: {cnt['frame_set_equal']}")
    cols = collections.Counter()
    for (x, d0, d1), c in col.items():
        cols[(d0, d1)] += c
    out(f"(their first/last pair frame - our first/last mask frame) histogram: {dict(cols.most_common(8))}")
    out(f"mask bits: {cnt['bits']}; frame has a pair of theirs: {cnt['bit_frame_hit']}")
    out(f"  our byte in {{ctrl, ctrl+1}} of that pair: {cnt['bit_byte_hit']}; and lane == their bit position: {cnt['bit_byte_lane_hit']}")
    out(f"  our byte in {{data, data+1}} of that pair: {cnt['bit_data_byte_hit']}")
    out(f"  (our byte - their ctrl byte) top: {dict(shift.most_common(6))}")
    # column bases
    out("")
    out("column step check (frames between consecutive LAB columns, ours vs theirs):")
    xs = sorted(x for x in th.COLUMN_BASE)
    bad = 0
    for a, b in zip(xs, xs[1:]):
        tf = (th.COLUMN_BASE[b] - th.COLUMN_BASE[a]) / F
        of = g.FX[b] - g.FX[a]
        if tf != of:
            bad += 1
            out(f"  X{a}->X{b}: theirs {tf} frames, ours {of}")
    out(f"  {len(xs) - 1} steps, {bad} differ")
    offs = {x: loc(th.COLUMN_BASE[x] - 136) for x in xs}
    d = collections.Counter(offs[x][0] - g.FX[x] for x in xs)
    out(f"  their column period start frame - our FX[X]: {dict(d)}; byte-in-frame of period start: "
        f"{dict(collections.Counter(v[1] for v in offs.values()))}")
    out(f"  their {len(th.LAB_X)} whitelist + {len(th.JAILBREAK_LAB_X)} jailbreak columns all LAB in our geometry: "
        f"{all(g.kind.get(x) == 'LAB' for x in xs)}; our non-LAB columns: "
        f"{sorted(x for x, k in g.kind.items() if k not in ('LAB',))}")
    out(f"  our LAB columns they never list: {sorted(x for x, k in g.kind.items() if k == 'LAB' and x not in th.COLUMN_BASE)}")
    # rows
    out("")
    ys = sorted(set(th.LAB_Y) | set(th.JAILBREAK_LAB_Y))
    out("Y rows: (their ctrl byte-in-frame at N0 pair0 for Y, ours byte/lane of mask bit0 at X10 N0):")
    for y in ys:
        o = ours(10, y, 0)[0]
        fr, by = loc(th.cram_ctrl_addr(10, y, 7, 0))
        out(f"  Y{y}: theirs pair7 frame {fr} byte {by} bit {th.cram_ctrl_bit(y)} | ours frame {o[0]} byte {o[1]} lane {o[2]}")
    # extrapolated rows / columns (their formula is arithmetic, so it extends)
    out("")
    cnt2 = collections.Counter()
    for y in (1, 15, 20, 22, 23):
        for x in th.LAB_X:
            for n in th.LE_N:
                o = {v for v in ours(x, y, n).values()}
                try:
                    t = {(r[1], r[2] + s, r[3]) for r in theirs_pairs(x, y, n) for s in (0, 1)}
                except KeyError:
                    continue
                cnt2[(y, "equal")] += o == t
                cnt2[(y, "sites")] += 1
    out("extrapolated rows (their formula run at a Y they never list), cell-set equal / sites: "
        + ", ".join(f"Y{y} {cnt2[(y, 'equal')]}/{cnt2[(y, 'sites')]}" for y in (1, 15, 20, 22, 23)))
    # real bitstreams: ours vs post-fit .vo masks
    import os
    import re
    import cycloneiv_decompress as cd
    C = REPO / "corpus" / "cycloneiv"
    names = [n for n in os.listdir(C) if re.match(r"(ho2?|lut_[abc]|site_x\d+_y\d+_n\d+)_", n)
             and (C / n / "postfit.vo").exists() and (C / n / "bitstream.rbf").exists()]
    z = collections.Counter()
    for nm in sorted(names):
        vo = cc.load_vo(nm)
        u = cd.decompress((C / nm / "bitstream.rbf").read_bytes())
        for a in vo.atoms.values():
            if a["type"] != "cycloneive_lcell_comb":
                continue
            m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)$", a.get("location") or "")
            if not m:
                continue
            x, y, n = map(int, m.groups())
            mask = int(a["params"]["lut_mask"].split("'h")[1], 16)
            try:
                o = ours(x, y, n)
            except KeyError:
                continue
            ok = all((u[PRE + c[0] * F + c[1]] >> c[2] & 1) == (mask >> k & 1) for k, c in o.items())
            z["cells"] += 1
            z["ours_exact"] += ok
            if x in th.COLUMN_BASE and y in th.LAB_Y:
                t = {(r[1], r[2] + s, r[3]) for r in theirs_pairs(x, y, n) for s in (0, 1)}
                if set(o.values()) != t:
                    z["cells_in_disagreement_zone"] += 1
                    z["ours_exact_in_zone"] += ok
            else:
                z["cells_outside_their_grid"] += 1
                z["ours_exact_outside_their_grid"] += ok
    out(f"real EP4CE6 cells (lut_/site_/ho_/ho2_ designs vs post-fit .vo lut_mask): {dict(z)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
