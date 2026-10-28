#!/usr/bin/env python3.15t
"""Profile pluribus pipeline stages on real inputs (issue #144: what would Rust clearly speed up).

  python3.15t scripts/profile_stages.py [--stages decode,asm_active,...] [--cprofile] [--list]

Each stage runs as a child process: wall from perf_counter, CPU (user+sys) and peak RSS from
os.wait4 rusage.  In-process stages print `PROFILE_JSON {...}` with per-phase wall times; with
--cprofile the child also writes tmp/profile_stages/<stage>.prof and reports the top functions by
tottime (hot-loop share).  Scratch copies of DBs / caches live in tmp/profile_stages/ -- the
originals (databases/*.db, tmp/ddb/*, tmp/cycloneiv_bit_inventory.json) are never written.
Results: tmp/profile_stages.json; log tmp/logs/profile_stages.log.
Threads stay <= 8 per stage (shared box).
"""
import argparse
import json
import logging
import os
import queue
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / "tmp" / "profile_stages"
LOG = REPO / "tmp" / "logs" / "profile_stages.log"
PY = sys.executable
log = logging.getLogger("profile_stages")

POSEIDON = REPO / "sources/cycloneiv-corpus/poseidon_computerspace/ComputerSpace_psdcgx150_20260202.rbf"
MACHXO2_CFG = REPO / "corpus/machxo2/constructs/adder_v01_16/decoded.config"
ECP5_BIT = REPO / "corpus/ecp5/cheyao_icepi-zero__fire-v.cf50af64.bit"
WORKERS = 8
# Stall guard (awto-dan#53): no child output line for STALL_S -> hung: kill + log.  The longest
# silent in-process phase is the ddb fan-out template loop (~2 min pure Python); 300 s ~ 2.5x.
STALL_S = 300
# Backstop per stage = 3x measured cold worst case (bit inventory ~60 s, tracer 3 designs ~50 s
# + ~60 s load, reach on fnirsi ~3 min): 600 s.
LIMIT_S = 600


# ----------------------------------------------------------------------------- in-process stages
def _plane():
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of("EP4CGX150"))
    return cc.cram_plane(POSEIDON.read_bytes(), g), g


def stage_decode(ph):
    """cram_plane on an EP4CGX150 image: nibble decompress (pure Python) + unpackbits (numpy)."""
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_decompress as cd
    raw = POSEIDON.read_bytes()
    t = time.perf_counter()
    info = {}
    u = cd.decompress(raw, info)
    ph["decompress"] = time.perf_counter() - t
    t = time.perf_counter()
    plane, _g = _plane()
    ph["cram_plane_total"] = time.perf_counter() - t
    return dict(in_bytes=len(raw), out_bytes=len(u), set_bits=int(len(plane.keys)), frames=plane.shape[0])


def stage_asm_active(ph):
    """Dec() load + Dec.active(plane): 51.6 M asm entries vs the plane (numpy searchsorted/bincount)."""
    plane, _g = _plane()
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_asm_decode as ad
    t = time.perf_counter()
    dec = ad.Dec()
    ph["dec_load"] = time.perf_counter() - t
    t = time.perf_counter()
    gids, _recs, blk = dec.active(plane)
    ph["active"] = time.perf_counter() - t
    t = time.perf_counter()
    gids2, _r2, _b2 = dec.active(plane)
    ph["active_2nd"] = time.perf_counter() - t
    return dict(entries=int(len(dec.pf)), groups=int(len(dec.gsize)), fired=int(len(gids)), blocks=int(len(set(blk.tolist()))))


def stage_ddb_fanout(ph):
    """cycloneiv_ddb_routing.fanout: exact routing.ddb decode (ptr-tag chain + template pool loops)."""
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_ddb_asm as A
    import cycloneiv_ddb_routing as R
    tmp = SCRATCH / "ddb"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "tmp/ddb/stingray4_routing.bin"
    dst = tmp / "stingray4_routing.bin"
    if not dst.exists():
        shutil.copyfile(src, dst)
    A.TMP = str(tmp)
    t = time.perf_counter()
    R.fanout("stingray4")
    ph["fanout"] = time.perf_counter() - t
    import numpy as np
    z = np.load(tmp / "stingray4_rt_fanout.npz")
    return dict(elements=int(len(z["V"])), templates=int(len(z["cnt"])), template_edges=int(z["cnt"].sum()))


