# Running a new bitstream through the pipeline

How to take a raw MachXO2 `.bin` you have never seen before and get it
fully loaded, reachability-analysed and comparable against the other
firmware versions.  Written after doing exactly this for the Hantek V2
bitstream (2026-07-14); the V2 paths below are a real worked example.

## TL;DR — one command per bitstream

```sh
python3 scripts/run_pipeline.py --label V02 \
    --bin "/mnt/2tb/git/awto-2000/fpga/v2/DS1302_impl1(8)_V02.bin" \
    --config tmp/v2/DS1302_V02.bin.config \
    --pins /mnt/2tb/git/awto-2000/fpga/aw2/aw2-pins.tsv
```

`run_pipeline.py` chains every stage with the right interpreter and env
vars, logs each stage to `tmp/pipeline_<label>_<stage>.log`, and stops
on the first failure.  Already-unpacked bitstream → drop `--bin`.
Already-loaded label → `--skip-load` (starts at reach).

## The stages it runs

| stage  | script                      | interpreter | notes |
|--------|-----------------------------|-------------|-------|
| unpack | `scripts/trellis_unpack.py` | python3     | `.bin` → named-cell `.config` via pytrellis; only with `--bin` |
| iomap  | `scripts/fpga_iomap.py`     | python3     | `.config` → `.config.iomap.tsv` sidecar (pin↔site map); only with `--bin` |
| load   | `load.py`                   | python3     | netlist recovery → DB rows for the label |
| reach  | `reach.py`                  | **python3.14t** | NoGIL BFS workers |
| reach2/3/4 | `reach{2,3,4}.py`       | python3     | derived analyses |
| report | `report.py`                 | python3     | summary tables |

Interpreter rules (CLAUDE.md): only `reach.py` needs python3.14t.
**Do not run `load.py` under python3.14t** — sqlalchemy forces the GIL
on and the subsequent pytrellis import segfaults.

## Environment

`run_pipeline.py` sets these itself; for manual runs export:

```
TRELLIS_BUILD=/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build
TRELLIS_DBROOT=/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database
```

Optional: `TRELLIS_DEVICE` (default `LCMXO2-1200`), `TRELLIS_PACKAGE`
for the iomap stage (default `TQFP100` via `run_pipeline.py --package`;
force it — best-fit package detection can drift to a bigger package).

## Safety rules

- `/mnt/2tb/git/awto-2000/` is a **live RE project — read-only**.
  Unpack outputs for new bitstreams go under pluribus `tmp/` (e.g.
  `tmp/v2/`), never next to the source `.bin`.
- `trellis_unpack.py` and `fpga_iomap.py` **refuse to overwrite** an
  existing output file.  This is deliberate: it makes clobbering the
  curated v4/v7 sidecars in awto-2000 impossible.  Delete the target
  first if regeneration is intended.
- The DB is per-label always-rebuild: loading label `V02` deletes and
  reinserts only `V02` rows.  Other labels are untouched.

## Verifying the result

1. **Load log** (`tmp/pipeline_<label>_load.log`): expect
   `45/45 pads resolved` and a low
   `Input-pad H06E gap: N pads with no net_fanout` count.
2. **FF D-input health**: `python3 scripts/ffd_stats.py <config>` —
   classifies every FF's D-net (LUT z / FF q / routed / const).
   A large `const` count means D recovery is broken (exit 1 if >10%).
   Reference point: V07 shows 409 LUT z / 345 FF q / 301 routed /
   35 const after the REG.SD polarity fix; before the fix it was
   1081/1090 const.
3. **Cross-bitstream comparison**:
   `python3 scripts/compare_pads.py V02 V4 V07` — per-pin direction and
   stitch status across labels.  All three Hantek firmwares configure
   the identical 45-pad set with identical directions; a pin that is
   `NOFAN` in one firmware but `+fan` in another is a lifter gap, not a
   dead pin (all 16 ADC data pins are live in every firmware).
4. **Unstitched-pad diagnostics**: `scripts/diag_fanout_gap.py` and
   `scripts/diag_unstitched.py` dump the DSU class of each stranded pad
   net and which bel pins it touches.

## Pitfalls learned the hard way

- **REG.SD polarity** (fixed in `machxo2_lift.py`): Trellis PLC
  bits.db defines SD value 1 as the zero-state (enum omitted from the
  textcfg) meaning DI (FF packed with its LUT); explicit `SD 0` means
  the FF's D comes from the fabric-routed **M** wire.  nextpnr
  machxo2 `pack.cc` is the ground truth for the forward direction.
- The DI wire never appears in config arcs (LUT F→DI is an internal
  fixed path), so SD=1 FFs must resolve their D straight to the paired
  LUT's F key.
- Diamond-built Hantek bitstreams are compressed; `trellis_unpack.py`
  wraps the raw config with an `FF 00` header before `read_bit` and
  relies on `deserialise_chip_forced` (compressed MachXO2 configs carry
  no IDCODE).
- Right-edge/top-edge pads route via `E{N}_H06E*` bus names whose
  canonical must anchor at the pad's own column (see `gkey()` in
  `machxo2_lift.py`); this was the earlier H06E gap fix.
