"""Cyclone V hard-block cells (M10K, MLAB RAM) -> vendor primitive instances.

- A record is {name, kind, params, pins}: `kind` is the Quartus atom (cyclonev_ram_block ...),
  `params` its decoded parameters, `pins` {port: [net | "1'b0" | "1'b1", ...]} LSB first (outputs: nets).
- verilog.py instantiates the vendor model with these; the sim gate runs both sides on the same model.
- Every rule is a corpus differential against build.vo (docs/altera/cycloneV/cyclonev-postfit-oracle.md "RAM and MLAB");
  a block outside the rules is returned with `unmodelled` set, never guessed.
"""
import re


def _kvi(kv, key, default=None):
    v = kv.get((key, None))
    return default if v is None else v


def _routed(pins, port):
    """{pi: (net, is_output)} for one port name."""
    return {pi: v for (p, pi), v in pins.items() if p == port}


def m10k_addr_pins(abits, dbits):
    """Physical ADDR pin index for logical address bit (nextpnr mistral/pack.cc setup_m10ks)."""
    offset = max(12 - max(abits, 8 if dbits == 40 else 9), 0)
    return {bit: bit + offset for bit in range(abits)}


def m10k_cell(tile, kv, pins):
    """One M10K tile -> record.

    kv: {(mux, idx): value} of the tile's `s` lines.  pins: {(port, pi): (net, is_output)} of routed ports.
    Rules (all 0 exceptions over the 20 corpus RAM designs):
      width A = A_DATA_WIDTH (default 40), width B = B_DATA_WIDTH (default 20).
      ADDRB routed: dual_port (A writes, B reads); only ADDRA: single_port, or rom if no WREN / DATAAIN routed.
      output register: {A,B}_OUTPUT_SEL == REG -> port_{a,b}_data_out_clock clock0.
      dual_port x40: DATAAIN.k / DATABIN.k = portadatain[k] / [20+k]; DATAAOUT.k / DATABOUT.k = portbdataout[k] / [20+k].
      single_port: DATAAIN.k = portadatain[k], DATAAOUT.k = portadataout[k].
      address: ADDR<A|B>.p = bit p - offset (m10k_addr_pins); abits = smallest 1..13 whose pin set covers the routed pins.
      write enable: WREN.0 or WREN.1, whichever is routed (design-dependent, TOP_W_SEL/BOT_W_SEL).
      clock: CLKIN.0 (or .6) = clk0; CLKIN.1 (or .7) routed = clk1 and the B side (address, read enable) on clock1.
    """
    x, y = tile[1], tile[2]
    name = f"ram_m10k_r{x}c{y}"
    wa = int(_kvi(kv, "A_DATA_WIDTH", "40"))
    wb = int(_kvi(kv, "B_DATA_WIDTH", "20"))
    addra, addrb = _routed(pins, "ADDRA"), _routed(pins, "ADDRB")
    dual = bool(addrb)
    rec = {"name": name, "kind": "cyclonev_ram_block", "x": x, "y": y, "block": "M10K",
           "params": {}, "pins": {}, "outs": {}, "unmodelled": None}
    if _kvi(kv, "TRUE_DUAL_PORT", "0") == "1" and dual:
        rec["unmodelled"] = "bidir_dual_port: no corpus evidence"
        return rec
    if dual and not (wa == 40 and wb == 40):
        rec["unmodelled"] = f"dual_port with widths A={wa} B={wb}: no corpus evidence"
        return rec
    ref = addrb if dual else addra
    abits = next((n for n in range(1, 14)
                  if set(ref) <= set(m10k_addr_pins(n, wa).values())), None)
    if abits is None:
        rec["unmodelled"] = f"address pins {sorted(ref)} fit no depth"
        return rec
    amap = m10k_addr_pins(abits, wa)
    rom = not dual and ("WREN", 0) not in pins and ("WREN", 1) not in pins and not _routed(pins, "DATAAIN")
    ck0 = 0 if ("CLKIN", 0) in pins else 6 if ("CLKIN", 6) in pins else 0     # CLKIN.6 / .7 = alternate pins
    ck1 = 1 if ("CLKIN", 1) in pins else 7 if ("CLKIN", 7) in pins else None
    clk1 = ck1 is not None
    depth = 1 << abits
    used = lambda port: sorted(pi for (p, pi) in pins if p == port)
    width = (max(used("DATAAIN") + [pi + 20 for pi in used("DATABIN")] + used("DATAAOUT")
                 + [pi + 20 for pi in used("DATABOUT")], default=-1) + 1)
    rec["params"] = {
        "operation_mode": '"dual_port"' if dual else '"rom"' if rom else '"single_port"',
        "mixed_port_feed_through_mode": '"old"',
        "ram_block_type": '"M20K"',
        "port_a_data_width": wa, "port_b_data_width": wa if not dual else wb,
        "port_a_address_width": abits, "port_b_address_width": abits,
        "port_a_logical_ram_depth": depth, "port_a_logical_ram_width": width,
        "port_a_first_address": 0, "port_a_last_address": depth - 1, "port_a_first_bit_number": 0,
        "port_b_logical_ram_depth": depth, "port_b_logical_ram_width": width,
        "port_b_first_address": 0, "port_b_last_address": depth - 1, "port_b_first_bit_number": 0,
        "port_a_data_out_clock": '"clock0"' if _kvi(kv, "A_OUTPUT_SEL") == "REG" else '"none"',
        "port_b_data_out_clock": '"clock0"' if _kvi(kv, "B_OUTPUT_SEL") == "REG" else '"none"',
        "port_b_address_clock": '"clock1"' if clk1 else '"clock0"',
        "port_b_read_enable_clock": '"clock1"' if clk1 else '"clock0"',
        "port_a_address_width": abits,
    }
    if ("ENABLE", 1) in pins:
        rec["params"]["clk0_core_clock_enable"] = '"ena0"'
    net = lambda port, pi: pins[(port, pi)][0] if (port, pi) in pins else "1'b0"
    P = rec["pins"]
    P["portadatain"] = [net("DATAAIN", k) if k < 20 else net("DATABIN", k - 20) for k in range(wa)]
    P["portaaddr"] = [net("ADDRA", amap[b]) for b in range(abits)]
    P["portbaddr"] = [net("ADDRB", amap[b]) for b in range(abits)] if dual else ["1'b0"] * abits
    P["portbdatain"] = ["1'b0"] * (wb if dual else wa)
    wr = [pi for pi in (0, 1) if ("WREN", pi) in pins]
    if len({pins[("WREN", pi)][0] for pi in wr}) > 1:
        rec["unmodelled"] = "WREN.0 and WREN.1 carry different nets: no corpus evidence"
        return rec
    P["portawe"] = [net("WREN", wr[0])] if wr else ["1'b0"]
    P["portbwe"] = ["1'b0"]
    P["portare"] = ["1'b1"]
    P["portbre"] = [net("RDEN", 0)] if ("RDEN", 0) in pins else ["1'b1"]
    P["clk0"] = [net("CLKIN", ck0)]
    P["clk1"] = [net("CLKIN", ck1)] if clk1 else ["1'b0"]
    P["ena0"] = [net("ENABLE", 1)] if ("ENABLE", 1) in pins else ["1'b1"]
    P["ena1"] = P["ena2"] = P["ena3"] = ["1'b1"]
    P["clr0"] = P["clr1"] = ["1'b0"]
    P["nerror"] = ["1'b1"]
    P["portabyteenamasks"] = P["portbbyteenamasks"] = ["1'b1"]
    P["portaaddrstall"] = P["portbaddrstall"] = ["1'b0"]
    P["devclrn"] = P["devpor"] = ["1'b1"]
    o = rec["outs"]            # output port -> {bit: net}
    port = "portbdataout" if dual else "portadataout"
    o[port] = {}
    for pi in used("DATAAOUT"):
        o[port][pi] = pins[("DATAAOUT", pi)][0]
    for pi in used("DATABOUT"):
        o[port][pi + 20] = pins[("DATABOUT", pi)][0]
    # contents: RAM.<row> = 40-bit word, stored inverted, bits permuted (nextpnr write_m10k_cell)
    rec["init"] = m10k_init(kv, abits, wa) if wa in (20, 40) else 0
    if not rec["init"] and any(v != "ff.ffffffff" for (m, _i), v in kv.items() if m == "RAM") and wa not in (20, 40):
        rec["unmodelled"] = f"initial contents at width {wa}: no corpus evidence"
    return rec


