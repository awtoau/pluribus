# cycloneiv_clean

Cyclone IV GX (EP4CGX150) address engine rebuilt from vendor-derived facts only. Spec and plan: `docs/altera/cycloneIV/cycloneiv-clean-pipeline.md`. Process: `docs/recovery-process.md`.

## Modules

- `ddb.py`: raw loaders for `routing.ddb` fan-out (A1) and `asm.ddb` group bits (A2). Vendor x/y/index straight from the file, stored 31-bit addresses, flag bytes split out. No coordinate conversion.
- `plane.py`: geometry (A6) and the sof -> rbf closed form (A5). `address_to_plane` = raw address as sof bit index, then A5 (one function for routing and LUT cells); `CANDIDATES` keeps the rejected alternative for the oracles.
- `sofio.py`: sof / rbf file helpers around `quartus_cpf` (black box).
- `names.py`: RCF element names (A7).
- `reg_used.py`: register-used claim per LE (YGR output select x used LE_BUFFER; no dedicated bit exists). `bim.py`: LI -> BLOCK_INPUT_MUX of VIO / HIO pad pins (IO LABLINE groups; pin -> BIM from `blockiface.py`, the routing.ddb block interfaces) and BLOCK_INPUT_MUX -> CLKBUF_IN. `clkbuf.py`: clock buffer input select (block 73) and the fixed wires into CLKBUF_IN.
- `clocks.py`, `lab_control.py`, `muxsel.py`: clock network + register clock lines, LI -> LAB_CONTROL_MUX through the LAB_PIA_TO_INPUT input map, LAB mux selection decode (tests `test_decoders.py`).
- `tracer.py`: P2. rbf -> programmed edges (4 flag-rule variants), nets, LUT INIT cells, IO default-pattern classes; RCF ground-truth parse. CLI: `python3.15t -m lifters.cycloneiv_clean.tracer <rbf> <out.npz>`.
- Gate (P3): `scripts/cycloneiv_clean_gate.py`; baseline rows in `gate_runs` (`params.baseline`), log `tmp/logs/cycloneiv_clean_gate.log`, results `tmp/cycloneiv_clean/gate_*.json`.

## Accepted inputs

| # | Fact | Status here |
|---|---|---|
| A1 | routing graph from `routing.ddb` | `ddb.Routing` |
| A2 | asm group bits, group = destination position in the source fan-out | `ddb.Asm` |
| A3 | LAB LUT address law (asmdb), vendor formula as read (no sign flip, no constant), columns ascending | oracle O1 (`test_o1_sign_variants`), not code |
| A4 | address -> image byte/bit | `plane.address_to_plane` |
| A5 | sof bit -> rbf closed form + mirrored blocks | `plane.sof_to_rbf`, oracle O3 |
| A6 | geometry | `plane` constants |
| A7 | name -> element, exact | `names`, oracle O4 |
| A8 | vendor x = fitter X | tile test in O2 |

Evidence per row: `docs/altera/cycloneIV/cycloneiv-clean-pipeline.md`.

## Banned

AFX ladder, descending-x mirror, any (dx, df) / per-column / per-source table or fit, hop override, R4 column table, coord variants, relax rule, alias table, learned name/LI/phys maps, the specimen matcher, the old decode / trace modules. Enforced by `tests/test_banned_inputs.py` (identifier list there).

## Local data (untracked)

- `databases/cycloneiv/sof2rbf_mask.npz`: `python3.15t scripts/cycloneiv_sof2rbf_tables.py` (quartus_cpf, ~1 min).
- `tmp/ddb/stingray4_{rt_fanout.npz, asm_*.npy}`: `ddb.build()`.
- Oracle inputs under `vendor-analysis/` (asmdb decode), `corpus/cycloneiv/`, `tmp/hop_specimens/`. Tests skip when missing.

## Tests

`python3.15t -m pytest tests/cycloneiv_clean tests/test_banned_inputs.py -q -rsx`

- O1 LUT cells, O2 R4 arcs (strict + tile), O3 sof -> rbf vs `quartus_cpf`, O4 names.
- A candidate below 100 % shows as xfail with its count; every number is also in `tmp/logs/cycloneiv_clean_oracles.log`.

