#!/usr/bin/env python3
"""Cut a small test pair out of one corpus design's Quartus (compressed, uncompressed) .rbf pair.

Keeps header + PRAM (raw), CRAM frame 0, the densest frame, the last frame, postamble and 0xFF
tail.  The compressed side is Quartus' own key/nibble groups for those byte ranges, spliced
(every frame is CRC16-self-contained, so the cut stream is still well formed).  The expected
uncompressed side is Quartus' bytes for the same ranges; only its length field and the
option-RAM CRC16 are recomputed for the shorter length.

Usage: python3.15t scripts/cyclonev_compressed_fixture.py corpus/cyclonev/<design> OUTDIR
Writes OUTDIR/cv_fixture.compressed.rbf and OUTDIR/cv_fixture.rbf.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cyclonev_decompress as cd  # noqa: E402


def groups(coded):
    """Key/nibble groups of a coded stream, one per 2 output bytes."""
    nib = []
    for b in coded:
        nib += (b & 15, b >> 4)
    out, i = [], 0
    while i < len(nib) and i + 1 + cd.NV[nib[i]] <= len(nib):
        k = 1 + cd.NV[nib[i]]
        out.append(nib[i:i + k])
        i += k
    return out


def pack(nibs):
    assert len(nibs) % 2 == 0
    return bytes(nibs[i] | nibs[i + 1] << 4 for i in range(0, len(nibs), 2))


def main():
    d, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    c = (d / "bitstream.compressed.rbf").read_bytes()
    u = (d / "bitstream.rbf").read_bytes()
    h = cd.parse_header(c)
    info = {}
    assert cd.decompress(c, info) == u
    st, g, n = h["cram_start"], info["cram_frame"], info["cram_frames"]
    gr = groups(c[st:])
    assert 2 * len(gr) == len(u) - st
    dens = sorted(range(1, n - 1), key=lambda k: -sum(1 for x in u[st + k * g:st + (k + 1) * g] if x))
    for k in dens:
        ranges = [(0, g), (k * g, (k + 1) * g), ((n - 1) * g, len(u) - st)]
        nibs = [x for a, b in ranges for grp in gr[a // 2:b // 2] for x in grp]
        if len(nibs) % 2 == 0:
            break
    cc = c[:st] + pack(nibs)
    uu = bytearray(u[:st] + b"".join(u[st + a:st + b] for a, b in ranges))
    s = h["sync"]
    cd.fix_header(uu, s, len(uu))
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "cv_fixture.compressed.rbf").write_bytes(cc)
    (outdir / "cv_fixture.rbf").write_bytes(bytes(uu))
    print(f"{d.name}: frames 0, {k}, {n - 1} of {n}; compressed {len(cc)} B, uncompressed {len(uu)} B")


if __name__ == "__main__":
    main()
