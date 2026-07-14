#!/usr/bin/env python3
"""Unpack a MachXO2 vendor bitstream into named cells using pytrellis.

Bitstream -> named-cell recovery: read the raw .bin against Project
Trellis's MachXO2 database and emit the ChipConfig text form (tiles,
routing arcs, LUT INITs, IO enums) -- the input format for load.py.

Copied from awto-2000 debris/fpga/scripts/trellis_unpack.py and adapted
for pluribus (TRELLIS_BUILD/TRELLIS_DBROOT env vars, refuse-to-overwrite
guard so a careless invocation can never clobber an existing .config).

Usage: trellis_unpack.py BIN [OUT.config]
Env:   TRELLIS_BUILD  = libtrellis build dir containing pytrellis.so
       TRELLIS_DBROOT = prjtrellis database root
       TRELLIS_DEVICE = device name (default LCMXO2-1200)
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get(
    "TRELLIS_BUILD",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build"))
DBROOT = os.environ.get(
    "TRELLIS_DBROOT",
    "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: trellis_unpack.py BIN [OUT.config]", file=sys.stderr)
        return 2
    bin_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else bin_path + ".config"
    if os.path.exists(out_path):
        print(f"[unpack] REFUSING to overwrite existing {out_path}\n"
              "         delete it first or pass a different OUT.config",
              file=sys.stderr)
        return 1

    import pytrellis

    print(f"[unpack] load_database({DBROOT})")
    pytrellis.load_database(DBROOT)

    print(f"[unpack] reading bitstream: {bin_path}")
    with open(bin_path, "rb") as fh:
        raw = fh.read()
    # Trellis read_bit() requires an outer container header (LSCC or 0xFF 0x00),
    # but a raw MachXO2 config starts directly at the FF FF BD B3 sync word.
    # read_bit slurps the whole file and deserialise_chip scans for that sync,
    # so prepending a minimal 0xFF 0x00 header makes the file acceptable
    # without altering the config stream.
    read_path = bin_path
    if raw[:2] not in (b"\x4c\x53", b"\xff\x00"):
        patched = b"\xff\x00" + raw
        tmpdir = os.path.join(REPO, "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        read_path = os.path.join(
            tmpdir, os.path.basename(bin_path) + ".hdr.bit")
        with open(read_path, "wb") as fh:
            fh.write(patched)
        print(f"[unpack] raw config (starts {raw[:4].hex()}); "
              f"wrapped with FF 00 header -> {read_path}")
    bitstream = pytrellis.Bitstream.read_bit(read_path)

    device = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")
    print(f"[unpack] deserialise_chip_forced({device!r}) "
          "(MachXO2 compressed config carries no IDCODE/frame-count)")
    chip = bitstream.deserialise_chip_forced(device)
    try:
        print(f"[unpack]   device = {chip.info.name}  "
              f"({chip.info.num_frames} frames x {chip.info.bits_per_frame} bits)")
    except Exception as exc:  # noqa: BLE001 - informational only
        print(f"[unpack]   (chip.info unavailable: {exc})")

    print("[unpack] ChipConfig.from_chip()")
    cc = pytrellis.ChipConfig.from_chip(chip)
    text = cc.to_string()

    with open(out_path, "w") as fh:
        fh.write(text)
    print(f"[unpack] wrote named-cell config: {out_path} ({len(text)} bytes)")

    # --- quick recovery summary ------------------------------------------
    lines = text.splitlines()
    tiles = [ln for ln in lines if ln.startswith(".tile")]
    arcs = [ln for ln in lines if "arc:" in ln]
    inits = [ln for ln in lines if ".INIT" in ln and "word" in ln]
    enums = [ln for ln in lines if ln.strip().startswith("enum:")]
    ios = [ln for ln in enums if "PIO" in ln or "IO" in ln]
    print("\n[unpack] === recovery summary ===")
    print(f"  tiles configured : {len(tiles)}")
    print(f"  routing arcs     : {len(arcs)}")
    print(f"  LUT INIT words   : {len(inits)}")
    print(f"  enum settings    : {len(enums)}  (IO-related: {len(ios)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
