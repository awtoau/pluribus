#!/usr/bin/env python3
"""Parity test: native tile decode vs pytrellis ChipConfig.from_chip.

Runs under python3.14t.  For each reference bitstream:
  * native path: native_bitstream CRAM -> native_tile_decode -> canonical sets
  * oracle path: pytrellis Bitstream.read_bit -> deserialise_chip ->
    ChipConfig.from_chip -> to_string, parsed into the same canonical sets
Compares {tile: {arcs, words, enums}} order-independently and reports
per-tile-type divergences.  Logs to tmp/.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)

BUILD = os.environ.get("TRELLIS_BUILD", "tmp/prjtrellis/libtrellis/build")
DB = os.environ.get("TRELLIS_DBROOT", "tmp/prjtrellis/database")

import native_tile_decode as ntd

# In-repo generic fuzz bitstream: the default test vector, runs out of the box.
FUZZ_BIT = os.path.join(REPO, "diamond-fuzz", "targets",
                        "re_efb_00000_S_nc", "impl1", "fuzz_impl1.bit")

# Opt-in real vendor bitstreams (board-specific, not shipped in this repo).
# Set PLURIBUS_VENDOR_BITSTREAMS to an os.pathsep-separated list of .bin/.bit
# paths to also compare the compressed / bare-preamble vendor cases.
VENDOR_BITSTREAMS = [p for p in
                     os.environ.get("PLURIBUS_VENDOR_BITSTREAMS", "").split(os.pathsep)
                     if p]

BITSTREAMS = [("fuzz_efb_uncompressed", FUZZ_BIT)]
BITSTREAMS += [(f"vendor_{os.path.basename(p)}", p) for p in VENDOR_BITSTREAMS]


def parse_config_string(s):
    """Parse a pytrellis ChipConfig.to_string() into canonical per-tile sets."""
    tiles = {}
    cur = None
    for ln in s.splitlines():
        if ln.startswith(".tile "):
            name = ln[len(".tile "):].strip()
            cur = {"arcs": set(), "words": set(), "enums": set()}
            tiles[name] = cur
        elif ln.startswith("arc: ") and cur is not None:
            _, sink, source = ln.split()
            cur["arcs"].add((sink, source))
        elif ln.startswith("word: ") and cur is not None:
            _, name_, val = ln.split()
            cur["words"].add((name_, val))
        elif ln.startswith("enum: ") and cur is not None:
            _, name_, val = ln.split()
            cur["enums"].add((name_, val))
        elif ln.startswith("unknown:"):
            pass
        elif ln.strip() == "" or ln.startswith("."):
            cur = None  # leave tile block on blank / next directive
    # drop empties (mirror canonical())
    return {k: v for k, v in tiles.items()
            if v["arcs"] or v["words"] or v["enums"]}


def _bit_path_for_oracle(path):
    """pytrellis read_bit needs an 'FF 00 ... FF' .bit header; a bare vendor
    .bin starts at the raw preamble.  Wrap it in a temp .bit if needed."""
    raw = open(path, "rb").read()
    if raw[:4] == b"LSCC" or raw[:2] == b"\xff\x00":
        return path, None
    # minimal header: FF 00 (magic) FF (terminates the header scan), then the
    # bare command stream (which begins with the FF FF BD B3 preamble).
    import tempfile
    tf = tempfile.NamedTemporaryFile(suffix=".bit", delete=False)
    tf.write(b"\xff\x00\xff")
    tf.write(raw)
    tf.close()
    return tf.name, tf.name


def oracle_config(path, pb, log):
    sys.path.insert(0, BUILD)
    import pytrellis
    if not getattr(oracle_config, "_loaded", False):
        pytrellis.load_database(DB)
        oracle_config._loaded = True
    bitpath, tmp = _bit_path_for_oracle(path)
    how = "read_bit+deserialise"
    try:
        chip = pytrellis.Bitstream.read_bit(bitpath).deserialise_chip()
    except (ValueError, RuntimeError) as ex:
        # Vendor no-id / compressed streams: pytrellis can't self-identify the
        # chip and its Python binding doesn't expose the idcode override.  Feed
        # the (P2-verified byte-identical) native CRAM into a pytrellis Chip and
        # let pytrellis's OWN decode run -- still an independent decode oracle.
        log(f"  read_bit failed ({ex}); feeding native CRAM into pytrellis Chip")
        idcode = pb.idcode or 0x012ba043
        chip = pytrellis.Chip(idcode)
        cram = chip.cram
        assert cram.frames() == pb.num_frames and cram.bits() == pb.bits_per_frame
        for f in range(pb.num_frames):
            row = pb.cram[f]
            for b in range(pb.bits_per_frame):
                if row[b]:
                    cram.set_bit(f, b, True)
        how = "Chip(idcode)+native-CRAM"
    finally:
        if tmp:
            os.unlink(tmp)
    t0 = time.perf_counter()
    cc = pytrellis.ChipConfig.from_chip(chip)
    s = cc.to_string()
    dt = time.perf_counter() - t0
    log(f"  oracle [{how}] from_chip+to_string: {dt*1000:.1f} ms")
    return parse_config_string(s), chip


def tiletype_of(tilename):
    # tilegrid keys are "NAME:TYPE"
    return tilename.rsplit(":", 1)[-1] if ":" in tilename else "?"


def compare(native, oracle, tilegrid, log):
    all_tiles = set(native) | set(oracle)
    matched = 0
    diverged = []
    for name in sorted(all_tiles):
        nv = native.get(name, {"arcs": frozenset(), "words": frozenset(),
                               "enums": frozenset()})
        ov = oracle.get(name, {"arcs": set(), "words": set(), "enums": set()})
        na, nw, ne = set(nv["arcs"]), set(nv["words"]), set(nv["enums"])
        oa, ow, oe = set(ov["arcs"]), set(ov["words"]), set(ov["enums"])
        if na == oa and nw == ow and ne == oe:
            matched += 1
        else:
            diverged.append((name, tiletype_of(name),
                             ("arcs", na - oa, oa - na),
                             ("words", nw - ow, ow - nw),
                             ("enums", ne - oe, oe - ne)))
    return matched, diverged


def run(name, path, log):
    log(f"\n=== {name}: {path} ===")
    tilegrid = ntd.load_tilegrid("LCMXO2-1200", DB)

    import native_bitstream
    pb = native_bitstream.parse_file(path)
    log(f"  cram parsed: frames={pb.frames_read}/{pb.num_frames} "
        f"crc_verified={pb.crc_verified}")

    ncpu = os.cpu_count() or 4
    # serial timing
    t0 = time.perf_counter()
    cfg1 = ntd.decode_chip(pb.cram, tilegrid, DB, workers=1)
    t_serial = time.perf_counter() - t0
    # parallel timing
    t0 = time.perf_counter()
    cfg = ntd.decode_chip(pb.cram, tilegrid, DB, workers=ncpu)
    t_par = time.perf_counter() - t0
    log(f"  native decode: serial(1w)={t_serial*1000:.1f} ms  "
        f"parallel({ncpu}w)={t_par*1000:.1f} ms  "
        f"speedup={t_serial/t_par:.2f}x  (322 tiles)")

    # True NoGIL compute scaling: amplify the work (R full-chip decodes) and
    # split it across raw threads, so thread/dispatch fixed costs are amortised
    # and we measure how the *decode compute* itself scales free-threaded.
    # This is the number that matters for the Python-vs-C++ decode decision.
    import threading
    tiles = list(tilegrid.items())
    for _, m in tiles:
        ntd.get_tile_type(m["type"], DB)
    prepared = [(ntd.get_tile_type(m["type"], DB), m["start_frame"],
                 m["start_bit"]) for _, m in tiles]
    cramref = pb.cram

    def decode_n(rep):
        for _ in range(rep):
            for tt, foff, boff in prepared:
                ntd.decode_tile(tt, cramref, foff, boff)

    R = 64  # total full-chip decodes
    decode_n(2)  # warm
    t0 = time.perf_counter()
    decode_n(R)
    t_serial = (time.perf_counter() - t0)
    log(f"  scaling: {R} full-chip decodes serial = {t_serial*1000:.0f} ms "
        f"({t_serial/R*1000:.1f} ms/decode)")
    for T in (2, 4, 8, 16):
        if T > ncpu:
            break
        per = R // T
        threads = [threading.Thread(target=decode_n, args=(per,))
                   for _ in range(T)]
        t0 = time.perf_counter()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        dt = time.perf_counter() - t0
        log(f"    {T:2d} threads x {per} decodes (SHARED data): {dt*1000:.0f} ms  "
            f"speedup={t_serial/dt:.2f}x")

    # Same work, but each thread owns PRIVATE copies of CRAM + DB so there is no
    # cross-thread refcount churn on shared objects.  If this scales but SHARED
    # does not, the bottleneck is free-threaded refcount contention, not the GIL.
    def decode_n_private(rep):
        cram_p = [bytearray(row) for row in cramref]          # private CRAM
        prep_p = [(ntd.parse_bits_db(os.path.join(
                        DB, "MachXO2", "tiledata", m["type"], "bits.db")),
                   m["start_frame"], m["start_bit"]) for _, m in tiles]
        for _ in range(rep):
            for tt, foff, boff in prep_p:
                ntd.decode_tile(tt, cram_p, foff, boff)
    for T in (2, 4, 8, 16):
        if T > ncpu:
            break
        per = R // T
        threads = [threading.Thread(target=decode_n_private, args=(per,))
                   for _ in range(T)]
        t0 = time.perf_counter()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        dt = time.perf_counter() - t0
        log(f"    {T:2d} threads x {per} decodes (PRIVATE data): {dt*1000:.0f} ms  "
            f"speedup={t_serial/dt:.2f}x")

    native_can = ntd.canonical(cfg)
    oracle_can, _chip = oracle_config(path, pb, log)

    matched, diverged = compare(native_can, oracle_can, tilegrid, log)
    total = len(set(native_can) | set(oracle_can))
    log(f"  tiles compared (non-empty union) = {total}")
    log(f"  matched = {matched}   diverged = {len(diverged)}")
    if diverged:
        # group by tiletype
        bytype = {}
        for name_, tt, a, w, e in diverged:
            bytype.setdefault(tt, []).append((name_, a, w, e))
        log("  --- divergences by tile type ---")
        for tt in sorted(bytype):
            insts = bytype[tt]
            log(f"  [{tt}] {len(insts)} tile(s):")
            for name_, a, w, e in insts[:6]:
                for label, only_native, only_oracle in (a, w, e):
                    if only_native or only_oracle:
                        log(f"      {name_} {label}: "
                            f"native-only={sorted(only_native)} "
                            f"oracle-only={sorted(only_oracle)}")
            if len(insts) > 6:
                log(f"      ... and {len(insts)-6} more {tt} tiles")
    return matched, len(diverged), t_serial, t_par


def main():
    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)
    logpath = os.path.join(REPO, "tmp", "native_tile_parity.log")
    fh = open(logpath, "w")

    def log(*a):
        msg = " ".join(str(x) for x in a)
        print(msg)
        fh.write(msg + "\n")
        fh.flush()

    log(f"python {sys.version}")
    log(f"GIL enabled: {getattr(sys, '_is_gil_enabled', lambda: True)()}")
    log(f"cpu_count={os.cpu_count()}")
    if not VENDOR_BITSTREAMS:
        log("note: set PLURIBUS_VENDOR_BITSTREAMS (os.pathsep-separated) to "
            "also compare real vendor streams")

    grand = []
    for name, path in BITSTREAMS:
        if not os.path.exists(path):
            log(f"SKIP {name}: missing {path}")
            continue
        grand.append((name,) + run(name, path, log))

    log("\n=== SUMMARY ===")
    ok = True
    for name, matched, ndiv, ts, tp in grand:
        log(f"  {name}: matched={matched} diverged={ndiv} "
            f"serial={ts*1000:.0f}ms parallel={tp*1000:.0f}ms")
        if ndiv:
            ok = False
    log(f"\nPARITY {'PASS' if ok else 'DIVERGENCES FOUND'}")
    fh.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
