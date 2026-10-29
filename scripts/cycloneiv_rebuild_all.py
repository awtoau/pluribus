#!/usr/bin/env python3.15t
"""Full Cyclone IV corpus rebuild into a NEW tree, then migration checks (Dan 2026-10-29).

  scripts/cycloneiv_rebuild_all.py [--root DIR] [--sample N] [--jobs 12] [--stages build,determinism,register,evidence,derived,gates,swap]

Stages (each resumable; --root DIR resumes a run):
  build        every corpus/cycloneiv/<d> with design.toml + src/ -> <root>/<d>/ through cycloneiv_fuzz.build_one
               (same flow/flags; src/force.rcf is the back-annotation input where design.toml names it).
               Kept: images, rcf, post-fit .vo/.sdo, reports, logs. Dropped: quartus/db, incremental_db, qdb.
               Per-dir rebuild.json = status/tool version/elapsed/sha256; failed:/refused: recorded, never silent.
  determinism  new rbf vs old rbf (where the old tree still has one) -> tmp/rebuild_determinism.json
  register     corpus_builds for the new tree into <root>/gx150.db (snapshot of the family DB; live DB untouched)
  evidence     recompute every specimen-pair from the new planes, compare, backfill build_base/build_spec
               -> tmp/rebuild_evidence_migration.json
  derived      regenerate lifters/data/cycloneiv_ep4cgx150_* in <root>/_view, diff vs stored
  gates        claims_register (verdict diff), bit inventory, 76-design gate, progress ledger, all in <root>/_view
  swap         prints the commands that adopt the new tree (Dan approves; nothing is swapped here)
Old corpus and live DB are never modified. Log: tmp/logs/cycloneiv_rebuild_all.log
Disk guard: stop when free space < DISK_STOP_GB. Concurrency: min(--jobs, tmp/limits/build_pool.max).
"""
import argparse
import collections
import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
OLD = REPO / "corpus" / "cycloneiv"
OUT_ROOT = Path("/mnt/2tb/corpus-rebuild")
DISK_STOP_GB = 60
DEFAULT_JOBS = 12
PER_JOB_GB = 2.0
IMAGE = REPO / "sources/cycloneiv-corpus/neptuno_cgx150_mc2/mc2.rbf"   # the third-party EP4CGX150 image
DROP_DIRS = ("db", "incremental_db", "qdb")
STAGES = ("build", "determinism", "register", "evidence", "derived", "gates", "swap")
# derived artifact -> regenerating command (cwd = view). Inputs the commands read from corpus/cycloneiv are the NEW tree.
DERIVED = [   # (artifact or None for a cache-prep step, command); order matters: caches first
    (None, ["scripts/cycloneiv_ddb_asm.py", "parse"]),                       # asm.ddb -> tmp/ddb/<die>_asm_*.npy
    (None, ["scripts/cycloneiv_ddb_routing.py", "fanout"]),                  # routing.ddb -> <die>_rt_fanout.npz
    (None, ["scripts/cycloneiv_ddb_routing.py", "nodes"]),
    (None, ["scripts/cycloneiv_ddb_routing.py", "twin"]),
    (None, ["scripts/cycloneiv_ddb_routing.py", "templates"]),
    (None, ["scripts/cycloneiv_asm_decode.py", "prepare"]),                  # tmp/ddb/<die>_dec_*.npy from the vendor files
    (None, ["scripts/cycloneiv_ddb_blockmap.py", "build"]),                  # tmp/ddb/<die>_blockmap.npz
    ("cycloneiv_ep4cgx150_ddb_map.npz", ["scripts/cycloneiv_ddb_trace.py", "export"]),
    ("cycloneiv_ep4cgx150_li_map.json", ["scripts/cycloneiv_li_map.py", "extract", "--designs", "gx150_*", "--split", "even"]),
    ("cycloneiv_ep4cgx150_phys_map.json", ["scripts/cycloneiv_phys_trace.py", "learn", "--designs", "gx150_*", "--split", "even"]),
]
# Not regenerated (no regenerating CLI or inputs are device probes, not builds): asm_names.json, geom.json, labs.json.
# Backstop per regeneration/gate command: first full run, nothing measured yet; the 60 s CPU-stall guard is primary.
CMD_OVERALL_S = 4 * 3600
log = logging.getLogger("rebuild_all")
STOP = threading.Event()
DB_LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def free_gb(p):
    return shutil.disk_usage(p).free / 2**30


