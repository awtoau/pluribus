# Cyclone IV GX (EP4CGX150) PLL and clock buffers (#175, #165)

Code: `lifters/cycloneiv_clean/{pll,clkbuf,clocks}.py`; tracer hooks in `tracer.Extras`. Scripts: `cycloneiv_clean_pll_gate.py`, `cycloneiv_clean_pll_ports.py`, `cycloneiv_clean_image_clocks.py`, `cycloneiv_clean_hardblocks_build.py {gen|build} pllmp`.
Rules: ledger P-002, P-008..P-011, B-010, B-011. Facts: `tests/test_reversing_facts.py` (clkbuf / pll tests), `tests/cycloneiv_clean/test_pll.py`.

## Decoded from vendor data (no pair fitting)

- PLL_k = `IC_DESIGN_INDEX` of the asmdb dirt `COORDINATE_MAP_DATA` (`pll.pll_tiles`): FAST_PLL paths 0..5 = icd 1 5 6 7 8 2, GENERAL_PLL paths 0..1 = icd 3 4; SW_LOC (x, y) = tile (PLL_1 X0Y13 ... PLL_4 X117Y90).
  - `pll.PLL_SITE` is derived; the six specimen values agree, PLL_6 = (43, 2), PLL_7 = (43, 3) (specimens `gxhb_pllmp_site{6,7}`: enable bit at exactly that path).
- Clock buffer sites: dirt `CLKMUX_PLL_SOURCE` = 30 integers (index = site) = 5 runs of 6 (icd 1 8 4 2 3). A run belongs to the tile whose `PLL_BUFFER` parents include the icd (unique assignment) -> tiles (0,45) (0,46) (117,46) (57,91) (57,0). The hand-typed tile list is gone (`clkbuf.tiles`).
- Dirt integer decode: first element of each INTEGER node = delta against the previous INTEGER node of the file (running sum over all integer nodes; `io_dirt.py`).
- `PLL_BUFFER` (RCF type) = element 69 `PLLBUF`: 5 per PLL, index = output counter c0..c4; every CLKBUF_IN of index 2 / 3 has two PLL_BUFFER parents (two PLLs). Value of the select group = `8 | I` when the parent PLL's icd equals the dirt PLL of the site, `I` for the other parent (E-U5; writer `ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom`@0x2fd9f8 `| 8`, `second_pll_feeds_clock_mux`@0x2f9adc).
  - The compare is inferred from 7 of 7 PLL specimens (site 2 / 8 / 23 / 29 x PLL_k); the decompile is cut at a noreturn call. Dirt PLL not a parent of the selected CLKBUF_IN: both parents carry the same value; the enabled PLL (CFF) decides, two enabled = no edge.
- Fabric control inputs (areset, pfdena, clkswitch, scan*, phase*): group `PLL_<port>_INPUT` of the PLL path = LOCAL_INTERCONNECT index of the PLL tile; BIM index of the port from the vendor interface `PLL<icd>` (blockiface): CLKSWITCH 0, SCANCLK 1, PHASECOUNTERSELECT 2 / 9 / 19, CONFIGUPDATE 3, PHASEUPDOWN 8, SCANCLKENA 10, CLKBUFBLOCK ENA 11, PHASESTEP 17 (16 in PLL3 / PLL4), SCANDATA 24, PFDENA 25, ARESET 27.
  - Edges LI -> BIM are absent from the routing graph: `pll.Inputs` appends them. Specimens `gxhb_pllmp_{ar,pfd,sw,scan}`: 7 of 7 ports (value = RCF LI index, BIM = interface node). PHASEUPDOWN / PHASESTEP / PHASECOUNTERSELECT / EXTCLK_ENABLE: by elimination of the interface ports, unspecimened.
