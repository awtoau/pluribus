#!/usr/bin/env python3
"""Detection-only: is a Cyclone V .rbf image's CRAM an encrypted stream, or a mis-decoded one?

Sections (each prints to stdout and tmp/logs/cyclonev_encryption_probe.log):
  opt    option-RAM bits of the images vs every Quartus-produced stream (bit-by-bit value sets)
  align  CRAM re-alignment search: bit offset 0..7 x byte delta, nibble-coded and raw, CRC16 chain
  stats  byte statistics of the CRAM vs Quartus-compressed CRAM, random bytes, synthetic dense data
  pair   ciphertext relation between two images at equal offsets
No key handling of any kind: nothing here tries to recover, guess or test a key.

Usage: python3.15t scripts/cyclonev_encryption_probe.py --image NAME=PATH [--image ...]
           --corpus DIR --sfl DIR [--section opt align stats pair] [--workers 8]
  --corpus: dirs holding bitstream.rbf + bitstream.compressed.rbf; --sfl: output dir of
  cyclonev_compressed_pairs.py --sfl.
"""
import argparse
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_decompress as cd  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_encryption_probe.log"
log = logging.getLogger("encprobe")

# Names of option-RAM bits as Project Mistral's data/opt-mux.txt lists them (strip.bit).
MISTRAL = {"6.35": "compression_dis", "2.13": "crc_error_detection_en", "6.2": "cvp_conf_done_en",
           "6.3": "release_clears_before_tristates_dis", "6.4": "device_wide_reset_en",
           "6.5": "allow_device_wide_output_enable_dis", "6.6": "retry_config_on_error_en",
           "2.20": "oct_done_dis", "2.19": "nceo_dis", "0.2": "iocsr_ready_from_csr_done_en"}
for _b in range(19, 27):
    MISTRAL[f"6.{_b}"] = "idcode"
for _b in range(27, 35):
    MISTRAL[f"6.{_b}"] = "crc_divide_order"
for _b in range(8, 40):
    MISTRAL[f"7.{_b}"] = "jtag_id"
for _b in (7, 8, 9):
    MISTRAL[f"0.{_b}"] = "external_clk_spi"
for _b in range(9, 40):
    MISTRAL[f"3.{_b}"] = "opt_b"
for _b in range(0, 33):
    MISTRAL[f"4.{_b}"] = "opt_b"
for _b in [39] + list(range(0, 15)):
    MISTRAL.setdefault(f"2.{_b}" if _b < 39 else "1.39", "opt_a")


def LENGTH_BIT(st, bit):
    """Strip 4 bits 0..6 and strip 5 bits 16..39 hold the stream length (design-dependent)."""
    return (st == 4 and bit < 7) or (st == 5 and bit >= 16)


def emit(msg=""):
    print(msg, flush=True)
    log.info(msg)


def load_image(path):
    """Realigned bytes of an image + (sync, shift)."""
    d = Path(path).read_bytes()
    s, sh = cd.find_sync(d)
    return (cd.realign(d, sh) if sh else d), s, sh


def opt_bits(d, s):
    """1280-bit option RAM as a numpy uint8 array indexed strip*40+bit."""
    return np.array([(cd.oram_strip(d, s, st) >> b) & 1 for st in range(32) for b in range(40)],
                    dtype=np.uint8)


def quartus_headers(corpus, sfl, refs=()):
    """name -> (compressed?, option bits).  Only the first 0x200 bytes of each file are read."""
    out = {}
    files = []
    for dd in sorted(Path(corpus).iterdir()):
        for fn, comp in (("bitstream.compressed.rbf", True), ("bitstream.rbf", False)):
            if (dd / fn).is_file():
                files.append((f"corpus/{dd.name}/{fn}", dd / fn, comp))
    for f in sorted(Path(sfl).glob("*.rbf")):
        files.append((f"sfl/{f.name}", f, ".compressed." in f.name))
    for r in refs:
        for f in sorted(Path(r).glob("*.rbf")):
            files.append((f"ref/{f.name}", f, f.stat().st_size < 0.8 * 2_632_660 and "xA4" not in f.name))
    for name, f, comp in files:
        with open(f, "rb") as fh:
            h = fh.read(0x200)
        try:
            s, sh = cd.find_sync(h)
        except cd.FormatError:
            continue
        if sh:
            continue
        comp = not (cd.oram_strip(h, s, 6) >> 35) & 1
        out[name] = (comp, opt_bits(h, s), cd.oram_strip(h, s, 6) >> 19 & 0xFF)
    return out


