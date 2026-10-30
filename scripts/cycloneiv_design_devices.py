#!/usr/bin/env python3.15t
"""reference/design_devices.tsv: device group of every corpus/cycloneiv design (scope rule, Dan 2026-10-30).

  python3.15t scripts/cycloneiv_design_devices.py        # log: tmp/logs/cycloneiv_design_devices.log

Columns: design, device (design.toml `device`; empty = no key), rcf_device (routing.rcf, if built), package_pins (Quartus device.db), group.
Groups: primary (EP4CGX150DF31, F896) | other-package (other EP4CGX150) | other-die (EP4CGX110) | no-device-key (early designs; default Cyclone IV E).
The tracked TSV is the record of the pre-trim corpus (16,865 designs): re-running after a corpus trim drops the removed designs.
"""
import glob
import logging
import os
import re
import sys
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import pkgpad as K  # noqa: E402

OUT = os.path.join(REPO, "reference", "design_devices.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_design_devices.log")


def group(dev):
    if not dev:
        return "no-device-key"
    if dev.startswith("EP4CGX150DF31"):
        return "primary"
    return "other-package" if dev.startswith("EP4CGX150") else "other-die" if dev.startswith("EP4CGX110") else "other-device"


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    pk, counts, rows = {}, {}, []
    for d in sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "*", ""))):
        n = os.path.basename(d.rstrip("/"))
        try:
            dev = tomllib.load(open(d + "design.toml", "rb")).get("device", "")
        except (OSError, ValueError):
            dev = ""
        rcf = ""
        if os.path.exists(d + "routing.rcf"):
            m = re.search(r"device = (\w+);", open(d + "routing.rcf").read(600))
            rcf = m[1] if m else ""
        key = dev or rcf
        if key and key not in pk:
            try:
                pk[key] = str(K.package_pins(key))
            except ValueError:
                pk[key] = ""
        g = group(dev)
        counts[g] = counts.get(g, 0) + 1
        rows.append((n, dev, rcf, pk.get(key, ""), g))
    with open(OUT, "w") as f:
        f.write("design\tdevice\trcf_device\tpackage_pins\tgroup\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    logging.info("wrote %s rows %d groups %s", OUT, len(rows), counts)


if __name__ == "__main__":
    main()
