#!/usr/bin/env python3.15t
"""Score the hard-block decoders against the Quartus post-fit netlist of each specimen (#169).

  python3.15t scripts/cycloneiv_clean_hardblocks_score.py [pll|m9k|mac|all]   # log tmp/logs/cycloneiv_clean_hardblocks_score.log, json tmp/cycloneiv_clean/hardblocks_score.json

Per feature: matched / missing / extra / wrong.  Ambiguous or undecoded = missing.  Ground truth = postfit.vo defparams (vendor tool), not our own build.
"""
import json
import logging
import os
import re
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_hardblocks_score.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "hardblocks_score.json")
log = logging.getLogger("hb_score")


def vo_params(name, atom):
    """defparams of the first atom whose escaped name contains `atom` in a specimen's postfit.vo; also its Location."""
    t = open(os.path.join(CORPUS, name, "postfit.vo")).read()
    m = re.search(r"// Location: (\w+)\ncycloneiv_\w+ \\(" + re.escape(atom) + r"[^ ]*) ", t)
    if not m:
        return None, None
    key = re.escape(m[2])
    d = {k: v for k, _, v in re.findall(r"defparam \\" + key + r" \.(\w+) = (\"?)([^\";]*)\2;", t)}
    return m[1], d


def score_pll(names=None):
    from lifters.cycloneiv_clean import asmdb_walk as W, pll
    import cycloneiv_clean_dirt as D
    pm = pll.load(W.Walk(), D.enum_tables())
    cff = pll.IO.Cff()
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)
    for n in sorted(os.listdir(CORPUS)):
        if not (n.startswith("gxhb_pll_") or n.startswith("gxhb_pllsite_")) or not os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf")):
            continue
        loc, p = vo_params(n, "pll|auto_generated|pll1")
        if p is None:
            continue
        k = int(loc.split("_")[1])
        bt, path = pll.PLL_SITE[k]
        vals = pll.read_cff(os.path.join(CORPUS, n, "bitstream.rbf"), cff)
        used = pm.used(vals)
        r = dict(matched=0, missing=0, extra=0, wrong=0)
        r["extra"] += sum(1 for u in used if u[0] != k)                  # enabled PLL that the netlist does not have
        if (k, bt, path) not in used:
            r["missing"] += 1
        d = pm.params(vals, bt, path)
        want = {"m": int(p["m"]), "n": int(p["n"]), "charge_pump": int(p["charge_pump_current_bits"]),
                "loop_filter_r": int(p["loop_filter_r_bits"]), "loop_filter_c": int(p["loop_filter_c_bits"]), "vco_post_scale": int(p["vco_post_scale"])}
        for c in range(5):
            want[f"c{c}"] = ("bypass", 0, 0, 0) if p[f"c{c}_mode"] == "bypass" else ("counter", int(p[f"c{c}_high"]), int(p[f"c{c}_low"]), int(p[f"c{c}_initial"]))
        for key, w in want.items():
            if d[key] == w:
                r["matched"] += 1
            else:
                r["wrong"] += 1
        rows.append(dict(build=n, pll=k, **r))
        for key in tot:
            tot[key] += r[key]
    return rows, tot


def _m9k_ctx():
    from lifters.cycloneiv_clean import asmdb_walk as W, fields as F, m9k, plane as P
    import cycloneiv_clean_dirt as D
    w = W.Walk()
    flds = F.fields(w, D.enum_tables())
    return dict(w=w, tab=P.load_tables(), off=m9k.content_offsets(flds), bases=F.bases(w, 39), m9k=m9k, P=P)


def _plane_set(name):
    from lifters.cycloneiv_clean import sofio
    x = sofio.rbf_cram(os.path.join(CORPUS, name, "bitstream.rbf"))
    r, j, k = np.nonzero(x)
    return (r.astype(np.int64) * 800 + j + 1) * 8 + k


def _mem_init_ones(name):
    t = open(os.path.join(CORPUS, name, "src", "top.v")).read()
    out = []
    for m in re.finditer(r"\.mem_init(\d)\(2048'h([0-9a-f]+)\)", t):
        v = int(m[2], 16)
        out += [int(m[1]) * 2048 + b for b in range(2048) if v >> b & 1]
    return np.array(out, np.int64)


