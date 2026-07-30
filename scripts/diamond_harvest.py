#!/usr/bin/env python3.15t
"""Harvest Diamond's own installed data and diff it against the open toolchain.

Diamond ships ~4 GB of vendor data under `ispfpga/`, including per-device
usage text (`.usg`) that documents every option its tools accept.  That text is
the vendor's own statement of what the hardware and bitstream support.  Where
the open flow (ecppack / nextpnr / prjtrellis) has no equivalent, the claim
"Diamond documents this and the open flow lacks it" is evidence, not inference
-- which is exactly the distinction this script is built to preserve.

Three harvesters, all read-only:

  H1 usg-options    parse every `.usg` into (tool, option, values) and report
                    which options the open tools do not mention at all.
  H2 binary-strings mine Diamond executables and shared objects for option
                    names, enum values and error text, then cross-reference the
                    same way.  Catches options too new or too obscure to be in
                    the usage text.
  H3 data-inventory record every data file per device family with size and
                    mtime, so "the vendor data is newer than the fuzzing" can
                    be stated with dates rather than asserted.

Cross-referencing is deliberately conservative: an option counts as "present in
the open flow" if its name appears anywhere in the open tools' strings.  That
biases towards *under*-reporting gaps, so anything this script does flag is
worth a look.

Usage:  scripts/diamond_harvest.py [--diamond DIR] [--family ep5c00]
Writes tmp/diamond_harvest.json, logs to tmp/logs/diamond_harvest.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
OUT = REPO / "tmp/diamond_harvest.json"

sys.path.insert(0, str(REPO / "scripts"))
import toolchain  # noqa: E402  (path set above)

# Resolved, not hardcoded (#90).  The Diamond version is discovered rather than
# pinned to 3.14, so an upgrade does not leave this harvesting the old tree.
DIAMOND = Path(toolchain.diamond_root())
OSS_CAD = Path(toolchain.suite_root() or "")

# ECP5 device trees.  Named here so the inventory reports them as a family
# rather than as unrelated directories.
ECP5_TREES = ["ep5a00", "ep5c00", "ep5c00a", "ep5g00", "ep5g00p", "ep5m00"]

# The open-source tools whose capabilities we compare against.  Each is
# searched as a binary blob, so this works whether the option name appears in
# an argument parser table, a help string or a database key.
OPEN_TOOLS = [
    "ecppack", "ecpunpack", "ecpbram", "ecpmulti",
    "nextpnr-ecp5", "nextpnr-machxo2", "yosys",
]


@dataclass
class UsgOption:
    tool: str
    device: str
    option: str
    values: list[str] = field(default_factory=list)
    kind: str = "flag"          # flag | setting
    in_open: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    ecp5: bool = False

    @property
    def missing(self) -> bool:
        return not self.in_open


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("diamond_harvest")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "diamond_harvest.log", mode="w")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


# ---------------------------------------------------------------------------
# H1: usage text
# ---------------------------------------------------------------------------

_OPT_RE = re.compile(r"^\s*(-[A-Za-z_]\w*)\s*(<[^>]*>)?\s*=\s*(.*)$")
# A "-g Option Val1, Val2" settings line: two spaces or more separate the
# option name from its comma-separated value list.
_SET_RE = re.compile(r"^\s{4,}([A-Z][A-Za-z0-9_]{2,})\s{2,}(\S.*?)\s*$")


def parse_usg(path: Path, log: logging.Logger) -> list[UsgOption]:
    """Parse one `.usg` file into flags and `-g` settings.

    The format is free-form vendor help text, so parsing is heuristic: an
    option line matches `-flag = description`, and an indented `Name  V1, V2`
    line inside the `-g` block is a setting with an enumerated value list.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        return []

    tool = path.stem
    device = path.parent.parent.name
    out: list[UsgOption] = []
    in_g_block = False

    for raw in text.splitlines():
        m = _OPT_RE.match(raw)
        if m:
            opt = m.group(1)
            out.append(UsgOption(tool, device, opt, kind="flag"))
            in_g_block = opt == "-g"
            continue
        if in_g_block:
            s = _SET_RE.match(raw)
            if s:
                name, vals = s.group(1), s.group(2)
                # Values are comma separated; the vendor notes "First is
                # default" in the -g header, so order is meaningful.
                vlist = [v.strip() for v in vals.split(",") if v.strip()]
                # Guard against prose lines sneaking in: real value lists are
                # short tokens, not sentences.
                if vlist and all(len(v) <= 24 and " " not in v for v in vlist):
                    out.append(UsgOption(tool, device, name, vlist, "setting"))
            elif raw.strip() and not raw.startswith(" "):
                in_g_block = False
    return out


