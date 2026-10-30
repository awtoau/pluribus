#!/usr/bin/env python3.15t
"""Derive the sof tag-21 (CFF) and tag-18 (option) bit -> rbf periphery cell tables of EP4CGX150.  Black box: quartus_cpf only.

Method (same as cycloneiv_sof2rbf_tables.py): bit-plane sofs, sof tag bit i = bit p of i, plus the complement planes.
A periphery cell that flips with every plane/complement pair carries one tag bit; its index is read from the planes.
Cells that do not flip are template constants.  Cells claimed by two tag bits are counted and reported (no bijection assumed).
Output: databases/cycloneiv/cff2rbf.npz (local, not committed).  Log: tmp/logs/cycloneiv_clean_cff_tables.log
usage: python3.15t scripts/cycloneiv_clean_cff_tables.py [--groups-only]   (groups-only: re-run the data-group step on the existing npz)
"""
import gzip
import logging
import os
import shutil
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import plane as P  # noqa: E402
from lifters.cycloneiv_clean import sofio as S  # noqa: E402

log = logging.getLogger("cff_tables")
SRC = "sfl_ep4cgx150.sof"
WORK = os.path.join(REPO, "tmp", "cff_tables")
# source: sof tag 21 = 12-byte header + ceil(31,060 / 8) bytes; 31,060 = ASMDB_DIE m_num_cff_bits (asmdb body offset 9)
# source: sof tag 18 = 40 bytes; asmdb m_num_option_reg_bits = 160 (asmdb body offset 17)
TAGS = {21: dict(skip=12, nbits=31060, name="cff"), 18: dict(skip=0, nbits=320, name="option")}
# source: observed in the 60 flip-resolved two-group bits: the check group lies in the last 8 bytes of its frame (bytes 788..795 = frame bytes 796 - 8)
END_BYTE = P.RBF_FRAME_BYTES - 8
PERIPHERY_BYTES = P.RBF_HEADER + P.RBF_PRE_FRAMES * P.RBF_FRAME_BYTES


def sections(d):
    p, out = 12, {}
    while p < len(d):
        tag, ln = struct.unpack_from("<HI", d, p)
        out[tag] = (p + 6, ln)
        p += 6 + ln
    return out


def make_sof(src, out, tag, bits, skip):
    d = bytearray(gzip.decompress(open(src, "rb").read()))
    off, ln = sections(d)[tag]
    packed = np.packbits(bits, bitorder="little").tobytes()
    if skip + len(packed) != ln:
        raise SystemExit(f"tag {tag}: {skip} + {len(packed)} bytes != section {ln}")
    d[off + skip:off + ln] = packed
    d[-2:] = struct.pack("<H", S.sof_crc(bytes(d[:-2])))
    with open(out, "wb") as f:
        f.write(gzip.compress(bytes(d), 1))


def periphery_bits(rbf):
    """uint8 [FRAMES0, RBF_FRAME_BYTES, 8]: header + periphery frames of an rbf."""
    b = np.fromfile(rbf, np.uint8)[P.RBF_HEADER:PERIPHERY_BYTES]
    return np.unpackbits(b.reshape(P.RBF_PRE_FRAMES, P.RBF_FRAME_BYTES, 1), axis=2, bitorder="little")


def run_tag(tag, src):
    spec = TAGS[tag]
    n = spec["nbits"]
    nplane = int(n - 1).bit_length()
    i = np.arange(n, dtype=np.int64)
    pad = (-n) % 8
    d0 = gzip.decompress(open(src, "rb").read())
    off, ln = sections(d0)[tag]
    plane, comp = [], []
    for p in range(nplane):
        for inv in (0, 1):
            bits = ((i >> p) & 1).astype(np.uint8) ^ inv
            if pad:
                bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
            sof, rbf = os.path.join(WORK, f"t{tag}_{p}_{inv}.sof"), os.path.join(WORK, f"t{tag}_{p}_{inv}.rbf")
            make_sof(src, sof, tag, bits, spec["skip"])
            S.to_rbf(sof, rbf)
            (comp if inv else plane).append(periphery_bits(rbf).astype(np.int8))
            os.remove(sof)
            os.remove(rbf)
        log.info("tag %d plane %d / %d", tag, p + 1, nplane)
    flips = np.ones(plane[0].shape, bool)
    idx = np.zeros(plane[0].shape, np.int64)
    for p in range(nplane):
        flips &= plane[p] != comp[p]
        idx |= plane[p].astype(np.int64) << p
    idx = np.where(flips & (idx < n), idx, -1)
    return idx


