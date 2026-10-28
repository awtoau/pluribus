#!/usr/bin/env python3.15t
"""Native Cyclone V decoder verification stages (docs/cyclonev-native-decoder.md).

  account   claimed / unclaimed set bits + frame CRC/EDCRC verification per design (claim 3)
  routes    per-pip / per-net routing vs RCF; element-type map learned on split A, scored on A (in-sample) and B (held out)
  diff      native vs a fresh mistral-cv decomp, per design, line-set diff (compat mode must be 0; default mode classified)
Log: tmp/logs/cyclonev_native_verify.log   Results: tmp/cyclonev_native/results/<stage>.json
"""
import argparse
import collections
import concurrent.futures
import json
import logging
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_account as acc  # noqa: E402
import numpy as np  # noqa: E402
import cyclonev_decode as cd  # noqa: E402
import cyclonev_native_logic as lg  # noqa: E402
import cyclonev_native_lutmap as lm  # noqa: E402
import cyclonev_native_oracle as orc  # noqa: E402
import cyclonev_native_tables as nt  # noqa: E402
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

DEVICE = "5CEBA4U19C8"
WORK = os.path.join(REPO, "tmp", "cyclonev_native")
RES = os.path.join(WORK, "results")
log = logging.getLogger("cyclonev_native_verify")
# mistral-cv decomp of a 2 MB rbf: 1.4-2.7 s measured 2026-10-24 (docs/cyclonev-postfit-oracle.md); limit 15 s.
DECOMP_LIMIT_S = 15


def corpus_root():
    for c in (os.path.join(REPO, "corpus", "cyclonev"), "/mnt/2tb/git/pluribus/corpus/cyclonev"):
        if os.path.exists(os.path.join(c, "adder12", "bitstream.rbf")):
            return c
    raise SystemExit("no corpus outputs found")


def designs(root, only=None):
    names = sorted(d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, "bitstream.rbf")))
    return [n for n in names if not only or n in only]


def mistral_bt(rbf, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import heavy_guard
    r = heavy_guard.guarded([toolchain.mistral_cv(), "decomp", DEVICE, rbf, out], "mistral-cv",
                            overall_s=DECOMP_LIMIT_S)  # #122
    if r.timed_out:
        raise RuntimeError(f"mistral-cv decomp exceeded {DECOMP_LIMIT_S}s on {rbf}")
    if r.returncode:
        raise RuntimeError(f"mistral-cv rc={r.returncode}: {r.stderr[-300:]}")
    return r.stderr


def linesets(lines):
    d = collections.defaultdict(set)
    for l in lines:
        if l:
            d[l[0]].add(l)
    return d


def read_lines(path):
    return open(path).read().split("\n")


def diff_one(args):
    name, root, tables = args
    rbf = os.path.join(root, name, "bitstream.rbf")
    od = os.path.join(WORK, name)
    os.makedirs(od, exist_ok=True)
    mistral_bt(rbf, os.path.join(od, "mistral.bt"))
    ml = linesets(read_lines(os.path.join(od, "mistral.bt")))
    data = open(rbf, "rb").read()
    out = {"design": name}
    for mode in ("compat", "native"):
        m = cd.decode(data, DEVICE, overrides=(mode == "native"), compat=(mode == "compat"), tables=tables)
        L = m.bt_lines()
        open(os.path.join(od, f"{mode}.bt"), "w").write("\n".join(L) + "\n")
        nl = linesets(L)
        res = {}
        for k in sorted(set(nl) | set(ml)):
            oa, ob = nl.get(k, set()) - ml.get(k, set()), ml.get(k, set()) - nl.get(k, set())
            res[k] = {"native": len(nl.get(k, ())), "mistral": len(ml.get(k, ())), "only_native": sorted(oa),
                      "only_mistral": sorted(ob)}
        out[mode] = res
        out[mode + "_unresolved"] = len(m.route_unknown)
    return out


def stage_diff(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    log.info("diff: %d designs from %s", len(names), root)
    results = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(diff_one, [(n, root, tables) for n in names]):
            results.append(r)
            bad = {m: sum(len(v["only_native"]) + len(v["only_mistral"]) for v in r[m].values()) for m in ("compat", "native")}
            log.info("%-28s compat_diff=%d native_diff=%d", r["design"], bad["compat"], bad["native"])
    os.makedirs(RES, exist_ok=True)
    json.dump(results, open(os.path.join(RES, "diff.json"), "w"))
    tot = {m: collections.Counter() for m in ("compat", "native")}
    for r in results:
        for m in tot:
            for k, v in r[m].items():
                tot[m][k + ":native"] += v["native"]
                tot[m][k + ":mistral"] += v["mistral"]
                tot[m][k + ":only_native"] += len(v["only_native"])
                tot[m][k + ":only_mistral"] += len(v["only_mistral"])
    for m in tot:
        log.info("TOTAL %s: %s", m, dict(sorted(tot[m].items())))
    log.info("diff done in %.0fs", time.time() - t0)


def account_one(args):
    name, root, tables = args
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    m = cd.decode(data, DEVICE, overrides=True, claims=True, tables=tables)
    m.bt_lines()
    r = acc.account(m, data)
    r["design"] = name
    return r


def stage_account(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    res = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(account_one, [(n, root, tables) for n in names]):
            res.append(r)
            c, f = r["cram"], r["frames"]
            log.info("%-28s cram set=%d unclaimed=%d | crc16 %d/%d edcrc %d/%d | oram unclaimed=%d", r["design"], c["set"],
                     c["set_unclaimed"], f["crc16_ok"], f["frames"], f["edcrc_ok"], f["frames"], r["oram"]["set_unclaimed"])
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "account.json"), "w"))
    log.info("account done in %.0fs", time.time() - t0)


