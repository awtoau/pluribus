#!/usr/bin/env python3.15t
"""Unbonded-pad states (#172): per build of the package experiment, every IO pad (sites of blocks 5 / 6 and the dedicated clock sites 60 / 61) crossed with
"bonded in the build's package" (pad has a ball in the package pkg ddb) and the decoded site class / unused-pin option; CRAM MIO_DATA_INVERT / MIO_OE_INVERT values likewise.

  python3.15t scripts/cycloneiv_pkgtest_unbonded.py [DIR ...]      (default: every tmp/pkgtest/*/bitstream.rbf)
Log: tmp/logs/cycloneiv_pkgtest_unbonded.log; per-build tables tmp/pkgtest/unbonded_<build>.tsv (local).
"""
import collections
import json
import logging
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from lifters.cycloneiv_clean import io_decode as ID  # noqa: E402
from lifters.cycloneiv_clean import io_fields as IF  # noqa: E402
from lifters.cycloneiv_clean import io_pins as IP  # noqa: E402
from lifters.cycloneiv_clean import pkgpad as K  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

log = logging.getLogger("pkgtest_unbonded")
CRAM_GROUPS = ("MIO_DATA_INVERT", "MIO_OE_INVERT")
# source: part-name package codes (Quartus device names) -> pin count of the pkg ddb
COUNT = {"CF23": 484, "DF27": 672, "DF31": 896}


def bonded_pads(count):
    pins = K.pins(count)
    return set(K.pin_pad(pins).values())


def site_classes(pm, dec, io, rbf, bonded):
    """-> [(site, pad index, bonded, class, detail, cram values)] for every pad that has a site."""
    raw = np.fromfile(rbf, np.uint8) if isinstance(rbf, (str, Path)) else np.frombuffer(rbf, np.uint8)
    val, _ = io.cff.read(raw.tobytes())
    bits = np.unpackbits(raw, bitorder="little")
    out = []
    for j, s in sorted(pm.pad_site.items()):
        cram = {}
        for g in CRAM_GROUPS:
            a = pm.chain.cram.get(s, {}).get(g)
            if a:
                r, jj, k = P.address_to_plane(np.asarray(a, np.int64))
                cram[g] = "".join(str(int(bits[o])) for o in P.rbf_bit_offset(r, jj, k).tolist())
        if s[0] in IP.CLK_BLOCKS:
            g = pm.clk[s]
            iost = "".join(str(int(val[a])) for a in g["iost"])
            clamp = "".join(str(int(val[a])) for a in g["clamp"])
            std = pm.used_input.get(len(iost), {}).get((iost, clamp))
            cls = "used" if std else ("unused" if (len(iost), iost, clamp) in pm.unused else "MISSING")
            det = f"clk iost={iost} clamp={clamp}"
        else:
            r = dec.decode(s, ID.site_vector(pm.chain, val, s))
            cls = r["class"]
            det = "+".join(r.get("unused_options", [])) if cls == "unused" else ""
            if cls in ("MISSING",):
                det = json.dumps(r.get("raw"), sort_keys=True)
        out.append((s, j, j in bonded, cls, det, cram))
    return out


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pkgtest_unbonded.log", "w"), logging.StreamHandler()])
    io = T.Io()
    dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
    pm = IP.PinMap(io, dec)
    dirs = [Path(a) for a in sys.argv[1:]] or sorted((REPO / "tmp" / "pkgtest").glob("*/bitstream.rbf"))
    for rbf in dirs:
        name = rbf.parent.name
        pkg = re.search(r"(CF23|DF27|DF31)", name)[1]
        rows = site_classes(pm, dec, io, rbf, bonded_pads(COUNT[pkg]))
        ct = collections.Counter((b, c, d) for _, _, b, c, d, _ in rows if c != "MISSING")
        log.info("== %s (%d pads, %d bonded)", name, len(rows), sum(1 for r in rows if r[2]))
        for (b, c, d), n in sorted(ct.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            log.info("   bonded=%-5s %-8s %-30s %d", b, c, d, n)
        for r in rows:
            if r[3] == "MISSING":
                log.info("   MISSING bonded=%s site %s %s", r[2], r[0], r[4][:160])
        cr = collections.Counter((b, c, d, tuple(sorted(cm.items()))) for _, _, b, c, d, cm in rows)
        shown = collections.Counter()
        for (b, c, d, cm), n in cr.items():
            shown[(b, c == "unused" and d, cm)] += n
        for k, n in sorted(shown.items(), key=lambda kv: str(kv[0])):
            log.info("   CRAM bonded=%s unused-option=%s %s : %d", *k, n)


if __name__ == "__main__":
    main()
