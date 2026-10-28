# Cyclone IV third-party image corpus

- Purpose: independent gates for the Cyclone IV decoder (`docs/recovery-process.md` Phase 1). Not table sources.
- Images are other people's binaries, fetched for interop testing; **never committed**. Committed: `sources/cycloneiv-corpus/manifest.json` (URL, commit/tag, licence, SHA-256, size, analysis) and this file.
- Fetch / analyse / re-hash: `scripts/cycloneiv_corpus_fetch.py --fetch | --analyze | --verify` (log `tmp/logs/cycloneiv_corpus_fetch.log`). Each image sits in its own directory `sources/cycloneiv-corpus/<name>/`, read as data only.
- Caps: corpus <= 10 GB, >= 12 GB free disk (script stops loudly on breach). Current total: 36.7 MB, 17 images.
- Retrieved 2026-10-29.

## Method

- `.rbf`: used as published (raw or compressed) -> `cycloneiv_decompress.decompress` -> `cycloneiv_corpus.cram_plane`.
- `.sof`: converted with the vendor tool (`quartus_cpf -c -o bitstream_compression=off`), derived `.derived.rbf` beside it, then as above. The `.sof` container carries the device string; the `.rbf` carries none.
- Device identification: SOF string where available; else geometry signature (frame bytes, periphery frames, CRAM frames) matched to a SOF-identified image; else INFERRED (marked). Never from filename alone; board names in the notes are corroboration only.
- "Parses" = decompress succeeds, header CRC and every CRAM frame CRC-16 valid, `cram_plane` returns a plane without error. This is *decoded*, not *lifted*: no independent oracle (no netlist) exists for these images, so it is weaker evidence than the Quartus fuzz corpus.
- "Geometry supported" = `cycloneiv_geom.load(die_of(device))` exists (lifters/data: ep4ce6 die = EP4CE6/EP4CE10, ep4cgx150 die = EP4CGX110/150). For the rest the default lane model is used for the plane only.

## Images

