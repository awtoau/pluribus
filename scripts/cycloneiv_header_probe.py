#!/usr/bin/env python3.15t
"""Print the option-lane header of corpus builds (lane 0..4 hex) to see which header bits follow
device die, die variant, package, speed or temperature grade.

  python3.15t scripts/cycloneiv_header_probe.py gx150_smoke gx110_smoke ...
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_decompress as cd  # noqa: E402


def main():
    for n in sys.argv[1:]:
        info = {}
        cd.decompress((cc.CORPUS / n / "bitstream.rbf").read_bytes(), info)
        print(f"{n:24s} {cc.device_of(n):18s} lanes {info['lanes'][:4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
