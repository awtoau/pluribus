#!/usr/bin/env python3.15t
"""Match an unknown Cyclone III/IV image to a die: decompress it (structural checks), then list the
quartus_cpf pairs (cycloneiv_pairs.py) with the same geometry and the option-lane bits that differ.
Read-only on the image; the decompressed copy goes to tmp/cycloneiv/<stem>.rbf.

  python3.15t scripts/cycloneiv_die_match.py IMAGE [--pairs tmp/cycloneiv/pairs]
Log: tmp/logs/cycloneiv_die_match.log
"""
import argparse
import logging
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_decompress as cd  # noqa: E402


def bits(x):
    return [i for i in range(40) if x >> i & 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--pairs", default=str(REPO / "tmp" / "cycloneiv" / "pairs"))
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_die_match.log", "w")])
    log = logging.getLogger()
    img = pathlib.Path(a.image)
    info = {}
    try:
        out = cd.decompress(img.read_bytes(), info)
    except cd.FormatError as e:
        log.info("%s: FAIL %s; found so far %s", img.name, e, info)
        return 2
    dst = REPO / "tmp" / "cycloneiv" / (img.stem + ".rbf")
    dst.write_bytes(out)
    log.info("%s: decodes; all %d CRAM frame CRCs valid; %s", img.name, info["cram_frames"],
             {k: info[k] for k in ("frame", "periphery_frames", "cram_frames", "length",
                                   "leftover_nibbles", "length_field", "trimmed_ff_tail") if k in info})
    me = [int(x, 16) for x in info["lanes"]]
    for p in sorted(pathlib.Path(a.pairs).glob("*.rbf")):
        if p.name.endswith(".c.rbf"):
            continue
        u = p.read_bytes()
        if len(u) != len(out):
            continue
        h = cd.parse(u)
        if h["frame"] != info["frame"]:
            continue
        diff = {n: bits(int(h["lanes"][n], 16) ^ me[n]) for n in range(8)
                if n != 2 and int(h["lanes"][n], 16) != me[n]}
        diff[2] = bits((int(h["lanes"][2], 16) ^ me[2]) & 0xFFFF)  # lane 2 bits 16.. = length
        same_periph = u[32 + info["frame"]:info["cram_start"]] == out[32 + info["frame"]:info["cram_start"]]
        log.info("  same geometry: %-26s lane bits differing (lane: bits) %s; periphery identical %s",
                 p.stem, {k: v for k, v in diff.items() if v}, same_periph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
