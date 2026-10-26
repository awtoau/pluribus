"""MachXO2 distributed RAM -> DPR16X4C primitive record (issue #127).

One RAMW slice (C) + two DPRAM slices (A, B) in a PLC tile are a DPR16X4C.  The pin table below is
the Diamond oracle's (scripts/dpram_oracle.py, results in docs/machxo2-diamond-oracle.md):

  DI0..DI3  = wires A5..D5      WAD0..WAD3 = wires A4..D4      WRE = LSR2     WCK = CLK2
  RAD0..RAD3 = wires A..D of the DPRAM slices' LUT inputs (A0..D0, A1..D1, A2..D2, A3..D3: one net)
  DO0..DO3  = wires F0..F3      INITVAL nibble a = {B.K1, B.K0, A.K1, A.K0} bit a of the 16-bit INITs
"""

_DI = ("A5", "B5", "C5", "D5")
_WAD = ("A4", "B4", "C4", "D4")
_DO = ("F0", "F1", "F2", "F3")
_KEYS = (("A", 0), ("A", 1), ("B", 0), ("B", 1))      # (slice, K) holding DO0..DO3


def cells(pc, resolve):
    """[{name, prim, params, pins, not_lifted}] for each RAMW tile."""
    res = []
    for (r, c, sl), en in sorted(pc.slice_enum.items()):
        if en.get("MODE") != "RAMW":
            continue
        nl = []
        if sl != "C" or any(pc.slice_enum.get((r, c, x), {}).get("MODE") != "DPRAM" for x in "AB"):
            nl.append("RAMW not in the A/B DPRAM + C RAMW arrangement")
        for x in "ABC":
            for k in ("WREMUX", "WCKMUX"):
                v = pc.slice_enum.get((r, c, x), {}).get(k)
                if v not in (None, "WRE", "WCK", "#OFF"):
                    nl.append(f"SLICE{x}.{k}={v}")
        for k, v in pc.enums.get((r, c), {}).items():
            if k in ("LSR2.LSRMUX", "CLK2.CLKMUX") and v == "INV":
                nl.append(f"{k}={v}: write-port polarity")
        pins = {}
        for i in range(4):
            pins[f"DI{i}"] = {"dir": "in", "net": resolve(r, c, _DI[i])}
            pins[f"WAD{i}"] = {"dir": "in", "net": resolve(r, c, _WAD[i])}
            pins[f"DO{i}"] = {"dir": "out", "net": resolve(r, c, _DO[i])}
        pins["WRE"] = {"dir": "in", "net": resolve(r, c, "LSR2")}
        pins["WCK"] = {"dir": "in", "net": resolve(r, c, "CLK2")}
        for i, letter in enumerate("ABCD"):
            cands = [resolve(r, c, f"{letter}{j}") for j in range(4)]
            nets = {n for n in cands if n}
            if len(nets) > 1:
                nl.append(f"RAD{i}: DPRAM LUT inputs carry different nets {sorted(nets)}")
            pins[f"RAD{i}"] = {"dir": "in", "net": next((n for n in cands if n), None)}
        mem = [0] * 16
        for bit, (sl2, k) in enumerate(_KEYS):
            init = pc.lut_init.get((r, c, sl2, str(k)), "0" * 16)
            for a in range(16):
                if int(init, 2) >> a & 1:
                    mem[a] |= 1 << bit
        initval = "0x" + "".join(f"{m:X}" for m in reversed(mem))
        res.append({"name": f"R{r}C{c}_DPRAM", "prim": "DPR16X4C", "params": {"initval": initval},
                    "pins": pins, "not_lifted": nl})
    return res