def routes_prep(args):
    name, root, tables, bid = args
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    m = cd.decode(data, DEVICE, overrides=True, tables=tables)
    links = m.routes()
    conn = orc.connect()
    rcf = orc.load_rcf(conn, bid)
    conn.close()
    st, tot, cc = orc.type_stats(m, tables, rcf, links)
    return name, links, rcf, (st, tot, cc), None


def stage_routes(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    conn = orc.connect()
    bids = dict(conn.execute("select design, id from corpus_builds"))
    conn.close()
    prep = {}
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for name, links, rcf, st, tot in ex.map(routes_prep, [(n, root, tables, bids[n]) for n in names]):
            prep[name] = (links, rcf, st, tot)
    split = {n: orc.split_of(n) for n in names}
    log.info("split A=%d B=%d designs", sum(1 for v in split.values() if v == "A"), sum(1 for v in split.values() if v == "B"))
    tmapA = orc.learn_type_map([prep[n][2] for n in names if split[n] == "A"])
    tmapAll = orc.learn_type_map([prep[n][2] for n in names])
    log.info("type map learned on A: %s", dict(sorted(tmapA.items())))
    log.info("type map learned on all differs from A: %s", {k: (tmapA.get(k), tmapAll.get(k)) for k in set(tmapA) | set(tmapAll) if tmapA.get(k) != tmapAll.get(k)})
    out = {"tmapA": tmapA, "tmapAll": tmapAll, "designs": {}}
    agg = {k: collections.Counter() for k in ("A", "B", "all")}
    for n in names:
        links, rcf, _, _ = prep[n]
        c, det = orc.score_routes(tables, tmapA, rcf, links)
        out["designs"][n] = {"split": split[n], "counts": dict(c), "missing": det["missing"][:20],
                             "wrong": det["wrong"][:20], "extra": det["extra"][:20]}
        agg[split[n]].update(c)
        agg["all"].update(c)
    for k, c in agg.items():
        log.info("routes[%s] %s headline=%.4f", k, {a: b for a, b in c.items() if not a.startswith("unmapped_type")}, orc.headline(c))
    log.info("unmapped RCF element types (all): %s", {a[14:]: b for a, b in agg["all"].most_common() if a.startswith("unmapped_type")})
    os.makedirs(RES, exist_ok=True)
    json.dump(out, open(os.path.join(RES, "routes.json"), "w"))


def logic_one(args):
    name, root, tables, bid, overrides = args
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    m = cd.decode(data, DEVICE, overrides=overrides, tables=tables)
    links = m.routes()
    conn = orc.connect()
    atoms, by_atom = lg.load_build(conn, bid)
    conn.close()
    t = lg.Tally()
    lg.score_logic(m, tables, atoms, by_atom, links, t)
    return name, {f: dict(c) for f, c in t.c.items()}, dict(t.detail)


def stage_logic(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    conn = orc.connect()
    bids = dict(conn.execute("select design, id from corpus_builds"))
    conn.close()
    agg = {k: collections.defaultdict(collections.Counter) for k in ("A", "B", "all")}
    details = collections.defaultdict(list)
    per = {}
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for name, cnt, det in ex.map(logic_one, [(n, root, tables, bids[n], not a.no_overrides) for n in names]):
            per[name] = cnt
            sp = orc.split_of(name)
            for f, c in cnt.items():
                agg[sp][f].update(c)
                agg["all"][f].update(c)
            for f, d in det.items():
                for x in d:
                    if len(details[f]) < 25:
                        details[f].append((name,) + tuple(x))
    for grp in ("all", "A", "B"):
        for f, c in sorted(agg[grp].items()):
            log.info("logic[%s] %-28s %s headline=%.4f", grp, f, dict(c), lg.headline(c))
    os.makedirs(RES, exist_ok=True)
    json.dump({"agg": {g: {f: dict(c) for f, c in v.items()} for g, v in agg.items()}, "details": details, "per": per},
              open(os.path.join(RES, "logic_nooverride.json" if a.no_overrides else "logic.json"), "w"), default=str)


def lutsamples_one(args):
    name, root, tables, bid = args
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    m = cd.decode(data, DEVICE, overrides=True, tables=tables)
    S = lg.settings_index(m.settings())
    conn = orc.connect()
    atoms, by_atom = lg.load_build(conn, bid)
    conn.close()
    out = []
    for a in atoms.values():
        if a["type"] != "cyclonev_lcell_comb" or a["name"].startswith("~QUARTUS_CREATED_GND"):
            continue
        blk = "MLAB" if a["loc_kind"] == "MLABCELL" else "LAB"
        x, y, alm, half = a["x"], a["y"], a["n"] // 6, lg.HALF[(a["n"] // 3) % 2]
        st = S.get((blk, x, y), {})
        raw_s = st.get(("LUT_MASK", alm))
        raw = 0 if raw_s is None else int(raw_s.replace(".", ""), 16)
        mode = st.get(("%sMODE" % half, alm)) or lg.DEFAULT_MODE[half]
        used = {c["port"][4] for c in by_atom[a["id"]] if c["port"].startswith("data") and c["port"] != "datag" and c["net"]}
        out.append(((half, mode, blk == "MLAB"), (frozenset(used), int(a["params"]["lut_mask"].split("'h")[1], 16), raw), name))
    return out


def stage_lutmap(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    conn = orc.connect()
    bids = dict(conn.execute("select design, id from corpus_builds"))
    conn.close()
    sa, sb = collections.defaultdict(list), collections.defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for out in ex.map(lutsamples_one, [(n, root, tables, bids[n]) for n in names]):
            for key, smp, name in out:
                (sa if orc.split_of(name) == "A" else sb)[key].append(smp)
    ptab = lambda mlab: lg.MLAB_PERM if mlab else None  # noqa: E731
    log.info("samples A: %s", {k: len(v) for k, v in sorted(sa.items())})
    log.info("samples B: %s", {k: len(v) for k, v in sorted(sb.items())})
    res = {}
    for key in sorted(set(sa) | set(sb)):
        half, mode, mlab = key
        if key not in sa:
            log.info("%s: no A samples", key)
            continue
        wins = lm.learn({key: sa[key]}, ptab)[key]
        bswap = half == "B"
        okb = [w for w in wins if lm.consistent(w, sb.get(key, []), bswap, ptab(mlab))]
        # hand-coded doc model on the same samples
        def doc_ok(smps):
            n = 0
            for used, q, raw in smps:
                r = lg.lut_matches(q, raw, half, mode, set(used), mlab)
                n += 1 if r else 0
            return n
        log.info("%s: A=%d B=%d winners(A)=%d consistent_on_B=%d | doc-model A %d/%d B %d/%d", key, len(sa[key]),
                 len(sb.get(key, [])), len(wins), len(okb), doc_ok(sa[key]), len(sa[key]), doc_ok(sb.get(key, [])), len(sb.get(key, [])))
        res[str(key)] = {"A": len(sa[key]), "B": len(sb.get(key, [])), "winnersA": len(wins), "winners_ok_B": len(okb),
                         "example": [list(w[0]) + [w[1], w[2]] for w in wins[:2]]}
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "lutmap.json"), "w"))