def score_m9k_content():
    """Content map: (a) bincode per width, every mux position; (b) random-fill specimens at their sites, set-cell equality."""
    c = _m9k_ctx()
    m9k, tab = c["m9k"], c["tab"]
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)

    def add(label, r):
        rows.append(dict(label=label, **r))
        for k in tot:
            tot[k] += r[k]
    inst = m9k.instance(23, 40)
    cells = m9k.content_cells(c["bases"][inst], c["off"], tab)
    base_set = None
    for width in m9k.WIDTHS:
        pre = f"gxm9k_hb{width}"
        if not os.path.exists(os.path.join(CORPUS, pre + "_base", "bitstream.rbf")):
            continue
        b0 = np.isin(cells, _plane_set(pre + "_base"))
        code = np.zeros(m9k.CONTENT_BITS, np.int64)
        for k in range(14):
            code |= (np.isin(cells, _plane_set(f"{pre}_k{k}")) ^ b0).astype(np.int64) << k
        wd, bt = np.divmod(np.arange(m9k.depth(width) * width), width)
        want = np.zeros(m9k.CONTENT_BITS, np.int64)
        want[m9k.pos_of_index(m9k.index(width, wd, bt))] = wd * width + bt + 1
        add(f"bincode w{width}", dict(matched=int(((code == want) & (want > 0)).sum()), missing=int(((code == 0) & (want > 0)).sum()),
                                      extra=int(((code > 0) & (want == 0)).sum()),
                                      wrong=int(((code > 0) & (want > 0) & (code != want)).sum())))
    for n in sorted(os.listdir(CORPUS)):
        if not re.match(r"gxm9k_r(16|9|1)(_x\d+_y\d+_n0)?_s\d+$", n) or not os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf")):
            continue
        t = open(os.path.join(CORPUS, n, "design.toml")).read()
        mm = re.search(r"M9K_X(\d+)_Y(\d+)_N0", t)
        ones = _mem_init_ones(n)
        if not mm or not len(ones):
            continue
        ins = m9k.instance(int(mm[1]), int(mm[2]))
        cl = m9k.content_cells(c["bases"][ins], c["off"], tab)
        want = np.zeros(m9k.CONTENT_BITS, bool)
        wd_ = int(re.match(r"gxm9k_r(\d+)", n)[1])
        want[m9k.pos_of_index(m9k.index(wd_, ones // wd_, ones % wd_))] = True    # WYSIWYG mem_init c = word * W + bit
        got = np.isin(cl, _plane_set(n))
        add(n, dict(matched=int((want & got).sum() + (~want & ~got).sum()), missing=int((want & ~got).sum()), extra=int((~want & got).sum()), wrong=0))
    return rows, tot


ROUTING = ("RAM_MS_", "RAM_PIA_", "RAM_CONTENT", "MAC_ROW_DATA_INPUT", "MAC_PIA_")      # port-input muxes (routing to the block), not block configuration


def _inst_map(ctx, btype, inst):
    """plane cell id -> (group name, gi, path index, bit position) for the control groups of one instance."""
    from lifters.cycloneiv_clean import fields as F
    out = {}
    base = ctx["bases_by"][btype][inst:inst + 1]
    for f in ctx["flds"]:
        if f.btype != btype or f.name.startswith(ROUTING):
            continue
        for pi, site in enumerate(f.sites):
            for off in site:
                a = F.absolute(base, off).ravel()
                r, j, k = ctx["P"].sof_to_rbf(a, ctx["tab"])
                for bp, c in enumerate(((r * 800 + j) * 8 + k).tolist()):
                    out.setdefault(c, (f.name, f.gi, pi, bp))
    return out


def _ctl_ctx():
    from lifters.cycloneiv_clean import asmdb_walk as W, fields as F, plane as P
    import cycloneiv_clean_dirt as D
    w = W.Walk()
    return dict(flds=F.fields(w, D.enum_tables()), tab=P.load_tables(), P=P, bases_by={b: F.bases(w, b) for b in (39, 41)})


def _ctl_diff(ctx, imap, base, spec):
    b, s = set(_plane_set(base).tolist()), set(_plane_set(spec).tolist())
    on, off = s - b, b - s
    sig = {(*imap[c], "set") for c in on if c in imap} | {(*imap[c], "clear") for c in off if c in imap}
    return sig, len(on) + len(off)


def _cross(ctx, tag, pairs, btype, inst_of):
    """pairs: [(feature, base, spec_A, spec_B)]; signature from site A; site B scored against it."""
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)
    for feat, (bA, sA, iA), (bB, sB, iB) in pairs:
        gA, gB = _ctl_diff(ctx, _inst_map(ctx, btype, iA), bA, sA)[0], _ctl_diff(ctx, _inst_map(ctx, btype, iB), bB, sB)[0]
        key = lambda g: {x[:4]: x[4] for x in g}                                  # noqa: E731
        ka, kb = key(gA), key(gB)
        r = dict(matched=len(gA & gB), wrong=sum(1 for k in ka if k in kb and ka[k] != kb[k]),
                 missing=sum(1 for k in ka if k not in kb), extra=sum(1 for k in kb if k not in ka))
        rows.append(dict(block=tag, feature=feat, signature=sorted(map(list, gA)), **r))
        for k in tot:
            tot[k] += r[k]
    return rows, tot


def score_mac():
    ctx = _ctl_ctx()
    from lifters.cycloneiv_clean import mac
    ia, ib = mac.instance(103, 87), mac.instance(43, 87)
    feats = ["signed_a", "signed_b", "signed_ab", "in_a_reg", "in_b_reg", "mult_reg", "out_reg", "w9", "w10", "dyn_signa", "dyn_signb", "null_seed"]
    pairs = [(f, ("gxhb_macpa_base", f"gxhb_macpa_{f}", ia), ("gxhb_macpb_base", f"gxhb_macpb_{f}", ib)) for f in feats
             if all(os.path.exists(os.path.join(CORPUS, x, "bitstream.rbf")) for x in (f"gxhb_macpa_{f}", f"gxhb_macpb_{f}"))]
    return _cross(ctx, "MAC", pairs, 41, None)


def score_m9k_ctl():
    ctx = _ctl_ctx()
    from lifters.cycloneiv_clean import m9k
    sites = {"": (23, 40), "x65_y40_n0_": (65, 40), "x7_y60_n0_": (7, 60)}
    feats = ["cke_in_none", "cke_core_none", "cke_out_none", "rdw_old", "wrclk", "outclk", "outclr", "addrclr", "byteena", "cke_in_ena0",
             "cke_core_ena0", "cke_out_ena0", "powerup", "null_rename", "null_seed"]
    ok = lambda n: os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf"))        # noqa: E731
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)
    for f in feats:
        base = "o" if f in ("cke_out_none", "outclr", "cke_out_ena0") else "s"
        if f in ("cke_in_none", "cke_core_none", "wrclk", "rdw_old", "cke_in_ena0", "cke_core_ena0", "outclk"):
            base = "o" if f != "outclk" else "s"
        sp = {k: (f"gxm9k_w_{k}base_{base}", f"gxm9k_w_{k}{f}", m9k.instance(*xy)) for k, xy in sites.items()}
        if not all(ok(v[0]) and ok(v[1]) for v in sp.values()):
            continue
        for k in ("x65_y40_n0_", "x7_y60_n0_"):
            r, t = _cross(ctx, "M9K", [(f"{f}@{k.rstrip('_') or 'x23_y40'}", sp[""], sp[k])], 39, None)
            rows += r
            for kk in tot:
                tot[kk] += t[kk]
    return rows, tot


def score_m9k_code_rules():
    """Code-derived writer rules (m9k.WRITERS) vs gxm9k_w_* WYSIWYG builds: expected value from the top.v parameter, one-hot select,
    stored as written; flag bit 9 / NEW_DATA flag polarity measured (stored bit = 1 - registered / old-data)."""
    from lifters.cycloneiv_clean import m9k
    ctx = _ctl_ctx()
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)
    for n in sorted(os.listdir(CORPUS)):
        if not n.startswith("gxm9k_w_") or not os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf")):
            continue
        t = open(os.path.join(CORPUS, n, "design.toml")).read()
        mm = re.search(r"M9K_X(\d+)_Y(\d+)_N0", t)
        v = open(os.path.join(CORPUS, n, "src", "top.v")).read()
        inst = m9k.instance(int(mm[1]), int(mm[2]))
        imap = _inst_map(ctx, 39, inst)
        cells = {}
        for c, (nm, gi, pi, bp) in imap.items():
            if nm in ("RAM_REG_DATA_OUT", "RAM_NEW_DATA_MODE") and bp == 0:
                cells[nm] = c
        have = set(_plane_set(n).tolist())
        want = {"RAM_REG_DATA_OUT": 1 if "port_a_data_out_clock" in v else 0,
                "RAM_NEW_DATA_MODE": 1 if re.search(r'port_a_read_during_write_mode\("old_data"\)', v) else 0}
        r = dict(matched=0, missing=0, extra=0, wrong=0)
        for nm, val in want.items():
            if nm not in cells:
                r["missing"] += 1
                continue
            phys = int(cells[nm] in have)
            r["matched" if phys == 1 - val else "wrong"] += 1
        rows.append(dict(build=n, **r))
        for k in tot:
            tot[k] += r[k]
    return rows, tot


