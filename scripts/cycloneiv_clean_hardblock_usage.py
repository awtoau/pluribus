#!/usr/bin/env python3.15t
"""Is a hard / config block (transceiver, PCIe hard IP, CONTROL, OCT, HSSI strip) used by the third-party EP4CGX150 image? (#165)

  PLURIBUS_DJI_IMAGE=<path> python3.15t scripts/cycloneiv_clean_hardblock_usage.py     # log tmp/logs/cycloneiv_clean_hardblock_usage.log, json tmp/cycloneiv_clean/hardblock_usage.json

- Cells = the absolute-address groups of each non-LAB/MEAB/MAC/PLL/IO/clock block type of the asmdb walk (hardblocks.absolute_bits rule), CRAM + CFF
  mapped to rbf plane cells; DPRIO offsets inside the CFF range are reported as a separate alias candidate (docs/altera/cycloneIV/cycloneiv-address-spaces.md 2.1).
- Idle pattern = per-cell majority over the EP4CGX150 gate builds (none instantiates a transceiver / PCIe atom) and over the DF27 (F672) package builds.
- Per block: cells, set in image, never set in any corpus build (ever_set), image != idle, and the same "!= idle" count for each reference build (spread).
- Counts only; image path never logged.
"""
import collections
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_dirt as D  # noqa: E402
import cycloneiv_clean_residue as R  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_decompress as cd  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
from lifters.cycloneiv_clean import asmdb_walk as W, cycloneiv_io as IO, hardblocks as H, options as OPT, plane as P  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_hardblock_usage.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "hardblock_usage.json")
# source: the block types already decoded or out of scope here (docs/altera/cycloneIV/cycloneiv-clean-hardblocks.md: PLL, M9K, MAC; docs/altera/cycloneIV/cycloneiv-clean-io.md: HIO, VIO, dedicated clock pads; clock buffers)
EXCLUDE = {"LAB", "MEAB", "MAC", "FAST_PLL", "GENERAL_PLL", "HIO", "VIO", "CLKBUF_GCLK", "DEDICATED_CLOCK", "DEDICATED_NEGATIVE_CLOCK"}
DEVICE = "EP4CGX150DF27C7"        # F672: the package the image is inferred to be (tests/cycloneiv_clean/test_pkginfer.py)
log = logging.getLogger("hbu")


def split_block(name, gtype):
    """CONTROL holds the fabric-visible config blocks (CRC / JTAG / OSC / RU) under one block type: split by the group-type prefix."""
    return f"CONTROL.{gtype.split('_')[0]}" if name == "CONTROL" else name


def collect(w, names):
    """-> {block: {"cram": set, "cff": set, "dprio": set, "opt": set, "sites": {site: set of (space, addr)}}} over the non-excluded groups."""
    out = collections.OrderedDict()
    for g in w.groups():
        if g["cls"] == 5:
            continue
        bname = names["block_type"].get(g["btype"], str(g["btype"]))
        if bname in EXCLUDE:
            continue
        key = split_block(bname, names["arch_group_type"].get(g["type"], str(g["type"])))
        d = out.setdefault(key, {"cram": set(), "cff": set(), "dprio": set(), "opt": set(), "groups": set(), "sites": collections.defaultdict(set)})
        d["groups"].add(names["arch_group_type"].get(g["type"], str(g["type"])))
        n = len(g["bits"]) if g["cls"] == 7 else len(g["paths"])
        for s in range(n):
            for b in W._site_bits(w, g, s):
                tag = b >> 24
                if b >> 31 == 0:
                    sp, a = "cram", b & 0x7FFFFFFF
                elif b >> 28 == 0xA:
                    sp, a = "cff", b & 0x0FFFFFFF
                elif tag == 0x84:
                    sp, a = "dprio", b & 0x00FFFFFF
                elif tag == 0x88:
                    sp, a = "opt", b & 0x00FFFFFF
                else:
                    continue
                d[sp].add(a)
                d["sites"][s].add((sp, a))
    return out


