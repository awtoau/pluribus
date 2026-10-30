#!/usr/bin/env python3.15t
"""Run the clean Cyclone IV pipeline (lifters/cycloneiv_clean, #165) on an EP4CGX150 compressed image.  Counts only; no ground truth.

  python3.15t scripts/cycloneiv_clean_image.py IMAGE        (or env PLURIBUS_DJI_IMAGE)
Read-only on IMAGE.  The decompressed plane is a derived file in tmp/cycloneiv_clean/image_plane.rbf, removed at exit (--keep to retain).
Sections: container + integrity, decode (routing / LUT / FF / clock / block / IO / options), sanity statistics.
Unresolved or ambiguous items are counted as missing, never guessed.  Log tmp/logs/cycloneiv_clean_image.log, results tmp/cycloneiv_clean/image.json.
"""
import argparse
import collections
import json
import logging
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

log = logging.getLogger("cycloneiv_clean_image")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_image.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
PLANE = os.path.join(OUT, "image_plane.rbf")
RESULT = os.path.join(OUT, "image.json")
DEVICE_LES = 149_760                    # source: docs/cycloneiv-bitstream.md EP4CGX150 (9,360 LABs x 16)
GEOM = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")
CORPUS_REF = os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_000", "bitstream.rbf")


def container(data):
    """Decompress to the quartus_cpf rbf layout; header facts and frame CRC counts."""
    import cycloneiv_decompress as cd
    info = {}
    rbf = cd.decompress(data, info)
    s, f, r = cd.PREAMBLE, info["frame"], info["periphery_frames"]
    ok = cd.frames_ok_np(rbf, s + r * f, f)
    lanes = [int(x, 16) for x in cd.parse(rbf)["lanes"]]
    res = {"input_bytes": len(data), "compressed": bool(info["compressed"]), "frame_bytes": f, "periphery_frames": r,
           "header_crc_ok": bool(cd.hdr_crc_ok(rbf, s)), "cram_frames_walked": int(info["cram_frames"]),
           "cram_frame_crc_pass": int(ok[:info["cram_frames"]].sum()), "cram_frame_crc_total": int(info["cram_frames"]),
           "frames_after_chain_valid": int(ok[info["cram_frames"]:].sum()), "decompressed_bytes": len(rbf),
           "bits_per_frame": info["bits_per_frame"], "cram_bits": info["cram_bits"],
           "leftover_nibbles": info.get("leftover_nibbles"), "lane_set_bits": [bin(x).count("1") for x in lanes]}
    return rbf, res, lanes


def option_bits(lanes):
    """Header option lanes vs the Quartus-built reference rbf (container flag / length / CRC already normalised by decompress)."""
    import cycloneiv_decompress as cd
    out = {"decoded_fields": 0, "note": "option-bit meaning not decoded (no docs/cycloneiv-clean-options.md): all MISSING"}
    if not os.path.exists(CORPUS_REF):
        out["reference"] = "absent"
        return out
    ref = [int(x, 16) for x in cd.parse(open(CORPUS_REF, "rb").read())["lanes"]]
    out["bits_differing_from_reference_build"] = sum(bin(a ^ b).count("1") for a, b in zip(lanes, ref))
    out["lanes_differing"] = [i for i, (a, b) in enumerate(zip(lanes, ref)) if a != b]
    out["bits_total"] = 8 * 40
    return out


class Ctx:
    """Read-only pipeline state (same construction as the gate)."""

    def __init__(self):
        from lifters.cycloneiv_clean import ddb, names
        from lifters.cycloneiv_clean import tracer as T
        t0 = time.time()
        self.T, self.names = T, names
        self.rt = ddb.Routing()
        self.st = T.Static()
        self.lut = T.Lut()
        self.ext = T.Extras(self.st, self.lut, self.rt)
        self.io = T.Io()
        self.enum = np.where(self.rt.tpl >= 0, self.rt.enum[np.maximum(self.rt.tpl, 0)].astype(np.int32), -1)
        self.tname = {v: k for k, v in names.enums().items()}
        log.info("context ready in %.1fs", time.time() - t0)

    def tn(self, rec):
        return self.tname.get(int(self.enum[rec]), str(int(self.enum[rec])))


