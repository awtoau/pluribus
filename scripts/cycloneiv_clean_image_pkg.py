#!/usr/bin/env python3.15t
"""Which package is the third-party EP4CGX150 image built for? (#172)  IO-site classes of the image against each package's bonded-pad set.

  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_image_pkg.py
Evidence (experiment tmp/pkgtest, docs/cycloneiv-clean-io.md): a pad with no ball in the build's package is written as the "driving ground = unspecified" state
(strengths all ones, CRAM MIO_DATA_INVERT 11 / MIO_OE_INVERT 0); a bonded unused pad gets the RESERVE_ALL_UNUSED_PINS option state (weak pull-up / tri-state).
Per package: image sites in the ground state that are bonded (contradiction), unbonded pads whose image state is not ground (contradiction), used sites on unbonded pads.
Counts only in the log (no path, name or hash): tmp/logs/cycloneiv_clean_image_pkg.log; local per-site table tmp/cycloneiv_clean/image_pkg_sites.tsv.
"""
import collections
import json
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_decompress as cd  # noqa: E402
import cycloneiv_pkgtest_unbonded as U  # noqa: E402
from lifters.cycloneiv_clean import io_decode as ID  # noqa: E402
from lifters.cycloneiv_clean import io_fields as IF  # noqa: E402
from lifters.cycloneiv_clean import io_pins as IP  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

log = logging.getLogger("image_pkg")


def main():
    img = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not img:
        raise SystemExit("env PLURIBUS_DJI_IMAGE not set")
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_clean_image_pkg.log", "w"), logging.StreamHandler()])
    rbf = cd.decompress(open(img, "rb").read(), {})
    io = T.Io()
    dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
    pm = IP.PinMap(io, dec)
    rows = {}
    for pkg, count in U.COUNT.items():
        rows[pkg] = U.site_classes(pm, dec, io, bytes(rbf), U.bonded_pads(count))
    base = rows["DF31"]            # bonded flag is overwritten per package below; class / detail / cram do not depend on it
    log.info("image sites: %d pads with a site", len(base))
    cls = collections.Counter((c, d if c == "unused" else "") for _, _, _, c, d, _ in base)
    log.info("image classes: %s", dict(cls))
    out = REPO / "tmp" / "cycloneiv_clean"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "image_pkg_sites.tsv", "w") as fh:
        fh.write("block\tsite\tpad\tclass\tdetail\tcram\tbonded_F484\tbonded_F672\tbonded_F896\n")
        for i, (s, j, _b, c, d, cm) in enumerate(base):
            fh.write(f"{s[0]}\t{s[1]}\t{j}\t{c}\t{d[:60]}\t{cm}\t" + "\t".join(str(rows[p][i][2]) for p in ("CF23", "DF27", "DF31")) + "\n")
    for pkg in U.COUNT:
        r = rows[pkg]
        unb = [x for x in r if not x[2]]
        ct = collections.Counter((x[2], x[3], x[4] if x[3] == "unused" and not x[4].startswith("clk") else "") for x in r)
        gnd_bonded = sum(1 for x in r if x[2] and x[3] == "unused" and x[4] == "gnd+unspec")
        gnd_unbonded = sum(1 for x in unb if x[3] == "unused" and x[4] == "gnd+unspec")
        non_gnd_unbonded = [x for x in unb if not (x[3] == "unused" and x[4] == "gnd+unspec")]
        used_unbonded = sum(1 for x in unb if x[3] == "used")
        log.info("%s: pads with site %d, unbonded %d | ground-state sites bonded %d (contradiction), ground-state sites unbonded %d | unbonded pads not ground %d "
                 "(of which used %d, clock-pad unused %d, MISSING %d, fixed %d) | classes by (bonded, class, option): %s",
                 pkg, len(r), len(unb), gnd_bonded, gnd_unbonded, len(non_gnd_unbonded), used_unbonded,
                 sum(1 for x in non_gnd_unbonded if x[3] == "unused"), sum(1 for x in non_gnd_unbonded if x[3] == "MISSING"), sum(1 for x in non_gnd_unbonded if x[3] == "fixed"), dict(ct))


if __name__ == "__main__":
    main()