class Cells:
    """address -> rbf plane cell (A4 + A5 for CRAM, primary replica for CFF); one sorted unique array per block."""

    def __init__(self):
        self.geo = cg.load(cg.die_of("EP4CGX150"))
        self.vmap = cc.vmap_for(P.RBF_FRAME_BYTES, tuple(self.geo.lane_bytes), tuple(map(tuple, self.geo.lane_swaps)))
        self.nv = len(self.vmap)
        self.tab = P.load_tables()
        self.cff = IO.Cff()

    def cram(self, addr):
        a = np.array(sorted(x for x in addr if x < P.N_BITS), np.int64)
        return R.plane_flat_ordered(a, self.nv, self.vmap, self.tab) if len(a) else np.zeros(0, np.int64)

    def cffcells(self, idx):
        i = np.array(sorted(x for x in idx if x < self.cff.n_bits), np.int64)
        c = self.cff.primary[i, 0, :]
        return c[:, 0] * self.nv + self.vmap[c[:, 1] * 8 + c[:, 2]], i


def present(keys, cells):
    if not len(cells):
        return np.zeros(0, bool)
    k = np.searchsorted(keys, cells)
    return keys[np.minimum(k, len(keys) - 1)] == cells


def plane_keys(path, geo):
    pl = cc.cram_plane(open(path, "rb").read(), geo)
    return pl.keys if pl.shape[1] == cc.vmap_for(P.RBF_FRAME_BYTES, tuple(geo.lane_bytes), tuple(map(tuple, geo.lane_swaps))).shape[0] else None


def reference_matrix(paths, cells, geo, workers=4):
    """bool [designs, cells]; planes of another cell width are skipped."""
    def one(p):
        k = plane_keys(p, geo)
        return None if k is None else present(k, cells)
    with ThreadPoolExecutor(workers) as ex:
        rows = [r for r in ex.map(one, paths) if r is not None]
    return np.array(rows, bool)


def gate_designs():
    names = [ln.split("\t")[0] for ln in open(os.path.join(REPO, "reference", "gate_fast.tsv")).read().splitlines()[1:]]
    return [str(cc.CORPUS / n / "bitstream.rbf") for n in names if (cc.CORPUS / n / "bitstream.rbf").exists() and cc.device_of(n).startswith("EP4CGX150")]


def pkg_designs(code):
    import glob
    return sorted(glob.glob(os.path.join(REPO, "tmp", "pkgtest", f"*{code}*", "bitstream.rbf")))


def summarise(name, cells, img, gate, pkg, ever):
    """Row of counts for one cell set (idle = majority over the references)."""
    n = len(cells)
    r = {"cells": n, "image_set": int(img.sum()), "ever_set_in_corpus": int(ever.sum()), "never_set_in_corpus": int((~ever).sum()),
         "image_set_never_in_corpus": int((img & ~ever).sum())}
    for lab, M in (("gate", gate), ("df27", pkg)):
        if M is None or not len(M):
            continue
        idle = M.sum(0) * 2 > len(M)
        diff = (M != idle[None, :]).sum(1)
        r[f"{lab}_builds"] = len(M)
        r[f"{lab}_idle_set"] = int(idle.sum())
        r[f"{lab}_varies"] = int(((M.sum(0) > 0) & (M.sum(0) < len(M))).sum())
        r[f"{lab}_image_ne_idle"] = int((img != idle).sum())
        r[f"{lab}_image_set_idle_clear"] = int((img & ~idle).sum())
        r[f"{lab}_image_clear_idle_set"] = int((~img & idle).sum())
        r[f"{lab}_build_ne_idle_min_med_max"] = [int(diff.min()), int(np.median(diff)), int(diff.max())]
    return r


def fmt(r):
    s = f"cells {r['cells']:6d} image set {r['image_set']:6d} never-in-corpus {r['never_set_in_corpus']:6d} image-set&never {r['image_set_never_in_corpus']:5d}"
    for lab in ("gate", "df27"):
        if f"{lab}_builds" in r:
            s += (f" | {lab}({r[lab + '_builds']}): idle-set {r[lab + '_idle_set']}, varies {r[lab + '_varies']}, image!=idle {r[lab + '_image_ne_idle']}"
                  f" (set-vs-idle-clear {r[lab + '_image_set_idle_clear']}, clear-vs-idle-set {r[lab + '_image_clear_idle_set']}), builds!=idle min/med/max {r[lab + '_build_ne_idle_min_med_max']}")
    return s


