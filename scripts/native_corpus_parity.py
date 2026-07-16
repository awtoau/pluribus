#!/usr/bin/env python3
"""EXHAUSTIVE fidelity proof (pluribus issue #36, P5).

Compares the pure-Python native tile decode against the pytrellis oracle
(``ChipConfig.from_chip(...).to_string()``) over the WHOLE corpus:

  * every ``diamond-fuzz/targets/*/impl1/fuzz_impl1.bit`` that exists, and
  * any real vendor bitstreams supplied via ``PLURIBUS_VENDOR_BITSTREAMS``.

Parallelism is at the BITSTREAM level: one whole bitstream per worker, each
with its OWN CRAM + its OWN pytrellis Chip / native DB view.  We do NOT thread
across tiles within a bitstream (that hits free-threaded refcount cache-line
contention on shared objects).  ``concurrent.futures.ProcessPoolExecutor``
gives every worker fully independent hot data, so scaling is clean and the C++
pytrellis oracle never races another thread.  Runs under python3.14t.

native path:  native_bitstream CRAM -> native_tile_decode -> canonical sets
oracle path:  fuzz .bit -> pytrellis read_bit+deserialise (independent parse);
              vendor no-id -> feed P2-verified native CRAM into
              pytrellis.Chip(idcode) and run pytrellis's own decode.
Both read the SAME bits.db, so any DB quirk is SHARED and agrees.  A real
divergence therefore = a native-decoder bug and is reported precisely.

Logs to tmp/native_corpus_parity.log.
"""
import glob
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)

BUILD = os.environ.get("TRELLIS_BUILD", "tmp/prjtrellis/libtrellis/build")
DB = os.environ.get("TRELLIS_DBROOT", "tmp/prjtrellis/database")

TARGETS_GLOB = os.path.join(REPO, "diamond-fuzz", "targets")
# Opt-in real vendor bitstreams (board-specific, not shipped in this repo).
# Set PLURIBUS_VENDOR_BITSTREAMS to an os.pathsep-separated list of .bin/.bit
# paths to also compare the compressed / bare-preamble vendor cases.
VENDOR = [p for p in
          os.environ.get("PLURIBUS_VENDOR_BITSTREAMS", "").split(os.pathsep)
          if p]
DEVICE = "LCMXO2-1200"
MAX_DIV_DETAIL = 40   # per-bitstream cap on divergence lines carried back

# ---------------------------------------------------------------------------
# per-worker (per-process) state -- loaded once by the pool initializer
# ---------------------------------------------------------------------------
_W = {}


def _worker_init():
    # Silence pytrellis' chatty C++ stdout so it does not flood the log; real
    # results and errors travel back through return values / exceptions.
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    import native_bitstream
    import native_tile_decode as ntd
    from native_tile_parity import (parse_config_string, _bit_path_for_oracle,
                                     compare)
    sys.path.insert(0, BUILD)
    import pytrellis
    pytrellis.load_database(DB)
    _W["nb"] = native_bitstream
    _W["ntd"] = ntd
    _W["pt"] = pytrellis
    _W["parse_config_string"] = parse_config_string
    _W["_bit_path_for_oracle"] = _bit_path_for_oracle
    _W["compare"] = compare
    _W["tilegrid"] = ntd.load_tilegrid(DEVICE, DB)


def _oracle_can(path, pb):
    pt = _W["pt"]
    bitpath, tmp = _W["_bit_path_for_oracle"](path)
    try:
        try:
            chip = pt.Bitstream.read_bit(bitpath).deserialise_chip()
            how = "read_bit"
        except (ValueError, RuntimeError):
            idcode = pb.idcode or 0x012ba043
            chip = pt.Chip(idcode)
            cram = chip.cram
            if cram.frames() != pb.num_frames or cram.bits() != pb.bits_per_frame:
                raise RuntimeError(
                    f"cram geometry mismatch {cram.frames()}x{cram.bits()} "
                    f"vs {pb.num_frames}x{pb.bits_per_frame}")
            for f in range(pb.num_frames):
                row = pb.cram[f]
                for b in range(pb.bits_per_frame):
                    if row[b]:
                        cram.set_bit(f, b, True)
            how = "cram"
    finally:
        if tmp:
            os.unlink(tmp)
    cc = pt.ChipConfig.from_chip(chip)
    return _W["parse_config_string"](cc.to_string()), how