def routing(cx, bits):
    st, T = cx.st, cx.T
    fired = cx.ext.apply(bits, st.fire(bits, workers=4))
    ed = st.edst.astype(np.int64)
    indeg_graph = np.bincount(ed, minlength=cx.rt.n)       # in-degree over the whole routing graph (+ appended implicit edges)
    res = {"edge_universe": int(st.n_edges), "variants": {}}
    for v, e in fired.items():
        e = np.asarray(e)
        d = ed[e]
        cnt = np.bincount(d)
        multi = np.flatnonzero(cnt > 1)
        res["variants"][v] = {"programmed_edges": int(len(e)), "dst_nodes": int((cnt > 0).sum()),
                              "fanin_conflict_nodes": int(len(multi)), "fanin_conflict_edges": int(cnt[multi].sum())}
    e = np.asarray(fired[T.HEADLINE_VARIANT])
    res["headline_variant"] = T.HEADLINE_VARIANT
    s, d = st.esrc[e].astype(np.int64), ed[e]
    g = T.Graph(st, e)
    roots = g.roots()
    nodes = np.unique(np.concatenate([s, d]))
    res["used_nodes"] = int(len(nodes))
    res["nets_roots"] = len(roots)
    # undriven used node = programmed-edge source with no programmed parent although the routing graph gives it a driver
    undriven = [r for r in roots if indeg_graph[r] > 0]
    res["undriven_used_nodes"] = len(undriven)
    res["undriven_by_type"] = dict(collections.Counter(cx.tn(r) for r in undriven).most_common(12))
    res["source_roots_by_type"] = dict(collections.Counter(cx.tn(r) for r in roots if indeg_graph[r] == 0).most_common(12))
    bt = collections.Counter()
    for t, c in zip(*np.unique(cx.enum[d], return_counts=True)):
        bt[cx.tname.get(int(t), str(int(t)))] = int(c)
    res["edges_by_dst_type"] = dict(bt.most_common())
    # loops: strongly connected components of the programmed graph
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    idx = {int(n): i for i, n in enumerate(nodes)}
    a = np.searchsorted(nodes, s)
    b = np.searchsorted(nodes, d)
    m = coo_matrix((np.ones(len(a), np.int8), (a, b)), shape=(len(nodes), len(nodes))).tocsr()
    ncomp, lab = connected_components(m, directed=True, connection="strong")
    sizes = np.bincount(lab)
    selfloop = int((a == b).sum())
    res["loops"] = {"scc_gt1": int((sizes > 1).sum()), "nodes_in_scc_gt1": int(sizes[sizes > 1].sum()), "self_loop_edges": selfloop,
                    "largest_scc": int(sizes.max())}
    del idx
    return res, fired, g


def blocks(cx, fired_head):
    st = cx.st
    geom = json.load(open(GEOM))
    kind = {int(k): v for k, v in geom["col_kind"].items()}
    e = np.asarray(fired_head)
    d, s = st.edst[e].astype(np.int64), st.esrc[e].astype(np.int64)
    ein = [cx.names.enum_of(t) for t in ("BLOCK_INPUT_MUX", "M4K_LEFT_CONTROL_INPUT")]
    eout = cx.names.enum_of("M4K_BUFFER")
    out = {"input_edges_by_column_kind": {}, "output_edges_by_column_kind": {}}
    for arr, enums, key in ((d, ein, "input_edges_by_column_kind"), (s, [eout], "output_edges_by_column_kind")):
        sel = np.flatnonzero(np.isin(cx.enum[arr], enums))
        c, tiles = collections.Counter(), collections.defaultdict(set)
        for i in sel.tolist():
            r = int(arr[i])
            k = kind.get(int(cx.rt.x[r]), "none")
            c[k] += 1
            tiles[k].add((int(cx.rt.x[r]), int(cx.rt.y[r])))
        out[key] = {k: {"edges": c[k], "tiles": len(tiles[k])} for k in c}
    out["note"] = "usage by routed edges only; M9K/MAC mode, width, init and coefficients not decoded: MISSING"
    return out


