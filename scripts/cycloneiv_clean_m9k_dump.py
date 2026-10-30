#!/usr/bin/env python3.15t
"""Dump the M9K memory contents of an EP4CGX150 image / corpus specimens with the vendor-derived layouts (lifters/cycloneiv_clean/m9k.py, #169).

  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_m9k_dump.py image [--out tmp/m9k_dump]
  python3.15t scripts/cycloneiv_clean_m9k_dump.py crosscheck [--out tmp/m9k_dump]

image:      per populated M9K block: raw 256x36 mem_init matrix, wiring evidence (m9kctl + routed M4K_BUFFER outputs), decoded mode bits,
            candidate word decodings at the 9 verified widths, a structural ranking, hex / txt / mif per block, summary.  Read-only on the image
            (path only from the env var; never logged).  The decompressed plane is removed at exit.
crosscheck: the same read path on gxm9k_hb* (MIF) and gxm9k_r* (mem_init) specimens vs their sources; words matched / missing / extra / wrong.
All output is local (tmp/), never committed.  The structural score ranks candidate widths for the image only; the layouts themselves are the
verified vendor-derived maps, not a fit.  Log: tmp/logs/cycloneiv_clean_m9k_dump.log.
"""
import argparse
import json
import logging
import math
import os
import re
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_dump.log")
log = logging.getLogger("m9k_dump")
ENV_IMAGE = "PLURIBUS_DJI_IMAGE"


# ---- pure functions (no vendor data needed) -----------------------------------------------------------------------------------------

def matrix(bitvals):
    """bitvals[p] (mux position) -> uint8 [256, 36] raw mem_init matrix: row r, column c = mem_init bit r * 36 + c."""
    from lifters.cycloneiv_clean import m9k
    bv = np.asarray(bitvals, np.uint8)
    idx = np.arange(256 * 36)
    return bv[m9k.pos_of_index(idx)].reshape(256, 36)


def candidates(bitvals):
    """{width: (words uint8 [depth, width], set_bits_outside_layout)} for the 9 verified widths."""
    from lifters.cycloneiv_clean import m9k
    bv = np.asarray(bitvals, np.uint8)
    out = {}
    for w in m9k.WIDTHS:
        wd, bt = np.divmod(np.arange(m9k.depth(w) * w), w)
        pos = m9k.pos_of_index(m9k.index(w, wd, bt))
        mapped = np.zeros(m9k.CONTENT_BITS, bool)
        mapped[pos] = True
        out[w] = (m9k.read_words(bv, w), int(bv[~mapped].sum()))
    return out


def word_ints(words):
    """uint8 [depth, W] (bit 0 first) -> list of python ints."""
    return [int("".join(str(int(b)) for b in r[::-1]), 2) for r in words]


def byte_stream(words):
    """Candidate byte stream: words concatenated little-endian, ceil(W/8) bytes per word; W < 8 is the bit stream packed LSB first."""
    d, w = words.shape
    if w < 8:
        flat = words.reshape(-1)
        flat = np.pad(flat, (0, (-len(flat)) % 8))
        return np.packbits(flat.reshape(-1, 8), axis=1, bitorder="little").reshape(-1)
    nb = (w + 7) // 8
    pad = np.pad(words, ((0, 0), (0, nb * 8 - w)))
    return np.packbits(pad.reshape(d * nb, 8), axis=1, bitorder="little").reshape(-1)


def _entropy(b):
    if not len(b):
        return 0.0
    p = np.bincount(b, minlength=256) / len(b)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def _ascii_runs(b, minrun=4):
    """Fraction of nonzero bytes inside runs of >= minrun printable ASCII bytes (0x20..0x7e)."""
    pr = (b >= 0x20) & (b <= 0x7E)
    nz = int((b != 0).sum())
    if not nz:
        return 0.0
    run = tot = 0
    for v in np.concatenate([pr, [False]]).tolist():
        if v:
            run += 1
        else:
            if run >= minrun:
                tot += run
            run = 0
    return tot / nz


