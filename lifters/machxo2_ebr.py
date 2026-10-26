"""MachXO2 EBR -> vendor primitive record (DP8KC / PDPW8KC), issue #127.

Pin wiring comes from the device DB (`.fixed_conn` of the EBR0 tile: primitive pin <-> CIB
J-wire, `E1_`/`E2_` prefixes = the EBR1/EBR2 tile one/two columns right); parameters from the
decoded EBR1/EBR2 tile config.  Anything the decode cannot place is returned in `not_lifted`,
never guessed.
"""
import re
from pathlib import Path

_FLAG_PINS = {"AE", "AF", "EF", "FF"}      # FIFO8KB flag outputs: FIFO mode is not lifted
_OFF = {"": 0, "E1_": 1, "E2_": 2}
_WIRE = re.compile(r"^(E1_|E2_)?(J\w+)$")
_INV_MUX = {"RSTA": "EBR.RSTAMUX", "RSTB": "EBR.RSTBMUX", "WEA": "EBR.WEAMUX", "WEB": "EBR.WEBMUX"}
_CONST_MUX = {"ADA0": "EBR.ADA0MUX", "ADA1": "EBR.ADA1MUX", "ADB0": "EBR.ADB0MUX"}

_cache = {}


def pin_table(dbroot, family, tiletype):
    """({input pin: (col offset, wire)}, {output pin: (col offset, wire)}) from bits.db."""
    key = (str(dbroot), family, tiletype)
    if key in _cache:
        return _cache[key]
    ins, outs = {}, {}
    p = Path(dbroot) / family / "tiledata" / tiletype / "bits.db"
    for line in p.read_text().splitlines():
        if not line.startswith(".fixed_conn "):
            continue
        dst, src = line.split()[1:3]
        if dst.endswith("_EBR"):                       # primitive input pin <- CIB wire
            pin = dst[1:-4]
            if pin in _FLAG_PINS:
                continue
            m = _WIRE.match(src)
            ins[pin] = (_OFF[m.group(1) or ""], m.group(2))
        elif src.endswith("_EBR"):                     # CIB wire <- primitive output pin
            pin = src[1:-4]
            if pin in _FLAG_PINS:
                continue
            m = _WIRE.match(dst)
            outs[pin] = (_OFF[m.group(1) or ""], m.group(2))
    _cache[key] = (ins, outs)
    return ins, outs


def _en(tiles, name, default):
    for t in tiles:
        if name in t:
            return t[name]
    return default


def decode_params(en1, en2, wd1, en0):
    """Primitive parameters from the three tiles of one EBR.  -> (kind, params, not_lifted)."""
    nl = []
    if en1.get("EBR.MODE") == "FIFO8KB":
        return "FIFO8KB", {}, ["EBR.MODE FIFO8KB (FIFO mode is not lifted)"]
    wr = int(en1.get("EBR.PDPW8KC.DATA_WIDTH_R", "9"))
    wb = int(en1.get("EBR.DP8KC.DATA_WIDTH_B", "9"))
    wa = 18 if en1.get("EBR.FIFO8KB.DATA_WIDTH_W") == "18" else int(en2.get("EBR.DP8KC.DATA_WIDTH_A", "9"))
    pdpw = wa == 18 or wr == 18
    if pdpw and wa not in (18, 1, 2, 4, 9):
        nl.append(f"write width {wa}")
    # decoded word is bit-reversed vs the Diamond string (corpus: "0b100" -> word 001)
    cs = lambda k: "0b" + wd1.get(f"EBR.CSDECODE_{k}", "111")[::-1]
    regs = (en1.get("EBR.REGMODE_A", "NOREG"), en1.get("EBR.REGMODE_B", "NOREG"))
    common = {
        "GSR": en1.get("EBR.GSR", "ENABLED"),
        "RESETMODE": en1.get("EBR.RESETMODE", "SYNC"),
        "ASYNC_RESET_RELEASE": en1.get("EBR.ASYNC_RESET_RELEASE", "SYNC"),
    }
    if pdpw:
        if regs[0] != regs[1]:
            nl.append(f"PDPW8KC has one REGMODE but A={regs[0]} B={regs[1]}")
        p = {"DATA_WIDTH_W": wa, "DATA_WIDTH_R": wr, "REGMODE": regs[1],
             "CSDECODE_W": cs("A"), "CSDECODE_R": cs("B"), **common}
        return "PDPW8KC", p, nl
    wm = lambda k: _en([en0, en1], f"EBR.DP8KC.WRITEMODE_{k}", "NORMAL")
    p = {"DATA_WIDTH_A": wa, "DATA_WIDTH_B": wb, "REGMODE_A": regs[0], "REGMODE_B": regs[1],
         "CSDECODE_A": cs("A"), "CSDECODE_B": cs("B"),
         "WRITEMODE_A": wm("A"), "WRITEMODE_B": wm("B"), **common}
    return "DP8KC", p, nl


