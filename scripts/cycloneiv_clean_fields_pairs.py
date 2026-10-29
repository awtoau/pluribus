#!/usr/bin/env python3
"""Pair diffs of existing corpus builds against the vendor field map (#169).  No new builds.

  python3.15t scripts/cycloneiv_clean_fields_pairs.py      # log tmp/logs/cycloneiv_clean_fields_pairs.log, json tmp/cycloneiv_clean/fields_pairs.json

Pair = two builds differing in ONE named feature (design.toml purpose / top.v diff).  Diff = CRAM plane cells that differ between the two rbfs.
Each diff cell is classified: group bits of the instance the feature sits in (by vendor group name), asm.ddb routing address, other
(any other instance's group bit), unclaimed (missing).  The instance is the one the QSF location names; the M9K column / row is
chosen as the unique instance whose group bits contain every RAM_CONTENT diff cell (no fitted offset).
"""
import collections
import json
import logging
import os
import re
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import asmdb_walk as W, ddb, fields as F, plane as P, sofio  # noqa: E402
import cycloneiv_clean_dirt as D  # noqa: E402

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
LABS = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_labs.json")      # fitter probe output (vendor tool), LAB columns
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_fields_pairs.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "fields_pairs.json")
LOC = re.compile(r"(LCCOMB|FF|M9K)_X(\d+)_Y(\d+)_N(\d+)")


def cell_id(r, j, k):
    return (np.asarray(r, np.int64) * 800 + j) * 8 + k


def to_cells(addr, tables):
    r, j, k = P.sof_to_rbf(np.asarray(addr, np.int64), tables)
    return cell_id(r, j, k)


def diff_cells(a, b):
    """plane cell ids where two rbf CRAMs differ."""
    x = sofio.rbf_cram(os.path.join(CORPUS, a, "bitstream.rbf")) ^ sofio.rbf_cram(os.path.join(CORPUS, b, "bitstream.rbf"))
    r, j, k = np.nonzero(x)
    return cell_id(r, j + 1, k)


class Model:
    def __init__(self):
        self.tables = P.load_tables()
        self.w = W.Walk()
        self.names = D.enum_tables()
        self.flds = F.fields(self.w, self.names)
        a = np.asarray(ddb.Asm().pos, np.int64) & ddb.ADDR_MASK
        self.asm_cells = np.unique(to_cells(a[a < P.N_BITS], self.tables))
        self.bases = {bt: F.bases(self.w, bt) for bt in F.PLACED}
        self.labs = json.load(open(LABS))["labs"]
        self.lab_xs = sorted({x for x, _ in self.labs})

    def instance_cells(self, btype, idx):
        """{(group name, gi, kind): cell id array} of one instance."""
        out = {}
        b = self.bases[btype][idx:idx + 1]
        for f in self.flds:
            if f.btype != btype:
                continue
            for si, site in enumerate(f.sites):
                for off in site:
                    out.setdefault((f.name, f.gi, "path", si), []).append(to_cells(F.absolute(b, off).ravel(), self.tables))
            for off in f.aux:
                out.setdefault((f.name, f.gi, "aux", 0), []).append(to_cells(F.absolute(b, off).ravel(), self.tables))
        return {k: np.unique(np.concatenate(v)) for k, v in out.items()}

    def classify(self, diff, inst):
        owner = collections.defaultdict(list)
        for k, c in inst.items():
            for x in np.intersect1d(diff, c):
                owner[int(x)].append(k)
        in_asm = np.isin(diff, self.asm_cells)
        rows = collections.Counter()
        names = collections.Counter()
        for i, x in enumerate(diff.tolist()):
            if x in owner:
                rows["group"] += 1
                for k in owner[x]:
                    names[(k[0], k[1], k[3], k[2])] += 1
            elif in_asm[i]:
                rows["asm_ddb"] += 1
            else:
                rows["unclaimed"] += 1
        return rows, names

    def lab_index(self, x, y):
        return self.lab_xs.index(x) * F.ROWS_PER_COLUMN + (y - 1)


def loc_of(build, kind):
    t = open(os.path.join(CORPUS, build, "design.toml")).read()
    m = re.search(kind + r"_X(\d+)_Y(\d+)_N(\d+)", t)
    return tuple(map(int, m.groups())) if m else None


