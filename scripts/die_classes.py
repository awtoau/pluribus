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

WHAT IT CANNOT SAY
------------------
That two parts share a die in the DATABASE is strictly a statement about the model.
For ECP5 it is corroborated by the vendor's own package files being byte-identical
(Diamond's `LFE5U-12F_CABGA256.con` vs `..._25F_...`) and by hardware, but this
script only reads Trellis.  Treat a match as a strong hypothesis, and check the
vendor's `.con` files before acting on a family this has not been confirmed for.

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
