"""MachXO2 IOLOGIC output DDR -> ODDRXE primitive record (issue #127).

An IOLOGIC<L> with MODE IDDR_ODDR whose PIO<L>.DATAMUX_ODDR is IOLDO drives its pad from the
DDR register: D0 = JOPOS<L> (CIB JA), D1 = JONEG<L> (JB), SCLK = JCLK, RST = JLSR.  Wire names
come from the PIC tile `.fixed_conn` table.  Input DDR (IDDRX*) and the x2/x4/x7 gearing modes
are not lifted; the settings are reported.
"""
import re
from pathlib import Path

_FC = re.compile(r"^\.fixed_conn E1_J(OPOS|ONEG|CLK|LSR|CE|TS)([A-D])_\w+IOLOGIC (J\w+)$")


def wires(dbroot, family, tiletype):
    """{(letter, role): wire} e.g. ('A', 'OPOS') -> 'JA0'."""
    out = {}
    for line in (Path(dbroot) / family / "tiledata" / tiletype / "bits.db").read_text().splitlines():
        m = _FC.match(line)
        if m:
            out[(m.group(2), m.group(1))] = m.group(3)
    return out


def cells(pc, resolve, pad_pin, dbroot, family="MachXO2"):
    """[{name, prim, params, pins, not_lifted}]; pad_pin(row, col, letter) -> package pin or None."""
    res = []
    for (r, c), ttype in sorted(pc.tile_type.items()):
        if not ttype.startswith("PIC_"):
            continue
        en = pc.enums.get((r, c), {})
        for L in "ABCD":
            if en.get(f"IOLOGIC{L}.MODE") is None:
                continue
            nl = []
            mode = en[f"IOLOGIC{L}.MODE"]
            if mode != "IDDR_ODDR":
                nl.append(f"IOLOGIC{L}.MODE {mode} (only IDDR_ODDR lifted)")
            if en.get(f"PIO{L}.DATAMUX_ODDR") != "IOLDO":
                nl.append(f"IOLOGIC{L} configured but PIO{L}.DATAMUX_ODDR is not IOLDO "
                          "(input DDR / gearing not lifted)")
            w = wires(dbroot, family, ttype)
            pins = {}
            for role, port in (("OPOS", "D0"), ("ONEG", "D1"), ("CLK", "SCLK"), ("LSR", "RST")):
                net = resolve(r, c, w[(L, role)]) if (L, role) in w else None
                inv = False
                if role == "CLK":
                    inv = en.get(f"IOLOGIC{L}.CLKOMUX") == "INV"
                if role == "LSR":
                    inv = en.get(f"IOLOGIC{L}.LSRMUX") == "INV"
                pins[port] = {"dir": "in", "net": net, "inv": inv}
            pins["Q"] = {"dir": "out", "net": None, "pad_pin": pad_pin(r, c, L)}
            lsro = en.get(f"IOLOGIC{L}.LSROMUX")
            if lsro not in (None, "LSRMUX"):
                nl.append(f"IOLOGIC{L}.LSROMUX {lsro}")
            for k in sorted(en):
                if k.startswith(f"IOLOGIC{L}.") and k.split(".", 1)[1] not in (
                        "MODE", "CLKOMUX", "CLKIMUX", "LSRMUX", "LSROMUX", "LSRIMUX", "GSR", "TSMUX"):
                    nl.append(f"{k}={en[k]} has no parameter mapping")
            ok = mode == "IDDR_ODDR" and en.get(f"PIO{L}.DATAMUX_ODDR") == "IOLDO"
            res.append({"name": f"R{r}C{c}_IOLOGIC{L}", "prim": "ODDRXE" if ok else "UNSUPPORTED",
                        "params": {"GSR": en.get(f"IOLOGIC{L}.GSR", "ENABLED")},
                        "pins": pins, "not_lifted": nl})
    return res
