#!/usr/bin/env python3
"""Anlogic Tang-Dynasty arch-DB decoder  ->  eagle_s20 fuse database (issue #67).

Tang Dynasty ships a per-family architecture database ``arch/<device>.db`` that
contains, in an obfuscated ASCII form, the *entire* fuse map: the tile grid
(which tile type sits where, and where in the CRAM its bits live) and, per tile
type, every configuration bit (routing arc / LUT-init / property).  This is the
Anlogic analogue of prjtrellis' fuzzed DB and apicula's chipdb — except Anlogic
already put it in their tool, so **no fuzzing and no license are required**: the
DB is simply decoded.

Obfuscation
-----------
The file is whitespace-separated records.  String fields are enciphered with a
position-dependent substitution keyed by the family name on line 0
(``0 eagle_s20 3`` -> key = ``eagle_s20``).  The cipher advances one key
position per *decoded* character across the whole stream (see :func:`decode`).
Numeric fields are plaintext.  This is the same cipher prjtang's ``unlogic.py``
uses, but prjtang's full-file structural walk is pinned to TD 4.2.885 and
desyncs on other releases (it was verified against TD 4.6.4 / March-2020 and the
Dec-2018 golden here, both of which diverge in the device-geometry preamble).

Robust extraction (this script)
-------------------------------
Rather than walk the whole file, we exploit that the cipher has only ``len(key)``
phases.  The two sections pluribus needs — ``bil_info`` (tile grid) and
``bcc_info`` (per-tile fuse bits) — sit near the end.  We brute-force the key
phase (0..len-1) on the first token of every line to LOCATE each section marker,
then decode that section directly from the located (line, keyphase).  This
skips every version-divergent middle section (device geometry, wires/pips,
models, timing, ...) and is therefore tolerant of the TD release.

Cross-check: on TD 4.6.4 eagle_s20 the bcc_info section decodes to exactly its
declared 147 tile-type entries and terminates on the line immediately before the
located bil_info marker — i.e. the two independently-located sections abut
perfectly, which is only possible if the whole decode stayed key-synced.

Output (``--out DIR``):
    DIR/tilegrid.json   name -> {type,x,y,rows,cols,start_frame,start_bit,flag}
    DIR/bccinfo.json    tiletype -> [ {name,type,frame,bit,xoff,yoff,expr,data}, ... ]
    DIR/meta.json       {family, device, key, markers}

Usage:
    python3 scripts/anlogic_dbdecode.py <arch/eagle_s20.db> --out tmp/anlogic/db
"""

import argparse
import json
import os
import sys


class Cipher:
    """Position-dependent substitution decipher (Tang-Dynasty arch DB).

    The key is the family name (line 0, field 1).  ``pos`` is the running key
    phase; it advances one step per character actually processed.  Callers seek
    to a known (line, pos) and decode forward; only decoded fields move ``pos``.
    """

    def __init__(self, key, pos=0):
        self.key = key
        self.pos = pos

    def decode(self, tok):
        key, o, i = self.key, [], 0
        pos = self.pos
        while i < len(tok):
            inp = ord(tok[i])
            mod = ord(key[pos])
            z = inp - mod
            if inp < mod:
                z += 0x5d
            if z < 0x20:
                z += 0x5d
            if inp == 0x20:
                z = 0x20
            pos = (pos + 1) % len(key)
            if inp != 0x21:          # 0x21 '!' escapes the next raw char
                o.append(chr(z))
            else:
                i += 1
                o.append(tok[i])
            i += 1
        self.pos = pos
        return "".join(o)


def _read_lines(path):
    with open(path, "r", errors="surrogateescape") as fh:
        return fh.read().split("\n")


def _family_key(lines):
    """Line 0 is ``0 <family> <arch_count>`` in plaintext."""
    parts = lines[0].split()
    if len(parts) < 3:
        sys.exit(f"unexpected arch-db header: {lines[0]!r}")
    return parts[1]


