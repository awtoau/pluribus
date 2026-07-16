#!/usr/bin/env python3
"""Serialize a native MachXO2 decode into prjtrellis `.config` TEXT.

This is the lossless replacement for `pytrellis ... ChipConfig.to_string()`.
It produces the SAME tile sections prjtrellis emits (byte-identical: `.device`
header, `.tile <name>:<type>` blocks with `arc:` / `word:` / `enum:` /
`unknown:` lines, in std::map iteration order) and then ADDITIONALLY emits the
config the old pytrellis path silently dropped at command 0x72:

  * `.bram_init <index>` sections    -- the EBR block-RAM initial contents,
    recovered from the parser's decoded 9-bit words (native_bitstream).
  * `.efb_block ...` sections        -- the 0x72 EFB feature/config-register
    preloads (see docs/cmd-0x72.md).

Tile decode (arcs/words/enums) is delegated to the proven, parity-verified
`native_tile_decode`; here we additionally reproduce prjtrellis's `unknown:`
lines by porting the coverage bookkeeping from
`TileBitDatabase::tile_cram_to_config` + `BitGroup::add_coverage`
(libtrellis/src/BitDatabase.cpp).  The additive sections port
`Bitstream.cpp::deserialise_chip` (EBR) and `ChipConfig::to_string` (format).

Everything is pure dict/list/tuple/bytearray -- safe under python3.14t NoGIL.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import native_bitstream  # noqa: E402
import native_tile_decode as ntd  # noqa: E402
from native_tile_decode import (  # noqa: E402
    DEFAULT_DB_ROOT, FAMILY, _match, get_tile_type, load_tilegrid, decode_tile,
)

# LSC_EBR_ADDRESS opcode; RAW records carrying it start with this byte.
LSC_EBR_ADDRESS = 0xF6
CMD_0x72 = 0x72
# MachXO2/MachXO3 EBR: 1024 nine-bit words per block (Chip.cpp bram_data_size).
BRAM_DATA_SIZE = {"MachXO2": 1024, "MachXO3": 1024, "MachXO": 1024, "ECP5": 2048}


# ---------------------------------------------------------------------------
# tile decode WITH prjtrellis coverage/unknown bookkeeping
# ---------------------------------------------------------------------------

def decode_tile_full(tt, cram, foff, boff, nframes, nbits):
    """Port of TileBitDatabase::tile_cram_to_config INCLUDING coverage/unknowns.

    Returns (arcs, words, enums, unknowns) where the first three are identical
    to ``native_tile_decode.decode_tile`` (same winner selection / ordering) and
    ``unknowns`` is the sorted list of set-but-uncovered tile-local (frame, bit)
    positions -- exactly the ``unknown:`` lines prjtrellis writes.

    Coverage rules (BitDatabase.cpp):
      * mux  : cover the WINNING arc's non-inverted bits.
      * word : cover, for EVERY bitgroup, the bits where inv != match(group).
      * enum : cover the WINNING option's non-inverted bits.
    """
    coverage = set()  # tile-local (frame, bit)

    arcs = []
    for sink in sorted(tt.muxes):
        best_src = None
        best_bits = None
        best_n = 0
        for src, bits in tt.muxes[sink]:          # already sorted by src
            if _match(bits, cram, foff, boff) and len(bits) >= best_n:
                best_src = src
                best_bits = bits
                best_n = len(bits)
        if best_src is not None:
            for (f, b, inv) in best_bits:          # winner: cover non-inv bits
                if not inv:
                    coverage.add((f, b))
            if best_n > 0:
                arcs.append((sink, best_src))

    words = []
    for name in sorted(tt.words):
        defval, groups = tt.words[name]
        val = []
        for g in groups:
            m = _match(g, cram, foff, boff)
            val.append(m)
            for (f, b, inv) in g:                  # cover bits where inv != m
                if inv != m:
                    coverage.add((f, b))
        valt = tuple(val)
        if valt != defval:
            valstr = "".join("1" if x else "0" for x in reversed(val))
            words.append((name, valstr))

    enums = []
    for name in sorted(tt.enums):
        defval, options = tt.enums[name]
        best_opt = None
        best_bits = None
        best_n = -1
        for opt in sorted(options):
            bits = options[opt]
            if _match(bits, cram, foff, boff) and len(bits) >= best_n:
                best_opt = opt
                best_bits = bits
                best_n = len(bits)
        if best_opt is None:
            if defval is not None:
                enums.append((name, "_NONE_"))
        else:
            for (f, b, inv) in best_bits:          # winner: cover non-inv bits
                if not inv:
                    coverage.add((f, b))
            if defval is not None and options.get(defval) == best_bits:
                pass
            else:
                enums.append((name, best_opt))

    unknowns = []
    for f in range(nframes):
        for b in range(nbits):
            if cram[foff + f][boff + b] and (f, b) not in coverage:
                unknowns.append((f, b))

    return arcs, words, enums, unknowns


def decode_chip_full(cram, tilegrid, db_root=DEFAULT_DB_ROOT, family=FAMILY,
                     self_check=True):
    """Decode every tile with unknowns.  Returns {tilename: (a, w, e, unk)}.

    When ``self_check`` is set, cross-checks (arcs, words, enums) against the
    parity-verified ``native_tile_decode.decode_tile`` and dies on any
    divergence -- so a bug in the coverage port can never silently corrupt the
    proven tile decode.
    """
    result = {}
    for name, meta in tilegrid.items():
        tt = get_tile_type(meta["type"], db_root, family)
        foff = meta["start_frame"]
        boff = meta["start_bit"]
        nframes = meta["cols"]   # tile spans `cols` frames
        nbits = meta["rows"]     # ... and `rows` bits
        a, w, e, unk = decode_tile_full(tt, cram, foff, boff, nframes, nbits)
        if self_check:
            ref = decode_tile(tt, cram, foff, boff)
            if (a != ref["arcs"] or w != ref["words"] or e != ref["enums"]):
                raise RuntimeError(
                    f"native_config decode divergence at tile {name}: "
                    f"arcs {a!r} vs {ref['arcs']!r}; words {w!r} vs "
                    f"{ref['words']!r}; enums {e!r} vs {ref['enums']!r}")
        result[name] = (a, w, e, unk)
    return result


# ---------------------------------------------------------------------------
# EBR block-RAM recovery (port of Bitstream.cpp EBR handling)
# ---------------------------------------------------------------------------

def build_bram_data(pb, bram_data_size):
    """Replay the parsed EBR records into {ebr_index: [values]} (prjtrellis order).

    Mirrors deserialise_chip: LSC_EBR_ADDRESS sets current_ebr/addr_in_ebr,
    LSC_EBR_WRITE appends 8 nine-bit words per 9-byte frame with rollover to the
    next block when addr_in_ebr reaches bram_data_size.  The 9-byte -> 8x9-bit
    unpack was already done by native_bitstream (each EBR_WRITE word is a tuple
    of 8 values), so we place those values directly.
    """
    bram = {}
    current_ebr = 0
    addr_in_ebr = 0

    def ensure(idx):
        if idx not in bram:
            bram[idx] = [0] * bram_data_size

    for kind, r in pb.records:
        if kind == "RAW" and r["raw"] and r["raw"][0] == LSC_EBR_ADDRESS:
            raw = r["raw"]
            # opcode + 3 skip + 4-byte big-endian address
            data = (raw[4] << 24) | (raw[5] << 16) | (raw[6] << 8) | raw[7]
            current_ebr = (data >> 11) & 0x3FF
            addr_in_ebr = data & 0x7FF
            ensure(current_ebr)
        elif kind == "EBR_WRITE":
            for words in r["words"]:               # each: tuple of 8 values
                if addr_in_ebr >= bram_data_size:
                    addr_in_ebr = 0
                    current_ebr += 1
                    ensure(current_ebr)
                ensure(current_ebr)
                blk = bram[current_ebr]
                for k in range(8):
                    blk[addr_in_ebr + k] = words[k]
                addr_in_ebr += 8
    return bram


# ---------------------------------------------------------------------------
# serialisation (port of ChipConfig::to_string, + additive sections)
# ---------------------------------------------------------------------------

def _tiles_text(decoded, tilegrid):
    """Emit the `.tile` sections, byte-identical to ChipConfig::to_string."""
    out = []
    for name in sorted(tilegrid):                  # std::map order (by tile name)
        a, w, e, unk = decoded[name]
        if not (a or w or e or unk):               # TileConfig::empty()
            continue
        out.append(f".tile {name}\n")
        for sink, src in a:
            out.append(f"arc: {sink} {src}\n")
        for nm, val in w:
            out.append(f"word: {nm} {val}\n")
        for nm, val in e:
            out.append(f"enum: {nm} {val}\n")
        for f, b in unk:
            out.append(f"unknown: F{f}B{b}\n")
        out.append("\n")
    return "".join(out)


def _bram_text(bram):
    """Emit `.bram_init` sections, byte-identical to ChipConfig::to_string."""
    out = []
    for idx in sorted(bram):
        out.append(f".bram_init {idx}\n")
        vals = bram[idx]
        for i, v in enumerate(vals):
            out.append(f"{v:03x}")
            out.append("\n" if i % 8 == 7 else " ")
        out.append("\n")
    return "".join(out)


def _efb_text(pb):
    """Emit `.efb_block` sections for the 0x72 EFB preloads (additive).

    prjtrellis has no text form for these (it never modelled 0x72); this is a
    pluribus-native, grep-friendly encoding the lifter can later consume.  Each
    block: a `.efb_block sel <hex> flags <hex> len <n>` header then a `data:`
    line of space-separated hex payload bytes.  See docs/cmd-0x72.md.
    """
    out = []
    for (_off, flags, sel, payload) in pb.efb_blocks:
        out.append(f".efb_block sel 0x{sel:02x} flags 0x{flags:02x} "
                   f"len {len(payload)}\n")
        out.append("data: " + " ".join(f"{b:02x}" for b in payload) + "\n")
        out.append("\n")
    return "".join(out)


def serialize(pb, decoded, tilegrid, device, family=FAMILY):
    """Full prjtrellis-format `.config` text for a native decode.

    ``pb``       : ParsedBitstream (native_bitstream) -- EBR words + EFB blocks.
    ``decoded``  : {tile: (arcs, words, enums, unknowns)} from decode_chip_full.
    ``tilegrid`` : the device tilegrid (for tile ordering).
    """
    parts = [f".device {device}\n\n\n"]            # device + endl+endl + sysconfig endl
    parts.append(_tiles_text(decoded, tilegrid))
    bram = build_bram_data(pb, BRAM_DATA_SIZE.get(family, 1024))
    parts.append(_bram_text(bram))
    parts.append(_efb_text(pb))
    return "".join(parts), bram


def config_from_file(bitpath, device="LCMXO2-1200", db_root=DEFAULT_DB_ROOT,
                     family=FAMILY, self_check=True):
    """Parse a .bit/.bin natively and return (text, pb, bram) for the full config."""
    pb = native_bitstream.parse_file(bitpath)
    tilegrid = load_tilegrid(device, db_root, family)
    decoded = decode_chip_full(pb.cram, tilegrid, db_root, family,
                               self_check=self_check)
    text, bram = serialize(pb, decoded, tilegrid, device, family)
    return text, pb, bram


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bitfile")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--device", default="LCMXO2-1200")
    args = ap.parse_args()
    text, pb, bram = config_from_file(args.bitfile, device=args.device)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    sys.stderr.write(
        f"# bram_init blocks={len(bram)} efb_blocks={len(pb.efb_blocks)} "
        f"bytes={len(text)}\n")


if __name__ == "__main__":
    main()
