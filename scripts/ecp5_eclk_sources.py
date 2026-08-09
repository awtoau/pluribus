"""Which wires can legally drive an ECLKBRIDGECS input on this die?

Run INSIDE nextpnr, which owns the routing graph:

    nextpnr-ecp5 --12k --package CABGA256 --speed 8 \
        --run scripts/ecp5_eclk_sources.py

Answers the question the ECLK build failures kept re-asking one hop at a time:
`Failed to route arc ... from X2/Y49/JCLKOS2_PLL to X0/Y25/JCLK0_ECLKBRIDGECS1`.
A pip either exists in the database or it does not -- so enumerate the uphill
pips of the bridge inputs instead of instantiating primitives and rebuilding.

Prints, for each ECLKBRIDGECS/ECLKSYNCB input wire, every wire that can reach it
and the bel each source belongs to.
"""

TARGETS = ("ECLKBRIDGECS", "ECLKSYNC", "BRGECLK")


def wire_name(ctx, wire):
    return ctx.getWireName(wire)


def report(ctx):
    # The pip graph alone answers the question -- a wire name like
    # JCLKOS2_PLL already identifies its primitive, so no bel-pin walk is needed.
    # (This binding has getBelPinWire but no getBelPins, so a bel->pins map is
    # not available anyway.)
    driver_of = {}

    for wire in ctx.getWires():
        name = str(ctx.getWireName(wire))
        if not any(t in name for t in TARGETS):
            continue
        ups = list(ctx.getPipsUphill(wire))
        if not ups:
            continue
        print(f"\n=== {name}   ({len(ups)} uphill pip(s))")
        for pip in ups:
            src = ctx.getPipSrcWire(pip)
            sname = str(ctx.getWireName(src))
            who = driver_of.get(sname, [])
            print(f"    <- {sname}"
                  + (f"   [{', '.join(who)}]" if who else ""))
            # One more hop back: what can reach THAT source? This is where a
            # PLL output has to appear if the path is legal at all.
            for pip2 in ctx.getPipsUphill(src):
                s2 = str(ctx.getWireName(ctx.getPipSrcWire(pip2)))
                who2 = driver_of.get(s2, [])
                print(f"         <- {s2}"
                      + (f"   [{', '.join(who2)}]" if who2 else ""))


report(ctx)  # noqa: F821 -- `ctx` is injected by nextpnr
