#!/usr/bin/env python3.15t
"""Package-consistent rbf cells (#172): cells equal across every speed grade of one package but different between packages (speed-grade / placement noise removed).

  python3.15t scripts/cycloneiv_pkgtest_consistent.py [kind: loc|free]
Per package pair: count of such cells in the header frame, periphery frames (split: CFF table / not in table) and CRAM; CFF cells are attributed to asmdb groups, CRAM cells to
the IO-block CRAM groups (io_decode.Chain.cram) or reported as unattributed.  Log: tmp/logs/cycloneiv_pkgtest_consistent.log
"""
import collections
import itertools
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_pkgtest_diff as D  # noqa: E402
from lifters.cycloneiv_clean import io_decode as ID  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402

log = logging.getLogger("pkgtest_consistent")
ROOT = REPO / "tmp" / "pkgtest"
# source: part names built by scripts/cycloneiv_pkgtest.py DEVICES, grouped by package
GROUPS = {"F484": ["CF23C8", "CF23C7", "CF23I7"], "F672": ["DF27C7", "DF27I7"], "F896": ["DF31C7", "DF31I7"]}


def bits(path):
    return np.unpackbits(np.fromfile(path, np.uint8), bitorder="little")


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "loc"
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pkgtest_consistent.log", "w"), logging.StreamHandler()])
    own = D.Owners()
    chain = ID.Chain()
    # CRAM cells of the IO-block groups, as rbf bit offsets
    cram_owner = {}
    for site, gs in chain.cram.items():
        for g, addrs in gs.items():
            r, j, k = P.address_to_plane(np.asarray(addrs, np.int64))
            for off in P.rbf_bit_offset(r, j, k).tolist():
                cram_owner[off] = (site, g)
    data = {pkg: [bits(ROOT / f"{kind}_EP4CGX150{d}" / "bitstream.rbf") for d in ds] for pkg, ds in GROUPS.items()}
    cell_of = {tuple(c): int(i) for c, i in zip(own.cff.cells, own.cff.idx)}
    hdr0, per0 = P.RBF_HEADER * 8, (P.RBF_HEADER + P.RBF_FRAME_BYTES) * 8
    cram0 = (P.RBF_HEADER + P.RBF_PRE_FRAMES * P.RBF_FRAME_BYTES) * 8
    for a, b in itertools.combinations(GROUPS, 2):
        cons = {}
        for pkg in (a, b):
            ref = data[pkg][0]
            same = np.ones(len(ref), bool)
            for o in data[pkg][1:]:
                same &= o == ref
            cons[pkg] = same
        n = min(len(data[a][0]), len(data[b][0]))
        diff = cons[a][:n] & cons[b][:n] & (data[a][0][:n] != data[b][0][:n])
        idx = np.nonzero(diff)[0]
        hdr = idx[(idx >= hdr0) & (idx < per0)]
        per = idx[(idx >= per0) & (idx < cram0)]
        cram = idx[idx >= cram0]
        fr = lambda o: ((o // 8 - P.RBF_HEADER) // P.RBF_FRAME_BYTES, (o // 8 - P.RBF_HEADER) % P.RBF_FRAME_BYTES, o % 8)
        in_tab = [o for o in per if fr(int(o)) in cell_of]
        cram_io = [o for o in cram if int(o) in cram_owner]
        log.info("%s vs %s [%s]: consistent differing cells: header-frame %d, periphery %d (in CFF table %d, not in table %d), CRAM %d (in IO-block CRAM groups %d)",
                 a, b, kind, len(hdr), len(per), len(in_tab), len(per) - len(in_tab), len(cram), len(cram_io))
        log.info("   header-frame bytes: %s", sorted({int(o // 8 - P.RBF_HEADER - P.RBF_FRAME_BYTES * 0) - 0 for o in hdr}))
        grp = collections.Counter()
        for o in in_tab:
            ow = own.owner.get(cell_of[fr(int(o))], [])
            grp[(ow[0][0], ow[0][2]) if ow else ("none", "")] += 1
        log.info("   CFF cells by (block type, group): %s", dict(sorted(grp.items(), key=lambda kv: -kv[1])[:25]))
        log.info("   not-in-table periphery cells (frame, byte, bit): %s", sorted(fr(int(o)) for o in per if fr(int(o)) not in cell_of)[:30])
        cg = collections.Counter(cram_owner[int(o)][1] for o in cram_io)
        log.info("   IO CRAM groups: %s; unattributed CRAM cells %d", dict(cg), len(cram) - len(cram_io))


if __name__ == "__main__":
    main()
