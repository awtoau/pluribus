#!/usr/bin/env python3.15t
"""Group parts into DIE CLASSES — which devices are the same silicon (#98).

WHY IT MATTERS TWICE
--------------------
1. **Coverage claims.** "Verified on 16 devices" means far less if those sixteen are
   nine dies.  The routing graph is a pure function of the die, so checking two
   parts that share one is running the same test twice.  Any per-device sweep should
   report die classes alongside the device count or it overstates its own variety.

2. **Usable capacity.** LFE5U-12F and -25F are one die, and the open flow already
   hands a 12F all 24,288 LUT4s with no patching -- confirmed on silicon at 82.9%
   utilisation (#98).  Wherever else that pattern holds, the same may be true.

METHOD
------
Two independent signals, both from data we did not author:

  * `frames` x `bits_per_frame` from Trellis `devices.json` -- the size of the
    configuration memory.  Different dies cannot share it.
  * the SHA-256 of `tilegrid.json` -- the full tile inventory and placement.
    Byte-identical means the database describes literally the same fabric.

Agreement between the two is what makes this more than a coincidence, and the
tilegrid hash is the stronger signal: two dies could coincidentally have equal
frame counts, but not an identical tile map.

PROVENANCE — why a tilegrid match is vendor evidence, not a copy
---------------------------------------------------------------
The obvious objection is that prjtrellis derived one family's database from
another, making identical files an artefact.  It does not: `tools/get_tilegrid_all.py`
runs **Diamond once per device** (`diamond.run(device, wire.v)`) and extracts the
tilegrid from Diamond's own output, for every device marked `fuzz=1` -- which is all
of MachXO2, MachXO3 and MachXO3D.  So an identical tilegrid means DIAMOND described
two parts with the same tile map.

The method also demonstrably discriminates, which is what rules out a degenerate
"everything matches" result: `LCMXO3D-4300` and `LCMXO3-4300` have the **same** frame
geometry (623 x 1560) and **different** tilegrids, the MachXO3D security block being
real fabric.  A test that separates those is not merely echoing frame counts.

On that basis, and cross-checked against frames x bits_per_frame from a separate
source, these are vendor-corroborated rather than hypotheses:

    LCMXO2-1200 == LCMXO3-1300      LCMXO2-4000 == LCMXO3-4300
    LCMXO2-2000 == LCMXO3-2100      LCMXO2-7000 == LCMXO3-6900

MachXO3 is the MachXO2 fabric with a different periphery.  Note Diamond keeps them
in separate device trees (`xo2c00` vs `xo3c00a`/`xo3c00f`) and only the MachXO2 tree
ships a `.bfd`, so the trees themselves cannot be diffed -- the tilegrid is the
comparison that works.

DO NOT READ CAPACITY OFF THE PART NUMBER
----------------------------------------
The marketing density in a part number does not track the LUT count across
families, and taking it at face value produced a wrong claim once already (an
apparent 3% of extra LUTs to "recover" on a MachXO2-1200 by treating it as a
MachXO3L-1300).  Counting bels instead:

    LCMXO2-1200   LUT4 = 1,280   FF = 1,280   640 slices
    LCMXO3-1300   LUT4 = 1,280   FF = 1,280   640 slices    <- identical
    LCMXO2-2000   LUT4 = 2,112   FF = 2,112   1,056 slices
    LCMXO3-2100   LUT4 = 2,112   FF = 2,112   1,056 slices   <- identical

The tier was renamed (1200 -> 1300, 2000 -> 2100, 4000 -> 4300, 7000 -> 6900) while
the fabric stayed put.  There is no spare capacity in the difference because there
is no difference.

OPEN, and it cuts against the corroboration above: Lattice's MachXO3L datasheet
quotes 1320 LUTs for the -1300, not 1280.  Either the datasheet counts by a
different definition, or prjtrellis's MachXO3 tilegrid was copied from MachXO2
after all -- `fuzz=1` says the extractor WOULD run Diamond per device, which is not
proof it did for the committed file.  The MachXO3D control favours the first
reading, but MachXO3D is a separate tree with its own `.bfd`, so it does not fully
transfer.  Settling it means running Diamond for LCMXO3L-1300 and extracting the
tilegrid ourselves.

WHAT IT STILL CANNOT SAY
------------------------
A shared die does not imply shared usable capacity.  Fusing, binning and speed grade
are orthogonal, and only hardware settles them -- see #98, where the ECP5 12F/25F
case was confirmed on silicon at 82.9% utilisation but an intermittent per-part
defect rate could only be bounded, not excluded.

Nothing here says the two parts are pin-compatible, electrically equivalent, or that
a bitstream for one will configure the other; the MachXO3 periphery differs even
where the fabric does not.

Nor does a shared die mean shared usable capacity: fusing, binning and speed grade
are orthogonal, and only hardware settles them (see #98's caveats).

    scripts/die_classes.py [--family ECP5] [--json PATH]

Logs to ./tmp/logs/die_classes.log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("die_classes")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "die_classes.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def tilegrid_hash(db, family, device):
    p = os.path.join(db, family, device, "tilegrid.json")
    if not os.path.isfile(p):
        return None, 0
    with open(p, "rb") as fh:
        data = fh.read()
    return hashlib.sha256(data).hexdigest()[:16], len(data)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default="", help="limit to one family")
    ap.add_argument("--json", default=str(REPO / "tmp/die_classes.json"))
    args = ap.parse_args()
    log = setup_logging()
    db = toolchain.trellis_dbroot()
    dj = json.load(open(os.path.join(db, "devices.json")))

    out = {}
    for family, fi in sorted(dj["families"].items()):
        if args.family and family != args.family:
            continue
        rows = []
        for device, info in sorted(fi["devices"].items()):
            h, size = tilegrid_hash(db, family, device)
            rows.append({
                "device": device,
                "frames": info.get("frames"),
                "bits_per_frame": info.get("bits_per_frame"),
                "idcode": info.get("idcode"),
                "tilegrid_sha": h,
                "tilegrid_bytes": size,
            })
        if not rows:
            continue

        # Group by the strongest available signal, falling back to geometry when a
        # family ships no tilegrid (so the absence is visible, not silently merged).
        groups = {}
        for r in rows:
            key = r["tilegrid_sha"] or f"geom:{r['frames']}x{r['bits_per_frame']}"
            groups.setdefault(key, []).append(r)

        log.info("==== %s: %d device(s) -> %d die class(es) ====", family,
                 len(rows), len(groups))
        for key, members in sorted(groups.items(),
                                   key=lambda kv: -len(kv[1])):
            first = members[0]
            shared = len(members) > 1
            log.info("  %s%d x %s  (%s x %s)",
                     "SHARED DIE: " if shared else "unique:     ",
                     len(members),
                     ", ".join(m["device"] for m in members),
                     first["frames"], first["bits_per_frame"])
            if shared:
                # The IDCODE is what still separates them, so show it: that is the
                # field a bitstream carries and the config engine checks.
                for m in members:
                    idc = m["idcode"]
                    idc = idc if isinstance(idc, str) else (
                        f"0x{idc:08x}" if idc is not None else "none")
                    log.info("        %-16s idcode %s", m["device"], idc)
        out[family] = {"devices": rows,
                       "die_classes": [[m["device"] for m in v]
                                       for v in groups.values()]}

    n_dev = sum(len(v["devices"]) for v in out.values())
    n_die = sum(len(v["die_classes"]) for v in out.values())
    log.info("")
    log.info("TOTAL: %d device(s) across %d die class(es)", n_dev, n_die)
    log.info("A per-device sweep of all %d parts exercises %d distinct fabrics.",
             n_dev, n_die)
    with open(args.json, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    log.info("results -> %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
