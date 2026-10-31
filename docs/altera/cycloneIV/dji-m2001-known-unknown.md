# DJI m2001 (EP4CGX150): known vs unknown partition of the lifted netlist

Every LUT / FF / M9K / MAC / pad of the current lift is assigned to one named block or to an UNKNOWN component.
Seeds: `boards/dji-m2001/blocks.json` (durable, extend by hand). Tool: `scripts/cycloneiv_clean_partition.py`.
Evidence per block: `docs/lightbridge-fpga.md` section or awtoau/pluribus #177 comment id. Tags: **V** cell-traced, **I** inferred role, **S** structure known / function unknown, **U** unknown.

## Regenerate

```
python3.15t scripts/cycloneiv_clean_partition.py --nl tmp/image_sim_dji_push/nl.pkl --blocks boards/dji-m2001/blocks.json \
    [--build-seeds] --rtl tmp/cycloneiv_clean/rtl_partitioned.v --flat tmp/cycloneiv_clean/rtl_flat_partitioned.v --lint
```
- `--build-seeds` rewrites `blocks.json` from the trace outputs (`tmp/dji_spi/image_fork.json`, AF3 cone, `tmp/cycloneiv_clean/duml_entry_trace.json`, `pins.tsv`); omit it to use the committed seeds.
- Outputs: `tmp/cycloneiv_clean/partition.json` (cell lists per block), `partition.md` (table below), `rtl_partitioned.v` (structured RTL, statements grouped under `// ==== BLOCK: <name> (conf) ====` headers, declarations first), `rtl_flat_partitioned.v` (same for the flat emit), `partition_rtl.json` (mapping stats + lint).
- Growth is bounded (`--grow 2`): a LUT joins a block only when every consumer is in it, or its LAB is mostly that block and it touches it; an FF only when D-source and all consumers are inside. Two blocks claiming a cell in one round = contested, left unknown (0 this run). Seed overlaps: first block wins, listed in `partition.json` (8 this run: regfile FFs also reached by engine / comparator / record-reader seeds).

## Coverage (lift `tmp/image_sim_dji_push/nl.pkl`, 2026-11-01)

| class | LUT | FF | M9K | MAC | pads |
|---|---|---|---|---|---|
| V verified | 4960 (5.6%) | 3529 (9.8%) | 73 (13.5%) | 1 (1.1%) | 66 (77.6%) |
| I inferred | 387 (0.4%) | 58 (0.2%) | 8 (1.5%) | 4 (4.6%) | 0 (0.0%) |
| S structure known, function unknown | 115 (0.1%) | 9 (0.0%) | 13 (2.4%) | 0 (0.0%) | 0 (0.0%) |
| U unknown | 83820 (93.9%) | 32277 (90.0%) | 448 (82.7%) | 82 (94.3%) | 19 (22.4%) |
| known (V+I) | 5347 (6.0%) | 3587 (10.0%) | 81 (14.9%) | 5 (5.7%) | 66 (77.6%) |
| total | 89282 | 35873 | 542 | 87 | 85 |

## Known blocks