def sec_opt(images, corpus, sfl, refs):
    q = quartus_headers(corpus, sfl, refs)
    qc = {k: v for k, v in q.items() if v[0]}
    qu = {k: v for k, v in q.items() if not v[0]}
    emit(f"== opt: Quartus streams {len(q)} (of which {sum(k.startswith('ref/') for k in q)} --ref) ({len(qc)} compressed, {len(qu)} uncompressed)")
    mc = np.array([v[1] for v in qc.values()])
    mu = np.array([v[1] for v in qu.values()])
    ids = {}
    for v in qc.values():
        ids[v[2]] = ids.get(v[2], 0) + 1
    emit(f"compressed streams by IDCODE byte: {ids}")
    same = np.array([v[1] for v in qc.values() if v[2] in (0x05, 0x15)])
    emit(f"compressed, IDCODE byte 05/15 (same die family as the images): {len(same)}")
    for name, (d, s, sh) in images.items():
        b = opt_bits(d, s)
        emit(f"-- image {name}: shift {sh} bits, IDCODE byte {cd.oram_strip(d, s, 6) >> 19 & 0xFF:#04x}, "
             f"compression_dis={b[6 * 40 + 35]}")
        emit("bit      mistral-name          image  Q-compressed(n0/n1)  Q-same-die(n0/n1)  Q-uncompr(n0/n1)  verdict")
        for st in range(32):
            for bit in range(40):
                i = st * 40 + bit
                if LENGTH_BIT(st, bit):
                    continue
                c1, s1, u1 = int(mc[:, i].sum()), int(same[:, i].sum()), int(mu[:, i].sum())
                c0, s0, u0 = len(mc) - c1, len(same) - s1, len(mu) - u1
                if not (c0 and c1) and b[i] != (1 if c1 else 0):
                    verdict = "Q-compressed CONSTANT, image differs"
                elif s0 + s1 and not (s0 and s1) and b[i] != (1 if s1 else 0):
                    verdict = "same-die Q constant, image differs"
                else:
                    continue
                emit(f"{st}.{bit:<5} {MISTRAL.get(f'{st}.{bit}', '-'):<22}{int(b[i]):>5}  "
                     f"{c0}/{c1:<16} {s0}/{s1:<14} {u0}/{u1:<14} {verdict}")
    cons = np.where(same.min(axis=0) == same.max(axis=0), same.min(axis=0), 2)
    emit("-- strips with any deviation: Quartus same-die consensus ('.' = varies across Quartus builds), "
         "then each image; '^' = image bit differs from a constant Quartus bit (bit 0 at left)")
    for st_, b_ in [(4, range(7)), (5, range(16, 40))]:
        for bb in b_:
            cons[st_ * 40 + bb] = 2
    ibits = {n: opt_bits(d, s) for n, (d, s, _) in images.items()}
    for st in range(32):
        sl = slice(st * 40, st * 40 + 40)
        dev = [(n, np.where((cons[sl] != 2) & (b[sl] != cons[sl]))[0]) for n, b in ibits.items()]
        if not any(len(x) for _, x in dev):
            continue
        emit(f"strip {st:>2} Q    " + "".join("." if v == 2 else str(v) for v in cons[sl]))
        for n, x in dev:
            emit(f"strip {st:>2} {n:<4} " + "".join(str(v) for v in ibits[n][sl]) + f"   deviating bits {list(map(int, x))}")
    if len(images) >= 2:
        (n1, (d1, s1_, _)), (n2, (d2, s2_, _)) = list(images.items())[:2]
        b1, b2 = opt_bits(d1, s1_), opt_bits(d2, s2_)
        diff = [f"{i // 40}.{i % 40}" for i in range(1280) if b1[i] != b2[i]]
        emit(f"-- bits differing {n1} vs {n2}: {len(diff)}: {' '.join(diff)}")
        in_q = {}
        for i in range(1280):
            if b1[i] != b2[i]:
                in_q[f"{i // 40}.{i % 40}"] = (int(mc[:, i].sum()), len(mc))
        emit(f"   of those, ones/n among Quartus-compressed streams: {in_q}")
    # do Quartus builds differ among themselves in strips 3/4/5/7 (opt_b / length / jtag_id)?
    for strip in (3, 4, 5, 7):
        vals = set()
        for k, v in qc.items():
            if v[2] in (0x05, 0x15):
                row = v[1].reshape(32, 40)[strip]
                # strip 4/5 carry the length field; mask it out
                if strip == 4:
                    row = row[7:]
                if strip == 5:
                    row = row[:16]
                vals.add(tuple(int(x) for x in row))
        emit(f"distinct strip {strip} values (length-field bits masked) over same-die Quartus "
             f"compressed streams: {len(vals)}")