- Clock buffer core inputs (index 4): group `CLKBUF_INTERFACE_COREIN` gi = site, value = LOCAL_INTERCONNECT index; implicit edge LI -> the BIM feeding the CLKBUF_IN (ledger B-014; `ASM_CLKBUF_INTERFACE_COREIN::process_atom`@0x2fe19a). 5 specimens, 22 gate pips (fast run 32 listed 23 missing LI -> BIM at the clock buffer tiles). The group has one DB_ILLEGAL marker column (0xfffffffb): dropped from the pattern table.
- PLL_FBOUT -> PLL_FEEDBACK_IN (empty group): conducts while `PLL_ENABLE_PLL` is set (`pll.Wires`). The second parent (core feedback) is external feedback: not modelled. `PLL_FEEDBACK_SELECT` on PLL_1: value 0 = no compensation, 3 = normal (12 builds); PLL_6 / PLL_7 have no CRAM cells for it (MPLL).
- Frequency limits: `ddb_stingray4.pll` (EP4CGX150 parts, GPLL / MPLL, grades 6 7 8). Every value is a PERIOD in ps (vco 769..1666 ps = 1300..600 MHz; input 200000..2116 ps = 5..472 MHz). `pll.fin_interval`: VCO = Fin M / N, PFD = Fin / N, Fout = Fin M / (N C). Checked: Fin = 50 MHz inside the interval in 6 of 6 `gxhb_pllsite_*`, Fout = 100 MHz.

## Open

- PLL_CLKIN source (IO_RAW_DATAIN / CLKPIN_TO_PLLCLKIN_MUX / PLLREFCLKMUX -> PLL_CLKIN), ledger P-011: the 2-entry destination group cells are 0 in 12 PLL builds and 33 other designs although the RCF routes differ; PLL_6 / PLL_7 route through PLLREFCLKMUX. 1 missing pip per PLL design (the only PLL fault left in the PLL builds).
  - Asmdb of this die has no PLL_INPUT_CLOCK_SELECT / PLL_SELECT_REF_CLK group for blocks 43 / 45.
  - CFF diff base vs clkswitch (9 bits): PLL_SO_ENABLE, PLL_SO_CONTROL_MODE, PLL_CLOCK_SWITCH_INVERT, 6 IO pad bits. No clock-input select bit.
- Scan chain layout (144 bits) and dynamic reconfiguration: the CFF groups are the shadow of the scan chain; order in `ddb_stingray_basic.pll` (not read here). Switchover / lock-detect inputs: lock detect is output only (`PLL_LOCKED_PIN` edges match).
- Mux selection when a CLKBUF_IN has two enabled PLL parents with the dirt PLL not among them: no edge (counted missing).

## Image (counts only; per-domain detail local in `tmp/cycloneiv_clean/image_clocks.json`)

- 2 PLLs enabled: PLL_2 (M 14, N 1, c0 50 / 50) and PLL_8 (M 20, N 1, c0 4 / 4, c3 8 / 8), VCO post-scale 2.
- Clock buffer sites: 30 = 3 PLL_BUFFER + 2 CLK_BUFFER (dedicated pad) + 7 BLOCK_INPUT_MUX (core signal) + 18 unused. The 3 formerly undecoded sources are PLL outputs: PLL_8 c0, PLL_8 c3, PLL_2 c0.
- Clock domains: 6 roots, 34,112 FFs of which 31,495 resolve (PLL_8 c0 20,472; PLL_8 c3 10,530; pad 214; core clocks 141 + 99; PLL_2 c0 39); 2,617 FFs have no clock line.
- Frequencies for Fin unknown: Fin PLL_2 in [54.9, 119.0] MHz -> c0 = 0.14 Fin = [7.7, 16.7] MHz; Fin PLL_8 in [38.5, 83.3] MHz -> c0 = 2.5 Fin = [96.1, 208.3] MHz, c3 = 1.25 Fin = [48.1, 104.2] MHz. One shared crystal: [54.9, 83.3] MHz. Fin is not determined (PLL_CLKIN source open).
