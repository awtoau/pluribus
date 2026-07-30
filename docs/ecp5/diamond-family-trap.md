# `ep5c00` is LatticeECP3, not ECP5

A naming trap in Diamond's install that invalidated several earlier findings
here, and is worth recording because it will catch the next person.

## The correction

`data/DiamondDevFile.xml` states it outright:

    <Family name="ECP5U"       text="sa5p00"
    <Family name="ECP5UM"      text="sa5p00m"
    <Family name="ECP5UM5G"    text="sa5p00g"
    <Family name="LatticeECP3" text="ep5c00"

`ep5c` reads like "ECP5" and means **ECP-3**. The real ECP5 tree is `sa5p00`.

Confirmed by contents: `ispfpga/sa5p00/data/` holds `LFE5U-12F_CABGA256.con`,
`.fil` and `.svg` — the exact Cynthion part. `ispfpga/ep5c00/data/` contains
**zero** `LFE5U` files.

This is the same class of error as the earlier `or5g00` false positive, where
`ReadBack`/`ReadCapture` were found in a LatticeSC/ECP2-era tree and mistaken
for ECP5 capability. **Every finding must be attributed to its device tree, and
the tree name must be checked against `DiamondDevFile.xml` rather than read.**

## What survived, re-checked against `sa5p00`

The bitgen options reported earlier from `ep5c00` were ECP3's. The real ECP5
list is nearly identical, with two differences:

    CfgMode      Disable, Flowthrough, Bypass
    RamCfg       Reset, NoReset
    DONEPHASE    T3, T2, T1, T0
    GOEPHASE     T1, T3, T2
    GSRPHASE     T2, T3, T1
    GWEPHASE     T2, T3, T1        <- ECP3 has GWDPHASE
    ES           Yes, No           <- ECP3 defaults No

Two capabilities confirmed present in the **real** ECP5 tree:

- **`-m <format>`** creates "mask" and "readback" files.
- **`-sei <type>`** injects a soft error into a bitstream frame, with `-site`
  selecting a site type. This pairs directly with SEDGA, and there is no open
  equivalent.

So the conclusion that these options exist for ECP5 and are missing from
`ecppack` stands — but it now rests on the right tree.

## Other findings from the mining pass

**`.con` files are plain text** — complete package and I/O topology for the
exact Cynthion parts: die coordinates, ball names, banks, LVDS/MIPI/DQS
capability. No reverse engineering needed.

**`bstool` dumps the vendor BFD to ASCII** (undocumented argument order).
Diffing 198 vendor tiles against trellis: **trellis is a strict subset — zero
tiles wrong or invented, 13 missing.** That is a strong endorsement of trellis
and a finite to-do list.

**`.spd` timing decoded** — roughly 10,300 conditioned arcs per speed grade
against trellis's 1051, and **34 I/O standards against trellis's 10**. Caveat:
the picosecond scaling is validated by magnitude and quantisation, but the
arc-name-to-trellis mapping is not established, so these need datasheet
spot-checks before use in a timing model.

**`ECP5.xfp`** carries bitstream opcodes and the PROGRAMN/INITN/DONE sequence —
directly relevant to the earlier conclusion that reconfigure-from-flash cannot
work, which is worth re-checking against it.

## Two puzzles resolved

`ReadCapture` is confirmed **not** ECP5. The webhelp prose says otherwise; the
binary wins. **The usage text is reliable, the webhelp prose is not** — which
inverts an assumption made earlier.

The SEDGA 77.5/155.0 oddity was OSCG frequencies bleeding into the wrong list.
The real legal set includes **62.0**, which Diamond's own comment omits and
trellis has right.
