#!/usr/bin/env python3
"""Corpus evidence for the Cyclone V signal-polarity rules (docs/altera/cycloneV/cyclonev-postfit-oracle.md "Polarity").

1. LUT data inputs: every routed cyclonev_lcell_comb data{a..f} port in build.vo, `!` or not.
2. Pad outputs: per output pin, Quartus obuf `.i(!...)` vs a `.bt` inverter line
   `i GPIO...:DATAOUT.<n> 1` / `i HMC...:<..>DOUT.<n> 1` carrying that pin.
Usage: python3 scripts/cyclonev_polarity_evidence.py
Log: tmp/logs/cyclonev_polarity_evidence.log
"""
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cyclonev"
LOG = REPO / "tmp" / "logs" / "cyclonev_polarity_evidence.log"


def main():
    lut = Counter()
    pad = Counter()
    exceptions = []
    n = 0
    for d in sorted(CORPUS.iterdir()):
        vo_p = d / "quartus" / "simulation" / "questa" / "build.vo"
        if not vo_p.is_file() or not (d / "decomp.bt").is_file():
            continue
        n += 1
        vo = vo_p.read_text()
        for cell in re.findall(r"^cyclonev_lcell_comb .*?\);", vo, re.M | re.S):
            for port, val in re.findall(r"\.data([a-f])\(([^)]*)\)", cell):
                val = val.strip()
                if val not in ("gnd", "vcc", ""):
                    lut[("inverted" if val.startswith("!") else "plain")] += 1
        pins = {}
        for line in (d / "build.pin").read_text().splitlines():
            p = [c.strip() for c in line.split(":")]
            if len(p) > 3 and p[2] == "output" and p[1]:
                pins[p[0]] = p[1]
        inv_pins = set()
        for line in (d / "decomp.bt").read_text().splitlines():
            m = re.match(r"^i (\S+) (\d) ; (\S+)", line)
            if m and m.group(2) == "1" and re.search(r":(DATAOUT|\w*DOUT)\.", m.group(1)):
                inv_pins.add(m.group(3))
        for name, i_val in re.findall(r"^cyclonev_io_obuf \\(\S+)~output \(\s*\.i\(([^)]*)\)", vo, re.M):
            pin = pins.get(name)
            if pin is None:
                continue
            q = i_val.strip().startswith("!")
            b = pin in inv_pins
            pad[(q, b)] += 1
            if q != b:
                exceptions.append(f"{d.name} {name} {pin} quartus_inv={q} bt_inv={b}")
    lines = [f"designs: {n}",
             f"LUT data inputs (routed): inverted={lut['inverted']} plain={lut['plain']}",
             "pad outputs (quartus `!`, bt inverter): " +
             " ".join(f"{k}={v}" for k, v in sorted(pad.items())),
             f"exceptions: {len(exceptions)}"] + exceptions[:20]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
