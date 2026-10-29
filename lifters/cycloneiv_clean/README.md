# cycloneiv_clean

Cyclone IV GX (EP4CGX150) address engine rebuilt from vendor-derived facts only. Spec and plan: `docs/cycloneiv-clean-pipeline.md`. Process: `docs/recovery-process.md`.

## Modules

- `ddb.py`: raw loaders for `routing.ddb` fan-out (A1) and `asm.ddb` group bits (A2). Vendor x/y/index straight from the file, stored 31-bit addresses, flag bytes split out. No coordinate conversion.
- `plane.py`: geometry (A6) and the sof -> rbf closed form (A5). `address_to_plane` = raw address as sof bit index, then A5 (one function for routing and LUT cells); `CANDIDATES` keeps the rejected alternative for the oracles.
- `sofio.py`: sof / rbf file helpers around `quartus_cpf` (black box).
- `names.py`: RCF element names (A7).
- `tracer.py`: P2. rbf -> programmed edges (4 flag-rule variants), nets, LUT INIT cells, IO default-pattern classes; RCF ground-truth parse. CLI: `python3.15t -m lifters.cycloneiv_clean.tracer <rbf> <out.npz>`.
- Gate (P3): `scripts/cycloneiv_clean_gate.py`; baseline rows in `gate_runs` (`params.baseline`), log `tmp/logs/cycloneiv_clean_gate.log`, results `tmp/cycloneiv_clean/gate_*.json`.

## Accepted inputs

| # | Fact | Status here |
|---|---|---|
| A1 | routing graph from `routing.ddb` | `ddb.Routing` |
| A2 | asm group bits, group = destination position in the source fan-out | `ddb.Asm` |
| A3 | LAB LUT address law (asmdb), dy negated, columns ascending | oracle O1 (`test_o1_sign_variants`), not code |
| A4 | address -> image byte/bit | `plane.address_to_plane` |
| A5 | sof bit -> rbf closed form + mirrored blocks | `plane.sof_to_rbf`, oracle O3 |
| A6 | geometry | `plane` constants |
| A7 | name -> element, exact | `names`, oracle O4 |
| A8 | vendor x = fitter X | tile test in O2 |

Evidence per row: `docs/cycloneiv-clean-pipeline.md`.

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
- Entry roles: expected 1 iff `b0 == +1` (select) or `b1 == -1`; with exclusion, every other entry of the group is expected 0. Variants: `lit` / `lit_x` (literal rule, set-only / with exclusion), `sel` / `sel_x` (first entry always the select). Headline variant `lit_x`, fixed before the first GT comparison.
- Set-only over-fires: the three inputs sharing one select bit differ only in the second-level bits, so exclusion is required (rb_000..009, 2026-10-30: set-only extras 42,425, with exclusion 2,585).
- Not decided by the flags: 3-groups with `b0 = 0` on the select entry (no expected-1 entry under `lit`); 2-groups (R24 / C16 / wide muxes) whose second entry is set with `b0 = b1 = 0`.
- Not in asm.ddb groups at all: clock network edges (CLKBUF_OUT -> GLOBAL_CLK_H, GLOBAL_CLK_H -> GLOBAL_CLK_V, GLOBAL_CLK_V -> SCLK_TO_ROWCLK_BUF, LAB_CLK -> BLK_CLK_BUF: empty or flag-0 groups) and LOCAL_INTERCONNECT -> BLOCK_INPUT_MUX / LAB_CONTROL_MUX (not in the routing.ddb fan-out). So register-clock recovery is 0 until the clock mux settings are placed (not in asm.ddb routing).
- `.vo` LUT ports are the physical post-fit pins (no RCF route_port permutation applies); LUT cell index = 15 - l of the `.vo` lut_mask bit l.
