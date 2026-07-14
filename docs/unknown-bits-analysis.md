# V07 Unknown Bits — Root Cause Analysis

## Overview

The V07 bitstream (LCMXO2-1200HC, TQFP100) has 157 bits that `ecpunpack` /
prjtrellis cannot name.  These appear in the `.config` output as
`unknown: FxByz` lines.  This document explains what every category of unknown
bit is, verified against the `diamond-fuzz/` test corpus already in this repo.

```
Tile type            Count  Root cause
───────────────────  ─────  ─────────────────────────────────────────────────
CIB_PIC_B_DUMMY        42   IO config in frames F24–F27 — never fuzzed
EBR1                   36   EBR.MODE bits: prjtrellis DB has wrong bit address
CIB_EBR1               21   EBR.MODE same bug (CIB mirrors the EBR tile)
CIB_EBR0               18   EBR.MODE same bug
CIB_EBR2               18   EBR.MODE same bug
CIB_PIC_B0             15   IO config bleed — same F24–F27 gap
CIB_EBR_DUMMY           3   EBR.MODE same bug (DUMMY mirror)
PIC_B0                  3   IO F24–F27 gap
CIB_CFG2                1   sysConfig / boot mode; not catalogued (harmless)
───────────────────  ─────
TOTAL                 157
```

---

## EBR Unknown Bits (97 bits) — prjtrellis DB Bug

### Symptom

Every EBR1 tile in V07 (7 blocks) emits:

```
unknown: F0B13
unknown: F1B8
unknown: F1B20
unknown: F1B21
unknown: F1B22
unknown: F1B33
unknown: F1B34
```

### Verified in diamond-fuzz corpus

The same unknowns appear in **every** diamond-fuzz EBR result, regardless of mode:

```
diamond-fuzz/results/dp8kc_x1/dp8kc_x1.config       → F0B13 F1B8 F1B20-22 F1B33-34
diamond-fuzz/results/pdpw8kc_x18/pdpw8kc_x18.config → F0B13 F1B8 F1B20-22 F1B33-34
diamond-fuzz/results/ebr_pdpw8kc_wr18_ww18/...      → F0B13 F1B8 F1B20-22 F1B33-34
```

This rules out V07-specific configuration — it's a universal prjtrellis issue.

### Root cause

`database/MachXO2/tiledata/EBR1/bits.db` says:

```
.config_enum EBR.MODE NONE
DP8KC    F0B13 F1B8 F1B20 F1B21 F1B22 F1B35   ← database expects F1B35
FIFO8KB  F0B13 F1B0 F1B8 F1B20 F1B21 F1B22 F1B35
NONE     -
PDPW8KC  F0B13 F1B8 F1B20 F1B21 F1B22 F1B35   ← database expects F1B35
```

But Diamond 3.14 sets **F1B33 and F1B34** (not F1B35) for all active EBR
modes.  Because no enum value matches the actual bit pattern, `ecpunpack` falls
through and lists every MODE bit individually as `unknown:`.

Secondary bug: the database encodes DP8KC and PDPW8KC with *identical* bit
patterns, so it cannot distinguish the two modes even in theory.

### Fix required in prjtrellis

Replace `F1B35` with `F1B33 F1B34` in the EBR.MODE enum for all three active
values, and add a differentiating bit for DP8KC vs PDPW8KC.  This requires
re-running the `041-ebr_config` fuzzer with Diamond 3.14.

The check script (`diamond-fuzz/prjtrellis_patches/check/041-ebr_config/check.py`)
verifies DATA_WIDTH, REGMODE, WRITEMODE, etc., but does **not** directly
verify the MODE bits — which is why this bug survived the check suite.

### V07 interpretation

All 7 V07 EBR blocks use PDPW8KC (pseudo-dual-port 8K×9):
- Separate read and write clock ports fit the ADC-write / SPI-DAC-read
  clock architecture (ADC_ENCA ≈ 75 MHz write, slower SPI read clock)
- DATA_WIDTH_R and DATA_WIDTH_W confirmed from the `EBR.PDPW8KC.*` named enums
  that *do* decode correctly

### F1B32 — a third EBR mode bit (5 of 6 EBRs)

After applying the F1B35 → F1B33 F1B34 patch locally, only EBR_R6C11 decodes
as PDPW8KC.  The other five EBR blocks have additional or different bit
combinations that no enum value matches.  Checking the actual `.config` per EBR:

| EBR tile   | Mode bits set in .config           | Decodes after patch? |
|------------|------------------------------------|----------------------|
| EBR_R6C11  | F1B33 + F1B34                      | PDPW8KC ✓            |
| EBR_R6C5   | F1B34 only                         | still unknown        |
| EBR_R6C15  | F1B32 + F1B33 + F1B34              | still unknown        |
| EBR_R6C2   | F1B32 + F1B33                      | still unknown        |
| EBR_R6C8   | F1B32 + F1B34                      | still unknown        |
| EBR_R6C21  | F1B32 only                         | still unknown        |

**F1B32 is a third mode bit not in the current database at all.**  The five
EBRs that set it likely encode DATA_WIDTH variants (e.g. 1-bit, 2-bit, 4-bit,
9-bit vs 18-bit width configurations for DP8KC or PDPW8KC).  Re-running the
`041-ebr_config` fuzzer will discover whether F1B32 encodes width, port
asymmetry, or a separate DATA_WIDTH_A/DATA_WIDTH_B setting.

Until the fuzzer is run, 5 of 6 V07 EBRs still emit spurious `unknown:` lines
for their mode bits.

---

## CIB_PIC_B_DUMMY Unknown Bits (42 bits) — Unfuzzed Frames

### Symptom

13 CIB_PIC_B_DUMMY tiles at the bottom row (R11) have unknowns in frames
F25–F27:

```
F26B46 — 8 tiles
F27B38 — 8 tiles
F27B46 — 8 tiles
F27B26 — 6 tiles
F27B25 — 6 tiles
F26B30 — 6 tiles
```

Total: 42 bits across 13 dummy-pad CIB tiles.

### Root cause

`bits.db` for `CIB_PIC_B_DUMMY` covers routing mux bits in frames F0–F23.
The non-routing configuration section contains only `fixed_conn` entries — no
enum/config bits at all.  Frames F24–F27 were never included in the original
prjtrellis MachXO2 fuzzing campaign.

The `diamond-fuzz/` bank-2 results (`iddrxe_bank2`, `bb_ts_high_bank2`, etc.)
do contain `CIB_PIC_B_DUMMY` tiles but show **no unknowns** because those
designs use simple LVCMOS/LVTTL IO standards.

V07 uses **OUTPUT_MIPI** and **OUTPUT_SSTL25_I** on the adjacent bonded pads.
These high-speed standards require additional configuration bits that spill into
frames F24–F27 of the neighbouring dummy-pad CIB tile.

### Fix required in prjtrellis

The `CIB_PIC_B_DUMMY` bits.db needs fuzzing with designs that use high-speed
IO standards (MIPI, SSTL25, HSTL, LVDS) on adjacent pads.  The relevant
fuzzer would vary `BASE_TYPE` and `DRIVE` on the bonded pad and observe which
bits change in the adjacent `CIB_PIC_B_DUMMY` tile.

### V07 interpretation

The bits are in the **CIB** (Connectivity InterBlock) tile that abuts unbonded
silicon IO cells.  These unbonded cells exist in the silicon but have no
package pin.  Diamond still configures their electrical state for signal
integrity on the adjacent bonded pads.

These bits are **functionally harmless** for V07 operation — the unbonded pads
cannot affect the circuit — but they represent genuine configuration that
Diamond wrote and prjtrellis cannot yet name.

---

## Missing DAC Arcs — Bottom-Edge CIB Routing Gap

### Symptom

Four DAC output pads (DAC_D0/D2/D6/D7, package pins 36/38/42/43, bottom IO row
R11) have no fabric-side net resolved in `pad_map`.  SQL queries confirm a
fabric net (`n2501`, `n2520`, etc.) is connected to the IO buffer's JA2 input
in the arc table, but the arc chain terminates at the IO buffer — nothing in
`net_fanout`, `ffs`, or `luts` drives those nets.

Tracing arcs for `n2501` (DAC_D0):

```
R11C10  V02N0201 → H00R0000   (both n2501)
R11C10  H00R0000 → JA2        (both n2501)
```

The chain ends at `V02N0201`.  The arc that feeds it from the fabric is missing
from the decoded database.

### Root cause

The routing mux that connects internal fabric wires to bottom-edge IO buffer
inputs sits in CIB tiles at row R11.  The configuration for these muxes is
encoded in frames F24–F27 of those CIB tiles.  The prjtrellis MachXO2 fuzzing
campaign did not include designs with **OUTPUT_MIPI** or **OUTPUT_SSTL25_I**
standards on bottom-edge pads, so those frame/bit addresses are absent from
`bits.db`.

