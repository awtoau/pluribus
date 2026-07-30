#!/usr/bin/env python3.15t
"""Parser for prjtrellis `bits.db` tile databases (ECP5 / MachXO2 / MachXO3).

The database is the ground truth the whole open toolchain rests on: it maps
configuration bit positions to human-readable mux arcs, enums and words.  If it
is wrong, every tool downstream is wrong in the same way and nothing complains.

Format (whitespace-significant, sections separated by blank lines):

    # comment
    .mux <SINK_WIRE>
    <SOURCE_WIRE> <bits...>          # "-" means the all-zero / default arc

    .config <ENUM>.<FIELD> <default> # a "word": ordered list of bit positions
    <bit>
    <bit>

    .config_enum <ENUM>.<FIELD> [default]
    <VALUE> <bits...>                # "-" means the all-zero encoding

    .fixed_conn <SINK> <SOURCE>      # hardwired connection, consumes no bits

A bit position is `F<frame>B<bit>`, optionally prefixed with `!` meaning the
bit must be *clear* for this encoding to match.

This module is a library; `trellis_db_check.py` is the detector that uses it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB_ROOT = Path("/home/dan/opt/oss-cad-suite/share/trellis/database")

_BIT_RE = re.compile(r"^(!?)F(\d+)B(\d+)$")


@dataclass(frozen=True)
class Bit:
    """A single configuration bit reference, with its required polarity."""

    frame: int
    bit: int
    invert: bool = False

    @property
    def pos(self) -> tuple[int, int]:
        """Position only, ignoring polarity -- for overlap analysis."""
        return (self.frame, self.bit)

    def __str__(self) -> str:
        return f"{'!' if self.invert else ''}F{self.frame}B{self.bit}"


def parse_bits(tokens: list[str]) -> frozenset[Bit]:
    """Parse a whitespace-split list of bit tokens.

    `-` on its own is prjtrellis's notation for "no bits set" (the default
    encoding), and yields the empty set rather than an error.
    """
    out: set[Bit] = set()
    for tok in tokens:
        if tok == "-":
            continue
        m = _BIT_RE.match(tok)
        if not m:
            raise ValueError(f"unparseable bit token {tok!r}")
        out.add(Bit(int(m.group(2)), int(m.group(3)), m.group(1) == "!"))
    return frozenset(out)


@dataclass
class MuxArc:
    source: str
    bits: frozenset[Bit]


@dataclass
class Mux:
    sink: str
    arcs: list[MuxArc] = field(default_factory=list)


@dataclass
class ConfigEnum:
    """`.config_enum` -- a named field with a set of symbolic values."""

    name: str
    default: str | None
    values: dict[str, frozenset[Bit]] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        """The bel/primitive the enum belongs to, e.g. IOLOGICA of IOLOGICA.MODE."""
        return self.name.split(".")[0]


@dataclass
class ConfigWord:
    """`.config` -- a field encoded as an ordered vector of bits."""

    name: str
    default: str | None
    bits: list[Bit] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        return self.name.split(".")[0]


@dataclass
class TileDb:
    tile: str
    path: Path
    muxes: dict[str, Mux] = field(default_factory=dict)
    enums: dict[str, ConfigEnum] = field(default_factory=dict)
    words: dict[str, ConfigWord] = field(default_factory=dict)
    fixed_conns: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def all_config_bits(self) -> set[tuple[int, int]]:
        pos: set[tuple[int, int]] = set()
        for e in self.enums.values():
            for bs in e.values.values():
                pos |= {b.pos for b in bs}
        for w in self.words.values():
            pos |= {b.pos for b in w.bits}
        return pos

    def all_mux_bits(self) -> set[tuple[int, int]]:
        pos: set[tuple[int, int]] = set()
        for m in self.muxes.values():
            for a in m.arcs:
                pos |= {b.pos for b in a.bits}
        return pos


def parse_tile_db(path: Path) -> TileDb:
    """Parse one tile's bits.db.  Never raises: malformed lines land in .errors."""
    db = TileDb(tile=path.parent.name, path=path)
    section: str | None = None  # 'mux' | 'enum' | 'word'
    cur_mux: Mux | None = None
    cur_enum: ConfigEnum | None = None
    cur_word: ConfigWord | None = None

    for lineno, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        head = parts[0]

        if head == ".mux":
            cur_mux = Mux(sink=parts[1])
            # A tile may legitimately not repeat a sink; if it does, merge.
            if parts[1] in db.muxes:
                cur_mux = db.muxes[parts[1]]
            else:
                db.muxes[parts[1]] = cur_mux
            section, cur_enum, cur_word = "mux", None, None
            continue
        if head == ".config":
            cur_word = ConfigWord(name=parts[1],
                                  default=parts[2] if len(parts) > 2 else None)
            db.words[parts[1]] = cur_word
            section, cur_mux, cur_enum = "word", None, None
            continue
        if head == ".config_enum":
            cur_enum = ConfigEnum(name=parts[1],
                                  default=parts[2] if len(parts) > 2 else None)
            db.enums[parts[1]] = cur_enum
            section, cur_mux, cur_word = "enum", None, None
            continue
        if head == ".fixed_conn":
            # Hardwired sink<-source; no configuration bits involved, so it is
            # irrelevant to overlap analysis but must not be mistaken for data.
            db.fixed_conns.append((parts[1], parts[2]))
            section, cur_mux, cur_enum, cur_word = None, None, None, None
            continue
        if head.startswith("."):
            db.errors.append(f"{path}:{lineno}: unknown directive {head}")
            section = None
            continue

        try:
            if section == "mux" and cur_mux is not None:
                cur_mux.arcs.append(MuxArc(parts[0], parse_bits(parts[1:])))
            elif section == "enum" and cur_enum is not None:
                cur_enum.values[parts[0]] = parse_bits(parts[1:])
            elif section == "word" and cur_word is not None:
                # A word body is one bare bit token per line, MSB first.
                cur_word.bits.extend(sorted(parse_bits(parts), key=lambda b: b.pos))
            else:
                db.errors.append(f"{path}:{lineno}: data outside any section: {line!r}")
        except ValueError as exc:
            db.errors.append(f"{path}:{lineno}: {exc}")
    return db


def load_family(family: str, root: Path = DEFAULT_DB_ROOT) -> dict[str, TileDb]:
    """Load every tile database for a device family, keyed by tile type name."""
    tiledata = root / family / "tiledata"
    if not tiledata.is_dir():
        raise FileNotFoundError(f"no tiledata for {family} under {root}")
    out: dict[str, TileDb] = {}
    for d in sorted(tiledata.iterdir()):
        f = d / "bits.db"
        if f.is_file():
            out[d.name] = parse_tile_db(f)
    return out


if __name__ == "__main__":
    import sys

    fam = sys.argv[1] if len(sys.argv) > 1 else "ECP5"
    tiles = load_family(fam)
    ne = sum(len(t.enums) for t in tiles.values())
    nw = sum(len(t.words) for t in tiles.values())
    nm = sum(len(t.muxes) for t in tiles.values())
    err = sum(len(t.errors) for t in tiles.values())
    print(f"{fam}: {len(tiles)} tiles, {nm} muxes, {ne} enums, {nw} words, {err} parse errors")
    for t in tiles.values():
        for e in t.errors[:5]:
            print("  ", e)