def structure(words, outside, wire=None):
    """Structural metrics of one candidate decoding, plus consistency with the wiring evidence (`wire`, see `wiring`).  Ranking aid only."""
    vals = np.asarray(word_ints(words), object)
    nzm = np.array([v != 0 for v in vals])
    n_nz = int(nzm.sum())
    b = byte_stream(words)
    nzb = b[b != 0]
    res = {"words": len(vals), "nonzero_words": n_nz, "set_bits": int(words.sum()), "outside_layout": outside,
           "entropy_nonzero_bytes": round(_entropy(nzb), 3), "ascii_run_frac": round(_ascii_runs(b), 3)}
    # repeated-record regularity: best period p (1..64 words) = fraction of nonzero words equal to the word p later
    best = (0.0, 0)
    if n_nz > 4:
        for p in range(1, 65):
            a, c = vals[:-p], vals[p:]
            m = np.array([x != 0 for x in a])
            if m.sum() >= 4:
                f = float(np.mean([x == y for x, y in zip(a[m], c[m])]))
                if f > best[0]:
                    best = (f, p)
    res["repeat_best_frac"], res["repeat_best_period"] = round(best[0], 3), best[1]
    # monotonic table: adjacent nonzero pairs with constant non-negative step / non-decreasing
    nzv = [int(v) for v in vals[nzm]]
    if len(nzv) > 3:
        d = np.diff(np.asarray(nzv, np.float64))
        res["monotonic_frac"] = round(float((d >= 0).mean()), 3)
        res["const_step_frac"] = round(float((d == np.bincount(np.abs(d).astype(np.int64)).argmax()).mean()), 3) if (d >= 0).all() else 0.0
    else:
        res["monotonic_frac"] = res["const_step_frac"] = 0.0
    # zero-run structure: nonzero words as one contiguous span / number of zero runs between populated words
    if n_nz:
        idx = np.flatnonzero(nzm)
        span = int(idx[-1] - idx[0] + 1)
        res["first_nonzero_word"], res["last_nonzero_word"] = int(idx[0]), int(idx[-1])
        res["span_fill"] = round(n_nz / span, 3)
        res["zero_runs_inside_span"] = int((np.diff(idx) > 1).sum())
        # column occupancy: set bits per bit column (a real width leaves the unused upper columns empty)
        col = words.sum(0)
        res["empty_columns"] = int((col == 0).sum())
    else:
        res.update(span_fill=0.0, zero_runs_inside_span=0, empty_columns=words.shape[1])
    if wire is not None:
        # wiring consistency: nonzero words beyond the depth reachable with the wired address pins; non-empty bit columns that no routed output pin carries
        ab = wire["address_bits_wired"]
        if ab:
            nb = int(math.log2(len(vals)))
            idx = np.flatnonzero(nzm)
            # an unwired address pin is a constant: the nonzero words must agree on every unwired address bit
            res["nonzero_words_with_varying_unwired_address_bit"] = int(sum(1 for k in range(nb) if k not in ab and len({(int(w) >> k) & 1 for w in idx}) > 1))
            res["unwired_address_bits"] = [k for k in range(nb) if k not in ab]
        else:
            res["nonzero_words_with_varying_unwired_address_bit"] = None
        outs = set(wire["routed_output_pins"])
        col = words.sum(0)
        w = words.shape[1]
        # output pin c of port A, and pin c + 18 of a second (<= 18 wide) port
        ok_pin = lambda c: c in outs or (w <= 18 and c + 18 in outs)
        res["nonempty_columns_without_output_pin"] = int(sum(1 for c in range(w) if col[c] and not ok_pin(c))) if outs else None
        res["output_pins_beyond_width"] = int(sum(1 for o in outs if o >= w and not (w <= 18 and 18 <= o < 18 + w))) if outs else None
        # source: m9k.py / specimens gxm9k_hb*: RAM_USE_PACKED_MODE is set exactly for the 32 and 36 bit builds (262 specimens, 0 exceptions)
        res["packed_mode_contradiction"] = int(bool(wire["packed_mode"]) != (w >= 32))
    return res