def stage_ddb_fanout_loops(ph):
    """The two pure-Python loops of fanout() in isolation (the rest is numpy)."""
    import struct
    import numpy as np
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_ddb_routing as R
    raw = (REPO / "tmp/ddb/stingray4_routing.bin").read_bytes()
    n = struct.unpack_from("<I", raw, 12)[0]
    rec = np.frombuffer(raw, R.NODE, count=n, offset=16)
    t = time.perf_counter()
    tags = rec["dn"]
    last, nxt = 0, 1
    for i, tg in enumerate(tags.tolist()):
        if tg == 0:
            continue
        if tg == 12:
            nxt += 1
        elif tg & 3 == 2:
            last += tg >> 2
    ph["ptr_tag_chain"] = time.perf_counter() - t
    n_tpl, n_edge = R.N_TPL["stingray4"], R.N_EDGE["stingray4"]
    L = len(raw)
    p = L - (17 * n_tpl + 6 * n_edge)
    sc = struct.Struct("<hhhhhbbbH")
    t = time.perf_counter()
    for k in range(n_tpl):
        d = sc.unpack_from(raw, p)
        c1 = d[8]
        p += 15 + 4 * c1
        c2 = struct.unpack_from("<H", raw, p)[0]
        p += 2 + 2 * c2
    ph["template_pool_walk"] = time.perf_counter() - t
    return dict(elements=int(n), templates=n_tpl)


def stage_forced_diff(ph):
    """Specimen diff helper (cycloneiv_forced.diff): two uncompressed corpus planes -> set difference."""
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_forced as F
    t = time.perf_counter()
    on, off = F.diff("gxll_00_02_s", "gxll_00_02_b")
    ph["diff"] = time.perf_counter() - t
    return dict(only_spec=len(on), only_base=len(off))


def stage_lift_machxo2(ph):
    """MachXO2 lifter on a Diamond construct (.config -> Design)."""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "scripts"))
    import toolchain
    from lifters.trellis_lift import TrellisLift
    t = time.perf_counter()
    lift = TrellisLift("machxo2", "LCMXO2-1200", dbroot=toolchain.trellis_dbroot())
    ph["init"] = time.perf_counter() - t
    t = time.perf_counter()
    pc = lift.parse_config(str(MACHXO2_CFG))
    ph["parse_config"] = time.perf_counter() - t
    t = time.perf_counter()
    d = lift.recover_netlist(pc)
    ph["recover_netlist"] = time.perf_counter() - t
    return dict(luts=len(d.luts), ffs=len(d.ffs), nets=len(getattr(d, "nets", [])))


def stage_lift_ecp5(ph):
    """ECP5: native bitstream decode (.bit -> config text) then ECP5Lift."""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "scripts"))
    import toolchain
    import native_config
    import ecp5_corpus_test as ct
    from lifters.trellis_lift import TrellisLift
    dbroot = toolchain.trellis_dbroot()
    dev, fam, _idc, _how = ct.identify(str(ECP5_BIT), dbroot)
    t = time.perf_counter()
    text, _pb, _bram = native_config.config_from_file(str(ECP5_BIT), device=dev, db_root=dbroot)
    ph["native_decode"] = time.perf_counter() - t
    cfg = SCRATCH / "ecp5.config"
    cfg.write_text(text)
    t = time.perf_counter()
    lift = TrellisLift("ecp5", dev, dbroot=dbroot)
    ph["init"] = time.perf_counter() - t
    t = time.perf_counter()
    pc = lift.parse_config(str(cfg))
    ph["parse_config"] = time.perf_counter() - t
    t = time.perf_counter()
    d = lift.recover_netlist(pc)
    ph["recover_netlist"] = time.perf_counter() - t
    return dict(device=dev, family=fam, luts=len(d.luts), ffs=len(d.ffs))


INPROC = {
    "decode": stage_decode,
    "asm_active": stage_asm_active,
    "ddb_fanout": stage_ddb_fanout,
    "ddb_fanout_loops": stage_ddb_fanout_loops,
    "forced_diff": stage_forced_diff,
    "lift_machxo2": stage_lift_machxo2,
    "lift_ecp5": stage_lift_ecp5,
}


# ----------------------------------------------------------------------------- external stages
def _db_copy(name):
    dst = SCRATCH / name
    if not dst.exists():
        shutil.copyfile(REPO / "databases" / name, dst)
    return dst


def _reach_env(dbname):
    env = dict(os.environ, PLURIBUS_DB_BACKEND="sqlite", PLURIBUS_SQLITE_PATH=str(_db_copy(dbname)))
    return env


