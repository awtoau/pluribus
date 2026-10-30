"""Package inference from a Cyclone IV GX (EP4CGX150) bitstream (#172).  Vendor-derived rule, no fitted constants.

Rule (docs/cycloneiv-clean-io.md "Package"): an IO pad with no ball in the build's package is written as the ground / unspecified unused state
(strengths all ones); bonded pads never are.  Package P is consistent with a bitstream iff
  - no ground-state IO site is bonded in P (contradiction), no used IO site is unbonded in P, and
  - every IO pad unbonded in P is in the ground state (or a MISSING site whose strength groups are closer to the ground vector than to the tri-state vector).
Exactly one consistent package -> inferred; none or several -> None (refuse to guess).  "exact": the ground set equals the unbonded set.
Dedicated clock pads are not tested (their unused state does not depend on bonding).
"""
import re

import numpy as np

from . import io_decode as ID
from . import io_pins as IP
from . import pkgpad as K

# source: pkg ddb names ddb_stingray4fbga<N>_pkg.ddb (N = DEV_PIN count = part.pin_count of device.db); package names from the Altera part names (CF23 F484, DF27 F672, DF31 F896)
PACKAGES = {"F484": 484, "F672": 672, "F896": 896}
STRENGTHS = ("MIO_SET_PULLUP_STRENGTH", "MIO_SET_PULLDOWN_STRENGTH")


def part_package(device):
    """Package name of an Altera part name (EP4CGX150DF27I7 -> F672) from device.db part.pin_count."""
    n = K.package_pins(device)
    return next(p for p, c in PACKAGES.items() if c == n)


def bonded_pads(count):
    return set(K.pin_pad(K.pins(count)).values())


def site_states(pm, dec, raw):
    """{pad index: {"site", "cls", "ground"}} for every Row / Column I/O pad: ground = ground-state unused option or a MISSING site closer to the ground strength vector."""
    val, _ = pm.io.cff.read(bytes(raw))
    out = {}
    for j, s in pm.pad_site.items():
        if s[0] in IP.CLK_BLOCKS:
            continue
        r = dec.decode(s, ID.site_vector(pm.chain, val, s))
        ground = r["class"] == "unused" and "gnd" in "+".join(r.get("unused_options", []))
        if r["class"] == "MISSING":
            bits = "".join(r["raw"][g] for g in STRENGTHS)
            ground = bits.count("1") * 2 > len(bits)
        out[j] = {"site": s, "cls": r["class"], "ground": bool(ground), "strict": r["class"] == "unused" and ground}
    return out


def infer_package(states):
    """-> {"package": name | None, "exact": bool, "per_package": {name: counts}, "reason": str}."""
    io_pads = set(K.io_site_pads(K.pads()).values())
    ground = {j for j, v in states.items() if v["ground"]}
    used = {j for j, v in states.items() if v["cls"] == "used"}
    per, ok = {}, []
    for name, count in PACKAGES.items():
        unb = io_pads - bonded_pads(count)
        c = {"unbonded": len(unb), "ground_unbonded": len(ground & unb), "ground_bonded": len(ground - unb), "used_unbonded": len(used & unb),
             "unbonded_not_ground": len(unb - ground)}
        c["consistent"] = c["ground_bonded"] == 0 and c["used_unbonded"] == 0 and c["unbonded_not_ground"] == 0
        c["exact"] = c["consistent"] and ground == unb
        per[name] = c
        if c["consistent"]:
            ok.append(name)
    if len(ok) == 1:
        return {"package": ok[0], "exact": per[ok[0]]["exact"], "per_package": per, "reason": "unique consistent package"}
    return {"package": None, "exact": False, "per_package": per,
            "reason": "no consistent package" if not ok else "ambiguous: " + ",".join(ok)}


def infer(pm, dec, raw):
    st = site_states(pm, dec, raw)
    r = infer_package(st)
    r["ground_sites"] = sum(v["ground"] for v in st.values())
    r["ground_strict"] = sum(v["strict"] for v in st.values())
    return r


def infer_bytes(raw):
    """Self-contained entry (builds the Io / decoder / pin map): rbf bytes -> infer() result."""
    import json

    from . import io_fields as IF
    from . import tracer as T
    io = T.Io()
    dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
    return infer(IP.PinMap(io, dec), dec, raw)
