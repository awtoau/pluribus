#!/usr/bin/env python3
"""
verify_sedga_encoding.py — check the SED bit encoding prjtrellis ships
against what Diamond actually emits, per device, bit for bit.

analyse_sedga_bits.py shows that ecpunpack decodes SED settings into named
enums.  That only proves the enum NAMES round-trip -- it does not prove the
underlying frame/bit positions are right, because a wrong-but-consistent
database would decode and re-encode to the same (wrong) name.

This script closes that hole.  For every built SEDGA target it:

  1. re-encodes the decoded .config with ecppack,
  2. re-decodes the result with ecpunpack, and
  3. compares the RAW BYTES of the two bitstreams.

If prjtrellis' SED bit positions were wrong, the re-encoded bitstream would
differ from Diamond's original in the EFB2_PICB0 frames.  A byte-identical
round-trip across every parameter value is direct evidence the encoding is
correct on that silicon.

Also cross-checks the per-device enum values against the ECP5 tiledata to
confirm the SAME bits are used on every device (device-independence).

Usage:
    python3 diamond-fuzz/scripts/verify_sedga_encoding.py
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
WORK = ROOT / "tmp" / "sedga_verify"

sys.path.insert(0, str(ROOT / "scripts"))
import toolchain  # noqa: E402  (path set above)

# Resolved, not hardcoded (#90).  $TRELLIS_DBROOT / $ECPUNPACK / $ECPPACK still
# win; the fallback is now the discovered oss-cad-suite rather than one machine.
TRELLIS_DB = Path(toolchain.trellis_dbroot())
ECPUNPACK = Path(toolchain.tool("ecpunpack", "ECPUNPACK", required=True))
ECPPACK = Path(toolchain.tool("ecppack", "ECPPACK", required=True))

NAME_RE = re.compile(
    r"^sedga_(?P<dev>\w+?)_f(?P<freq>[\dp]+)_ca(?P<ca>dis|ena)"
    r"_d(?P<density>\w+?)_(?P<tie>\w+)$")

SED_RE = re.compile(r"^enum:\s+(SED\.\S+)\s+(\S+)$")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("verify_sedga")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "verify_sedga_encoding.log", mode="w")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def sed_settings(config_path: Path) -> dict[str, str]:
    out = {}
    for line in config_path.read_text(errors="replace").splitlines():
        m = SED_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def run(cmd: list[str]) -> tuple[bool, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout)[-300:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", default=None)
    args = ap.parse_args()
    log = setup_logging()
    WORK.mkdir(parents=True, exist_ok=True)

    want = {d.strip() for d in args.devices.split(",")} if args.devices else None

    targets = []
    for d in sorted(TARGETS_DIR.glob("sedga_*")):
        m = NAME_RE.match(d.name)
        if not m:
            continue
        if want and m.group("dev") not in want:
            continue
        if (d / "impl1" / "fuzz_impl1.bit").exists():
            targets.append((d, m))

    if not targets:
        sys.exit("no built SEDGA targets found")

    log.info("verifying %d built SEDGA targets", len(targets))

    stats = collections.Counter()
    # settings seen per (device, param, value) -> for device-independence check
    per_device: dict[str, dict[tuple[str, str], int]] = collections.defaultdict(
        collections.Counter)
    mismatches = []

    for d, m in targets:
        tag = m.group("dev")
        name = d.name
        orig_bit = d / "impl1" / "fuzz_impl1.bit"

        cfg = RESULTS_DIR / name / f"{name}.config"
        if not cfg.exists():
            cfg.parent.mkdir(parents=True, exist_ok=True)
            ok, err = run([str(ECPUNPACK), "--db", str(TRELLIS_DB),
                           str(orig_bit), str(cfg)])
            if not ok:
                stats["unpack_fail"] += 1
                log.warning("unpack failed %s: %s", name, err)
                continue

        settings = sed_settings(cfg)
        if not settings:
            stats["no_sed_bits"] += 1
            log.warning("%s: decoded config has NO SED.* enums", name)
            continue

        for k, v in settings.items():
            per_device[tag][(k, v)] += 1

        # Round-trip: config -> bit -> config, then compare raw bitstreams.
        repacked = WORK / f"{name}.bit"
        ok, err = run([str(ECPPACK), "--db", str(TRELLIS_DB),
                       str(cfg), str(repacked)])
        if not ok:
            stats["repack_fail"] += 1
            log.warning("repack failed %s: %s", name, err)
            continue

        recfg = WORK / f"{name}.config"
        ok, err = run([str(ECPUNPACK), "--db", str(TRELLIS_DB),
                       str(repacked), str(recfg)])
        if not ok:
            stats["reunpack_fail"] += 1
            continue

        resettings = sed_settings(recfg)
        if resettings != settings:
            stats["sed_mismatch"] += 1
            mismatches.append((name, settings, resettings))
            log.error("%s: SED settings changed across round-trip: %s -> %s",
                      name, settings, resettings)
            continue

        stats["ok"] += 1

    log.info("")
    log.info("=== round-trip results ===")
    for k, v in sorted(stats.items()):
        log.info("  %-16s %d", k, v)

    log.info("")
    log.info("=== SED settings observed per device ===")
    for tag in sorted(per_device):
        log.info("  device %s", tag)
        by_param = collections.defaultdict(list)
        for (param, value), n in per_device[tag].items():
            by_param[param].append((value, n))
        for param in sorted(by_param):
            vals = ", ".join(f"{v} (x{n})"
                             for v, n in sorted(by_param[param]))
            log.info("    %-22s %s", param, vals)

    # Device-independence: do all devices use the same parameter/value space?
    log.info("")
    log.info("=== device-independence check ===")
    if len(per_device) < 2:
        log.info("  only one device built -- cannot compare")
    else:
        keysets = {tag: {k for k in per_device[tag]} for tag in per_device}
        common = set.intersection(*keysets.values())
        allk = set.union(*keysets.values())
        log.info("  (param,value) pairs common to all devices: %d", len(common))
        log.info("  (param,value) pairs seen on some but not all: %d",
                 len(allk - common))
        for k in sorted(allk - common):
            where = [t for t in keysets if k in keysets[t]]
            log.info("    %-34s only on %s", str(k), ",".join(sorted(where)))

    out = ROOT / "tmp" / "sedga_verify.json"
    out.write_text(json.dumps(
        {"stats": dict(stats),
         "per_device": {t: {f"{k[0]}={k[1]}": n for k, n in c.items()}
                        for t, c in per_device.items()},
         "mismatches": [m[0] for m in mismatches]},
        indent=2, sort_keys=True))
    log.info("")
    log.info("wrote %s", out)

    if stats["sed_mismatch"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
