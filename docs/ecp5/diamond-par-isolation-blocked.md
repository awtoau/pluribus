# The yosys-netlist-into-Diamond-PAR experiment does not work

The cleanest way to attribute a Diamond-versus-open-flow difference to a stage
is to feed the *same yosys netlist* into Diamond's place-and-route. If Diamond
still wins, it is the placer and the fix belongs in nextpnr; if the gap
disappears, it is Synplify/LSE and the fix belongs in yosys.

**That experiment cannot be run.** Diamond's `ngdbuild` will not accept a
yosys ECP5 netlist, for a reason that is structural rather than incidental.

## What was fixed, and what could not be

Three obstacles were solved and are documented in
`docs/upstream-yosys-edif-notes.md`: `$scopeinfo` cells emitted as undeclared
cell references, vector ports becoming duplicate pin names, and Amaranth's
`FREQUENCY PORT ... HZ` syntax. Each has a minimal reproducer, and
`./scripts/diamond_probe.py --edif-repro` re-checks them.

The fourth obstacle is not a bug to be worked around. `ngdbuild` rejects the
netlist with two error classes:

    ERROR - ngdbuild: INITVAL string not allowed on single-port or dual-port
    block cpu...integer_RegFilePlugin_logic_regfile_fpga.asMem_ram.1.9
    (TRELLIS_DPR16X4)

    ERROR - ngdbuild: Block cpu...decode_ctrls_0_up_Decode_INSTRUCTION_0_
    LUT4_Z_A_LUT4_Z_A_LUT4_Z_3:  missing INITSTATE property on ROM .

## Why it is structural

yosys and Diamond do not share a primitive vocabulary for the ECP5:

- **Distributed RAM.** yosys emits `TRELLIS_DPR16X4` with an `INITVAL` string
  (`"64'h0000000000000000"`). Diamond's library has no such cell -- its
  primitive is `DPR16X4C` -- and rejects `INITVAL` on that block outright.
  100 instances in `vexii_hello` (the CPU register file), 22 in the analyzer.
- **LUTs.** yosys writes `(property INIT (integer 32768))`. ngdbuild
  classifies these as ROMs and demands `INITSTATE` instead. This affects
  *every LUT4 in the design*.

`TRELLIS_*` is Project Trellis's own naming, invented for nextpnr, and it was
never intended to be read by Diamond. The two toolchains meet at the bitstream,
not at the netlist.

## The obvious workaround makes it worse

`synth_ecp5 -nolutram` avoids `TRELLIS_DPR16X4`, and was tried
(`./scripts/diamond_par_probe.py`). It removes the `INITVAL` error and leaves
the LUT4 one, which then applies to everything:

| variant | ngdbuild | distinct errors |
|---|---|---|
| baseline | rejected | 2 |
| `-nolutram` | rejected | **9899** |

Going from 2 errors to 9899 confirms the LUT4 `INIT`/`INITSTATE` mismatch is
the general case, not an edge case attached to a few cells.

The `-nolutram -nobram` variant goes further still and shows the vocabulary
gap directly:

    ERROR - ngdbuild: logical block 'usb.transmitter.remaining_crc_
    TRELLIS_FF_Q_6' with type 'TRELLIS_FF' is unexpanded.

Diamond has no `TRELLIS_FF` either. Once BRAM and LUTRAM inference are
disabled, enough of the design falls back to plain flip-flops that the flip-flop
cell type itself becomes the reported blocker. There is no subset of
`synth_ecp5` options that produces a netlist Diamond can read, because the
problem is the primitive names, not the options.

## What a fix would actually require

A `write_edif` mode, or a separate backend, that emits **Diamond's** ECP5
primitive vocabulary rather than Trellis's:

- `TRELLIS_DPR16X4` -> `DPR16X4C`, with `INITVAL` translated to whatever
  Diamond's library accepts on that cell (or dropped, if the RAM does not
  need initialisation).
- `LUT4` `INIT` -> `INITSTATE`, in Diamond's expected encoding.
- The same for `TRELLIS_FF` (whose `CEMUX`/`CLKMUX`/`LSRMUX`/`SRMODE`
  properties ngdbuild already warns it is ignoring), `CCU2C`, `PFUMX`,
  `L6MUX21`, `TRELLIS_IO`.

That is a real backend, not a patch -- and its value is limited, because it
only serves toolchain comparison. Nobody synthesises with yosys in order to
place with Diamond as a production flow.

## Consequence for the comparison

Stage attribution has to come from cell-level accounting instead: compare what
each flow *instantiated* from the same RTL, and reason about which stage is
responsible from the primitive mix. That is weaker than a controlled
transplant -- it cannot separate "Synplify inferred a better structure" from
"Diamond's mapper packed it better" -- and any conclusion drawn this way
should be stated with that limit attached.

The remaining like-for-like axis is the full-toolchain comparison
(`--mode lse`), which is a valid answer to "does Diamond produce a better
bitstream" even though it cannot say which half of Diamond did it.
