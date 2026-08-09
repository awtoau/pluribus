# ECP5 open-flow build speed and variance

Measured on the Cynthion SoC **HYPERRAM_BIST** variant (~18k cells, `LFE5U-25F`
die marked 12F, CABGA256), commit `b71655b9`, on an i9-14900K (24C/31 usable
threads) with 62 GB RAM.  Every number below is dated; re-measure rather than
trust a stale one.

Harnesses: `scripts/fpga_build_bench.py` (stage timing + seed sweep),
`scripts/yosys_qor_bisect.py` (commit → LUT4 walk).

## Summary

| finding | status |
|---|---|
| `autoname` was 46% of synthesis; fixed upstream | **fixed** — yosys PR #6050 |
| 32 cores do not speed up yosys | **by design**, 6 of 201 passes threaded |
| GPU cannot help | inherent — pointer-chasing graph algorithms |
| Seeds decide pass/fail, not the mean | **use the sweep**, 8 seeds ≈ 1 build |
| `hr_fast_clk` ran on fabric routing with indeterminate skew | **fixed** in cynthion `592c02b` (#314) |
| Newer yosys regresses timing on this design | **open**, bisect running |

## Baseline (2026-08-09)

Suite `oss-cad-suite 20260522` — yosys 0.65+57, nextpnr 0.10-74, ecppack 1.4-79.

| stage | wall | CPU |
|---|---|---|
| yosys | 75 s | 106% |
| nextpnr | 47 s | 213% |
| ecppack | 0.33 s | 99% |
| **total** | **~122 s** | — |

Matches the ~130 s in the handover README (that figure was never captured — the
log had rotated — so this is the first recorded measurement).

## Why synthesis was slow: `autoname`

`top.rpt` named it outright:

```
Time spent: 46% 1x autoname (37 sec), 9% 47x opt_clean (7 sec), ...
Renamed 43183 objects in module top (3164 iterations).
```

- 3,164 iterations to rename 43,183 objects — ~13 objects per full scan.
- A degenerating fixpoint loop, not a parallelism problem.
- Upstream: issue **#5394**, fixed by PR **#6050** "autoname: rewrite"
  (merged 2026-07-19) — priority-queue traversal, *"No more fixpoint outer
  loop"*.  Our binary predated it by two months.

**It cannot be parallelised with the rest of synthesis.** `autoname` runs after
`map_cells`, mutates the names `write_json` serialises, and nextpnr consumes that
JSON.  Strict serial dependency.

Result: **75 s → 31 s** on the same input.

## Why 32 cores don't help

Yosys is C++20 (399 core files); ABC is C (1,440 `.c`); nextpnr is C++17.  No
interpreted layer — slowness is never a runtime issue here.

Thread scaling, measured on an idle box:

```
YOSYS_MAX_THREADS=1  → 33.91 s wall,  99% cpu
YOSYS_MAX_THREADS=31 → 34.38 s wall, 116% cpu
```

- Threading **is** compiled in (`have_threads` in the build feature list) and
  present in both old and new builds.
- But only **6 of 201 pass files** use the pool — all `opt_clean`/`opt_merge`.
- Cause is architectural: passes mutate one shared RTLIL netlist plus an interned
  `IdString` table.  Locking it costs more than it saves; sharding is a large
  upstream redesign, landing incrementally.
- Passes also form a dependency chain (`abc9` needs techmap's output).  You can
  parallelise *within* a pass, never *across* the sequence.

**GPU is out.** No GPU backend exists in either tool, and ABC/the SA placer are
pointer-chasing graph algorithms — the opposite of what a GPU wants.

### Profile after the autoname fix (nightly, 31 s total)

| pass | time |
|---|---|
| OPT_CLEAN | 7.79 s |
| OPT_EXPR | 6.34 s |
| ABC9_EXE | 5.51 s |
| TECHMAP | 5.49 s |
| OPT_DFF | 2.73 s |
| MEMORY_LIBMAP | 2.24 s |

Flat — no dominator left.  ABC is 4 sequential calls to an external
single-threaded C program (`passes/techmap/abc9_exe.cc`, temp-dir file I/O);
parallelising them would save ~3 s of a ~78 s build and is upstream's change to
make.

### Why caching / precompiling the CPU doesn't work

`synth_ecp5` runs `flatten` early — 480 modules in, 107 out — then optimises
across the wreckage, propagating constants *into* VexiiRiscv from the SoC.  A
separately-synthesised CPU would be a different, larger netlist.  Keeping
hierarchy (`-noflatten`, or blackboxing) costs area and timing, and this design
is already at **DP16KD 52/56 (92%)** and **EHXPLLL 2/2 (100%)**.

## Variance is the bigger prize

Identical netlist and flags; only `--seed` differs.  8 seeds, `clk` constrained
60 MHz, run concurrently (**~85 s wall for all 8** — this is what the core count
is actually good for):

| toolchain combination | median | min | max | FAIL |
|---|---|---|---|---|
| old yosys + old nextpnr | 64.70 | 60.55 | 69.35 | **0/8** |
| old yosys + NEW nextpnr | 65.00 | 62.44 | 68.62 | **0/8** |
| local yosys 0.67+153 + new | 62.83 | 58.63 | 66.45 | 2/8 |
| nightly yosys 0.68+40 + new | 59.95 | 56.45 | 62.59 | **5/8** |

A single build cannot distinguish a real improvement from placement luck — one
seed landed at **59.94 MHz**, missing the constraint by 0.06 MHz.

### The 60 MHz constraint sits in the middle of the distribution

`clk` is not near 60 MHz for any physical reason.  Two independent facts collide:
the ULPI/USB 60 MHz is externally fixed, and the CPU's own ceiling happens to land
at ~55-65 MHz.  `SYNC_MHZ = 60` (`top.py:591`) was set to the oscillator value, so
the constraint sits at the **midpoint of the achievable spread** (sd 2.0-3.1 MHz in
every sweep, all four toolchains) — which fails about half the time by construction.

The CPU and USB are already separate PLL outputs (`car.clk_sync` and
`clk_60MHz_0__io` are distinct nets in `top.lpf`), so nothing requires the CPU to
run at the USB rate.  Measured, 8 seeds each:

| case | min | median | max | FAIL | worst-case margin |
|---|---|---|---|---|---|
| old netlist @60 | 60.55 | 64.70 | 69.35 | 0/8 | +0.55 MHz |
| old netlist @50 | 59.52 | 63.27 | 69.31 | 0/8 | **+9.52 MHz** |
| nightly @60 | 56.45 | 59.95 | 62.59 | **5/8** | −3.55 MHz |
| nightly @50 | 57.96 | 59.64 | 60.79 | **0/8** | **+7.96 MHz** |

**Dropping the constraint to 50 MHz turns 5/8 failures into 0/8** on the very
netlist that fails today, with ~8 MHz of margin.  Relaxing it does not degrade
placement — the achieved median is within 1 MHz of the 60 MHz runs, because
nextpnr stops optimising once the constraint is met.

### Why the path is slow: span, not logic

Critical path, nightly build, `clk`:

| | time | share |
|---|---|---|
| logic (9 LUTs) | 1.76 ns | 10% |
| **routing (10 nets)** | **16.14 ns** | **90%** |
| total | 18.28 ns | → 54.70 MHz |

The path crosses the die four times: `(2,26) → (4,27) → (30,28) → (33,27) →
(56,7) → (26,34)`.  Two hops alone cost 10.84 ns.

Five of the nine cells belong to `PcPlugin_logic_harts_0_aggregator_target`
(`VexiiRiscv.v:11345`) — a single combinational AND-OR priority mux merging four
32-bit next-PC sources: trap vector, branch target, BTB prediction, and
sequential PC.  Those four are produced by four plugins the placer scatters
across the die, and they must converge in one cycle.  The BTB hop alone
(`(56,7) → (26,34)`, BRAM to mux) is 6.57 ns — 36% of the period.

LUT4 count does **not** predict Fmax here: 14,395 LUTs gave 64.70 MHz while
14,219 gave 59.95.  Size is not the problem; span is.

**CPU pipeline relaxations are already exhausted.**  `--relaxed-btb` (`jumpAt=2`)
and `--relaxed-branch` are both already on in `gateware/soc/cpu/cpu.py`;
`top.py:605` records that `--relaxed-btb` was added for this exact symptom at
57.55 MHz and is NOT the remaining limit.  Those flags add pipeline stages; they
do not shorten wires, and what remains is 90% wire.

**Floorplanning IS available — via `--pre-place`, not LPF.**  The ECP5 LPF parser
(`ecp5/lpf.cc:126`) accepts only `LOCATE COMP ... SITE`, but nextpnr's core has
full region support (`Region`, `CellInfo::region`, `testRegion`) and exposes
`createRectangularRegion` / `constrainCellToRegion` to Python.
`scripts/ecp5_floorplan_cpu.py` uses it; verified constraining 10,966 cells under
`cpu.cpu` (37% of the design).  Two traps, both recorded in that script:

- `addBelToRegion` on a region that was never created **segfaults**
  (`basectx.cc:129` dereferences a null `unique_ptr`) — use
  `createRectangularRegion`, which creates and fills.
- `constrainCellToRegion` walks `ctx.hierarchy`, which is **empty for a flattened
  netlist**: it warns "No cell matched" and silently does nothing.  Match on the
  name prefix over `ctx.cells` instead.

Region sizing is a real constraint: `x0..40/y0..30` fails placement after 93M
attempts.  Whether a workable region buys Fmax is **unmeasured** — judge it by
seed sweep, never a single build.

The RTL-level fix remains pipelining the aggregator so the far sources
(especially the BTB) register before the merge, splitting one 18 ns path into two.

```
python3.15t scripts/fpga_build_bench.py --pkg <dir> --seeds 8 --workers 8
```

Seeds are independent processes, so they scale across cores.  The free-threaded
`libtrellis` work (pybind11 2.13.6 + `mod_gil_not_used()`) is what lets one
python3.15t process drive them GIL-free; it does not speed up yosys or nextpnr
themselves, which are separate C++ binaries.

**Seeds are a nextpnr parameter, not a yosys one** — yosys is deterministic, so
there is nothing for it to sweep.  Synthesise once, fan seeds across P&R.

## Correctness: `hr_fast_clk` runs on fabric routing

nextpnr ≥ `0.10-122` (commit `8624a48b`, 2026-07-17) makes this an error;
older builds emitted `log_info("no route found, general routing will be used")`
— **not even a warning**.

```
ERROR: Unable to route edge clock source 'hr_fast_clk' to pin
       'hr_fast_clk$eclk7_0$buffer.ECLKI' using dedicated routing.
```

Geometry, from the routed logs and `device-db/ECP5/LFE5U-25F/tilegrid.json`:

- ECP5-25F has **exactly two PLL sites, both at Y49** — `EHXPLL_LL` (X2) and
  `EHXPLL_LR` (X70), top corners.
- Every HyperRAM ECLK consumer (`IOLOGIC`/`DQSBUFM`) sits at **X0/Y2–Y11**,
  bottom-left.
- ~38 tiles apart — beyond the bank's dedicated edge-clock spine.
- `ECLKBRIDGECS: 0/2` — the device-crossing bridge is unused.

**No PLL placement can reach it**; both toolchains chose X2/Y49 because there is
no alternative.  This is device geometry, not a tool bug, so Diamond would hit
the same wall — no vendor oracle needed.

**Impact:** every HYPERRAM_BIST bitstream built *before the fix* routed a 100 MHz
edge clock through general fabric with indeterminate skew, silently.  On a BIST
where skew is the measurement, those results are suspect.

**Fixed** in cynthion-workspace `592c02b` (#314) — `hyperram_clocks.py`
instantiates an `ECLKBRIDGECS` (`CLK0`=`clk_hr_fast`, `CLK1`/`SEL` tied off; a
die-crossing bridge, not a mux).  Confirmed available: `ECLKBRIDGECS0`/`1` are in
the 25F tilegrid, nextpnr supports the primitive (`ecp5/pack.cc:2488`), and
`docs/ecp5-gap-matrix.md` lists it as *covered*.

The handover package (`b71655b`, cut 2026-08-09 23:32) **predates the fix** —
its `top.il` contains zero `ECLKBRIDGECS` instances, which is why every
measurement in this document trips the error.  Re-cut the package to benchmark
the fixed design.

`--allow-fabric-eclk` only restores the old silence — it changes nothing
physically.  Comparison runs only.

## Open: newer yosys regresses timing

The cross-run **exonerates nextpnr**: the old netlist through the new placer is
unchanged (65.00 MHz, 0/8).  The regression tracks the *yosys netlist* and
worsens with newer yosys.

Cell counts on identical `top.il` — three yosys builds, three netlists:

| build | LUT4 | PFUMX | L6MUX21 | total |
|---|---|---|---|---|
| 0.65+57 (suite 20260522) | 14,395 | 2,944 | 909 | 29,007 |
| 0.67+153 (local) | 13,124 | 2,128 | 446 | 26,454 |
| 0.68+40 (suite 20260809) | 14,219 | 2,765 | 940 | 28,683 |

**Bisected to `2ee7dc5a1` "Implement constbit gather"** (nella, 2026-07-11, in
PR #6030), by binary search over the 341-commit range:

| commit | LUT4 | total cells |
|---|---|---|
| `c57f66cee` eqbits drop_all (parent) | 13,124 | 26,454 |
| **`2ee7dc5a1` Implement constbit gather** | **14,219** | **28,683** |

**+1,095 LUT4 (+8.3%) in one commit**, and it is the value every later commit
carries through to the 0.68+40 nightly.

The SAT effort limit added by the same PR is **NOT** the cause — disproved twice:

- `scratchpad -set opt_dff.sat_effort 0` (limit disabled) still gives 14,219;
- the commit's own `log_warning("solver effort budget ... exhausted")` never
  fires on this design.

Mechanism, from `passes/opt/opt_dff.cc`: the commit replaces immediate per-bit
const removal with a batched `ConstObligation` list checked later by SAT.  The
old path's `removed_sigbits` is left declared and never populated — which is why
the commit does not build on GCC 16 (`-Werror=unused-variable`, `opt_dff.cc:1021`).
That dead variable is a signal the rewrite dropped a result the old path applied.

**Before reporting upstream**, decide whether the QoR loss is a known trade for
bounded runtime — a SAT effort limit is usually added to stop pathological
solves.  The report is "this design regressed 8.3%", not "you broke it".

## Recommendation

**Do not upgrade the toolchain yet.**  The nightly buys ~43 s and costs a 5-in-8
timing failure rate against 0-in-8 today — a bad trade on a design at 92% BRAM.

Upgrade order once the regression is understood:

1. Fix the ECLK (`ECLKBRIDGECS`) — correctness, independent of toolchain.
2. Land the bisect result; report upstream if it is a genuine regression.
3. Move the whole suite together — `~/.local/bin` wrappers deliberately pin all
   three tools to one release (*"Keep the whole chain on one release"*).
   Upgrading yosys alone recreates the split those wrappers exist to prevent.