def flip_lut_bit(m, tile, alm, k):
    """Flip bit k of LUT_MASK.alm of a LAB tile in the decoded planes; returns the CRAM position."""
    row = next(r for r in m.mux["lab"] if r["mux"] == "lut_mask")
    bx, by = row["bits"][alm][k]
    pos = m.pos2bit(tile) + by * m.sx + bx
    m.bits.cram[pos] ^= 1
    return pos


def roundtrip_one(args):
    name, root, tables = args
    out = {"design": name}
    orig = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    m = cd.decode(orig, DEVICE, overrides=True, tables=tables)
    enc = cd.encode_rbf(tables, m.bits)
    out["uncompressed_byte_identical"] = enc == orig
    comp = open(os.path.join(root, name, "bitstream.compressed.rbf"), "rb").read()
    mc = cd.decode(comp, DEVICE, overrides=True, tables=tables)
    same = (np.array_equal(m.bits.cram, mc.bits.cram) and all(np.array_equal(a, b) for a, b in zip(m.bits.pram, mc.bits.pram)))
    dis = next(r for r in m.mux["opt"] if r["mux"] == "compression_dis")["bits"][0][0]
    o1, o2 = list(m.bits.oram), list(mc.bits.oram)
    o1[dis[0]] ^= 1 << dis[1]
    for bx, by in next(r for r in m.mux["opt"] if r["mux"] == "jtag_id")["bits"][0]:   # usercode: checksum of the file
        o1[bx] &= ~(1 << by)
        o2[bx] &= ~(1 << by)
    o1[5] = o2[5] = 0     # strip 5: ~10 compression-linked bits whose set differs per design (length/CRC-like), unclaimed
    out["compressed_planes_equal"] = bool(same and o1 == o2)
    encc = cd.encode_rbf(tables, mc.bits, compress=True)
    off, used = mc.bits.compressed
    end = off + (used + 1) // 2
    out["compressed_stream_identical"] = encc[:end] == comp[:end]
    out["compressed_full_identical"] = encc == comp
    # single-feature edit: flip one LUT mask bit, re-encode, re-decode
    lines0 = m.bt_lines()
    S = lg.settings_index(m.settings())
    tile = next(((x, y), alm) for (blk, x, y), kv in sorted(S.items()) if blk == "LAB"
                for (mux, alm) in kv if mux == "LUT_MASK") if any(
        mux == "LUT_MASK" for (blk, x, y), kv in S.items() if blk == "LAB" for (mux, _a) in kv) else (tables["pos"]["T_LAB"][5], 0)
    k = sum(map(ord, name)) % 64
    pos = flip_lut_bit(m, tile[0], tile[1], k)
    edited = cd.encode_rbf(tables, m.bits)
    m2 = cd.decode(edited, DEVICE, overrides=True, tables=tables)
    lines1 = m2.bt_lines()
    a, b = linesets(lines0), linesets(lines1)
    changed = {kk: (sorted(a.get(kk, set()) - b.get(kk, set())), sorted(b.get(kk, set()) - a.get(kk, set()))) for kk in set(a) | set(b)}
    changed = {kk: v for kk, v in changed.items() if v[0] or v[1]}
    out["edit"] = {"tile": list(tile[0]), "alm": tile[1], "bit": k, "cram_pos": int(pos), "changed": changed,
                   "frames": {kk: v for kk, v in acc.frame_check(m2, edited).items() if kk in ("crc16_ok", "edcrc_ok", "frames")}}
    # Mistral cross-check of the edit
    od = os.path.join(WORK, name)
    os.makedirs(od, exist_ok=True)
    ef = os.path.join(od, "edited.rbf")
    open(ef, "wb").write(edited)
    mistral_bt(ef, os.path.join(od, "edited.mistral.bt"))
    mb = linesets(read_lines(os.path.join(od, "edited.mistral.bt")))
    ob = linesets(read_lines(os.path.join(od, "mistral.bt"))) if os.path.exists(os.path.join(od, "mistral.bt")) else None
    if ob is not None:
        mchg = {kk: (sorted(ob.get(kk, set()) - mb.get(kk, set())), sorted(mb.get(kk, set()) - ob.get(kk, set())))
                for kk in set(ob) | set(mb)}
        mchg = {kk: v for kk, v in mchg.items() if v[0] or v[1]}
        out["edit"]["mistral_changed"] = mchg
    return out