def zero_chain_starts(buf, starts, gmin, gmax, need=3):
    """(start, g) where `need` consecutive g-byte frames at start each CRC16-check (state 0)."""
    hits = []
    tab = cd.CRC_T
    n = len(buf)
    for s in starts:
        if s < 0 or s + gmax >= n:
            continue
        a = 0xFFFF
        for g in range(1, gmax + 1):
            a = (a >> 8) ^ tab[(a ^ buf[s + g - 1]) & 0xFF]
            if a == 0 and g >= gmin and s + need * g <= n:
                if all(cd.crc_ok(buf, s + k * g, g) for k in range(1, need)):
                    hits.append((s, g))
    return hits


def bit_shift_slice(d, start, length, sh):
    """Bytes [start, start+length) of the bitstream shifted down by sh bits (LSB-first)."""
    v = int.from_bytes(d[start:start + length + 1], "little") >> sh
    return (v & ((1 << (8 * length)) - 1)).to_bytes(length, "little")


def align_one(d, cs, sh, delta, mode, gmax):
    seg = bit_shift_slice(d, cs + delta, 3 * gmax + 4096 if mode == "coded" else 4 * gmax + 1500, sh)
    if mode == "raw":
        # raw CRC chain over the bytes themselves; scan starts over the first 1500 bytes
        return [(sh, delta, s, g) for s, g in zero_chain_starts(seg, range(0, 1500), 64, gmax)]
    out, _ = cd.nibble_decode(seg)
    return [(sh, delta, s, g) for s, g in zero_chain_starts(out, range(0, 4), 64, gmax)]


def align_scan(d, cs, workers, gmax=2048, deltas=range(-16, 17)):
    jobs = [(sh, de, mode) for sh in range(8) for de in deltas for mode in ("coded", "raw")]
    # raw mode only needs one delta: the scan window already covers +-1500 bytes
    jobs = [j for j in jobs if j[2] == "coded" or j[1] == -16]
    hits = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(lambda j: (j, align_one(d, cs, j[0], j[1], j[2], gmax)), jobs):
            if r[1]:
                hits.append((r[0][2], r[1]))
    return len(jobs), hits


def sec_align(images, corpus, workers):
    emit("== align: CRAM re-alignment search (bit offset 0..7 x byte delta -16..16, coded and raw)")
    ctl = next(Path(corpus).iterdir()) / "bitstream.compressed.rbf"
    d, s, sh = load_image(ctl)
    h = cd.parse_header(d)
    n, hits = align_scan(d, h["cram_start"], workers)
    emit(f"control (Quartus compressed, {ctl.parent.name}): {n} trials, hits {[(m, x[:3]) for m, x in hits][:6]}")
    rnd = bytes(np.random.default_rng(1).integers(0, 256, 200000, dtype=np.uint8))
    n, hits = align_scan(rnd, 40000, workers)
    emit(f"control (random bytes): {n} trials, hits {len(hits)}")
    for name, (d, s, sh) in images.items():
        h = cd.parse_header(d)
        n, hits = align_scan(d, h["cram_start"], workers)
        emit(f"{name}: realigned by {sh} bits; cram_start {h['cram_start']} (PRAM 64 frames CRC ok); "
             f"{n} trials, CRC16-chain hits: {len(hits)} {hits[:4]}")
        # at the whole-file level every shift: only one makes the sync/option CRC valid
        raw = Path(images_paths[name]).read_bytes()
        ok = []
        for t in range(8):
            try:
                x = cd.realign(raw[:4096], t)
                ss, ssh = cd.find_sync(x)
                ok.append((t, ssh == 0 and cd.crc_ok(x, ss + 4, 0xA4)))
            except cd.FormatError:
                ok.append((t, False))
        emit(f"{name}: whole-file shift t with sync+option-CRC valid: {[t for t, v in ok if v]}")


def blk_entropy(a, bs=16):
    n = len(a) // bs
    m = a[:n * bs].reshape(n, bs)
    ent = np.zeros(n)
    srt = np.sort(m, axis=1)
    for i in range(n):
        _, c = np.unique(srt[i], return_counts=True)
        p = c / bs
        ent[i] = -(p * np.log2(p)).sum()
    return ent