def pool_cap(jobs):
    try:
        cap = int((REPO / "tmp/limits/build_pool.max").read_text().strip())
    except (OSError, ValueError):
        cap = jobs
    return max(1, min(jobs, cap))


def prefix_of(name):
    t = name.split("_")
    return "_".join(t[:2]) if t[0] in ("gx150", "gx110", "site", "ff", "rnd", "lut", "ho", "ho2") and len(t) > 1 else t[0]


def enumerate_designs():
    out = []
    for d in sorted(OLD.iterdir()):
        if (d / "design.toml").is_file() and (d / "src").is_dir():
            out.append(d.name)
    return out


def pick_sample(names, n):
    """>= 2 per prefix, plus extra dirs that have an old rbf (determinism check); n caps the extras."""
    by = collections.defaultdict(list)
    for x in names:
        by[prefix_of(x)].append(x)
    pick = []
    for p, xs in sorted(by.items()):
        pick += xs[:2]
    with_rbf = [x for x in names if (OLD / x / "bitstream.rbf").exists() and x not in pick]
    have = sum((OLD / x / "bitstream.rbf").exists() for x in pick)
    pick += with_rbf[:max(0, 4 - have)]
    log.info("sample: %d prefixes, %d dirs (%d with old rbf)", len(by), len(pick),
             sum((OLD / x / "bitstream.rbf").exists() for x in pick))
    return sorted(set(pick))


def marker(d):
    try:
        return json.loads((d / "rebuild.json").read_text())
    except (OSError, ValueError):
        return None


REQUIRED = ("bitstream.rbf", "postfit.vo", "routing.rcf", "fit.rpt", "build.pin")


def complete(d):
    m = marker(d)
    return bool(m and m.get("status") == "ok" and all((d / f).is_file() for f in REQUIRED))


# ---------------------------------------------------------------- build
def build_job(name, root):
    import build_pool
    import cycloneiv_fuzz as fz
    import corpus_register as cr
    if STOP.is_set():
        return None
    nd, od = root / name, OLD / name
    if complete(nd):
        return None
    if free_gb(root) < DISK_STOP_GB:
        STOP.set()
        log.error("DISK GUARD: %.1f GB free < %d GB; stopping new builds (resume with --root %s)",
                  free_gb(root), DISK_STOP_GB, root)
        return None
    prev = marker(nd) or {}
    if prev.get("status") in ("failed", "refused") and prev.get("attempts", 1) >= 2:
        return build_pool.BuildOutcome(prev["status"], prev.get("reason", "?"))     # already retried once
    attempts = prev.get("attempts", 0) + 1
    shutil.rmtree(nd, ignore_errors=True)
    nd.mkdir(parents=True)
    shutil.copy2(od / "design.toml", nd / "design.toml")
    shutil.copytree(od / "src", nd / "src")
    qt = root / "_qtmp" / name
    fz._tl.corpus, fz._tl.qtmp = root, qt                    # per-job TMPDIR (Quartus alt*.dir litter), this thread only
    t0 = time.monotonic()
    try:
        step = fz.build_one(name)
    finally:
        shutil.rmtree(qt, ignore_errors=True)
    el = time.monotonic() - t0
    if step:
        fit = (nd / "logs" / "quartus_fit.log")
        txt = fit.read_text(errors="replace") if fit.exists() else ""
        refused = step == "quartus_fit" and re.search(r"Error.*(back.?annotat|routing|force)", txt, re.I)
        status = "refused" if refused else "failed"
        reason = f"{step} after {el:.0f}s"
        (nd / "rebuild.json").write_text(json.dumps({"status": status, "reason": reason, "attempts": attempts}))
        return build_pool.BuildOutcome(status, reason)
    q = nd / "quartus"
    for sub in DROP_DIRS:
        shutil.rmtree(q / sub, ignore_errors=True)
    dup = q / "build.rbf"
    if dup.exists() and sha256(dup) == sha256(nd / "bitstream.rbf"):    # same bytes, one inode
        dup.unlink()
        os.link(nd / "bitstream.rbf", dup)
    old_rbf = od / "bitstream.rbf"
    (nd / "rebuild.json").write_text(json.dumps({
        "status": "ok", "attempts": attempts, "elapsed_s": round(el, 1), "quartus": cr.toolchain_of(nd),
        "built": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "rbf_sha256": sha256(nd / "bitstream.rbf"), "old_rbf_sha256": sha256(old_rbf) if old_rbf.exists() else None}))
    return None


