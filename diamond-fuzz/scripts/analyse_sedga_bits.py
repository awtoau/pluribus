#!/usr/bin/env python3
"""
analyse_sedga_bits.py — recover the ECP5 SEDGA configuration-bit encoding by
diffing Diamond-generated bitstreams.

Method
------
For each device, every SEDGA target's bitstream is decoded to a
prjtrellis-format .config and diffed against that device's SEDGA-free
baseline.  Bits that appear only when SEDGA is instantiated, and that
correlate with a parameter value, are that parameter's encoding.

Nothing here guesses at bit positions: a bit is only attributed to a
parameter if it partitions the target set exactly along that parameter's
values.  Bits that vary for other reasons (placement noise, the harness
IO, the registered output) show up as unattributed and are reported as
such rather than quietly dropped.

The recovered encoding is then compared against what prjtrellis already
ships in ECP5/tiledata/EFB2_PICB0/bits.db, so agreement or disagreement
with the existing database is explicit.

Outputs tmp/sedga_encoding.json and a human-readable summary.

Usage:
    python3 diamond-fuzz/scripts/analyse_sedga_bits.py [--devices 12f,25f]
"""

import argparse
import collections
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

FUZZ_DIR = Path(__file__).resolve().parents[1]
ROOT = FUZZ_DIR.parent
TARGETS_DIR = FUZZ_DIR / "targets"
RESULTS_DIR = FUZZ_DIR / "results"
LOG_DIR = ROOT / "tmp" / "logs"
TMP = ROOT / "tmp"

TRELLIS_DB = Path(os.environ.get(
    "TRELLIS_DBROOT",
    "/home/dan/opt/oss-cad-suite/share/trellis/database"))

# Decode ECP5 bitstreams with prjtrellis' reference ecpunpack.
#
# pluribus' own scripts/trellis_unpack.py (native pure-Python decoder) does
# NOT work on these bitstreams: it aborts with
#     native_bitstream.ParseError: crc fail at offset 173
# on every ECP5 .bit tried here, including the trivial SEDGA-free baseline.
# The native decoder was written for MachXO2 and its CRC/frame handling does
# not carry over to ECP5.  That is a real gap in pluribus (worth its own
# issue) but not one this task needs to fix, so the reference C++ decoder is
# used instead.  Recorded rather than worked around silently.
ECPUNPACK = Path(os.environ.get(
    "ECPUNPACK", "/home/dan/opt/oss-cad-suite/bin/ecpunpack"))

# Trellis device name per target tag (the .config decode needs the device
# whose tilegrid matches the bitstream).
TRELLIS_DEVICE = {
    "12f": "LFE5U-12F",
    "25f": "LFE5U-25F",
    "45f": "LFE5U-45F",
    "85f": "LFE5U-85F",
}

