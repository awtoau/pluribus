#!/usr/bin/env python3
"""Round-trip proof for the native MachXO2 encoder (pluribus issue #34).

Proves `scripts/native_bitstream.py` decodes losslessly by re-encoding the
decoded representation back into a bitstream and comparing to the original:

  1. BYTE-EXACT      re_encode(decode(bin)) == bin, byte-for-byte.
  2. SEMANTIC        decode(re_encode(decode(bin))) yields a CRAM + command set
                     identical to decode(bin) (weaker fall-back if a compressor
                     tie-break diverges from Diamond).
  3. DATA-PRESENCE   the re-encoded stream still carries the 0x72 EFB blocks and
                     the EBR writes -- no silent truncation.

This is THE completeness proof the stock prjtrellis decoder fails (it truncates
at the undocumented 0x72 command).  No pytrellis / no server needed -- runs
purely against the native parser+encoder.  Run under python3.14t.

Logs to tmp/native_bitstream_roundtrip.log.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import native_bitstream as nb  # noqa: E402

LOG_PATH = os.path.join(REPO, "tmp", "native_bitstream_roundtrip.log")

# In-repo generic fuzz bitstream: the default test vector, runs out of the box.
FUZZ_BIT = os.path.join(REPO, "diamond-fuzz", "targets",
                        "re_efb_00000_S_nc", "impl1", "fuzz_impl1.bit")

# Opt-in real vendor bitstreams (board-specific, not shipped in this repo).
# Set PLURIBUS_VENDOR_BITSTREAMS to an os.pathsep-separated list of .bin/.bit
# paths to also exercise the compressed / bare-preamble vendor cases.
VENDOR_BITSTREAMS = [p for p in
                     os.environ.get("PLURIBUS_VENDOR_BITSTREAMS", "").split(os.pathsep)
                     if p]

CASES = [("fuzz re_efb_00000_S_nc (uncompressed)", FUZZ_BIT)]
CASES += [(f"vendor {os.path.basename(p)} (compressed)", p)
          for p in VENDOR_BITSTREAMS]

_log_fh = None


def log(msg=""):
    print(msg)
    if _log_fh:
        _log_fh.write(msg + "\n")
        _log_fh.flush()


def cram_equal(a, b):
    if len(a) != len(b):
        return False
    return all(a[i] == b[i] for i in range(len(a)))


def semantic_view(pb):
    """The decode result that must be invariant under re-encode."""
    ebr = [(k, r["params"], tuple(r["words"]))
           for k, r in pb.records if k == "EBR_WRITE"]
    return dict(
        cram=pb.cram,
        efb=[b[1:] for b in pb.efb_blocks],      # (flags, sel, payload)
        ebr=ebr,
        idcode=pb.idcode, usercode=pb.usercode, ctrl0=pb.ctrl0,
        frames_read=pb.frames_read,
    )


def compare_semantic(a, b):
    diffs = []
    if not cram_equal(a["cram"], b["cram"]):
        diffs.append("CRAM differs")
    for key in ("efb", "ebr", "idcode", "usercode", "ctrl0", "frames_read"):
        if a[key] != b[key]:
            diffs.append(f"{key} differs ({a[key]!r} != {b[key]!r})")
    return diffs


def first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def main():
    global _log_fh
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    _log_fh = open(LOG_PATH, "w")
    log(f"# python: {sys.version.split()[0]}")
    if not VENDOR_BITSTREAMS:
        log("# note: set PLURIBUS_VENDOR_BITSTREAMS (os.pathsep-separated) to "
            "also test real vendor streams")
    log("")

    results = []
    for label, path in CASES:
        log("=" * 72)
        log(f"CASE: {label}")
        log(f"  file: {path}")
        if not os.path.exists(path):
            log("  MISSING FILE -> FAIL")
            results.append((label, "missing", False))
            continue

        raw = open(path, "rb").read()
        pb = nb.parse_file(path)
        setbits = sum(sum(r) for r in pb.cram)
        n_efb = len(pb.efb_blocks)
        n_ebr = sum(1 for k, _ in pb.records if k == "EBR_WRITE")
        ebr_frames = sum(len(r["words"]) for k, r in pb.records if k == "EBR_WRITE")
        compressed = any(r["compressed"] for k, r in pb.records if k == "FRAMES")
        log(f"  decode: frames={pb.frames_read}/{pb.num_frames} "
            f"cram_setbits={setbits} compressed={compressed}")
        log(f"          efb_blocks={n_efb} ebr_writes={n_ebr} "
            f"ebr_frames={ebr_frames}")

        enc = nb.encode(pb)

        # --- (1) byte-exact ---------------------------------------------
        byte_exact = (enc == raw)
        if byte_exact:
            log(f"  [1] BYTE-EXACT: PASS  ({len(enc)} bytes identical)")
        else:
            d = first_diff(raw, enc)
            log(f"  [1] BYTE-EXACT: FAIL  len raw={len(raw)} enc={len(enc)} "
                f"first diff at 0x{d:x}")
            if d is not None and d < min(len(raw), len(enc)):
                log(f"      raw={raw[d:d+12].hex()}  enc={enc[d:d+12].hex()}")

        # --- (2) semantic round-trip ------------------------------------
        pb2 = nb.parse(nb.strip_bit_header(enc))
        sem_diffs = compare_semantic(semantic_view(pb), semantic_view(pb2))
        semantic_ok = not sem_diffs
        if semantic_ok:
            log("  [2] SEMANTIC:   PASS  (CRAM + EFB + EBR + registers identical "
                "after re-decode)")
        else:
            log("  [2] SEMANTIC:   FAIL  " + "; ".join(sem_diffs))

        # --- (3) data-presence in the re-encoded stream -----------------
        enc_efb = len(pb2.efb_blocks)
        enc_ebr = sum(1 for k, _ in pb2.records if k == "EBR_WRITE")
        presence_ok = (enc_efb == n_efb and enc_ebr == n_ebr
                       and pb2.frames_read == pb.frames_read)
        log(f"  [3] PRESENCE:   {'PASS' if presence_ok else 'FAIL'}  "
            f"re-encoded efb={enc_efb}/{n_efb} ebr={enc_ebr}/{n_ebr} "
            f"frames={pb2.frames_read}/{pb.frames_read}")

        level = "BYTE-EXACT" if byte_exact else (
            "SEMANTIC" if semantic_ok else "FAIL")
        ok = presence_ok and (byte_exact or semantic_ok)
        results.append((label, level, ok))

    log("")
    log("=" * 72)
    log("SUMMARY")
    allpass = True
    for label, level, ok in results:
        log(f"  [{'PASS' if ok else 'FAIL'}] {label}  ->  {level}")
        allpass = allpass and ok
    log("")
    log("ALL PASS" if allpass else "SOME FAILED")
    raise SystemExit(0 if allpass else 1)


if __name__ == "__main__":
    main()