def record_outcome(name, outcome, root):
    import tomllib
    import db
    import schema
    from provenance import corpus as CO
    spec = tomllib.loads((OLD / name / "design.toml").read_text())
    with DB_LOCK, db.engine().begin() as conn:
        CO.record_build_outcome(conn, "cycloneiv", spec.get("device", ""), name, outcome.status, outcome.reason,
                                out_dir=str(root / name), top=spec.get("top", "top"), toolchain=None)


def stage_build(root, names, jobs):
    import build_pool
    import schema
    schema.init()
    todo = [n for n in names if not complete(root / n)]
    cap = pool_cap(jobs)
    log.info("build: %d designs, %d to do, %d chains, root %s, free %.0f GB", len(names), len(todo), cap, root, free_gb(root))
    t0 = time.monotonic()
    build_pool.map_adaptive(lambda n: build_job(n, root), todo, per_job_gb=PER_JOB_GB, max_workers=cap,
                            on_outcome=lambda n, o: record_outcome(n, o, root))
    st = collections.Counter((marker(root / n) or {}).get("status", "missing") for n in names)
    log.info("build done in %.0fs: %s%s", time.monotonic() - t0, dict(st), " (STOPPED by disk guard)" if STOP.is_set() else "")
    return st


# ---------------------------------------------------------------- determinism
def popcount_xor(a, b):
    import numpy as np
    x = np.frombuffer(a, np.uint8) ^ np.frombuffer(b, np.uint8)
    return int(np.unpackbits(x).sum())


def stage_determinism(root, names):
    res = {}
    for n in names:
        old, new = OLD / n / "bitstream.rbf", root / n / "bitstream.rbf"
        if not (old.exists() and new.exists()):
            continue
        ob, nb = old.read_bytes(), new.read_bytes()
        same = ob == nb
        r = {"identical": same, "old_sha256": hashlib.sha256(ob).hexdigest(), "new_sha256": hashlib.sha256(nb).hexdigest()}
        if not same:
            r["len_old"], r["len_new"] = len(ob), len(nb)
            if len(ob) == len(nb):
                r["differing_bits"] = popcount_xor(ob, nb)
        res[n] = r
    summ = {"compared": len(res), "identical": sum(r["identical"] for r in res.values()),
            "differs": sum(not r["identical"] for r in res.values())}
    (REPO / "tmp").mkdir(exist_ok=True)
    (REPO / "tmp/rebuild_determinism.json").write_text(json.dumps({"root": str(root), "summary": summ, "designs": res}, indent=1))
    log.info("determinism: %s", summ)
    for n, r in res.items():
        if not r["identical"]:
            log.info("  differs %s: %s", n, {k: v for k, v in r.items() if "sha" not in k})
    return summ


# ---------------------------------------------------------------- register
def snapshot_db(root):
    snap = root / "gx150.db"
    if not snap.exists():
        src = sqlite3.connect(f"file:{REPO}/databases/cycloneiv/gx150.db?mode=ro", uri=True)
        dst = sqlite3.connect(snap)
        src.backup(dst)
        dst.close()
        src.close()
        log.info("snapshot of the family DB -> %s", snap)
    return snap