def stage_roundtrip(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    res = []
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(roundtrip_one, [(n, root, tables) for n in names]):
            res.append(r)
            log.info("%-26s unc=%s comp_planes=%s comp_stream=%s comp_full=%s edit_changed=%s", r["design"],
                     r["uncompressed_byte_identical"], r["compressed_planes_equal"], r["compressed_stream_identical"],
                     r["compressed_full_identical"], {k: (len(v[0]), len(v[1])) for k, v in r["edit"]["changed"].items()})
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "roundtrip.json"), "w"))
    n = len(res)
    log.info("roundtrip: uncompressed identical %d/%d, compressed planes equal %d/%d, compressed stream identical %d/%d, "
             "compressed full identical %d/%d", sum(r["uncompressed_byte_identical"] for r in res), n,
             sum(r["compressed_planes_equal"] for r in res), n, sum(r["compressed_stream_identical"] for r in res), n,
             sum(r["compressed_full_identical"] for r in res), n)


FUZZ = os.path.join(REPO, "tmp", "cyclonev_blockmux_fuzz")


def probe_model(slug, overrides=False, tables=None):
    d = os.path.join(FUZZ, slug)
    data = open(os.path.join(d, slug + ".rbf"), "rb").read()
    return cd.decode(data, DEVICE, overrides=overrides, tables=tables), d


