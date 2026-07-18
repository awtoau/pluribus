#!/usr/bin/env python3
"""Native MachXO2 tile decode (pluribus issue #35, P4).

Turns the verified CRAM bit-matrix (from ``native_bitstream.py``) into a
per-tile ``{arcs, words, enums}`` configuration -- i.e. produces the prjtrellis
``.config`` natively, without pytrellis.  This is a faithful Python port of
prjtrellis ``TileBitDatabase::tile_cram_to_config`` (see
``libtrellis/src/BitDatabase.cpp``) driven by the same ``bits.db`` /
``tilegrid.json`` database.

Decode is embarrassingly parallel across tile instances: each tile reads a
disjoint rectangle of the global CRAM and its (read-only) type database.  Under
python3.14t (free-threaded / NoGIL) we fan the tiles out over a thread pool.
The hot path touches only plain dict/list/set/tuple/bytearray -- no
sqlalchemy, no GIL re-enable.

Database format (text), per tile TYPE, relative to the tile origin:
  * ``.mux SINK`` then lines ``SOURCE  Fx By [Fx By ...]``  -- routing arcs.
  * ``.config NAME [defval]`` then one BitGroup per line       -- config words.
  * ``.config_enum NAME [defval]`` then ``OPT  Fx By ...``     -- config enums.
  * ``.fixed_conn ...`` (parsed, ignored for decode).
A bit token is ``[!]F<frame>B<bit>``; ``!`` means the bit must be 0 to match.
``F``/``B`` are tile-LOCAL coordinates; global CRAM = (start_frame + F,
start_bit + B), matching ``CRAMView::bit`` and ``get_device_tilegrid``.
"""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

DEFAULT_DB_ROOT = os.environ.get("TRELLIS_DBROOT", "tmp/prjtrellis/database")
FAMILY = "MachXO2"

# Pluribus-owned corrections applied on top of the base tiledata (issue #29) —
# see db_overrides.py. Kept local to pluribus so they survive a DB re-clone.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_overrides import apply_overrides as _apply_db_overrides  # noqa: E402


# ---------------------------------------------------------------------------
# bits.db parsing
# ---------------------------------------------------------------------------

def _cbit(tok):
    """Parse a bit token '[!]F<frame>B<bit>' -> (frame, bit, inv)."""
    inv = False
    i = 0
    if tok[0] == "!":
        inv = True
        i = 1
    assert tok[i] == "F", tok
    bpos = tok.index("B", i)
    frame = int(tok[i + 1:bpos])
    bit = int(tok[bpos + 1:])
    return (frame, bit, inv)


def _bitgroup(tokens):
    """A BitGroup is a frozenset of cbits; a lone '-' means empty."""
    bits = []
    for t in tokens:
        if t == "-":
            break
        bits.append(_cbit(t))
    return frozenset(bits)


class TileType:
    """Parsed decode database for one tile TYPE."""
    __slots__ = ("muxes", "words", "enums")

    def __init__(self):
        # sink -> list of (source, bitgroup), sorted by source
        self.muxes = {}
        # name -> (defval tuple[bool], list[bitgroup])
        self.words = {}
        # name -> (defval or None, dict option->bitgroup)
        self.enums = {}


def parse_bits_db(path):
    tt = TileType()
    # Strip comments (# to EOL) and keep raw lines; blank lines inside a record
    # are skipped by the C++ reader, records are delimited by '.' directives.
    with open(path) as fh:
        raw = [ln.split("#", 1)[0] for ln in fh]

    # Build a list of (directive_tokens, [entry_token_lists]) records.
    n = len(raw)
    i = 0
    while i < n:
        toks = raw[i].split()
        if not toks:
            i += 1
            continue
        directive = toks[0]
        head = toks
        i += 1
        entries = []
        while i < n:
            etoks = raw[i].split()
            if not etoks:
                i += 1
                continue
            if etoks[0].startswith("."):
                break
            entries.append(etoks)
            i += 1

        if directive == ".mux":
            sink = head[1]
            arcs = []
            for e in entries:
                arcs.append((e[0], _bitgroup(e[1:])))
            arcs.sort(key=lambda a: a[0])
            tt.muxes[sink] = arcs
        elif directive == ".config":
            name = head[1]
            have_default = len(head) > 2
            defstr = head[2] if have_default else None
            groups = [_bitgroup(e) for e in entries]
            if have_default:
                # to_string reverses the vector; reading reverses back so
                # defval[i] corresponds to groups[i].
                defval = tuple(c == "1" for c in reversed(defstr))
            else:
                defval = tuple(False for _ in groups)
            tt.words[name] = (defval, groups)
        elif directive == ".config_enum":
            name = head[1]
            defval = head[2] if len(head) > 2 else None
            options = {}
            for e in entries:
                options[e[0]] = _bitgroup(e[1:])
            tt.enums[name] = (defval, options)
        elif directive == ".fixed_conn":
            pass  # not used for tile decode
        else:
            raise RuntimeError(f"{path}: unexpected directive {directive!r}")
    return tt


