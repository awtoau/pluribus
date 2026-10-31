#!/usr/bin/env python3.15t
"""Fetch third-party Cyclone IV (EP4CGX150) configuration images, record provenance, test the reader.

Purpose: independent gates for the Cyclone IV decoder (docs/recovery-process.md Phase 1).  Images are
other people's binaries: downloaded for interop testing, never committed.  Committed:
sources/cycloneiv-corpus/manifest.json (URL, commit/tag, licence, SHA-256, size, analysis) and
docs/altera/cycloneIV/cycloneiv-corpus.md.  Model: scripts/ecp5_corpus_fetch.py.

  python3.15t scripts/cycloneiv_corpus_fetch.py --fetch      # download CANDIDATES (gh), hash, write manifest
  python3.15t scripts/cycloneiv_corpus_fetch.py --analyze    # .sof -> .rbf (quartus_cpf), decode, fill manifest
  python3.15t scripts/cycloneiv_corpus_fetch.py --verify     # re-hash local files vs manifest, no network

Each image lives in its own directory sources/cycloneiv-corpus/<name>/ and is only ever read as data
(this script never executes anything from it).  .sof inputs are converted with the vendor tool
(quartus_cpf -c, compression off); the .rbf is derived data, not a build of ours.
Caps (Dan, 2026-10-29): total <= 10 GB under sources/cycloneiv-corpus/, >= 12 GB free disk; a download
that would breach either stops the run with a loud message.
Log: tmp/logs/cycloneiv_corpus_fetch.log
"""
import argparse
import datetime
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
ROOT = REPO / "sources" / "cycloneiv-corpus"
MANIFEST = ROOT / "manifest.json"
CAP_BYTES = 10 * 1024 ** 3
FREE_FLOOR = 12 * 1024 ** 3
GH_TIMEOUT_S = 120      # one gh api / release download of <= 8 MB; GitHub answers in seconds, 120 s = stall
CPF_TIMEOUT_S = 60      # quartus_cpf sof->rbf on <= 4 MB; ~2 s measured on the fuzz corpus (cycloneiv_fuzz OVERALL_S)

# kind "git": raw file at repo/path (HEAD commit pinned at fetch).  kind "release": asset of a release tag.
CANDIDATES = [
    dict(name="poseidon_galaksija", kind="release", repo="turri21/GalaksijaPLUS_poseidon-ep4cgx150",
         asset="GalaksijaPLUS_poseidon-ep4cgx150.rbf", licence="MIT", src="HDL in the same repo",
         what="Galaksija PLUS home computer core"),
    dict(name="poseidon_einstein", kind="release", repo="turri21/TatungEinstein_poseidon-ep4cgx150",
         asset="TatungEinstein_poseidon-ep4cgx150_20250405.rbf", licence="GPL-2.0", src="HDL in the same repo",
         what="Tatung Einstein core"),
    dict(name="poseidon_scv", kind="release", repo="turri21/SCV_poseidon-ep4cgx150",
         asset="scv_psdcgx150_20250918.rbf", licence="GPL-2.0", src="HDL in the same repo",
         what="Epoch Super Cassette Vision core"),
    dict(name="poseidon_computerspace", kind="git", repo="turri21/ComputerSpace_poseidon-ep4cgx150",
         path="releases/ComputerSpace_psdcgx150_20260202.rbf", licence="none stated (repo)",
         src="HDL in the same repo", what="Computer Space arcade core"),
    dict(name="neptuno_cgx150_mc2", kind="git", repo="distwave/neptuno-ep4cgx150",
         path="sources/Neptuno_firmware/Neptuno_MC2_firmware_1.05v/_MC2_firmware/synth/neptUNO_EP4CGX150/output_files/mc2.rbf",
         licence="none stated (repo)", src="HDL in the same repo", what="NeptUNO/MC2 firmware (NIOS II) on EP4CGX150"),
]

log = logging.getLogger("cycloneiv_corpus_fetch")


def setup_logging():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_corpus_fetch.log")):
        h.setFormatter(fmt)
        log.addHandler(h)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def gh(args, out=None):
    """Run gh read-only; return stdout bytes (or write to `out`)."""
    r = subprocess.run(["gh", *args], capture_output=True, timeout=GH_TIMEOUT_S)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.decode()[:300]}")
    if out is not None:
        Path(out).write_bytes(r.stdout)
    return r.stdout


def total_bytes():
    return sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) if ROOT.exists() else 0


def check_budget(next_bytes, name):
    used, free = total_bytes(), shutil.disk_usage(REPO).free
    if used + next_bytes > CAP_BYTES or free - next_bytes < FREE_FLOOR:
        log.error("LIMIT HIT: stopping on %s (%d B); corpus %d B of %d, free %d B (floor %d)",
                  name, next_bytes, used, CAP_BYTES, free, FREE_FLOOR)
        raise SystemExit(3)


def load_manifest():
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"entries": []}


def save_manifest(m):
    ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")


