#!/usr/bin/env python3.15t
"""Compare an unknown Altera/Intel .rbf-style image with the quartus_cpf .rbf set made by
fpga_family_probe.py: header block, length, 0xFF gap, trailer.  Read-only on the image.

  python3.15t scripts/fpga_family_compare.py IMAGE.bin [--rbf-dir tmp/m2001/rbf] [--skip 0x20]
"""
import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse(d):
    """(preamble length, header bytes up to the first 0xFF run >= 16, gap length, payload end)."""
    pre = len(d) - len(d.lstrip(b"\xff"))
    m = re.compile(rb"\xff{16,}").search(d, pre)
    hdr = d[pre:m.start()]
    gap = len(d[m.start():]) - len(d[m.start():].lstrip(b"\xff"))
    end = len(d.rstrip(b"\xff"))
    return pre, hdr, gap, end


def crc16_modbus(b):
    a = 0xFFFF
    for x in b:
        a ^= x
        for _ in range(8):
            a = (a >> 1) ^ (0xA001 if a & 1 else 0)
    return a


def hdr_crc_ok(d, pre):
    """Header CRC16 (CRC-16/MODBUS over the 40 bytes after the leading 0x6a, stored LE):
    holds on every quartus_cpf Cyclone III/IV rbf tried."""
    h = d[pre:pre + 43]
    return len(h) == 43 and crc16_modbus(h[1:41]) == h[41] | h[42] << 8


def lane(h, n):
    return "".join(str(x >> n & 1) for x in h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--rbf-dir", default=os.path.join(REPO, "tmp", "m2001", "rbf"))
    a = ap.parse_args()
    d = open(a.image, "rb").read()
    pre, hdr, gap, end = parse(d)
    print(f"image: preamble {pre:#x}, header {len(hdr)} B {hdr.hex()}, gap {gap}, payload end {end:#x} "
          f"(payload {end - pre})")
    print(f"header CRC16/MODBUS valid: {hdr_crc_ok(d, pre)}; bit-lane 1 of header bytes 9..16: {lane(hdr[9:17], 1)}")
    rows = []
    for f in sorted(os.listdir(a.rbf_dir)):
        if not f.endswith(".rbf"):
            continue
        r = open(os.path.join(a.rbf_dir, f), "rb").read()
        p2, h2, g2, e2 = parse(r)
        common = 0
        while common < min(len(hdr), len(h2)) and hdr[common] == h2[common]:
            common += 1
        rows.append((common, f, p2, len(h2), g2, e2 - p2, h2.hex()))
    rows.sort(reverse=True)
    for c, f, p2, hl, g2, ln, hx in rows[:25]:
        print(f"{c:3d} common hdr bytes  {f:34s} pre {p2:#x} hdr {hl:3d} gap {g2:6d} payload {ln:9d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
