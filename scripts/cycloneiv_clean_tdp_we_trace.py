#!/usr/bin/env python3.15t
"""TDP M9K write-enable port association, full fan-in trace (#178): for the image's TDP tiles (7_85/7_86), print the
complete backward trace (FF clocks + immediate drivers) of we / we_b and of addr / addr_b.

RESOLVED (#178, 2026-10-31): this trace shows the gi9 net sharing a clock domain with addr_b and the gi11 net with addr,
which looks like a port-A/port-B swap vs m9k_tdp.py's A=gi9/B=gi11 reading -- but applying that swap broke hl_ram_6's
memory-content sim (a design that DOES exercise m9k_tdp.py, unlike what an earlier pass believed from a stale cached
netlist). The clock-domain match is a property of this specific design's own logic (an unrelated net happens to share
a clock with this port's address), not a general PIA-gi-to-port rule -- cache_pia_usage allocates PIA lines dynamically
per tile (M-016), so there is no fixed "this port's write enable shares its own address's clock domain" law to read off.
Kept for the raw per-tile fan-in data (still correct); do not re-derive a port-swap conclusion from it alone.
  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_tdp_we_trace.py     log tmp/logs/cycloneiv_clean_tdp_we_trace.log
Counts / net names only, no raw ROM/firmware data.
"""
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_tdp_we_trace.log")
log = logging.getLogger("tdp_we_trace")


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    pf = os.path.join(REPO, "tmp", "inventory_image.path")
    path = os.environ.get("PLURIBUS_DJI_IMAGE") or (open(pf).read().strip() if os.path.exists(pf) else None)
    if not path or not os.path.exists(path):
        raise SystemExit("PLURIBUS_DJI_IMAGE not set or missing")
    import cycloneiv_decompress as cd
    from lifters.cycloneiv_clean import emit
    plane = os.path.join(REPO, "tmp", "tdp_we_trace_plane.rbf")
    open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))
    try:
        cx = emit.Ctx()
        b = emit.Builder(cx, plane, "image", 2)
        nl = b.run()
    finally:
        os.remove(plane)
    ff = {f["name"]: f for f in nl.ffs}
    lut = {l["name"]: l for l in nl.luts}
    co = {f"co_{l['x']}_{l['y']}_{l['le']}": l["name"] for l in nl.luts}

    def trace(sig, depth=5, seen=None):
        """Backward trace: each hop prints the signal and, if it's an FF, its clock."""
        seen = seen if seen is not None else set()
        out = []
        frontier = [sig]
        for d in range(depth):
            nxt = []
            for s in frontier:
                if not s or s in seen or s.startswith(("1'",)):
                    continue
                seen.add(s)
                if s in ff:
                    f = ff[s]
                    out.append((d, s, "FF", f.get("clk")))
                    if f.get("d"):
                        nxt.append(f["d"])
                elif s in lut:
                    l = lut[s]
                    out.append((d, s, "LUT", None))
                    nxt.extend(p for p in l.get("pins", []) if p)
                elif s in co:
                    out.append((d, s, "CO->" + co[s], None))
                    nxt.append(co[s])
                else:
                    out.append((d, s, "?", None))
            frontier = nxt
        return out

    tiles = [m for m in nl.m9k if m.get("modelled") and m.get("tdp")]
    log.info("[V] TDP-modelled tiles in this image build: %s", [(m["x"], m["y"]) for m in tiles])
    for m in tiles:
        log.info("=== tile %d_%d ===", m["x"], m["y"])
        for key in ("we", "we_b"):
            log.info("-- %s = %s --", key, m.get(key))
            for d, s, kind, clk in trace(m.get(key)):
                log.info("   [%d] %s %s%s", d, s, kind, f" clk={clk}" if clk else "")
        for key in ("addr", "addr_b"):
            log.info("-- %s (first 2 of %d) --", key, len(m.get(key) or []))
            for p in (m.get(key) or [])[:2]:
                for d, s, kind, clk in trace(p, depth=3):
                    log.info("   [%d] %s %s%s", d, s, kind, f" clk={clk}" if clk else "")


if __name__ == "__main__":
    main()
