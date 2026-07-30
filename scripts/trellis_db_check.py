#!/usr/bin/env python3.15t
"""Detectors for *incorrect* data in the prjtrellis bit database.

`validate_fuzz.py` answers "did this bitstream decode cleanly?".  This script
answers a different and harder question: "is the database itself self-consistent?"
That is what turned up the two known MachXO2 tool bugs -- `EBR.MODE` sitting at
the wrong bit address, and `PULLMODE=NONE` bits overlapping `BASE_TYPE`.  Both
were found by hand.  These detectors find that shape of bug mechanically, over
every tile of every family, with no Diamond run and no hardware.

Detectors, each independently reportable:

  D1 overlap-across-fields   two different config fields in the same tile claim
                             the same physical bit.  Setting one silently
                             corrupts the other.  This is the PULLMODE/BASE_TYPE
                             shape.
  D2 nonexclusive-enum       two values of the *same* enum have bit patterns
                             that cannot be told apart -- identical sets, or one
                             a subset of another with no distinguishing clear
                             bit.  Decode is then ambiguous: the database cannot
                             say which value a bitstream means.
  D3 duplicate-encoding      two enum values encode to exactly the same bits.
  D4 mux-bit-collision       a routing mux shares bits with a config field, or
                             two mux arcs of one sink are indistinguishable.
  D5 ragged-enum             values of one enum touch different bit *sets*,
                             leaving positions unconstrained -- often a sign the
                             fuzzer never swept the full cross-product.
  D6 word-overlap            a `.config` word's bit vector overlaps another
                             field, or repeats a position within itself.
  D7 empty-or-singleton      an enum with a single value carries no information;
                             usually an under-fuzzed field.

Every finding is emitted with tile, field, values and the exact bit positions,
so it can be checked against Diamond by hand or fed to the round-trip differ.

Usage:
    scripts/trellis_db_check.py [FAMILY ...]        # default: all families
Outputs `tmp/trellis_db_check-<family>.json` plus a summary, and logs to
`tmp/logs/trellis_db_check.log`.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trellis_db import DEFAULT_DB_ROOT, Bit, TileDb, load_family  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
OUT_DIR = REPO / "tmp"

ALL_FAMILIES = ["ECP5", "MachXO2", "MachXO3", "MachXO3D", "MachXO"]


@dataclass
class Finding:
    detector: str
    family: str
    tile: str
    field: str
    detail: str
    bits: list[str]
    severity: str = "warn"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("trellis_db_check")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "trellis_db_check.log", mode="w")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def _fmt(bits) -> list[str]:
    return sorted(str(b) for b in bits)


def _pos(bits) -> set[tuple[int, int]]:
    return {b.pos for b in bits}


def d1_overlap_across_fields(fam: str, db: TileDb) -> list[Finding]:
    """Two distinct config fields claiming the same physical bit.

    Legitimate only when the fields are alternative interpretations of one
    resource, which the database has no way to express -- so every hit is at
    minimum a documentation gap, and at worst the PULLMODE/BASE_TYPE bug.
    """
    owner: dict[tuple[int, int], set[str]] = defaultdict(set)
    for name, e in db.enums.items():
        for bs in e.values.values():
            for b in bs:
                owner[b.pos].add(name)
    for name, w in db.words.items():
        for b in (x for x in w.bits if x is not None):
            owner[b.pos].add(name)

    # Group by the exact set of colliding fields so one shared bit-range does
    # not explode into hundreds of near-identical findings.
    groups: dict[frozenset[str], list[tuple[int, int]]] = defaultdict(list)
    for pos, names in owner.items():
        if len(names) > 1:
            groups[frozenset(names)].append(pos)

    out = []
    for names, positions in sorted(groups.items(), key=lambda kv: sorted(kv[0])):
        # Fields sharing a prefix (IOLOGICA.MODE vs IOLOGICA.CEIMUX) are far
        # more suspicious than unrelated bels, but report both, flagged.
        prefixes = {n.split(".")[0] for n in names}
        sev = "error" if len(prefixes) == 1 else "warn"
        out.append(Finding(
            "D1-overlap-across-fields", fam, db.tile, " & ".join(sorted(names)),
            f"{len(positions)} bit(s) claimed by {len(names)} fields "
            f"({'same bel' if sev == 'error' else 'different bels'})",
            [f"F{f}B{b}" for f, b in sorted(positions)], sev))
    return out


def _decode_enum(values: dict[str, frozenset[Bit]],
                 tile: dict[tuple[int, int], bool]) -> str | None:
    """Reproduce prjtrellis `EnumSettingBits::get_value` exactly.

    From libtrellis/src/BitDatabase.cpp:242-267 --

        for (const auto &opt : options)
            if (opt.second.match(tile) && opt.second.bits.size() >= bestbits)
                bestmatch = opt, bestbits = opt.second.bits.size();

    `options` is a std::map, so iteration is in sorted key order, and `>=`
    means that among equally-long matches the *lexicographically last* value
    wins.  `match` requires every bit of the group to hold its stated polarity
    (BitDatabase.cpp:50-55); bit *count* includes inverted bits.

    Modelling this faithfully matters: a naive "subset implies ambiguity" test
    fires on thousands of encodings that longest-match resolves correctly.
    Only a genuine mis-decode is a finding.
    """
    best: str | None = None
    bestbits = 0
    for v in sorted(values):
        bs = values[v]
        if all(tile.get(b.pos, False) != b.invert for b in bs) and len(bs) >= bestbits:
            best, bestbits = v, len(bs)
    return best


def d2_enum_roundtrip(fam: str, db: TileDb) -> list[Finding]:
    """Encode each enum value, then decode it back, and check you get it again.

    This is the decisive self-consistency test and it needs no oracle: writing
    value V into an otherwise-blank tile and reading it back must yield V.  If
    it yields something else, then any bitstream Diamond produces with V set
    will be misreported by every open tool that reads the database.

    Encoding follows `EnumSettingBits::set_value` -- set the group's bits to
    their stated polarity, leave every other bit clear.
    """
    out = []
    for name, e in db.enums.items():
        if len(e.values) < 2:
            continue
        # Restrict the simulated tile to bits this field actually touches, so
        # unrelated fields cannot perturb the result.
        for v, bs in e.values.items():
            tile = {b.pos: (not b.invert) for b in bs}
            got = _decode_enum(e.values, tile)
            if got != v:
                # Distinguish "aliases an equal encoding" from "shadowed by a
                # longer one" -- different bugs with different fixes.
                if got is not None and e.values[got] == bs:
                    kind, sev = "aliases", "error"
                    why = (f"encodes identically to {got!r}; the two values are "
                           f"indistinguishable in any bitstream")
                else:
                    kind, sev = "shadowed", "error"
                    n = len(e.values[got]) if got else 0
                    why = (f"round-trips to {got!r} instead: writing {v!r} then "
                           f"reading back yields {got!r} "
                           f"({n} bits beats {len(bs)}, longest-match wins)")
                out.append(Finding(
                    f"D2-enum-roundtrip-{kind}", fam, db.tile, name,
                    f"value {v!r} {why}", _fmt(bs), sev))
    return out


def d3_duplicate_encoding(fam: str, db: TileDb) -> list[Finding]:
    """Two values of one enum with byte-identical encodings.

    Always a real defect: no bitstream can ever distinguish them, so one of the
    two names is unreachable on decode.  Reported separately from D2 because
    the fix differs -- usually the fuzzer conflated two settings that share
    bits but differ in some field it never varied.
    """
    out = []
    for name, e in db.enums.items():
        byenc: dict[frozenset[Bit], list[str]] = defaultdict(list)
        for v, bs in e.values.items():
            byenc[bs].append(v)
        for bs, vals in byenc.items():
            if len(vals) > 1:
                # An all-default (no bits) group for several values is the
                # common benign case: they are all "the default", and the
                # database records a defval to pick between them.
                sev = "warn" if not bs else "error"
                out.append(Finding(
                    "D3-duplicate-encoding", fam, db.tile, name,
                    f"values {sorted(vals)} all encode to the same bits -- "
                    f"decode can never distinguish them"
                    + (f" (default is {e.default!r})" if e.default else ""),
                    _fmt(bs), sev))
    return out


def d4_mux_bit_collision(fam: str, db: TileDb) -> list[Finding]:
    """Routing-mux bits shared with configuration, or ambiguous arcs."""
    out = []
    cfg_owner: dict[tuple[int, int], str] = {}
    for name, e in db.enums.items():
        for bs in e.values.values():
            for b in bs:
                cfg_owner.setdefault(b.pos, name)
    for name, w in db.words.items():
        for b in (x for x in w.bits if x is not None):
            cfg_owner.setdefault(b.pos, name)

    groups: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for sink, m in db.muxes.items():
        for arc in m.arcs:
            for b in arc.bits:
                if b.pos in cfg_owner:
                    groups[(sink, cfg_owner[b.pos])].append(b.pos)
    for (sink, cfg), positions in sorted(groups.items()):
        out.append(Finding(
            "D4-mux-bit-collision", fam, db.tile, f"mux {sink} & {cfg}",
            f"routing mux shares {len(set(positions))} bit(s) with config field",
            [f"F{f}B{b}" for f, b in sorted(set(positions))], "error"))

    # Routing round-trip: select each arc, decode, expect the same arc back.
    # `MuxBits::get_driver` (BitDatabase.cpp:113-129) uses the same
    # longest-match-wins rule as enums, so model it identically.
    for sink, m in db.muxes.items():
        arcs = {a.source: a.bits for a in m.arcs}
        if len(arcs) < 2:
            continue
        for src, bs in arcs.items():
            tile = {b.pos: (not b.invert) for b in bs}
            got = _decode_enum(arcs, tile)
            if got != src:
                same = got is not None and arcs[got] == bs
                out.append(Finding(
                    "D4-mux-roundtrip", fam, db.tile, f"mux {sink}",
                    f"arc from {src!r} "
                    + (f"encodes identically to {got!r}"
                       if same else
                       f"round-trips to {got!r} instead (longest-match wins)"),
                    _fmt(bs), "error"))
    return out


def d5_ragged_enum(fam: str, db: TileDb) -> list[Finding]:
    """Enum values that do not all constrain the same bit positions.

    A well-characterised enum names, for every value, the state of every bit in
    its field -- so the position sets agree and only the polarities differ.
    When they disagree, some bit is left unconstrained for some value, which
    means the fuzzer never observed that combination.  Under-characterisation,
    and a decode hazard.
    """
    out = []
    for name, e in db.enums.items():
        if len(e.values) < 2:
            continue
        sets = {v: _pos(bs) for v, bs in e.values.items() if bs}
        if len(sets) < 2:
            continue
        union = set().union(*sets.values())
        ragged = {v: sorted(union - s) for v, s in sets.items() if s != union}
        if ragged:
            worst = max(ragged.items(), key=lambda kv: len(kv[1]))
            out.append(Finding(
                "D5-ragged-enum", fam, db.tile, name,
                f"{len(ragged)}/{len(sets)} values leave bits unconstrained; "
                f"worst is {worst[0]!r} missing {len(worst[1])} of "
                f"{len(union)} field bits",
                [f"F{f}B{b}" for f, b in sorted(union)], "warn"))
    return out


def d6_word_overlap(fam: str, db: TileDb) -> list[Finding]:
    out = []
    for name, w in db.words.items():
        seen: dict[tuple[int, int], int] = {}
        dup = []
        for i, b in enumerate(w.bits):
            if b.pos in seen:
                dup.append(b.pos)
            seen[b.pos] = i
        if dup:
            out.append(Finding(
                "D6-word-repeated-bit", fam, db.tile, name,
                f"word bit vector lists {len(dup)} position(s) more than once",
                [f"F{f}B{b}" for f, b in sorted(set(dup))], "error"))
    return out


def d7_singleton_enum(fam: str, db: TileDb) -> list[Finding]:
    """A field with one value carries no information -- almost always
    an under-fuzzed field where only the default was ever observed."""
    out = []
    for name, e in db.enums.items():
        if len(e.values) == 1:
            v, bs = next(iter(e.values.items()))
            out.append(Finding(
                "D7-singleton-enum", fam, db.tile, name,
                f"only one value ever characterised ({v!r}); "
                f"the fuzzer never observed an alternative",
                _fmt(bs), "info"))
        elif len(e.values) == 0:
            out.append(Finding(
                "D7-empty-enum", fam, db.tile, name,
                "enum declared with no values at all", [], "error"))
    return out


DETECTORS = [
    d1_overlap_across_fields,
    d2_enum_roundtrip,
    d3_duplicate_encoding,
    d4_mux_bit_collision,
    d5_ragged_enum,
    d6_word_overlap,
    d7_singleton_enum,
]


def check_family(fam: str, log: logging.Logger) -> list[Finding]:
    try:
        tiles = load_family(fam, DEFAULT_DB_ROOT)
    except FileNotFoundError as exc:
        log.error("%s: %s", fam, exc)
        return []
    log.info("%s: loaded %d tiles", fam, len(tiles))
    findings: list[Finding] = []
    for db in tiles.values():
        for det in DETECTORS:
            findings.extend(det(fam, db))
    return findings


def main(argv: list[str]) -> int:
    log = setup_logging()
    fams = argv[1:] or ALL_FAMILIES
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    grand: dict[str, dict[str, int]] = {}
    for fam in fams:
        findings = check_family(fam, log)
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            counts[f.detector] += 1
        grand[fam] = dict(counts)

        out = OUT_DIR / f"trellis_db_check-{fam}.json"
        out.write_text(json.dumps([asdict(f) for f in findings], indent=1))
        log.info("%s: %d findings -> %s", fam, len(findings), out)
        for det in sorted(counts):
            sev = {f.severity for f in findings if f.detector == det}
            log.info("  %-26s %5d  (%s)", det, counts[det], "/".join(sorted(sev)))

        # Surface the highest-value hits inline so a re-run is readable
        # without opening the JSON.
        for f in findings:
            if f.severity == "error" and f.detector.startswith(("D1", "D2", "D3")):
                log.warning("  %s %s/%s: %s [%s]", f.detector, f.tile, f.field,
                            f.detail, ", ".join(f.bits[:8]))

    log.info("summary: %s", json.dumps(grand))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
