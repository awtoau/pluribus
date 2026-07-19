# FNIRSI 2D15P — Anlogic EG4S20 (eagle_s20) — pluribus board (#67)

Third pluribus FPGA family. The FNIRSI 2D15P handheld oscilloscope uses an
**Anlogic EG4S20BG256** (family `eg4`, device `eagle_s20`, JTAG idcode
`0x0a014c35`) — the same silicon as the Sipeed Lichee Tang.

## What lands in the DB

- **Device / package / idcode / sysconfig** — from the bitstream container,
  every CLB frame CRC-verified (CRC-16/BUYPASS).
- **Tile grid + per-tile CRAM occupancy** (`anlogic_tiles`) — the structural
  floorplan: 3317 tiles (2450 `plb` CLBs, 502 `pib` interconnect, 16
  `emb_slice` BRAM, 8 `dsp`, IO / clock / PLL), each with its CRAM address and
  how many of its bits the bitstream sets.
- **LUT4-init** (`luts`) — the truth table of every configured LUT, classified
  by `classify_lut` (BUF/INV/AND/OR/XOR/MUX/COMBO). Validated by construction:
  LUT non-zero-ness correlates exactly with tile occupancy (empty tiles decode
  to all-zero LUTs) and the inits are canonical functions.

**Not yet decoded (future work):** routing / connectivity. Anlogic muxes are
*binary-encoded* — a sink's source is chosen by the value of several
`TOP.Xn.MCnn` config bits evaluated through the per-bit boolean expr the fuse DB
carries (this is the mux decode prjtang leaves unfinished). So LUT input pins
and FF connectivity are left unconnected, `arcs` stays empty, and the anlogic
pipeline stops after `unpack + load` (no reach/report/verilog).

## Fuse DB recipe (license-free, no fuzzing)

Unlike prjtrellis (Diamond fuzzing) or apicula (fuzzing), the Anlogic fuse map
is already present — obfuscated — inside Tang Dynasty's own architecture DB, so
**no license and no fuzzing are needed**; the DB is simply *decoded*:

```
# 1. Obtain Tang Dynasty and its arch DB (any Linux release works; the decoder
#    is version-tolerant).  e.g. TD_RELEASE_March2020_r4.6.4 or the Dec-2018
#    golden.  Only arch/eagle_s20.db is needed.
unzip TD_RELEASE_March2020_r4.6.4_RHEL.zip     # -> .../arch/eagle_s20.db

# 2. Decode the fuse DB (pure Python, no TD execution, no license).
python3 scripts/anlogic_dbdecode.py \
    <TD>/arch/eagle_s20.db --out tmp/anlogic/db
#    -> tmp/anlogic/db/{tilegrid.json, bccinfo.json, meta.json}

# 3. Run the pipeline, pointing $ANLOGIC_DB at the decoded DB.
ANLOGIC_DB=tmp/anlogic/db \
    python3 scripts/run_pipeline.py --board boards/fnirsi-eg4s20 --all
```

### How the decode works

`arch/eagle_s20.db` is whitespace-separated records; string fields are
enciphered with a position-dependent substitution keyed by the family name on
line 0 (`0 eagle_s20 3` -> key `eagle_s20`). prjtang's `unlogic.py` walks the
whole file, but that walk is pinned to TD 4.2.885 and desyncs on other releases.
`anlogic_dbdecode.py` instead brute-forces the cipher phase (only `len(key)`
possibilities) to *locate* the two sections pluribus needs — `bcc_info`
(per-tile fuse bits) and `bil_info` (tile grid) — near the end of the file, and
decodes each directly, skipping every version-divergent middle section. On TD
4.6.4 the two independently-located sections abut perfectly (bcc_info ends on
the line before bil_info), which is only possible if the decode stayed synced.

The DB is derived from the proprietary Tang Dynasty and is **not** checked into
the repo (it is regenerable by the recipe above). Store it under `tmp/` or point
`$ANLOGIC_DB` / this board's `./eagle_s20_db/` at it.

## CRAM bit mapping (provisional)

A tile at `(start_frame, start_bit)` places fuse `(frame_off f, bit_off b)` at
CRAM `[start_frame+f][raw(start_bit+b)]`, where `raw()` inserts the two 6-bit
db→raw gaps (3892 db bits → 3904 raw). LUT-init reads directly under this
mapping and yields clean inits; the input-pin permutation is not yet
cross-checked against a TD-synthesised known function (a TD round-trip would
confirm it), so `classify_lut` pin assignments are indicative.
