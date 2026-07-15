# Fuzzing strategy & coverage

Companion to [diamond-re-oracle.md](diamond-re-oracle.md).  That doc is *when*
to reach for Diamond; this one is *how to fuzz* and *what to cover*.

## The one rule: never optimise the sweep

**Sweep the full parameter space.  Do not prune.**  Targets are cheap to
build (~1 s each in Diamond) and re-runs are incremental (change-detection in
`run_all_fuzz.py` skips unchanged results), so there is no cost to going
bigger — and every reason to.

The whole point of fuzzing is to catch what you *didn't* predict:

- **The vendor may not have done what you expect.**  Pruning a combination
  because "that mode obviously reuses the same bits" bakes in an assumption
  the bitstream is there to test.
- **The vendor tool may be buggy.**  prjtrellis's EBR.MODE lives at the wrong
  bit address (`F1B35` vs `F1B33/F1B34`), and PULLMODE=NONE bits overlap
  BASE_TYPE — both are cases where the *tool* is wrong and a full cross-product
  is what surfaces it (see pluribus#29, #11).
- **A failure is data, not waste.**  A target that fails to build, or decodes
  to *zero* unknown bits when you expected some, tells you something real.
  `re_bottomio` decoding to 0 unknowns is how we learned a single high-speed
  pad does *not* trigger the CIB F24–F27 config — the gap needs adjacent pads.

Corollary: keep the design *minimal* (one primitive, tie unused inputs to
ground, register one output so nothing is optimised away) but the *parameter
sweep maximal*.

## Generating targets

`diamond-fuzz/scripts/gen_re_targets.py` mechanically emits target dirs under
`diamond-fuzz/targets/` (auto-discovered by `run_all_fuzz.py` via `iterdir`).
Primitive families reuse verified port-lists copied from the existing corpus
(`dp8kc_x9`, `pdpw8kc_x18`, `efb_spi`), so only the parameter block is swept
and instantiations are always well-formed.  Current families:

| Family | Sweep | Serves |
|---|---|---|
| `re_ebr_dp8kc_*` / `re_ebr_pdpw_*` | every DATA_WIDTH × REGMODE × WRITEMODE (~950 targets) | pluribus#29 items 1–2 (EBR.MODE F1B33/34, F1B32 3rd bit); #22, #128, AWG/ADC EBR paths |
| `re_efb_*` | every i2c1/i2c2/spi/tc/ufm combo × SPI_MODE, WBDATO→fabric | EFB_JF / JWBDATO-vs-JTAG disambiguation; #21/#134/#138 SPI control path; #28/#147 spy bitstream |
| `re_iostd_*` | every BASE_TYPE × PULLMODE × DRIVE on an edge pad (~352) | #11 PULLMODE/BASE_TYPE bit overlap; #29 item 4 FAILSAFE_RCV — the *silent-wrong-answer* class |
| `re_edge_*` | an output register on every edge package pin | #29 item 3 CIB F24–F27; #156/#129 ADC-A & bottom-edge dead pins; the DAC D0/D2/D6/D7 missing driver |
| `re_ident_*` / `re_cfgspi_*` | known-ident SPI readback, ordinary vs sysCONFIG-slave-SPI pins | #179 REG 0x05 ident (strategy-2 known-answer); #138 config-corner SPI decode |
| `re_jtag_*` | JTAGF ER1/ER2 bridge | JTAG hard-IP; feeds the JWBDATO/JTAG disambiguation |

Run:  `python3 diamond-fuzz/scripts/run_all_fuzz.py --targets 're_*' -j 4`
(missing-first ordering builds new targets before cached ones).

## Why better fuzz data pays off — proven both ways

An audit of every FPGA issue (open + closed, both repos) found two recurring
patterns where fuzzing gives a direct answer that hand-RE gave slowly or wrong.

**Retrospective — closed issues fuzz would have shortcut:**
- *The free stack cannot build the primitive* → the Diamond oracle is the only
  way.  **#142** (all 713 IOLOGIC/DDR fuzz runs failed — yowasp-nextpnr can't
  place MachXO2 DDR), **#168** (IDDRX2E BEL pins), **#141** (Yosys rejects EFB
  → *zero* fuzzer-derived EFB evidence, which is why the `EFB_JF` guess exists).
  Unarguable — this is the oracle's founding rationale.
- *prjtrellis's `bits.db` is wrong or incomplete* → a check-suite-backed
  cross-product catches it automatically.  **#11** (drive-4 LVTTL33 silently
  mis-decoded as MIPI/SSTL — a *wrong answer accepted as right*), **#60** (DAC
  F24–F27), **#22** (EBR.MODE), **#156** (CIB_EBR ADC pins).

**Prospective — open issues fuzz resolves:** pluribus#29 (all items), #179
ident, #138/#25 config-corner SPI — already served by the `re_*` families and
the existing `efb_*`/`ebr_*` corpus; mostly need *running and diffing against
V07*, not inventing.

**Honest boundary — NOT fuzz:** live-device reads (USERCODE/TraceID/die-temp,
SWD register captures) and off-chip pin destinations (#58/#27/#8) cannot come
from a static bitstream, no matter how much you fuzz.

## Highest-value investments (ranked)

1. **EBR mode re-fuzz + a MODE-bit `check.py`** — one defect corrupts *every*
   EBR decode; broadest blast radius, cheapest fix.  (`re_ebr_*` now covers the
   full sweep; the missing piece is `041-ebr_config/check.py` asserting the
   MODE bits + a DP8KC-vs-PDPW8KC differentiator.)
2. **Right-edge CIB_EBR pass-through routing** — unblocks the ADC-channel-A
   dead-pin family (#156, #129).  (`re_edge_*` starts this; a routing-through
   variant is the next step.)
3. **Full IO BASE_TYPE × PULLMODE × DRIVE** (`re_iostd_*`) — kills the
   silent-wrong-answer class (#11); a mis-decode that *looks* valid is worse
   than a visible `fan=0`.
4. **EFB WISHBONE/SPI output → fabric** (`re_efb_*`) — replaces the `EFB_JF`
   guess with ground truth.
5. **Run `re_cfgspi_*` + `re_ident_*` and diff against V07** — no new fuzzing;
   directly attacks #179/#138 via oracle strategies 1 and 2.

## Extending

Add a new family to `gen_re_targets.py`: reuse an existing target's `fuzz.v`
port-list as the template, sweep the parameter block exhaustively, emit one
dir per point.  Do not hand-write large primitive instantiations — copy a
verified one.  Do not skip "redundant-looking" points.