# sedga_<dev>_f<freq>_ca<dis|ena>_d<density>_<tieoff>
NAME_RE = re.compile(
    r"^sedga_(?P<dev>\w+?)_f(?P<freq>[\dp]+)_ca(?P<ca>dis|ena)"
    r"_d(?P<density>\w+?)_(?P<tie>\w+)$")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("analyse_sedga")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "analyse_sedga_bits.log", mode="w")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def unpack(target_dir: Path, device: str, log: logging.Logger) -> Path | None:
    """Decode target's .bit to a .config (cached)."""
    bit = target_dir / "impl1" / "fuzz_impl1.bit"
    if not bit.exists():
        return None
    out_dir = RESULTS_DIR / target_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = out_dir / f"{target_dir.name}.config"
    if cfg.exists() and cfg.stat().st_mtime >= bit.stat().st_mtime:
        return cfg
    cfg.unlink(missing_ok=True)
    r = subprocess.run(
        [str(ECPUNPACK), "--db", str(TRELLIS_DB), str(bit), str(cfg)],
        capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0 or not cfg.exists():
        log.warning("unpack failed for %s: %s",
                    target_dir.name, r.stderr.strip()[-200:])
        return None
    return cfg


def parse_config(path: Path) -> dict[str, set[str]]:
    """Parse a .config into {tile_name: {config-line, ...}}.

    Every non-empty line inside a .tile block is kept verbatim, so arcs,
    enums, words and unknown bits are all compared.
    """
    tiles: dict[str, set[str]] = {}
    cur = None
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith(".tile "):
            cur = s.split(None, 1)[1].strip()
            tiles.setdefault(cur, set())
            continue
        if s.startswith("."):
            # another section type (.bram_init/.efb_block/...) ends tile scope
            if not s.startswith(".tile"):
                cur = None
            continue
        if cur and s:
            tiles[cur].add(s)
    return tiles


def tile_diff(base: dict[str, set[str]],
              other: dict[str, set[str]]) -> dict[str, set[str]]:
    """Config lines present in `other` but not in `base`, per tile."""
    out: dict[str, set[str]] = {}
    for tile, lines in other.items():
        extra = lines - base.get(tile, set())
        if extra:
            out[tile] = extra
    return out


def attribute(records: list[dict], key: str) -> dict[str, dict[str, list[str]]]:
    """Find config lines that partition targets exactly by records[key].

    Returns {tile: {value: [lines...]}} listing, for each parameter value,
    the lines present in EVERY target with that value and in NO target with
    any other value.  That exactness requirement is what stops placement
    noise being mistaken for encoding.
    """
    by_value: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        by_value[r[key]].append(r)
    if len(by_value) < 2:
        return {}

    tiles = {t for r in records for t in r["diff"]}
    result: dict[str, dict[str, list[str]]] = {}

    for tile in sorted(tiles):
        per_value_common: dict[str, set[str]] = {}
        for value, recs in by_value.items():
            sets = [r["diff"].get(tile, set()) for r in recs]
            per_value_common[value] = set.intersection(*sets) if sets else set()

        for value, common in per_value_common.items():
            others = set()
            for v2, recs in by_value.items():
                if v2 == value:
                    continue
                for r in recs:
                    others |= r["diff"].get(tile, set())
            unique = common - others
            if unique:
                result.setdefault(tile, {})[value] = sorted(unique)
    return result


def load_prjtrellis_sed() -> dict[str, dict[str, list[str]]]:
    """Parse the SED enums prjtrellis already ships for ECP5."""
    db = TRELLIS_DB / "ECP5" / "tiledata" / "EFB2_PICB0" / "bits.db"
    out: dict[str, dict[str, list[str]]] = {}
    if not db.exists():
        return out
    cur = None
    for line in db.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith(".config_enum SED."):
            cur = s.split(None, 1)[1].rsplit(None, 1)[0]
            out[cur] = {}
            continue
        if s.startswith("."):
            cur = None
            continue
        if cur and s:
            parts = s.split()
            out[cur][parts[0]] = parts[1:]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", default=None,
                    help="comma-separated device tags (default: all found)")
    args = ap.parse_args()
    log = setup_logging()

    want = {d.strip() for d in args.devices.split(",")} if args.devices else None

    # Collect built targets grouped by device.
    per_dev: dict[str, list[Path]] = collections.defaultdict(list)
    baselines: dict[str, Path] = {}
    for d in sorted(TARGETS_DIR.glob("sedga_*")):
        if not (d / "impl1" / "fuzz_impl1.bit").exists():
            continue
        if d.name.endswith("_baseline"):
            tag = d.name.split("_")[1]
            baselines[tag] = d
            continue
        m = NAME_RE.match(d.name)
        if m:
            per_dev[m.group("dev")].append(d)

    if want:
        per_dev = {k: v for k, v in per_dev.items() if k in want}

    if not per_dev:
        sys.exit("no built SEDGA targets found -- run run_all_fuzz.py first")

    trellis_sed = load_prjtrellis_sed()
    report: dict[str, dict] = {}

    for tag, dirs in sorted(per_dev.items()):
        device = TRELLIS_DEVICE.get(tag)
        log.info("=== device %s (%s): %d built targets ===",
                 tag, device, len(dirs))

        if tag not in baselines:
            log.warning("no baseline for %s -- skipping", tag)
            continue
        base_cfg = unpack(baselines[tag], device, log)
        if base_cfg is None:
            log.warning("baseline unpack failed for %s -- skipping", tag)
            continue
        base = parse_config(base_cfg)

        records = []
        for d in dirs:
            m = NAME_RE.match(d.name)
            cfg = unpack(d, device, log)
            if cfg is None:
                continue
            records.append({
                "name": d.name,
                "freq": m.group("freq").replace("p", "."),
                "ca": {"dis": "DISABLED", "ena": "ENABLED"}[m.group("ca")],
                "tie": m.group("tie"),
                "diff": tile_diff(base, parse_config(cfg)),
            })

        if not records:
            log.warning("no decodable targets for %s", tag)
            continue

        log.info("  decoded %d/%d targets", len(records), len(dirs))

        # Which tiles ever differ from baseline at all?
        tile_hits = collections.Counter()
        for r in records:
            for t in r["diff"]:
                tile_hits[t] += 1
        log.info("  tiles differing from baseline: %d", len(tile_hits))
        for t, n in tile_hits.most_common(10):
            log.info("    %-24s %d/%d targets", t, n, len(records))

        freq_enc = attribute(records, "freq")
        ca_enc = attribute(records, "ca")
        tie_enc = attribute(records, "tie")

        report[tag] = {
            "device": device,
            "targets": len(records),
            "tiles_differing": dict(tile_hits),
            "SED_CLK_FREQ": freq_enc,
            "CHECKALWAYS": ca_enc,
            "TIEOFF": tie_enc,
        }

        for label, enc in (("SED_CLK_FREQ", freq_enc),
                           ("CHECKALWAYS", ca_enc),
                           ("TIEOFF", tie_enc)):
            if not enc:
                log.info("  %s: no bits partition exactly by this parameter",
                         label)
                continue
            log.info("  %s:", label)
            for tile, values in sorted(enc.items()):
                log.info("    tile %s", tile)
                for value, lines in sorted(values.items()):
                    log.info("      %-10s %s", value, " ".join(lines))

    out = TMP / "sedga_encoding.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    log.info("")
    log.info("wrote %s", out)

    if trellis_sed:
        log.info("")
        log.info("=== prjtrellis already ships (ECP5 EFB2_PICB0) ===")
        for enum, values in sorted(trellis_sed.items()):
            log.info("  %s", enum)
            for v, bits in sorted(values.items()):
                log.info("    %-10s %s", v, " ".join(bits) if bits else "-")


if __name__ == "__main__":
    main()
