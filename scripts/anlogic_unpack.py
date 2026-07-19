#!/usr/bin/env python3
"""Anlogic EG4 (eagle_s20) bitstream unpacker  ->  normalized text config (#67).

The Anlogic analogue of scripts/gowin_unpack.py / trellis_unpack.py: it decodes
a raw Anlogic bitstream into a normalized ``.anloconfig`` text file that the
pure-Python lifter (lifters/anlogic_lift.py) reads back.  Pure Python, no heavy
deps — runs under the free-threaded python3.15t pipeline interpreter.

Two container encodings are handled (both are the SAME record set):
  * ASCII-header ``.bit``  — a text comment header, then binary blocks each
    prefixed by a 16-bit big-endian *bit* length; record tags have the MSB
    CLEAR (0x70 = DEVICE_ID, 0x6c = CONFIG, ...).  Each CLB frame is its own
    494-byte block.  (Tang Dynasty "ASCII bitstream" output.)
  * flash ``.bin``         — 0xFF padding, ``cc55aa33`` sync, then concatenated
    records ``Tag Flag Size(2 BE) Data CRC(2 BE)``; tags have the MSB SET
    (0xf0 = DEVICE_ID, 0xec = CONFIG, ...).  (What is stored in SPI flash and
    what the FNIRSI 2D15P target ships.)

Both carry: DEVICE_ID (idcode), a handful of sysconfig words, FRAMES geometry
(1259 x 488 bytes for eagle_s20), 1259 CLB config frames, then BRAM/mem-init
frames and a DONE marker.  The container framing + CRC-16/BUYPASS were
independently reverse-engineered and verified (see tmp/gowin/2d15p/NOTES.md);
this decoder re-checks every frame CRC.

Fuse-mapped output (optional): if a decoded fuse DB is supplied (--db DIR, from
scripts/anlogic_dbdecode.py) the config also carries the tile grid with per-tile
CRAM occupancy and recovered LUT-init words.

    CRAM MAPPING (PROVISIONAL — see NOTES).  A tile at (start_frame, start_bit)
    places fuse (frame_off f, bit_off b) at CRAM[start_frame+f][raw(start_bit+b)]
    where raw() inserts the two 6-bit db->raw gaps (3892 db bits -> 3904 raw).
    LUT-init (``MEMORY`` fuses) reads directly under this mapping and yields
    clean, recognizable inits.  Routing (``ARCVAL``) uses binary-encoded muxes
    whose selection needs the per-bit boolean expr evaluated (prjtang leaves
    this unfinished); it is NOT emitted as verified netlist here.

Usage:
    python3 scripts/anlogic_unpack.py <in.bit|in.bin> <out.anloconfig> \
        [--db tmp/anlogic/db] [--device EG4S20BG256]
"""

import argparse
import json
import os
import sys

# ── CRC-16/BUYPASS (poly 0x8005, init 0, non-reflected) ────────────────────────
_CRC_POLY = 0x8005
_CRC_TAB = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ _CRC_POLY) if (_c & 0x8000) else (_c << 1)
        _c &= 0xffff
    _CRC_TAB.append(_c)


def crc16(data):
    c = 0
    for b in data:
        c = ((c << 8) & 0xffff) ^ _CRC_TAB[(c >> 8) ^ b]
    return c


# eagle_s20 geometry (from devices.json / verified container)
FRAMES = 1259
FRAME_BYTES = 488
FRAME_BITS_RAW = FRAME_BYTES * 8          # 3904
DB_BITS = 3892
# the 12 unused bits appear as two 6-bit gaps; db-bit -> raw-bit
_GAP1, _GAP2 = 974, 2920


def db_to_raw(bit):
    if bit >= _GAP2:
        return bit + 12
    if bit >= _GAP1:
        return bit + 6
    return bit


