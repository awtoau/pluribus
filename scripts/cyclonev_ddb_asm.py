#!/usr/bin/env python3.15t
"""Cyclone V `asm.ddb` (Quartus route-assembler database) reader + comparison with the native routing tables.

Format: docs/cyclonev-ddb-format.md "asm". Body header = u32 4, u32 N, u32 N, u16 max_n, u16 max_nb. Body = one record per routing SOURCE node; a record lists, for each
destination mux the source fans out to, the CRAM bits that select it (2-hot / 1-hot code positions).

  python3.15t scripts/cyclonev_ddb_asm.py stats  --die e50f|gt150f
  python3.15t scripts/cyclonev_ddb_asm.py compare --die e50f|gt150f      # vs scripts/cyclonev_native_tables.py (Mistral-sourced)
Heavy (holds ~3-4 GB for e50f, more for larger dies): takes heavy_guard.heavy_lock.
Logs tmp/logs/cyclonev_ddb_asm.log; results tmp/cyclonev_ddb/<die>_asm_compare.json.
"""
import argparse
import collections
import json
import logging
import os
import struct
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402

log = logging.getLogger("cyclonev_ddb_asm")
DEVINFO = dd.DEVINFO + "/cyclonev"
DIES = {"e50f": ("cyclonev_e50f", "5CEBA4U19C8"), "gt150f": ("cyclonev_d6_gtf150", "5CEBA7U19C8")}


def asm_path(die):
    d, _ = DIES[die]
    return f"{DEVINFO}/{d}/ddb_{d}_asm.ddb"


class RecordStream:
    """Streaming parser: body = u32 version(4), u32 N, u32 N, u16 max n, u16 max nb, then N records
         record = u16 n, n*u16 vals, u16 nb, nb*(i32 delta, i32 flag), i32 trailer      (n = 0: 8 bytes)
       Positions: one running sum over all deltas of all records (trailer ignored), taken modulo `modulus`.
       Yields batches {rec_n, rec_nb, vals(list), P, flag, trailer}."""

    def __init__(self, path, modulus, batch_records=100_000):
        self.path, self.mod, self.batch = path, modulus, batch_records
        self.hdr = dd.read_header(path)

    def __iter__(self):
        blocks = dd.iter_body(self.path, self.hdr)
        buf = bytearray()
        eof = False

        def fill(need):
            nonlocal eof
            while len(buf) < need and not eof:
                try:
                    buf.extend(next(blocks))
                except StopIteration:
                    eof = True

        fill(16)
        ver, n1, n2, self.max_n, self.max_nb = struct.unpack_from("<IIIHH", buf, 0)
        if ver != 4 or n1 != n2:
            raise dd.DdbError(f"asm body header {ver},{n1},{n2}")
        del buf[:16]
        self.n_records = n1
        S = 0
        done = 0
        unp = struct.unpack_from
        while done < n1:
            rn, rnb, rflag, rtr, deltas, valsl = [], [], [], [], [], []
            for _ in range(min(self.batch, n1 - done)):
                fill(1 << 16)
                if eof and len(buf) < 8:
                    if any(buf):
                        raise dd.DdbError("truncated record")
                    done = n1                 # < 8 zero bytes left: padding of the zero tail
                    break
                n, = unp("<H", buf, 0)
                nb, = unp("<H", buf, 2 + 2 * n)
                size = 4 + 2 * n + 8 * nb + 4
                if len(buf) < size:
                    fill(size)
                    if len(buf) < size:
                        raise dd.DdbError("truncated record")
                rn.append(n); rnb.append(nb)
                valsl.append(unp("<%dH" % n, buf, 2))
                if nb:
                    a = np.frombuffer(bytes(buf[4 + 2 * n:4 + 2 * n + 8 * nb]), "<i4").reshape(nb, 2)
                    deltas.append(a[:, 0]); rflag.append(a[:, 1])
                rtr.append(unp("<i", buf, size - 4)[0])
                del buf[:size]
                done += 1
            rnb_a = np.array(rnb, np.int64)
            d = np.concatenate(deltas).astype(np.int64) if deltas else np.zeros(0, np.int64)
            P = S + np.cumsum(d)
            if len(P):
                S = int(P[-1])
            yield dict(n=np.array(rn, np.int32), nb=rnb_a, vals=valsl, P=P % self.mod, S_end=S,
                       flag=np.concatenate(rflag) if rflag else np.zeros(0, np.int32), trailer=np.array(rtr, np.int32))
        fill(1)
        if len(buf) and any(buf):
            raise dd.DdbError(f"{len(buf)} unparsed bytes after {n1} records")


