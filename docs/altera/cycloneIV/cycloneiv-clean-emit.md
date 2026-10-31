# Cyclone IV GX clean emit: bitstream -> flat Verilog (#165, 2026-10-30)

Code: `lifters/cycloneiv_clean/emit.py` (Ctx, Builder, `verilog()`), CLI `scripts/cycloneiv_clean_emit.py`, `CycloneIVLift.lift_clean`.
Checks: `scripts/cycloneiv_clean_emit_check.py` (structural vs post-fit .vo / routing.rcf), `scripts/cycloneiv_clean_emit_sim.py` (iverilog vs .vo + Quartus sim_lib). Test: `tests/cycloneiv_clean/test_emit.py`.

## Decode rules used
- LUT input pin: `LE_LUT_INPUT` gi 0..3 = DATAA..DATAD (RCF `route_port`), site = LE; selection via `muxsel.MapSelect`; input number i < 38 = LOCAL_INTERCONNECT i, else LOCAL_LINE i - 38 (rule: `ASM_LE_LUT_INPUT::process_atom`@0x16c464). 3,819 / 3,819 pins on rb_000.
- LOCAL_LINE le = third output path of LE le; LE_BUFFER 2 le + b = output path b; value from `LE_REG_OUT_YGR` gi (1 = LUT, 0 = register).
- Unconnected LUT input = 1'b1 (every function-dependent unconnected input in the corpus is VCC).
- Carry: `LE_USE_CARRY` clear -> C input = cout of LE le - 1 (same LAB) or, for LE 0, LE 15 of the LAB at Y + 1 (`validate_chain_le_locations`@0xfb2b6); `cout = lut4(mask, a, b, cin, 0)` in every mode (cin = gnd when the chain is not used).
- FF controls (enable, async clear, sync clear / load incl. sload tied high, clock polarity, clock from LAB_CONTROL_MUX), register feedback on DATAC, FF existence from the sync bit: [cycloneiv-clean-ffctl.md](cycloneiv-clean-ffctl.md).
- sload tied high (LAB state 4 / 5, LE sync bit): D = ASDATA = LE DATAC input, with or without a LUT in the LE.
- IO_DATAIN / IO_RAW_DATAIN / CLK_BUFFER (x, y, S) = pad with site `X<x>Y<y>SUB_LOC<S>`.
- LOCAL_LINE le selected by a `LE_LUT_INPUT` pin (input number >= 38) of an existing LE counts as used (the consumer is a mux, not a routing edge): claims the LE's LOCAL_LINE register path / constant LUT. An FF-only LE's DATAC is its D, not the carry.
- HIO pad data (`MIO_LABLINE_TO_DATA` gi 0) and OE (`MIO_LABLINE_TO_OE`): `io_line.Line` = `asmdb_select.std_select` patterns (class 20 `ASMDB_HETEROGENEOUS_ENCODED_MUX::select`@0x8c334, `ASMDB_ARCH_GROUP_STD::select`@0x7a3ac) matched against the plane; input number < 38 = LOCAL_INTERCONNECT of the pad's tile. Driver = net of that LI. 132 / 132 HIO output pads of rb_000..009 equal the routing.rcf LI index. OE emitted as `pad = oe ? data : 1'bz` (HIO bidir only; unscored: no corpus RCF routes an OE port).

## Not decoded (explicit `// UNDECODED:` + counts)
- Power-up level (no asmdb group; every corpus dffeas is `low`, modelled 0); FF clock when the selected LAB clock mux is unconfigured (1,779 on the image).
- VIO bidirectional OE; HIO data/OE inversion (`MIO_DATA_INVERT`, `MIO_OE_INVERT`) and registered pad paths; CLKBUF_OUT source (pad / PLL); PLL connectivity; M9K widths / ports / modes; MAC mode and connectivity.
- BIM index of a pad pin: routing.ddb block interfaces (`blockiface.py`, E-R6): interface VIO_L / VIO_R / HIO node = BLOCK_INPUT_MUX, connection to element IO = (DB_INPUT_PORT_TYPE, z = SUB_LOC, index). HIO BIM = 8 z + {DATAIN 5, OE 4}; VIO_R serves SUB_LOC 0, 1 in tile x + 1, VIO_L SUB_LOC 2, 3 in tile x. `bim.py` PINS: DATA gi 0 / 1, OE, CLR, SCLR, INREG / OUTREG CE; OEREG CE and the CLK groups are not bound to a pin.
- CLKBUF_IN (`clkbuf.py`): fixed wire from its unique parent; the clock buffer input select group `CLKBUF_CLK_INPUT_SELECT_CYCLONEII` (block type 73, 30 sites) names the CLKBUF_IN index; BIM -> CLKBUF_IN from the CM_* interfaces (pin INCLK).
- Combinational loops (`scripts/cycloneiv_clean_loops.py`): graph over emitted pins; loops that exist only through pins the LUT's INIT ignores are not logic loops.