def check_bitstream(item):
    """Worker: (name, path, kind) -> compact result dict."""
    name, path, kind = item
    r = {"name": name, "path": path, "kind": kind, "status": "ok",
         "matched": 0, "total": 0, "ndiv": 0, "div": [], "how": "",
         "error": ""}
    try:
        nb = _W["nb"]
        ntd = _W["ntd"]
        pb = nb.parse_file(path)
        if pb.frames_read != pb.num_frames:
            r["status"] = "parse_incomplete"
            r["error"] = f"frames_read={pb.frames_read}/{pb.num_frames}"
            return r
    except Exception as ex:
        r["status"] = "parse_fail"
        r["error"] = f"{type(ex).__name__}: {ex}"
        return r
    try:
        cfg = ntd.decode_chip(pb.cram, _W["tilegrid"], DB, workers=1)
        native_can = ntd.canonical(cfg)
    except Exception as ex:
        r["status"] = "native_fail"
        r["error"] = f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"
        return r
    try:
        oracle_can, how = _oracle_can(path, pb)
        r["how"] = how
    except Exception as ex:
        r["status"] = "oracle_fail"
        r["error"] = f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"
        return r
    matched, diverged = _W["compare"](native_can, oracle_can, None, None)
    r["matched"] = matched
    r["total"] = len(set(native_can) | set(oracle_can))
    r["ndiv"] = len(diverged)
    if diverged:
        r["status"] = "DIVERGED"
        # carry back a compact, picklable description (cap the volume)
        for nm, tt, a, w, e in diverged[:MAX_DIV_DETAIL]:
            fields = []
            for label, only_n, only_o in (a, w, e):
                if only_n or only_o:
                    fields.append((label, sorted(only_n), sorted(only_o)))
            r["div"].append((nm, tt, fields))
    return r


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def discover():
    """Return (present, missing): lists of (name, path, kind)."""
    present, missing = [], []
    for d in sorted(glob.glob(os.path.join(TARGETS_GLOB, "*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        bit = os.path.join(d, "impl1", "fuzz_impl1.bit")
        if os.path.exists(bit):
            present.append((name, bit, "fuzz"))
        else:
            missing.append((name, bit, "fuzz"))
    for v in VENDOR:
        if os.path.exists(v):
            present.append((os.path.basename(v), v, "vendor"))
        else:
            missing.append((os.path.basename(v), v, "vendor"))
    return present, missing


def run_pool(items, workers):
    """Run check_bitstream over items with a process pool; return (results, wall)."""
    results = []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers,
                             initializer=_worker_init) as ex:
        # chunksize amortises IPC; ordering irrelevant (each result self-labels).
        for r in ex.map(check_bitstream, items, chunksize=4):
            results.append(r)
    return results, time.perf_counter() - t0


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of bitstreams (debug)")
    ap.add_argument("--scaling", action="store_true",
                    help="also run a worker-count scaling sweep on a subset")
    ap.add_argument("--scaling-subset", type=int, default=256)
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)
    logpath = os.path.join(REPO, "tmp", "native_corpus_parity.log")
    fh = open(logpath, "w")

    def log(*a):
        msg = " ".join(str(x) for x in a)
        print(msg)
        fh.write(msg + "\n")
        fh.flush()

    log(f"python {sys.version}")
    log(f"GIL enabled: {getattr(sys, '_is_gil_enabled', lambda: True)()}")
    log(f"cpu_count={os.cpu_count()}  workers={args.workers}")

    present, missing = discover()
    if args.limit:
        present = present[:args.limit]
    n_fuzz = sum(1 for x in present if x[2] == "fuzz")
    n_vendor = sum(1 for x in present if x[2] == "vendor")
    log(f"discovered: {len(present)} bitstreams present "
        f"({n_fuzz} fuzz + {n_vendor} vendor), "
        f"{len(missing)} missing .bit (unbuilt targets)")
    if not VENDOR:
        log("note: set PLURIBUS_VENDOR_BITSTREAMS (os.pathsep-separated) to "
            "also compare real vendor streams")

    # ---- full correctness run ---------------------------------------------
    log(f"\n=== FULL RUN: {len(present)} bitstreams @ {args.workers} workers ===")
    results, wall = run_pool(present, args.workers)
    log(f"wall-clock: {wall:.1f} s  "
        f"({wall/max(1,len(present))*1000:.1f} ms/bitstream aggregate)")

    buckets = {}
    for r in results:
        buckets.setdefault(r["status"], []).append(r)
    matched_ok = buckets.get("ok", [])
    diverged = buckets.get("DIVERGED", [])
    failed = {k: v for k, v in buckets.items() if k not in ("ok", "DIVERGED")}

    tot_tiles = sum(r["total"] for r in results)
    log(f"\n--- status buckets ---")
    for st in sorted(buckets):
        log(f"  {st}: {len(buckets[st])}")
    log(f"  total tiles compared across corpus: {tot_tiles}")

    if diverged:
        log(f"\n--- DIVERGENCES ({len(diverged)} bitstreams) ---")
        for r in diverged:
            log(f"  [{r['name']}] ({r['how']}) {r['ndiv']} tile(s) differ:")
            for nm, tt, fields in r["div"]:
                for label, only_n, only_o in fields:
                    log(f"      {nm} [{tt}] {label}: "
                        f"native-only={only_n} oracle-only={only_o}")

    if failed:
        log(f"\n--- FAILURES/SKIPS ---")
        for st, rs in sorted(failed.items()):
            log(f"  [{st}] {len(rs)}:")
            for r in rs[:20]:
                log(f"      {r['name']}: {r['error'].splitlines()[0] if r['error'] else ''}")
            if len(rs) > 20:
                log(f"      ... and {len(rs)-20} more")

    if missing:
        log(f"\n--- MISSING .bit (unbuilt targets, not a decoder failure): "
            f"{len(missing)} ---")
        for nm, path, kind in missing[:20]:
            log(f"      {nm}")
        if len(missing) > 20:
            log(f"      ... and {len(missing)-20} more")

    # ---- scaling sweep -----------------------------------------------------
    scaling = []
    if args.scaling:
        subset = present[:args.scaling_subset]
        log(f"\n=== SCALING SWEEP: {len(subset)} bitstreams, varying workers ===")
        wc = 1
        counts = []
        while wc <= (os.cpu_count() or 1):
            counts.append(wc)
            wc *= 2
        if counts[-1] != os.cpu_count():
            counts.append(os.cpu_count())
        base = None
        for wc in counts:
            _res, w = run_pool(subset, wc)
            nd = sum(r["status"] not in ("ok",) for r in _res)
            if base is None:
                base = w
            log(f"  {wc:3d} workers: {w:6.1f} s  "
                f"speedup={base/w:5.2f}x  "
                f"({w/len(subset)*1000:.1f} ms/bitstream)  nonok={nd}")
            scaling.append((wc, w, base / w))

    # ---- verdict -----------------------------------------------------------
    log(f"\n{'='*60}")
    log(f"FIDELITY VERDICT")
    log(f"{'='*60}")
    n_compared = len(matched_ok) + len(diverged)
    log(f"  bitstreams compared : {n_compared}")
    log(f"  matched (0 diverge) : {len(matched_ok)}")
    log(f"  DIVERGED            : {len(diverged)}")
    log(f"  skipped/failed      : {sum(len(v) for v in failed.values())} "
        f"+ {len(missing)} missing .bit")
    for st, rs in sorted(failed.items()):
        log(f"      {st}: {len(rs)}")
    log(f"  wall-clock @ {args.workers}w: {wall:.1f} s")
    ok = (len(diverged) == 0)
    log(f"\n  RESULT: "
        + ("FAITHFUL -- native decode == pytrellis across the entire corpus"
           if ok else f"DIVERGENCES FOUND in {len(diverged)} bitstream(s)"))
    fh.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
