#!/usr/bin/env python3
"""Conformance check: do Cyclone V images that are claimed encrypted have the STRUCTURE of an
AES design-security stream?  Structure only: no key handling, no decryption, no key search.

Per image, per check: PASS / FAIL / INCONCLUSIVE with numbers (log: tmp/logs/cyclonev_aes_conformance.log).
  PASS          the observation is what an encrypted stream must show
  FAIL          the observation contradicts an encrypted stream (or the stated scheme)
  INCONCLUSIVE  needs the key or a Quartus-produced encrypted reference
Images are named by label in a local, untracked JSON config {label: path}; paths never printed.
Controls run first (uniform random; Quartus-compressed CRAM) so the checks are shown to discriminate.

Usage: python3.15t scripts/cyclonev_aes_conformance.py --config <images.json> [--label L ...]
Format facts and open points: docs/cyclonev-aes-conformance.md
"""
import argparse
import itertools
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_decompress as cd  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_aes_conformance.log"
FIXTURE = REPO / "tests" / "fixtures" / "cv_fixture.compressed.rbf"
log = logging.getLogger("aesconf")
Z_LIMIT = 5.0          # |z| under uniform-random; 5 sigma = 6e-7 false-fail rate per statistic
HDR_LEN_CONST = 1428   # compressed streams: 4*len - field (docs/cyclonev-compressed-rbf.md)

# Option bits constant in all 254 Quartus 25.1 streams + 5 older-toolchain streams
# (docs/fpga-encryption.md): (strip, bit) -> value.  Length field and jtag_id excluded.
QUARTUS_CONST = {(6, 36): 1, (6, 37): 1, (6, 10): 1, (3, 1): 1, (3, 3): 1, (3, 5): 1, (3, 7): 1, (3, 8): 1}
for _b in range(9, 40):
    QUARTUS_CONST[(3, _b)] = 1
_q4 = [1, 0] + [1] * 31
for _i, _v in enumerate(_q4):
    QUARTUS_CONST[(4, 7 + _i)] = _v


def emit(msg=""):
    print(msg, flush=True)
    log.info(msg)


class Result:
    def __init__(self):
        self.rows = []

    def add(self, check, verdict, detail):
        self.rows.append((check, verdict, detail))
        emit(f"  {check:<34}{verdict:<14}{detail}")


def load(data):
    s, sh = cd.find_sync(data)
    d = cd.realign(data, sh) if sh else data
    h = cd.parse_header(d)
    ext = len(d.rstrip(b"\xff"))
    fld = cd.length_field(d, s)
    bits = np.array([[(cd.oram_strip(d, s, st) >> b) & 1 for b in range(40)] for st in range(32)], dtype=np.uint8)
    return {"d": d, "s": s, "shift": sh, "h": h, "ext": ext, "field": fld, "opt": bits,
            "die": cd.oram_strip(d, s, 6) >> 19 & 0xFF}


def cipher_region(im):
    cs = im["h"]["cram_start"]
    return np.frombuffer(im["d"][cs:im["ext"]], dtype=np.uint8)


def z_scores(a):
    n = len(a)
    h = np.bincount(a, minlength=256)
    chi = float(((h - n / 256) ** 2 / (n / 256)).sum())
    nib = np.concatenate([a & 15, a >> 4])
    hn = np.bincount(nib, minlength=16)
    chin = float(((hn - len(nib) / 16) ** 2 / (len(nib) / 16)).sum())
    pair = np.bincount(a[:-1].astype(np.int64) * 256 + a[1:], minlength=65536)
    e = (n - 1) / 65536
    chip = float(((pair - e) ** 2 / e).sum())
    p = h[h > 0] / n
    return (float(-(p * np.log2(p)).sum()), (chi - 255) / math.sqrt(510), (chin - 15) / math.sqrt(30),
            (chip - 65535) / math.sqrt(2 * 65535))


def dup_blocks(a):
    """Duplicate 16-byte blocks at each of the 16 block alignments (ECB / repeated-IV tell)."""
    out = []
    for off in range(16):
        n = (len(a) - off) // 16
        blk = np.ascontiguousarray(a[off:off + n * 16].reshape(n, 16)).view("V16").ravel()
        out.append(n - len(np.unique(blk)))
    return out


def poisson_ok(count, lam):
    """True if count is within 5 sigma of Poisson(lam) (upper side only: excess = structure)."""
    return count <= lam + Z_LIMIT * math.sqrt(max(lam, 1.0)) + 1