def build_maps(model):
    """Mistral-sourced native tables -> position ownership maps."""
    import cyclonev_native_tables as nt
    t = nt.load(model)
    g = t["geom"]
    W, H = g["cram_sx"], g["cram_sy"]
    M = W * H
    r = t["routes"]
    pats, rxy, rvals = t["patterns"], t["rxy"], t["rvals"]
    pat, fw, span, src, so, dest = r["pat"], r["fw"], r["span"], r["src"], r["src_off"], r["dest"]
    owner = np.full(M, -1, np.int32)
    bitk = np.full(M, -1, np.int8)
    maxbits = max(p["bits"] for p in pats)
    slot_tab = np.full((len(pats) + 1, 1 << maxbits), -1, np.int16)
    for p in np.unique(pat):
        if p == 0xFE:
            continue
        pt = pats[p]
        xy = rxy[pt["o_xy"] * 2:(pt["o_xy"] + pt["bits"]) * 2].reshape(-1, 2)
        idx = np.nonzero(pat == p)[0]
        f = fw[idx].astype(np.int64)
        for k in range(pt["bits"]):
            pos = f + int(xy[k, 0]) + int(xy[k, 1]) * W
            owner[pos] = idx
            bitk[pos] = k
        for s, c in enumerate(rvals[pt["o_vals"]:pt["o_vals"] + pt["span"]]):
            if c and slot_tab[p, c] < 0:
                slot_tab[p, c] = s
    return t, M, owner, bitk, slot_tab


def mistral_triples(t):
    """(source key, dest mux, slot, dest type id) for every non-default slot of every regular mux."""
    r = t["routes"]
    pats, rvals = t["patterns"], t["rvals"]
    pat, span, src, so, dest = r["pat"], r["span"], r["src"], r["src_off"], r["dest"]
    S, Mx, Sl = [], [], []
    for p in np.unique(pat):
        if p == 0xFE:
            continue
        pt = pats[p]
        idx = np.nonzero(pat == p)[0]
        for s, c in enumerate(rvals[pt["o_vals"]:pt["o_vals"] + pt["span"]]):
            if c:
                S.append(src[so[idx] + s]); Mx.append(idx); Sl.append(np.full(len(idx), s, np.int16))
    return np.concatenate(S), np.concatenate(Mx), np.concatenate(Sl)


