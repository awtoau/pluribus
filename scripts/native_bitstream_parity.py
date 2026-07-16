#!/usr/bin/env python3
"""Parity test: native MachXO2 parser CRAM vs prjtrellis pytrellis CRAM.

Proves `scripts/native_bitstream.py` decodes the CRAM byte-identically to the
reference oracle (pytrellis) for compressed vendor and uncompressed fuzz
bitstreams.

Oracle wrinkle: real vendor `.bin` test vectors typically start directly at
the preamble (no `.bit` header) and carry NO `VERIFY_ID`, so pytrellis can't
identify the chip.  They also contain the undocumented `0x72` command, which
pytrellis rejects.  Neither affects the CRAM (both live outside the config-frame
CRC region), so to build the oracle we:
  1. inject `VERIFY_ID <idcode>` immediately BEFORE the stream's `LSC_RESET_CRC`
     (the reset zeroes the CRC afterwards, so the frame-CRC region is unchanged);
  2. truncate the stream at the first post-frame command (the exact offset our
     native parser reports) and append a no-op `ISC_PROGRAM_DONE`, so pytrellis
     stops cleanly with the full CRAM already populated.
Well-formed `.bit` files (fuzz, and any vendor stream with header+VERIFY_ID) are
fed to pytrellis unchanged.

Run under python3.14t with pytrellis on PYTHONPATH/LD_LIBRARY_PATH.
Logs to tmp/native_bitstream_parity.log.
"""
import os
import sys
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import native_bitstream as nb  # noqa: E402

PREAMBLE = nb.PREAMBLE
LOG_PATH = os.path.join(REPO, "tmp", "native_bitstream_parity.log")

DB = os.environ.get("TRELLIS_DBROOT", "tmp/prjtrellis/database")

# In-repo generic fuzz bitstream: the default test vector, runs out of the box.
FUZZ_BIT = os.path.join(REPO, "diamond-fuzz", "targets",
                        "re_efb_00000_S_nc", "impl1", "fuzz_impl1.bit")

# Opt-in real vendor bitstreams (board-specific, not shipped in this repo).
# Set PLURIBUS_VENDOR_BITSTREAMS to an os.pathsep-separated list of .bin/.bit
# paths to also exercise the compressed / bare-preamble vendor cases.
VENDOR_BITSTREAMS = [p for p in
                     os.environ.get("PLURIBUS_VENDOR_BITSTREAMS", "").split(os.pathsep)
                     if p]

# (label, path)
CASES = [("fuzz re_efb_00000_S_nc (uncompressed)", FUZZ_BIT)]
CASES += [(f"vendor {os.path.basename(p)} (compressed)", p)
          for p in VENDOR_BITSTREAMS]

_log_fh = None


def log(msg=""):
    print(msg)
    if _log_fh:
        _log_fh.write(msg + "\n")
        _log_fh.flush()


def make_oracle_bit(raw, geom, cut_offset, tmp_path):
    """Build a pytrellis-parseable .bit from a bare-preamble vendor .bin.

    `cut_offset` is the byte index (in the header-stripped stream, which for a
    bare .bin equals the file) of the first post-frame command, from the native
    parser.  We keep bytes [0, cut_offset), append a no-op DONE, and inject a
    VERIFY_ID just before the RESET_CRC so pytrellis identifies the chip without
    disturbing the frame CRC.
    """
    assert raw[0:4] == PREAMBLE, "expected bare preamble .bin"
    # locate the first LSC_RESET_CRC (0x3B) after the preamble + dummy bytes.
    reset_at = raw.index(bytes([nb.LSC_RESET_CRC]), 4)
    verify = bytes([nb.VERIFY_ID, 0, 0, 0]) + struct.pack(">I", geom["idcode"])
    # cut_offset indexes the ORIGINAL raw stream; injection sits before it.
    body = raw[:reset_at] + verify + raw[reset_at:cut_offset]
    done = bytes([nb.ISC_PROGRAM_DONE, 0, 0, 0])
    header = b"\xFF\x00\xFF"  # minimal .bit metadata header
    out = header + body + done
    with open(tmp_path, "wb") as f:
        f.write(out)
    return tmp_path


def pytrellis_cram(pytrellis, bit_path):
    chip = pytrellis.Bitstream.read_bit(bit_path).deserialise_chip()
    c = chip.cram
    frames = c.frames()
    bits = c.bits()
    cram = [bytearray(bits) for _ in range(frames)]
    for f in range(frames):
        row = cram[f]
        for j in range(bits):
            row[j] = 1 if c.bit(f, j) else 0
    return cram, frames, bits, chip.info.name, chip.info.idcode


