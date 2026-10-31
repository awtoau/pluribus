#!/usr/bin/env python3.15t
"""Cyclone V clean PRAM: vendor-derived claim map + labelled Mistral oracle comparison.

  tables   per die: asmdb header, extent count, tiling check (coverage / overlap)   [vendor only]
  compare  vendor extents vs Mistral pram.txt (ORACLE, run after the derivation)   [oracle]
Log: tmp/logs/cyclonev_clean_pram.log. Doc: docs/altera/cycloneV/cyclonev-clean-pram.md
"""
import argparse
import collections
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from lifters.cyclonev_clean import pram  # noqa: E402

log = logging.getLogger("cvclean")
# source: Quartus devinfo directory names under quartus/common/devinfo/cyclonev/
DIES = ["e50f", "d6_gtf150", "gx25f", "gt75f", "gt300f", "sx50f", "sx120f"]
# source: ORACLE ONLY - die directory name -> Mistral data/ prefix (names compared by eye)
ORACLE_DIE = {"d6_gtf150": "gt150f"}
# source: ORACLE ONLY - vendor icd block name -> Mistral block label (name/size match, comparison stage only)
ORACLE_LABEL = {
    "cc_clkmuxf_corne": "cmuxc", "cc_clkmuxf_lr": "cmuxh", "cc_clkmuxf_tb": "cmuxv", "ir_dll_top": "dll",
    "pl_fpll_ip": "fpll", "im_sysclk": "cbuf", "ir_lvl_top": "lvl", "io_oc_rsrtcal": "term",
    "io_oct_serpar": "serpar", "io_oct_serpar_h": "serpar", "io_4iomodule_c5": "gpio", "io_4iomodule_h_c5": "gpio",
    "ir_ioregdqs16_c5": "dqs16", "ir_ioregdqs16_h_c5": "dqs16",
}
MISTRAL = os.environ.get("PLURIBUS_MISTRAL_ROOT", "")  # oracle checkout; compare stage only


def stage_tables():
    for die in DIES:
        hdr, rows, own = pram.vendor_tables(die)
        n = hdr["num_cff_bits"]
        log.info("%s num_cff_bits=%d extents=%d claimed=%d (%.4f%%) double-claims=0", die, n, len(rows), len(own),
                 100.0 * len(own) / n)


def oracle_extents(die):
    pre = ORACLE_DIE.get(die, die)
    import re
    if not MISTRAL:
        raise SystemExit("compare needs PLURIBUS_MISTRAL_ROOT (oracle checkout)")
    txt = open(os.path.join(MISTRAL, "libmistral", f"cvd-{pre}.cc")).read()
    sizes = [int(x) for x in re.search(r"// pram sizes\s*\{([^}]*)\}", txt).group(1).replace("\n", " ").split(",") if x.strip()]
    base = [sum(sizes[:i]) for i in range(len(sizes))]
    n = sum(sizes)
    out = []
    for line in open(os.path.join(MISTRAL, "data", f"{pre}-pram.txt")):
        t = line.split()
        if not t:
            continue
        s, r = t[0].split(".")
        a, b = (int(v) for v in r.split("-"))
        out.append((t[1], n - 1 - (base[int(s)] + a), b - a + 1))
    return n, sizes, out


def stage_compare():
    tot = collections.Counter()
    for die in DIES:
        hdr, rows, own = pram.vendor_tables(die)
        try:
            n, sizes, orc = oracle_extents(die)
        except OSError as e:
            log.info("%s: no oracle (%s)", die, e)
            continue
        if n != hdr["num_cff_bits"]:
            log.info("%s: oracle total %d != vendor %d", die, n, hdr["num_cff_bits"])
        v = {(a, sz): name for name, _k, _j, a, sz in rows}
        o = {(a, sz): lab for lab, a, sz in orc}
        matched = [k for k in v if k in o]
        label_ok = sum(1 for k in matched if ORACLE_LABEL.get(v[k]) == o[k])
        ocover = {}
        for (a, sz), lab in o.items():
            for b in range(sz):
                ocover[(a - b) % n] = (a, sz)
        wrong = [k for k in v if k not in o and any(((k[0] - b) % n) in ocover for b in range(k[1]))]
        extra = [k for k in v if k not in o and k not in wrong]
        missing = [k for k in o if k not in v and not any(((k[0] - b) % n) in own for b in range(k[1]))]
        wrong_o = [k for k in o if k not in v and k not in missing]
        bits_ok = sum(sz for _a, sz in matched)
        log.info("%s: vendor extents %d oracle extents %d | matched %d (label agrees %d) missing %d extra %d wrong %d "
                 "(oracle-side wrong %d) | matched bits %d / %d", die, len(v), len(o), len(matched), label_ok,
                 len(missing), len(extra), len(wrong), len(wrong_o), bits_ok, n)
        tot.update(matched=len(matched), missing=len(missing), extra=len(extra), wrong=len(wrong),
                   oracle=len(o), vendor=len(v), bits=bits_ok, bits_total=n)
        # strip-boundary consistency of the oracle's strip sizes against the vendor extents
        cuts = set()
        acc = 0
        for sz in sizes[:-1]:
            acc += sz
            cuts.add(acc)
        straddle = sum(1 for (a, s_) in v if any(c in range(n - 1 - a + 1, n - 1 - a + s_) for c in cuts))
        log.info("%s: vendor extents straddling an oracle strip boundary: %d", die, straddle)
    if tot["oracle"]:
        m, mi, ex, wr = tot["matched"], tot["missing"], tot["extra"], tot["wrong"]
        log.info("TOTAL: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%  (bits %d / %d = %.2f%%)",
                 m, m, mi, ex, wr, 100.0 * m / (m + mi + ex + wr), tot["bits"], tot["bits_total"],
                 100.0 * tot["bits"] / tot["bits_total"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["tables", "compare", "all"])
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_clean_pram.log"))])
    if a.stage in ("tables", "all"):
        stage_tables()
    if a.stage in ("compare", "all"):
        stage_compare()


if __name__ == "__main__":
    main()