_db_cache = {}
_frozen_cache_len = -1   # cache size at the last immortalization freeze
_db_lock = threading.Lock()


def get_tile_type(tiletype, db_root=DEFAULT_DB_ROOT, family=FAMILY):
    key = (family, tiletype)
    tt = _db_cache.get(key)
    if tt is None:
        with _db_lock:
            tt = _db_cache.get(key)
            if tt is None:
                path = os.path.join(db_root, family, "tiledata", tiletype,
                                    "bits.db")
                tt = parse_bits_db(path)
                _apply_db_overrides(tt, family, tiletype, _bitgroup)
                _db_cache[key] = tt
    return tt


def load_tilegrid(device, db_root=DEFAULT_DB_ROOT, family=FAMILY):
    path = os.path.join(db_root, family, device, "tilegrid.json")
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# tile decode (port of tile_cram_to_config)
# ---------------------------------------------------------------------------

def _match(bitgroup, cram, foff, boff):
    """True iff every cbit matches: cram[foff+f][boff+b] != inv."""
    for (f, b, inv) in bitgroup:
        v = cram[foff + f][boff + b]
        if (v != 0) == inv:      # v set but inv wanted-clear, or v clear but wanted-set
            return False
    return True


def decode_tile(tt, cram, foff, boff):
    """Return {'arcs':[(sink,src)], 'words':[(name,valstr)], 'enums':[(name,val)]}.

    Faithful to TileBitDatabase::tile_cram_to_config, minus the coverage/
    unknown tracking (unknowns are not part of the parity contract).  Iteration
    order matches std::map (sorted keys) so the >=-size tie-break picks the same
    winner as the C++.
    """
    arcs = []
    for sink in sorted(tt.muxes):
        best_src = None
        best_n = 0
        for src, bits in tt.muxes[sink]:   # already sorted by src
            if _match(bits, cram, foff, boff) and len(bits) >= best_n:
                best_src = src
                best_n = len(bits)
        # emit only if a driver was found whose bitgroup is non-empty
        if best_src is not None and best_n > 0:
            arcs.append((sink, best_src))

    words = []
    for name in sorted(tt.words):
        defval, groups = tt.words[name]
        val = tuple(_match(g, cram, foff, boff) for g in groups)
        if val != defval:
            valstr = "".join("1" if b else "0" for b in reversed(val))
            words.append((name, valstr))

    enums = []
    for name in sorted(tt.enums):
        defval, options = tt.enums[name]
        best_opt = None
        best_bits = None
        best_n = -1
        for opt in sorted(options):
            bits = options[opt]
            if _match(bits, cram, foff, boff) and len(bits) >= best_n:
                best_opt = opt
                best_bits = bits
                best_n = len(bits)
        if best_opt is None:
            if defval is not None:
                enums.append((name, "_NONE_"))
            # else: emit nothing
        else:
            if defval is not None and options.get(defval) == best_bits:
                pass  # matches default option's bits -> not emitted
            else:
                enums.append((name, best_opt))

    return {"arcs": arcs, "words": words, "enums": enums}


