#!/usr/bin/env python3
"""VALIDATION FAILED -- method does not detect frame periodicity even on the
known-good sample. Kept as a negative result (awto-dji#3, air-side m1900 die
ID); do not build on this without re-deriving why it failed first.

Idea tested: decompress a Cyclone V CRAM payload with Mistral's universal
nibble rule (die-independent decode loop, die constants only set the output
length -- confirmed by reading cv-files.cc directly), then look for
byte-periodicity at the die's own `cram_frame_bytes` width via
autocorrelation. If real, this would identify a die from raw bytes alone,
no Mistral tile database needed.

Validation on m2001 (confirmed e50f, 5CEBA4U19C8) -- this script's own
--die-hint e50f run against m2001.depack.bin:
  - Offset/decompress arithmetic DOES check out: decompressed length lands
    exactly on the predicted framed_bytes (2,597,992), cram_sx recovers
    exactly 4958 (both derived independently from frame_size/cram_sy/
    pram_sizes read straight from libmistral/cvd-e50f.cc, not fitted).
  - But the expected period (524 = cram_frame_bytes) ranks 441st of 2016
    candidate periods by mean-abs-diff autocorrelation -- no peak at all.
  - Per-byte-position variance across frames (mod cram_frame_bytes) at the
    known CRC16 footer offset is indistinguishable from the overall mean
    (1041 vs 1035 overall); the actual min/max-variance positions are
    unrelated, scattered offsets.
  - Likely cause: CRAM bits are NOT stored byte-aligned-by-logic-column --
    rbf_load's cram[] bit-unpack applies a ya/yb permutation (`pos = 224 +
    (31^yb) + 32*ya`) that scrambles logical placement across the frame's
    bit layout before any byte-level locality could show up. Byte-level
    autocorrelation on the raw decompressed stream is the wrong lens for
    this; detecting real structure would need the same permutation
    Mistral's own bmux/cram decode applies, i.e. would need the die's
    tile database after all -- defeating the method's own point.

Also falsified along the way: rbf_save()'s per-first/last-frame marker
bytes (0x84 0x3e 0x01 / 0x42 0x9f 0x00) are a Mistral SAVE-path-only
convention, not present in real Quartus-produced bitstreams, and never
checked by rbf_load() on load -- not a usable frame-boundary sentinel.

Implements the universal nibble-decompression rule from
/mnt/2tb/git/mistral/libmistral/cv-files.cc rbf_load() (read directly, lines
~47-100) plus the CRAM-start-offset arithmetic from the same function
(oram_frame_bytes/pram_frame_bytes/pram_blocks), using per-die constants
read directly from libmistral/cvd-<die>.cc (frame_size, pram_sizes[],
cram_sx, cram_sy) -- NOT from memory/paraphrase.
"""
import sys
import numpy as np

DIES = {
    "e50f":   dict(frame_size=129, cram_sx=4958, cram_sy=3928,
                   pram_sizes=[3383,5071,4826,3383,2494,2732,2449,8226,5106,2418,3383,2449,2732,2449]),
    "gt75f":  dict(frame_size=173, cram_sx=6006, cram_sy=5304,
                   pram_sizes=[3433,5071,9669,4786,3383,2853,4791,7235,3383,9629,5106,4786,3433,6304,6800,9500]),
    "gt150f": dict(frame_size=227, cram_sx=7605, cram_sy=7024,
                   pram_sizes=[5806,7434,9669,8169,4862,7518,7204,4767,13012,5106,7204,5751,1984,9500,6800,9136]),
    "gt300f": dict(frame_size=317, cram_sx=10038, cram_sy=9948,
                   pram_sizes=[8224,7434,9669,10587,7280,7518,11971,5801,9629,5106,7204,8169,6800,9500,6800,9136]),
    "gx25f":  dict(frame_size=113, cram_sx=3856, cram_sy=3412,
                   pram_sizes=[2511,5071,4826,3383,2858,2368,2449,8226,5106,2418,3383,1984,9500]),
    "sx50f":  dict(frame_size=173, cram_sx=6006, cram_sy=5304,
                   pram_sizes=[3433,5071,9669,4786,3383,2853,7162,9607,3438,5066,3433,6304,6800,9500]),
    "sx120f": dict(frame_size=227, cram_sx=7605, cram_sy=7024,
                   pram_sizes=[5806,7434,9669,8169,4862,2772,7162,9607,3438,7484,5751,1984,9500,6800,9136]),
}


