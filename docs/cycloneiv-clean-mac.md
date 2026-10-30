# Cyclone IV GX MAC (embedded multiplier) decode and behavioural emit (#165, 2026-10-30)

Code: `lifters/cycloneiv_clean/macctl.py`, `emit.py` (`Builder._mac`, `verilog()`). Checks: `scripts/cycloneiv_clean_mac_check.py` (structural), `scripts/cycloneiv_clean_mac_sim.py` (multiplier output vs the post-fit `mac_out` bus). Test: `tests/cycloneiv_clean/test_macctl.py`.
Conditions: EP4CGX150, existing builds only (0 new). All 44 MAC designs of the corpus are the `gxhb_mac*` specimen family; the rules were read off them, so there is no independent MAC design.

## Rules
- Used: any control cell of the instance set. MAC cells are in no default-bit list and read 0 in a MAC-free build; the output elements are `DSP_BUFFER`, which the old edge-based detection never saw (542 M9K tiles, 0 MAC edges). Image: 87 of 360 (was 0 detected).
- Pins: `MAC_ROW_DATA_INPUT` gi k (mapped mux, 46 inputs) = LOCAL_INTERCONNECT index of the MAC tile feeding data pin k (k < 18 DATAA[k], k >= 18 DATAB[k-18]); `MAC_PIA_TO_CLK` / `_CE` / `_CLR` / `_SIGN` gi k likewise (decoded with `ffctl.Calc`, the inverse of the asmdb mux writer). `MAC_ROW_DATA_INVERT` gi k = pin inversion.
- Sign: `MAC_SIGN_INVERT` gi 0 / 1 (A / B): bit set = unsigned, cleared = signed; dynamic sign pin = `MAC_PIA_TO_SIGN` gi 0 / 1 (the model's `signa` = 1 means signed: `cycloneiv_atoms.v`).
- Registers (earlier \"which register is enabled is not decoded\" was wrong): `MAC_ROW_IREG_{UPPER,LOWER}_DATA` gi 0 = A input register, gi 1 = B input register; `MAC_ROW_OREG_UPPER_DATA` gi 0 and 1 = output register (a multiplier register and an output register give the same bits: one register stage after the multiplier). `MAC_USE_NINE_BIT_DATA_WIDTH_PER_ROW` = 9-bit rows.
- Clock: `MAC_CLK_FAST_MUX` (7-bit one-hot): bit 0 = the PIA clock path (`MAC_PIA_TO_CLK` = LI index), bits 1..6 = block clock line 0..5 (`BLK_CLK_BUF` of the MAC tile; its structural parents are added in the forest).
- Result: bit i of the 36-bit product = `DSP_BUFFER` index i of the MAC tile; emitted as `mac_<x>_<y>_r[i]` of a behavioural 18 x 18 signed/unsigned multiplier with the decoded input / output registers (async clear, enable).
- Not modelled: 9-bit rows, two-multiplier and 36-bit modes (several MAC instances), saturation / rounding / shift (`MAC_*SATAC`, `SHFTR`), sign registers, accumulation.

## Results
- Structural (44 designs, matched / missing / extra / wrong): mac_inst 47 / 0 / 0 / 0 (incl. the 4 MAC instances of w36), mac_cfg 330 / 0 / 0 / 0, mac_pin 1,450 / 0 / 0 / 18 (the 18 are `two_mult_w9`: two 9-bit multipliers share the row inputs differently).
- Multiplier output equivalence (iverilog, emit vs post-fit mac_out, 300 random cycles): 42 pass, 0 fail, 2 not modelled (two_mult_w9, w36 has several outs).
- Pad-level `emit_sim`: all 44 fail on the result pads (BIM pad index of HIO pins not decoded, HIO agent); the multiplier bus itself matches.
- Image (counts): 87 MAC instances used, output register 29, input register A 53 / B 29, signed A 64 / B 79, dynamic sign pins 0, 2 in 9-bit / multi-MAC mode.
