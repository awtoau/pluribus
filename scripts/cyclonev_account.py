#!/usr/bin/env python3.15t
"""Whole-bitstream accounting for the native Cyclone V decoder (claim 3 of docs/altera/cycloneV/cyclonev-native-decoder.md).

Every set configuration bit is either claimed by a named feature (a table entry that reads it) or listed as unclaimed.
Frame overhead (headers, EDCRC, CRC-16, option/PRAM page checksums) is verified, not counted as a feature.
"""
import numpy as np

import cyclonev_decode as cd

CLS = {"route": 1, "bmux": 2, "inv": 3, "one": 4}


def claim_maps(m):
    """Static claim count + first class per CRAM position, from the claims the model collected."""
    n = m.sx * m.sy
    cnt = np.zeros(n, np.uint8)
    cls = np.zeros(n, np.uint8)
    for name, pos in m.claims["cram"]:
        p = np.unique(np.asarray(pos).ravel())
        cnt[p] = np.minimum(cnt[p].astype(np.int32) + 1, 255).astype(np.uint8)
        c0 = cls[p]
        cls[p] = np.where(c0 == 0, CLS[name], c0)
    return cnt, cls


def tile_type_map(m):
    """Per CRAM position -> tile-type id (0 = outside tiles: header rows / edges)."""
    g = m.g
    xb = np.array(g["x_to_bx"] + [m.sx])
    x = np.arange(m.sx)
    tx = np.searchsorted(xb, x, side="right") - 1
    tx = np.minimum(tx, len(g["x_to_bx"]) - 1)
    y = np.arange(m.sy)
    ty = (y - 2) // 86
    names = ["outside"]
    code = {}
    tt = np.zeros((m.sy, m.sx), np.uint8)
    # column type per tile column, tile row membership; DSP2 rows are part of the DSP tile
    col = [g["column_types"][t] for t in tx]
    for ctype in sorted(set(col)):
        code[ctype] = len(names)
        names.append(ctype)
    ids = np.array([code[c] for c in col], np.uint8)
    ok_y = (y >= 2) & (ty < g["tile_sy"])
    tt[:] = ids[None, :]
    tt[~ok_y, :] = 0
    return tt.reshape(-1), names


def frame_check(m, data):
    geo = m.geo
    f = np.frombuffer(m.bits.framed, np.uint8).reshape(geo.sx, geo.cfb)
    out = {"frames": geo.sx, "frame_bytes": geo.cfb}
    # CRC-16 over bytes [0, cfb-2)
    crc = cd.crc16_rows(f[:, :geo.cfb - 2])
    stored = f[:, geo.cfb - 2].astype(np.uint16) | (f[:, geo.cfb - 1].astype(np.uint16) << 8)
    out["crc16_ok"] = int((crc == stored).sum())
    # EDCRC
    nb = 32 * geo.cram_frame_bits
    contrib, init = cd.edcrc_contrib(nb)
    k = np.arange(nb)
    bitid, block = k // geo.cram_frame_bits, k % geo.cram_frame_bits
    pos = 224 + (31 - bitid) + 32 * block
    bits = (f[:, pos >> 3] >> (pos & 7).astype(np.uint8)) & 1
    calc = np.full(geo.sx, init, np.uint32)
    for j in range(nb):
        sel = bits[:, j] != 0
        calc[sel] ^= contrib[j]
    got = (f[:, geo.cfb - 8].astype(np.uint32) | (f[:, geo.cfb - 7].astype(np.uint32) << 8)
           | (f[:, geo.cfb - 6].astype(np.uint32) << 16) | (f[:, geo.cfb - 5].astype(np.uint32) << 24))
    zones = m.g["noedcrc_zones"]
    exp_has = np.zeros(geo.sx, bool)
    idx = 0
    for x in range(geo.sx):
        exp_has[x] = not (idx < len(zones) and x >= zones[idx])
        if idx < len(zones) and x == zones[idx] + 255:
            idx += 1
    ok = np.where(exp_has, calc == got, got == 0)
    out["edcrc_ok"] = int(ok.sum())
    out["edcrc_frames_with_crc"] = int(exp_has.sum())
    out["edcrc_bad_frames"] = [int(i) for i in np.nonzero(~ok)[0][:10]]
    # header bits [0,224): only the documented sync bytes may be set
    hdr = f[:, :28].copy()
    hdr[0, :3] = 0
    hdr[-1, :3] = 0
    out["header_extra_set_bits"] = int(np.unpackbits(hdr).sum())
    out["header_sync_ok"] = bool(f[0, :3].tolist() == [0x84, 0x3E, 0x01] and f[-1, :3].tolist() == [0x42, 0x9F, 0x00])
    # bytes cfb-4, cfb-3: not covered by any rule
    out["frame_gap_bytes_set_bits"] = int(np.unpackbits(f[:, geo.cfb - 4:geo.cfb - 2]).sum())
    # frame bit slots for rows 24..31: present in the frame, never loaded by libmistral
    slot_bits = 0
    for y in range(24, 32):
        p = geo.slot_pos(y)
        slot_bits += int(((f[:, p >> 3] >> (p & 7)) & 1).sum())
    out["rows_24_31_slot_set_bits"] = slot_bits
    # PRAM pages + option frame
    a = m.bits.raw
    pages = []
    for pg in range(geo.pram_blocks):
        off = geo.oram_frame_bytes + pg * geo.pram_frame_bytes
        pg_bytes = a[off:off + geo.pram_frame_bytes]
        pages.append(cd.crc16(pg_bytes[:-2].tobytes()) == int(pg_bytes[-2]) | (int(pg_bytes[-1]) << 8))
    out["pram_page_crc16_ok"] = [bool(p) for p in pages]
    out["oram_checksum_ok"] = bool(cd.crc16(a[0x84:0x126].tobytes()) == (int(a[0x126]) | (int(a[0x127]) << 8)))
    comp = m.bits.compressed
    if comp:
        end = comp[0] + (comp[1] + 1) // 2
        out["cram_stream_bytes"] = end - comp[0]
        out["postamble_bytes"] = int(len(a) - end)
        out["postamble_expected"] = int(m.g["postamble_1"] + 2 + 10 + 2 + m.g["postamble_2"])
    return out