def die_geometry(die):
    c = DIES[die]
    frame_size = c["frame_size"]
    pram_sizes = c["pram_sizes"] + [0] * (32 - len(c["pram_sizes"]))
    mpram = max(pram_sizes)
    pram_frame_bytes = (frame_size + 2) * 4
    oram_frame_bytes = pram_frame_bytes + 104
    pram_blocks = (mpram + frame_size - 1) // frame_size
    cram_offset = oram_frame_bytes + pram_frame_bytes * pram_blocks
    cram_sx, cram_sy = c["cram_sx"], c["cram_sy"]
    padding = (64 - (cram_sy & 63)) ^ 32
    cram_frame_size = cram_sy + 256 + padding
    cram_frame_bytes = cram_frame_size // 8
    framed_bytes = cram_sx * cram_frame_bytes
    return dict(cram_offset=cram_offset, cram_frame_bytes=cram_frame_bytes,
                framed_bytes=framed_bytes, cram_sx=cram_sx)


def nibble_decompress(comp: bytes, target_len: int) -> bytes:
    """Universal rule from rbf_load(): 4-bit key nibble selects which of the
    2 output nibbles per output byte-pair are read vs implicit-zero. No
    die-specific branching in this loop itself (confirmed by reading the
    C++ -- die constants only set target_len, the stopping point)."""
    out = bytearray()
    pos = 0
    high = False
    n = len(comp)

    def r():
        nonlocal pos, high
        if high:
            high = False
            v = comp[pos] >> 4
            pos += 1
            return v
        else:
            high = True
            return comp[pos] & 0xF

    while len(out) < target_len and pos < n:
        key = r()
        v = r() if (key & 1) else 0
        v |= (r() << 4) if (key & 2) else 0
        out.append(v)
        v2 = r() if (key & 4) else 0
        v2 |= (r() << 4) if (key & 8) else 0
        out.append(v2)
    return bytes(out)


def autocorr_periodogram(stream: bytes, max_period: int, log=print):
    """Byte-level autocorrelation: for each candidate period P, mean
    |stream[i] - stream[i+P]| over i -- a REAL repeating frame structure
    produces a local MINIMUM in mean difference at P = true frame width
    (frames differ in content but less than random offset does, since
    per-frame overhead bytes like CRC/edcrc fields recur in the same
    position mod P)."""
    arr = np.frombuffer(stream, dtype=np.uint8).astype(np.int16)
    n = len(arr)
    scores = {}
    # only test periods that divide evenly into a plausible frame-width
    # range (~128-4096 bytes, covering all 7 dies' cram_frame_bytes), to
    # keep this O(max_period * n) pass affordable rather than scanning all
    # of n.
    for period in range(32, max_period, 1):
        usable = n - period
        if usable < period * 4:
            continue
        diff = np.abs(arr[:usable] - arr[period:period + usable])
        scores[period] = float(diff.mean())
    return scores


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--die-hint", default="e50f",
                     help="die whose geometry to use for the OFFSET/decompress-length "
                          "(validation step: must be the die's own confirmed geometry; "
                          "exploration step: try each of the 7 in turn)")
    ap.add_argument("--max-period", type=int, default=2048)
    args = ap.parse_args()

    data = open(args.target, "rb").read()
    geo = die_geometry(args.die_hint)
    print(f"die={args.die_hint} cram_offset={geo['cram_offset']} "
          f"cram_frame_bytes={geo['cram_frame_bytes']} framed_bytes={geo['framed_bytes']} "
          f"cram_sx={geo['cram_sx']}")
    print(f"file length={len(data)}, compressed region available="
          f"{len(data) - geo['cram_offset']}")

    comp = data[geo["cram_offset"]:]
    decompressed = nibble_decompress(comp, geo["framed_bytes"])
    print(f"decompressed length={len(decompressed)} (target {geo['framed_bytes']}, "
          f"{'MATCH' if len(decompressed) == geo['framed_bytes'] else 'SHORT -- ran out of input'})")

    scores = autocorr_periodogram(decompressed, args.max_period)
    best = sorted(scores.items(), key=lambda kv: kv[1])[:15]
    print("Top 15 lowest-mean-diff periods (candidate frame widths):")
    for period, score in best:
        flag = " <-- expected cram_frame_bytes" if period == geo["cram_frame_bytes"] else ""
        print(f"  period={period:6d}  mean_abs_diff={score:8.3f}{flag}")
    expected = geo["cram_frame_bytes"]
    if expected <= args.max_period:
        print(f"\nScore AT expected period {expected}: {scores.get(expected)}")
        rank = sorted(scores.items(), key=lambda kv: kv[1])
        rank_pos = next((i for i, (p, _) in enumerate(rank) if p == expected), None)
        print(f"Rank of expected period among {len(scores)} tested periods: {rank_pos}")


if __name__ == "__main__":
    main()
