#!/usr/bin/env python3
"""Split a sipeed pack blob into BFNP-aligned blocks.

Usage:
  python3 scripts/split_sipeed_pack.py \
    --input sources/sipeed/slogic_combo8_pack_202309181010.bin \
    --outdir tmp/sipeed_split
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def find_all(haystack: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    pos = 0
    while True:
        pos = haystack.find(needle, pos)
        if pos < 0:
            return out
        out.append(pos)
        pos += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Input binary path")
    ap.add_argument("--outdir", required=True, help="Output directory")
    args = ap.parse_args()

    in_path = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    blob = in_path.read_bytes()
    bfnp_offsets = find_all(blob, b"BFNP")
    if not bfnp_offsets:
        raise SystemExit("No BFNP signatures found")

    manifest: dict[str, object] = {
        "input": str(in_path),
        "size": len(blob),
        "bfnp_count": len(bfnp_offsets),
        "blocks": [],
    }

    for i, start in enumerate(bfnp_offsets):
        end = bfnp_offsets[i + 1] if (i + 1) < len(bfnp_offsets) else len(blob)
        chunk = blob[start:end]
        out_name = f"block{i:02d}_{start:08x}_{end:08x}.bin"
        out_path = outdir / out_name
        out_path.write_bytes(chunk)

        fcfg_count = chunk.count(b"FCFG")
        pcfg_count = chunk.count(b"PCFG")
        sha256 = hashlib.sha256(chunk).hexdigest()

        block_info = {
            "index": i,
            "start": start,
            "end": end,
            "size": len(chunk),
            "fcfg_count": fcfg_count,
            "pcfg_count": pcfg_count,
            "sha256": sha256,
            "file": out_name,
        }
        cast_blocks = manifest["blocks"]
        assert isinstance(cast_blocks, list)
        cast_blocks.append(block_info)
        print(
            f"block {i}: off={start}-{end} size={len(chunk)} "
            f"FCFG={fcfg_count} PCFG={pcfg_count} sha256={sha256[:16]}..."
        )

    manifest_path = outdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
