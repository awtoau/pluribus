#!/usr/bin/env python3.15t
"""TDP M9K write-enable port association test (#165): per tile with both write enables wired, does each enable share the FF clock domain of its own port's address+data (as lifted: we<->addr, we_b<->addr_b) or the other port's?
  python3.15t scripts/cycloneiv_clean_tdp_we_check.py --nl NL.pkl     Log tmp/logs/cycloneiv_clean_tdp_we_check.log
Counts only.  Clock domain of a pin group = set of FF clocks within 4 LUT/FF stages backwards (non-FF leaves ignored).
"""
import argparse, collections, logging, os, pickle, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_tdp_we_check.log")
log = logging.getLogger("tdp_we")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--nl", required=True); a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    sys.path.insert(0, REPO)
    nl = pickle.load(open(a.nl, "rb"))
    ff = {f["name"]: f for f in nl.ffs}; lut = {l["name"]: l for l in nl.luts}
    co = {f"co_{l['x']}_{l['y']}_{l['le']}": l["name"] for l in nl.luts}

    def clks(sigs, depth=4):
        seen, fr, out = set(), [s for s in sigs if s and not s.startswith(("1'", "0'"))], set()
        for _ in range(depth):
            nx = []
            for x in fr:
                if x in seen: continue
                seen.add(x)
                if x in ff:
                    out.add(ff[x]["clk"]); nx += [ff[x][k] for k in ("d",) if ff[x].get(k)]
                elif x in lut: nx += [p for p in lut[x]["pins"] if p]
                elif x in co: nx.append(co[x])
            fr = nx
        return out
    c = collections.Counter(); ex = []
    for m in nl.m9k:
        if not (m.get("modelled") and m.get("tdp")): continue
        if m["we_b"] in (None, "1'b0") or m["we"] in (None, "1'b0", "1'b1"): continue
        A = clks([p for p in m["addr"]]); B = clks([p for p in m["addr_b"]])
        wa, wb = clks([m["we"]]), clks([m["we_b"]])
        if not (A and B and wa and wb) or A == B: c["undecidable"] += 1; continue
        if wa <= A and wb <= B and not (wa <= B) : c["as lifted (we=A, we_b=B)"] += 1
        elif wa <= B and wb <= A and not (wa <= A): c["swapped (we in B domain, we_b in A domain)"] += 1; ex.append(f"{m['x']}_{m['y']}")
        else: c["mixed"] += 1
    log.info("[V] tdp tiles with both enables wired: %s", dict(c)); log.info("swapped examples %s", ex[:10])


if __name__ == "__main__": main()
