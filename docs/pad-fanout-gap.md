# The residual input-pad fanout gap

`load.py` reports, per bitstream:

    Input-pad fanout gap: N pads with no net_fanout

A pad in that count has a `net_in` in `pad_map` but nothing in
`net_fanout` consumes it: the recovered netlist claims the pin's signal
reaches no logic.  This note records what N actually is, so nobody
re-derives it.

## N is a lifter-defect count, not a design fact

The tempting reading — "the PnR routed that pin to a stub; it's an unused
channel" — is wrong, and there is a cheap way to prove it wrong for any
board that has more than one bitstream.

Load every bitstream you have for the same board under separate labels
and diff the pad table (`scripts/compare_pads.py LABEL...`).  Pads are
physically wired to the same peripherals in all of them, so:

- **A pin stitched in one bitstream and stranded in another is a lifter
  bug.** The board did not change between firmware builds; only the
  routing PnR happened to choose did.
- The union across bitstreams tells you which pins are genuinely live.
  If every pin is `+fan` somewhere, the residual is *entirely* modelling
  gaps and the board's pin annotation is corroborated end to end.

This was done for the board in `boards/aw2-2d82auto` (three firmware
versions, findings recorded with that RE project, not here): all pads had
identical direction in all three, every peripheral data pin was stitched
in at least one, and no pad was stranded in all three.  The "unused
channel" theory died there.  Which pads strand varies per bitstream,
apparently at PnR's whim — itself a strong tell that the fault is ours.

## Two distinct failure modes

`scripts/diag_fanout_gap.py LABEL CONFIG` prints the DSU class of each
stranded pad net and resolves every canonical key back to its bel pin.
That splits the residual cleanly.

### (A) Bus pickup never unified — the class is routing-only

The common mode.  A typical class:

    net=nNNNN: DSU class size=2
        (21, 3, 266)     <- JQ0, the pad's own fabric joint node
        (21, 3, 307)     <- the long-line it drives
        consumed by 0 LUT input(s), 0 FF input(s)

The pad drives a long-line and the class ends there.  The arc that picks
the signal back off that bus at another column *is* in the bitstream, but
`gkey()` maps its wire name to a different canonical, so the DSU never
merges the two halves of one physical net.

Same family as the H06E fix already in `gkey()` (anchoring `E{N}_H06E*`
at the pad's own column rather than col−N).  That cured some pads and
left these.  The survivors are all right-edge or top-edge pads, and their
classes span several columns carrying the *same* wire id — e.g. id 307
appearing at both `(18,2)` and `(21,2)` — which is exactly the anchoring
smell.  Look there first.

### (B) Canonical collision — a pad net merged with an FF's Q

Rarer, and worse:

    net=nNNNN: DSU class size=3
        (11, 0, 341)
        (11, 1, 270)
        (11, 3, 4885)  <- SLICEB.FF1.Q
        consumed by 0 LUT input(s), 0 FF input(s)

An input pad's joint node has been unioned with a flip-flop's **Q
output**.  That is physically impossible — it would be two drivers on one
node.  Two distinct physical wires are colliding on one
`(col, row, wire_id)` canonical, which silently **merges two unrelated
nets**.

The gap counter only notices when the merged net happens to have no
consumer.  The same collision anywhere else in the design fuses two
signals and nothing complains.  So (B) is not really a pad bug at all: it
is a netlist-correctness bug that a pad happened to expose, and it should
be fixed before (A).

Tell-tale in the diag output: a stranded net that "appears as a fanout
OUT_net Nx" with N > 0 — something else drives a net that a pad is
supposed to drive.

## Guard

`scripts/ffd_stats.py CONFIG` is the regression guard for the REG.SD
polarity bug, which used to dominate this counter: it dropped every
fabric-routed FF D input, stranding pads wholesale while leaving cell
counts and net names looking perfectly healthy.  Run it after any change
to FF or routing recovery — it exits non-zero if more than 10% of FFs
come back with a constant D.
