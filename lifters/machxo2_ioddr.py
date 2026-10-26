"""MachXO2 IOLOGIC output DDR -> ODDRXE primitive record (issue #127).

An IOLOGIC<L> with MODE IDDR_ODDR whose PIO<L>.DATAMUX_ODDR is IOLDO drives its pad from the
DDR register: D0 = JOPOS<L> (CIB JA), D1 = JONEG<L> (JB), SCLK = JCLK, RST = JLSR.  Wire names
come from the PIC tile `.fixed_conn` table.  Input DDR (IDDRX*) and the x2/x4/x7 gearing modes
are not lifted; the settings are reported.
"""
import re
from pathlib import Path

_FC = re.compile(r"^\.fixed_conn (?:[NSEW]1_)?J(OPOS|ONEG|CLK|LSR|CE|TS)([A-D])_\w*IOLOGIC (?:([NSEW])1_)?(J\w+)$")
_OFF = {None: (0, 0), "N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}


def wires(dbroot, family, tiletype):
    """{(letter, role): (drow, dcol, wire)} e.g. ('A', 'OPOS') -> (0, 0, 'JA0'); top edge uses S1_ wires."""
    out = {}
    for line in (Path(dbroot) / family / "tiledata" / tiletype / "bits.db").read_text().splitlines():
        m = _FC.match(line)
        if m:
            out[(m.group(2), m.group(1))] = (*_OFF[m.group(3)], m.group(4))
    return out


def cells(pc, resolve, pad_pin, pad_net, dbroot, family="MachXO2"):
    """[{name, prim, params, pins, not_lifted}]; pad_pin(row, col, letter) -> package pin or None;
    pad_net(row, col, letter) -> fabric net driving that output pad (= the OPOS/D0 wire; the lift keys
    pad J-wires through the pad node, so D0 is read from the pad rather than from the wire)."""
    res = []
    sinks = {(r, c, sk) for (r, c, sk, _src) in pc.arcs}
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
                net = None
                if (L, role) in w:
                    dr, dc, wire = w[(L, role)]
                    # a J wire no decoded arc drives is unrouted (the pad keeps a placeholder net)
                    if (r + dr, c + dc, wire) in sinks:
                        net = pad_net(r, c, L) if role == "OPOS" else resolve(r + dr, c + dc, wire)
                if net is None and role in ("OPOS", "ONEG", "CLK"):
                    nl.append(f"{port} unrouted in the bitstream (tie-off / dedicated clock source not decodable)")
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
