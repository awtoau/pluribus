# Re-check of boards/dji-m2001/{pins,nets}.tsv against current docs/lift (2026-10-31)

Row-by-row disposition from the pass that produced the tracked `pins.tsv` (90 rows) and `nets.tsv`
(17 rows) in this directory. Not every row reached a confident answer -- see each row's own
confidence/tag columns; some are intentionally left "unverifiable, inferred only."

## Method

1. Checked every row's claim against `docs/lightbridge-fpga.md` (authoritative, current findings doc — doc wins on conflict).
2. Where the doc doesn't cover a pad directly, ran `scripts/cycloneiv_clean_pad_roles.py --nl tmp/image_sim_dji_push/nl.pkl
   --tag image --pkg F672` (current lift, built after today's F-021 and multi-LE-tail-strip fixes, mtime 15:00 > the
   14:50 cutoff) and pulled per-pad `(clock, direct_ff, cone-size)` signatures directly via a small inline script, not
   just the summary group buckets the tool prints.

## Category counts (pins.tsv, 90 rows)

- **CONFIRMED** (matches current doc + structural signature): 46 rows — the 12-pad AD9363 TX bus, the 8-pad FX3 DQ
  bus, the 13-pad AD9363 RX-bus-proper (see below), AF3, B14, AA7/AA8/AA9/AB11 (relabeled).
- **STALE, FIXED FROM THE DOC'S OWN STATED FACTS**: 4 rows + 1 relabel + 1 relabel = AA7/AA8/AA9/AB11 (the conflict
  the coordinator spot-checked) and AF3/B14 (label-only corrections, not wrong-chip errors).
- **STALE, DOWNGRADED TO UNVERIFIABLE** (draft claimed a specific bus membership/grouping the structural recheck does
  NOT support): 8 rows (AA26, AB23, AC24, AC25, AC26, AD25, AD26, AE26 — see "RX bus split" below) + AB8/AC8 (draft's
  claimed 3-pad SPI-relay grouping with AA7 is not structurally supported; downgraded, not asserted wrong).
- **UNVERIFIABLE, LEFT AS-IS** (no doc coverage, pad_roles.py signature inconclusive or not attempted — genuinely open,
  not forced to an answer): ~28 rows — all the `U`-confidence bank4/bank5 undecoded-source outputs, the two UART/GPIO
  guesses (AD13/AD5), the AD9363_CTL_0..5 group (P19/P20/R19/R20/R22/R25).
- **OUTLIER, FLAGGED NOT RESOLVED**: T19, M25/N25 (see below).

## nets.tsv (17 rows)

No row is structurally wrong. Two clock domains' FF counts drifted a small amount (23338→23084 on `clk_main`,
12950→12259 on `clk_pll_b`, 137→141 on `clk_core_a`) — expected and explained: F-021 touched ~5,228 LEs' ASDATA
resolution, which can reassign a handful of FFs' effective clock/role. This is a consequence of a known, already-
landed fix, not a new discrepancy. Two domains (`clk_pll_c`, `clk_ext_b14`) and `clk_core_b`'s total matched exactly.

## Bus-uniformity findings (the signal most useful for the eventual bus tracer)

**AD9363 TX bus (12 pads): fully uniform, zero outliers.** Identical `(out_clk0, out_cone[:3])` signature
`[4, 31, 67]` across all 12 — this is as clean as a bus signature gets. No correction needed.

**FX3 DQ bus (8 pads): fully uniform, zero outliers.** Identical bidir signature (`out_cone=[18,31,20]`,
`in_cone=[1,1]`) across all 8. Confirms the draft's own V-tag exactly.

**AD9363 "RX bus" (draft: 21 pads, one group) — SPLITS INTO THREE STRUCTURALLY DISTINCT GROUPS, not one bus:**
1. **13 pads structurally uniform** (`clk=u_clkbuf_out_0_46_30_0/pos`, `cone[:2]=[1,0]`, consumers 1-2): AA25, AB26,
   T24, T25, U25, U26, V26, W24, W25, W26, Y24, Y25 — this is the real, confirmed bus. (A `direct_ff` sub-variant
   splits 4 of these from the other 9, but cone shape and clock match across all 13 — treated as one bus, a minor
   explainable variant, not a second group.)
2. **8 pads with NO consumer at all** in the current lift (`clk=[]`, `consumers=0`, `cone=[0]`): AA26, AB23, AC24,
   AC25, AC26, AD25, AD26, AE26. The draft's own text called these "sink not decoded" (implying present-but-opaque);
   the structural fact is stronger — there is no sink, full stop, structurally identical to A5/AA22 which the draft
   *already* separately flagged as `nosink_in`. **This is the main finding of this pass**: 8 of 21 claimed RX-bus
   pads may not belong to the bus at all, or the bus's true width is 13 (not 21), or these 8 feed something this
   lift still doesn't model (a possibility, not a confirmed story — left open deliberately).
3. **2 clear outliers**, neither matching group 1 or group 2: **T19** (`cone[:3]=[8,8,38]`, much deeper fan-out —
   matches the draft's own "T19 → 146 FFs → AA7" note flagging it as different from its RX-bus peers) and **M25/N25**
   (the dedicated-clock-pad-used-as-data pair; N25's `cone[:3]=[1,1,3]` doesn't match either group, consistent with
   the draft's own separate treatment of these two).

This is exactly the "mostly uniform with outliers" signature a connectivity-based bus tracer should learn to use:
same clock + same enable + repeated per-bit cone shape = real member; a pad sharing the clock domain but breaking the
cone-shape/consumer pattern = does not belong, regardless of what a human guessed when first labeling it.

## Not resolved this pass (explicitly, per the "iterate, don't perfect" framing)

- Whether the 8 no-sink pads are mis-assigned-to-this-bus, genuinely unused, or feed something undecoded — open.
- AB8/AC8's real role, if any — downgraded from the draft's specific guess, not replaced with a better one.
- The ~28 fully-unverifiable rows (bank4/bank5 undecoded outputs, UART/GPIO guesses, AD9363_CTL group) — no new
  evidence this pass either way; left exactly as uncertain as the draft already said they were.
- PLL_2/PLL_8 parameter claims — not independently re-run this pass (no PLL-param recheck script was used).

## Files

- `tmp/dji_pins/board/pins_corrected.tsv` — corrected pins table, same column format as the original.
- `tmp/dji_pins/board/nets_corrected.tsv` — corrected nets table, same column format as the original.
- Both still local/uncommitted, per the original draft's own framing. Promotion to a tracked location is a separate,
  later step — not part of this pass.