def compare(a, b):
    """Return None if identical, else (frame, bit, a_val, b_val)."""
    if len(a) != len(b):
        return ("frame-count", len(a), len(b), None)
    for f in range(len(a)):
        ra, rb = a[f], b[f]
        if len(ra) != len(rb):
            return (f, "bit-count", len(ra), len(rb))
        if ra != rb:
            for j in range(len(ra)):
                if ra[j] != rb[j]:
                    return (f, j, ra[j], rb[j])
    return None


def main():
    global _log_fh
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    _log_fh = open(LOG_PATH, "w")
    tmpdir = os.path.join(REPO, "tmp")
    os.makedirs(tmpdir, exist_ok=True)

    try:
        import pytrellis
    except ImportError as e:
        log(f"FATAL: cannot import pytrellis: {e}")
        log("Set PYTHONPATH/LD_LIBRARY_PATH to the build_ft dir and use python3.14t.")
        raise SystemExit(2)

    pytrellis.load_database(DB)
    log(f"# pytrellis database: {DB}")
    log(f"# python: {sys.version.split()[0]}")
    if not VENDOR_BITSTREAMS:
        log("# note: set PLURIBUS_VENDOR_BITSTREAMS (os.pathsep-separated) to "
            "also test real vendor streams")
    log("")

    geom = nb.MACHXO2_1200
    results = []

    for label, path in CASES:
        log("=" * 72)
        log(f"CASE: {label}")
        log(f"  file: {path}")
        if not os.path.exists(path):
            log("  MISSING FILE -> FAIL")
            results.append((label, False, "missing file"))
            continue

        raw = open(path, "rb").read()
        # --- native parse (full stream, handles 0x72) ---
        try:
            pb = nb.parse_file(path, geom=geom)
        except Exception as e:
            log(f"  native parse FAILED: {e}")
            results.append((label, False, f"native parse: {e}"))
            continue
        native_set = sum(sum(r) for r in pb.cram)
        log(f"  native: frames_read={pb.frames_read}/{pb.num_frames} "
            f"crc_verified={pb.crc_verified} setbits={native_set} "
            f"efb_blocks={len(pb.efb_blocks)}")
        if pb.frames_read != pb.num_frames:
            log(f"  FAIL: frames_read {pb.frames_read} != {pb.num_frames}")
            results.append((label, False, "frame count"))
            continue
        if not pb.crc_verified:
            log("  FAIL: final-frame CRC not verified")
            results.append((label, False, "crc not verified"))
            continue

        # --- build oracle input ---
        bare = raw[0:4] == PREAMBLE
        if bare:
            tmpbit = os.path.join(tmpdir, f"oracle_{os.path.basename(path)}.bit")
            oracle_path = make_oracle_bit(raw, geom, pb.frame_block_end, tmpbit)
            log(f"  oracle: injected VERIFY_ID + truncated at frame_block_end="
                f"0x{pb.frame_block_end:x}, DONE appended -> {os.path.basename(oracle_path)}")
        else:
            oracle_path = path  # well-formed .bit; pytrellis parses directly

        try:
            oc, ofr, obits, oname, oid = pytrellis_cram(pytrellis, oracle_path)
        except Exception as e:
            log(f"  pytrellis parse FAILED: {e}")
            results.append((label, False, f"pytrellis: {e}"))
            continue
        oset = sum(sum(r) for r in oc)
        log(f"  pytrellis: {oname} id=0x{oid:08x} frames={ofr} bits={obits} setbits={oset}")

        diff = compare(pb.cram, oc)
        if diff is None:
            log(f"  RESULT: PASS  CRAM byte-identical ({ofr}x{obits}, {oset} set bits)")
            results.append((label, True, "identical"))
        else:
            log(f"  RESULT: FAIL  first diff at frame/bit {diff[0]}/{diff[1]} "
                f"native={diff[2]} pytrellis={diff[3]}")
            results.append((label, False, f"diff at {diff[0]}/{diff[1]}"))

    log("")
    log("=" * 72)
    log("SUMMARY")
    allpass = True
    for label, ok, note in results:
        log(f"  [{'PASS' if ok else 'FAIL'}] {label}  ({note})")
        allpass = allpass and ok
    log("")
    log("ALL PASS" if allpass else "SOME FAILED")
    raise SystemExit(0 if allpass else 1)


if __name__ == "__main__":
    main()