def stage_register(root):
    import db
    import schema
    from sqlalchemy import select, update
    import corpus_register as cr
    cr.log = log
    n = cr.register("cycloneiv", root)
    t = schema.corpus_builds.c
    nout = 0
    with db.engine().begin() as conn:
        for d in sorted(root.iterdir()):
            m = marker(d) if d.is_dir() and not d.name.startswith("_") else None
            if m and m.get("status") != "ok":
                conn.execute(update(schema.corpus_builds).where(t.design == d.name).values(
                    status=f"{m['status']}:{m.get('reason', '?')}"))
                nout += 1
            elif m and m.get("quartus"):
                conn.execute(update(schema.corpus_builds).where(t.design == d.name).values(toolchain=m["quartus"]))
        # corpus_members.build_id points at corpus_builds ids, which the re-register renumbered
        ids = {r.design: r.id for r in conn.execute(select(t.design, t.id))}
        mem = schema.corpus_members.c
        for r in list(conn.execute(select(mem.id, mem.name).where(mem.family == "cycloneiv"))):
            if r.name in ids:
                conn.execute(update(schema.corpus_members).where(mem.id == r.id).values(build_id=ids[r.name]))
    log.info("register: %d corpus_builds rows, %d failed/refused kept", n, nout)


# ---------------------------------------------------------------- evidence
def derive_names(name, result, root):
    """(base_design, spec_design) in the new tree, or None. Names recorded by the recorders, in order of use."""
    meta_base = (result or {}).get("base")
    spec_c = [name, name + "_s"]
    if name.startswith("bh_"):
        spec_c.insert(0, "gxbh_" + name.split("_")[1])
    base_c = [meta_base, name + "_b"] + ([meta_base[:-2] + "_b"] if meta_base and meta_base.endswith("_s") else [])
    spec = next((c for c in spec_c if c and (root / c).is_dir()), None)
    base = next((c for c in base_c if c and (root / c).is_dir()), None)
    return (base, spec) if base and spec and base != spec else None


def plane_keys(root, design, cache):
    import numpy as np
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    import tomllib
    if design in cache:
        return cache[design]
    d = root / design
    dev = tomllib.loads((d / "design.toml").read_text()).get("device", "EP4CE6E22C8")
    pl = cc.cram_plane((d / "bitstream.rbf").read_bytes(), cg.load(cg.die_of(dev)))
    cache[design] = (np.unique(np.asarray(pl.keys, np.int64)), int(pl.shape[1]))
    return cache[design]


def stage_evidence(root):
    import numpy as np
    import db
    import schema
    from sqlalchemy import select, update
    from provenance import evidence_io as E
    e = schema.evidence.c
    with db.engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(
            e.id, e.name, e.source_ref, e.generator, e.build_base, e.build_spec, e.result, e.bits_spec, e.bits_base).where(
            e.kind == "specimen-pair", e.family == "cycloneiv"))]
        cb = {r.design: r.id for r in conn.execute(select(schema.corpus_builds.c.design, schema.corpus_builds.c.id))}
    log.info("evidence: %d specimen-pair rows", len(rows))
    by_base = collections.defaultdict(list)
    per = collections.defaultdict(collections.Counter)
    detail, fills = [], []
    for r in rows:
        dn = derive_names(r["name"], r["result"], root)
        ref = r["source_ref"]
        if dn is None:
            per[ref]["underivable"] += 1
            continue
        by_base[dn[0]].append((r, dn))

    def work(base):
        cache = {}
        out = []
        for r, (b, s) in by_base[base]:
            if not (complete(root / b) and complete(root / s)):
                out.append((r, b, s, "not-built", 0, 0))
                continue
            kb, nvb = plane_keys(root, b, cache)
            ks, nvs = plane_keys(root, s, cache)
            if len(cache) > 6:
                for k in [k for k in cache if k != b][:-2]:
                    cache.pop(k)
            ss, sb = E.unpack(r["bits_spec"]), E.unpack(r["bits_base"])
            bad = int((~np.isin(ss, ks) | np.isin(ss, kb)).sum() + (~np.isin(sb, kb) | np.isin(sb, ks)).sum())
            meta = (r["result"] or {}).get("meta") or {}
            if bad:
                kind = "mismatch"
            elif not meta.get("plane_level") and np.array_equal(np.setdiff1d(ks, kb), ss) and np.array_equal(np.setdiff1d(kb, ks), sb):
                kind = "exact"
            else:
                kind = "stored-bits-confirmed"
            out.append((r, b, s, kind, bad, int(ss.size + sb.size)))
        return out

    with ThreadPoolExecutor(8) as ex:
        for res in ex.map(work, list(by_base)):
            for r, b, s, kind, bad, nbits in res:
                per[r["source_ref"]][kind] += 1
                if kind == "mismatch":
                    detail.append({"id": r["id"], "name": r["name"], "source_ref": r["source_ref"], "base": b, "spec": s, "bad_bits": bad, "stored_bits": nbits})
                if b in cb and s in cb:
                    fills.append((r["id"], cb[b], cb[s], r["build_base"] is None or r["build_spec"] is None))
    filled = 0
    with db.engine().begin() as conn:
        for rid, bb, bs, was_missing in fills:
            conn.execute(update(schema.evidence).where(e.id == rid).values(build_base=bb, build_spec=bs))
            filled += was_missing
    tot = collections.Counter()
    for c in per.values():
        tot.update(c)
    summ = {"rows": len(rows), "totals": dict(tot), "backfilled_build_ids": filled,
            "still_lacking": sum(1 for r in rows if (r["build_base"] is None or r["build_spec"] is None)) - filled}
    (REPO / "tmp/rebuild_evidence_migration.json").write_text(json.dumps(
        {"root": str(root), "summary": summ, "per_source_ref": {k: dict(v) for k, v in sorted(per.items())}, "mismatches": detail}, indent=1))
    log.info("evidence: %s", summ)
    for k, v in sorted(per.items()):
        if v.get("mismatch"):
            log.info("  MISMATCH %-60s %s", k, dict(v))
    return summ