def logic(cx, bits, fired_head, g):
    lut, st, T = cx.lut, cx.st, cx.T
    cells = lut.cells(bits).astype(np.uint8)
    nz = cells.sum(axis=2) > 0
    full = cells.sum(axis=2) == 16
    carry = lut.carry_in(bits)
    ff = cx.ext.reg.ff(bits, fired_head)
    used_buf = cx.ext.reg.used(fired_head).any(axis=2)
    lab_active = nz.any(axis=1)
    res = {"device_les": DEVICE_LES, "luts_nonzero_init": int(nz.sum()), "luts_all_ones_init": int(full.sum()),
           "luts_carry_in_flag_among_nonzero": int((carry & nz).sum()), "les_with_used_buffer": int(used_buf.sum()),
           "les_ff_claimed": int(ff.sum()), "labs_with_lut": int(lab_active.sum()), "labs_total": int(len(lab_active)),
           "impossible_luts": bool(nz.sum() > DEVICE_LES), "impossible_ffs": bool(ff.sum() > DEVICE_LES),
           "ff_without_lut_and_buffer": int((ff & ~nz & ~used_buf).sum())}
    # register clock: line chosen per (LAB, LE); root(s) of the programmed tree(s) that contain it, found upstream
    blk = np.where(ff, cx.ext.clocks.le_blk(bits), -1)
    res["ff_clock_line_chosen"] = int((blk >= 0).sum())
    res["ff_no_clock_line_MISSING"] = int(ff.sum() - (blk >= 0).sum())
    src, dst = st.esrc[fired_head].astype(np.int64), st.edst[fired_head].astype(np.int64)
    o = np.argsort(dst, kind="stable")
    ds, ss = dst[o], src[o]
    lo_hi = {}

    def parents(n):
        i = np.searchsorted(ds, n, "left")
        j = np.searchsorted(ds, n, "right")
        return ss[i:j].tolist()

    def roots_of(n):
        if n in lo_hi:
            return lo_hi[n]
        seen, stack, rts = {n}, [n], set()
        while stack:
            x = stack.pop()
            ps = parents(x)
            if not ps:
                rts.add(x)
            for p in ps:
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        lo_hi[n] = rts
        return rts

    distinct = np.unique(blk[blk >= 0])
    one, many, none = {}, 0, 0
    for r in distinct.tolist():
        rts = roots_of(r)
        if len(rts) == 1:
            one[r] = next(iter(rts))
        elif not rts or rts == {r}:
            none += 1                           # the line itself has no programmed driver
        else:
            many += 1
    cnt = collections.Counter()
    for r in blk[blk >= 0].tolist():
        cnt["resolved" if r in one else "other"] += 1
    res["clock_lines_distinct"] = int(len(distinct))
    res["clock_lines_one_root"] = len(one)
    res["clock_lines_ambiguous_roots_MISSING"] = many
    res["clock_lines_undriven_MISSING"] = none
    res["ff_clock_one_root"] = cnt["resolved"]
    res["ff_clock_unresolved_MISSING"] = cnt["other"] + res["ff_no_clock_line_MISSING"]
    res["clock_root_nets_distinct"] = len(set(one.values()))
    res["clock_root_types"] = dict(collections.Counter(cx.tn(r) for r in set(one.values())).most_common(8))
    return res