def pads_report(rbf_bytes, res):
    """F672 transceiver / REFCLK pins: pad kind, CFF site (if any), decoded class (counts and ball names of public pin list only)."""
    from lifters.cycloneiv_clean import io_decode as ID, io_fields as IF, io_pins as IP, pinfile as PF, pkgpad as K, tracer as T
    io = T.Io()
    dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
    pm = IP.PinMap(io, dec)
    val, _ = io.cff.read(rbf_bytes)
    cls = pm.classify(val, DEVICE)
    pins = K.pins(672)
    pads = K.pads()
    pin_pad = K.pin_pad(pins)
    ball_pad = {pins[i]["strs"][0]: pads[j]["strs"][3] for i, j in pin_pad.items()}
    ball_site = pm.ball_site(DEVICE)
    kinds = collections.Counter(ball_pad.values())
    log.info("F672 bonded pads by kind (pad ddb): %s", dict(kinds))
    rows = {"pad_kinds_bonded_F672": dict(kinds)}
    gx, ref = [], []
    for r in PF.rows():
        b = r["balls"].get("F672")
        if not b:
            continue
        isgx = r["name"].startswith("GXB_")
        isref = r["name"].startswith("REFCLK") or "REFCLK" in r["optional"]
        if isgx or isref:
            (gx if isgx else ref).append((b, r["name"], ball_pad.get(b), ball_site.get(b), cls.get(b, {}).get("class")))
    log.info("GXB pins F672: %d; with a CFF site: %d; classes %s", len(gx), sum(1 for x in gx if x[3]), dict(collections.Counter(x[4] for x in gx)))
    log.info("REFCLK pins F672: %d; with a CFF site: %d; classes %s", len(ref), sum(1 for x in ref if x[3]), dict(collections.Counter(x[4] for x in ref)))
    for x in ref:
        log.info("  REFCLK ball %s name %s pad kind %s site %s class %s", *x)
    allc = collections.Counter(c["class"] for c in cls.values())
    log.info("F672 balls with a site: %d, classes %s (used %s)", len(cls), dict(allc), allc.get("used"))
    rows.update(gxb_pins=len(gx), gxb_with_site=sum(1 for x in gx if x[3]), refclk_pins=len(ref), refclk_with_site=sum(1 for x in ref if x[3]),
                refclk_classes=dict(collections.Counter(x[4] for x in ref)), f672_site_classes=dict(allc))
    res["pads"] = rows


def option_report(rbf_bytes, res):
    """Option-register groups that reach the rbf header (32 cells) vs the vendor default vector: the CRC / error-detect, ASMI, remote-update style options."""
    b = np.frombuffer(rbf_bytes, np.uint8)
    ent = OPT.entries()
    obs, dflt, have = {}, OPT.default_vector(), set()
    for e in ent:
        if e["rbf_cells"]:
            v = 0
            for fr, j, k in e["rbf_cells"][:1]:
                v = int(b[P.RBF_HEADER + fr * P.RBF_FRAME_BYTES + j] >> k & 1)
            obs[e["index"]] = v
            have.add(e["index"])
    diff = [i for i in obs if obs[i] != dflt[i]]
    out = {}
    for name, bits in OPT.groups().items():
        vis = [i for i in bits if i in obs]
        out[name] = {"bits": len(bits), "bits_in_rbf": len(vis), "differ_from_vendor_default": [i for i in vis if obs[i] != dflt[i]]}
        log.info("option group %-45s bits %2d in rbf %2d differing from default %s", name, len(bits), len(vis), out[name]["differ_from_vendor_default"])
    res["options"] = {"bits_in_rbf": len(obs), "differ_from_default": len(diff), "groups": out}