# ---------------------------------------------------------------- view (derived + gates)
def make_view(root):
    """Repo look-alike: code copied, corpus/cycloneiv -> new tree, family DB = snapshot, tmp fresh; the rest symlinked."""
    v = root / "_view"
    if (v / ".ready").exists():
        return v
    shutil.rmtree(v, ignore_errors=True)
    v.mkdir()
    for p in REPO.iterdir():
        n = p.name
        if n in ("corpus", "databases", "tmp", ".claude", "__pycache__"):
            continue
        if n in ("scripts", "lifters", "provenance", "docs", "reports") or (p.is_file() and p.suffix == ".py"):
            shutil.copytree(p, v / n, ignore=shutil.ignore_patterns("__pycache__")) if p.is_dir() else shutil.copy2(p, v / n)
        else:
            os.symlink(p, v / n)
    (v / "corpus").mkdir()
    for p in (REPO / "corpus").iterdir():
        os.symlink(root if p.name == "cycloneiv" else p, v / "corpus" / p.name)
    (v / "databases" / "cycloneiv").mkdir(parents=True)
    shutil.copy2(snapshot_db(root), v / "databases/cycloneiv/gx150.db")
    for p in (REPO / "databases").iterdir():
        if p.name != "cycloneiv":
            os.symlink(p, v / "databases" / p.name)
    for p in (REPO / "databases/cycloneiv").iterdir():
        if not p.name.startswith("gx150.db"):          # never link the live DB's -wal/-shm
            os.symlink(p, v / "databases/cycloneiv" / p.name)
    (v / "tmp/logs").mkdir(parents=True)
    (v / "tmp/limits").mkdir()
    shutil.copy2(REPO / "tmp/limits/build_pool.max", v / "tmp/limits/build_pool.max")
    (v / "tmp/cycloneiv").mkdir()
    for f in ("rl_gx_m8f.json", "rl_gx_m8c.json"):      # learner tables the phys tracer reads; see derived-stage notes
        if (REPO / "tmp/cycloneiv" / f).exists():
            os.symlink(REPO / "tmp/cycloneiv" / f, v / "tmp/cycloneiv" / f)
    (v / ".ready").write_text(datetime.datetime.now().isoformat())
    log.info("view ready: %s", v)
    return v