def io_fields(cx, plane_path, bits, val, detail_path=None):
    """Full per-site field decode (lifters/cycloneiv_clean/io_fields.py): every IO site of the chain -> class + fields; counts only in the result,
    the per-site table (ball, direction, standard, drive, slew, pull, termination, raw patterns) goes to detail_path (local, not committed)."""
    from lifters.cycloneiv_clean import io_decode as ID
    from lifters.cycloneiv_clean import io_fields as IF
    from lifters.cycloneiv_clean import plane as PL
    table = json.load(open(ID.DECODE_PATH))
    dec = IF.Decoder(table)
    chain = cx.io.chain
    cram_names = sorted({e["group"] for e in table["cram_values"]})

    def cram_of(site):
        out = {}
        for n in cram_names:
            a = chain.cram.get(site, {}).get(n)
            if a:
                r, j, k = PL.address_to_plane(np.asarray(a, np.int64))
                out[n] = "".join(str(int(b)) for b in bits[np.asarray(r) * PL.BITS_PER_FRAME + (np.asarray(j) - 1) * 8 + np.asarray(k)])
        return out
    rows, cnt = [], collections.Counter()
    fields = collections.defaultdict(collections.Counter)
    for site in sorted(chain.cff):
        vec = ID.site_vector(chain, val, site)
        d = dec.decode(site, vec, cram_of(site))
        d["ball"] = cx.io.site_ball.get(site)
        rows.append(d)
        cnt[d["class"]] += 1
        if d["class"] == "used":
            for f in ("direction", "standard", "drive", "slew", "pull-up", "bus-hold", "termination", "open-drain",
                      "registered-input", "registered-output", "registered-oe"):
                fields[f][d[f]["status"]] += 1
            cnt["used_" + d["direction"].get("value", "ambiguous")] += 1
        elif d["class"] == "unused":
            cnt["unused_" + "+".join(d["unused_options"])] += 1
    miss = [r for r in rows if r["class"] == "MISSING"]
    res = {"sites": len(rows), "classes": dict(cnt), "used_field_status": {k: dict(v) for k, v in sorted(fields.items())},
           "missing_sites": len(miss), "missing_distinct_raw_vectors": len({json.dumps(r["raw"], sort_keys=True) for r in miss}),
           "sites_with_ball": sum(1 for r in rows if r["ball"]), "used_with_ball": sum(1 for r in rows if r["class"] == "used" and r["ball"])}
    if detail_path:
        json.dump(rows, open(detail_path, "w"), indent=0, default=str)
    return res


