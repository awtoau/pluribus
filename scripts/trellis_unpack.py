#!/usr/bin/env python3
"""Unpack a vendor bitstream into a prjtrellis-format `.config` (native decode).

Bitstream -> named-cell recovery: decode the raw .bin into the generic tile
config (tiles, routing arcs, LUT INITs, IO enums) that load.py consumes.

By default this uses the pure-Python **native** decoder
(`native_bitstream` + `native_tile_decode` + `native_config`), which is
LOSSLESS: it emits the exact same `.tile` sections as pytrellis PLUS the config
pytrellis silently drops at bitstream command 0x72 --

  * `.bram_init` sections  -- the EBR block-RAM initial contents, and
  * `.efb_block` sections  -- the 0x72 EFB feature/config-register preloads.

Pass `--legacy-pytrellis` to fall back to the old pytrellis path (tile sections
only; EBR/EFB data is lost) for A/B comparison.

Refuses to overwrite an existing output, so a careless invocation can never
clobber a .config that other work depends on.

Usage: trellis_unpack.py BIN [OUT.config] [--legacy-pytrellis]
Env:   TRELLIS_DBROOT = prjtrellis database root (native + legacy paths)
       TRELLIS_DEVICE = device name (default LCMXO2-1200)
       TRELLIS_BUILD  = libtrellis build dir (legacy path only)
"""

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
sys.path.insert(0, SCRIPTS)

PREAMBLE = bytes([0xFF, 0xFF, 0xBD, 0xB3])


def _summary(text):
    lines = text.splitlines()
    tiles = [ln for ln in lines if ln.startswith(".tile")]
    arcs = [ln for ln in lines if ln.startswith("arc:")]
    inits = [ln for ln in lines if ".INIT" in ln and ln.startswith("word:")]
    enums = [ln for ln in lines if ln.startswith("enum:")]
    ios = [ln for ln in enums if "PIO" in ln or "IO" in ln]
    unknowns = [ln for ln in lines if ln.startswith("unknown:")]
    brams = [ln for ln in lines if ln.startswith(".bram_init")]
    efbs = [ln for ln in lines if ln.startswith(".efb_block")]
    print("\n[unpack] === recovery summary ===")
    print(f"  tiles configured : {len(tiles)}")
    print(f"  routing arcs     : {len(arcs)}")
    print(f"  LUT INIT words   : {len(inits)}")
    print(f"  enum settings    : {len(enums)}  (IO-related: {len(ios)})")
    print(f"  unknown bits     : {len(unknowns)}")
    print(f"  EBR .bram_init   : {len(brams)}   <-- recovered (pytrellis drops these)")
    print(f"  EFB .efb_block   : {len(efbs)}   <-- recovered (pytrellis drops these)")


def run_native(bin_path, out_path, device):
    import native_config
    from native_tile_decode import DEFAULT_DB_ROOT

    db_root = DEFAULT_DB_ROOT
    print(f"[unpack] native decode: {bin_path}")
    print(f"[unpack]   device={device!r}  db_root={db_root}")
    text, pb, bram = native_config.config_from_file(
        bin_path, device=device, db_root=db_root)
    with open(out_path, "w") as fh:
        fh.write(text)
    print(f"[unpack] wrote native config: {out_path} ({len(text)} bytes)")
    print(f"[unpack]   frames_read={pb.frames_read}/{pb.num_frames} "
          f"crc_verified={pb.crc_verified}  EBR blocks={len(bram)}  "
          f"EFB blocks={len(pb.efb_blocks)}")
    _summary(text)
    return 0


def run_legacy_pytrellis(bin_path, out_path, device):
    """The OLD pytrellis path (kept for A/B comparison; drops EBR/EFB data)."""
    from lifters.machxo2_lift import DEF_BUILD_DIR, DEF_DBROOT
    sys.path.insert(0, DEF_BUILD_DIR)
    import pytrellis

    print(f"[unpack] (legacy pytrellis) load_database({DEF_DBROOT})")
    pytrellis.load_database(DEF_DBROOT)

    print(f"[unpack] reading bitstream: {bin_path}")
    with open(bin_path, "rb") as fh:
        raw = fh.read()
    # Trellis read_bit() requires an outer container header (LSCC or 0xFF 0x00),
    # but a raw MachXO2 config starts directly at the FF FF BD B3 sync word.
    # Prepending a minimal 0xFF 0x00 header makes the file acceptable without
    # altering the config stream.
    read_path = bin_path
    if raw[:2] not in (b"\x4c\x53", b"\xff\x00"):
        patched = b"\xff\x00" + raw
        tmpdir = os.path.join(REPO, "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        read_path = os.path.join(tmpdir, os.path.basename(bin_path) + ".hdr.bit")
        with open(read_path, "wb") as fh:
            fh.write(patched)
        print(f"[unpack] raw config (starts {raw[:4].hex()}); "
              f"wrapped with FF 00 header -> {read_path}")
    bitstream = pytrellis.Bitstream.read_bit(read_path)

    print(f"[unpack] deserialise_chip_forced({device!r})")
    chip = bitstream.deserialise_chip_forced(device)
    cc = pytrellis.ChipConfig.from_chip(chip)
    text = cc.to_string()
    with open(out_path, "w") as fh:
        fh.write(text)
    print(f"[unpack] wrote named-cell config: {out_path} ({len(text)} bytes)")
    _summary(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bin", help="input bitstream (.bin / .bit)")
    ap.add_argument("out", nargs="?", help="output .config (default BIN.config)")
    ap.add_argument("--legacy-pytrellis", action="store_true",
                    help="use the old pytrellis decode (drops EBR/EFB data)")
    args = ap.parse_args()

    bin_path = args.bin
    out_path = args.out if args.out else bin_path + ".config"
    if os.path.exists(out_path):
        print(f"[unpack] REFUSING to overwrite existing {out_path}\n"
              "         delete it first or pass a different OUT.config",
              file=sys.stderr)
        return 1

    device = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")
    if args.legacy_pytrellis:
        return run_legacy_pytrellis(bin_path, out_path, device)
    return run_native(bin_path, out_path, device)


if __name__ == "__main__":
    raise SystemExit(main())