## Tracer facts (asm.ddb flags, measured on corpus rb_000..009; numbers live in gate_runs)

- Edge k of record r = group k; the last (groups - edges) groups are select-bit pseudo-groups (no edge). 14,862,095 real groups, 43,944,457 entries, all inside the die.
- Entry value (vendor, `DYGR_ROUTE_ASM_INFO_BODY::get_bits_from_source_to_dest` libddb_dygr 0x23bfe0): F0 (use-encoded) clear -> bit must be 1; F0 set -> bit must equal F1 (encoded-high); F0 / F1 = running sum of the i8 flag deltas, 1 bit. Exclusion bits of the destination not in the source's list must be 0. The earlier literal `b0 == +1 or b1 == -1` rule (`lit` / `sel` variants) was fitted to the corpus and is replaced (E-L1).
- Set-only over-fires: the three inputs sharing one select bit differ only in the second-level bits, so exclusion is required (rb_000..009, 2026-10-30: set-only extras 42,425, with exclusion 2,585).
- Clock network (`clocks.py`, #165): fan-in is a tree CLKBUF_OUT -> GLOBAL_CLK_H -> GLOBAL_CLK_V -> SCLK_TO_ROWCLK_BUF -> LAB_CLK (fan-in 30, the mux) -> BLK_CLK_BUF.
  - SCLK -> LAB_CLK: 12-entry groups, literal rule (already matched). H -> V: 1-entry group, flags 0 / 0, address in the asmdb DEFAULT-bit list (blank = 1): programmed iff the bit is CLEARED (all 120 such edges of the device).
  - Empty-group edges with fan-in 1 (145,283, all clock) are structural: they conduct when their destination is used; demand propagates up the unique parent from used SCLK and from the LAB-selected BLK_CLK_BUF.
  - LAB side: LAB_CLOCK_FAST_MUX gi 0 / gi 1 choose a LAB clock line j (first-level bit j = BLK_CLK_BUF index j); LE_CLOCK_SELECT bit 1 = gi 0, 0 = gi 1.
- LOCAL_INTERCONNECT has no fan-out in routing.ddb: LI -> LAB_CONTROL_MUX edges come from LAB_PIA_TO_INPUT gi k (`lab_control.py`, `muxsel.py`): control mux index k of the LAB, input number = LI index, aux = first-level bit, nxt = second-level state (none / bit0 / bit1).
- LE_USE_CARRY bit clear = C input from the carry chain (`sum_lutc_input = cin`); LE_LUT_FUNCTION has one group per LE, so arithmetic-mode LEs use the combinational cell relation.
- LI -> BLOCK_INPUT_MUX, VIO pad data pins (`bim.py`): MIO_LABLINE_TO_DATA gi 0 selects the LI; BIM = f(SUB_LOC): 0 -> (tile x+1, I0), 1 -> (x+1, I14), 2 -> (x, I5), 3 -> (x, I13). Labels from `scripts/cycloneiv_clean_bim_specimens.py` (6 builds, 24 pads, RCF names BIM, vo names pad). Open: HIO pads (block type 5, class-20 two-vector mux; aux/nxt absent), MIO_LABLINE_TO_DATA gi 1 and the control-pin muxes (BIM index unlabelled).
- LOCAL_LINE -> LAB_CONTROL_MUX: LAB_PIA_TO_INPUT map has 54 inputs = 38 LOCAL_INTERCONNECT + 16 LOCAL_LINE (input i >= 38 = LOCAL_LINE i - 38).
- Register used (`reg_used.py`): LE_REG_OUT_YGR gi 0 / 1 = output select (1 = LUT) of LE_BUFFER 2 le + 0 / 1, gi 2 = third path; unused path reads 0. Pair specimens (`scripts/cycloneiv_clean_reg_pairs.py`): adding an FF clears the YGR bit of each used path and nothing else in the LE except the clock-select polarity; FF-only LEs set LE_USE_SYNC_CLEAR + LE_USE_SYNC_LOAD; FF + LUT with both outputs used can leave every LE field unchanged (FF output on a path that was unused) - undecidable from LE fields alone, hence the used-buffer term.
- `.vo` LUT ports are the physical post-fit pins (no RCF route_port permutation applies); LUT cell index = 15 - l of the `.vo` lut_mask bit l.