def fetch_one(c):
    d = ROOT / c["name"]
    if d.exists() and any(d.iterdir()):
        raise RuntimeError(f"{d} not empty (one download per fresh directory)")
    rec = dict(c)
    if c["kind"] == "git":
        meta = json.loads(gh(["api", f"repos/{c['repo']}/contents/{c['path']}"]))
        check_budget(meta["size"], c["name"])
        commit = json.loads(gh(["api", f"repos/{c['repo']}/commits?path={c['path']}&per_page=1"]))[0]["sha"]
        d.mkdir(parents=True)
        fn = Path(c["path"]).name
        gh(["api", f"repos/{c['repo']}/contents/{c['path']}?ref={commit}", "-H", "Accept: application/vnd.github.raw", "--allow-escape-sequences"], d / fn)
        rec.update(file=fn, commit=commit, url=f"https://github.com/{c['repo']}/blob/{commit}/{c['path']}")
    else:
        rels = json.loads(gh(["api", f"repos/{c['repo']}/releases"]))
        hit = [(r, a) for r in rels for a in r["assets"] if a["name"] == c["asset"]]
        if not hit:
            raise RuntimeError(f"asset {c['asset']} not found in {c['repo']} releases")
        r, a = hit[0]
        check_budget(a["size"], c["name"])
        d.mkdir(parents=True)
        gh(["release", "download", r["tag_name"], "-R", c["repo"], "-p", c["asset"], "-D", str(d)])
        rec.update(file=c["asset"], tag=r["tag_name"], url=a["browser_download_url"])
    p = d / rec["file"]
    rec.update(bytes=p.stat().st_size, sha256=sha256(p),
               retrieved=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=10))).isoformat(timespec="seconds"))
    log.info("fetched %-24s %9d B %s", c["name"], rec["bytes"], rec["sha256"][:12])
    return rec


def do_fetch():
    m = load_manifest()
    have = {e["name"] for e in m["entries"]}
    for c in CANDIDATES:
        if c["name"] in have:
            continue
        try:
            m["entries"].append(fetch_one(c))
        except RuntimeError as e:
            log.error("FAILED %s: %s", c["name"], e)
        save_manifest(m)
    log.info("corpus %d B in %d entries", total_bytes(), len(m["entries"]))


def sof_device(p):
    """Device string from the .sof container (ASCII part number)."""
    m = re.search(rb"EP4C[EG][A-Z]?\d+[A-Z]\d+[A-Z]\d+[A-Z]*", p.read_bytes()[:4096])
    return m.group(0).decode() if m else None


# (frame bytes, periphery frames, CRAM frames) -> device, for images without a device string (.rbf).
# SOF = read from a .sof container in this corpus; INFERRED = geometry vs our own lane model / board.
STATIC_SIGS = {
    (796, 37, 6154): ("EP4CGX150", "INFERRED: frame 796 = 793-byte lanes of lifters/data/cycloneiv_ep4cgx150_geom.json; boards are EP4CGX150"),
}


def analyze_one(e, sigs):
    import cycloneiv_corpus as cc
    import cycloneiv_decompress as cd
    import cycloneiv_geom as cg
    d = ROOT / e["name"]
    p = d / e["file"]
    a = {}
    if p.suffix == ".sof":
        a["sof_device"] = sof_device(p)
        rbf = d / (p.stem + ".derived.rbf")
        if not rbf.exists():
            r = subprocess.run([str(Path(__import__("toolchain").quartus_bin()) / "quartus_cpf"), "-c", "-o",
                                "bitstream_compression=off", p.name, rbf.name], cwd=d, capture_output=True,
                               timeout=CPF_TIMEOUT_S)
            if r.returncode:
                a["error"] = "quartus_cpf: " + r.stdout.decode()[-200:]
                return a
        a["derived_rbf_sha256"] = sha256(rbf)
    else:
        rbf = p
    data = rbf.read_bytes()
    info = {}
    try:
        cd.decompress(data, info)
    except cd.FormatError as ex:
        a["error"] = f"decompress: {ex}"
        return a
    a.update(frame_bytes=info["frame"], periphery_frames=info["periphery_frames"], cram_frames=info["cram_frames"],
             header_compressed=cd.parse(data)["compressed"], cram_crc_ok=True)
    sig = (info["frame"], info["periphery_frames"], info["cram_frames"])
    dev = a.get("sof_device") or ""
    if dev:
        a["device_source"] = "SOF container string"
    elif sig in sigs:
        dev, a["device_source"] = sigs[sig]
    a["device"] = dev or None
    try:
        geom = cg.load(cg.die_of(dev)) if dev else None
    except (KeyError, FileNotFoundError):
        geom = None
    a["geometry_supported"] = geom is not None
    try:
        plane = cc.cram_plane(data, geom)
        a["plane_shape"] = list(plane.shape)
        a["set_bits"] = int(plane.sum())
        a["reader_ok"] = True
    except Exception as ex:   # record, do not hide
        a["reader_ok"] = False
        a["reader_error"] = f"{type(ex).__name__}: {ex}"
    return a


def do_analyze():
    m = load_manifest()
    sigs = dict(STATIC_SIGS)
    import cycloneiv_decompress as cd
    for e in m["entries"]:     # signatures from .sof-identified images first
        p = ROOT / e["name"] / e["file"]
        if p.suffix == ".sof":
            d = sof_device(p)
            r = ROOT / e["name"] / (p.stem + ".derived.rbf")
            if d and r.exists():
                i = {}
                cd.decompress(r.read_bytes(), i)
                sigs.setdefault((i["frame"], i["periphery_frames"], i["cram_frames"]),
                                (d, "SOF container string of a same-geometry image (die family, not package)"))
    for e in m["entries"]:
        e["analysis"] = analyze_one(e, sigs)
        log.info("%-24s %s", e["name"], json.dumps(e["analysis"]))
    save_manifest(m)


def do_verify():
    bad = 0
    for e in load_manifest()["entries"]:
        p = ROOT / e["name"] / e["file"]
        if not p.exists():
            log.warning("MISSING %s", p)
            bad += 1
        elif sha256(p) != e["sha256"]:
            log.error("MISMATCH %s", p)
            bad += 1
    log.info("verify: %d problem(s)", bad)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", action="store_true")
    g.add_argument("--analyze", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    setup_logging()
    if a.verify:
        return do_verify()
    if a.fetch:
        do_fetch()
    else:
        do_analyze()
    return 0


if __name__ == "__main__":
    sys.exit(main())