def io_sites(cx, plane_path, bits=None):
    val, disagree = cx.io.cff.read(plane_path)
    cl = cx.io.classify(plane_path)
    res = {"cff_bits": int(len(val)), "cff_bits_set": int(val.sum()), "cff_primary_replica_disagreements": disagree,
           "sites_in_chain": len(cx.io.chain.cff), "sites_classified_default_pattern": len(cl)}
    kinds = collections.Counter()
    balls = 0
    for site, ks in cl.items():
        balls += cx.io.site_ball.get(site) is not None
        kinds["/".join(sorted(ks))] += 1
    res["classified_with_ball"] = balls
    res["classified_kinds"] = dict(kinds.most_common())
    # sites with any set CFF bit in their key groups that match no decoded pattern: unresolved = MISSING
    keyset = {}
    for site, grp in cx.io.chain.cff.items():
        bs = [a for g in cx.T.IO_KEY_GROUPS for a in grp.get(g, [])]
        keyset[site] = bs
    touched = {s for s, bs in keyset.items() if bs and any(val[a] for a in bs)}
    res["sites_with_set_key_bits"] = len(touched)
    res["sites_set_but_unclassified_MISSING"] = len(touched - set(cl))
    res["sites_balls_total"] = len([s for s in cx.io.site_ball])
    # field decode: exact pattern match of each value row against the site's group bits.  A value counts only if its rows differ from the
    # default pattern of that base kind; unique such value = decoded, none and all rows equal default = "default", else MISSING.
    t = json.load(open(os.path.join(REPO, "databases", "cycloneiv", "io_decode.json")))
    rows, dflt = collections.defaultdict(list), {}
    for v in t["values"]:
        if v["setting"] == "default":
            dflt[(v["base_kind"], v["group"])] = v["pattern"]
        else:
            rows[(v["setting"], v["base_kind"], v["value"])].append(v)

    def read(grp, r):
        b = grp.get(r["group"], [])
        return "".join(str(int(val[a])) for a in b) if len(b) == r["n_elem"] else None

    fields = collections.defaultdict(collections.Counter)
    for site, ks in cl.items():
        grp = cx.io.chain.cff[site]
        for setting in sorted({k[0] for k in rows}):
            hits, groups_eq_default, applicable = set(), True, False
            for (st_, bk, value), rs in rows.items():
                if st_ != setting or bk not in ks:
                    continue
                applicable = True
                groups_eq_default &= all(read(grp, r) == dflt.get((bk, r["group"])) for r in rs)
                if all(read(grp, r) == r["pattern"] for r in rs) and any(r["pattern"] != dflt.get((bk, r["group"])) for r in rs):
                    hits.add(value)
            if not applicable:
                fields[setting]["not_applicable_to_kind"] += 1
            elif len(hits) == 1:
                fields[setting]["decoded_non_default"] += 1
            elif hits:
                fields[setting]["ambiguous_MISSING"] += 1
            elif groups_eq_default:
                fields[setting]["default"] += 1
            else:
                fields[setting]["no_value_matches_MISSING"] += 1
    res["field_decode"] = {k: dict(v) for k, v in sorted(fields.items())}
    if bits is not None:
        res["fields"] = io_fields(cx, plane_path, bits, val, os.path.join(OUT, "image_io_table.json") if plane_path == PLANE else None)
    res["pin_mapped_sites"] = f"{balls} of {len(cl)} classified sites map to a package ball (pad -> pin via the vendor package table)"
    return res


def hardblocks(cx, plane_path):
    """PLL (CFF), M9K content / control, MAC control: counts only (#169).  Undecoded = MISSING."""
    from lifters.cycloneiv_clean import asmdb_walk as W, fields as F, m9k, mac, pll, plane as P
    import cycloneiv_clean_dirt as D
    w = W.Walk()
    flds = F.fields(w, D.enum_tables())
    tab = P.load_tables()
    bits = cx.T.plane_bits(plane_path)
    res = {}
    cff = cx.io.cff.read(plane_path)[0]
    pm = pll.PllMap(flds)
    used = pm.used(cff)
    res["pll"] = {"enabled": len(used), "sites_decoded": [k for k, _, _ in used],
                  "params": {f"PLL_{k}": {kk: (list(v) if isinstance(v, tuple) else v) for kk, v in pm.params(cff, bt, p).items()} for k, bt, p in used},
                  "other_enabled_paths_MISSING": sum(1 for (bt, nm, gi), ps in pm.g.items() if nm == "PLL_ENABLE_PLL" for i, pa in enumerate(ps)
                                                      if pa is not None and (bt, i) not in pll.PLL_SITE.values() and cff[pa[0]])}

    def cell(a):
        r, j, k = P.sof_to_rbf(a.ravel(), tab)
        return (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)
    off = m9k.content_offsets(flds)
    cc = cell(F.absolute(F.bases(w, 39), off))
    v = bits[cc]
    per = v.sum(1)
    ctl = collections.Counter()
    for f in flds:
        if f.btype == 39 and f.name in ("RAM_USE_TRUE_DUAL_PORT_MODE", "RAM_USE_PACKED_MODE", "RAM_REG_DATA_OUT", "RAM_REG_DATA_OUT_B", "RAM_NEW_DATA_MODE"):
            c = cell(F.absolute(F.bases(w, 39), np.asarray(f.sites[0][0], np.int64)))
            ctl[f.name] = int(bits[c].any(axis=1).sum())
    res["m9k"] = {"instances": int(len(per)), "content_bits": int(v.size), "content_bits_set": int(per.sum()), "instances_with_content": int((per > 0).sum()),
                  "instances_with_any_control": ctl.most_common() and dict(ctl), "content_unmapped_MISSING": 0}
    ma = 0
    mc = 0
    mflds = [f for f in flds if f.btype == 41 and not f.name.startswith(("MAC_ROW_DATA_INPUT", "MAC_PIA_"))]
    anyset = np.zeros(len(F.bases(w, 41)), bool)
    for f in mflds:
        for site in f.sites:
            for o in site:
                anyset |= bits[cell(F.absolute(F.bases(w, 41), o))].any(axis=1)
    res["mac"] = {"instances": int(len(anyset)), "instances_with_set_control_bits": int(anyset.sum()), "mode_decode": "MISSING (unsigned / 9-bit / registers decoded only as signature bits)"}
    return res


