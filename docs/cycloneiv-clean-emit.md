# Cyclone IV GX clean emit: bitstream -> flat Verilog (#165, 2026-10-30)

Code: `lifters/cycloneiv_clean/emit.py` (Ctx, Builder, `verilog()`), CLI `scripts/cycloneiv_clean_emit.py`, `CycloneIVLift.lift_clean`.
Checks: `scripts/cycloneiv_clean_emit_check.py` (structural vs post-fit .vo / routing.rcf), `scripts/cycloneiv_clean_emit_sim.py` (iverilog vs .vo + Quartus sim_lib). Test: `tests/cycloneiv_clean/test_emit.py`.

## Decode rules used
- LUT input pin: `LE_LUT_INPUT` gi 0..3 = DATAA..DATAD (RCF `route_port`), site = LE; selection via `muxsel.MapSelect`; input number i < 38 = LOCAL_INTERCONNECT i, else LOCAL_LINE i - 38 (rule: `ASM_LE_LUT_INPUT::process_atom`@0x16c464). 3,819 / 3,819 pins on rb_000.
- LOCAL_LINE le = third output path of LE le; LE_BUFFER 2 le + b = output path b; value from `LE_REG_OUT_YGR` gi (1 = LUT, 0 = register).
- Unconnected LUT input = 1'b1 (every function-dependent unconnected input in the corpus is VCC).
- Carry: `LE_USE_CARRY` clear -> C input = cout of LE le - 1 (same LAB).
- FF-only LE (all-zero INIT, register output): D = ASDATA = LE DATAC input.
- IO_DATAIN / IO_RAW_DATAIN / CLK_BUFFER (x, y, S) = pad with site `X<x>Y<y>SUB_LOC<S>`.
- LOCAL_LINE le selected by a `LE_LUT_INPUT` pin (input number >= 38) of an existing LE counts as used (the consumer is a mux, not a routing edge): claims the LE's LOCAL_LINE register path / constant LUT. An FF-only LE's DATAC is its D, not the carry.
- HIO pad data (`MIO_LABLINE_TO_DATA` gi 0) and OE (`MIO_LABLINE_TO_OE`): `io_line.Line` = `asmdb_select.std_select` patterns (class 20 `ASMDB_HETEROGENEOUS_ENCODED_MUX::select`@0x8c334, `ASMDB_ARCH_GROUP_STD::select`@0x7a3ac) matched against the plane; input number < 38 = LOCAL_INTERCONNECT of the pad's tile. Driver = net of that LI. 132 / 132 HIO output pads of rb_000..009 equal the routing.rcf LI index. OE emitted as `pad = oe ? data : 1'bz` (HIO bidir only; unscored: no corpus RCF routes an OE port).

## Not decoded (explicit `// UNDECODED:` + counts)
- FF enable, async clear, sync clear, sync load, clock polarity, power-up level (FF modelled idle, posedge, power-up 0).
- Carry chain entering a LAB; VIO bidirectional OE; HIO data/OE inversion (`MIO_DATA_INVERT`, `MIO_OE_INVERT`) and registered pad paths; CLKBUF_OUT source (pad / PLL); PLL connectivity; M9K widths / ports / modes; MAC mode and connectivity.
- Open, with the vendor location: BIM index of a pad pin (LI -> BIM pips, 1,305 HIO) = routing.ddb `DYGR_ROUTE_BLOCK_IO_MAPPING` (3) / `_ENTRY` (7,502) / `DYGR_ROUTE_BLOCK_INTERFACE` (28); serializers `DYGR_ROUTE_BLOCK_IO_MAPPING*::operator<<` libddb_dygr 0x2c7880 / 0x2c7680, pool position inside `DYGR_ROUTE_INFO_BODY::operator<<` 0x2d5040 not yet walked. HIO BIM index per SUB_LOC is a GT label only (5, 13, 21 = 5 + 8 SUB_LOC on rb_000..019), not used.
- Combinational loops (`scripts/cycloneiv_clean_loops.py`): graph over emitted pins; loops that exist only through pins the LUT's INIT ignores are not logic loops.