def violations(s):
    """Number of wiring contradictions: set bit lost by the layout, nonzero words disagreeing on an unwired (constant) address bit, non-empty column without a routed
    output pin, routed output pin beyond the width (None = no evidence = no violation)."""
    return int(bool(s["outside_layout"])) + sum(int(bool(s.get(k))) for k in
                                                ("nonzero_words_with_varying_unwired_address_bit", "nonempty_columns_without_output_pin", "output_pins_beyond_width", "packed_mode_contradiction"))


def consistent(s):
    return violations(s) == 0


def composite(s):
    """Ranking score of one decoding (image candidates only): 0 when any set bit falls outside the layout (data would be lost), else the
    sum of ASCII-run fraction, repeat regularity, monotonic regularity and low entropy (1 - H/8)."""
    if s["outside_layout"] or not s["nonzero_words"]:
        return 0.0
    return round(s["ascii_run_frac"] + s["repeat_best_frac"] + 0.5 * s["monotonic_frac"] + (1 - s["entropy_nonzero_bytes"] / 8), 3)


def hexdump(b, per=16):
    lines = []
    for o in range(0, len(b), per):
        ch = b[o:o + per]
        if not ch.any() and o:
            continue
        lines.append(f"{o:05x}  " + " ".join(f"{x:02x}" for x in ch).ljust(per * 3 - 1) + "  |" + "".join(chr(x) if 32 <= x < 127 else "." for x in ch) + "|")
    return "\n".join(lines)


def write_block_files(out, name, words, w, bitvals):
    """<name>.hex ($readmemh words, one per line), .txt (hexdump with ASCII), .mif, .raw36.hex (256 rows x 36 bits, row r = mem_init bits r*36..r*36+35)."""
    nd = (w + 3) // 4
    vals = word_ints(words)
    open(os.path.join(out, name + ".hex"), "w").write("\n".join(f"{v:0{nd}x}" for v in vals) + "\n")
    open(os.path.join(out, name + ".txt"), "w").write(f"# words={len(vals)} width={w} byte stream = words little-endian ({(w + 7) // 8 if w >= 8 else 'bit-packed'})\n" + hexdump(byte_stream(words)) + "\n")
    open(os.path.join(out, name + ".mif"), "w").write(f"WIDTH={w};\nDEPTH={len(vals)};\nADDRESS_RADIX=HEX;\nDATA_RADIX=HEX;\nCONTENT BEGIN\n" +
                                                      "".join(f"{a:X} : {v:0{nd}X};\n" for a, v in enumerate(vals)) + "END;\n")
    m = matrix(bitvals)
    open(os.path.join(out, name + ".raw36.hex"), "w").write("\n".join(f"{int(''.join(str(int(x)) for x in r[::-1]), 2):09x}" for r in m) + "\n")
    open(os.path.join(out, name + ".raw36.bin"), "w").write("\n".join("".join(str(int(x)) for x in r[::-1]) for r in m) + "\n")


# ---- sources for the cross-check ----------------------------------------------------------------------------------------------------

def parse_mif(path, width, depth):
    """Intel MIF -> list of int words (unlisted = 0)."""
    t = open(path).read()
    rad = {k: v for k, v in re.findall(r"(ADDRESS_RADIX|DATA_RADIX)\s*=\s*(\w+)", t)}
    base = {"HEX": 16, "BIN": 2, "DEC": 10, "UNS": 10, "OCT": 8}
    ab, db = base[rad.get("ADDRESS_RADIX", "HEX")], base[rad.get("DATA_RADIX", "HEX")]
    words = [0] * depth
    body = t.split("CONTENT BEGIN", 1)[1].split("END;")[0]
    for m in re.finditer(r"^\s*(?:\[(\w+)\.\.(\w+)\]|(\w+))\s*:\s*(\w+)\s*;", body, re.M):
        a, b = (m[1], m[2]) if m[1] else (m[3], m[3])
        for ad in range(int(a, ab), int(b, ab) + 1):
            words[ad] = int(m[4], db) & ((1 << width) - 1)
    return words