def decode_chip(cram, tilegrid, db_root=DEFAULT_DB_ROOT, family=FAMILY,
                workers=None):
    """Decode every tile.  Returns {tilename: {'arcs','words','enums'}}.

    NoGIL-parallel over tile instances via a thread pool.  Databases are
    pre-parsed serially so the parallel hot path is pure reads.
    """
    tiles = list(tilegrid.items())
    # Warm the type cache serially (cheap, keeps workers lock-free).
    for _, meta in tiles:
        get_tile_type(meta["type"], db_root, family)

    if workers is None:
        workers = min(32, (os.cpu_count() or 4))

    # ── freeze point ──────────────────────────────────────────────────────
    # `_db_cache` holds the parsed tile-type databases: static for the life of
    # the process, and walked by every worker for every tile, so its refcounts
    # are a cross-thread contention hotspot.  Immortalize it once it is warm.
    # NOTE: deliberately NOT immortalizing `cram`/`tilegrid` -- those are
    # per-bitstream, and decode_chip is called once per bitstream by the corpus
    # tools, so immortalizing them would leak one buffer per bitstream.
    # PLURIBUS_IMMORTAL=0 disables.
    # Freeze only when the cache gained entries since the last freeze:
    # corpus tools call decode_chip thousands of times per process, and
    # re-walking an unchanged (already immortal) cache is pure waste — and
    # would falsely trip ft_immortal's repeat-call-site leak warning (the
    # cache is bounded and process-lifetime; re-freezing it is idempotent,
    # not a leak).
    global _frozen_cache_len
    if (workers > 1 and len(_db_cache) != _frozen_cache_len
            and os.environ.get("PLURIBUS_IMMORTAL", "1") != "0"):
        try:
            _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _repo not in sys.path:
                sys.path.insert(0, _repo)
            import ft_immortal
            if ft_immortal.available() and ft_immortal.gil_disabled():
                ft_immortal.immortalize_tree(_db_cache)
                _frozen_cache_len = len(_db_cache)
        except Exception:
            pass  # perf-only; never fail a decode over this

    def work_chunk(chunk):
        out = []
        for name, meta in chunk:
            tt = get_tile_type(meta["type"], db_root, family)
            out.append((name, decode_tile(tt, cram, meta["start_frame"],
                                          meta["start_bit"])))
        return out

    if workers <= 1:
        return dict(work_chunk(tiles))

    # Chunk tiles across workers to amortise executor dispatch; each chunk is
    # a GIL-free decode over disjoint CRAM rectangles.
    nchunks = workers * 4
    step = max(1, (len(tiles) + nchunks - 1) // nchunks)
    chunks = [tiles[i:i + step] for i in range(0, len(tiles), step)]
    result = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(work_chunk, chunks):
            result.update(part)
    return result


# ---------------------------------------------------------------------------
# canonical form for parity comparison
# ---------------------------------------------------------------------------

def canonical(chip_cfg):
    """{tile: {'arcs':set, 'words':set, 'enums':set}}, dropping empty tiles."""
    out = {}
    for name, cfg in chip_cfg.items():
        a = frozenset(tuple(x) for x in cfg["arcs"])
        w = frozenset(tuple(x) for x in cfg["words"])
        e = frozenset(tuple(x) for x in cfg["enums"])
        if a or w or e:
            out[name] = {"arcs": a, "words": w, "enums": e}
    return out


def decode_file(bitpath, device="LCMXO2-1200", db_root=DEFAULT_DB_ROOT,
                family=FAMILY, workers=None):
    """Full path: parse .bit/.bin -> CRAM -> per-tile config."""
    import native_bitstream
    pb = native_bitstream.parse_file(bitpath)
    tilegrid = load_tilegrid(device, db_root, family)
    return decode_chip(pb.cram, tilegrid, db_root, family, workers), pb


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bitfile")
    ap.add_argument("--device", default="LCMXO2-1200")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    cfg, pb = decode_file(args.bitfile, device=args.device,
                          workers=args.workers)
    can = canonical(cfg)
    narcs = sum(len(t["arcs"]) for t in can.values())
    nwords = sum(len(t["words"]) for t in can.values())
    nenums = sum(len(t["enums"]) for t in can.values())
    print(f"# {args.bitfile}")
    print(f"# non-empty tiles={len(can)} arcs={narcs} words={nwords} "
          f"enums={nenums}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
