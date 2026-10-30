#!/usr/bin/env python3.15t
"""Consumer search for the AF3-engine RAM (M9K 7_85 + 7_86), all 542 M9K modelled (#165).  Counts only.
  python3.15t scripts/cycloneiv_clean_ram_consumers.py --nl NL.pkl     log tmp/logs/cycloneiv_clean_ram_consumers.log
Forward closure (through LUTs, carries and FFs, any depth) from (a) the port-A / engine-side outputs o[0..17], (b) the port-B outputs o[18..35] of both tiles, and
(c) the engine's flag FF candidates; reports the sinks reached: pads, M9K pins (tile, pin class), MAC inputs, FF clock domains entered.
"""
import argparse, collections, logging, os, pickle, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_ram_consumers.log")
log = logging.getLogger("ram_consumers")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--nl", required=True); ap.add_argument("--flag", default="ff_6_90_6"); a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    nl = pickle.load(open(a.nl, "rb"))
    lut = {l["name"]: l for l in nl.luts}; ff = {f["name"]: f for f in nl.ffs}
    cons = collections.defaultdict(list)
    for l in nl.luts:
        for p in l["pins"] + ([l["cin"]] if l.get("cin") else []):
            cons[p].append((l["name"], "lut"))
        cons["co_" + l["name"][3:]]
    for f in nl.ffs:
        for k in ("d", "ena", "aclr", "sclr", "sload", "asdata"):
            if f.get(k): cons[f[k]].append((f["name"], k))
    for io in nl.ios:
        for k in ("drv", "oe"):
            if io.get(k): cons[io[k]].append(("pad_" + io["ball"], k))
    for m in nl.m9k:
        n = f"m9k_{m['x']}_{m['y']}"
        for k in ("data", "data_b", "addr", "addr_b", "raddr"):
            for s in (m.get(k) or []): cons[s].append((n, k))
        for k in ("we", "we_b", "ce", "ce_b", "ce_core", "ce_core_b"):
            if m.get(k): cons[m[k].lstrip("!")].append((n, k))
    for mm in nl.mac:
        for s in mm["a"] + mm["b"]: cons[s].append((f"mac_{mm['x']}_{mm['y']}", "in"))
    for l in nl.luts:     # a carry output is consumed as the next LE's cin pin: same name space as lc_ for the closure
        cons.setdefault("co_" + l["name"][3:], [])

    def closure(starts):
        seen, fr = set(starts), list(starts)
        sinks, doms = collections.Counter(), collections.Counter()
        while fr:
            nx = []
            for s in fr:
                for c, k in cons.get(s, ()):
                    if c in seen: continue
                    seen.add(c)
                    if c in ff:
                        doms[ff[c]["clk"]] += 1; nx.append(c)
                    elif c in lut:
                        nx.append(c); nx.append("co_" + c[3:])
                    else:
                        sinks[f"{c.split('_')[0]}_{c.split('_',1)[1] if c.startswith('pad_') else ''}" if c.startswith("pad_") else f"{c}:{k}"] += 1
            fr = nx
        return sinks, doms, len(seen)
    for name, starts in (("port-A outputs o[0..17] of 7_85/7_86", [f"m9k_{t}_o[{k}]" for t in ("7_85", "7_86") for k in range(18)]),
                         ("port-B outputs o[18..35] of 7_85/7_86", [f"m9k_{t}_o[{k}]" for t in ("7_85", "7_86") for k in range(18, 36)]),
                         (f"flag FF candidate {a.flag}", [a.flag])):
        sinks, doms, n = closure(starts)
        pads = {k: v for k, v in sinks.items() if k.startswith("pad_")}
        m9 = collections.Counter(k.split(":")[0] for k in sinks if k.startswith("m9k_"))
        mac = sum(1 for k in sinks if k.startswith("mac_"))
        log.info("[V] %s: %d nodes; FF clock domains entered %s; pads %s; M9K tiles %s (pins %s); MAC inputs %d", name, n, dict(doms), pads or "none", len(m9), dict(collections.Counter(k.split(":")[1] for k in sinks if k.startswith("m9k_"))), mac)
        log.info("      M9K tiles reached: %s", sorted(m9))


if __name__ == "__main__": main()
