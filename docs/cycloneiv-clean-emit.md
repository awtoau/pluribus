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

## Not decoded (explicit `// UNDECODED:` + counts)
- FF enable, async clear, sync clear, sync load, clock polarity, power-up level (FF modelled idle, posedge, power-up 0).
- Carry chain entering a LAB; HIO pad output data; bidirectional OE; CLKBUF_OUT source (pad / PLL); PLL connectivity; M9K widths / ports / modes; MAC mode and connectivity.