def _seek_marker(lines, key, marker):
    """Return (line_index, key_phase) where the first token deciphers to
    ``marker`` under some key phase, else (None, None).  The cipher has only
    len(key) phases, so this is a cheap per-line brute force."""
    klen = len(key)
    for idx, line in enumerate(lines):
        sp = line.split(None, 1)
        if not sp:
            continue
        tok = sp[0]
        if len(tok) != len(marker):
            # decode length can differ from raw length only via '!' escapes,
            # which markers never use; a fast length gate skips ~everything.
            if "!" not in tok:
                continue
        for phase in range(klen):
            if Cipher(key, phase).decode(tok) == marker:
                return idx, phase
    return None, None


class _Reader:
    """Sequential line reader tied to a Cipher, for decoding one section."""

    def __init__(self, lines, idx, cipher):
        self.lines = lines
        self.i = idx
        self.c = cipher

    def peek_raw(self):
        return self.lines[self.i].split()

    def take(self, decode_ids):
        toks = self.lines[self.i].split()
        self.i += 1
        for k in decode_ids:
            if k < len(toks):
                toks[k] = self.c.decode(toks[k])
        return toks


def decode_bil_info(lines, idx, phase, key):
    """Decode the tile grid.  Header:
        bil_info <max_col> <max_row> <?> <frames> <db_bits> <?> <n_tiles> <n_bel>
    then n_tiles records, grouped by grid location:
        <x> <y> <num>
          (num times) <inst> <type> <x> <y> <rows> <cols> <start_frame> <start_bit> <flag>
                      <blank>
    inst/type are enciphered (fields 0,1); the rest are plaintext.
    """
    r = _Reader(lines, idx, Cipher(key, phase))
    hdr = r.take([0])
    assert hdr[0] == "bil_info", hdr[:1]
    max_col, max_row = int(hdr[1]), int(hdr[2])
    n_tiles = int(hdr[7])
    tiles = {}
    total = 0
    for _ in range(max_row * max_col):
        loc = r.take([])
        x, y, num = int(loc[0]), int(loc[1]), int(loc[2])
        total += num
        for _j in range(num):
            t = r.take([0, 1])
            assert int(t[2]) == x and int(t[3]) == y, (t[:4], x, y)
            tiles[t[0]] = {
                "type": t[1], "x": int(t[2]), "y": int(t[3]),
                "rows": int(t[4]), "cols": int(t[5]),
                "start_frame": int(t[6]), "start_bit": int(t[7]),
                "flag": int(t[8]),
            }
            blank = r.take([])
            assert len(blank) == 0, ("bil_info: expected blank", blank[:4])
    if total != n_tiles:
        sys.exit(f"bil_info: decoded {total} tiles, header declares {n_tiles} "
                 f"(decode desync)")
    return tiles, {"max_col": max_col, "max_row": max_row,
                   "frames": int(hdr[4]), "db_bits": int(hdr[5]),
                   "n_tiles": n_tiles, "end_line": r.i}