def stats_of(a):
    n = len(a)
    h = np.bincount(a, minlength=256)
    p = h[h > 0] / n
    ent = float(-(p * np.log2(p)).sum())
    chi = float(((h - n / 256) ** 2 / (n / 256)).sum())
    nib = np.concatenate([a & 15, a >> 4])
    hn = np.bincount(nib, minlength=16)
    chin = float(((hn - len(nib) / 16) ** 2 / (len(nib) / 16)).sum())
    ac = [float(np.corrcoef(a[:-k].astype(float), a[k:].astype(float))[0, 1]) for k in (1, 2, 3, 4, 8, 16)]
    pair = np.bincount(a[:-1].astype(np.int64) * 256 + a[1:], minlength=65536)
    e = (n - 1) / 65536
    chip = float(((pair - e) ** 2 / e).sum())
    win = np.lib.stride_tricks.sliding_window_view(a, 16)
    sub = np.ascontiguousarray(win[:2_000_000])
    u = np.unique(sub.view("V16").ravel())
    dup_all = len(sub) - len(u)
    al = a[:n // 16 * 16].reshape(-1, 16)
    dup_al = len(al) - len(np.unique(np.ascontiguousarray(al).view("V16").ravel()))
    be = blk_entropy(a[:1 << 20])
    return {"n": n, "H": ent, "chi2_byte_z": (chi - 255) / math.sqrt(510),
            "chi2_nibble_z": (chin - 15) / math.sqrt(30),
            "chi2_pair_z": (chip - 65535) / math.sqrt(2 * 65535),
            "autocorr_lag1,2,3,4,8,16": [round(x, 4) for x in ac],
            "ones_frac": float(np.unpackbits(a[:1 << 20]).mean()),
            "dup16_unaligned(first2M)": dup_all, "dup16_aligned": dup_al,
            "blkH16_mean": float(be.mean()), "blkH16_sd": float(be.std())}


def encode_zero_suppress(plain_nibbles):
    """Test control only: the key/nibble coder of the format doc applied to synthetic data."""
    n = len(plain_nibbles) // 4 * 4
    q = plain_nibbles[:n].reshape(-1, 4)
    out = []
    for g in q:
        k = int(g[0] != 0) | int(g[1] != 0) << 1 | int(g[2] != 0) << 2 | int(g[3] != 0) << 3
        out.append(k)
        out.extend(int(x) for x in g if x)
    if len(out) % 2:
        out.append(0)
    o = np.array(out, dtype=np.uint8)
    return bytes(o[0::2] | (o[1::2] << 4))


def cram_region(d):
    h = cd.parse_header(d)
    e = len(d.rstrip(b"\xff"))
    return h["cram_start"], e


def sec_stats(images, corpus, sfl):
    emit("== stats: byte statistics (z = standard deviations from the uniform-random expectation)")
    rows = {}
    for name, (d, s, sh) in images.items():
        cs, e = cram_region(d)
        a = np.frombuffer(d[cs:e], dtype=np.uint8)
        rows[f"{name} CRAM {len(a)}B"] = stats_of(a)
        h = cd.parse_header(d)
        pr = np.frombuffer(d[cs - h["pram_frame"] * h["pram_frames"]:cs], dtype=np.uint8)
        rows[f"{name} PRAM {len(pr)}B"] = stats_of(pr)
    rows["random 2.0MB"] = stats_of(np.random.default_rng(7).integers(0, 256, 2_000_000, dtype=np.uint8))
    comp = sorted(Path(corpus).glob("*/bitstream.compressed.rbf"), key=lambda p: -p.stat().st_size)
    for f in (comp[0], comp[len(comp) // 2]):
        d, s, sh = load_image(f)
        cs, e = cram_region(d)
        a = np.frombuffer(d[cs:e], dtype=np.uint8)
        rows[f"Quartus compressed CRAM {f.parent.name} {len(a)}B"] = stats_of(a)
        h = cd.parse_header(d)
        pr = np.frombuffer(d[cs - h["pram_frame"] * h["pram_frames"]:cs], dtype=np.uint8)
        rows[f"Quartus PRAM {f.parent.name} {len(pr)}B"] = stats_of(pr)
    for f in sorted(Path(sfl).glob("*b050dd.compressed.rbf")):
        d, s, sh = load_image(f)
        cs, e = cram_region(d)
        rows[f"Quartus SFL compressed CRAM {f.name}"] = stats_of(np.frombuffer(d[cs:e], dtype=np.uint8))
    # synthetic: every nibble present with probability r, uniform 1..15 (most incompressible
    # plaintext a zero-suppression coder can be given): max coded-byte entropy over r
    rng = np.random.default_rng(3)
    best = (0, 0)
    for r in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        nib = rng.integers(1, 16, 4_000_000, dtype=np.uint8) * (rng.random(4_000_000) < r)
        enc = np.frombuffer(encode_zero_suppress(nib.astype(np.uint8)), dtype=np.uint8)
        st = stats_of(enc[:2_000_000])
        rows[f"synthetic zero-suppressed, nibble density {r}: {len(enc)}B"] = st
        best = max(best, (st["H"], r))
    for k, v in rows.items():
        emit(f"-- {k}")
        emit("   " + " | ".join(f"{a}={round(b, 4) if isinstance(b, float) else b}" for a, b in v.items()))
    emit(f"max coded-byte entropy over synthetic densities: {best[0]:.4f} bits/byte at r={best[1]}")


def sec_pair(images, corpus):
    if len(images) < 2:
        return
    (n1, (d1, _, _)), (n2, (d2, _, _)) = list(images.items())[:2]
    (c1, e1), (c2, e2) = cram_region(d1), cram_region(d2)
    a = np.frombuffer(d1[c1:e1], dtype=np.uint8)
    b = np.frombuffer(d2[c2:e2], dtype=np.uint8)
    m = min(len(a), len(b))
    emit(f"== pair: {n1} vs {n2} CRAM at equal offsets ({m} B compared; CRAM lengths {len(a)}, {len(b)})")
    eq = a[:m] == b[:m]
    emit(f"identical bytes at equal offsets: {int(eq.sum())} ({eq.mean() * 100:.4f}%; random 0.3906%)")
    A = a[:m // 16 * 16].reshape(-1, 16)
    B = b[:m // 16 * 16].reshape(-1, 16)
    emit(f"identical aligned 16-byte blocks at equal offsets: {int((A == B).all(axis=1).sum())} of {len(A)}")
    sa = set(np.ascontiguousarray(A).view("V16").ravel().tolist())
    sb = set(np.ascontiguousarray(B).view("V16").ravel().tolist())
    emit(f"aligned 16-byte blocks present in both images at any offset: {len(sa & sb)}")
    x = a[:m] ^ b[:m]
    p = np.bincount(x, minlength=256) / m
    p = p[p > 0]
    emit(f"byte entropy of the XOR of the two CRAM regions: {float(-(p * np.log2(p)).sum()):.4f} bits/byte")
    p1, p2 = [d[cram_region(d)[0] - 524 * 64:cram_region(d)[0]] for d in (d1, d2)]
    emit(f"PRAM identical bytes at equal offsets: {sum(u == v for u, v in zip(p1, p2))} of {len(p1)}")
    ctl = next(Path(corpus).iterdir()) / "bitstream.compressed.rbf"
    dq, _, _ = load_image(ctl)
    pq = dq[cram_region(dq)[0] - 524 * 64:cram_region(dq)[0]]
    emit(f"PRAM identical bytes, {n1} vs a Quartus-built same-die stream ({ctl.parent.name}): "
         f"{sum(u == v for u, v in zip(p1, pq))} of {len(p1)}")
    emit(f"PRAM identical bytes, {n2} vs the same Quartus stream: {sum(u == v for u, v in zip(p2, pq))} of {len(p2)}")


images_paths = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--image", action="append", required=True, help="NAME=PATH (read-only input)")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--sfl", required=True)
    ap.add_argument("--ref", action="append", default=[],
                    help="dir of extra Quartus-built .rbf (e.g. third-party, older toolchains); gitignored inputs")
    ap.add_argument("--section", nargs="*", default=["opt", "align", "stats", "pair"])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.FileHandler(LOG, mode="w")])
    images = {}
    for spec in a.image:
        n, p = spec.split("=", 1)
        images_paths[n] = p
        images[n] = load_image(p)
    if "opt" in a.section:
        sec_opt(images, a.corpus, a.sfl, a.ref)
    if "align" in a.section:
        sec_align(images, a.corpus, min(a.workers, 8))
    if "stats" in a.section:
        sec_stats(images, a.corpus, a.sfl)
    if "pair" in a.section:
        sec_pair(images, a.corpus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
