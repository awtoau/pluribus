#!/usr/bin/env python3
"""Second pass: peek EVERY candidate's first 200 bytes, extract the exact
Lattice part string, and classify the build flow.

  'Part: LFE5U-85F-6CABGA381'  -> ecppack (prjtrellis/nextpnr open flow)
  'Lattice Semiconductor Corporation Bitstream ... Diamond' -> Diamond
Range: bytes=0-199 only, no full downloads.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

TMP = os.path.dirname(os.path.abspath(__file__))
PART_RE = re.compile(r"Part:\s*(LFE5[A-Z0-9]*-\d+[A-Z]+-\d+[A-Z]+\d+)")


def peek(x):
    p = subprocess.run(["curl", "-sL", "-r", "0-199", x["url"]], capture_output=True)
    raw = p.stdout[:200]
    if raw[:2] == b"\x1f\x8b":
        return x, "gzip", None
    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in raw)
    m = PART_RE.search(txt)
    if m:
        return x, "ecppack-open-flow", m.group(1)
    low = txt.lower()
    if "diamond" in low or "lattice semiconductor corporation bitstream" in low:
        return x, "DIAMOND", None
    return x, "unknown-header", None


def main():
    path = os.path.join(TMP, "corpus_github.json")
    d = json.load(open(path))
    print(f"peeking all {len(d)} candidates", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=16) as ex:
        for x, flow, part in ex.map(peek, d):
            base = [n for n in x["notes"].split("; ") if n and not n.startswith("flow=")]
            base.append(f"flow={flow}")
            if part:
                base.append(f"part={part}")
                # ground truth beats the filename guess
                dm = re.search(r"-(\d+[A-Z])-", part)
                if dm:
                    x["device_guess"] = dm.group(1)
                    if part.startswith("LFE5UM5G"):
                        x["device_guess"] += " (UM5G)"
                    elif part.startswith("LFE5UM"):
                        x["device_guess"] += " (UM)"
            elif flow == "DIAMOND":
                base.append("Lattice Diamond vendor-flow bitstream (HIGH VALUE)")
            x["notes"] = "; ".join(base)
    json.dump(d, open(path, "w"), indent=1)
    print("annotated", path, file=sys.stderr)


if __name__ == "__main__":
    main()
