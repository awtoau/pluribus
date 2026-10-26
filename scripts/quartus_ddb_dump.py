#!/usr/bin/env python3.15t
"""Inflate the ddb files of one Cyclone IV device-info die into tmp/ddb/<die>_<kind>.bin.

  python3.15t scripts/quartus_ddb_dump.py --family cycloneivgx --die stingray4
Files are regenerable (derived artifacts); the Quartus install is never written.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import quartus_ddb as qd  # noqa: E402
import toolchain  # noqa: E402

KINDS = ["gid_database", "hdr", "icname", "routing", "asm", "place", "pad", "asmdb", "asmdb_dirt", "timing"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default="cycloneivgx")
    ap.add_argument("--die", required=True)
    ap.add_argument("--kinds", default=",".join(KINDS))
    a = ap.parse_args()
    src = Path(toolchain.quartus_bin()).parent / "common" / "devinfo" / a.family
    dst = REPO / "tmp" / "ddb"
    dst.mkdir(parents=True, exist_ok=True)
    for kind in a.kinds.split(","):
        f = src / f"ddb_{a.die}_{kind}.ddb"
        if not f.exists():
            print(f"{kind}: absent")
            continue
        try:
            _h, ms, raw = qd.read(f)
        except Exception as e:  # report, keep going: other kinds may use another container
            print(f"{kind}: {type(e).__name__}: {e}")
            continue
        data = b"".join(m[2] for m in ms)
        (dst / f"{a.die}_{kind}.bin").write_bytes(data)
        print(f"{kind}: {len(raw)} -> {len(data)} bytes, {len(ms)} members")
    return 0


if __name__ == "__main__":
    sys.exit(main())
