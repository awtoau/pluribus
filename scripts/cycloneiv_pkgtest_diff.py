#!/usr/bin/env python3.15t
"""Diff two or more rbf files of the package experiment (#172): preamble, header frame (option register), periphery frames (CFF cells -> owning asmdb group / site), CRAM frames.

  python3.15t scripts/cycloneiv_pkgtest_diff.py REF.rbf OTHER.rbf [...]
Every differing CFF bit is reported with (block type, site, group) of every asmdb group holding it, plus the pad of the site; option bits via options.py.
Log: tmp/logs/cycloneiv_pkgtest_diff.log
"""
import collections
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from lifters.cycloneiv_clean import cycloneiv_io as IO  # noqa: E402
from lifters.cycloneiv_clean import options as OPT  # noqa: E402
from lifters.cycloneiv_clean import pkgpad as K  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402

log = logging.getLogger("pkgtest_diff")
PRE, FB, NPRE = P.RBF_HEADER, P.RBF_FRAME_BYTES, P.RBF_PRE_FRAMES


class Owners:
    """CFF bit index -> [(block type, site, group name)] over every asmdb group of every block type; cell (frame, byte, bit) -> CFF bit."""

    def __init__(self):
        import cycloneiv_clean_dirt as D
        from lifters.cycloneiv_clean import asmdb_walk as W
        self.cff = IO.Cff()
        names = D.enum_tables()["arch_group_type"]
        w = W.Walk()
        self.owner = collections.defaultdict(list)
        for o in w.groups():
            if o["cls"] not in (5, 6, 7):
                continue
            nm = names.get(o["type"], str(o["type"]))
            n = len(o["bits"]) if o["cls"] == 7 else len(o["paths"])
            for s in range(n):
                for a in W._site_bits(w, o, s):
                    if a >> 29 == 5:
                        self.owner[a & 0x1FFFFFFF].append((o["btype"], s, nm))
        self.cell = {tuple(c): int(i) for c, i in zip(self.cff.cells, self.cff.idx)}
        pads = K.pads()
        site_pad = K.io_site_pads(pads)
        self.site_fn = {s: (pads[j]["strs"][1], pads[j]["strs"][4]) for s, j in site_pad.items()}


def frames(path):
    b = np.fromfile(path, np.uint8)
    return b, b[PRE:PRE + NPRE * FB].reshape(NPRE, FB)


def diff(ref, other, own):
    rb, rf = frames(ref)
    ob, of = frames(other)
    out = {"len": (len(rb), len(ob)), "preamble_bytes_differ": [int(i) for i in np.nonzero(rb[:PRE] != ob[:PRE])[0]]}
    d0 = np.nonzero(rf[0] != of[0])[0]
    out["header_frame_bytes_differ"] = [(int(i), f"{rf[0][i]:02x}->{of[0][i]:02x}") for i in d0]
    bits = []
    for fr in range(1, NPRE):
        for by in np.nonzero(rf[fr] != of[fr])[0]:
            x = int(rf[fr][by]) ^ int(of[fr][by])
            bits += [(fr, int(by), k) for k in range(8) if x >> k & 1]
    out["periphery_cells_differ"] = len(bits)
    cff = collections.defaultdict(list)
    for c in bits:
        cff[own.cell.get(c)].append(c)
    out["cff"] = {i: (cs, own.owner.get(i, []), int(rf[cs[0][0]][cs[0][1]] >> cs[0][2] & 1), int(of[cs[0][0]][cs[0][1]] >> cs[0][2] & 1)) for i, cs in cff.items() if i is not None}
    out["periphery_cells_not_in_cff_table"] = len(cff.get(None, []))
    cr, co = rb[PRE + NPRE * FB:], ob[PRE + NPRE * FB:]
    n = min(len(cr), len(co))
    dd = np.nonzero(cr[:n] != co[:n])[0]
    out["cram_bytes_differ"] = int(len(dd))
    out["cram_frames_differ"] = sorted({int(i) // FB for i in dd})
    out["tail_len"] = (len(cr) - 6154 * FB, len(co) - 6154 * FB)
    hb = [(int(i), k) for i in d0 for k in range(8) if (int(rf[0][i]) ^ int(of[0][i])) >> k & 1]
    cells = {tuple(c): e for e in OPT.entries() for c in e["rbf_cells"]}
    out["header_bits"] = [(i, k, rf[0][i] >> k & 1, of[0][i] >> k & 1, (cells[(0, i, k)]["index"], cells[(0, i, k)]["klass"], cells[(0, i, k)].get("name"), cells[(0, i, k)].get("function")) if (0, i, k) in cells else "not an option cell") for i, k in hb]
    return out


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pkgtest_diff.log", "w"), logging.StreamHandler()])
    own = Owners()
    ref, others = sys.argv[1], sys.argv[2:]
    for o in others:
        r = diff(ref, o, own)
        log.info("== %s vs %s", Path(ref).parent.name, Path(o).parent.name)
        for k, v in r.items():
            if k == "cff":
                log.info("cff bits differing: %d", len(v))
                per = collections.defaultdict(lambda: collections.defaultdict(list))
                for i, (cs, ow, a, b) in sorted(v.items()):
                    for t, st, g in ow[:1] or [("none", i, "none")]:
                        per[(t, st)][g].append((i, a, b))
                for (t, st), gs in sorted(per.items(), key=lambda kv: str(kv[0])):
                    log.info("  site %s %s: %s", (t, st), own.site_fn.get((t, st)), {g: f"{len(x)} bits {x[0][1]}->{x[0][2]}" + ("" if len({(y[1], y[2]) for y in x}) == 1 else " mixed") for g, x in gs.items()})
            else:
                log.info("%s: %s", k, v if not isinstance(v, list) or len(v) < 40 else f"{len(v)} items {v[:40]}")


if __name__ == "__main__":
    main()
