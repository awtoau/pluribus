#!/usr/bin/env python3.15t
"""decompress(compressed) == quartus_cpf uncompressed, on every pair from cycloneiv_pairs.py;
uncompressed input must pass through unchanged.  Prints the per-die geometry table.

  python3.15t scripts/cycloneiv_decompress_check.py [--dir tmp/cycloneiv/pairs] [--workers 8]
Log: tmp/logs/cycloneiv_decompress_check.log
"""
import argparse
import logging
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_decompress as cd  # noqa: E402


def check(c_path):
    u_path = c_path.with_name(c_path.name[:-len(".c.rbf")] + ".rbf")
    c, u = c_path.read_bytes(), u_path.read_bytes()
    row = {"stem": u_path.stem, "u_len": len(u), "c_len": len(c)}
    try:
        ic, iu = {}, {}
        oc = cd.decompress(c, ic)
        ou = cd.decompress(u, iu)
    except cd.FormatError as e:
        row["error"] = str(e)
        return row
    row.update(ok_c=oc == u, ok_u=ou == u, frame=ic["frame"], periphery=ic["periphery_frames"],
               cram=ic["cram_frames"], left=ic["leftover_nibbles"],
               lf_c=4 * len(c) - ic["length_field"], lf_u=4 * len(u) - iu["length_field"],
               lane1=ic["lanes"][1], lane3=ic["lanes"][3])
    if not row["ok_c"]:
        n = min(len(oc), len(u))
        row["first_diff"] = next((i for i in range(n) if oc[i] != u[i]), n)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(REPO / "tmp" / "cycloneiv" / "pairs"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_decompress_check.log", "w")])
    log = logging.getLogger()
    pairs = sorted(pathlib.Path(a.dir).glob("*.c.rbf"))
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(check, pairs))
    good_c = good_u = 0
    geo = {}
    for r in rows:
        if "error" in r:
            log.info("%-30s ERROR %s", r["stem"], r["error"])
            continue
        good_c += r["ok_c"]
        good_u += r["ok_u"]
        log.info("%-30s c %s u %s  F %4d periph %2d cram %5d  len %8d / %8d  4L-field c %d u %d  left %d%s",
                 r["stem"], "OK " if r["ok_c"] else "BAD", "OK " if r["ok_u"] else "BAD", r["frame"],
                 r["periphery"], r["cram"], r["c_len"], r["u_len"], r["lf_c"], r["lf_u"], r["left"],
                 f"  first diff {r['first_diff']:#x}" if not r["ok_c"] else "")
        geo.setdefault((r["u_len"], r["frame"], r["periphery"], r["cram"]), []).append(r["stem"])
    log.info("")
    log.info("decompress(c) == u: %d / %d;  uncompressed passes through: %d / %d",
             good_c, len(rows), good_u, len(rows))
    log.info("")
    log.info("| uncompressed bytes | F (bytes/frame) | periphery frames | CRAM frames | CRAM bits | files |")
    log.info("|---|---|---|---|---|---|")
    for (ln, f, p, n), stems in sorted(geo.items()):
        dies = sorted({s.replace("sfl_enhanced_", "").replace("sfl_", "").replace("pfl_", "") for s in stems})
        log.info("| %s | %d | %d | %d | %s | %s |", f"{ln:,}", f, p, n, f"{8 * (f - 2) * n:,}", ", ".join(dies))
    return 0 if good_c == good_u == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
