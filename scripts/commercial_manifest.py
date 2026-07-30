#!/usr/bin/env python3.15t
"""Join carved bitstreams back to the products they came from.

`commercial_fetch.py` records WHERE a firmware file came from.  `ecp5_carve.py`
records WHAT was found inside it.  Neither alone is a corpus manifest: a carved
bitstream with no product attribution is untraceable, and a product entry with no
bitstream list says nothing about what is testable.

This joins the two on the firmware file path and emits the committed manifest,
with the same field names as `corpus/manifest.json` so the commercial set and the
GitHub set merge:

    url, sha256, bytes, license, device, family, notes, local, status

plus the commercial-specific provenance: vendor, product, the container path the
bitstream was carved from (`origin`), and the source firmware's own SHA-256, so a
reader can verify the whole chain from vendor download to tested bitstream.

ONE PRODUCT, MANY BITSTREAMS.  A release zip can hold well over a hundred
designs (Tiliqua ships 161).  Those are recorded individually because they ARE
distinct designs, but `product_bitstream_count` is carried on each so a reader
can see at a glance when one product dominates the set -- which is exactly the
skew that made the original corpus 180/228 ULX3S.

Usage:
    python3.15t scripts/commercial_manifest.py
    python3.15t scripts/commercial_manifest.py --results tmp/commercial_results.json

Logs to ./tmp/logs/commercial_manifest.log.
"""
import argparse
import collections
import datetime
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FETCH_MANIFEST = os.path.join(REPO, "corpus", "commercial-manifest.json")
CARVE_JSON = os.path.join(REPO, "tmp", "commercial_carve.json")
OUT = os.path.join(REPO, "corpus", "commercial-bitstreams.json")


def setup_logging(name):
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(REPO, "tmp", "logs",
                                               f"{name}.log"))):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", default=FETCH_MANIFEST)
    ap.add_argument("--carve", default=CARVE_JSON)
    ap.add_argument("--results", help="optional ecp5_corpus_test results JSON, "
                                      "to fold the three claims in")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    log = setup_logging("commercial_manifest")

    fetch = json.load(open(args.fetch))["entries"]
    carve = json.load(open(args.carve))

    # index products by the firmware file they produced
    by_local = {}
    for f in fetch:
        if f.get("local"):
            by_local[os.path.normpath(f["local"])] = f

    results = {}
    if args.results and os.path.exists(args.results):
        for r in json.load(open(args.results)):
            if r.get("sha256"):
                results[r["sha256"]] = r
            # also key by basename: --scan entries carry no sha256 from the
            # manifest, only the label
            if r.get("label"):
                results.setdefault(r["label"], r)
        log.info("folded in %d test result(s)", len(results))

    per_product = collections.Counter()
    for c in carve:
        src = os.path.normpath(c.get("source_file", ""))
        prod = by_local.get(src)
        per_product[prod["key"] if prod else "unattributed"] += 1

    entries = []
    unattributed = 0
    for c in carve:
        src = os.path.normpath(c.get("source_file", ""))
        prod = by_local.get(src)
        if prod is None:
            unattributed += 1
        key = prod["key"] if prod else None
        e = {
            "family": c["family"],
            "device": c["device"],
            "bytes": c["bytes"],
            "sha256": c["sha256"],
            "local": c["local"],
            "origin": c["origin"],
            "carved_from": c.get("source_file"),
            "vendor": prod["vendor"] if prod else None,
            "product": prod["product"] if prod else None,
            "url": prod["url"] if prod else None,
            "license": prod["license"] if prod else "unknown",
            "firmware_sha256": prod.get("sha256") if prod else None,
            "product_key": key,
            "product_bitstream_count": per_product.get(key or "unattributed"),
            "notes": prod["notes"] if prod else "carved; product not matched",
            "status": "ok",
        }
        if c.get("device_note"):
            e["device_note"] = c["device_note"]
        if c.get("part_strings"):
            e["part_strings"] = c["part_strings"]
        # fold in the three claims when available
        r = results.get(c["sha256"]) or results.get(os.path.basename(c["local"]))
        if r:
            e["decode"] = r.get("decode")
            e["oracle"] = r.get("oracle")
            e["lift"] = r.get("lift")
            e["crc_verified"] = r.get("crc_verified")
            e["frames_complete"] = r.get("frames_complete")
            if r.get("metrics"):
                m = r["metrics"]
                e["ff_clk_const_rate"] = m.get("ff_clk_const_rate")
                e["widemux_total"] = m.get("widemux_total")
        entries.append(e)

    out = {
        "note": ("FPGA bitstreams carved from COMMERCIAL product firmware, for "
                 "decoder interoperability testing. The binaries are NOT "
                 "redistributed (corpus/commercial/ and corpus/vendor-firmware/ "
                 "are gitignored); this manifest records the full chain -- vendor "
                 "download URL, that file's SHA-256, the container path the "
                 "bitstream sits at, and the bitstream's own SHA-256 -- so the "
                 "set is reproducible from the original sources. Field names "
                 "match corpus/manifest.json so the commercial and GitHub sets "
                 "merge."),
        "retrieved": datetime.datetime.now().astimezone().isoformat(),
        "by_family": dict(collections.Counter(e["family"] for e in entries)),
        "by_product": dict(per_product),
        "entries": sorted(entries, key=lambda e: (e["family"], e["device"],
                                                  e["sha256"])),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    log.info("%d bitstream(s) -> %s", len(entries), args.out)
    for fam, n in sorted(out["by_family"].items()):
        log.info("  family %-9s %d", fam, n)
    for k, n in per_product.most_common():
        log.info("  product %-26s %d", k, n)
    if unattributed:
        log.warning("%d carved bitstream(s) could not be matched to a product",
                    unattributed)


if __name__ == "__main__":
    main()
