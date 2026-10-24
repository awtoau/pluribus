#!/usr/bin/env python3.15t
"""Validate lifters/data/cyclonev_mac_model.v (our own cyclonev_mac model; the vendor atom is encrypted).

- Per corpus design whose build.vo has a cyclonev_mac: simulate build.vo ON OUR MODEL against the
  design's own source RTL (src/*.v), random vectors after a reset preamble.
- Trusted only if every DSP design shows model wrong == 0 and compared > 0.
- Result per design: ok | wrong | compared counts, same numbers as the `model=` field of the sim gate.
Usage: python3.15t scripts/cyclonev_dsp_model_check.py [<design> ...]
Log: tmp/logs/cyclonev_dsp_model_check.log
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_lifted_sim_check as gate  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_dsp_model_check.log"


def dsp_designs():
    out = []
    for d in gate.all_designs():
        vo = gate.CORPUS / d / "quartus" / "simulation" / "questa" / "build.vo"
        if vo.is_file() and re.search(r"^\s*cyclonev_mac\s", vo.read_text(), re.M):
            out.append(d)
    return out


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    designs = sys.argv[1:] or dsp_designs()
    bad = 0
    with open(LOG, "a") as fh:
        for d in designs:
            r = gate.check_design(d)
            line = (f"{d:24s} model={r['model']} compared={r['model_ok'] + r['model_wrong']} "
                    f"wrong={r['model_wrong']} lifted-vs-src={r['ls_ok']}/{r['ls_ok'] + r['ls_wrong']}")
            ok = r["model"] == "ok" and not r["model_wrong"]
            bad += not ok
            print(("OK   " if ok else "FAIL ") + line, flush=True)
            fh.write(("OK   " if ok else "FAIL ") + line + "\n")
    print(f"{len(designs) - bad}/{len(designs)} DSP designs: model == source RTL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