def stage_probes(a):
    """Re-derive the oracle-backed corrections from Quartus knob builds with the native decoder."""
    tables = nt.load(DEVICE)
    import re
    res = {"opt": [], "lab": []}
    base, _ = probe_model("rs_opt_default", False, tables)
    for slug in sorted(x for x in os.listdir(FUZZ) if x.startswith("rs_opt_")):
        m, d = probe_model(slug, False, tables)
        diff = [(st, b) for st in range(32) for b in range(40) if ((m.bits.oram[st] ^ base.bits.oram[st]) >> b) & 1]
        knobs = [l.split("-name")[1].strip() for l in open(os.path.join(d, slug + ".qsf")) if "ENABLE_" in l or "RELEASE" in l
                 or "START_UP" in l or "CVP" in l]
        lines = [l for l in m.bt_lines() if l.startswith("o ")]
        mo, _ = probe_model(slug, True, tables)
        lines_o = [l for l in mo.bt_lines() if l.startswith("o ")]
        res["opt"].append({"build": slug, "qsf_knobs": knobs, "oram_bits_changed_vs_default": diff, "o_lines_bootstrap": lines,
                           "o_lines_native": lines_o})
        log.info("opt %-24s changed %s knobs=%s", slug, diff, knobs)
    rows = []
    for slug in sorted(x for x in os.listdir(FUZZ) if x.startswith("labdump_rs_")):
        m, d = probe_model(slug, False, tables)
        v = open(os.path.join(d, slug + ".v")).read()
        neg = bool(re.search(r"@\(\s*negedge\s+clk", v))
        links = m.routes()
        tn = tables["routes"]["type_names"]
        src = None
        for s_, t_ in links:
            if (t_ >> 17) & 0x7F == 20 and (t_ >> 10) & 0x7F == 20 and tn[t_ >> 24] == "TCLK" and (t_ & 0x3FF) < 2:
                src = "CLKIN.%d" % (t_ & 0x3FF)
        sets = lg.settings_index(m.settings()).get(("LAB", 20, 20), {})
        if src is None and ("CLKA_SEL", -1) in sets or ("CLKB_SEL", -1) in sets:
            src = "DATAIN(fabric)"
        r = m.routes()
        b645 = int(m.bits.cram[m.pos2bit((20, 20)) + 45 * m.sx + 6])
        b1044 = int(m.bits.cram[m.pos2bit((20, 20)) + 44 * m.sx + 10])
        rows.append((slug, "neg" if neg else "pos", src, b645, b1044))
        log.info("lab %-26s edge=%s clock_via=%s bit(6.45)=%d bit(10.44)=%d", slug, "neg" if neg else "pos", src, b645, b1044)
    # which bit tracks which fact
    edge_t = sum(1 for r_ in rows if r_[4] == (r_[1] == "neg"))
    srcsel = {r_[2]: r_[3] for r_ in rows}
    src_t = sum(1 for r_ in rows if r_[3] == (0 if r_[2] and r_[2].startswith("CLKIN") else 1))
    log.info("bit(10.44) == edge in %d/%d; bit(6.45) == (source is fabric DATAIN) in %d/%d", edge_t, len(rows), src_t, len(rows))
    res["lab"] = rows
    res["lab_summary"] = {"edge_bit_10_44": [edge_t, len(rows)], "source_bit_6_45": [src_t, len(rows)]}
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "probes.json"), "w"), default=str)


