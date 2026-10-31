# Cyclone IV third-party image corpus

- Purpose: independent gates for the Cyclone IV decoder (`docs/recovery-process.md` Phase 1). Not table sources.
- Images are other people's binaries, fetched for interop testing; **never committed**. Committed: `sources/cycloneiv-corpus/manifest.json` (URL, commit/tag, licence, SHA-256, size, analysis) and this file.
- Fetch / analyse / re-hash: `scripts/cycloneiv_corpus_fetch.py --fetch | --analyze | --verify` (log `tmp/logs/cycloneiv_corpus_fetch.log`). Each image sits in its own directory `sources/cycloneiv-corpus/<name>/`, read as data only.
- Caps: corpus <= 10 GB, >= 12 GB free disk (script stops loudly on breach). 5 EP4CGX150 images.
- Retrieved 2026-10-29.

## Method

- `.rbf`: used as published (raw or compressed) -> `cycloneiv_decompress.decompress` -> `cycloneiv_corpus.cram_plane`.
- `.sof`: converted with the vendor tool (`quartus_cpf -c -o bitstream_compression=off`), derived `.derived.rbf` beside it, then as above. The `.sof` container carries the device string; the `.rbf` carries none.
- Device identification: SOF string where available; else geometry signature (frame bytes, periphery frames, CRAM frames) matched to a SOF-identified image; else INFERRED (marked). Never from filename alone; board names in the notes are corroboration only.
- "Parses" = decompress succeeds, header CRC and every CRAM frame CRC-16 valid, `cram_plane` returns a plane without error. This is *decoded*, not *lifted*: no independent oracle (no netlist) exists for these images, so it is weaker evidence than the Quartus fuzz corpus.
- "Geometry supported" = `cycloneiv_geom.load(die_of(device))` exists (ep4cgx150 only).

## Images

| name | design | source repo | licence | device | bytes | frame; periph+CRAM frames | set CRAM bits | geometry supported | HDL source |
|---|---|---|---|---|---|---|---|---|---|
| `poseidon_galaksija` | Galaksija PLUS home computer core | turri21/GalaksijaPLUS_poseidon-ep4cgx150 | MIT | EP4CGX150 (inferred) | 1,412,585 | 796 B; 37+6154 | 399,649 | yes | HDL in the same repo |
| `poseidon_einstein` | Tatung Einstein core | turri21/TatungEinstein_poseidon-ep4cgx150 | GPL-2.0 | EP4CGX150 (inferred) | 1,502,642 | 796 B; 37+6154 | 587,794 | yes | HDL in the same repo |
| `poseidon_scv` | Epoch Super Cassette Vision core | turri21/SCV_poseidon-ep4cgx150 | GPL-2.0 | EP4CGX150 (inferred) | 1,395,654 | 796 B; 37+6154 | 365,224 | yes | HDL in the same repo |
| `poseidon_computerspace` | Computer Space arcade core | turri21/ComputerSpace_poseidon-ep4cgx150 | none stated (repo) | EP4CGX150 (inferred) | 1,374,113 | 796 B; 37+6154 | 320,332 | yes | HDL in the same repo |
| `neptuno_cgx150_mc2` | NeptUNO/MC2 firmware (NIOS II) on EP4CGX150 | distwave/neptuno-ep4cgx150 | none stated (repo) | EP4CGX150 (inferred) | 4,928,127 | 796 B; 37+6154 | 278,767 | yes | HDL in the same repo |

- All 5 decode with valid CRCs and `cram_plane` runs without errors.
- Geometry signature: 796 B x 37+6154 = EP4CGX150 (inferred from lane model). Other-die images removed: #173.
- Licence column is the repo's declared licence; "none stated" = no LICENSE file in the repo. Nothing is redistributed from here.
- Free oracle where HDL ships (rows with "HDL in the same repo"): build the HDL with Quartus on the same part for a matched source+bitstream pair. Not done yet.

## Not fetched / notes

- Source only (HDL, no bitstream): `michaelmiehling/A25_VME` (EP4CGX30, MEN Mikro, GPL-3.0), `aospan/NetUP_Dual_Universal_CI-fpga` (EP4CGX22, GPL-3.0).
- `.svf` only: `circuitvalley/Intel_FPGA_Board_98Y2610` (EP4CGX22), bitstream embedded in SVF; needs an SVF->rbf step.
- `.pof`/`.jic` of MC2 / QMTECH demos: flash images (extra wrapper), not fetched; same designs exist as `.sof`/`.rbf`.
- Not Cyclone IV: `ManuFerHi/Poseidon` `10CL120_cores/*.rbf` are Cyclone 10 LP; MiST cores are Cyclone III EP3C25.
- Product firmware that merely contains an FPGA (not fetched): none obtained.