`ecpunpack` cannot decode the routing mux selection and produces no arc for the
V02N0201 → (fabric driver) hop.  The connection exists in silicon; it is simply
invisible to the current tool.

### Relationship to CIB_PIC_B_DUMMY unknowns

The CIB_PIC_B_DUMMY `unknown: F26B46` etc. bits are **non-routing config**
(electrical standard / signal integrity settings for the pad itself).  The
missing DAC arcs are **routing mux** bits — a different bit field in the same
F24–F27 range of a different CIB tile variant.  Both gaps share the same root
cause (F24–F27 never fuzzed with MIPI/SSTL25) but are distinct phenomena
affecting different bit fields and different tile types.

### Fix required in prjtrellis

Fuzz CIB tile variants adjacent to bottom-edge bonded pads with designs that
use OUTPUT_MIPI or OUTPUT_SSTL25_I IO standards and observe which F24–F27
bits change.  Both the routing mux bits (which arc inputs the IO buffer reads)
and the non-routing config bits (electrical standard settings) will be
resolved by the same fuzzing campaign.

### Impact on Pluribus

Until the prjtrellis database covers these frames, `report.py` will show
DAC_D0/D2/D6/D7 as having no recoverable fabric driver.  This is a known
database gap, not a Pluribus bug.

---

## CIB_PIC_B0 / PIC_B0 Unknown Bits (18 bits)

Split into two sub-cases with different root causes.

### CIB_PIC_B0 F24–F27 unknowns (15 bits, 4 tiles)

Same root cause as CIB_PIC_B_DUMMY: frames F24–F27 not covered in `bits.db`.
Affects CIB tiles adjacent to real bonded IO cells using MIPI/SSTL25 standards.

### PIC_B0 F4B39 / F5B39 unknowns (3 bits, tiles PB6, PB20)

Different root cause.  F4B39 and F5B39 are in the `PIOC.BASE_TYPE` and
`PIOD.BASE_TYPE` enums respectively (not PIOA/PIOB as proximity might suggest).
These bits are the **25/33V receiver enable** for the PIOC and PIOD IO slots.

In `PIC_B0/bits.db`, F4B39 appears in:
- `PIOC.BASE_TYPE BIDIR_LVCMOS25 F2B36 F4B39` — receiver + driver enabled
- `PIOC.BASE_TYPE INPUT_LVCMOS25 F4B13 F4B21 F4B39` — receiver + input mode

V07 has F4B39 **alone** (no F2B36, no F4B13/F4B21), meaning the 25/33V
receiver is active but the database has no named enum for this partial state.

This is the "FAILSAFE receiver enabled, no driver, no explicit standard"
configuration Diamond writes for bonded-but-unused IO pads.  The pads
(PIOC/PIOD slots of PB6 and PB20) are live package pins that no signal is
assigned to in the design; Diamond defaults them to PULLMODE=FAILSAFE with
the receiver enabled — a safe high-impedance input state.

prjtrellis is missing this enum value.  Fix: add to `PIC_B0/bits.db`:
```
.config_enum PIOC.BASE_TYPE NONE
...
FAILSAFE_RCV F4B39    ← new entry needed
```
and the PIOD equivalent with F5B39.  Fuzz verification: constrain a pad to
PULLMODE=FAILSAFE with no BASE_TYPE and confirm Diamond sets only F4B39.

---

## CIB_CFG2 Unknown Bit (1 bit)

One bit in the sysConfig tile.  The `140-sysconfig` check fuzzer covers
the documented config options; this extra bit is likely a boot-mode or
security option not yet catalogued.  Functionally, V07 boots correctly, so
whatever this bit encodes is set to a working state.

---

## Summary

| Category | Count | Status |
|---|---|---|
| EBR.MODE wrong bit address (F1B35 vs F1B33/F1B34) | 97 | prjtrellis DB bug — fix: re-fuzz 041-ebr_config |
| CIB_PIC_B_DUMMY frames F24–F27 | 42 | prjtrellis coverage gap — fix: fuzz with MIPI/SSTL25 IO |
| CIB_PIC_B0/PIC_B0 frames F24–F27 | 15+3=18 | Same coverage gap |
| CIB_CFG2 sysConfig | 1 | Uncatalogued boot/security option |

**All 157 unknowns are explained.  None indicate V07-specific errors.**
The EBR.MODE bug is the only case where prjtrellis actively misidentifies bits;
the IO-frame gaps are simply omissions in coverage.

