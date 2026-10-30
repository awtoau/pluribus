#!/usr/bin/env python3.15t
"""Cross-check our decoded package tables (pkgpad.pins / pkgpad.pads) ball by ball against the official pin list (#168, #172).

Per package: balls in both / only in the official file (missing) / only in ours (extra); of the common balls, function token sets that differ (wrong).
Log: tmp/logs/cycloneiv_clean_pin_xcheck.log; local table tmp/pin_xcheck/<pkg>.tsv.
"""
import logging
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("PLURIBUS_REPO") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(REPO))
from lifters.cycloneiv_clean import pinfile as F  # noqa: E402
from lifters.cycloneiv_clean import pkgpad as K  # noqa: E402

log = logging.getLogger("pin_xcheck")


def ours_tokens(name, fn):
    toks = {t.strip() for t in (fn if fn is not None else name).split(",") if t.strip()}
    toks.discard("IO")
    return toks


def check(package):
    count = F.PACKAGES[package][1]
    pins, pads = K.pins(count), K.pads()
    pp = K.pin_pad(pins)
    ours = {p["strs"][0]: ours_tokens(p["strs"][1], pads[pp[i]]["strs"][4] if i in pp else None) for i, p in enumerate(pins)}
    off = {b: F.functions(r) for b, r in F.by_ball(package).items()}
    both = set(ours) & set(off)
    wrong = sorted(b for b in both if ours[b] != off[b])
    res = {"official": len(off), "ours": len(ours), "matched": len(both) - len(wrong), "missing": len(set(off) - set(ours)),
           "extra": len(set(ours) - set(off)), "wrong": len(wrong)}
    out = REPO / "tmp" / "pin_xcheck"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{package}.tsv", "w") as fh:
        fh.write("ball\tofficial\tours\tstatus\n")
        for b in sorted(set(ours) | set(off)):
            st = "wrong" if b in wrong else "matched" if b in both else "missing" if b in off else "extra"
            fh.write(f"{b}\t{','.join(sorted(off.get(b, ())))}\t{','.join(sorted(ours.get(b, ())))}\t{st}\n")
    return res, [(b, sorted(off[b]), sorted(ours[b])) for b in wrong]


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_clean_pin_xcheck.log", "w"), logging.StreamHandler()])
    bad = 0
    for pkg in F.PACKAGES:
        res, wrong = check(pkg)
        den = res["matched"] + res["missing"] + res["extra"] + res["wrong"]
        log.info("%s: %s  headline %d / %d", pkg, res, res["matched"], den)
        for w in wrong[:20]:
            log.info("  wrong %s official=%s ours=%s", *w)
        bad += res["missing"] + res["extra"] + res["wrong"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