EG4_IDCODES = {
    0x00014c35: "EG4X15/EG4X20BG256", 0x0e014c35: "EG4A15BG256",
    0x08014c35: "EG4A20BG256", 0x0c014c35: "EG4A20NG88",
    0x04014c35: "EG4D20EG176", 0x0a014c35: "EG4S20BG256",
    0x06014c35: "EG4S20NG88", 0x02014c35: "EG4S20CG324",
}


class Container:
    """Decoded bitstream: idcode, sysconfig words, CLB CRAM, BRAM frames."""

    def __init__(self):
        self.idcode = None
        self.device = None
        self.sysconfig = {}          # name -> int
        self.frames = []             # list of 488-byte CLB frame data
        self.frame_crc_ok = 0
        self.bram = []               # list of raw mem-init frame bytes
        self.n_frames_declared = None
        self.bytes_per_frame = None

    def bit(self, frame, raw_bit):
        """CRAM bit at (frame, raw_bit); MSB-first within each byte (libtang)."""
        return (self.frames[frame][raw_bit >> 3] >> (7 - (raw_bit & 7))) & 1


def _is_ascii_bit(data):
    return data[:1] == b"#"


def _parse_ascii_bit(data):
    """ASCII-header .bit: comment header then 16-bit-bitlength-prefixed blocks."""
    c = Container()
    hdr_end = data.find(b"\n\n")
    body = data[hdr_end + 2:] if hdr_end >= 0 else data
    blocks = []
    p = 0
    while p + 2 <= len(body):
        size_bits = (body[p] << 8) | body[p + 1]
        p += 2
        nbytes = (size_bits + 7) // 8
        blocks.append(body[p:p + nbytes])
        p += nbytes
    # record blocks (10-byte) carry tag (MSB clear) + flag + size + data + crc
    config_at = None
    for bi, b in enumerate(blocks):
        if len(b) == 4 and b[1] == 0xf0 and (b[0] | 0x80) == 0xec:
            config_at = bi          # '6c f0 <nframes>' config header block
            c.n_frames_declared = (b[2] << 8) | b[3]
            break
        if len(b) >= 6:
            _record(c, b, b[0] | 0x80)   # normalize tag MSB for dispatch
    if config_at is None:
        sys.exit("ASCII .bit: no CONFIG (6c f0 ..) block found")
    for n in range(c.n_frames_declared):
        blk = blocks[config_at + 1 + n]
        c.frames.append(blk[:FRAME_BYTES])
        stored = (blk[FRAME_BYTES] << 8) | blk[FRAME_BYTES + 1]
        if crc16(blk[:FRAME_BYTES]) == stored:
            c.frame_crc_ok += 1
    # BRAM/mem-init blocks: 1152-byte payloads after the CLB frames
    for blk in blocks[config_at + 1 + c.n_frames_declared:]:
        if len(blk) >= 1152:
            c.bram.append(blk[:1152])
    return c


def _parse_flash_bin(data):
    """flash .bin: FF padding, cc55aa33 sync, concatenated MSB-set records."""
    c = Container()
    pos = data.find(b"\xcc\x55\xaa\x33")
    if pos < 0:
        sys.exit("flash .bin: no cc55aa33 sync word")
    pos += 4
    while data[pos] != 0xec:                     # walk header records
        tag = data[pos]
        size = (data[pos + 2] << 8) | data[pos + 3]
        rec = data[pos:pos + 4 + size]
        _record(c, rec, tag)
        pos += 4 + size
    # 'ec f0 <nframes>' CONFIG header (no CRC on the 4-byte header itself)
    c.n_frames_declared = (data[pos + 2] << 8) | data[pos + 3]
    pos += 4
    for n in range(c.n_frames_declared):
        frame = data[pos:pos + FRAME_BYTES]
        c.frames.append(frame)
        stored = (data[pos + FRAME_BYTES] << 8) | data[pos + FRAME_BYTES + 1]
        # frame 0's CRC additionally covers the 'ec f0 <n>' header bytes
        span = data[pos - 4:pos + FRAME_BYTES] if n == 0 else frame
        if crc16(span) == stored:
            c.frame_crc_ok += 1
        pos += FRAME_BYTES + 6                    # 488 data + 2 crc + 4 pad
    # BRAM/mem-init region: after a short pad, records of 'ed 00 00 <col>' then
    # 1152 data bytes, stride 1162.  Skip the lead-in pad to the first 'ed'.
    scan = pos
    while scan < len(data) and scan < pos + 64 and data[scan] != 0xed:
        scan += 1
    if scan < len(data) and data[scan] == 0xed:
        pos = scan
    while pos + 4 + 1152 <= len(data) and data[pos] == 0xed:
        c.bram.append(data[pos + 4:pos + 4 + 1152])
        pos += 1162
    return c