def mem_init_words(top, width):
    """cycloneiv_ram_block mem_init0..4 (WYSIWYG: mem_init bit c = word * W + bit, as in score_m9k_content) -> words."""
    from lifters.cycloneiv_clean import m9k
    t = open(top).read()
    ones = []
    for m in re.finditer(r"\.mem_init(\d)\(2048'h([0-9a-f]+)\)", t):
        v = int(m[2], 16)
        ones += [int(m[1]) * 2048 + b for b in range(2048) if v >> b & 1]
    d = m9k.depth(width)
    words = [0] * d
    for c in ones:
        if c // width < d:
            words[c // width] |= 1 << (c % width)
    return words


def score_words(got, want):
    """matched / missing / extra / wrong over words: equal; wanted nonzero but got zero; wanted zero but got nonzero; both nonzero and differ."""
    r = dict(matched=0, missing=0, extra=0, wrong=0)
    for g, e in zip(got, want):
        if g == e:
            r["matched"] += 1
        elif e and not g:
            r["missing"] += 1
        elif g and not e:
            r["extra"] += 1
        else:
            r["wrong"] += 1
    return r


# ---- pipeline (needs local vendor data) ---------------------------------------------------------------------------------------------

def _ctx():
    from lifters.cycloneiv_clean import emit
    return emit.Ctx()


def wiring(cx, b, mk, i, x, y, ctl):
    """Port wiring evidence for instance i: decoded pin selections + routed M4K_BUFFER outputs + input-mux edges at the tile."""
    from lifters.cycloneiv_clean import names, m9k
    st, rt = cx.st, cx.rt
    e = np.asarray(b.edges, np.int64)
    s, d = st.esrc[e].astype(np.int64), st.edst[e].astype(np.int64)
    outs = sorted({int(rt.element(int(r))[4]) for r in s[cx.enum[s] == names.enum_of("M4K_BUFFER")] if rt.x[r] == x and rt.y[r] == y})
    e_in = [names.enum_of("BLOCK_INPUT_MUX"), names.enum_of("M4K_LEFT_CONTROL_INPUT")]
    n_in = int(((cx.enum[d] == e_in[0]) | (cx.enum[d] == e_in[1])).__and__((rt.x[d] == x) & (rt.y[d] == y)).sum())
    data = [k for k in range(36) if mk["data"][i, k] >= 0]
    wad = [k for k in range(mk["waddr"].shape[1]) if mk["waddr"][i, k] >= 0]
    cls, A = int(mk["cls"][i]), int(mk["A"][i])
    lo = max(A - 9, 0)
    low_pins = [16 - lo + j for j in range(lo) if mk["data"][i, 16 - lo + j] >= 0]
    # exact address bit numbers: waddr slot j = address bit lo + j; data gi 16 - lo + j = address bit j (m9kctl.py, emit._m9k)
    abits = sorted([j for j in range(lo) if mk["data"][i, 16 - lo + j] >= 0] + [lo + j for j in range(9) if mk["waddr"][i, j] >= 0]) if cls >= 0 else None
    return {"packed_mode": ctl["RAM_USE_PACKED_MODE"], "address_bits_wired": abits, "word_width_class": cls, "class_names": ["by1", "by2", "by4", "by8/9", "by16/18", "by32/36"][cls] if cls >= 0 else None,
            "address_bits_from_class": A, "width_from_class_and_data_pins": int(mk["W"][i]),
            "data_pins_wired": data, "data_pin_count": len(data),
            "write_address_slots_wired": wad, "low_address_pins_wired_on_data_gi": low_pins,
            "address_pin_count": len(wad) + len(low_pins), "separate_read_address_groups": int(mk["read_groups"][i]),
            "write_enable_selected": int(mk["we"][i]) >= 0, "clock_line": str(cx.m9kctl.clock_line(mk["clk_fast"][i])),
            "output_register": bool(mk["oreg"][i]),
            "routed_output_pins": outs, "routed_output_count": len(outs),
            "width_from_routed_outputs": (max(outs) + 1) if outs else 0, "programmed_input_mux_edges_at_tile": n_in}


def run_image(out):
    import cycloneiv_decompress as cd
    import heavy_guard
    from lifters.cycloneiv_clean import emit, m9k
    path = os.environ.get(ENV_IMAGE)
    if not path:
        raise SystemExit(f"image path: env {ENV_IMAGE}")
    os.makedirs(out, exist_ok=True)
    plane = os.path.join(out, "_plane.rbf")
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    t0 = time.time()
    try:
        open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))      # read-only on the image
        with heavy_guard.lease(gb, "cyc4_clean_m9k_dump", log):
            cx = emit.Ctx()
            b = emit.Builder(cx, plane, "image")
            nl = b.run()
            log.info("builder done %.0fs; M9K tiles with output edges / routing: %d", time.time() - t0, len(nl.m9k))
            content = cx.m9k_content(b.bits)
            mk = cx.m9kctl.decode(b.bits)
            cols = m9k.columns()
            pop = np.flatnonzero(content.sum(1) > 0)
            from lifters.cycloneiv_clean import m9k_usage
            usage = m9k_usage.summary(m9k_usage.usage(cx, b.bits, b.edges, mk))
            log.info("usage (lifters/cycloneiv_clean/m9k_usage.py): %s", usage)
            res = {"m9k_instances": int(len(content)), "tiles_used_by_emit": len(nl.m9k), "populated_blocks": int(len(pop)),
                   "usage": usage, "content_bits_total": int(content.size), "content_bits_set": int(content.sum()), "blocks": []}
            emitted = {(M["x"], M["y"]): M for M in nl.m9k}
            for i in pop.tolist():
                x, y = cols[i // 90], i % 90 + 1
                name = f"m9k_i{i:03d}_x{x}_y{y}"
                bv = content[i]
                cand = candidates(bv)
                ctl = {n: int(b.bits[c[i]]) for n, c in cx.m9k_ctl.items()}
                wire = wiring(cx, b, mk, i, x, y, ctl)
                st = {w: structure(c[0], c[1], wire) for w, c in cand.items()}
                for w in st:
                    st[w]["composite"] = composite(st[w])
                    st[w]["wiring_consistent"] = consistent(st[w])
                    st[w]["wiring_violations"] = violations(st[w])
                outs = wire["routed_output_pins"]
                target = 18 if outs and max(outs) >= 18 else (max(outs) + 1 if outs else 0)      # tie-break only: width nearest the routed output pins
                ranked = sorted(st, key=lambda w: (st[w]["wiring_violations"], -st[w]["composite"], abs(w - target), w))
                wired_w = wire["width_from_class_and_data_pins"] or None
                top, second = ranked[0], ranked[1]
                row = {"block": name, "instance": i, "column_rank": i // 90, "x": x, "y": y, "row": y, "set_bits": int(bv.sum()),
                       "in_emit_tiles": (x, y) in emitted, "wiring": wire, "mode_bits": ctl,
                       "candidates": {str(w): st[w] for w in m9k.WIDTHS}, "ranking": ranked,
                       "best_width": top, "second_width": second, "best_composite": st[top]["composite"], "second_composite": st[second]["composite"],
                       "wired_width": wired_w, "wired_width_composite": st[wired_w]["composite"] if wired_w in st else None,
                       "wired_width_rank": ranked.index(wired_w) + 1 if wired_w in st else None,
                       "widths_with_no_lost_bits": [w for w in m9k.WIDTHS if st[w]["outside_layout"] == 0],
                       "widths_wiring_consistent": [w for w in m9k.WIDTHS if st[w]["wiring_consistent"]]}
                sigs = {w: np.argwhere(cand[w][0]).tobytes() for w in row["widths_wiring_consistent"]}
                row["consistent_distinct_contents"] = len(set(sigs.values()))
                cls_ok = {"by1": (1,), "by2": (2,), "by4": (4,), "by8/9": (8, 9), "by16/18": (16, 18), "by32/36": (32, 36)}.get(wire["class_names"])
                row["best_width_agrees_with_wired_class"] = None if cls_ok is None else top in cls_ok
                row["evidence"] = ("none consistent" if not sigs else "wiring-unique content" if len(set(sigs.values())) == 1 and len(sigs) == 1 else
                                   "wiring-consistent, equivalent content across widths" if len(set(sigs.values())) == 1 else "wiring-consistent, content differs across widths")
                write_block_files(out, name, cand[top][0], top, bv)
                for w in m9k.WIDTHS:                                    # every candidate, for hand inspection
                    open(os.path.join(out, f"{name}.x{w}.hex"), "w").write("\n".join(f"{v:0{(w + 3) // 4}x}" for v in word_ints(cand[w][0])) + "\n")
                res["blocks"].append(row)
                log.info("%s set=%d best=x%d (%.3f) second=x%d (%.3f) wired=%s", name, row["set_bits"], top, row["best_composite"], second, row["second_composite"], wired_w)
            json.dump(res, open(os.path.join(out, "summary.json"), "w"), indent=1, default=str)
            with open(os.path.join(out, "summary.tsv"), "w") as f:
                f.write("block\tx\ty\tset_bits\tclass\twired_W\taddr_bits\tout_pins\tdata_pins\tbest_W\tbest_score\tsecond_W\tsecond_score\twired_rank\tno_lost_bit_widths\tmode_bits\n")
                for r in res["blocks"]:
                    w = r["wiring"]
                    f.write("\t".join(str(v) for v in (r["block"], r["x"], r["y"], r["set_bits"], w["class_names"], r["wired_width"], w["address_pin_count"],
                                                       w["routed_output_count"], w["data_pin_count"], r["best_width"], r["best_composite"], r["second_width"],
                                                       r["second_composite"], r["wired_width_rank"], ",".join(map(str, r["widths_with_no_lost_bits"])), ",".join(map(str, r["widths_wiring_consistent"])), r["evidence"],
                                                       json.dumps(r["mode_bits"], sort_keys=True))) + "\n")
            # emit overlay: the emitted netlist plus the chosen-layout memory for every populated block that emit left as an undecoded INIT
            v = emit.verilog(nl)
            ov = []
            for r in res["blocks"]:
                x, y, w = r["x"], r["y"], r["best_width"]
                M = emitted.get((x, y))
                tag = f"// UNDECODED: M9K {x},{y} port widths, port wiring, read/write mode"
                if M is not None and not M.get("modelled") and tag in v:
                    n = f"m9k_{x}_{y}"
                    add = (f"{tag}\n// INIT candidate x{w} (structural rank, wired width {r['wired_width']}): not decoded from the port wiring\n"
                           f"reg [{w - 1}:0] {n}_rom [0:{m9k.depth(w) - 1}];\ninitial $readmemh(\"{r['block']}.hex\", {n}_rom);")
                    v = v.replace(tag, add)
                    ov.append(r["block"])
                elif M is not None and M.get("modelled"):
                    ov.append(r["block"] + " (emit already models + inits it)")
            open(os.path.join(out, "emit_with_init.v"), "w").write(v)
            res["emit_overlay_blocks"] = ov
            json.dump(res, open(os.path.join(out, "summary.json"), "w"), indent=1, default=str)
            print(json.dumps({k: res[k] for k in res if k != "blocks"}))
            return res
    finally:
        if os.path.exists(plane):
            os.remove(plane)


def run_crosscheck(out):
    import heavy_guard
    from lifters.cycloneiv_clean import m9k
    os.makedirs(out, exist_ok=True)
    names_ = sorted(n for n in os.listdir(CORPUS) if re.match(r"gxm9k_(hb(1|2|4|8|9|16|18|32|36)_(base|k\d+)|r(1|2|4|8|9|16|18)(_x\d+_y\d+_n0)?_s\d+)$", n)
                    and os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf")))
    if not names_:
        raise SystemExit("no gxm9k_hb* / gxm9k_r* specimens in corpus/cycloneiv")
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0, nonzero_words_wanted=0)
    wtot = dict(matched=0, wrong=0, missing=0)
    with heavy_guard.lease(gb, "cyc4_clean_m9k_crosscheck", log):
        cx = _ctx()
        for n in names_:
            d = os.path.join(CORPUS, n)
            m = re.match(r"gxm9k_(?:hb|r)(\d+)", n)
            w = int(m[1])
            toml = open(os.path.join(d, "design.toml")).read()
            loc = re.search(r"M9K_X(\d+)_Y(\d+)_N0", toml)
            x, y = (int(loc[1]), int(loc[2])) if loc else (23, 40)
            i = m9k.instance(x, y)
            src_mif = os.path.join(d, "src", "init.mif")
            if os.path.exists(src_mif):
                want = parse_mif(src_mif, w, m9k.depth(w))
                kind = "mif"
            else:
                want = mem_init_words(os.path.join(d, "src", "top.v"), w)
                kind = "mem_init"
            bits = cx.T.plane_bits(os.path.join(d, "bitstream.rbf"))
            bv = cx.m9k_content(bits)[i]
            got = word_ints(m9k.read_words(bv, w))
            r = score_words(got, want)
            r["nonzero_words_wanted"] = sum(1 for e in want if e)
            mk = cx.m9kctl.decode(bits)
            wired = int(mk["W"][i])
            wl = "matched" if wired == w else ("missing" if wired == 0 else "wrong")
            if w in (1, 2, 4, 8, 9, 16, 18):
                wtot[wl] += 1
            ctlv = {k: int(bits[c[i]]) for k, c in cx.m9k_ctl.items()}
            rows.append(dict(build=n, width=w, source=kind, x=x, y=y, wired_width=wired, cls=int(mk["cls"][i]), n_data=int(mk["n_data"][i]),
                             packed_mode=ctlv["RAM_USE_PACKED_MODE"], tdp_mode=ctlv["RAM_USE_TRUE_DUAL_PORT_MODE"], **r))
            for k in tot:
                tot[k] += r[k]
        log.info("crosscheck specimens=%d words %s", len(rows), tot)
    by_w = {}
    for r in rows:
        a = by_w.setdefault(r["width"], dict(specimens=0))
        a["specimens"] += 1
        for k in ("matched", "missing", "extra", "wrong", "nonzero_words_wanted"):
            a[k] = a.get(k, 0) + r[k]
    res = {"specimens": len(rows), "words": tot, "by_width": dict(sorted(by_w.items())), "wired_width_vs_design_width": wtot,
           "specimens_with_any_wrong_or_missing_or_extra": sum(1 for r in rows if r["missing"] or r["extra"] or r["wrong"])}
    json.dump({"summary": res, "rows": rows}, open(os.path.join(out, "crosscheck.json"), "w"), indent=1)
    print(json.dumps(res))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("image", "crosscheck"))
    ap.add_argument("--out", default=os.path.join(REPO, "tmp", "m9k_dump"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "a")])
    (run_image if a.mode == "image" else run_crosscheck)(a.out)


if __name__ == "__main__":
    main()
