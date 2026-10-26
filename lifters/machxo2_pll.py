"""MachXO2 sysCLOCK PLL -> EHXPLLJ primitive record (issue #104, #127).

Parameters come from the decoded GPLL tile; pin wiring from the tile's `.fixed_conn` table
(`S<n>E<m>_` = tile n rows south / m columns east of the PLL tile).  Settings that are
tool-derived or off-chip are reported in `not_lifted`, never guessed.
"""
import re
from pathlib import Path

# EHXPLLJ model parameters (cae_library/simulation/verilog/machxo2/EHXPLLJ.v) that the tile encodes.
_DIV = ("CLKI_DIV", "CLKFB_DIV", "CLKOP_DIV", "CLKOS_DIV", "CLKOS2_DIV", "CLKOS3_DIV")
_WORD_PARAMS = ("CLKOP_CPHASE", "CLKOS_CPHASE", "CLKOS2_CPHASE", "CLKOS3_CPHASE",
                "CLKOP_FPHASE", "CLKOS_FPHASE", "CLKOS2_FPHASE", "CLKOS3_FPHASE",
                "PREDIVIDER_MUXA1", "PREDIVIDER_MUXB1", "PREDIVIDER_MUXC1", "PREDIVIDER_MUXD1",
                "PLL_LOCK_MODE")
_ENUM_PARAMS = ("CLKOP_ENABLE", "CLKOS_ENABLE", "CLKOS2_ENABLE", "CLKOS3_ENABLE", "FEEDBK_PATH",
                "PLL_USE_WB", "CLKOP_TRIM_POL", "CLKOS_TRIM_POL", "CLKOP_TRIM_DELAY",
                "CLKOS_TRIM_DELAY", "VCO_BYPASS_A0", "VCO_BYPASS_B0", "VCO_BYPASS_C0",
                "VCO_BYPASS_D0", "INT_LOCK_STICKY", "FRACN_ENABLE", "DPHASE_SOURCE",
                "OUTDIVIDER_MUXA2", "OUTDIVIDER_MUXB2", "OUTDIVIDER_MUXC2", "OUTDIVIDER_MUXD2")
# Words the tool derives from the frequency plan (not HDL parameters).
TOOL_DERIVED = {"GMC_TEST", "ICP_CURRENT", "LPF_RESISTOR", "LPF_CAPACITOR", "KVCO", "GMC_GAIN",
                "FREQ_LOCK_ACCURACY", "MFG_ENABLE_FILTEROPAMP", "MFG_GMCREF_SEL",
                "MFG1_TEST", "MFG2_TEST", "MFG_EN_UP", "MFG_FLOAT_ICP", "MFG_FORCE_VFILTER",
                "MFG_GMC_PRESET", "MFG_GMC_RESET", "MFG_ICP_TEST", "MFG_LF_PRESET",
                "MFG_LF_RESET", "MFG_LF_RESGRND", "CLOCK_ENABLE_PORTS", "MODE",
                "FRACN_DIV", "FRACN_ORDER"}
OUT_PINS = {"CLKOP": 0, "CLKOS": 1, "CLKOS2": 2, "CLKOS3": 3}   # -> G_J<L|R>PLLCLK<n>
_PIN = re.compile(r"^(?:S(\d+))?(?:E(\d+))?_?(J\w+)$")
_cache = {}


def pin_table(dbroot, family, tiletype):
    """({pin: (drow, dcol, wire)} inputs, {pin: (drow, dcol, wire)} outputs) from bits.db."""
    key = (str(dbroot), family, tiletype)
    if key in _cache:
        return _cache[key]
    ins, outs = {}, {}
    for line in (Path(dbroot) / family / "tiledata" / tiletype / "bits.db").read_text().splitlines():
        if not line.startswith(".fixed_conn "):
            continue
        dst, src = line.split()[1:3]
        md, ms = _PIN.match(dst), _PIN.match(src)
        if dst.endswith("_PLL") and md and ms and not src.endswith("_PLL") and "EFB" not in src:
            pin = md.group(3)[1:-4]
            ins[pin] = (int(ms.group(1) or 0), int(ms.group(2) or 0), ms.group(3))
        elif src.endswith("_PLL") and md and ms and not dst.endswith("_PLL"):
            pin = ms.group(3)[1:-4]
            outs[pin] = (int(md.group(1) or 0), int(md.group(2) or 0), md.group(3))
    _cache[key] = (ins, outs)
    return ins, outs


