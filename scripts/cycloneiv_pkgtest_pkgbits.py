#!/usr/bin/env python3.15t
"""Package-dependent CFF bits outside the IO sites (#172): bits whose value is constant within a package over every build of tmp/pkgtest (all designs, speed grades) and differs between packages.

  python3.15t scripts/cycloneiv_pkgtest_pkgbits.py
Each bit is attributed to its asmdb group(s) (block type, site, group name).  Log: tmp/logs/cycloneiv_pkgtest_pkgbits.log
"""
import collections
import logging
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_pkgtest_diff as D  # noqa: E402

log = logging.getLogger("pkgtest_pkgbits")
IO_BLOCKS = (5, 6, 60, 61)      # source: asmdb block types of the IO sites (docs/cycloneiv-clean-io.md)


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pkgtest_pkgbits.log", "w"), logging.StreamHandler()])
    own = D.Owners()
    by_pkg = collections.defaultdict(list)
    for p in sorted((REPO / "tmp" / "pkgtest").glob("*/bitstream.rbf")):
        by_pkg[re.search(r"(CF23|DF27|DF31)", p.parent.name)[1]].append(own.cff.read(str(p))[0])
    arr = {k: np.array(v) for k, v in by_pkg.items()}
    log.info("builds per package: %s", {k: len(v) for k, v in arr.items()})
    const = {k: (v.min(0) == v.max(0)) for k, v in arr.items()}
    allc = np.all([const[k] for k in arr], axis=0)
    first = {k: arr[k][0] for k in arr}
    differ = allc & ((first["CF23"] != first["DF27"]) | (first["DF27"] != first["DF31"]))
    idx = np.nonzero(differ)[0]
    log.info("CFF bits constant within each package and different between packages: %d", len(idx))
    io = collections.Counter()
    for i in idx:
        ow = own.owner.get(int(i), [])
        if ow and ow[0][0] in IO_BLOCKS:
            io[(ow[0][0], ow[0][2])] += 1
            continue
        log.info("  cff %d CF23=%d DF27=%d DF31=%d owners %s", i, first["CF23"][i], first["DF27"][i], first["DF31"][i], ow[:2])
    log.info("IO-block bits among them (by block type, group): %s", dict(io))


if __name__ == "__main__":
    main()