def analyse(cx, path):
    bits = cx.T.plane_bits(path)
    res = {"set_cram_bits": int(bits.sum())}
    r, fired, g = routing(cx, bits)
    res["routing"] = r
    head = np.asarray(fired[cx.T.HEADLINE_VARIANT])
    res["logic"] = logic(cx, bits, head, g)
    res["blocks"] = blocks(cx, head)
    res["io"] = io_sites(cx, path, bits)
    res["hardblocks"] = hardblocks(cx, path)
    return res


CONTROL_KEYS = (("routing", "variants"), ("routing", "undriven_used_nodes"), ("routing", "nets_roots"), ("routing", "loops"),
                ("logic", "luts_nonzero_init"), ("logic", "les_ff_claimed"), ("logic", "ff_clock_unresolved_MISSING"))


def run(image, control, keep=False):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    data = open(image, "rb").read()                       # read-only
    rbf, c, lanes = container(data)
    del data
    c["cram_bits"] = 39_040_976                           # plane geometry (A6); the decompress info counts the pad byte
    log.info("container %s", c)
    res = {"container": c, "options": option_bits(lanes)}
    log.info("options %s", res["options"])
    open(PLANE, "wb").write(rbf)
    try:
        return _analyse_all(cx_args=(c, res, control), t0=t0)
    finally:
        if not keep and os.path.exists(PLANE):
            os.remove(PLANE)


def _analyse_all(cx_args, t0):
    c, res, control = cx_args
    import heavy_guard
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_clean_image", log):
        cx = Ctx()
        res.update(analyse(cx, PLANE))
        for k in ("routing", "logic", "blocks", "io", "hardblocks"):
            log.info("%s %s", k, json.dumps(res[k]))
        res["control"] = {}
        for i in range(control):
            p = os.path.join(REPO, "corpus", "cycloneiv", f"gx150_rb_{i:03d}", "bitstream.rbf")
            if os.path.exists(p):
                a = analyse(cx, p)
                res["control"][f"quartus_built_{i}"] = {"_".join(k): a[k[0]][k[1]] for k in CONTROL_KEYS}
                log.info("control %d %s", i, json.dumps(res["control"][f"quartus_built_{i}"]))
    res["seconds"] = round(time.time() - t0, 1)
    json.dump(res, open(RESULT, "w"), indent=1, default=str)
    log.info("wrote %s (%.0fs)", RESULT, res["seconds"])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=os.environ.get("PLURIBUS_DJI_IMAGE"))
    ap.add_argument("--control", type=int, default=3, help="also run the sanity statistics on this many Quartus-built corpus designs (rb_000..)")
    ap.add_argument("--keep", action="store_true", help="keep the derived decompressed plane in tmp/")
    a = ap.parse_args()
    if not a.image:
        raise SystemExit("image path: argument or PLURIBUS_DJI_IMAGE")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "w")])
    run(a.image, a.control, a.keep)


if __name__ == "__main__":
    main()
