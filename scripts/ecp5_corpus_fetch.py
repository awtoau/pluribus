#!/usr/bin/env python3.15t
"""Fetch third-party ECP5 bitstreams into a local corpus, and record provenance.

WHY THIS EXISTS
---------------
Every ECP5 bitstream the lifter was verified against was built by OUR toolchain
(yosys + nextpnr + prjtrellis), and the round-trip oracle is nextpnr's own
placed netlist.  That is a closed loop: it can prove the lifter agrees with the
tool that made the file, and nothing else.  It cannot catch anything about how a
DIFFERENT packer lays a bitstream out.

This script builds the open loop.  It downloads bitstreams other people built —
different Diamond versions, different design styles, parts we do not own — and
records enough provenance that the corpus is reproducible WITHOUT redistributing
anyone's binary.

WHAT IS AND IS NOT COMMITTED
----------------------------
  * The manifest (this script's `--manifest` output, and docs/ecp5-corpus.md)
    IS committed: URL, project, licence, device, SHA-256, retrieval date.
  * The `.bit` files are NOT committed.  corpus/ is gitignored.  Anyone can
    reconstruct the corpus by re-running this script against the manifest, and
    the SHA-256 proves they got the same bytes we tested.

Usage:
    python3.15t scripts/ecp5_corpus_fetch.py --candidates tmp/corpus_github.json
    python3.15t scripts/ecp5_corpus_fetch.py --verify      # re-hash, no download

Logs to ./tmp/logs/ecp5_corpus_fetch.log.
"""
import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

CORPUS_DIR = os.path.join(REPO, "corpus", "ecp5")
MANIFEST = os.path.join(REPO, "corpus", "manifest.json")

# An ECP5 bitstream is 500KB-2.5MB depending on part.  Anything far outside
# that is a different family (iCE40 .bit is ~100KB) or a truncated file; we
# still record it, but flag it rather than silently treating it as ECP5.
MIN_PLAUSIBLE = 100 * 1024
MAX_PLAUSIBLE = 8 * 1024 * 1024

_lock = threading.Lock()


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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_name(entry):
    """Stable, filesystem-safe local filename derived from the source.

    Must be unique per URL, not per basename.  Several projects publish the
    same asset name across many release tags (`saxonsoc-ulx3s-linux-25.bit`
    appears under five tags), and keying on owner+basename alone made those
    downloads overwrite each other: the manifest then recorded five entries
    pointing at one file, so four of the five SHA-256s did not describe what
    was actually on disk.  A short hash of the full URL disambiguates without
    making the names unreadable.
    """
    owner_repo = entry.get("owner_repo", "unknown").replace("/", "_")
    base = os.path.basename(entry.get("path") or entry["url"]).split("?")[0]
    stem = f"{owner_repo}__{base}"
    tag = hashlib.sha256(entry["url"].encode()).hexdigest()[:8]
    root, ext = os.path.splitext(stem)
    return f"{root}.{tag}{ext}"


def fetch_one(entry, log, force=False):
    """Download one candidate.  Returns the manifest record (never raises)."""
    dest = os.path.join(CORPUS_DIR, local_name(entry))
    rec = dict(entry)
    rec["local"] = os.path.relpath(dest, REPO)

    if os.path.exists(dest) and not force:
        rec["sha256"] = sha256_file(dest)
        rec["bytes"] = os.path.getsize(dest)
        rec["status"] = "cached"
        with _lock:
            log.info("cached   %-52s %8d B", local_name(entry), rec["bytes"])
        return rec

    req = urllib.request.Request(
        entry["url"],
        headers={"User-Agent": "pluribus-ecp5-corpus/1.0 (decoder interop test)"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        rec["status"] = f"download-failed: {type(e).__name__}: {e}"
        with _lock:
            log.error("FAILED   %-52s %s", local_name(entry), e)
        return rec

    os.makedirs(CORPUS_DIR, exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)

    rec["bytes"] = len(data)
    rec["sha256"] = hashlib.sha256(data).hexdigest()
    rec["status"] = "ok"
    if not (MIN_PLAUSIBLE <= len(data) <= MAX_PLAUSIBLE):
        rec["status"] = "ok-implausible-size"
    with _lock:
        log.info("fetched  %-52s %8d B  %s",
                 local_name(entry), len(data), rec["sha256"][:12])
    return rec


def load_manifest():
    if os.path.exists(MANIFEST):
        return json.load(open(MANIFEST))
    return {"retrieved": None, "entries": []}


def save_manifest(man):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w") as fh:
        json.dump(man, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates",
                    help="JSON list of {url, owner_repo, project, path, "
                         "license, size, device_guess, notes}")
    ap.add_argument("--verify", action="store_true",
                    help="re-hash local files against the manifest; no network")
    ap.add_argument("--force", action="store_true", help="re-download cached")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    log = setup_logging("ecp5_corpus_fetch")

    if args.verify:
        man = load_manifest()
        bad = missing = ok = 0
        for rec in man["entries"]:
            p = os.path.join(REPO, rec["local"])
            if not os.path.exists(p):
                missing += 1
                log.warning("MISSING  %s", rec["local"])
            elif sha256_file(p) != rec.get("sha256"):
                bad += 1
                log.error("MISMATCH %s", rec["local"])
            else:
                ok += 1
        log.info("verify: %d ok, %d mismatched, %d missing", ok, bad, missing)
        return 1 if bad else 0

    if not args.candidates:
        ap.error("--candidates or --verify required")

    cands = json.load(open(args.candidates))
    if isinstance(cands, dict):
        cands = cands.get("entries", cands.get("candidates", []))
    log.info("%d candidates from %s", len(cands), args.candidates)

    recs = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(fetch_one, c, log, args.force) for c in cands]
        for f in concurrent.futures.as_completed(futs):
            recs.append(f.result())

    # De-duplicate by content hash: several projects vendor the same prebuilt
    # bitstream, and a corpus of ten copies of one design proves nothing.
    by_hash = {}
    dupes = 0
    for r in sorted(recs, key=lambda r: r.get("local", "")):
        h = r.get("sha256")
        if h and h in by_hash:
            dupes += 1
            by_hash[h].setdefault("duplicate_urls", []).append(r["url"])
            if os.path.exists(os.path.join(REPO, r["local"])):
                os.unlink(os.path.join(REPO, r["local"]))
            continue
        if h:
            by_hash[h] = r

    import datetime
    man = {
        "retrieved": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=10))).isoformat(),
        "note": "Third-party bitstreams are NOT redistributed in this repo. "
                "corpus/ is gitignored; this manifest makes the corpus "
                "reproducible from the original sources.",
        "entries": sorted(
            [r for r in recs if r.get("sha256") in by_hash
             and by_hash[r["sha256"]] is r],
            key=lambda r: r.get("local", "")),
        "failed": sorted([r for r in recs if not r.get("sha256")],
                         key=lambda r: r.get("url", "")),
    }
    save_manifest(man)
    log.info("manifest: %d unique, %d duplicate-content dropped, %d failed",
             len(man["entries"]), dupes, len(man["failed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
