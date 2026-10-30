# Cyclone IV GX high-level corpus: known-source designs for the Verilog lifter (#165)

Generator `scripts/cycloneiv_hl_corpus.py` (seeded; part library + ground-truth manifest `src/hl_truth.json`), scorer `scripts/cycloneiv_hl_score.py`, test `tests/cycloneiv_clean/test_hl_corpus.py`, gate `scripts/cycloneiv_clean_gate.py --tier hl`.
Designs `corpus/cycloneiv/hl_<kind>_<seed>` (src + design.toml tracked, outputs untracked), 153 built, family `hl` in `reference/corpus_keep.tsv` (all kept) and `reference/corpus_catalog.tsv`. Device EP4CGX150DF31C7.

## IO style (feasibility, 2026-10-30, Quartus 25.1, counter / FSM / FIFO(M9K) x 3 forms)
- A: all data ports `VIRTUAL_PIN`, clock a real pad. A': clock virtual too. B: one clock pad + one output pad (registered XOR-reduction of all state, stimulus from on-chip XNOR LFSR banks).
- Quartus accepts a virtual clock (critical warning 15725 "ripple clock"); build completes, fit reports 0 pads; the clock still enters through a global clock buffer.
- All 9 builds succeed. A / A': 0 IO sites in the decode, so no observable boundary: RTL-vs-flat equivalence has 0 outputs ("none"). Virtual inputs leave their LUT/FF pins unconnected (no source in the bitstream); the inputs' effect is not recoverable. FSM A: 0 FSMs recovered (4 of 6 FFs kept), counter A: logic present but sources absent.
- B: 1 output site used, all state FFs retained (counter 49 = 49 expected, FSM 37, FIFO 58 after M9K output register), equivalence runs (200 cycles, pass on all three).
- Decision: style B (min). Cost: the stimulus LFSR banks (role `stimulus`) and XOR tree (role `observer`) are extra constructs in every design; they are in the manifest.

## Manifest
- `constructs`: kind, role (dut / stimulus / observer), parameters (width, taps, op, states, encoding, depth, signed, ...). `expected`: counts per lifter report key (`reg_bits`, `counters`, `adders`, `subtractors`, `comparators`, `fsms`, `shift_registers`, `muxes`, `m9k`, `mac`). `fit`: Quartus fit.rpt figures after the build.
- Registers absorbed into M9K / multipliers are not counted in `reg_bits`. Equality compares, decoders, priority encoders, CRC, pipelines have no dedicated lifter key (reg_bits only).
- Kinds (designs): counter 12, adder 10, cmp 8, lfsr 10, shiftreg 6, crc 8, fsm 14, regs 8, mux 6, decoder 3, prienc 3, rom 6, ram 8, fifo 8, mac 8, pipe 5, dpath (composites) 10, mix (4-12 random parts) 14, bigregs 2 (600+ registers), bigrom 2 (60-64 M9K unique MIF), bigmac 1 (120 18x18), bigadd 1 (24 adders/subtractors + 12 comparators, 32 bit).

## Score (run `hl_score_v1`, 153 designs, 200 cycles, `--vo`; counts; matched / missing / extra / wrong)
| key | matched | missing | extra | wrong | headline |
|---|---|---|---|---|---|
| reg_bits | 25685 | 794 | 183 | 0 | 96.3% |
| counters | 0 | 142 | 0 | 0 | 0.0% |
| adders | 36 | 43 | 27 | 3 | 33.0% |
| subtractors | 1 | 14 | 0 | 0 | 6.7% |
| comparators | 0 | 38 | 0 | 0 | 0.0% |
| fsms | 10 | 32 | 0 | 0 | 23.8% |
| shift_registers | 189 | 334 | 71 | 0 | 31.8% |
| muxes | 15 | 1 | 537 | 0 | 2.7% |
| m9k | 176 | 14 | 3 | 0 | 91.2% |
| mac | 162 | 3 | 0 | 0 | 98.2% |
| all keys | 26274 | 1415 | 821 | 3 | 92.1% |
- counters + adders + subtractors pooled (a counter may lift as ADDC): 67 matched, 172 missing, 0 extra.
- Equivalence RTL vs flat emit: 144 pass, 9 fail (7 `regs` designs with an async-clear bundle; `adder_4`, `bigadd_1`: all mismatches have x in the flat model). Flat vs post-fit .vo: 103 pass, 50 fail; RTL vs .vo: 98 pass, 55 fail. All 50 baseline failures are M9K / MAC / wide-adder designs (kinds mix, fifo, mac, rom, ram, dpath, bigrom, adder, bigadd, bigmac, pipe): inherited from the flat emit, not the lift. rtl-vs-vo differs from flat-vs-vo in 9 designs (7 pass->fail, 2 fail->pass).
- Gate tier `hl` (no DB record): pips 144047 / 144226 (99.88%), nets 38919 / 38956 (99.91%), lut_init 36792 / 36792, register_clock 22790 / 26222 matched (missing 3044, extra 388; 3036 FFs with no clock line claim), pins 306 / 306. Emit FF count differs from fit.rpt registers in 6 designs.

## Failing scopes (what the lifter should learn)
- Counters with enable / load / clear, up/down, step != 1, and free-running address counters: not recognised as CNT_UP/CNT_DOWN (0 of 142); the pooled arithmetic class shows part are recovered as adders.
- Magnitude comparators fed by two registers: 0 of 38 (only chain-carry-only form is a rule).
- Subtractors 1 of 15; adders with carry-in or 3 operands: partial; accumulator forms lift as extra adders (27).
- FSMs: 0 of 14 in the `fsm` designs (3-24 states, binary / gray / one-hot, every state tests 1-2 distinct stimulus FFs, so far more than 5 other inputs); 10 recovered in dpath / mix, all 2-3 bit state with <= 3 inputs.
- LFSR / shift: SHIFT needs a >= 3 FF single-reader path; LFSR taps split a bank into several paths (extra 71) and feedback is not modelled (334 missing).
- Muxes: 537 extra MUX<2^k> from cone splitting of non-mux logic (shifters, stimulus XOR pairs).
- M9K: 14 missing in bigrom (64 blocks) and rom; MAC: 3 missing. Async-clear register bundles: RTL differs from flat (7 designs).
- No lifter key exists for: CRC XOR networks, pipelines, decoders, priority encoders, equality compares.

Results also in issue #165 (counts only). Rebuild: `scripts/cycloneiv_hl_corpus.py --generate` then `--build` (5 jobs, 153 designs in 13 min wall, 2026-10-30).
