# cycloneiv_clean

Cyclone IV GX (EP4CGX150) address engine rebuilt from vendor-derived facts only. Spec and plan: `docs/cycloneiv-clean-pipeline.md`. Process: `docs/recovery-process.md`.

## Modules

- `ddb.py`: raw loaders for `routing.ddb` fan-out (A1) and `asm.ddb` group bits (A2). Vendor x/y/index straight from the file, stored 31-bit addresses, flag bytes split out. No coordinate conversion.
- `plane.py`: geometry (A6) and the sof -> rbf closed form (A5). `address_to_plane` is an OPEN INTERFACE (raises until #165 decides); `CANDIDATES` holds named implementations for the oracles.
- `sofio.py`: sof / rbf file helpers around `quartus_cpf` (black box).
- `names.py`: RCF element names (A7).

## Accepted inputs

| # | Fact | Status here |
|---|---|---|
| A1 | routing graph from `routing.ddb` | `ddb.Routing` |
| A2 | asm group bits, group = destination position in the source fan-out | `ddb.Asm` |
| A3 | LAB LUT address law (asmdb) | oracle O1, not code |
| A4 | address -> image byte/bit | candidate only |
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
