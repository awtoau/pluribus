#!/usr/bin/env python3.15t
"""Retarget a bitstream to a different IDCODE, CRCs recomputed (#97 spin-off).

WHY THIS IS NOT A HEX EDIT
--------------------------
The IDCODE sits in the VERIFY_ID (0xE2) command, inside the CRC-protected command
stream.  Changing those four bytes with a hex editor leaves the stream's CRC16
describing the old value, and the configuration engine rejects the file -- so the
naive patch fails for a reason unrelated to whether the idea works.  Decoding and
re-encoding recomputes every CRC, which is only trustworthy because the ECP5
re-encode is byte-exact on 168/168 corpus bitstreams (#97).

Proof the patch is surgical: re-encoding WITHOUT a change reproduces the input
byte for byte, so any difference is attributable to the patch alone.

WHAT IT IS FOR
--------------
Several ECP5 parts share one die.  The evidence is not inference from our own
model -- it is the vendor's:

  * Diamond's own `LFE5U-12F_CABGA256.con` and `LFE5U-25F_CABGA256.con` are
    BYTE-IDENTICAL (443 rows, 197 I/O, same DQS/PLL/ECLK topology)
  * identical `frames` x `bits_per_frame` in devices.json -- 7562 x 592 for the
    whole 25F class, so the configuration memory is the same size
  * Trellis tilegrids for 12F and 25F are byte-identical files
  * only the IDCODE's top nibble differs: 12F 0x21111043, 25F 0x41111043,
    UM 0x0..., UM5G 0x8...

So the interesting question is whether a 25F-built bitstream, retargeted to the
12F IDCODE, configures a 12F and lights up fabric beyond the 12F's advertised
capacity.

READ THIS BEFORE BELIEVING A RESULT
-----------------------------------
Making the ID check pass is a TOOLING result and nothing more.  Three separate
things could still be true, and only hardware can separate them:

  1. Pure market segmentation -- the die is whole, the extra fabric works.
  2. Binning/salvage -- 12F parts are dies that FAILED test in the extra region.
     Then the extra LUTs are defective per-part, and the failure mode is the bad
     one: intermittently wrong rather than plainly dead.
  3. Something else is fused down (power, clocking) independently of the IDCODE.

A design that merely loads proves nothing; it has to be exercised over the extra
area, and a pass on one chip does not generalise to another. Treat a success as
"this specific part, this specific day".

    scripts/patch_idcode.py IN.bit OUT.bit --idcode 0x21111043
    scripts/patch_idcode.py IN.bit OUT.bit --as-device LFE5U-12F
    scripts/patch_idcode.py IN.bit --verify-only     # re-encode must be exact

Logs to ./tmp/logs/patch_idcode.log.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_bitstream as nb  # noqa: E402
import toolchain  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
VERIFY_ID = 0xE2


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("patch_idcode")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "patch_idcode.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def idcode_for(device):
    """The IDCODE devices.json gives for a part."""
    geom = nb.geometry_for(device)
    if geom.get("idcode") is None:
        sys.exit(f"{device} has no idcode in devices.json")
    return geom["idcode"]


def patch_records(pb, new_idcode, log):
    """Rewrite the IDCODE inside the raw VERIFY_ID record.

    The parser keeps VERIFY_ID as an opaque RAW span rather than a structured
    field, so the patch edits those bytes in place: opcode, three operand bytes,
    then the 32-bit IDCODE big-endian, matching how parse() reads it
    (skip_bytes(3) then get_uint32()).
    """
    hits = 0
    for i, (kind, r) in enumerate(pb.records):
        if kind != "RAW":
            continue
        raw = bytes(r["raw"])
        if not raw or raw[0] != VERIFY_ID or len(raw) < 8:
            continue
        was = int.from_bytes(raw[4:8], "big")
        r["raw"] = raw[:4] + new_idcode.to_bytes(4, "big") + raw[8:]
        log.info("  VERIFY_ID record %d: 0x%08x -> 0x%08x", i, was, new_idcode)
        hits += 1
    if not hits:
        sys.exit("no VERIFY_ID record found -- the bitstream may be built with "
                 "the ID check disabled (no_id_mode), in which case there is "
                 "nothing to patch and it already loads on any part of the family")
    return hits


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("infile")
    ap.add_argument("outfile", nargs="?")
    ap.add_argument("--idcode", help="target IDCODE, e.g. 0x21111043")
    ap.add_argument("--as-device", help="target part; its IDCODE is looked up")
    ap.add_argument("--device", help="device of the INPUT (default: from its IDCODE)")
    ap.add_argument("--verify-only", action="store_true",
                    help="only prove re-encode is byte-exact; write nothing")
    args = ap.parse_args()
    log = setup_logging()

    raw = open(args.infile, "rb").read()
    device = args.device
    if not device:
        from ecp5_corpus_test import identify
        device, family, idc, how = identify(args.infile)
        if not device:
            sys.exit(f"cannot identify {args.infile}: {how}; pass --device")
    geom = nb.geometry_for(device)
    log.info("input:  %s", args.infile)
    log.info("  device %s (%s), idcode 0x%08x, %d frames x %d bits",
             device, geom["family"], geom["idcode"], geom["num_frames"],
             geom["bits_per_frame"])

    stripped = nb.strip_bit_header(raw)
    pb = nb.parse(stripped, geom=geom)

    # Baseline: an unmodified re-encode MUST reproduce the input exactly, or the
    # patch cannot be attributed to the patch.
    baseline = nb.encode(pb)
    if baseline != stripped:
        sys.exit(f"re-encode is NOT byte-exact for this bitstream "
                 f"({len(baseline)} vs {len(stripped)} bytes) -- refusing to "
                 f"patch, since a difference could not be attributed to the patch")
    log.info("  baseline re-encode: BYTE-EXACT (%d bytes)", len(baseline))
    if args.verify_only:
        return 0

    if not (args.idcode or args.as_device):
        sys.exit("give --idcode or --as-device (or --verify-only)")
    target = (int(args.idcode, 16) if args.idcode
              else idcode_for(args.as_device))
    if not args.outfile:
        sys.exit("an output path is required when patching")

    log.info("patching to 0x%08x%s", target,
             f" ({args.as_device})" if args.as_device else "")
    patch_records(pb, target, log)
    out = nb.encode(pb)

    ndiff = sum(1 for a, b in zip(baseline, out) if a != b)
    log.info("  re-encoded %d bytes, %d differ from the unpatched stream "
             "(4 IDCODE + CRC bytes expected)", len(out), ndiff)
    if len(out) != len(baseline):
        log.warning("  length changed by %d -- unexpected for an IDCODE patch",
                    len(out) - len(baseline))

    # Re-decode to prove the patched stream is well-formed and carries the new id.
    #
    # Decode it AS THE TARGET, because that is what the file now claims to be --
    # and because parse() cross-checks the IDCODE against the geometry, so
    # re-reading it as the source part correctly raises a device mismatch.  For a
    # shared die the two geometries are numerically identical anyway (7562 x 592
    # across the whole 25F class), which is the very fact that makes the patch
    # interesting; the check is about provenance, not frame arithmetic.
    target_geom = (nb.geometry_for(args.as_device) if args.as_device
                   else dict(geom, idcode=target))
    if (target_geom["num_frames"], target_geom["bits_per_frame"]) != \
       (geom["num_frames"], geom["bits_per_frame"]):
        log.error("  GEOMETRY DIFFERS: %s is %dx%d but %s is %dx%d. These are "
                  "NOT the same die, so this patch cannot work -- the frame "
                  "layout itself differs.", device, geom["num_frames"],
                  geom["bits_per_frame"], args.as_device or hex(target),
                  target_geom["num_frames"], target_geom["bits_per_frame"])
        sys.exit(1)
    pb2 = nb.parse(out, geom=target_geom)
    log.info("  re-decode: idcode 0x%08x, frames %d/%d, crc_verified=%s",
             pb2.idcode or 0, pb2.frames_read, pb2.num_frames, pb2.crc_verified)
    if pb2.idcode != target:
        sys.exit(f"patched stream still reports 0x{pb2.idcode:08x}")
    same_cram = all(a == b for a, b in zip(pb.cram, pb2.cram))
    log.info("  CRAM unchanged by the patch: %s", same_cram)

    with open(args.outfile, "wb") as fh:
        fh.write(raw[:len(raw) - len(stripped)])   # original .bit header, if any
        fh.write(out)
    log.info("wrote %s", args.outfile)

    # Independent confirmation that the file is well-formed, not just
    # self-consistent: our decoder wrote it, so our decoder liking it proves little.
    ecpunpack = toolchain.tool("ecpunpack", "ECPUNPACK")
    if os.path.isabs(ecpunpack):
        import subprocess
        r = subprocess.run([ecpunpack, args.outfile, os.devnull],
                           capture_output=True, text=True)
        log.info("  ecpunpack (independent oracle): %s",
                 "accepts it" if r.returncode == 0
                 else f"rc={r.returncode}: {r.stderr.strip()[-160:]}")
    log.info("REMINDER: a loadable file is a tooling result. Whether fabric "
             "beyond the target part's advertised capacity actually works is a "
             "per-chip hardware question -- see this script's docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