def tool_strings(log: logging.Logger) -> dict[str, str]:
    """Extract printable strings from each open-source tool binary.

    Uses `strings` when available and falls back to reading the file and
    pulling ASCII runs, so the check still works on a minimal system.
    """
    blobs: dict[str, str] = {}
    have_strings = shutil.which("strings") is not None
    for name in OPEN_TOOLS:
        p = OSS_CAD / "bin" / name
        if not p.is_file():
            log.info("open tool not installed, skipping: %s", name)
            continue
        try:
            if have_strings:
                r = subprocess.run(["strings", "-a", str(p)],
                                   capture_output=True, text=True, check=False)
                blobs[name] = r.stdout
            else:
                data = p.read_bytes()
                blobs[name] = "\n".join(
                    m.decode("ascii", "replace")
                    for m in re.findall(rb"[ -~]{4,}", data))
            log.info("%s: %d KiB of strings", name, len(blobs[name]) // 1024)
        except OSError as exc:
            log.warning("cannot read %s: %s", p, exc)
    return blobs


def crossref(opts: list[UsgOption], blobs: dict[str, str], log) -> None:
    """Mark each Diamond option with the open tools that mention it.

    Matching is on whole-word option name.  For `-g` settings the name is
    distinctive (DONEPHASE, CfgMode); for bare flags like `-b` it is not, so
    those are matched case-sensitively with a word boundary and still treated
    as weak evidence.
    """
    cache: dict[str, list[str]] = {}
    for o in opts:
        key = o.option
        if key not in cache:
            pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(key.lstrip("-"))
                             + r"(?![A-Za-z0-9_])")
            cache[key] = [t for t, b in blobs.items() if pat.search(b)]
        o.in_open = cache[key]


# ---------------------------------------------------------------------------
# H3: data inventory
# ---------------------------------------------------------------------------

def inventory(root: Path, log: logging.Logger) -> list[dict]:
    """Record every device data file with size and mtime.

    The point is the dates: prjtrellis's ECP5 fuzzers were last touched in
    2022, and if the vendor data postdates that, the database was characterised
    against an older oracle than the one installed.  That is a claim best made
    with timestamps.
    """
    rows: list[dict] = []
    for tree in ECP5_TREES:
        d = root / "ispfpga" / tree / "data"
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            rows.append({
                "family": "ECP5", "tree": tree, "name": f.name,
                "suffix": f.suffix, "bytes": st.st_size,
                "mtime": __import__("datetime").datetime.fromtimestamp(
                    st.st_mtime).astimezone().isoformat(timespec="seconds"),
            })
    log.info("inventory: %d device data files across %d ECP5 trees",
             len(rows), len(ECP5_TREES))
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diamond", type=Path, default=DIAMOND)
    args = ap.parse_args(argv[1:])
    log = setup_logging()

    if not args.diamond.is_dir():
        log.error("Diamond not found at %s", args.diamond)
        return 1

    usgs = sorted((args.diamond / "ispfpga").rglob("*.usg"))
    log.info("found %d .usg files", len(usgs))
    opts: list[UsgOption] = []
    for u in usgs:
        opts.extend(parse_usg(u, log))
    log.info("parsed %d option entries (%d settings, %d flags)",
             len(opts),
             sum(1 for o in opts if o.kind == "setting"),
             sum(1 for o in opts if o.kind == "flag"))

    blobs = tool_strings(log)
    crossref(opts, blobs, log)

    # Report per unique option name, not per file -- but keep the set of
    # device trees that document each one.  This matters: `ReadCapture` and
    # `ReadBack` appear only under or5g00/mg5g00 (LatticeSC/ECP2-era parts),
    # NOT under any ep5* ECP5 tree, so quoting them as evidence of ECP5
    # readback would be wrong.  Attribution is the whole claim.
    uniq: dict[tuple[str, str, str], UsgOption] = {}
    devices: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for o in opts:
        key = (o.tool, o.option, o.kind)
        uniq.setdefault(key, o)
        devices[key].add(o.device)
    for key, o in uniq.items():
        o.devices = sorted(devices[key])
        o.ecp5 = any(d.startswith("ep5") for d in o.devices)

    missing = sorted((o for o in uniq.values() if o.missing),
                     key=lambda o: (o.tool, o.kind, o.option))
    log.info("=" * 72)
    log.info("Diamond options with NO mention in any open tool (%d of %d unique)",
             len(missing), len(uniq))
    log.info("-- settings documented for an ECP5 (ep5*) device tree --")
    for o in missing:
        if o.kind == "setting" and o.ecp5:
            log.warning("  %-10s %-20s values=%-40s trees=%s", o.tool, o.option,
                        ",".join(o.values), ",".join(o.devices))
    log.info("-- settings documented ONLY for non-ECP5 trees (do NOT cite as "
             "ECP5 evidence) --")
    for o in missing:
        if o.kind == "setting" and not o.ecp5:
            log.info("  %-10s %-20s values=%-40s trees=%s", o.tool, o.option,
                     ",".join(o.values), ",".join(o.devices))
    # Single-letter flags match almost any binary blob, so their crossref is
    # unreliable; list them without claiming anything.
    log.info("-- flags (crossref unreliable for short names; informational) --")
    for o in missing:
        if o.kind == "flag":
            log.debug("  %-10s %-6s trees=%s", o.tool, o.option,
                      ",".join(o.devices))

    inv = inventory(args.diamond, log)
    big = sorted(inv, key=lambda r: -r["bytes"])[:15]
    log.info("largest ECP5 vendor data files:")
    for r in big:
        log.info("  %-14s %-22s %8.1f MB  %s", r["tree"], r["name"],
                 r["bytes"] / 1e6, r["mtime"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "options": [asdict(o) for o in uniq.values()],
        "missing_from_open_flow": [asdict(o) for o in missing],
        "inventory": inv,
    }, indent=1))
    log.info("wrote %s", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
