# Cyclone IV corpus trim (#157 decision 5)

- Moved (not deleted) to the machine wastebasket slot `cycloneiv-corpus-trim-20261029-153324`; restore = move back under `corpus/cycloneiv/`.
- Evidence rows and claims untouched. gx150.db names `gxnb*`/`gxll*` keep `source_ref` to the exported forced-lab JSONs.
- Checks: grep scripts/tests/docs/lifters; DB evidence/scopes/corpus_members; declare_gate. None of tests, gate or corpus_members read the moved dirs.
- After move: `pytest tests` 369 passed; `scripts/recovery_status.py` rc 0.

| prefix | dirs | size | action | referenced? |
|---|---|---|---|---|
| gxnb37x60d1_* | 512 | 2.91 GB | moved | only `cycloneiv_forced.py` compare_nb regen path (rebuild reproduces) |
| gxnb58x30d1_* | 512 | 2.91 GB | moved | same |
| gxnb6x10d2_* | 512 | 2.91 GB | moved | same |
| gxll58x30_* | 480 | 0.8 MB | moved | evidence names only |
| gxll37x60_* | 480 | 0.8 MB | moved | evidence names only |
| ho2_* | 32 | 0.10 GB | moved | no references |
| gxnb10x10d1_*, gxnb100x75d1_* | 1024 | 5.8 GB | kept | requested keep; compare_nb baseline |
| gxll_*, gxll100x75_* | 960 | ~0 | kept | requested keep; profile_stages uses gxll_00_02 |
| gx150_sp_* | 300 | 3.44 GB | kept | default `--designs` of learner_baseline, asm_decode, io_bits, image_pass, verify_all |

- Freed: 8.93 GB.