def data_groups(idx, src):
    """Drop cells that are not storage of their tag bit (#168).  A tag bit with two cell groups (64 bits) has one data group and one
    frame-end check group whose plane-derived index collided with the bit's index; the data group is the one that changes when that tag bit
    alone is flipped in a real sof (check groups sit in other frames and respond to other bits).  Returns idx with the check cells set to -1."""
    idx = idx.copy()
    d0 = bytearray(gzip.decompress(open(src, "rb").read()))
    off, _ln = sections(d0)[21]
    base = os.path.join(WORK, "g_base")
    os.makedirs(WORK, exist_ok=True)

    def rbf_of(d, name):
        d = bytearray(d)
        d[-2:] = struct.pack("<H", S.sof_crc(bytes(d[:-2])))
        with open(base + ".sof", "wb") as f:
            f.write(gzip.compress(bytes(d), 1))
        S.to_rbf(base + ".sof", base + ".rbf")
        out = periphery_bits(base + ".rbf").astype(np.int8)
        os.remove(base + ".sof")
        os.remove(base + ".rbf")
        return out
    ref = rbf_of(d0, "ref")
    multi = [b for b in np.unique(idx[idx >= 0]) if (idx == b).sum() > 4]
    for b in multi:
        d = bytearray(d0)
        d[off + 12 + b // 8] ^= 1 << (b % 8)
        changed = rbf_of(d, "flip") != ref
        cells = np.argwhere(idx == b)
        keep = [bool(changed[tuple(c)]) for c in cells]
        # a group is data when all of its 4 cells changed (groups = consecutive runs of 4 in argwhere order)
        for g in range(0, len(cells), 4):
            if not all(keep[g:g + 4]):
                for c in cells[g:g + 4]:
                    idx[tuple(c)] = -1
    # both groups responded (flip also moved the check group): the check group responds to another bit stored in the OTHER group's frame
    for b in [b for b in multi if (idx == b).sum() > 4]:
        cells = np.argwhere(idx == b)
        groups = [cells[:4], cells[4:]]
        verdict = []
        for g in (0, 1):
            other_frame = int(groups[1 - g][0][0])
            j = next(int(x) for x in np.unique(idx[other_frame][idx[other_frame] >= 0]) if x != b and (idx == x).sum() == 4)
            d = bytearray(d0)
            d[off + 12 + j // 8] ^= 1 << (j % 8)
            verdict.append(bool(rbf_of(d, "flip")[tuple(groups[g][0])] != ref[tuple(groups[g][0])]))      # True: group g moved with an unrelated bit -> check group
        if verdict.count(True) == 1:
            for c in groups[verdict.index(True)]:
                idx[tuple(c)] = -1
    # still two groups (flip test inconclusive): same structure as the 60 flip-resolved cases (data group < byte END, check group in the last 8 bytes)
    for b in [b for b in multi if (idx == b).sum() > 4]:
        cells = np.argwhere(idx == b)
        ends = [bool((cells[g:g + 4][:, 1] >= END_BYTE).all()) for g in (0, 4)]
        if ends.count(True) == 1:
            for c in cells[(4 if ends[1] else 0):(8 if ends[1] else 4)]:
                idx[tuple(c)] = -1
    log.info("check groups dropped for %d multi-group bits; cells left per bit: %s", len(multi), sorted({int((idx == b).sum()) for b in multi}))
    return idx


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_cff_tables.log"), mode="w")])
    src = S.programmer_sof(SRC)
    os.makedirs(WORK, exist_ok=True)
    if "--groups-only" in sys.argv:
        z = dict(np.load(os.path.join(REPO, "databases", "cycloneiv", "cff2rbf.npz")))
        z["cff"] = data_groups(z["cff"], src).astype(np.int32)
        np.savez(os.path.join(REPO, "databases", "cycloneiv", "cff2rbf.npz"), **z)
        shutil.rmtree(WORK, ignore_errors=True)
        return
    out = {}
    for tag, spec in TAGS.items():
        idx = run_tag(tag, src)
        if tag == 21:
            idx = data_groups(idx, src)
        cells = int((idx >= 0).sum())
        uniq = len(np.unique(idx[idx >= 0]))
        log.info("tag %d (%s): %d bits, %d periphery cells carry a tag bit, %d distinct bits seen, %d bits unseen",
                 tag, spec["name"], spec["nbits"], cells, uniq, spec["nbits"] - uniq)
        out[spec["name"]] = idx.astype(np.int32)
    dest = os.path.join(REPO, "databases", "cycloneiv")
    os.makedirs(dest, exist_ok=True)
    np.savez(os.path.join(dest, "cff2rbf.npz"), source=np.array(SRC), source_sha256=np.array(S.sha256(src)), **out)
    shutil.rmtree(WORK, ignore_errors=True)
    log.info("wrote %s/cff2rbf.npz", dest)


if __name__ == "__main__":
    main()
