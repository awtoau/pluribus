#!/usr/bin/env python3.15t
"""Build the four-way ECP5 open-toolchain coverage matrix.

For every primitive Diamond ships a simulation model for, ask:

  1. Diamond    -- does the primitive exist?           (cae_library .v files)
  2. prjtrellis -- are its bits characterised?         (fuzzers + tiledata enums)
  3. yosys      -- is it declared?                     (cells_bb.v / cells_sim.v)
  4. nextpnr    -- can it place / route / emit?        (constids + pack.cc + bitstream.cc)

The interesting rows are where 1-3 hold and 4 does not: the data exists and the
place-and-route tool cannot use it.  Those are implementable gaps, not research
problems.

Writes a markdown matrix to docs/ecp5-gap-matrix.md and logs to tmp/logs/.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Paths.  Resolved, never hardcoded (#90) -- see scripts/toolchain.py.  None of
# them are written to except our own outputs.
#
# The three third-party checkouts (prjtrellis, nextpnr) are `required=False`,
# because this matrix's whole job is to report what each tool is missing: a tool
# that is simply absent must show up as "not compared", not stop the run.
# --------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import toolchain  # noqa: E402  (path set above)

DIAMOND_ECP5U = (Path(toolchain.diamond_root())
                 / "cae_library/simulation/verilog/ecp5u")
_TRELLIS_SRC = toolchain.sibling_repo("prjtrellis", "PRJTRELLIS_ROOT",
                                      "prjtrellis checkout", required=False)
TRELLIS_FUZZ = Path(_TRELLIS_SRC) / "fuzzers/ECP5" if _TRELLIS_SRC else None
TRELLIS_DB = Path(toolchain.trellis_dbroot()) / "ECP5/tiledata"
YOSYS_ECP5 = Path(toolchain.suite_share("yosys", "ecp5", required=True))
_NEXTPNR = toolchain.sibling_repo("nextpnr", "NEXTPNR_ROOT",
                                 "nextpnr checkout", required=False)
NEXTPNR_ECP5 = Path(_NEXTPNR) / "ecp5" if _NEXTPNR else None

LOG_DIR = REPO / "tmp/logs"
OUT_DOC = REPO / "docs/ecp5-gap-matrix.md"
OUT_JSON = REPO / "tmp/ecp5_gap_matrix.json"

# Pure combinational / soft primitives that Yosys implements natively via
# techmap rather than as a hard block.  They are not "gaps" -- there is no
# fabric resource behind them, they become LUTs.  Recorded so the matrix does
# not drown in 90 rows of AND2/XOR3/MUX41.
SOFT_PREFIXES = (
    "AND", "OR", "ND", "NR", "XOR", "XNOR", "INV", "MUX", "L6MUX",
    "LUT", "lut_", "PFUMX", "PFMUX", "FD1", "FL1", "UDFDL", "ROM",
    "SPR16", "DPR16", "CCU2", "SCCU2", "SLOGICB", "SDPRAME", "SRAMWB",
)
# IO buffer primitives: Yosys/nextpnr model these as TRELLIS_IO with a DIR
# attribute rather than as distinct cell types.  Not gaps either.
IO_BUF = {
    "IB", "OB", "BB", "OBZ", "IBPU", "IBPD", "BBPU", "BBPD", "OBZPU", "OBZPD",
    "ILVDS", "OLVDS", "BCLVDSOB", "LVDSOB", "OBCO", "INRDB", "BCINRD", "IMIPI",
}


@dataclass
class Row:
    name: str
    diamond: bool = True
    fuzzers: list[str] = field(default_factory=list)
    db_tiles: list[str] = field(default_factory=list)
    yosys_bb: bool = False
    yosys_sim: bool = False
    np_constid: bool = False
    np_pack: int = 0
    np_bitstream: int = 0
    np_cells: int = 0
    category: str = ""

    @property
    def trellis(self) -> bool:
        return bool(self.fuzzers or self.db_tiles)

    @property
    def yosys(self) -> bool:
        return self.yosys_bb or self.yosys_sim

    @property
    def nextpnr(self) -> bool:
        """nextpnr can actually *do* something with it, not merely name it."""
        return self.np_pack > 0 or self.np_bitstream > 0 or self.np_cells > 0


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("ecp5_gap_matrix")
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "ecp5_gap_matrix.log", mode="w")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def classify(name: str) -> str:
    if name in IO_BUF:
        return "io-buffer (TRELLIS_IO)"
    if name.startswith(SOFT_PREFIXES):
        return "soft (techmap to LUT/FF/DRAM)"
    return "hard block"


def diamond_primitives(log) -> list[str]:
    if not DIAMOND_ECP5U.is_dir():
        log.error("Diamond ecp5u library not found at %s", DIAMOND_ECP5U)
        return []
    names = sorted({p.stem for p in DIAMOND_ECP5U.glob("*.v")})
    log.info("Diamond ecp5u: %d primitive .v files", len(names))
    return names


def fuzzer_index(log) -> dict[str, list[str]]:
    """Map primitive name -> fuzzers that mention it.

    Fuzzers drive Diamond through NCL, so the primitive name shows up as a
    cellmodel-name / comp reference.  Grep every file in each fuzzer dir.
    """
    idx: dict[str, list[str]] = {}
    if TRELLIS_FUZZ is None or not TRELLIS_FUZZ.is_dir():
        log.error("prjtrellis ECP5 fuzzers not found (%s); set $PRJTRELLIS_ROOT "
                  "or check prjtrellis out beside this repo", TRELLIS_FUZZ)
        return idx
    blobs: dict[str, str] = {}
    for d in sorted(TRELLIS_FUZZ.iterdir()):
        if not d.is_dir():
            continue
        text = []
        for f in d.rglob("*"):
            if f.is_file() and f.suffix in {".py", ".ncl", ".v", ".vhd", ".lpf", ".txt", ".json"}:
                try:
                    text.append(f.read_text(errors="replace"))
                except OSError:
                    pass
        blobs[d.name] = "\n".join(text)
    log.info("indexed %d ECP5 fuzzer directories", len(blobs))
    return blobs  # type: ignore[return-value]


def db_enum_index(log) -> dict[str, set[str]]:
    """Map uppercase token -> set of tiles whose bit database mentions it.

    The tiledata JSON files hold, per tile type, the enums and words that
    prjtrellis has characterised.  A primitive name will not usually appear
    verbatim (the database speaks in tile/enum names like IOLOGIC.MODE), so we
    index every enum and word name and match primitives against them later.
    """
    idx: dict[str, set[str]] = {}
    if not TRELLIS_DB.is_dir():
        log.error("trellis tiledata not found at %s", TRELLIS_DB)
        return idx
    n = 0
    for tile in sorted(TRELLIS_DB.iterdir()):
        cfg = tile / "config.json"
        if not cfg.is_file():
            continue
        n += 1
        try:
            data = json.loads(cfg.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("cannot parse %s: %s", cfg, exc)
            continue
        for section in ("enums", "words"):
            for key in data.get(section, {}):
                idx.setdefault(key.upper(), set()).add(tile.name)
    log.info("indexed %d ECP5 tile config.json files, %d distinct enum/word keys",
             n, len(idx))
    return idx


def yosys_cells(log) -> tuple[set[str], set[str]]:
    def mods(path: Path) -> set[str]:
        if not path.is_file():
            log.warning("missing %s", path)
            return set()
        return set(re.findall(r"^\s*module\s+(\w+)", path.read_text(), re.M))

    bb = mods(YOSYS_ECP5 / "cells_bb.v")
    sim = mods(YOSYS_ECP5 / "cells_sim.v")
    log.info("yosys ecp5: %d blackbox, %d sim modules", len(bb), len(sim))
    return bb, sim


def nextpnr_index(log) -> tuple[set[str], dict[str, int], dict[str, int], dict[str, int]]:
    def read(name: str) -> str:
        if NEXTPNR_ECP5 is None:
            log.warning("nextpnr not found; set $NEXTPNR_ROOT or check it out "
                        "beside this repo. %s not compared", name)
            return ""
        p = NEXTPNR_ECP5 / name
        if not p.is_file():
            log.warning("missing %s", p)
            return ""
        return p.read_text()

    constids = set(re.findall(r"^X\((\w+)\)", read("constids.inc"), re.M))
    log.info("nextpnr-ecp5 constids.inc: %d ids", len(constids))

    counts: list[dict[str, int]] = []
    for fn in ("pack.cc", "bitstream.cc", "cells.cc"):
        text = read(fn)
        # Match the full identifier after id_, anchored on both sides.  A
        # sloppier pattern makes id_DDRDLL look like a hit for "DLL" and
        # id_PURPOSE like a hit for "PUR" -- which produced a wrong verdict
        # for PUR before this was tightened.
        c: dict[str, int] = {}
        for m in re.finditer(r"(?<![A-Za-z0-9_])id_([A-Za-z0-9_]+)", text):
            c[m.group(1)] = c.get(m.group(1), 0) + 1
        counts.append(c)
        log.info("nextpnr-ecp5 %s: %d distinct id_ references", fn, len(c))
    return constids, counts[0], counts[1], counts[2]


def build(log) -> list[Row]:
    prims = diamond_primitives(log)
    fuzz_blobs = fuzzer_index(log)
    dbidx = db_enum_index(log)
    ybb, ysim = yosys_cells(log)
    constids, npack, nbits, ncells = nextpnr_index(log)

    rows: list[Row] = []
    for name in prims:
        r = Row(name=name)
        r.category = classify(name)
        # A fuzzer "covers" a primitive if the primitive name appears as a
        # whole word in any of that fuzzer's source files.
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        r.fuzzers = [d for d, blob in fuzz_blobs.items() if pat.search(blob)]
        r.db_tiles = sorted(dbidx.get(name.upper(), ()))
        r.yosys_bb = name in ybb
        r.yosys_sim = name in ysim
        r.np_constid = name in constids
        r.np_pack = npack.get(name, 0)
        r.np_bitstream = nbits.get(name, 0)
        r.np_cells = ncells.get(name, 0)
        rows.append(r)
    return rows


def verdict(r: Row) -> str:
    """The 'implementable gap' column."""
    if r.category != "hard block":
        return "n/a - " + r.category.split(" ")[0]
    if not r.trellis and not r.yosys and not r.nextpnr:
        return "DATA GAP (needs fuzzing)"
    if r.trellis and not r.yosys:
        return "DATA GAP (bits known, yosys undeclared)"
    if r.yosys and not r.nextpnr:
        return "**IMPLEMENTABLE GAP**"
    if r.nextpnr:
        return "covered"
    return "review"


def render(rows: list[Row]) -> str:
    hard = [r for r in rows if r.category == "hard block"]
    other = [r for r in rows if r.category != "hard block"]
    out: list[str] = []
    out.append("# ECP5 four-way toolchain coverage matrix\n")
    out.append("Generated by `scripts/ecp5_gap_matrix.py`. Do not hand-edit the\n"
               "tables; edit the script and regenerate.\n")
    out.append(f"\nCounts: {len(rows)} Diamond primitives, {len(hard)} hard blocks, "
               f"{len(other)} soft/IO-buffer.\n")
    out.append("\n## Hard blocks\n")
    out.append("| Primitive | prjtrellis fuzzers | trellis db | yosys bb | yosys sim | "
               "np constid | np pack | np bitstream | np cells | verdict |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(hard, key=lambda x: x.name):
        fz = ", ".join(sorted(r.fuzzers)) if r.fuzzers else "-"
        db = f"{len(r.db_tiles)} tiles" if r.db_tiles else "-"
        out.append(
            f"| `{r.name}` | {fz} | {db} | {'Y' if r.yosys_bb else '-'} | "
            f"{'Y' if r.yosys_sim else '-'} | {'Y' if r.np_constid else '-'} | "
            f"{r.np_pack or '-'} | {r.np_bitstream or '-'} | {r.np_cells or '-'} | "
            f"{verdict(r)} |")
    out.append("\n## Soft / IO-buffer primitives (not gaps)\n")
    out.append("| Primitive | category |")
    out.append("|---|---|")
    for r in sorted(other, key=lambda x: x.name):
        out.append(f"| `{r.name}` | {r.category} |")
    return "\n".join(out) + "\n"


def main() -> int:
    log = setup_logging()
    rows = build(log)
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(render(rows))
    OUT_JSON.write_text(json.dumps(
        [{**r.__dict__, "verdict": verdict(r)} for r in rows], indent=1))
    log.info("wrote %s and %s", OUT_DOC, OUT_JSON)

    for r in sorted(rows, key=lambda x: x.name):
        v = verdict(r)
        if "GAP" in v:
            log.warning("%-14s %s  (fuzzers=%s yosys_bb=%s np_pack=%d)",
                        r.name, v, r.fuzzers or "-", r.yosys_bb, r.np_pack)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
