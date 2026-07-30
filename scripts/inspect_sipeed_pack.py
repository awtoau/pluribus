#!/usr/bin/env python3
"""Inspect and summarize the BFNP/FCFG/PCFG layout in a sipeed pack blob."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def find_all(buf: bytes, tag: bytes) -> list[int]:
    offsets: list[int] = []
    i = 0
    while True:
        i = buf.find(tag, i)
        if i < 0:
            return offsets
        offsets.append(i)
        i += 1


def parse_words(buf: bytes, off: int) -> list[int]:
    return list(struct.unpack("<4I", buf[off + 4 : off + 20]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Input pack binary")
    ap.add_argument(
        "--json-out",
        default="",
        help="Optional JSON output path with the parsed structure",
    )
    args = ap.parse_args()

    p = Path(args.input)
    b = p.read_bytes()
    size = len(b)

    bfnp = find_all(b, b"BFNP")
    fcfg = find_all(b, b"FCFG")
    pcfg = find_all(b, b"PCFG")

    tags = sorted(
        [(o, "BFNP") for o in bfnp]
        + [(o, "FCFG") for o in fcfg]
        + [(o, "PCFG") for o in pcfg],
        key=lambda x: x[0],
    )

    blocks: list[dict[str, object]] = []
    for i, start in enumerate(bfnp):
        end = bfnp[i + 1] if (i + 1) < len(bfnp) else size
        local_tags = [(o - start, t) for o, t in tags if start <= o < end]
        fcfg_local = [o for o, t in local_tags if t == "FCFG"]
        fcfg_deltas = [
            fcfg_local[j + 1] - fcfg_local[j] for j in range(len(fcfg_local) - 1)
        ]
        blocks.append(
            {
                "index": i,
                "start": start,
                "end": end,
                "size": end - start,
                "local_tags": local_tags,
                "fcfg_count": sum(1 for _, t in local_tags if t == "FCFG"),
                "pcfg_count": sum(1 for _, t in local_tags if t == "PCFG"),
                "fcfg_deltas": fcfg_deltas,
            }
        )

    timeline: list[dict[str, object]] = []
    for i, (off, name) in enumerate(tags):
        next_off = tags[i + 1][0] if (i + 1) < len(tags) else size
        timeline.append(
            {
                "offset": off,
                "tag": name,
                "next_distance": next_off - off,
                "words_le": parse_words(b, off),
            }
        )

    report = {
        "input": str(p),
        "size": size,
        "counts": {"BFNP": len(bfnp), "FCFG": len(fcfg), "PCFG": len(pcfg)},
        "blocks": blocks,
        "timeline": timeline,
    }

    print(f"file: {p}")
    print(f"size: {size}")
    print(f"counts: BFNP={len(bfnp)} FCFG={len(fcfg)} PCFG={len(pcfg)}")
    print("")
    print("blocks:")
    for bl in blocks:
        print(
            f"  block{bl['index']}: start={bl['start']} end={bl['end']} size={bl['size']} "
            f"FCFG={bl['fcfg_count']} PCFG={bl['pcfg_count']}"
        )
        deltas = bl["fcfg_deltas"]
        if isinstance(deltas, list) and deltas:
            uniq = sorted(set(int(x) for x in deltas))
            print(f"    FCFG delta pattern: {uniq}")

    print("")
    print("timeline:")
    for row in timeline:
        w = row["words_le"]
        assert isinstance(w, list)
        w_hex = [hex(int(x)) for x in w]
        print(
            f"  @{row['offset']:8d} {row['tag']:4s} next={row['next_distance']:6d} "
            f"words={w_hex}"
        )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("")
        print(f"json: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