def _record(c, rec, tag):
    """Dispatch one header record by its MSB-set tag."""
    data = rec[4:-2]
    if tag == 0xf0:                              # DEVICE_ID
        c.idcode = int.from_bytes(data, "big")
        c.device = EG4_IDCODES.get(c.idcode)
    elif tag == 0xc2:
        c.sysconfig["cfg1"] = int.from_bytes(data, "big")
    elif tag == 0xc3:
        c.sysconfig["cfg2"] = int.from_bytes(data, "big")
    elif tag == 0xc4:
        c.sysconfig["cfg_c4"] = int.from_bytes(data, "big")
    elif tag == 0xc5:
        c.sysconfig["cfg_c5"] = int.from_bytes(data, "big")
    elif tag == 0xca:
        c.sysconfig["cfg_ca"] = int.from_bytes(data, "big")
    elif tag == 0xc1:
        c.sysconfig["version_ucode"] = int.from_bytes(data, "big")
    elif tag == 0xc7:                            # FRAMES geometry
        c.n_frames_declared = int.from_bytes(data[0:2], "big")
        c.bytes_per_frame = int.from_bytes(data[2:4], "big")


def parse_container(path):
    data = open(path, "rb").read()
    c = _parse_ascii_bit(data) if _is_ascii_bit(data) else _parse_flash_bin(data)
    if len(c.frames) != FRAMES:
        sys.exit(f"expected {FRAMES} CLB frames, decoded {len(c.frames)}")
    return c


# ── fuse-DB-driven decode ──────────────────────────────────────────────────────

def load_db(dbdir):
    tg = json.load(open(os.path.join(dbdir, "tilegrid.json")))
    bcc = json.load(open(os.path.join(dbdir, "bccinfo.json")))
    return tg, bcc


def tile_occupancy(c, tile):
    """Count set CRAM bits in a tile's (rows x cols) window under the
    provisional mapping.  A real, mapping-consistent utilisation metric."""
    sf, sb = tile["start_frame"], tile["start_bit"]
    rows, cols = tile["rows"], tile["cols"]
    if sf < 0 or sb < 0 or rows <= 0 or cols <= 0:
        return 0
    n = 0
    for f in range(rows):
        fr = sf + f
        if fr >= FRAMES:
            break
        for b in range(cols):
            rb = db_to_raw(sb + b)
            if rb < FRAME_BITS_RAW and c.bit(fr, rb):
                n += 1
    return n


def recover_lut_inits(c, tile, fuses):
    """Reconstruct LUT-init words for a tile from its MEMORY fuses.
    Returns {(slice,lut): init16} for LUTs whose init is non-zero."""
    sf, sb = tile["start_frame"], tile["start_bit"]
    if sf < 0 or sb < 0:
        return {}
    acc = {}
    for fz in fuses:
        for sym, val in fz["data"].items():
            if not val.startswith("MEMORY("):
                continue
            if fz["expr"] != sym:            # bit carries this symbol directly
                continue
            slc, lut, idx = val[7:-1].split(",")
            fr = sf + fz["frame"]
            rb = db_to_raw(sb + fz["bit"])
            if fr >= FRAMES or rb >= FRAME_BITS_RAW:
                continue
            acc.setdefault((slc, lut), {})[int(idx)] = c.bit(fr, rb)
    out = {}
    for key, bits in acc.items():
        if len(bits) < 16:
            continue
        v = 0
        for i in range(16):
            v |= bits.get(i, 0) << i
        if v:                                # skip all-zero (unconfigured) LUTs
            out[key] = v
    return out


