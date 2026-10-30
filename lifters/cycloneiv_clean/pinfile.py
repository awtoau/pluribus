"""Official EP4CGX150 pin list (Altera "Pin Information", v1.1) parsed from the vendor store: ball -> name / optional / config function per package.  Vendor-derived only (#168, #172).

- File: `~/vendors/altera/cyclone-iv/ep4cgx150-pinout.txt` (tab separated, latin-1, manifest `~/vendors/altera/README.md`); columns F896 / F672 / F484 = ball per package.
- Columns 8..15 = DQS / DQ names per package and width; DQS and DPCLK tokens are kept as functions; DQ<n> / DM<n> data names vary per package and width and are not in the pad ddb.
- A user-I/O row has name `IO` (or `CLKIOn`, `REFCLKnx`) and the optional function in column 3; dedicated rows (GND, VCC*, config, GXB) have their own name.
"""
import os

PATH = os.path.expanduser("~/vendors/altera/cyclone-iv/ep4cgx150-pinout.txt")
# source: column header row of the pin file ("F896 F672 F484" = columns 5..7); package pin counts = ball counts of the columns
PACKAGES = {"F896": (5, 896), "F672": (6, 672), "F484": (7, 484)}


def rows(path=PATH):
    """-> [{bank, vref, name, optional, config, balls: {pkg: ball}}] in file order (header and notes skipped)."""
    out, started = [], False
    for line in open(path, encoding="latin-1"):
        c = line.rstrip("\r\n").split("\t")
        c += [""] * (16 - len(c))
        if c[0] == "Bank Number":
            started = True
            continue
        if not started or not c[2]:
            continue
        balls = {p: c[i] for p, (i, _n) in PACKAGES.items() if c[i]}
        if balls:
            out.append({"bank": c[0], "vref": c[1], "name": c[2], "optional": c[3].strip('"'), "config": c[4].strip('"'), "dq": c[8:16], "balls": balls})
    return out


def functions(r):
    """Function token set of a row: name (unless plain IO) + optional + config functions."""
    toks = set()
    if r["name"] != "IO":
        toks.add(r["name"])
    for s in (r["optional"], r["config"]):
        toks.update(t.strip() for t in s.split(",") if t.strip())
    for s in r["dq"]:
        toks.update(t.strip().strip('"') for t in s.split(",") if t.strip().strip('"').startswith(("DQS", "DPCLK")))
    return toks


def by_ball(package):
    """-> {ball: row} for one package ('F896' | 'F672' | 'F484')."""
    return {r["balls"][package]: r for r in rows() if package in r["balls"]}


def plain_io(r):
    """A general-purpose user I/O row: name IO, no config function, no PLL / clock-out role."""
    return r["name"] == "IO" and not r["config"] and "CLK" not in r["optional"]