def compare(die):
    _, model = DIES[die]
    t0 = time.time()
    t, M, owner, bitk, slot_tab = build_maps(model)
    r = t["routes"]
    names = r["type_names"]
    pat, so, src, dest = r["pat"], r["src_off"], r["src"], r["dest"]
    tsrc, tmux, tslot = mistral_triples(t)
    log.info("%s: tables %d muxes, %d triples (%.1fs); M=%d", die, len(pat), len(tsrc), time.time() - t0, M)
    stream = RecordStream(asm_path(die), M)
    cnt = collections.Counter()           # (dest type, verdict) -> n
    seen_src = []
    seen_trip = []                         # matched (mux<<8|slot) packed
    out_of_class = 0
    recs_nonempty = recs_empty = 0
    rec_src = []
    for b in stream:
        n, nb = b["n"], b["nb"]
        nrec = len(n)
        recs_empty += int((nb == 0).sum()); recs_nonempty += int((nb > 0).sum())
        P = b["P"]
        rec = np.repeat(np.arange(nrec, dtype=np.int64), nb)
        own = owner[P]
        k = bitk[P].astype(np.int64)
        rt = own >= 0
        out_of_class += int((~rt).sum())
        key = rec[rt] * (len(pat) + 1) + own[rt]
        order = np.argsort(key, kind="stable")
        key, kk = key[order], k[rt][order]
        starts = np.flatnonzero(np.concatenate([[True], key[1:] != key[:-1]]))
        code = np.bitwise_or.reduceat(np.int64(1) << kk, starts)
        gkey = key[starts]
        grec, gmux = gkey // (len(pat) + 1), (gkey % (len(pat) + 1)).astype(np.int64)
        gslot = slot_tab[pat[gmux], code].astype(np.int64)
        valid = gslot >= 0
        gsrc = np.where(valid, src[so[gmux] + np.where(valid, gslot, 0)], 0).astype(np.int64)
        # record source = most common source among valid groups
        vr, vs = grec[valid], gsrc[valid]
        pair = vr * (1 << 40) + vs
        up, uc = np.unique(pair, return_counts=True)
        ur, us = up // (1 << 40), up % (1 << 40)
        best = np.full(nrec, -1, np.int64); bestc = np.zeros(nrec, np.int64)
        for i in np.argsort(uc, kind="stable"):    # ascending count: last write wins = max
            best[ur[i]] = us[i]; bestc[ur[i]] = uc[i]
        rsrc = best[grec]
        dtype_ = (dest[gmux] >> 24).astype(np.int64)
        verdict = np.where(~valid, 2, np.where(gsrc == rsrc, 0, 1))      # 0 matched, 1 wrong, 2 extra
        for v in (0, 1, 2):
            sel = verdict == v
            if sel.any():
                tt, tc = np.unique(dtype_[sel], return_counts=True)
                for a, c in zip(tt, tc):
                    cnt[(names[int(a)], ("matched", "wrong", "extra")[v])] += int(c)
        m0 = verdict == 0
        seen_trip.append((gmux[m0] * 256 + gslot[m0]).astype(np.int64))
        seen_src.append(np.unique(best[best >= 0]))
        rec_src.append(best[best >= 0])
        if recs_nonempty % 200000 < 100000:
            log.info("%s: %d records, matched %d", die, recs_nonempty + recs_empty, sum(v for (a, vv), v in cnt.items() if vv == "matched"))
    seen = np.unique(np.concatenate(seen_src))
    rs = np.concatenate(rec_src)
    dup = len(rs) - len(np.unique(rs))
    in_seen = np.isin(tsrc, seen)
    dt = (dest[tmux] >> 24).astype(np.int64)
    matched_set = np.unique(np.concatenate(seen_trip))
    tkey = tmux.astype(np.int64) * 256 + tslot
    is_matched = np.isin(tkey, matched_set)
    res = dict(die=die, model=model, M=M, records=recs_nonempty + recs_empty, empty_records=recs_empty,
               asm_records_with_route_source=int(len(rs)), sources_seen=int(len(seen)), records_sharing_a_source=int(dup),
               positions_outside_route_muxes=out_of_class,
               mistral_triples=int(len(tsrc)), per_dest_type={})
    tot = collections.Counter()
    for tid in np.unique(dt):
        nm = names[int(tid)]
        sel = dt == tid
        m_seen = int((sel & in_seen).sum())
        matched = cnt[(nm, "matched")]
        missing_seen = int((sel & in_seen & ~is_matched).sum())
        missing_unseen = int((sel & ~in_seen).sum())
        row = dict(mistral_triples=int(sel.sum()), triples_of_seen_sources=m_seen, matched=matched,
                   wrong=cnt[(nm, "wrong")], extra=cnt[(nm, "extra")], missing_seen_source=missing_seen,
                   missing_unseen_source=missing_unseen)
        res["per_dest_type"][nm] = row
        for kx, vx in row.items():
            tot[kx] += vx
    res["totals"] = dict(tot)
    mm = tot["matched"]
    res["headline_seen_sources"] = mm / max(1, mm + tot["wrong"] + tot["extra"] + tot["missing_seen_source"])
    res["headline_all"] = mm / max(1, mm + tot["wrong"] + tot["extra"] + tot["missing_seen_source"] + tot["missing_unseen_source"])
    os.makedirs(os.path.join(REPO, "tmp", "cyclonev_ddb"), exist_ok=True)
    outp = os.path.join(REPO, "tmp", "cyclonev_ddb", f"{die}_asm_compare.json")
    json.dump(res, open(outp, "w"), indent=1)
    log.info("%s: wrote %s (%.1fs)", die, outp, time.time() - t0)
    return res


def stats(die):
    _, model = DIES[die]
    import cyclonev_native_tables as nt
    g = nt.load(model)["geom"]
    M = g["cram_sx"] * g["cram_sy"]
    s = RecordStream(asm_path(die), M)
    rec = ne = bits = ush = 0
    shapes = collections.Counter()
    for b in s:
        rec += len(b["n"]); ne += int((b["nb"] > 0).sum())
        bits += int(b["nb"].sum()); ush += int(b["n"].sum())
        shapes.update(zip(b["n"].tolist(), b["nb"].tolist()))
    types = {t[5]: t[3] for t in dd.read_types(asm_path(die))}
    print(f"{die}: records {rec} (non-empty {ne}); sum n {ush} (type table unsigned short {types.get('unsigned short')}); "
          f"entries {bits} (type table ASM_BIT {types.get('DYGR_ROUTE_ASM_BIT')}); nodes (type table) {types.get('DYGR_ROUTE_ASM_NODE')}")
    print(shapes.most_common(8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("stats", "compare"))
    ap.add_argument("--die", choices=sorted(DIES), default="e50f")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_ddb_asm.log"))])
    if a.cmd == "stats":          # streaming, small RSS: no lock
        stats(a.die)
        return
    import heavy_guard
    with heavy_guard.heavy_lock("cyclonev_ddb_asm", log):
        heavy_guard.wait_available(log, "cyclonev_ddb_asm " + a.die)
        res = compare(a.die)
        log.info(json.dumps({k: v for k, v in res.items() if k != "per_dest_type"}, indent=1))
        for nm, row in sorted(res["per_dest_type"].items(), key=lambda kv: -kv[1]["mistral_triples"]):
            log.info("  %-8s %s", nm, row)


if __name__ == "__main__":
    main()