def external(stage):
    """-> (cmd list, env, setup/teardown hooks)."""
    S = str(REPO / "scripts")
    if stage.startswith("reach") or stage.startswith("report"):
        base, _, dbtag = stage.partition("@")
        dbname, label = {"": ("repl.db", "REPL_SCOPE"), "repl": ("repl.db", "REPL_SCOPE"),
                         "fnirsi": ("fnirsi.db", "FNIRSI"), "aw2": ("aw2.db", "V02")}[dbtag]
        script = {"reach": "reach.py", "reach2": "reach2.py", "reach3": "reach3.py", "reach4": "reach4.py",
                  "report": "report.py"}[base]
        cmd = [PY, str(REPO / script), "--bitstream", label]
        if base in ("reach", "reach3", "reach4"):
            cmd += ["--workers", str(WORKERS)]
        if base == "reach":
            cmd += ["--replace"]
        return cmd, _reach_env(dbname), None
    if stage == "bit_inventory":
        keep = [REPO / "tmp/cycloneiv_bit_inventory.json", REPO / "tmp/logs/cycloneiv_bit_inventory.log"]
        saved = {p: p.read_bytes() for p in keep if p.exists()}

        def restore():
            for p, b in saved.items():
                p.write_bytes(b)
        return [PY, f"{S}/cycloneiv_bit_inventory.py", "--image", str(POSEIDON)], dict(os.environ), restore
    if stage == "ddb_trace":
        return [PY, f"{S}/cycloneiv_ddb_trace.py", "score", "--designs", "gx150_rb*", "--split", "odd", "--limit", "3"], dict(os.environ), None
    if stage == "tests_lifters":
        return [PY, "-m", "pytest", "-q", "--durations=12", "tests/test_machxo2_lift.py", "tests/test_gowin_lift.py",
                "tests/test_ecp5_gate.py", "tests/test_ecp5_clock_tree.py", "tests/test_cyclonev_lift.py",
                "tests/test_cycloneiv_decompress.py", "tests/test_sqlite.py"], dict(os.environ), None
    if stage == "corpus_register":
        env = dict(os.environ, PLURIBUS_DB_BACKEND="sqlite", PLURIBUS_SQLITE_PATH=str(SCRATCH / "pluribus_copy.db"))
        if not (SCRATCH / "pluribus_copy.db").exists():
            shutil.copyfile(REPO / "pluribus.db", SCRATCH / "pluribus_copy.db")
        return [PY, f"{S}/corpus_register.py", "--family", "cycloneiv"], env, None
    if stage == "ledger_page":
        return [PY, f"{S}/coverage_page_build.py", str(SCRATCH / "coverage.html")], dict(os.environ), None
    raise KeyError(stage)


EXTERNAL = ["reach@repl", "reach2@repl", "reach3@repl", "reach4@repl", "report@repl",
            "reach@fnirsi", "reach3@fnirsi",
            "bit_inventory", "ddb_trace", "tests_lifters", "corpus_register", "ledger_page"]
ALL = list(INPROC) + EXTERNAL


# ----------------------------------------------------------------------------- child / driver
def run_child(stage, cprofile):
    ph = {}
    fn = INPROC[stage]
    out = {}
    if cprofile:
        import cProfile
        import pstats
        pr = cProfile.Profile()
        pr.enable()
        out = fn(ph)
        pr.disable()
        pf = SCRATCH / f"{stage}.prof"
        pr.dump_stats(str(pf))
        st = pstats.Stats(str(pf))
        tot = st.total_tt
        rows = sorted(st.stats.items(), key=lambda kv: -kv[1][2])[:12]
        out["top"] = [dict(fn=f"{k[0].split('/')[-1]}:{k[1]}:{k[2]}", tottime=round(v[2], 3), share=round(v[2] / tot, 3))
                      for k, v in rows]
        out["cprofile_total"] = round(tot, 3)
    else:
        out = fn(ph)
    out["phases"] = {k: round(v, 3) for k, v in ph.items()}
    print("PROFILE_JSON " + json.dumps(out), flush=True)


