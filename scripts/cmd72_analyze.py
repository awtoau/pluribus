#!/usr/bin/env python3
"""Locate and validate the 0x72 command chain across many bitstreams.

For each file: strip .bit header if present, find the real post-frame tail by
trying every '72 10' candidate offset, walking from it with the length rule
(total = 4 + info[2]) through USERCODE/EBR/CNTRL0 to DONE.  A candidate is the
real one iff the walk reaches DONE with the USERCODE CRC OK.  Prints the 0x72
block(s) found (info bytes + payload) and PASS/absent.
"""
import sys, glob, os
sys.path.insert(0, os.path.dirname(__file__))
import cmd72_walk as w


def strip(raw):
    try:
        return w.strip_bit_header(raw)
    except Exception:
        return raw  # already raw (.bin)


def walk_tail(d, start):
    """Walk from `start` (a 0x72) to DONE. Return (ok, blocks) or (False, ...)."""
    r = w.Reader(d, start)
    blocks = []
    usercode_crc_ok = None
    while r.i < len(d):
        off = r.i
        op = r.opcode()
        if op == 0xFF:
            continue
        if op == 0x72:
            p = [r.byte() for _ in range(3)]
            payload = d[r.i:r.i + p[2]]
            r.skip(p[2])
            blocks.append((off, p[0], p[1], p[2], bytes(payload)))
        elif op in (0xC2, 0xC3):
            m = r.byte(); r.skip(2); r.u32()
            if m & 0x80:
                e, a = r.check_crc()
                usercode_crc_ok = (e == a)
            r.reset_crc()
        elif op == 0x22:
            r.skip(3); r.u32()
        elif op == 0x23:
            r.skip(3); r.u32()
        elif op == 0xF6:
            r.skip(3); r.u32()
        elif op == 0xB2:
            p = [r.byte() for _ in range(3)]; fc = (p[1] << 8) | p[2]
            for _ in range(fc):
                r.skip(9)
            if p[0] & 0x80:
                r.check_crc()
        elif op == 0xCE:
            r.skip(3)
        elif op in (0x5E, 0x7A):
            m = r.byte(); r.skip(2)
            if m & 0x80:
                r.check_crc()
            # Require a USERCODE CRC to have validated OK: this proves byte-exact
            # consumption of the 0x72 block(s) (they participate in the CRC region).
            return (usercode_crc_ok is True), blocks
        else:
            return False, blocks
        if r.i > len(d):
            return False, blocks
    return False, blocks


def analyze(path):
    raw = open(path, "rb").read()
    d = strip(raw)
    # candidate 0x72 command offsets: scan whole stream for 0x72 followed by a
    # plausible info byte, try walking to DONE from each.
    best = None
    s = 0
    while True:
        i = d.find(b"\x72", s)
        if i < 0:
            break
        s = i + 1
        if i + 4 > len(d):
            continue
        ok, blocks = walk_tail(d, i)
        # require the walk to actually consume 0x72 as first block and hit DONE
        if ok and blocks and blocks[0][0] == i:
            best = (i, blocks)
            break
    return best


def main():
    files = sys.argv[1:]
    for f in files:
        r = analyze(f)
        tag = os.path.basename(os.path.dirname(os.path.dirname(f))) or os.path.basename(f)
        if r is None:
            print(f"{tag:24s} : NO 0x72 (parses to DONE without it or absent)")
            continue
        off, blocks = r
        print(f"{tag:24s} : PASS  0x72@0x{off:x}  {len(blocks)} block(s)")
        for (bo, fl, mid, ln, pl) in blocks:
            print(f"    info={fl:02x} {mid:02x} {ln:02x} (len={ln}) payload={' '.join('%02x'%b for b in pl)}")


if __name__ == "__main__":
    main()
