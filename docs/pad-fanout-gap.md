# The residual input-pad fanout gap

`load.py` reports, per bitstream:

    Input-pad fanout gap: N pads with no net_fanout

An input pad in that count has a `net_in` in `pad_map` but nothing in
`net_fanout` consumes it: the recovered netlist says the pin's signal
reaches no logic.  This note records what is (and is not) known about
the residual N, so nobody re-derives it.

State on 2026-07-14, after the REG.SD fix: **V07 = 3, V02 = 6, V4 = 6.**

## The pins are NOT dead — that hypothesis is disproven

An earlier comment in `load.py` guessed the stranded ADC pads were
unused channels the PnR had routed to a bus stub.  Loading all three
firmware versions of the same board and diffing
(`scripts/run_hantek_all.py` → `scripts/compare_pads.py`) kills that:

- All 45 configured pads have **identical direction** in V02, V4 and V07.
- Every one of the 16 ADC data pins is stitched to logic (`+fan`) in at
  least one firmware.  **No pad is stranded in all three.**
- Which pads strand differs per firmware, apparently at PnR's whim:

  | pin | signal   | V07   | V02   | V4    |
  |-----|----------|-------|-------|-------|
  | 35  | DAC_PD   | +fan  | NOFAN | +fan  |
  | 66  | ADC_D7A  | +fan  | NOFAN | +fan  |
  | 69  | ADC_D4A  | +fan  | +fan  | NOFAN |
  | 71  | ADC_D2A  | NOFAN | NOFAN | +fan  |
  | 74  | ADC_D1A  | +fan  | NOFAN | +fan  |
  | 75  | ADC_D0A  | +fan  | +fan  | NOFAN |
  | 83  | ADC_D0B  | +fan  | NOFAN | +fan  |
  | 84  | ADC_D1B  | +fan  | +fan  | NOFAN |
  | 85  | ADC_D2B  | +fan  | NOFAN | NOFAN |
  | 86  | ADC_D3B  | NOFAN | +fan  | NOFAN |
  | 96  | ADC_D6B  | +fan  | +fan  | NOFAN |
  | 97  | ADC_D7B  | NOFAN | +fan  | +fan  |

A pin that carries a signal in one firmware and not another, on the same
board, with the same pinout, is a **lifter modelling gap** — not a fact
about the design.  Every remaining NOFAN is a bug to be found.

Corollary worth stating plainly: the union across the three firmwares
corroborates the supplied board pinout completely.  All 16 ADC data
lines, both encode clocks, and the DAC bus are real, live, and used.

## Two distinct failure modes

`scripts/diag_fanout_gap.py LABEL CONFIG` prints the DSU class of each
stranded pad net and resolves each canonical key back to a bel pin.
That splits the residual cleanly in two.

### (A) Bus pickup never unified — the class is routing-only

The dominant mode (V07 pins 71/97; V02 pins 66/71/74/83/85).  Example:

    pin=71 ADC_D2A net=n2899: DSU class size=2
        (21, 3, 266)     <- JQ0, the pad's own fabric joint node
        (21, 3, 307)     <- the H06 bus wire it drives
        consumed by 0 LUT input(s), 0 FF input(s)

The pad drives a long-line and the class ends there.  The arc that picks
the signal back off that bus at some other column exists in the
bitstream, but `gkey()` maps its wire name to a *different* canonical, so
the DSU never merges the two halves.  This is the same class of bug as
the H06E right-edge fix (`gkey()` anchoring `E{N}_H06E*` at the pad's own
column) — that fix cured some pads and left these.  Note the affected
pads are all right-edge (C21) or top-edge (R0), and the classes span
several columns with the same wire id (e.g. 307 at both (18,2) and
(21,2)), which is exactly the anchoring smell.

### (B) Canonical collision — a pad net merged with an FF's Q

Rarer but worse (V07 pin 86; V02 pin 35):

    pin=86 ADC_D3B net=n2051: DSU class size=3
        (11, 0, 341)
        (11, 1, 270)
        (11, 3, 4885)  <- SLICEB.FF1.Q
        consumed by 0 LUT input(s), 0 FF input(s)

An input pad's joint node has been unioned with a flip-flop's **Q
output**.  Physically impossible: that would be two drivers on one node.
Two distinct physical wires are colliding on the same `(col,row,wire_id)`
canonical, which silently *merges two different nets*.  The gap counter
only notices because the merged net has no consumer, but the corruption
is real whether or not it happens to strand a pad — anywhere else in the
design this same collision would fuse two unrelated signals and nobody
would see it.  This one deserves priority over (A).

Tell-tale in the diag output: the stranded net "appears as a fanout
OUT_net Nx" with N > 0 — something drives a net that a *pad* is supposed
to drive.

## Reproducing

    python3 scripts/run_hantek_all.py                      # all 3 firmwares
    python3 scripts/compare_pads.py V02 V4 V07             # the table above
    python3 scripts/diag_fanout_gap.py V07 /mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config

## Guard

`scripts/ffd_stats.py` is the regression guard for the REG.SD bug that
used to dominate this counter (it dropped every fabric-routed FF D input
and stranded pads wholesale).  Run it after any change to FF or routing
recovery; it exits non-zero if more than 10% of FFs come back with a
constant D.
