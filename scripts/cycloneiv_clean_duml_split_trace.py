#!/usr/bin/env python3.15t
"""Meet-in-the-middle trace for the DUML/video split upstream of FX3 (#177).

Forward-tracing from the AD9363 RX bus explodes into the baseband/FEC block (tens of
thousands of FFs, per docs/lightbridge-fpga.md section 7's scramblers/CRC) before any
split point is reachable -- confirmed by a quick BFS, not assumed. Instead: walk
BACKWARD from the FX3 DQ bus drivers (known video leg) and separately identify any
candidate MCU-flag output pad, looking for a shared ancestor with the SPI0/MCU-interface
cluster (docs/lightbridge-fpga.md section 6, LAB region ~(25-40, 80-90)).

  python3.15t scripts/cycloneiv_clean_duml_split_trace.py --nl NL.pkl
Read-only. Log tmp/logs/cycloneiv_clean_duml_split_trace.log.
"""
import logging
import os
import pickle
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("duml_split")

FX3_DRV = ["lc_21_48_0", "lc_21_48_1", "lc_21_48_4", "lc_21_48_5",
           "lc_21_48_14", "lc_22_48_12", "lc_21_48_3", "lc_21_48_15"]
# Candidate MCU-flag output pads: no assigned chip_ref in pins.tsv, output direction,
# small/shared fan-in near the SPI0 cluster (found by manual pad_roles-style scan this pass).
FLAG_CANDIDATES = ["U22", "AC11", "AC10", "AD20", "AD21", "AD22", "AD23", "AD24"]


def _coord(name):
    m = re.match(r"(?:lc|ff)_(\d+)_(\d+)_", name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def backward_bfs(D, ffd, starts, cap=4000):
    """Bounded backward walk (same discipline as cycloneiv_clean_interior_bus_discover.py's
    cap -- comb chains can be long and trace_sinks only bounds FF-hop depth, not comb length)."""
    seen = set()
    frontier = set(starts)
    parent = {}
    hop_of = {}
    hop = 0
    while frontier and len(seen) < cap:
        nxt = set()
        for n in frontier:
            if n in seen:
                continue
            seen.add(n)
            hop_of[n] = hop
            if n in ffd:
                d = ffd[n].get("d")
                if d:
                    nxt.add(d)
                    parent.setdefault(d, n)
                continue
            cb = D.comb(n)
            if cb is not None:
                for u in cb[2]:
                    nxt.add(u)
                    parent.setdefault(u, n)
        frontier = nxt - seen
        hop += 1
    return seen, parent, hop_of


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs",
                                                                     "cycloneiv_clean_duml_split_trace.log"))])
    from lifters.cycloneiv_clean import patterns as PT
    nl = pickle.load(open(os.path.join(REPO, "tmp", "image_sim_dji_push", "nl.pkl"), "rb"))
    D = PT.Design(nl)
    ffd = {F["name"]: F for F in nl.ffs}
    lutd = {L["name"]: L for L in nl.luts}

    seen, parent, hop_of = backward_bfs(D, ffd, FX3_DRV, cap=1600)
    log.info("FX3 backward BFS: %d nodes before cap/exhaustion", len(seen))

    target = "ff_37_83_13"  # confirmed d=pad_AB11 (MCU SPI0 MOSI), the SPI0-region anchor
    if target in seen:
        path = [target]
        cur = target
        while cur in parent:
            cur = parent[cur]
            path.append(cur)
        path.reverse()
        log.info("PATH FX3-driver -> MCU SPI0 MOSI anchor (%d hops): %s", len(path) - 1, path)
    else:
        log.info("%s not reached within cap", target)

    log.info("Flag-candidate pad check (direction + driver-source):")
    for pad in FLAG_CANDIDATES:
        io = next((r for r in nl.ios if r.get("ball") == pad), None)
        if io is None or io.get("dir") != "output" or not io.get("drv"):
            log.info("  %s: not a usable output pad", pad)
            continue
        drv = io["drv"]
        F = ffd.get(drv)
        d = F.get("d") if F else drv
        src_pins = lutd.get(d, {}).get("pins") if d else None
        log.info("  %s: driver=%s coord=%s d-source-pins=%s", pad, drv, _coord(drv), src_pins)


if __name__ == "__main__":
    main()