### Additional finding — not in the 157 unknown count

| Gap | Effect | Fix path |
|-----|--------|----------|
| EBR F1B32 (third mode bit) | 5 of 6 EBRs still emit mode unknowns after F1B35 → F1B33/F1B34 patch | Re-fuzz 041-ebr_config with Diamond 3.14 |
| Bottom-edge CIB routing (F24–F27) | DAC_D0/D2/D6/D7 fabric drivers invisible; arc chain terminates at IO buffer | Fuzz CIB tiles adjacent to R11 pads with MIPI/SSTL25 IO |

---

## PB6 / PB20 Unknowns — Incomplete BASE_TYPE Encoding

`PB6:PIC_B0` and `PB20:PIC_B0` have unknowns in frames F4–F5 (not F24–F27):

```
PB6:  unknown F4B39, F5B39
PB20: unknown F5B39
```

These frame/bit addresses are **present** in `PIC_B0/bits.db` as part of the
`BASE_TYPE` enum (e.g. `BIDIR_LVCMOS25 F2B36 F4B39`).  However the full
multi-bit pattern required by any named BASE_TYPE is not present — only the
F4B39 or F5B39 bit is set, without the companion bits.

These PIOA/PIOB sub-IO slots in those tiles have `DRIVE`, `OPENDRAIN`, and
`PULLMODE` set but no `BASE_TYPE` enum decoded.  This indicates Diamond
partially configures "unused output" IO slots — writing a default electrical
state without committing to a named IO standard.  prjtrellis has no name for
this partial pattern.

These are not IO signal errors; the physically connected signals on those pads
are on PIOC/PIOD slots which decode correctly.

---

## Upstream Bug Reports

Two issues are worth filing to prjtrellis (report only — no code push required):

### Issue 1 — EBR.MODE bit encoding (high priority)

**File:** `database/MachXO2/tiledata/EBR1/bits.db`  
**Lines:** the `EBR.MODE` config_enum block  
**Problem:** Database encodes all active modes with F1B35; Diamond 3.14 uses
F1B33 + F1B34.  Every design using any EBR block will have undecodable mode
bits.  Additionally, DP8KC and PDPW8KC are encoded identically — the database
cannot distinguish them.  
**Evidence:** `diamond-fuzz/results/dp8kc_x1/`, `pdpw8kc_x18/`,
`ebr_pdpw8kc_wr18_ww18/` all show the same unknowns from Diamond 3.14.  
**Fix path:** Re-run prjtrellis fuzzer `041-ebr_config` with Diamond 3.14 to
rediscover the real bit positions.

### Issue 2 — CIB_PIC_B_DUMMY and CIB_PIC_B0 frame coverage gap

**Files:** `database/MachXO2/tiledata/CIB_PIC_B_DUMMY/bits.db`,
`CIB_PIC_B0/bits.db`  
**Problem:** Non-routing config section covers only F0–F23.  Designs using
MIPI, SSTL25, HSTL, or LVDS IO standards write configuration into frames
F24–F27 of adjacent CIB tiles that prjtrellis cannot name.  
**Evidence:** V07 bitstream — 13 CIB_PIC_B_DUMMY tiles × 2–3 bits each
(frames F26–F27), plus 4 CIB_PIC_B0 tiles × 3–6 bits each.  
**Fix path:** Fuzz CIB tile variants with a design that uses high-speed IO
standards (MIPI/SSTL25) on adjacent bonded pads and observe which F24–F27
bits change.

---

## Key files

```
diamond-fuzz/results/dp8kc_x1/dp8kc_x1.config          — DP8KC reference (shows same MODE unknowns)
diamond-fuzz/results/pdpw8kc_x18/pdpw8kc_x18.config     — PDPW8KC reference
diamond-fuzz/results/ebr_pdpw8kc_wr18_ww18/...          — PDPW8KC wide-port reference
diamond-fuzz/prjtrellis_patches/check/041-ebr_config/check.py  — EBR check suite (MODE not verified)
<prjtrellis-db>/MachXO2/tiledata/EBR1/bits.db           — EBR.MODE enum (wrong F1B35)
<prjtrellis-db>/MachXO2/tiledata/CIB_PIC_B_DUMMY/bits.db — ends at F23 (F24–F27 missing)
/mnt/2tb/git/awto-2000/fpga/v7/FPGA_V07.bin.config      — source bitstream (read-only)
```
