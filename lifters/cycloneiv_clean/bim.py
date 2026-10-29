"""LOCAL_INTERCONNECT -> BLOCK_INPUT_MUX edges of the vertical IO (VIO) pad data pins (#165).  Vendor-derived only.

The routing graph has no fan-out for LOCAL_INTERCONNECT, and BLOCK_INPUT_MUX records carry no asm.ddb groups, so these edges are decoded here:
  - VIO site s (asmdb block type 6) = Column I/O pad s in pad-ddb order (pkgpad.io_site_pads); the pad names its tile and SUB_LOC k.
  - MIO_LABLINE_TO_DATA gi 0 of the site selects the LOCAL_INTERCONNECT index (muxsel input map, input number = LI index).
  - The BIM of the pad data pin is a function of SUB_LOC only (SUB_LOC_BIM below): label specimens, one build names pad site and BIM in
    its routing.rcf / postfit.vo (scripts/cycloneiv_clean_bim_specimens.py, 6 builds, 24 / 24 pads, 0 contradictions).
  - LI and BIM are records of the BIM tile.
Not decoded: HIO pads (block type 5: input map is a class-20 two-vector mux), MIO_LABLINE_TO_DATA gi 1 and the control-pin muxes (OE, CE, CLK,
CLR, SCLR) whose BIM index is not labelled by the specimens.
"""
import numpy as np

from . import ddb, muxsel, names, pkgpad
from . import plane as P

VIO = 6                                  # source: ASMDB_ARCH_GROUP_BLOCK_TYPE VIO (docs/cycloneiv-clean-io.md)
GROUP = "MIO_LABLINE_TO_DATA"            # source: libdb_asmdb arch-group-type table (gi 0, 1; one site per VIO pad)
# source: scripts/cycloneiv_clean_bim_specimens.py labels (routing.rcf BIM of each output pad, pad site from postfit.vo): SUB_LOC -> (BIM tile dx, BIM index)
SUB_LOC_BIM = {0: (1, 0), 1: (1, 14), 2: (0, 5), 3: (0, 13)}


class Implicit:
    def __init__(self, rt=None, n_real=0):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import asmdb_walk as W
        rt = rt or ddb.Routing()
        w, nm = W.Walk(), D.enum_tables()["arch_group_type"]
        g = next(g for g in w.groups() if g["btype"] == VIO and nm.get(g["type"]) == GROUP and g["gi"] == 0)
        pads = pkgpad.pads()
        site_pad = pkgpad.io_site_pads(pads)
        tab = P.load_tables()
        keys_all = rt.element_keys()
        order = np.argsort(keys_all, kind="stable")
        keys = keys_all[order]

        def find(q):
            i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
            return int(order[i]) if keys[i] == q else -1
        e_li, e_bim = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("BLOCK_INPUT_MUX")
        self.sites, self.mux, self.eid, src, dst = [], [], [], [], []
        n = n_real
        for s in range(len(g["paths"])):
            if (VIO, s) not in site_pad:
                continue
            x, y, k = pkgpad.pad_site(pads[site_pad[(VIO, s)]])
            if k not in SUB_LOC_BIM:
                continue
            dx, i_bim = SUB_LOC_BIM[k]
            bim = find(ddb.element_key(e_bim, x + dx, y, 0, i_bim))
            m = muxsel.MapSelect(w, g, np.zeros(1, np.int64), s, tab)
            ids = np.full(len(m.aux), -1, np.int64)
            for i in range(len(m.aux)):
                if m.aux[i] == muxsel.ABSENT or m.aux[i] >= len(m.first_off):
                    continue
                li = find(ddb.element_key(e_li, x + dx, y, 0, i))
                if li >= 0 and bim >= 0:
                    ids[i] = n
                    n += 1
                    src.append(li)
                    dst.append(bim)
            self.sites.append((x, y, k))
            self.mux.append(m)
            self.eid.append(ids)
        self.esrc = np.asarray(src, np.int32)
        self.edst = np.asarray(dst, np.int32)
        self.n_real = n_real

    def apply(self, bits):
        """-> programmed implicit edge ids: one per pad whose gi 0 map resolves to exactly one existing LOCAL_INTERCONNECT."""
        out = []
        for m, ids in zip(self.mux, self.eid):
            sel = int(m.select(bits)[0])
            if sel >= 0 and ids[sel] >= 0:
                out.append(ids[sel])
        return np.asarray(out, np.int64)