def run_in_view(view, cmd, what):
    import heavy_guard
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=str(view / "databases/cycloneiv/gx150.db"))
    env.pop("PLURIBUS_HEAVY_HELD", None)
    t0 = time.monotonic()
    r = heavy_guard.run_stall_guarded([sys.executable, *cmd], what, log, stall_s=60, overall_s=CMD_OVERALL_S, cwd=view, env=env)
    (view / "tmp/logs" / (re.sub(r"\W+", "_", what) + ".out")).write_text(r.stdout + "\n--stderr--\n" + r.stderr)
    log.info("%s: rc=%s in %.0fs", what, r.returncode, time.monotonic() - t0)
    return r


def stage_derived(root):
    view = make_view(root)
    res = {}
    for fn, cmd in DERIVED:
        if fn is None:
            r = run_in_view(view, cmd, "prep " + cmd[0].split("/")[-1] + " " + cmd[1])
            if r.returncode != 0:
                log.error("cache prep failed: %s", (r.stderr or r.stdout)[-300:])
                res["prep:" + cmd[0]] = {"status": "failed", "rc": r.returncode}
            continue
        stored = REPO / "lifters/data" / fn
        r = run_in_view(view, cmd, f"regen {fn}")
        new = view / "lifters/data" / fn
        if r.returncode != 0:
            res[fn] = {"status": "regen-failed", "rc": r.returncode, "tail": (r.stderr or r.stdout)[-400:]}
        elif sha256(stored) == sha256(new):
            res[fn] = {"status": "identical"}
        else:
            res[fn] = {"status": "differs", "stored_bytes": stored.stat().st_size, "new_bytes": new.stat().st_size,
                       "detail": diff_artifact(stored, new)}
        log.info("derived %s: %s", fn, res[fn]["status"])
    (REPO / "tmp/rebuild_derived_diff.json").write_text(json.dumps(res, indent=1))
    return res


def diff_artifact(a, b):
    if a.suffix == ".json":
        x, y = json.loads(a.read_text()), json.loads(b.read_text())
        if isinstance(x, dict) and isinstance(y, dict):
            ks = set(x) | set(y)
            return {"keys_only_stored": len(set(x) - set(y)), "keys_only_new": len(set(y) - set(x)),
                    "values_differ": sum(1 for k in set(x) & set(y) if x[k] != y[k]), "keys": len(ks)}
        return {"len_stored": len(x), "len_new": len(y)}
    import numpy as np
    x, y = np.load(a), np.load(b)
    return {k: ("same" if k in x and k in y and np.array_equal(x[k], y[k]) else "differs") for k in sorted(set(x.files) | set(y.files))}


def claims_snapshot(dbp):
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    q = ("select s.scope_key, k.subject_key, k.tier, k.status from claims k left join scopes s on s.id=k.scope_id")
    d = collections.Counter(c.execute(q).fetchall())
    stat = dict(c.execute("select status, count(*) from claims group by 1").fetchall())
    c.close()
    return d, stat


def last_gate(dbp):
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    r = c.execute("select g.id, g.ts, g.passed, sum(x.matched), sum(x.missing), sum(x.extra), sum(x.wrong) from gate_runs g "
                  "left join gate_results x on x.run_id=g.id group by g.id order by g.id desc limit 1").fetchone()
    c.close()
    return r