def account(m, data, want_lists=False):
    """m: Model decoded with claims=True and with bt_lines() already evaluated."""
    geo = m.geo
    cnt, cls = claim_maps(m)
    tt, names = tile_type_map(m)
    cram = m.bits.cram
    loaded = np.zeros_like(cram, dtype=bool).reshape(m.sy, m.sx)
    loaded[32:, :] = True
    loaded = loaded.reshape(-1)
    setb = (cram != 0) & loaded
    claimed = cnt > 0
    res = {"cram": {"loaded_bits": int(loaded.sum()), "set": int(setb.sum()), "set_claimed": int((setb & claimed).sum()),
                    "set_unclaimed": int((setb & ~claimed).sum()), "claimed_positions": int(claimed.sum()),
                    "multi_claimed_positions": int((cnt > 1).sum()),
                    "set_multi_claimed": int((setb & (cnt > 1)).sum())}}
    by = {}
    for tid, nm in enumerate(names):
        sel = tt == tid
        by[nm] = {"set": int((setb & sel).sum()), "claimed": int((setb & sel & claimed).sum()),
                  "unclaimed": int((setb & sel & ~claimed).sum()), "positions": int((claimed & sel).sum())}
    res["cram"]["by_tile_type"] = by
    res["cram"]["forced_one_set"], res["cram"]["forced_one_total"] = m.ones_set
    byc = {}
    for c, i in CLS.items():
        byc[c] = int((setb & (cls == i)).sum())
    res["cram"]["set_by_first_claim_class"] = byc
    xb = np.array(m.g["x_to_bx"] + [m.sx])
    un = []
    for p in np.nonzero(setb & ~claimed)[0]:
        x, y = int(p) % m.sx, int(p) // m.sx
        tx = min(int(np.searchsorted(xb, x, side="right")) - 1, len(m.g["x_to_bx"]) - 1)
        ty = (y - 2) // 86
        tn = names[int(tt[p])]
        un.append([tn, tx, ty, x - m.g["x_to_bx"][tx], y - (2 + 86 * ty)])
    res["cram"]["unclaimed_rel"] = un
    # PRAM
    pr = {}
    for s in range(32):
        n = len(m.bits.pram[s])
        if not n:
            continue
        cl = np.zeros(n, bool)
        c = m.claims["pram"][s]
        if c:
            cl[np.unique(np.asarray(c))] = True
        st = m.bits.pram[s] != 0
        pr[str(s)] = {"bits": n, "set": int(st.sum()), "set_claimed": int((st & cl).sum()),
                      "set_unclaimed": int((st & ~cl).sum()), "positions_claimed": int(cl.sum())}
    res["pram"] = pr
    oc = set(m.claims["oram"])
    oset = [(s, b) for s in range(32) for b in range(40) if (m.bits.oram[s] >> b) & 1]
    res["oram"] = {"set": len(oset), "set_claimed": sum(1 for p in oset if p in oc),
                   "set_unclaimed": sum(1 for p in oset if p not in oc), "positions_claimed": len(oc),
                   "unclaimed_list": [list(p) for p in oset if p not in oc]}
    base = list(m.g["default_oram"])
    dflt = [int(v) for v in base[:8]] + [0xFFFFFFFFFF] * 4 + [int(v) for v in base[8:12]] + [0xFFFFFFFFFF] * 16
    res["oram"]["unclaimed_differ_from_die_default"] = [
        [s, b] for (s, b) in oset if (s, b) not in oc and not (dflt[s] >> b) & 1]
    res["oram"]["unclaimed_clear_vs_default"] = [
        [s, b] for s in range(32) for b in range(40)
        if (s, b) not in oc and ((dflt[s] >> b) & 1) and not (m.bits.oram[s] >> b) & 1]
    res["frames"] = frame_check(m, data)
    return res