def lift_one(args):
    name, root, tables = args
    from lifters.cyclonev_lift import CycloneVLift
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    od = os.path.join(WORK, name)
    os.makedirs(od, exist_ok=True)
    res = {"design": name}
    mistral_bt(os.path.join(root, name, "bitstream.rbf"), os.path.join(od, "mistral.bt"))
    for mode, kw in (("mistral", None), ("compat", dict(overrides=False, compat=True)), ("native", dict(overrides=True))):
        path = os.path.join(od, "mistral.bt")
        if kw is not None:
            m = cd.decode(data, DEVICE, tables=tables, **kw)
            path = os.path.join(od, mode + ".bt")
            open(path, "w").write("\n".join(m.bt_lines()) + "\n")
        lift = CycloneVLift(DEVICE)
        pc = lift.parse_config(path)
        d = lift.recover_netlist(pc)
        res[mode] = {"unparsed": pc.n_unparsed_lines, "luts": len(d.luts), "ffs": len(d.ffs), "nets": len(d.all_nets),
                     "arcs": len(pc.arcs), "pads": len(d.pads)}
    return res


def stage_lift(a):
    root = corpus_root()
    names = designs(root, a.only)
    tables = nt.load(DEVICE)
    res = []
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(lift_one, [(n, root, tables) for n in names]):
            res.append(r)
    same_compat = sum(1 for r in res if r["compat"] == r["mistral"])
    same_native = sum(1 for r in res if r["native"] == r["mistral"])
    log.info("lift: compat == mistral in %d/%d designs; native == mistral in %d/%d designs; unparsed lines native total %d",
             same_compat, len(res), same_native, len(res), sum(r["native"]["unparsed"] for r in res))
    for r in res:
        if r["native"] != r["mistral"]:
            log.info("lift differs %s: mistral=%s native=%s", r["design"], r["mistral"], r["native"])
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "lift.json"), "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["diff", "account", "routes", "logic", "lutmap", "roundtrip", "probes", "lift"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-overrides", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_native_verify.log"))])
    heavy_guard.wait_available(log, f"cyclonev_native_verify {a.stage}", min_gb=1.0 + 0.25 * a.workers)
    {"diff": stage_diff, "account": stage_account, "routes": stage_routes, "logic": stage_logic, "lutmap": stage_lutmap, "roundtrip": stage_roundtrip, "probes": stage_probes, "lift": stage_lift}[a.stage](a)


if __name__ == "__main__":
    main()