def stage_gates(root):
    view = make_view(root)
    vdb = view / "databases/cycloneiv/gx150.db"
    out = {}
    before_c, before_stat = claims_snapshot(vdb)
    before_g = last_gate(vdb)
    cov_before = json.loads((REPO / "docs/coverage-history.jsonl").read_text().splitlines()[-1])
    out["claims_register_rc"] = run_in_view(view, ["scripts/claims_register.py", "--family", "cycloneiv"], "claims_register").returncode
    after_c, after_stat = claims_snapshot(vdb)
    gone, new = before_c - after_c, after_c - before_c
    out["claims"] = {"status_before": before_stat, "status_after": after_stat, "verdict_rows_removed": sum(gone.values()),
                     "verdict_rows_added": sum(new.values()), "sample_removed": [list(k) for k in list(gone)[:5]],
                     "sample_added": [list(k) for k in list(new)[:5]]}
    out["inventory_rc"] = run_in_view(view, ["scripts/cycloneiv_bit_inventory.py", "--image", str(IMAGE), "--record"], "bit_inventory").returncode
    cov_after = json.loads((view / "docs/coverage-history.jsonl").read_text().splitlines()[-1])
    keys = ("die_bits", "verified", "measured", "sampled", "predicted", "decoded", "suspect", "refuted", "unknown")
    out["inventory"] = {"before": {k: cov_before.get(k) for k in keys}, "after": {k: cov_after.get(k) for k in keys}}
    out["gate_rc"] = run_in_view(view, ["scripts/cycloneiv_ddb_trace.py", "score", "--designs", "gx150_rb*", "--split", "odd"], "gate_76").returncode
    out["gate"] = {"before": before_g, "after": last_gate(vdb)}
    out["ledger_rc"] = run_in_view(view, ["scripts/progress_ledger.py"], "progress_ledger").returncode
    (REPO / "tmp/rebuild_gates.json").write_text(json.dumps(out, indent=1, default=str))
    log.info("gates: %s", json.dumps(out, default=str)[:1500])
    return out


def stage_swap(root):
    view = root / "_view"
    cmds = f"""# Adopt the rebuild (Dan approves each line; nothing above modified the old corpus or the live DB)
mv corpus/cycloneiv corpus/cycloneiv-old-$(date +%Y%m%d)
cp -a {root} corpus/cycloneiv   # or: ln -s {root} corpus/cycloneiv ; git sees only design.toml/src as before
cp {root}/gx150.db databases/cycloneiv/gx150.db.rebuild       # snapshot with new corpus_builds ids + backfilled build_base/build_spec
cp {view}/lifters/data/cycloneiv_ep4cgx150_* lifters/data/   # only if tmp/rebuild_derived_diff.json shows the diffs are wanted
cp {view}/docs/coverage-history.jsonl docs/coverage-history.jsonl ; cp {view}/docs/progress-history.jsonl docs/ """
    log.info("swap commands:\n%s", cmds)
    print(cmds)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    ap.add_argument("--sample", type=int, default=0, help="test run: >= 2 dirs per prefix + dirs with an old rbf")
    ap.add_argument("--match", default=None)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--stages", default=",".join(STAGES))
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp/logs/cycloneiv_rebuild_all.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    for n in ("cycloneiv_fuzz", "build_pool", "heavy_guard"):
        lg = logging.getLogger(n)
        lg.setLevel(logging.INFO)
        for h in log.handlers:
            if n not in [x.name for x in lg.handlers]:
                lg.addHandler(h)
    root = Path(a.root) if a.root else OUT_ROOT / ("cycloneiv-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    root.mkdir(parents=True, exist_ok=True)
    (REPO / "tmp/rebuild_root.txt").write_text(str(root) + "\n")
    os.environ["PLURIBUS_SQLITE_PATH"] = str(snapshot_db(root))      # record_build_outcome / register / evidence go to the snapshot
    names = enumerate_designs()
    if a.match:
        import fnmatch
        names = [n for n in names if fnmatch.fnmatch(n, a.match)]
    if a.sample:
        sel = root / "sample.json"
        names = json.loads(sel.read_text()) if sel.exists() else pick_sample(names, a.sample)
        sel.write_text(json.dumps(names))
    log.info("root %s, %d designs, stages %s", root, len(names), a.stages)
    stages = a.stages.split(",")
    rc = 0
    if "build" in stages:
        st = stage_build(root, names, a.jobs)
        rc = int(any(v for k, v in st.items() if k != "ok"))
        if STOP.is_set():
            return 2
    if "determinism" in stages:
        stage_determinism(root, names)
    if "register" in stages:
        stage_register(root)
    if "evidence" in stages:
        stage_evidence(root)
    if "derived" in stages:
        stage_derived(root)
    if "gates" in stages:
        stage_gates(root)
    if "swap" in stages:
        stage_swap(root)
    return rc


if __name__ == "__main__":
    sys.exit(main())