_PERM = [0, 20, 10, 30, 1, 21, 11, 31, 2, 22, 12, 32, 3, 23, 13, 33, 4, 24, 14, 34,
         5, 25, 15, 35, 6, 26, 16, 36, 7, 27, 17, 37, 8, 28, 18, 38, 9, 29, 19, 39]


def m10k_init(kv, abits, wa):
    """Initial contents as one integer (word a at bits [wa*a +: wa]), logical addresses 0..2^abits-1.

    RAM.<row> = 40-bit physical row, stored inverted with bits permuted (nextpnr write_m10k_cell).
    A row holds 40/wa words (low word first); the row index has 8 bits and the bits above the
    design's address range read as 1 (c_raminit_vnd_m10k_*, c_rom_vnd_m10k_8: rows 192..255).
    """
    wpr = 40 // wa
    nrows = max(1, (1 << abits) // wpr)
    tied = 0xFF & ~(nrows - 1)
    init = 0
    for k in range(nrows):
        v = kv.get(("RAM", k | tied))
        if v is None:
            continue
        hi, lo = v.split(".")
        word = (~((int(hi, 16) << 32) | int(lo, 16))) & ((1 << 40) - 1)      # undo inversion
        orig = 0
        for bit in range(40):                                                 # undo permute_init
            orig |= ((word >> bit) & 1) << _PERM[bit]
        init |= orig << (40 * k)
    return init


def mlab_cell(tile, alm, half, raw, kv, w, perm):
    """One RAM-mode MLAB ALM half (a 32 x 1 LUT-RAM bit) -> cyclonev_mlab_cell record.

    w: resolved nets {out, rd[5], din, wa[5], clk, clk_inv, we, we_inv}.
    Rules (nextpnr mistral/lab.cc assign_mlab_inputs, checked against the 4 c_ram_vnd_mlab_* designs):
      read address = pins A,B,C,D,F0 of the ALM; write data = E0 (E1 for the bottom half);
      write address = pin F1 of ALMs 2,3,7,6,1 (LAB-wide); write clock / enable = the LAB clock / enable
      selected like a register's (CLK0 / DATAIN.2); read data = the half's LUT output port.
      contents: word v = NOT raw[perm[31 - v]] (stored inverted, permuted, address bits complemented: 8/8 cells of c_raminit_vnd_mlab_4); top half = raw[0:32], bottom half = raw[32:64].
    """
    x, y = tile[1], tile[2]
    name = f"ram_mlab_r{x}c{y}_a{alm}_{'top' if half == 'T' else 'bottom'}"
    rec = {"name": name, "kind": "cyclonev_mlab_cell", "x": x, "y": y, "block": tile[0], "alm": alm,
           "half": half, "params": {}, "pins": {}, "outs": {}, "unmodelled": None}
    if w["clk"] is None or w["we"] is None:
        rec["unmodelled"] = "MLAB write clock / enable source not recovered"
        return rec
    pol = lambda net, inv: f"!{net}" if inv and not net.startswith("1'b") else net
    rec["params"] = {"data_width": 1, "address_width": 5, "byte_enable_mask_width": 1, "byte_size": 1,
                     "logical_ram_depth": 32, "logical_ram_width": 1, "first_address": 0,
                     "last_address": 31, "first_bit_number": 0, "mixed_port_feed_through_mode": '"new"'}
    P = rec["pins"]
    P["portadatain"] = [w["din"]]
    P["portaaddr"] = list(w["wa"])
    P["portbaddr"] = list(w["rd"])
    P["portabyteenamasks"] = ["1'b1"]
    P["clk0"] = [pol(w["clk"], w["clk_inv"])]
    P["clk1"] = ["1'b0"]
    P["ena0"] = [pol(w["we"], w["we_inv"])]
    P["ena1"] = P["ena2"] = ["1'b1"]
    P["clr"] = ["1'b0"]
    P["devclrn"] = P["devpor"] = ["1'b1"]
    rec["outs"] = {"portbdataout": {0: w["out"]}}
    word = 0
    off = 32 if half == "B" else 0
    for v in range(32):
        word |= (1 - ((raw >> perm[(31 - v) + off]) & 1)) << v      # read-address inputs are inverted
    rec["init"] = word
    return rec


# ---- FPLL -----------------------------------------------------------------------------------------
# Reference-clock pad per (FPLL tile, CLKIN_0_SRC): CLKIN_0_SRC = 4 + position in the FPLL `clkin` pad list,
# evidenced by Quartus builds with the refclk pinned (c_pll_vnd_*: H10; c_pllpin_*: the rest, #112).
# Values below 4 and pads without a build: NOT LIFTED, never guessed.
FPLL_REFCLK_PAD = {
    ((54, 37), 4): "GPIO.038.045.0:COMBOUT", ((54, 37), 5): "GPIO.044.045.0:COMBOUT",   # H10, G13
    ((0, 37), 4): "GPIO.014.045.0:COMBOUT", ((0, 37), 5): "GPIO.022.045.0:COMBOUT",     # K7, G10
    ((0, 37), 6): "GPIO.038.045.0:COMBOUT", ((0, 37), 7): "GPIO.044.045.0:COMBOUT",     # H10, G13
    ((54, 0), 4): "GPIO.038.000.0:COMBOUT", ((54, 0), 5): "GPIO.046.000.0:COMBOUT",     # U13, T15
    ((54, 0), 6): "GPIO.054.018.0:COMBOUT",                                             # L17
    ((0, 0), 4): "GPIO.022.000.0:COMBOUT", ((0, 0), 5): "GPIO.029.000.0:COMBOUT",       # P9, R10
    ((0, 0), 6): "GPIO.038.000.0:COMBOUT", ((0, 0), 7): "GPIO.046.000.0:COMBOUT",       # U13, T15
}
# Settings the model covers: value None = any value (analog / lock-filter, no effect on simulation).
_FPLL_KNOWN = {"FPLL_ENABLE": "1", "PL_AUX_BG_POWERDOWN": None, "NREVERT_INVERT": "1", "FRACTIONAL_DIVISION_SETTING": "00000001",
               "VCO_DIV": "0", "TCLK_SEL": "0", "CTRL_OVERRIDE_SETTING": "0", "CNT_IN_SRC": "0",
               "CLKIN_0_SRC": None, "BWCTRL": None, "CP_CURRENT": None, "LOCK_FILTER_CFG_SETTING": None,
               "UNLOCK_FILTER_CFG_SETTING": None, "VCO0PH_EN": None, "M_CNT_HI_DIV_SETTING": None,
               "M_CNT_LO_DIV_SETTING": None, "N_CNT_HI_DIV_SETTING": None, "N_CNT_LO_DIV_SETTING": None,
               "DPRIO0_CNT_HI_DIV": None, "DPRIO0_CNT_LO_DIV": None, "DPRIO0_CNT_ODD_DIV_EVEN_DUTY_EN": None}


def fpll_cell(tile, kv, nets=None):
    """One enabled FPLL tile -> `pluribus_cv_fpll` record (lifters/data/cyclonev_fpll_model.v).

    - f(counter c) = ref * M / N / C; M = M_HI + M_LO, N = N_HI + N_LO, C = DPRIO0_HI.c + DPRIO0_LO.c
      (unset hi/lo fields are 1).  Checked against the Quartus defparams by the sim gate.
    - Output counter c drives FPLL:CLKOUT.c (clock-tree CMUX PLLIN); refclk pad from FPLL_REFCLK_PAD.
    - nets: {"refclk", "nreset", "lock", ("clkout", c)} -> net (lifter); missing refclk/nreset = fault.
    - Settings outside _FPLL_KNOWN (phase, presets, bypass, fractional, ...) -> `unmodelled`.
    """
    x, y = tile[1], tile[2]
    nets = nets or {}
    hx = lambda key, idx=None, d=1: int(kv[(key, idx)], 16) if (key, idx) in kv else d
    m = hx("M_CNT_HI_DIV_SETTING") + hx("M_CNT_LO_DIV_SETTING")
    n = hx("N_CNT_HI_DIV_SETTING") + hx("N_CNT_LO_DIV_SETTING")
    cs, hi, lo, odd = {}, {}, {}, {}
    for c in range(9):
        if _kvi(kv, f"C{c}_COUT_EN") == "1":
            hi[c], lo[c] = hx("DPRIO0_CNT_HI_DIV", c), hx("DPRIO0_CNT_LO_DIV", c)
            odd[c] = kv.get(("DPRIO0_CNT_ODD_DIV_EVEN_DUTY_EN", c)) == "1"
            cs[c] = hi[c] + lo[c]
    why = []
    for (key, idx), val in sorted(kv.items(), key=str):
        if re.match(r"^(C\d_COUT_EN|VCO_PH\d_EN)$", key):
            continue
        if key not in _FPLL_KNOWN:
            why.append(f"{key}{'' if idx is None else f'.{idx}'}={val}")
        elif _FPLL_KNOWN[key] is not None and val != _FPLL_KNOWN[key]:
            why.append(f"{key}={val}")
    clkin = hx("CLKIN_0_SRC", None, 2)
    if ((x, y), clkin) not in FPLL_REFCLK_PAD:
        why.append(f"refclk from the clock network (CLKIN_0_SRC=0: core / PLL cascade)" if clkin == 0 else
                   f"refclk pad for CLKIN_0_SRC={clkin} (no corpus evidence)")
    for need in ("refclk", "nreset"):
        if not nets.get(need):
            why.append(f"{need} net not found")
    outs = {"locked": {0: nets["lock"]}} if nets.get("lock") else {}
    clk = {c: nets[("clkout", c)] for c in cs if nets.get(("clkout", c))}
    if clk:
        outs["clkout"] = clk
    byte = lambda d: "72'h" + "".join(f"{d.get(c, 0):02x}" for c in range(8, -1, -1))
    bits = lambda d: "9'b" + "".join("1" if d.get(c) else "0" for c in range(8, -1, -1))
    return {"name": f"fpll_r{x}c{y}", "kind": "pluribus_cv_fpll", "x": x, "y": y, "block": "FPLL",
            "params": {"M": m, "N": n, "NRESET_INVERT": 1, "C_HI": byte(hi), "C_LO": byte(lo),
                       "C_ODD": bits(odd), "C_EN": bits({c: c in clk for c in cs})},
            "pins": {"refclk": [nets.get("refclk")], "nreset": [nets.get("nreset")]},
            "outs": outs,
            "decode": {"m": m, "n": n, "c": cs, "clkin_0_src": clkin},
            "unmodelled": "; ".join(why) or None}


# ---- DSP (cyclonev_mac) -------------------------------------------------------------------------
# Mistral DSP pins: DATAIN.<n> of bank bi (9 bits per bank), RESULT.<k>, CLKIN.<c>.  Which atom port bit
# a (bank, n) is depends on the operation mode; learned from the corpus by pad correlation (build.vo
# port bit -> pad -> lifted pin), docs/altera/cycloneV/cyclonev-postfit-oracle.md "DSP".
#   m9x9        : ax[n] = bank0.n   bx[n] = bank1.n   ay[n] = bank2.n   by[n] = bank3.n   (lane 0 only)
#   m27x27      : ax[0:9]=bank0 ax[9:18]=bank6 ax[18:27]=bank7; ay: banks 2, 8, 9
#   m18x18_sumof2 (Mistral M18X19_COMBINED): ax/ay as m18x18_full, bx = banks 6,7, by = banks 8,9; by[18] = bank11.8
#   m18x18_full : ax[9b+n] = bank b.n (b=0,1)   ay[9(b-2)+n] = bank b.n (b=2,3)   ay[18] = bank5.8
# RESULT.k = resulta[k] in every mode.  CLKIN.c = clk[c].
_DSP_BANKS = {
    "m9x9": {"ax": [0], "bx": [1], "ay": [2], "by": [3]},
    "m18x18_full": {"ax": [0, 1], "ay": [2, 3]},
    "m18x18_sumof2": {"ax": [0, 1], "ay": [2, 3], "bx": [6, 7], "by": [8, 9]},
    "m27x27": {"ax": [0, 6, 7], "ay": [2, 8, 9]},
}
_DSP_SIGN_EXT = {("m18x18_full", "ay"): 5, ("m18x18_sumof2", "ay"): 5, ("m18x18_sumof2", "by"): 11}
_DSP_WIDTH = {   # atom port widths Quartus uses per mode: (ax, ay, bx, by)
    "m9x9": (9, 9, 9, 9),
    "m18x18_full": (18, 19, 16, 16),
    "m18x18_sumof2": (18, 19, 18, 19),
    "m27x27": (27, 27, 16, 16),
}


def dsp_cell(tile, kv, pins):
    """One DSP tile -> cyclonev_mac record; modes outside the corpus evidence are `unmodelled`."""
    x, y = tile[1], tile[2]
    rec = {"name": f"dsp_r{x}c{y}", "kind": "cyclonev_mac", "x": x, "y": y, "block": "DSP",
           "params": {}, "pins": {}, "outs": {}, "unmodelled": None}
    raw = _kvi(kv, "MODE")
    mode = {"M9X9": "m9x9", None: "m18x18_full", "M18X19_COMBINED": "m18x18_sumof2",
                         "M27X27": "m27x27"}.get(raw)
    if mode is None:
        rec["unmodelled"] = f"DSP MODE {raw}: no corpus evidence"
        return rec
    wax, way, wbx, wby = _DSP_WIDTH[mode]
    net = lambda bank, n: pins[(bank, "DATAIN", n)][0] if (bank, "DATAIN", n) in pins else "1'b0"

    def bus(port, width):
        bits = []
        for i in range(width):
            banks = _DSP_BANKS[mode].get(port)
            if banks and i // 9 < len(banks):
                bits.append(net(banks[i // 9], i % 9))
            elif i == 18 and (mode, port) in _DSP_SIGN_EXT:
                bits.append(net(_DSP_SIGN_EXT[(mode, port)], 8))
            else:
                bits.append("1'b0")
        return bits
    P = rec["pins"]
    P["ax"], P["ay"], P["bx"], P["by"] = bus("ax", wax), bus("ay", way), bus("bx", wbx), bus("by", wby)
    P["az"] = ["1'b0"] * 26
    P["bz"] = ["1'b0"] * 18
    P["scanin"] = ["1'b0"] * way
    P["coefsela"] = P["coefselb"] = ["1'b0"] * 3
    P["chainin"] = ["1'b0"] * 64
    for p in ("sub", "negate", "accumulate", "loadconst"):
        P[p] = ["1'b0"]
    P["clk"] = [pins[(None, "CLKIN", c)][0] if (None, "CLKIN", c) in pins else "1'b0" for c in range(3)]
    P["ena"] = ["1'b1"] * 3
    P["aclr"] = ["1'b0"] * 2
    on = lambda key: _kvi(kv, key) in ("1", "REG")
    # Mistral's A/B lane names are swapped against the atom's in the 18x19 mode (corpus: BX/BY registered
    # and signed <=> atom ax/ay clock "0" and signed true), also in m9x9; sumof2 (COMBINED) follows the atom.
    lane = {"ax": "AX", "ay": "AY", "bx": "BX", "by": "BY"} if mode == "m18x18_sumof2" else \
           {"ax": "BX", "ay": "BY", "bx": "AX", "by": "AY"}
    q = lambda v: '"true"' if v else '"false"'
    rec["params"] = {
        "operation_mode": f'"{mode}"', "ax_width": wax, "ay_scan_in_width": way, "bx_width": wbx,
        "by_width": wby, "result_a_width": 64,
        "signed_max": q(on(lane["ax"] + "_SIGNED")), "signed_may": q(on(lane["ay"] + "_SIGNED")),
        "signed_mbx": q(on(lane["bx"] + "_SIGNED")), "signed_mby": q(on(lane["by"] + "_SIGNED")),
        "ax_clock": '"0"' if on("INREG_CTRL_" + lane["ax"]) else '"none"',
        "ay_scan_in_clock": '"0"' if on("INREG_CTRL_" + lane["ay"]) else '"none"',
        "bx_clock": '"0"' if on("INREG_CTRL_" + lane["bx"]) else '"none"',
        "by_clock": '"0"' if on("INREG_CTRL_" + lane["by"]) else '"none"',
        "output_clock": '"0"' if on("OREG_CTRL") else '"none"',
    }
    rec["outs"] = {"resulta": {pi: pins[(None, "RESULT", pi)][0] for (b, p, pi) in pins
                                if p == "RESULT" and b is None}}
    return rec
