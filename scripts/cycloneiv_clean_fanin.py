#!/usr/bin/env python3.15t
"""Fan-in conflicts of the clean tracer on gx150_rb_000..009 (#165 errata E-L2): destination nodes with > 1 programmed driver, per variant.

  python3.15t scripts/cycloneiv_clean_fanin.py
Log: tmp/logs/cycloneiv_clean_fanin.log.  Reads lifters/cycloneiv_clean/tracer.py as is (no rule edits here).
"""
import logging
import os
import sys

import numpy as np

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_fanin.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
log = logging.getLogger("fanin")


def main():
    st = T.Static()
    ed = st.edst.astype(np.int64)
    tot = {}
    for i in range(10):
        d = os.path.join(REPO, "corpus", "cycloneiv", f"gx150_rb_{i:03d}")
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        for v, e in st.fire(bits, workers=4).items():
            cnt = np.bincount(ed[np.asarray(e)])
            t = tot.setdefault(v, [0, 0])
            t[0] += int((cnt > 1).sum())
            t[1] += int((cnt > 0).sum())
            log.info("%s %s dst_nodes=%d conflicts=%d", os.path.basename(d), v, int((cnt > 0).sum()), int((cnt > 1).sum()))
    for v, (c, n) in tot.items():
        log.info("TOTAL %s conflicts %d / %d dst nodes = %.2f %%", v, c, n, 100.0 * c / max(n, 1))


if __name__ == "__main__":
    main()