| name | design | source repo | licence | device | bytes | frame; periph+CRAM frames | set CRAM bits | geometry supported | HDL source |
|---|---|---|---|---|---|---|---|---|---|
| `neptuno_menu` | NeptUNO boot menu core | delgrom/neptUNOreloaded_Binaries | none stated (repo); cores derive from GPL MiST/MiSTer code | EP4CE55 (inferred) | 1,861,195 | 464 B; 21+3990 | 128,373 | no | no HDL in repo |
| `neptuno_nes` | NES console core | delgrom/neptUNOreloaded_Binaries | none stated (repo); NES core GPL-derived | EP4CE55 (inferred) | 1,861,195 | 464 B; 21+3990 | 490,768 | no | no HDL in repo |
| `neptuno_minimig` | Amiga (Minimig AGA) core | delgrom/neptUNOreloaded_Binaries | none stated (repo); Minimig is GPL | EP4CE55 (inferred) | 1,861,195 | 464 B; 21+3990 | 621,452 | no | no HDL in repo |
| `sidi_iremm92` | Irem M92 arcade core (SiDi) | ManuFerHi/SiDi-FPGA | none stated (repo) | EP4CE22F17C8 (SOF string) | 406,179 | 298 B; 25+2386 | 551,186 | no | no HDL in repo |
| `poseidon_galaksija` | Galaksija PLUS home computer core | turri21/GalaksijaPLUS_poseidon-ep4cgx150 | MIT | EP4CGX150 (inferred) | 1,412,585 | 796 B; 37+6154 | 399,649 | yes | HDL in the same repo |
| `poseidon_einstein` | Tatung Einstein core | turri21/TatungEinstein_poseidon-ep4cgx150 | GPL-2.0 | EP4CGX150 (inferred) | 1,502,642 | 796 B; 37+6154 | 587,794 | yes | HDL in the same repo |
| `poseidon_scv` | Epoch Super Cassette Vision core | turri21/SCV_poseidon-ep4cgx150 | GPL-2.0 | EP4CGX150 (inferred) | 1,395,654 | 796 B; 37+6154 | 365,224 | yes | HDL in the same repo |
| `poseidon_computerspace` | Computer Space arcade core | turri21/ComputerSpace_poseidon-ep4cgx150 | none stated (repo) | EP4CGX150 (inferred) | 1,374,113 | 796 B; 37+6154 | 320,332 | yes | HDL in the same repo |
| `joker_tv` | Joker TV USB DVB receiver FPGA (real product) | aospan/libjokertv | none stated (repo) | EP4CE22F17C8 (SOF string) | 710,848 | 298 B; 25+2386 | 136,614 | no | HDL in NetUP_Dual_Universal_CI-fpga (GPL-3.0), not this release |
| `ucore_ep4ce6` | uCore stack CPU on RZ-EasyFPGA EP4CE6 board | microCore-VHDL/uCore-for-Cyclone-IV | none stated (repo) | EP4CE6E22C8 (SOF string) | 364,192 | 210 B; 25+1727 | 114,308 | yes | VHDL in the same repo |
| `cam_isp_ep4ce6` | NIOS II camera ISP, SDRAM, LCD | bxinquan/nios2_cam_isp_demo | MIT | EP4CE6F17C8 (SOF string) | 380,918 | 210 B; 25+1727 | 158,975 | yes | Verilog in the same repo |
| `scope_ep4ce10` | AD9226 simple oscilloscope | Norman-w/fpga-simple-oscilloscope | none stated (repo) | EP4CE10F17C8 (SOF string) | 358,721 | 210 B; 25+1727 | 22,572 | yes | Verilog in the same repo |
| `basic52_ep4ce15` | BASIC-52 CPU on QMTECH EP4CE15 | mit41301/BASIC-52_EP4CE15F23 | none stated (repo) | EP4CE15F23C8 (SOF string) | 503,505 | 255 B; 37+1966 | 143,526 | no | HDL in the same repo |
| `bitcoin_de2_115` | SHA-256 miner on DE2-115 | progranism/Open-Source-FPGA-Bitcoin-Miner | GPL-3.0 | EP4CE115F29C7 (SOF string) | 3,541,342 | 639 B; 21+5568 | 1,843,190 | no | Verilog in the same repo |
| `d8m_tracker_de2_115` | D8M camera red-object tracker on DE2-115 | delhatch/Red_Tracker | none stated (repo) | EP4CE115F29C7 (SOF string) | 3,541,756 | 639 B; 21+5568 | 280,860 | no | HDL in the same repo |
| `sidi_neogeo` | Neo Geo core (SiDi128 board) | ManuFerHi/SiDi-FPGA | none stated (repo) | EP4CE115F29C7 (SOF string) | 1,213,623 | 639 B; 21+5568 | 670,689 | no | no HDL in repo |
| `neptuno_cgx150_mc2` | NeptUNO/MC2 firmware (NIOS II) on EP4CGX150 | distwave/neptuno-ep4cgx150 | none stated (repo) | EP4CGX150 (inferred) | 4,928,127 | 796 B; 37+6154 | 278,767 | yes | HDL in the same repo |

- All 17 decode with valid CRCs and `cram_plane` runs without errors.
- Geometry signatures: 210 B x 25+1727 = EP4CE6/EP4CE10 (same die, identical to our Quartus fuzz builds); 298 B = EP4CE22; 255 B = EP4CE15; 639 B = EP4CE115; 464 B = EP4CE55 (inferred); 796 B = EP4CGX150 (inferred from lane model).
- Licence column is the repo's declared licence; "none stated" = no LICENSE file in the repo. Nothing is redistributed from here.
- Free oracle where HDL ships (rows with "HDL in the same repo"): build the HDL with Quartus on the same part for a matched source+bitstream pair. Not done yet.

## Not fetched / notes

- Source only (HDL, no bitstream): `michaelmiehling/A25_VME` (EP4CGX30, MEN Mikro, GPL-3.0), `aospan/NetUP_Dual_Universal_CI-fpga` (EP4CGX22, GPL-3.0). Buildable with Quartus for a matched pair; EP4CGX22/30 are not geometry-supported.
- `.svf` only: `circuitvalley/Intel_FPGA_Board_98Y2610` (EP4CGX22), bitstream embedded in SVF; needs an SVF->rbf step.
- `.pof`/`.jic` of MC2 / QMTECH demos: flash images (extra wrapper), not fetched; same designs exist as `.sof`/`.rbf`.
- Many more `.sof` demos (LED/gate tutorials, ~359 KB, EP4CE6) exist (e.g. jvitkauskas/Altera-Cyclone-IV-board-V3.0); trivial designs, skipped.
- Not Cyclone IV: `ManuFerHi/Poseidon` `10CL120_cores/*.rbf` are Cyclone 10 LP; MiST cores are Cyclone III EP3C25.
- Product firmware that merely contains an FPGA (not fetched): none obtained.