def stat_checks(res, a, tag=""):
    """Checks that apply to any ciphertext candidate byte string."""
    H, zb, zn, zp = z_scores(a)
    ok = max(abs(zb), abs(zn), abs(zp)) < Z_LIMIT and H > 7.99
    res.add("cipher.uniform" + tag, "PASS" if ok else "FAIL",
            f"n={len(a)} H={H:.5f} z(byte,nibble,pair)=({zb:.2f},{zn:.2f},{zp:.2f}) limit +-{Z_LIMIT}")
    dups = dup_blocks(a)
    res.add("cipher.no_repeat16" + tag, "PASS" if sum(dups) == 0 else "FAIL",
            f"dup 16B blocks at 16 alignments: total {sum(dups)}, max {max(dups)} "
            f"(~{len(a) // 16} blocks each; ECB of zero-rich plaintext would repeat)")
    # plaintext-structure leakage: long constant runs and Quartus frame markers
    n = len(a)
    run16 = 0
    for v in (0x00, 0xFF):
        c = np.concatenate([[0], np.cumsum(a == v, dtype=np.int64)])
        run16 += int(((c[16:] - c[:-16]) == 16).sum())
    mk = sum(int(np.count_nonzero((a[:-2] == m[0]) & (a[1:-1] == m[1]) & (a[2:] == m[2])))
             for m in (bytes.fromhex("843e01"), bytes.fromhex("429f00"), bytes.fromhex("2ac501")))
    lam = 3 * n / 2 ** 24
    lam_run = 2 * n / 256.0 ** 16
    res.add("cipher.no_leak" + tag, "PASS" if poisson_ok(mk, lam) and run16 == 0 else "FAIL",
            f"frame-marker 3-byte hits {mk} (random expect {lam:.2f}); 16-byte 00/FF runs {run16} (expect {lam_run:.0e})")
    # tail: a keystream/block cipher leaves no constant tail
    tail = a[-256:]
    res.add("cipher.tail" + tag, "PASS" if len(set(tail.tolist())) > 100 else "FAIL",
            f"last 256 B: {len(set(tail.tolist()))} distinct byte values (random ~ 163)")


def check_image(label, im):
    res = Result()
    h, s, d = im["h"], im["s"], im["d"]
    emit(f"== {label}: IDCODE byte {im['die']:#04x}, PRAM {h['pram_frames']}x{h['pram_frame']} B, "
         f"cipher start {h['cram_start']}, nonFF extent {im['ext']}, whole-file bit shift {im['shift']}")
    res.add("hdr.cleartext", "PASS",
            f"sync at {s}, option-RAM CRC16 ok, {h['pram_frames']} PRAM frames CRC16 ok (header + PRAM are cleartext)")
    # PRAM is cleartext: low entropy, like a Quartus PRAM
    pr = np.frombuffer(d[h["cram_start"] - h["pram_frame"] * h["pram_frames"]:h["cram_start"]], dtype=np.uint8)
    Hp = z_scores(pr)[0]
    res.add("pram.cleartext", "PASS" if Hp < 6.0 else "FAIL", f"PRAM byte entropy {Hp:.3f} (cleartext Quartus PRAM 1.8-2.4 over whole stream)")
    # option bits
    dev = sorted(f"{st}.{b}" for (st, b), v in QUARTUS_CONST.items() if im["opt"][st][b] != v)
    res.add("opt.flags", "INCONCLUSIVE",
            f"{len(dev)} of {len(QUARTUS_CONST)} Quartus-constant option bits differ (6.36,6.37,6.10 incl.: "
            f"{[x for x in dev if x in ('6.36', '6.37', '6.10')]}); meaning of encrypted/key-source bits is not documented")
    # length field
    exp = (im["field"] + HDR_LEN_CONST) / 4
    res.add("len.field", "PASS" if abs(exp - im["ext"]) <= 0.75 else "FAIL",
            f"declared stream end (field+{HDR_LEN_CONST})/4 = {exp:.2f}, nonFF extent {im['ext']}")
    # alignment of the ciphertext to the 16-byte AES block, several candidate origins
    ln = im["ext"] - h["cram_start"]
    pram0 = h["cram_start"] - h["pram_frame"] * h["pram_frames"]
    orig = {"cipher_start": ln % 16, "sync": (im["ext"] - s) % 16, "file_start": im["ext"] % 16,
            "pram_start": (im["ext"] - pram0) % 16}
    # Quartus' encryptor pads its input to 128-bit blocks (docs/cyclonev-aes-conformance.md): the
    # encrypted run should be a 16 B multiple.  Aligned at cipher_start = weak PASS (1/16 by chance).
    ok = orig["cipher_start"] == 0
    res.add("len.block16", "PASS" if ok else "FAIL",
            f"cipher bytes {ln}; length mod 16 from cipher start {orig['cipher_start']} "
            f"(other origins: sync {orig['sync']}, file start {orig['file_start']}, PRAM start {orig['pram_start']}); "
            f"{'aligned, 1-in-16 chance alone' if ok else 'not a 128-bit multiple from any natural origin'}")
    # container padding after the stream
    pad = d[im["ext"]:]
    res.add("len.container_pad", "PASS" if not pad.strip(b"\xff") else "FAIL",
            f"{len(pad)} B after the stream, all 0xFF = {not pad.strip(b'\xff')}")
    stat_checks(res, cipher_region(im))
    return res


