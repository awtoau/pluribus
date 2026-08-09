"""Constrain the CPU to a rectangle of the die, from inside nextpnr.

    nextpnr-ecp5 ... --pre-place scripts/ecp5_floorplan_cpu.py

WHY THIS EXISTS
---------------
The Cynthion SoC's `clk` critical path is 90% routing (16.14 ns of 18.28 ns) and
crosses the die four times: (2,26) -> (30,28) -> (56,7) -> (26,34).  Five of its
nine cells belong to VexiiRiscv's PcPlugin next-PC mux, whose four sources are
produced by plugins the placer scatters to opposite corners.  The BTB hop alone
((56,7) -> (26,34), BRAM to mux) is 6.57 ns -- 36% of the period.

CPU pipeline relaxations are already exhausted: --relaxed-btb and
--relaxed-branch are both on.  They add pipeline stages; they do not shorten
wires.  What is left is placement.

nextpnr's ECP5 LPF parser accepts only `LOCATE COMP ... SITE` -- there is no
REGION/UGROUP -- but the CORE has full region support (Region, CellInfo::region,
testRegion) and both `addBelToRegion` and `constrainCellToRegion` are exposed to
Python.  constrainCellToRegion walks hierarchy, so one call on the CPU's
hierarchical name constrains every leaf beneath it.

TUNING
------
Too tight and placement fails or congests (the region must hold the CPU's LUTs,
FFs and the BRAMs it reaches).  Too loose and it buys nothing.  Start generous
(about half the die), tighten while Fmax improves.  Judge with a SEED SWEEP, not
one build -- sd is 2-3 MHz, so a single result cannot tell a real gain from luck:

    python3.15t scripts/fpga_build_bench.py --pkg <dir> --seeds 8 --workers 8 \
        --nextpnr-arg=--pre-place --nextpnr-arg=scripts/ecp5_floorplan_cpu.py

Env overrides: CPU_REGION_X0/X1/Y0/Y1, CPU_CELL (hierarchical cell to constrain).
"""

import os

X0 = int(os.environ.get("CPU_REGION_X0", 0))
X1 = int(os.environ.get("CPU_REGION_X1", 40))
Y0 = int(os.environ.get("CPU_REGION_Y0", 0))
Y1 = int(os.environ.get("CPU_REGION_Y1", 30))
CELL = os.environ.get("CPU_CELL", "cpu.cpu")
REGION = "cpu_region"

print(f"floorplan: constraining '{CELL}' to x {X0}..{X1}, y {Y0}..{Y1}")

# createRectangularRegion CREATES the region and fills it with every bel in the
# rectangle.  Do not hand-roll this with addBelToRegion: that indexes
# `region[name]->bels` on a region that does not exist yet and SEGFAULTS
# (basectx.cc:129 dereferences a null unique_ptr).
ctx.createRectangularRegion(REGION, X0, Y0, X1, Y1)  # noqa: F821

# constrainCellToRegion walks ctx.hierarchy, but that map is only populated when
# the JSON carries hierarchy metadata -- with a flattened netlist it is empty and
# the call warns "No cell matched" and does nothing.  Match on the name PREFIX
# over ctx.cells instead, which is what actually exists at pre-place time.
# Iterating ctx.cells yields KeyValue objects; the IdString is kv.first.
prefix = CELL + "."
n = 0
for kv in ctx.cells:  # noqa: F821
    name = str(kv.first)
    if name == CELL or name.startswith(prefix):
        ctx.constrainCellToRegion(kv.first, REGION)  # noqa: F821
        n += 1
print(f"floorplan: constrained {n} cells under '{CELL}'")
if n == 0:
    print(f"floorplan: WARNING nothing matched '{CELL}' -- check the prefix")