| block | conf | LUT | FF | M9K | MAC | pads | evidence |
|---|---|---|---|---|---|---|---|
| clock_infra | V | 0 | 0 | 0 | 0 | 1 | PLL_2/PLL_8 + 18 undecoded clock nets (not cells); `nets.tsv`, s10 |
| spi_regfile | V | 3407 | 2995 | 0 | 0 | 3 | s6; `tmp/dji_spi/image_fork.json` (208 regs x 2 copies, shift chain, address reg, read-back; AB11/AA8/AA9) |
| radio_spi_engine | V | 78 | 43 | 0 | 0 | 5 | s5; a2d81aa68; #177 6543374632 (mode mux LAB (38,83), counters (56,85)/(57,87)/(58,87); P19/P20/R19/T19/AA7) |
| af3_engine | V | 894 | 218 | 2 | 0 | 1 | s8/s11a; `cycloneiv_clean_af3_engine.py cone()` (B14-clock FF domain, ROM 7_85/7_86, AF3) |
| fx3_gpif | V | 50 | 21 | 0 | 0 | 18 | s9; #177 6543746246 (control LAB (21,53), DQ drivers/OE, DQ capture FFs) |
| video_buffer | V | 29 | 3 | 65 | 0 | 0 | #177 6543928814 (8192x1 tiles read by the FX3 DQ drivers; we LUTs (19,45)) |
| video_duml_demux | V | 104 | 41 | 0 | 0 | 0 | #177 6543928814 (LABs (11,45)/(12,47), field reg (17,45), byte reg (13,25)) |
| duml_uart_tx_ac11 | V | 60 | 47 | 2 | 0 | 1 | #177 6543928814 (FIFO (7,32)+(7,33), divider (9,34) 391 clk/bit; stream identity I) |
| fx3_in_uart_tx_ac10 | V | 64 | 35 | 1 | 0 | 1 | #177 6543928814 (FIFO (7,46), divider (3,45); stream identity I) |
| rx_id_comparator | V | 151 | 68 | 0 | 1 | 0 | #177 6543928814 (regs 3..5 vs received ID, deserialiser (31,65), frame timer (37,88)/(37,89), MAC (43,84)) |
| frame_fsm | V | 84 | 27 | 0 | 0 | 2 | #177 6543928814 (FSM (38,86)/(39,86), 21-FF counter (32,89)/(32,90), ff_40_88_10/11; AC8/AB12 pad identity I) |
| tx_playback | V | 28 | 17 | 2 | 0 | 13 | #177 6543928814 (RAM (23,62)/(23,63), read counter; 12 TXD pads + R25) |
| uplink_record_readers | I | 387 | 58 | 8 | 4 | 0 | #177 6543746246 / 6543928814 (regs 0x44..0x7B field readers (66,78)/(67,83)/(87,75)/(69,80)/(67,81) -> MAC (74,78/79/85),(43,73), M9K (81,77)/(65,77)/(94,65-70)) |
| ad9363_rx_capture | V | 11 | 14 | 1 | 0 | 22 | `pins.tsv` AD9363 inputs + first capture stage (13-pad bus, M25, N25, 8 no-sink pads) |
| reg3_tables | S | 69 | 9 | 7 | 0 | 0 | #177 6543928814 (reg 3 indexes 2048x4 tiles (36,57..62),(36,65)) |
| tx_source_bank | S | 46 | 0 | 6 | 0 | 0 | #177 6543928814 (2048x4 bank (23,54/55/58/61),(36,54/55) feeding the TX pipeline) |
| pads_misc | U | 6 | 0 | 0 | 0 | 19 | `pins.tsv` U/I pads with no block (AD20-24, AE25, R20/R22, bank5 outs, AD5/AD13, U22, A5, AA22) |

## Unknown remainder (connected components within one clock domain)

| component | LUT | FF | M9K | MAC | note |
|---|---|---|---|---|---|
| unknown_clk_pll_b_1 | 48870 | 12259 | 119 | 0 | clk_pll_b (`u_clkbuf_out_0_46_31_0`), LAB bbox x 11-116, y 1-77 |
| unknown_clk_main_1 | 33954 | 19654 | 329 | 82 | clk_main (`u_clkbuf_out_0_46_30_0`), whole die |
| unknown_clk_main_2 | 377 | 37 | 0 | 0 | |
| unknown_clk_core_a_1 | 226 | 141 | 0 | 0 | clk_core_a |
| unknown_clk_core_b_1 | 122 | 82 | 0 | 0 | clk_core_b (B2 output domain) |
| 19 smaller | <70 each | | | | `partition.json` |

- The two big blobs are the OFDM baseband: RX demod/FEC/descrambler and TX modulator (I); every known block touches them at its boundary (RX bus capture -> pll_b blob -> demux; record readers -> main blob -> tx_source_bank -> tx_playback).
- They are one component each because the baseband is densely connected; splitting them needs functional anchors (next: FFT/Viterbi shapes, MAC chains per `cycloneiv-clean-mac-trace.md`), not more adjacency.

## RTL

- Structured RTL (`rtl.lift`) is emitted FLAT with block section headers, not as per-block modules: the lift's bundles/FSMs/chains are cross-LAB constructs and its port-capture machinery is pattern-module specific; cutting modules needs port derivation on the structured text (open).
- Statement -> block: by the LHS name via the lift's home map (`rtl.lift(..., homemap=)`), else by RHS majority; mapping stats in `partition_rtl.json`.
- Both annotated files lint with verilator (`--lint`): reordering statements is semantics-preserving; declarations stay first.