def cells(pc, lift, design, resolve, dbroot, family="MachXO2"):
    """[{name, prim, params, pins, not_lifted}] for each GPLL tile of the design."""
    rc_to_name = {rc: n for n, rc in lift.tile_rc.items()}
    res = []
    for (r, c), ttype in sorted(pc.tile_type.items()):
        if "GPLL" not in ttype:
            continue
        en, wd = pc.enums.get((r, c), {}), pc.words.get((r, c), {})
        if en.get("MODE") != "EHXPLLJ":
            continue
        nl = []
        # a word absent from the decode is all-zero: DIV word 0 -> divide by 1
        params = {k: (int(wd[k], 2) if k in wd else 0) + 1 for k in _DIV}
        for k in _WORD_PARAMS:
            params[k] = int(wd[k], 2) if k in wd else 0
        for k in _ENUM_PARAMS:
            if k in en:
                v = en[k]
                params[k] = int(v) if v.isdigit() else v
        ins, outs = pin_table(dbroot, family, ttype)
        pins = {}
        side = "L" if ttype.endswith("L0") or "_L" in ttype else "R"
        # outputs: the global-clock wire G_J<side>PLLCLK<n> is the PLL output root
        for out, n in OUT_PINS.items():
            net = None
            for (ar, ac, sink, src) in pc.arcs:
                if src == f"G_J{side}PLLCLK{n}":
                    net = resolve(ar, ac, sink)
                    if net:
                        break
            pins[out] = {"dir": "out", "net": net}
        # reference clock: mux S1E1_REFCLK0 source
        refsrc = next((s for (ar, ac, sk, s) in pc.arcs if (ar, ac) == (r, c) and sk.endswith("REFCLK0")), None)
        if refsrc is None:
            pins["CLKI"] = {"dir": "in", "net": None}
            nl.append("reference clock mux not routed (internal oscillator or unrouted)")
        else:
            pins["CLKI"] = {"dir": "in", "net": resolve(r, c, refsrc)}
        fb = params.get("FEEDBK_PATH", "CLKOP")
        if fb not in ("INT_DIVD", "CLKOP"):
            nl.append(f"FEEDBK_PATH {fb}: feedback wiring not lifted")
        for pin, (dr, dc, wire) in ins.items():
            nm = {"ENCLKOP": "ENCLKOP", "ENCLKOS": "ENCLKOS", "ENCLKOS2": "ENCLKOS2",
                  "ENCLKOS3": "ENCLKOS3", "LOADREG": "LOADREG", "PHASEDIR": "PHASEDIR",
                  "PHASESEL0": "PHASESEL0", "PHASESEL1": "PHASESEL1", "PHASESTEP": "PHASESTEP",
                  "PLLWAKESYNC": "PLLWAKESYNC", "RESETC": "RESETC", "RESETD": "RESETD",
                  "RESETM": "RESETM", "RST": "RST", "STDBY": "STDBY"}.get(pin)
            if nm:
                pins[nm] = {"dir": "in", "net": resolve(r + dr, c + dc, wire)}
        for pin, (dr, dc, wire) in outs.items():
            nm = {"LOCK": "LOCK", "INTLOCK": "INTLOCK", "REFCLK": "REFCLK", "DPHSRC": "DPHSRC"}.get(pin)
            if nm:
                pins[nm] = {"dir": "out", "net": resolve(r + dr, c + dc, wire)}
        for k in sorted(set(wd) | set(en)):
            if k in TOOL_DERIVED:
                continue
            if k not in params and k not in (*_DIV, *_WORD_PARAMS, *_ENUM_PARAMS):
                nl.append(f"setting {k}={wd.get(k) or en.get(k)} has no parameter mapping")
        nl.append("FIN / frequency plan is off-chip (not in the bitstream); tool-derived words "
                  + ",".join(sorted(k for k in wd if k in TOOL_DERIVED)) + " follow from it")
        res.append({"name": f"R{r}C{c}", "prim": "EHXPLLJ", "params": params, "pins": pins,
                    "not_lifted": nl})
    return res
