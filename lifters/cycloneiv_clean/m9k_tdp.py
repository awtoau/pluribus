"""Cyclone IV GX M9K true dual port (bidir_dual_port) port decode (#165, #169): both ports the same word width, from the explicit-mode tables.

Group -> port pin tables are the libcomp_asmram constructor tables (ram_mapper.py, explicit modes 6..9 / 16..18):
  port A data   RAM_MS_DATA_INPUT   type 3 (DATAIN idx),  address RAM_MS_WRITE_ADDRESS_INPUT type 5 (+ type-5 entries of the data groups for x1..x8)
  port B data   RAM_MS_DATA_INPUT_B type 4 (DATAIN idx),  address RAM_MS_READ_ADDRESS_INPUT  type 6 (+ type-6 entries of the data-B groups)
Write enable with both wired: A = RAM_PIA_TO_INPUT_YGR gi 9, B = gi 11 (hl_ram_6 pin map); one wired gi alone is taken as A.
Output buffers: port A bit k = buffer k, port B bit k = buffer 18 + k (consumer buffers of hl_ram_6 / hl_mix_13 / hl_ram_7).
"""
import numpy as np

from . import m9kctl, ram_mapper as R

CAND = {0: (1,), 1: (2,), 2: (4,), 3: (8, 9), 4: (16, 18)}      # source: RAM_DATA_WRITE_MODE one-hot class (m9kctl) -> word widths
B_OFFSET = 18       # source: M4K_BUFFER index of port B bit 0 (hl_ram_6 / hl_mix_13 consumers use buffers 0..15 and 18..33)


def _tables(W):
    m = R.TDP_MODE[W]
    da = {ix: gi for gi, ty, ix in R.entries_mode("RAM_MS_DATA_INPUT", m) if ty == R.TYPE_DATA_A}
    db = {ix: gi for gi, ty, ix in R.entries_mode("RAM_MS_DATA_INPUT_B", m) if ty == R.TYPE_DATA_B}
    aa, ab = {}, {}
    for gi, ty, ix in R.entries_mode("RAM_MS_DATA_INPUT", m):
        if ty == R.TYPE_ADDR_A:
            aa.setdefault(ix, []).append(("RAM_MS_DATA_INPUT", gi))
    for gi, ty, ix in R.entries_mode("RAM_MS_WRITE_ADDRESS_INPUT", m):
        aa.setdefault(ix, []).append(("RAM_MS_WRITE_ADDRESS_INPUT", gi))
    for gi, ty, ix in R.entries_mode("RAM_MS_DATA_INPUT_B", m):
        if ty == R.TYPE_ADDR_B:
            ab.setdefault(ix, []).append(("RAM_MS_DATA_INPUT_B", gi))
    for gi, ty, ix in R.entries_mode("RAM_MS_READ_ADDRESS_INPUT", m):
        ab.setdefault(ix, []).append(("RAM_MS_READ_ADDRESS_INPUT", gi))
    return sorted(da), da, sorted(db), db, aa, ab


def is_tdp(mk, i):
    ctl = mk["ctl"]
    return bool(ctl[("RAM_USE_TRUE_DUAL_PORT_MODE", -1)][i, 0]) and not ctl[("RAM_USE_PACKED_MODE", -1)][i, 0] and \
        (mk["read_groups"][i] > 0 or (mk["data_b"][i] >= 0).any())


def decode(mk, i, outs, pin):
    """-> (spec dict, None) or (None, reason).  `outs` = routed M4K_BUFFER indices of the tile, `pin(sel)` = Verilog signal of a local-interconnect selection."""
    ctl = mk["ctl"]
    ca, cb = ctl[("RAM_DATA_WRITE_MODE", -1)][i], ctl[("RAM_DATA_WRITE_MODE_B", -1)][i]
    if ca.sum() != 1 or cb.sum() != 1:
        return None, "true dual port: word-width class not decoded"
    cls = int(ca.argmax())
    if cls != int(cb.argmax()) or cls not in CAND:
        return None, "true dual port: mixed or wide word width not modelled"
    wa = [k for k in range(18) if mk["data"][i, k] >= 0]
    wb = [k for k in range(18) if mk["data_b"][i, k] >= 0]
    oa = {o for o in outs if o < B_OFFSET}
    ob = {o - B_OFFSET for o in outs if o >= B_OFFSET}
    W = None
    for c in CAND[cls]:
        ia, da, ib, db, _, _ = _tables(c)
        if set(wa) <= set(da.values()) and set(wb) <= set(db.values()) and oa <= set(ia) and ob <= set(ib):
            W = c
            break
    if W is None:
        W = CAND[cls][-1]
    ia, da, ib, db, aa, ab = _tables(W)
    A = m9kctl.CLASS_A[cls]

    def addr(src, groups):
        out = []
        for ix in sorted(src, key=lambda ix: (ix - 8) % 13)[:A]:
            sel = -1
            for grp, gi in src[ix]:
                if grp == "RAM_MS_DATA_INPUT" and mk["data"][i, gi] >= 0:
                    sel = mk["data"][i, gi]
                elif grp == "RAM_MS_DATA_INPUT_B" and mk["data_b"][i, gi] >= 0:
                    sel = mk["data_b"][i, gi]
                elif grp == "RAM_MS_WRITE_ADDRESS_INPUT" and gi in m9kctl.WRITE_SLOTS and mk["waddr"][i, m9kctl.WRITE_SLOTS.index(gi)] >= 0:
                    sel = mk["waddr"][i, m9kctl.WRITE_SLOTS.index(gi)]
                elif grp == "RAM_MS_READ_ADDRESS_INPUT" and gi in mk["raddr"] and mk["raddr"][gi][i] >= 0:
                    sel = mk["raddr"][gi][i]
                if sel >= 0:
                    break
            out.append(pin(sel) if sel >= 0 else "1'b1")        # unconnected address pin = constant high (ledger M-019)
        return out
    w11, w9 = int(mk["pia_all"][i, 11]), int(mk["pia_all"][i, 9])
    both = w11 >= 0 and w9 >= 0
    return dict(W=W, A=A, cls=cls, data=[pin(mk["data"][i, da[ix]]) for ix in ia], data_b=[pin(mk["data_b"][i, db[ix]]) for ix in ib],
                addr=addr(aa, None), addr_b=addr(ab, None),
                we=pin(w9 if both else w11 if w11 >= 0 else w9), we_b=pin(w11) if both else "1'b0"), None