def lab_pairs():
    """base gxct_a_pos_bPP vs gxct_a_pos_PP<ctrl>: r0 at FF_X10_Y10_N1, LE position PP (one control signal added / changed)."""
    out = []
    for pp in range(8):
        base = f"gxct_a_pos_b{pp:02d}"
        for ctl in ("aclr", "ena", "sclr", "sload", "clkKB"):
            v = f"gxct_a_pos_{pp:02d}{ctl}"
            if os.path.exists(os.path.join(CORPUS, v, "bitstream.rbf")) and os.path.exists(os.path.join(CORPUS, base, "bitstream.rbf")):
                out.append((base, v, ctl, pp))
    return out


def _src_lines(b):
    p = os.path.join(CORPUS, b, "src")
    out = []
    for f in sorted(os.listdir(p)):
        if f.endswith((".v", ".mif")):
            out += [(f, ln) for ln in open(os.path.join(p, f)).read().splitlines()]
    return out


def src_diff(a, b):
    """number of source lines (file, text) present in only one of the two builds."""
    x, y = collections.Counter(_src_lines(a)), collections.Counter(_src_lines(b))
    return sum(((x - y) + (y - x)).values())


def m9k_pairs():
    """(base, variant): the base of the same family whose sources differ least from the variant; accepted only when <= 4 source lines differ."""
    ok = lambda d: os.path.exists(os.path.join(CORPUS, d, "bitstream.rbf")) and os.path.isdir(os.path.join(CORPUS, d, "src"))
    ds = [d for d in sorted(os.listdir(CORPUS)) if d.startswith("gxm9k_") and ok(d)]
    fam = collections.defaultdict(list)
    for d in ds:
        m = re.match(r"(gxm9k_(?:w|m)(?:_x\d+_y\d+_n\d+)?)_(.*)", d) or re.match(r"(gxm9k_[bh]\d+)_(.*)", d)
        if m:
            fam[m[1]].append(d)
    out = []
    for f, members in fam.items():
        bases = [d for d in members if "base" in d]
        for d in members:
            if d in bases:
                continue
            best = min(((src_diff(b, d), b) for b in bases), default=None)
            if best and best[0] <= 4:
                out.append((best[1], d, best[0]))
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log = logging.getLogger("pairs")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    m = Model()
    res = {"lab": [], "m9k": []}
    lab_cache = {}
    for base, v, ctl, pp in lab_pairs():
        d = diff_cells(base, v)
        x, y, _ = loc_of(v, "FF")
        idx = m.lab_index(x, y)
        inst = lab_cache.setdefault(idx, m.instance_cells(18, idx))
        rows, names = m.classify(d, inst)
        row = dict(base=base, variant=v, ctl=ctl, pos=pp, site=(x, y), diff=int(len(d)), **rows,
                   groups=sorted((f"{k[0]}#{k[1]}@{k[2]}:{k[3]}", n) for k, n in names.items()))
        res["lab"].append(row)
        log.info("LAB %s", json.dumps(row))
    # M9K: instance = argmax of diff cells inside any instance's group bits
    nm = len(m.bases[39])
    allc = [m.instance_cells(39, i) for i in range(nm)] if False else None
    pc = []
    for i in range(nm):
        b = m.bases[39][i:i + 1]
        cs = [to_cells(F.absolute(b, o).ravel(), m.tables) for f in m.flds if f.btype == 39 for site in f.sites for o in site]
        pc.append(np.unique(np.concatenate(cs)))
    log.info("M9K instances built %d", nm)
    cache = {}
    for base, v, nd in m9k_pairs():
        d = diff_cells(base, v)
        hits = np.array([np.isin(d, c).sum() for c in pc])
        idx = int(hits.argmax())
        uniq = int((hits == hits.max()).sum()) == 1
        site = loc_of(v, "M9K")
        inst = cache.setdefault(idx, m.instance_cells(39, idx))
        rows, names = m.classify(d, inst)
        row = dict(base=base, variant=v, src_lines=nd, site=site, instance=idx, col=idx // 90, row=idx % 90, unique=uniq, diff=int(len(d)), **rows,
                   groups=sorted((f"{k[0]}#{k[1]}:{k[3]}", n) for k, n in names.items()))
        res["m9k"].append(row)
        log.info("M9K %s", json.dumps(row))
    json.dump(res, open(OUT, "w"), indent=1, default=int)
    return 0


if __name__ == "__main__":
    sys.exit(main())