def score_m9k_modes():
    """Mode groups from the writer rules (m9k.true_dual_port_value / packed_mode_value) + asmdb_select vs altsyncram mode builds and the nine hb width builds."""
    from lifters.cycloneiv_clean import m9k
    ctx = _ctl_ctx()
    imap = _inst_map(ctx, 39, m9k.instance(23, 40))
    cell = {}
    for c, (nm, gi, pi, bp) in imap.items():
        if nm in ("RAM_USE_TRUE_DUAL_PORT_MODE", "RAM_USE_PACKED_MODE") and bp == 0:
            cell[nm] = c
    F = m9k.flag_bits
    cases = [("gxm9k_m_base_s", F("RAM_SINGLE_PORT"), 0), ("gxm9k_m_rom", F("RAM_READ_ONLY"), 0), ("gxm9k_m_dual", F("RAM_DUAL_PORT"), 0),
             ("gxm9k_m_bidir", F("RAM_BIDIR_DUAL_PORT"), 0)]
    cases += [(f"gxm9k_hb{w}_base", F("RAM_SINGLE_PORT") | (F("RAM_PACKED") if w in (32, 36) else 0), 0) for w in m9k.WIDTHS]
    rows, tot = [], dict(matched=0, missing=0, extra=0, wrong=0)
    for n, flags, _ in cases:
        if not os.path.exists(os.path.join(CORPUS, n, "bitstream.rbf")):
            continue
        have = set(_plane_set(n).tolist())
        r = dict(matched=0, missing=0, extra=0, wrong=0)
        for nm, val in (("RAM_USE_TRUE_DUAL_PORT_MODE", m9k.true_dual_port_value(flags)), ("RAM_USE_PACKED_MODE", m9k.packed_mode_value(flags))):
            r["matched" if int(cell[nm] in have) == val else "wrong"] += 1       # ENCODED 1-bit mux: bit0 = value
        rows.append(dict(build=n, **r))
        for k in tot:
            tot[k] += r[k]
    return rows, tot


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    res = {}
    if which in ("pll", "all"):
        rows, tot = score_pll()
        res["pll"] = dict(rows=rows, total=tot)
        log.info("PLL %d specimens %s", len(rows), json.dumps(tot))
    if which in ("m9k", "all"):
        rows, tot = score_m9k_content()
        res["m9k_content"] = dict(rows=rows, total=tot)
        log.info("M9K content %d specimens %s", len(rows), json.dumps(tot))
        for r in rows[:12]:
            log.info("  %s", json.dumps(r))
    if which in ("m9kcode", "all"):
        rows, tot = score_m9k_code_rules()
        res["m9k_code_rules"] = dict(rows=rows, total=tot)
        log.info("M9K code-derived writer rules %d builds %s", len(rows), json.dumps(tot))
    if which in ("m9kmodes", "all"):
        rows, tot = score_m9k_modes()
        res["m9k_modes"] = dict(rows=rows, total=tot)
        log.info("M9K mode groups (writer rules) %d builds %s", len(rows), json.dumps(tot))
    if which in ("mac", "all"):
        rows, tot = score_mac()
        res["mac"] = dict(rows=rows, total=tot)
        log.info("MAC control %d features %s", len(rows), json.dumps(tot))
        for r in rows:
            log.info("  %s %s", r["feature"], json.dumps({k: r[k] for k in ("matched", "missing", "extra", "wrong")}))
    if which in ("m9kctl", "all"):
        rows, tot = score_m9k_ctl()
        res["m9k_ctl"] = dict(rows=rows, total=tot)
        log.info("M9K control %d pairs %s", len(rows), json.dumps(tot))
        for r in rows:
            log.info("  %s %s", r["feature"], json.dumps({k: r[k] for k in ("matched", "missing", "extra", "wrong")}))
    json.dump(res, open(OUT, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