def measure(stage, cmd, env, cprofile):
    """Run cmd; -> dict(wall, cpu, rss_mb, rc, json, tail).  Stall guard: STALL_S without a line."""
    log.info("[%s] start: %s", stage, " ".join(os.path.relpath(c, REPO) if c.startswith(str(REPO)) else c for c in cmd))
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    q = queue.Queue()

    def pump():
        for line in p.stdout:
            q.put(line.rstrip("\n"))
        q.put(None)
    threading.Thread(target=pump, daemon=True).start()
    lines, last, pj, killed = [], time.perf_counter(), None, None
    while True:
        try:
            # 1 s poll: fine-grained enough to attribute a kill to the stall or the backstop.
            line = q.get(timeout=1.0)
        except queue.Empty:
            now = time.perf_counter()
            if now - last > STALL_S:
                killed = f"STALL: no output for {now - last:.0f}s (limit {STALL_S}s), elapsed {now - t0:.0f}s, last line: {lines[-1] if lines else ''!r}"
            elif now - t0 > LIMIT_S:
                killed = f"BACKSTOP: elapsed {now - t0:.0f}s > {LIMIT_S}s, last line: {lines[-1] if lines else ''!r}"
            if killed:
                log.error("[%s] %s loadavg %s", stage, killed, os.getloadavg())
                p.kill()
                break
            continue
        if line is None:
            break
        last = time.perf_counter()
        lines.append(line)
        if line.startswith("PROFILE_JSON "):
            pj = json.loads(line[len("PROFILE_JSON "):])
    _pid, status, ru = os.wait4(p.pid, 0)
    wall = time.perf_counter() - t0
    rc = os.waitstatus_to_exitcode(status)
    res = dict(stage=stage, wall=round(wall, 2), cpu=round(ru.ru_utime + ru.ru_stime, 2),
               rss_mb=round(ru.ru_maxrss / 1024, 1), rc=rc, json=pj, killed=killed,
               tail=[ln for ln in lines if not ln.startswith("PROFILE_JSON ")][-25:])
    log.info("[%s] wall %.2fs cpu %.2fs peak RSS %.0f MB rc %d%s", stage, wall, res["cpu"], res["rss_mb"], rc,
             f" phases {pj['phases']}" if pj and "phases" in pj else "")
    if pj and "top" in pj:
        for r in pj["top"][:8]:
            log.info("[%s]   %5.1f%% %8.3fs %s", stage, 100 * r["share"], r["tottime"], r["fn"])
    for ln in res["tail"][-6:]:
        log.info("[%s]   | %s", stage, ln[:200])
    return res


def external_cprofile(stage, cmd):
    """Wrap an external script in cProfile (main thread only) and summarise."""
    pf = SCRATCH / f"{stage.replace('@', '_')}.prof"
    if cmd[1] == "-m":          # pytest: not profiled
        return cmd, None
    return [cmd[0], "-m", "cProfile", "-o", str(pf)] + cmd[1:], pf


def summarise_prof(pf):
    import pstats
    st = pstats.Stats(str(pf))
    tot = st.total_tt
    rows = sorted(st.stats.items(), key=lambda kv: -kv[1][2])[:12]
    return [dict(fn=f"{k[0].split('/')[-1]}:{k[1]}:{k[2]}", tottime=round(v[2], 3), share=round(v[2] / tot, 3)) for k, v in rows], round(tot, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default=",".join(ALL))
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=str(REPO / "tmp" / "profile_stages.json"), help="results JSON (merged per stage)")
    ap.add_argument("--run", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.list:
        print("\n".join(ALL))
        return
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if a.run:
        run_child(a.run, a.cprofile)
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    out_path = Path(a.out)
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    for stage in a.stages.split(","):
        stage = stage.strip()
        if not stage:
            continue
        teardown = None
        if stage in INPROC:
            cmd = [PY, __file__, "--run", stage] + (["--cprofile"] if a.cprofile else [])
            env = dict(os.environ)
            pf = None
        else:
            cmd, env, teardown = external(stage)
            pf = None
            if a.cprofile:
                cmd, pf = external_cprofile(stage, cmd)
        try:
            res = measure(stage, cmd, env, a.cprofile)
        finally:
            if teardown:
                teardown()
        if pf and pf.exists():
            top, tot = summarise_prof(pf)
            res["json"] = dict(res.get("json") or {}, top=top, cprofile_total=tot)
            for r in top[:8]:
                log.info("[%s]   %5.1f%% %8.3fs %s", stage, 100 * r["share"], r["tottime"], r["fn"])
        results[stage + ("+cprofile" if a.cprofile else "")] = res
        out_path.write_text(json.dumps(results, indent=1))
    log.info("results -> %s", out_path)


if __name__ == "__main__":
    main()