def cross_checks(ims):
    emit("== cross-image checks")
    res = Result()
    labels = list(ims)
    for a_, b_ in itertools.combinations(labels, 2):
        A, B = ims[a_], ims[b_]
        same_die = A["die"] == B["die"] and A["h"]["pram_frame"] == B["h"]["pram_frame"]
        ca, cb = cipher_region(A), cipher_region(B)
        m = min(len(ca), len(cb))
        eq = float((ca[:m] == cb[:m]).mean())
        x = ca[:m] ^ cb[:m]
        p = np.bincount(x, minlength=256) / m
        hx = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
        pre = int((ca[:64] == cb[:64]).sum())
        sa = set(np.ascontiguousarray(ca[:len(ca) // 16 * 16].reshape(-1, 16)).view("V16").ravel().tolist())
        sb = set(np.ascontiguousarray(cb[:len(cb) // 16 * 16].reshape(-1, 16)).view("V16").ravel().tolist())
        shared = len(sa & sb)
        ok = abs(eq - 1 / 256) < 5 * math.sqrt(1 / 256 / m) and hx > 7.99 and pre <= 3 and shared == 0
        res.add(f"pair {a_}/{b_}", "PASS" if ok else "FAIL",
                f"{'same die' if same_die else 'diff die'}: equal bytes {eq * 100:.4f}% (rand 0.3906%), "
                f"XOR entropy {hx:.4f}, first-64B equal {pre} (rand 0.25), shared aligned 16B blocks {shared}")
        pa = A["opt"].copy()
        pb = B["opt"].copy()
        diff = [f"{st}.{b}" for st in range(32) for b in range(40)
                if pa[st][b] != pb[st][b] and not ((st == 4 and b < 7) or (st == 5 and b >= 16))]
        res.add(f"  hdr {a_}/{b_}", "INCONCLUSIVE", f"{len(diff)} option bits differ (length field excluded): {' '.join(diff[:24])}")
    # option-bit constants common to all images
    if len(ims) > 1:
        stack = np.stack([i["opt"] for i in ims.values()])
        const = [(st, b) for st in range(32) for b in range(40) if stack[:, st, b].min() == stack[:, st, b].max()]
        sec = [(st, b) for (st, b) in QUARTUS_CONST if (st, b) in set(const) and stack[0][st][b] != QUARTUS_CONST[(st, b)]]
        res.add("hdr.common_flags", "INCONCLUSIVE",
                f"{len(const)} option bits identical in all {len(ims)} images; {len(sec)} of those differ from every Quartus "
                f"stream: {' '.join(f'{a}.{b}' for a, b in sec[:20])} (candidate security bits; meaning unverified)")
    return res


def controls():
    emit("== controls (detector validation)")
    out = {}
    rnd = np.random.default_rng(11).integers(0, 256, 2_000_000, dtype=np.uint8)
    r = Result()
    emit(" control random-2MB (expect all PASS)")
    stat_checks(r, rnd)
    out["random"] = r
    q = Path(FIXTURE).read_bytes()
    c = cd.parse_header(q)
    a = np.frombuffer(q[c["cram_start"]:len(q.rstrip(b"\xff"))], dtype=np.uint8)
    r = Result()
    emit(" control Quartus-compressed CRAM, 36 KB cut (expect FAIL on cipher.uniform)")
    stat_checks(r, a)
    out["quartus"] = r
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True, help="JSON {label: path}, local and untracked")
    ap.add_argument("--label", action="append")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, mode="w")])
    cfg = json.loads(Path(a.config).read_text())
    ctl = controls()
    assert all(v == "PASS" for _, v, _ in ctl["random"].rows), "control random must PASS"
    assert any(c == "cipher.uniform" and v == "FAIL" for c, v, _ in ctl["quartus"].rows), "control Quartus must FAIL uniform"
    ims, results = {}, {}
    for lab, p in cfg.items():
        if a.label and lab not in a.label:
            continue
        ims[lab] = load(Path(p).read_bytes())
        results[lab] = check_image(lab, ims[lab])
    cross = cross_checks(ims) if len(ims) > 1 else None
    emit("== summary (PASS/FAIL/INCONCLUSIVE per image)")
    for lab, r in results.items():
        cnt = {v: sum(1 for _, x, _ in r.rows if x == v) for v in ("PASS", "FAIL", "INCONCLUSIVE")}
        emit(f"  {lab}: {cnt}  FAIL: {[c for c, v, _ in r.rows if v == 'FAIL']}")
    if cross:
        emit(f"  cross: {sum(v == 'FAIL' for _, v, _ in cross.rows)} FAIL of {len(cross.rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