def main():
    path = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not path:
        sys.exit("set PLURIBUS_DJI_IMAGE")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    w = W.Walk()
    names = D.enum_tables()
    blocks = collect(w, names)
    C = Cells()
    data = open(path, "rb").read()
    img_keys = cc.cram_plane(data, C.geo).keys
    rbf = bytes(cd.decompress(data, {}))
    del data
    val, _ = C.cff.read(rbf)
    ever = np.unpackbits(np.load(R.EVER))
    gate_paths, pkg_paths = gate_designs(), pkg_designs("DF27")
    log.info("blocks %d; gate builds %d; DF27 package builds %d; image plane cells set %d", len(blocks), len(gate_paths), len(pkg_paths), len(img_keys))
    # cells per block, per space; sites for per-instance detail
    allcells = {}
    for b, d in blocks.items():
        cr = C.cram(d["cram"])
        cf, cfi = C.cffcells(d["cff"])
        dp = sorted(x for x in d["dprio"] if x < C.cff.n_bits)
        dpf, _ = C.cffcells(dp) if dp else (np.zeros(0, np.int64), None)
        allcells[b] = {"cram": cr, "cff": cf, "dprio_in_cff": dpf}
    union = np.unique(np.concatenate([c for v in allcells.values() for c in v.values()]))
    log.info("union of cells %d", len(union))
    # consistency of the CFF cell mapping against Cff.read on the image
    cfa = np.arange(C.cff.n_bits)
    flat_all, _i = C.cffcells(set(cfa.tolist()))
    mism = int((present(img_keys, flat_all) != val.astype(bool)[_i]).sum())
    log.info("CFF cell mapping vs Cff.read on the image: %d mismatches of %d bits", mism, len(_i))
    gate = reference_matrix(gate_paths, union, C.geo)
    pkg = reference_matrix(pkg_paths, union, C.geo) if pkg_paths else None
    img_u = present(img_keys, union)
    ever_u = ever[union].astype(bool)
    pos = {int(c): i for i, c in enumerate(union)}
    res = {"gate_builds_used": int(len(gate)), "df27_builds_used": 0 if pkg is None else int(len(pkg)), "cff_map_mismatches": mism, "blocks": {}}
    for b, d in blocks.items():
        res["blocks"][b] = {"groups": len(d["groups"]), "group_types": sorted(d["groups"]), "addresses": {s: len(d[s]) for s in ("cram", "cff", "dprio", "opt")},
                            "dprio_addr_range": [min(d["dprio"]), max(d["dprio"])] if d["dprio"] else None, "dprio_in_cff_range": sum(1 for x in d["dprio"] if x < C.cff.n_bits),
                            "cram_range": [min(d["cram"]), max(d["cram"])] if d["cram"] else None, "cff_range": [min(d["cff"]), max(d["cff"])] if d["cff"] else None}
        log.info("== %s: groups %d, addresses %s, instances %d", b, len(d["groups"]), res["blocks"][b]["addresses"], len(d["sites"]))
        log.info("   cram range %s cff range %s dprio range %s (in CFF bit range: %d of %d)", res["blocks"][b]["cram_range"], res["blocks"][b]["cff_range"],
                 res["blocks"][b]["dprio_addr_range"], res["blocks"][b]["dprio_in_cff_range"], len(d["dprio"]))
        for sp, cells in allcells[b].items():
            if not len(cells):
                continue
            ix = np.array([pos[int(c)] for c in cells])
            r = summarise(b, cells, img_u[ix], gate[:, ix], None if pkg is None else pkg[:, ix], ever_u[ix])
            res["blocks"][b][sp] = r
            log.info("   %-13s %s", sp, fmt(r))
        # per instance (site): cells whose image state differs from the gate idle pattern
        idle = gate.sum(0) * 2 > len(gate)
        per = {}
        for s, items in sorted(d["sites"].items()):
            cr = C.cram({a for sp, a in items if sp == "cram"})
            cf, _ = C.cffcells({a for sp, a in items if sp == "cff"})
            cells = np.concatenate([cr, cf])
            if not len(cells):
                continue
            ix = np.array([pos[int(c)] for c in cells])
            per[s] = (len(cells), int((img_u[ix] != idle[ix]).sum()), int((img_u[ix] & ~ever_u[ix]).sum()),
                      int(((gate[:, ix] != idle[None, ix]).sum(1)).max()))
        if len(per) > 1:
            nd = [s for s, v in per.items() if v[1] > v[3]]
            log.info("   instances with cells %d; instances where image!=idle exceeds the gate-build maximum for that instance: %d %s", len(per), len(nd), nd[:20])
            res["blocks"][b]["instances_exceeding_gate_max"] = nd
    pads_report(rbf, res)
    option_report(rbf, res)
    json.dump(res, open(OUT, "w"), indent=1, default=int)
    return 0


if __name__ == "__main__":
    sys.exit(main())
