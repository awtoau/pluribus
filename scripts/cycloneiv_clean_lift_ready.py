#!/usr/bin/env python3.15t
"""Lift-ready set of the Cyclone IV clean pipeline (#165): designs whose recovered netlist is exact enough to start the RTL lift.

  python3.15t scripts/cycloneiv_clean_lift_ready.py [--run 26] [--limit N] [--workers 3]
A design is lift-ready when
  (1) gate run R (databases/cycloneiv/gx150.db gate_results): pips, nets, lut_init, register_clock each have 0 missing / extra / wrong;
  (2) structural check (cycloneiv_clean_emit_check.score_design): lut_site, ff_site, ff_clock, lut_carry each 0 missing / extra / wrong.
Pins are reported separately (gate category `pins`), never a blocker.  Output: reference/lift_ready.tsv (names only, one per line),
tmp/cycloneiv_clean/lift_ready_rows.json (per-design structural rows, reused by cycloneiv_clean_rtl_check.py).
Log tmp/logs/cycloneiv_clean_lift_ready.log.
"""
import argparse
import concurrent.futures as cf
import json
import logging
import os
import sqlite3
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_lift_ready")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_lift_ready.log")
DB = os.path.join(REPO, "databases", "cycloneiv", "gx150.db")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
TSV = os.path.join(REPO, "reference", "lift_ready.tsv")
GATE_CATS = ("pips", "nets", "lut_init", "register_clock")        # source: gate_results.category values of gate run 26
STRUCT_CATS = ("lut_site", "ff_site", "ff_clock", "lut_carry")    # source: cycloneiv_clean_emit_check.CATS


def gate_sets(run):
    """-> (gate_ok names, pins_clean names, all names); member name without the `@build` suffix = corpus directory."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("select m.name, g.category, g.missing + g.extra + g.wrong from gate_results g join corpus_members m on m.id = g.member_id "
                       "where g.run_id = ?", (run,)).fetchall()
    per = {}
    for n, c, f in rows:
        per.setdefault(n.split("@")[0], {})[c] = f
    ok = {n for n, d in per.items() if all(d.get(c, 1) == 0 for c in GATE_CATS)}
    pins = {n for n, d in per.items() if d.get("pins", 1) == 0}
    return ok, pins, set(per)


# decision (coordinator, 2026-10-30): all devices listed, `group` column; primary = the EP4CGX150 corpus package (DJI die), reported first
PRIMARY = "EP4CGX150DF31C7"
GROUPS = ("primary", "other-package", "other-die", "no-device-key")


DEVICES = os.path.join(REPO, "reference", "design_devices.tsv")      # design, device, rcf_device, package_pins, group (pins agent)


def group_of(root, n, _cache={}):
    if not _cache and os.path.exists(DEVICES):
        for l in open(DEVICES):
            f = l.rstrip("\n").split("\t")
            if len(f) >= 5 and f[0] != "design":
                _cache[f[0]] = f[4]
    if n in _cache:
        return _cache[n]
    import tomllib
    try:
        dev = tomllib.load(open(os.path.join(root, n, "design.toml"), "rb")).get("device")
    except (OSError, ValueError):
        dev = None
    if not dev:
        return "no-device-key"
    return "primary" if dev == PRIMARY else "other-package" if dev.startswith("EP4CGX150") else "other-die"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=26)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--reuse", action="store_true", help="reuse tmp/cycloneiv_clean/lift_ready_rows.json for designs already scored")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import cycloneiv_clean_emit_check as ck
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    ok, pins, allm = gate_sets(a.run)
    root = os.path.join(REPO, "corpus", "cycloneiv")
    names = sorted(n for n in ok if os.path.exists(os.path.join(root, n, "bitstream.rbf")) and os.path.exists(os.path.join(root, n, "postfit.vo")))
    cache = {}
    if a.reuse and os.path.exists(os.path.join(OUT, "lift_ready_rows.json")):
        cache = json.load(open(os.path.join(OUT, "lift_ready_rows.json")))
    log.info("gate run %d: members %d, gate-clean %d (on disk %d); pins-clean among all %d", a.run, len(allm), len(ok), len(names), len(pins))
    names = names[:a.limit] if a.limit else names
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.4)
    rows, t0 = {n: cache[n] for n in names if n in cache}, time.time()
    with heavy_guard.lease(gb, "cyc4_clean_lift_ready", log):
        cx = emit.Ctx()
        from lifters.cycloneiv_clean import tracer as T
        cx.res = T.Resolver(cx.rt)
        cx.st.edge_ids([0], [0])
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(ck.score_design, cx, os.path.join(root, n), 2): n for n in names if n not in rows}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=60, return_when=cf.FIRST_COMPLETED)
                if not done:                      # stall guard: no design finished in 60 s
                    log.error("stall: no design finished in 60 s (%d pending, load %s)", len(pending), os.getloadavg())
                    raise SystemExit(3)
                for f in done:
                    n = futs[f]
                    try:
                        r = f.result()
                        rows[n] = {c: r["cats"][c] for c in STRUCT_CATS}
                    except Exception as e:        # unscorable = not lift-ready, recorded
                        rows[n] = {"error": f"{type(e).__name__}: {e}"}
                        log.error("%s: %s", n, rows[n]["error"])
                if len(rows) % 200 < len(done):
                    log.info("scored %d / %d %.0fs", len(rows), len(names), time.time() - t0)
    grp = {n: group_of(root, n) for n in names}
    bad = {c: 0 for c in STRUCT_CATS}
    ready = []
    for n in names:
        r = rows[n]
        if "error" in r:
            continue
        fl = [c for c in STRUCT_CATS if r[c]["missing"] + r[c]["extra"] + r[c]["wrong"]]
        for c in fl:
            bad[c] += 1
        if not fl:
            ready.append(n)
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(os.path.join(OUT, "lift_ready_rows.json"), "w"))
    if not a.limit:
        os.makedirs(os.path.dirname(TSV), exist_ok=True)
        open(TSV, "w").write("# lift-ready designs: gate run %d pips/nets/lut_init/register_clock clean + structural lut_site/ff_site/ff_clock/lut_carry clean\n" % a.run +
                              "name\tgroup\n" + "".join(f"{n}\t{grp[n]}\n" for n in ready))
        for g in GROUPS:
            log.info("group %-14s lift-ready %d of gate-clean %d", g, sum(1 for n in ready if grp[n] == g), sum(1 for n in names if grp[n] == g))
    ready_pins = sum(1 for n in ready if n in pins)
    log.info("RESULT gate-clean %d, scored %d, errors %d, structural failures by category %s, LIFT-READY %d (pins-clean among them %d, pins faulty %d: reported, not a blocker)",
             len(ok), len(rows), sum(1 for r in rows.values() if "error" in r), bad, len(ready), ready_pins, len(ready) - ready_pins)


if __name__ == "__main__":
    main()