def initvals(words):
    """INITVAL_00..1F hex strings from the 1024 physical 9-bit words.

    Layout from the vendor model DP8KC.v: v_MEM[9*k+i] = bit i of word k;
    v_MEM[18*j+i'] = init_value[20*j+i'] (i' < 18, j < 512); INITVAL_n = init_value[320n +: 320].
    """
    bits = 0
    for k, w in enumerate(words):
        bits |= (w & 0x1FF) << (9 * k)
    init = 0
    for j in range(512):
        init |= ((bits >> (18 * j)) & 0x3FFFF) << (20 * j)
    return {f"INITVAL_{n:02X}": "0x%080X" % ((init >> (320 * n)) & ((1 << 320) - 1))
            for n in range(32)}


def blocks(pc, lift, resolve, dbroot, family="MachXO2"):
    """One record per EBR1 tile: {block, wid, prim, params, not_lifted, pins}.

    pins: {primitive pin: {"dir": "in"|"out", "net": name|None, "inv": bool, "const": 0|1|None}}
    `resolve(row, col, wire)` -> net name or None.
    """
    rc_to_name = {rc: name for name, rc in lift.tile_rc.items()}
    out = []
    for (r, c1), ttype in sorted(pc.tile_type.items()):
        if not ttype.startswith("EBR1"):
            continue
        c0 = c1 - 1
        n0 = rc_to_name.get((r, c0), "")
        t0 = n0.split(":")[-1]
        if not t0.startswith("EBR0"):
            out.append({"block": f"R{r}C{c1}", "prim": None, "params": {}, "pins": {},
                        "not_lifted": [f"no EBR0 tile at R{r}C{c0} ({t0!r})"]})
            continue
        ins, outs = pin_table(dbroot, family, t0)
        en0, en1, en2 = (pc.enums.get((r, c1 + d), {}) for d in (-1, 0, 1))
        wd1 = pc.words.get((r, c1), {})
        kind, params, nl = decode_params(en1, en2, wd1, en0)
        pins = {}
        for pin, (off, wire) in {**ins}.items():
            net = resolve(r, c0 + off, wire)
            inv = en1.get(_INV_MUX.get(pin, ""), "") == "INV"
            const = None
            mux = _CONST_MUX.get(pin)
            if mux:
                v = en1.get(mux, f"{pin}")
                if v in ("0", "1"):
                    const, net = int(v), None
                elif v == "INV":
                    inv = True
            pins[pin] = {"dir": "in", "net": net, "inv": inv, "const": const}
        for pin, (off, wire) in outs.items():
            pins[pin] = {"dir": "out", "net": resolve(r, c0 + off, wire), "inv": False, "const": None}
        wid_s = wd1.get("EBR.WID")
        out.append({"block": f"R{r}C{c1}", "wid": int(wid_s, 2) if wid_s else 0, "prim": kind,
                    "params": params, "pins": pins, "not_lifted": nl})
    return out