def decode_bcc_info(lines, idx, phase, key):
    """Decode per-tile-type fuse bits.  Header ``bcc_info <count>``; then, per
    entry, ``<tiletype> 0 0 <k>`` followed by k fuse-bit blocks:
        <name> <type> <frame> <bit> <xoff> <yoff> <mwa> <remap> <n?> <n?>   (record)
        (expr token lines: 1 field each, NOT enciphered -> no key advance)
        (rpn  token lines: 1 field each, NOT enciphered)
        (data lines: '<sym> <value>' -> field 1 enciphered)
        <blank>                                                             (block end)
        ...
        <blank>                                                             (entry end)

    Keeping the cipher synced only requires decoding field 1 of 2-field (data)
    lines and fields 0,1 of the record; 1-field expr/rpn lines never advance the
    key, so a shape-driven block reader stays synced regardless of how many
    expr/rpn/data lines a bit carries.
    """
    r = _Reader(lines, idx, Cipher(key, phase))
    hdr = r.take([0])
    assert hdr[0] == "bcc_info", hdr[:1]
    count = int(hdr[1])
    db = {}
    for _e in range(count):
        h = r.take([0])
        name, k = h[0], int(h[3])
        bits = []
        for _b in range(k):
            rec = r.take([0, 1])
            item = {
                "name": rec[0], "type": rec[1],
                "frame": int(rec[2]), "bit": int(rec[3]),
                "xoff": int(rec[4]), "yoff": int(rec[5]),
                "mwa": int(rec[6]), "remap": int(rec[7]),
            }
            expr, rpn, data = [], [], {}
            seen_data = False
            while True:
                toks = r.peek_raw()
                if len(toks) == 0:
                    r.i += 1
                    break
                if len(toks) == 2:                 # data line: '<sym> <value>'
                    td = r.take([1])
                    data[td[0]] = td[1]
                    seen_data = True
                else:                              # expr/rpn token (no key move)
                    r.i += 1
                    if not seen_data:
                        (rpn if expr else expr).append(toks[0])
            item["expr"] = "".join(expr)
            item["rpn"] = "".join(rpn)
            item["data"] = data
            bits.append(item)
        db[name] = bits
        term = r.peek_raw()
        assert len(term) == 0, (f"bcc_info: entry {name} not blank-terminated",
                                term[:4])
        r.i += 1
    return db, {"count": count, "end_line": r.i}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archdb", help="Tang Dynasty arch/<device>.db")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    if not os.path.isfile(args.archdb):
        sys.exit(f"arch db not found: {args.archdb}")
    os.makedirs(args.out, exist_ok=True)

    lines = _read_lines(args.archdb)
    key = _family_key(lines)
    device = lines[0].split()[1]
    print(f"family/device key = {key!r}  ({len(lines)} lines)")

    bcc_idx, bcc_phase = _seek_marker(lines, key, "bcc_info")
    bil_idx, bil_phase = _seek_marker(lines, key, "bil_info")
    if bcc_idx is None:
        sys.exit("could not locate bcc_info marker (unexpected arch-db format)")
    if bil_idx is None:
        sys.exit("could not locate bil_info marker (unexpected arch-db format)")
    print(f"bcc_info @ line {bcc_idx} phase {bcc_phase}")
    print(f"bil_info @ line {bil_idx} phase {bil_phase}")

    bcc, bcc_meta = decode_bcc_info(lines, bcc_idx, bcc_phase, key)
    n_fuses = sum(len(v) for v in bcc.values())
    print(f"bcc_info: {len(bcc)} tile types, {n_fuses} fuse bits "
          f"(ends line {bcc_meta['end_line']})")
    # Strong consistency check: the independently-located bcc_info section must
    # decode right up to the independently-located bil_info marker (0..2 blank
    # separators between them).  A larger gap means the bcc walk desynced.
    gap = bil_idx - bcc_meta["end_line"]
    if not (0 <= gap <= 2):
        sys.exit(f"bcc_info decode desynced: ends line {bcc_meta['end_line']}, "
                 f"bil_info at {bil_idx} (gap {gap})")
    print(f"  consistency: bcc_info abuts bil_info (gap {gap} line) — decode synced")

    tiles, bil_meta = decode_bil_info(lines, bil_idx, bil_phase, key)
    print(f"bil_info: {len(tiles)} tiles, grid {bil_meta['max_col']}x"
          f"{bil_meta['max_row']}, {bil_meta['frames']} frames x "
          f"{bil_meta['db_bits']} db-bits")

    with open(os.path.join(args.out, "tilegrid.json"), "w") as fh:
        json.dump(tiles, fh)
    with open(os.path.join(args.out, "bccinfo.json"), "w") as fh:
        json.dump(bcc, fh)
    with open(os.path.join(args.out, "meta.json"), "w") as fh:
        json.dump({
            "family": key, "device": device, "key": key,
            "bcc": bcc_meta, "bil": bil_meta,
            "bcc_marker": [bcc_idx, bcc_phase],
            "bil_marker": [bil_idx, bil_phase],
        }, fh, indent=1)
    print(f"wrote fuse DB to {args.out}/")


if __name__ == "__main__":
    main()
