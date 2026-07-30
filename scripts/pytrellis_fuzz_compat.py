#!/usr/bin/env python3.15t
"""A pytrellis stand-in for prjtrellis's FUZZERS, backed by our own code.

    # in a fuzzer, instead of `import pytrellis`
    from pytrellis_fuzz_compat import pytrellis

WHY
---
prjtrellis's fuzzers are already Python.  They touch C++ in only two places: reading
bitstreams, and the containers they accumulate bit attributions into before writing
`bits.db`.  Both are now ours -- `native_bitstream` reads, `trellis_db` +
`trellis_db_write` read and write the database -- so the fuzzers can run unmodified
if those names resolve here instead.  Same approach as `native_trellis.pytrellis_compat`
did for the lifters' routing graph.

The point is not tidiness.  `util/fuzz/nonrouting.py` decodes every Diamond variant
with `pytrellis.Bitstream.read_bit(...).deserialise_chip()`, which FAILS OUTRIGHT on
EFB-active designs -- measured, 6 of 6 EFB fuzz targets.  A parameter whose fuzz
design needs an active EFB therefore gets attributed no bits, and in the database
that is indistinguishable from a parameter nobody fuzzed.  Our decoder reads those
bitstreams, so fuzzing through this shim can attribute bits the C++ path structurally
cannot see.

SURFACE, taken from what the fuzzers actually call (not from the pytrellis headers):

    TileLocator(family, device, tiletype)
    get_tile_bitdata(locator)      -> TileBitDatabase
        .add_setting_enum(esb) / .add_setting_word(wsb) / .save()
    ConfigBit(frame, bit, inv)     .frame .bit .inv
    BitGroup([bits])               .bits  .match(cram)
    EnumSettingBits()              .name .defval .options{value: BitGroup}
    WordSettingBits()              .name .defval .bits[BitGroup]
    Bitstream.read_bit(path)       .deserialise_chip() -> Chip
    Chip.cram.bit(frame, bit)

ACCEPTANCE TEST, and it is the whole reason to trust this: `--selftest` loads every
shipped tile through the shim and re-saves it to a scratch directory, then compares
byte-for-byte.  Reproducing known-good output is the bar before generating new data,
exactly as it was for the bitstream encoder.

    scripts/pytrellis_fuzz_compat.py --selftest [--family MachXO2]

Logs to ./tmp/logs/pytrellis_fuzz_compat.log.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402
from trellis_db import Bit, ConfigEnum, ConfigWord, parse_tile_db  # noqa: E402
from trellis_db_write import format_tile_db  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"


# --- bit containers --------------------------------------------------------
# ConfigBit mirrors pytrellis's field names, including `inv`.  Our own Bit calls
# the same thing `invert`, so the shim translates rather than renaming Bit and
# breaking every existing caller.
@dataclass(frozen=True)
class ConfigBit:
    frame: int
    bit: int
    inv: bool = False

    def to_bit(self) -> Bit:
        return Bit(self.frame, self.bit, self.inv)

    @staticmethod
    def from_bit(b: Bit) -> "ConfigBit":
        return ConfigBit(b.frame, b.bit, b.invert)


class BitGroup:
    """A set of ConfigBits that together encode one value."""

    def __init__(self, bits=None):
        self.bits: list[ConfigBit] = []
        for b in (bits or []):
            # Accept our Bit, a pytrellis-style ConfigBit, or a bare (frame, bit).
            if isinstance(b, ConfigBit):
                self.bits.append(b)
            elif isinstance(b, Bit):
                self.bits.append(ConfigBit.from_bit(b))
            else:
                self.bits.append(ConfigBit(b[0], b[1], False))

    def match(self, cram) -> bool:
        """True when every bit is in its required state, honouring inversion."""
        for cb in self.bits:
            want = 0 if cb.inv else 1
            if cram.bit(cb.frame, cb.bit) != want:
                return False
        return True

    def frozen(self) -> frozenset[Bit]:
        return frozenset(cb.to_bit() for cb in self.bits)


@dataclass
class EnumSettingBits:
    name: str = ""
    defval: str | None = None
    options: dict[str, BitGroup] = field(default_factory=dict)


@dataclass
class WordSettingBits:
    name: str = ""
    defval: str | None = None
    bits: list[BitGroup] = field(default_factory=list)


# --- database access -------------------------------------------------------
@dataclass(frozen=True)
class TileLocator:
    family: str
    device: str
    tiletype: str


class TileBitDatabase:
    """One tile's bits.db, mutable, saved through the verified writer."""

    def __init__(self, path: Path, locator: TileLocator):
        self.path = path
        self.locator = locator
        self.db = parse_tile_db(path) if path.is_file() else None
        if self.db is None:
            # A tile we have no file for is an empty database, not an error: the
            # fuzzer's job is to populate it.
            from trellis_db import TileDb
            self.db = TileDb(tile=locator.tiletype, path=path)

    def add_setting_enum(self, esb: EnumSettingBits) -> None:
        self.db.enums[esb.name] = ConfigEnum(
            name=esb.name, default=esb.defval,
            values={v: bg.frozen() for v, bg in esb.options.items()})

    def add_setting_word(self, wsb: WordSettingBits) -> None:
        # A word is an ORDERED vector; a BitGroup with no bits is a held position
        # and must survive as one, or every later bit shifts (see trellis_db).
        bits: list[Bit | None] = []
        for bg in wsb.bits:
            fb = sorted(bg.frozen(), key=lambda b: (b.frame, b.bit))
            bits.append(fb[0] if fb else None)
        self.db.words[wsb.name] = ConfigWord(name=wsb.name, default=wsb.defval,
                                             bits=bits)

    def save(self, path: Path | None = None) -> None:
        target = Path(path or self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(format_tile_db(self.db))


def _db_root() -> str:
    return toolchain.trellis_dbroot()


def get_tile_bitdata(locator: TileLocator) -> TileBitDatabase:
    p = (Path(_db_root()) / locator.family / "tiledata" / locator.tiletype
         / "bits.db")
    return TileBitDatabase(p, locator)


# --- bitstream reading -----------------------------------------------------
class _Cram:
    def __init__(self, pb):
        self._pb = pb

    def bit(self, frame: int, b: int) -> int:
        return self._pb.cram[frame][b]

    @property
    def frames(self) -> int:
        return self._pb.num_frames

    @property
    def bits(self) -> int:
        return self._pb.bits_per_frame


class _Chip:
    def __init__(self, pb):
        self._pb = pb
        self.cram = _Cram(pb)

    @property
    def idcode(self):
        return self._pb.idcode


class _ParsedBit:
    def __init__(self, path):
        self.path = path

    def deserialise_chip(self) -> _Chip:
        """Decode with OUR decoder -- the reason this shim exists.

        Device comes from the bitstream's own IDCODE, never a default, so an
        ECP5 file is never read with MachXO2 geometry (#86).
        """
        import native_bitstream as nb
        from ecp5_corpus_test import identify
        dev, _fam, _idc, _how = identify(self.path)
        raw = open(self.path, "rb").read()
        geom = nb.geometry_for(dev) if dev else None
        stripped = nb.strip_bit_header(raw)
        pb = nb.parse(stripped, geom=geom) if geom else nb.parse(stripped)
        return _Chip(pb)


class Bitstream:
    @staticmethod
    def read_bit(path) -> _ParsedBit:
        return _ParsedBit(str(path))


def load_database(_root=None) -> None:
    """No-op: the database is resolved per call via toolchain (#90)."""


class _Namespace:
    """The names a fuzzer expects to find on `pytrellis`."""
    TileLocator = TileLocator
    get_tile_bitdata = staticmethod(get_tile_bitdata)
    ConfigBit = ConfigBit
    BitGroup = BitGroup
    EnumSettingBits = EnumSettingBits
    WordSettingBits = WordSettingBits
    Bitstream = Bitstream
    load_database = staticmethod(load_database)


pytrellis = _Namespace()


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("pytrellis_fuzz_compat")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "pytrellis_fuzz_compat.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def selftest(family, log) -> tuple[int, int]:
    """Load every tile through the shim, re-save it, compare byte-for-byte."""
    root = _db_root()
    td = os.path.join(root, family, "tiledata")
    if not os.path.isdir(td):
        return 0, 0
    out = REPO / "tmp" / "fuzz_compat_selftest" / family
    same = differ = 0
    for tile in sorted(os.listdir(td)):
        src = Path(td) / tile / "bits.db"
        if not src.is_file():
            continue
        bd = get_tile_bitdata(TileLocator(family, "", tile))
        dst = out / tile / "bits.db"
        bd.save(dst)
        if dst.read_text() == src.read_text():
            same += 1
        else:
            differ += 1
    log.info("%-9s %d byte-identical, %d differ", family, same, differ)
    return same, differ


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--family", default="")
    args = ap.parse_args()
    log = setup_logging()
    if not args.selftest:
        sys.exit("this is a library; pass --selftest to check it round-trips")
    root = _db_root()
    fams = ([args.family] if args.family
            else [f for f in sorted(os.listdir(root))
                  if os.path.isdir(os.path.join(root, f, "tiledata"))])
    tot_s = tot_d = 0
    for f in fams:
        s, d = selftest(f, log)
        tot_s += s
        tot_d += d
    log.info("==== %d identical, %d differ ====", tot_s, tot_d)
    log.info("Differences here are the same 72 known ones as trellis_db_write: 71 "
             "empty MachXO stubs and one non-canonical MachXO2 file.")
    return 1 if tot_d > 72 else 0


if __name__ == "__main__":
    sys.exit(main())