# ── config emission ────────────────────────────────────────────────────────────

def emit_config(c, out_path, tg, bcc, device_arg):
    device = device_arg or c.device or "EG4S20BG256"
    lines = []
    lines.append("# Anlogic EG4 (eagle_s20) normalized config — pluribus #67")
    lines.append("# CRAM/fuse mapping is PROVISIONAL (see scripts/anlogic_unpack.py).")
    lines.append(f".device {device}")
    lines.append(".package BG256")
    if c.idcode is not None:
        lines.append(f".idcode 0x{c.idcode:08x}")
    for k, v in c.sysconfig.items():
        lines.append(f".sysconfig {k} 0x{v:08x}")
    lines.append(f".frames {len(c.frames)} {FRAME_BYTES}")
    lines.append(f".frame_crc_ok {c.frame_crc_ok}/{len(c.frames)}")

    n_tiles = n_active = n_lut = 0
    if tg is not None and bcc is not None:
        # emit tile grid with occupancy, and recovered LUT inits
        for name in sorted(tg):
            t = tg[name]
            ttype = t["type"]
            occ = tile_occupancy(c, t)
            n_tiles += 1
            if occ:
                n_active += 1
            lines.append(
                f".tile {name} {ttype} {t['x']} {t['y']} "
                f"{t['start_frame']} {t['start_bit']} {t['rows']} {t['cols']} {occ}")
            fuses = bcc.get(ttype)
            if fuses and occ:
                for (slc, lut), init in recover_lut_inits(c, t, fuses).items():
                    lines.append(f"lut {name} {slc} {lut} {init:016b}")
                    n_lut += 1
    # BRAM init blocks (verified container content)
    for i, blk in enumerate(c.bram):
        if any(blk):
            hexrow = blk.hex()
            lines.append(f".bram_init {i} {hexrow}")

    lines.append(f"# summary: tiles={n_tiles} active={n_active} luts={n_lut} "
                 f"bram_blocks={sum(1 for b in c.bram if any(b))}")
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"tiles": n_tiles, "active": n_active, "luts": n_lut}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bitstream", help="input .bit (ASCII header) or .bin (flash)")
    ap.add_argument("out", help="output .anloconfig")
    ap.add_argument("--db", default=os.environ.get("ANLOGIC_DB"),
                    help="fuse DB dir from anlogic_dbdecode.py (else env ANLOGIC_DB)")
    ap.add_argument("--device", help="override device string")
    args = ap.parse_args()

    if os.path.exists(args.out):
        sys.exit(f"refusing to overwrite existing config: {args.out}")

    c = parse_container(args.bitstream)
    print(f"idcode=0x{c.idcode:08x} device={c.device} "
          f"frames={len(c.frames)} crc_ok={c.frame_crc_ok}/{len(c.frames)} "
          f"bram_frames={len(c.bram)}")
    if c.frame_crc_ok != len(c.frames):
        print(f"WARNING: {len(c.frames) - c.frame_crc_ok} frame CRC mismatches",
              file=sys.stderr)

    tg = bcc = None
    if args.db and os.path.isdir(args.db):
        tg, bcc = load_db(args.db)
        print(f"loaded fuse DB: {len(tg)} tiles, {len(bcc)} tile types")
    else:
        print("no fuse DB (--db) — emitting device/sysconfig/BRAM only")

    stats = emit_config(c, args.out, tg, bcc, args.device)
    print(f"wrote {args.out}: {stats}")


if __name__ == "__main__":
    main()
