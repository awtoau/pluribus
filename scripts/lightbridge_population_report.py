#!/usr/bin/env python3
"""Summarise tmp/ofdm_pop/{num,pop}_*.jsonl: numerology groups, per-burst table, similarity clusters (#165).
Output: tmp/ofdm_pop/report.txt and tmp/ofdm_pop/table.tsv (counts/parameters only).
"""
import glob
import json
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

ROOT = Path(__file__).resolve().parents[1]
POP = ROOT / "tmp" / "ofdm_pop"
OUT = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def load(prefix):
    rows = []
    for fn in sorted(glob.glob(str(POP / f"{prefix}_*.jsonl"))):
        rows += [json.loads(l) for l in open(fn)]
    return rows


def m(v, i=0):
    return None if v is None else v[i]


def classify(r):
    if r.get("n_fit", 0) == 0:
        return "unfit"
    df, cp, used = m(r["med_df_hz"]), m(r["med_cp_ratio"]), m(r["med_used_1024"])
    if abs(df - 10937.5) < 20 and abs(cp - 0.125) < 0.004:
        return "A: 10937.5 Hz, CP 1/8"
    if abs(df - 15000) < 40 and abs(cp - 1 / 14) < 0.004:
        return "B: 15000 Hz, CP 1/14"
    return "C: other"


def numerology():
    rows = load("num")
    p("== A. numerology per file (median over fitted wide bursts, z>8 and T-line>8) ==")
    p("file | band | n_wide | fit/tried | df Hz | CP/Tu | Tsym us | used carriers(1024-grid) | DC dB | -20dB bw MHz | burst ms | frame ms | narrow bursts (n, ms, MHz, centres) | group")
    groups = {}
    for r in rows:
        if r.get("load_failed"):
            p(r["file"], "LOAD FAILED")
            continue
        g = classify(r)
        r["group"] = g
        name = r.get("file")
        if r["dataset"] == "genesys":
            groups.setdefault(g, []).append(("genesys", r["device"], r["dist"]))
            continue
        groups.setdefault(g, []).append((r["dataset"], r.get("device") or name, name))
        f = lambda k, n=2: None if r.get("med_" + k) is None else round(r["med_" + k][0], n)  # noqa: E731
        p(name, "|", r.get("band", "2.44"), "|", r.get("n_wide"), "|", f"{r['n_fit']}/{r['n_tried']}", "|", f("df_hz", 1), "|",
          f("cp_ratio", 4), "|", f("tsym_us"), "|", f("used_1024", 0), "|", f("dc_db", 1), "|", f("bw_mhz"), "|", f("dur_ms"), "|",
          None if r.get("frame_period_ms_med") is None else round(r["frame_period_ms_med"], 2), "|",
          (r.get("n_narrow"), None if r.get("narrow_dur_ms_med") is None else round(r["narrow_dur_ms_med"], 2),
           None if r.get("narrow_bw_mhz_med") is None else round(r["narrow_bw_mhz_med"], 2), r.get("narrow_n_centres")), "|", g)
    gen = [r for r in rows if r["dataset"] == "genesys"]
    if gen:
        ok = [r for r in gen if r["n_fit"]]
        p(f"GENESYS M100 (single pre-cut burst per file): {len(ok)}/{len(gen)} fitted; df {np.median([m(r['med_df_hz']) for r in ok]):.1f} Hz "
          f"(min {min(m(r['med_df_hz']) for r in ok):.1f}, max {max(m(r['med_df_hz']) for r in ok):.1f}); CP {np.median([m(r['med_cp_ratio']) for r in ok]):.4f}; "
          f"used(1024 grid, edge-filter limited) {np.median([m(r['med_used_1024']) for r in ok if r['med_used_1024']]):.0f}")
    p("== groups by measured numerology (file counts; GENESYS counted per file) ==")
    for g, v in sorted(groups.items()):
        p(g, len(v), sorted({(a, b) for a, b, _ in v}))


def population():
    rows = load("pop")
    p("\n== B. per-burst population ==")
    fail = [r for r in rows if r.get("failed")]
    nowide = [r for r in rows if r.get("no_wide_bursts")]
    ok = [r for r in rows if "nsym" in r]
    p(f"records {len(rows)}: demod ok {len(ok)}, demod failed {len(fail)}, files with no wide burst {len(nowide)}")
    for r in fail:
        p("  failed:", r["tag"])
    for r in nowide:
        p("  no wide burst:", r["file"], r["device"])
    cols = ["tag", "dataset", "device", "dist", "kind", "nsym", "lead", "cp_q", "edge_err", "occ_bins", "pilot_agree", "hilo", "r_oddsym", "r_evensym",
            "alt_prod", "dphi_deg", "dphi_conc", "sym0_met_min", "sym0_k4", "sym1_cv", "sym2_cv", "k4", "m4", "snr_db"]
    with open(POP / "table.tsv", "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in ok:
            f.write("\t".join("" if r.get(c) is None else (f"{r[c]:.3f}" if isinstance(r[c], float) else str(r[c])) for c in cols) + "\n")
    lb = [r for r in ok if r["pilot_agree"] > 0.9 and r["cp_q"] > 0.8]
    p(f"bursts with Lightbridge pilot pattern (class agree>0.9, CP corr>0.8): {len(lb)}/{len(ok)}")
    other = [r for r in ok if r not in lb]
    for r in other:
        p(f"  not fitting the 1024/CP1/8/9-grid demod: {r['tag']} cp_q={r['cp_q']:.2f} agree={r['pilot_agree']:.2f}")
    p("device/dataset/dist groups (n; nsym; lead; hilo median [min,max]; alt_prod; dphi deg circ-median; k4; snr):")
    keyf = lambda r: (r["dataset"], r["device"], r.get("dist", ""))  # noqa: E731
    gk = {}
    for r in lb:
        gk.setdefault(keyf(r), []).append(r)
    for k, v in sorted(gk.items()):
        a = lambda c: np.array([x[c] for x in v if x.get(c) is not None], float)  # noqa: E731
        p(k, len(v), "nsym", sorted(set(int(x["nsym"]) for x in v)), "lead", sorted(set(int(x["lead"]) for x in v)),
          "hilo %.2f [%.2f,%.2f]" % (np.median(a("hilo")), a("hilo").min(), a("hilo").max()), "alt %.2f" % np.median(a("alt_prod")),
          "dphi %.0f [%.0f,%.0f]" % (np.median(a("dphi_deg")), a("dphi_deg").min(), a("dphi_deg").max()), "k4 %.2f" % np.median(a("k4")),
          "snr %.0f" % np.median(a("snr_db")))
    # clustering
    p("\n== clusters (Ward on standardised log hilo, dphi as 2-vector on doubled angle, alt_prod, k4) ==")
    feat = np.array([[np.log(r["hilo"]), np.cos(np.radians(2 * r["dphi_signed_deg"])), np.sin(np.radians(2 * r["dphi_signed_deg"])),
                      np.log(r["alt_prod"]), r["k4"]] for r in lb])
    z = (feat - feat.mean(0)) / (feat.std(0) + 1e-9)
    L = linkage(z, "ward")
    for ncl in (3, 5, 8):
        lab = fcluster(L, ncl, "maxclust")
        p(f"-- {ncl} clusters")
        for c in sorted(set(lab)):
            mem = [lb[i] for i in range(len(lb)) if lab[i] == c]
            comp = {}
            for r in mem:
                comp[(r["dataset"], r["device"])] = comp.get((r["dataset"], r["device"]), 0) + 1
            hl = np.median([x["hilo"] for x in mem])
            dp = np.median([x["dphi_signed_deg"] for x in mem])
            p(f"   cluster {c}: n={len(mem)} hilo~{hl:.2f} dphi~{dp:.0f} composition {dict(sorted(comp.items()))}")
    # variance explained by device (eta^2) for hilo and dphi, within genesys by distance
    def eta2(vals, labels):
        vals = np.asarray(vals, float)
        gm = vals.mean()
        ss_t = ((vals - gm) ** 2).sum()
        ss_b = sum(((vals[[i for i, l in enumerate(labels) if l == g]].mean() - gm) ** 2) * labels.count(g) for g in set(labels))
        return ss_b / ss_t if ss_t else float("nan")
    for name, sel in (("GENESYS (7 UAVs)", [r for r in lb if r["dataset"] == "genesys"]),):
        if len(sel) > 5:
            lh = [np.log(r["hilo"]) for r in sel]
            p(name, f"n={len(sel)}: eta^2 of log(hilo) explained by UAV {eta2(lh, [r['device'] for r in sel]):.2f}, by distance {eta2(lh, [r['dist'] for r in sel]):.2f}")
            dp = [np.cos(np.radians(2 * r['dphi_signed_deg'])) for r in sel]
            p(name, f"eta^2 of cos(2*dphi) by UAV {eta2(dp, [r['device'] for r in sel]):.2f}, by distance {eta2(dp, [r['dist'] for r in sel]):.2f}")
    for dsn in ("zenodo", "kuleuven"):
        sel = [r for r in lb if r["dataset"] == dsn]
        if len(sel) > 5:
            lh = [np.log(r["hilo"]) for r in sel]
            p(dsn, f"n={len(sel)}: eta^2 of log(hilo) by device {eta2(lh, [r['device'] for r in sel]):.2f}; within-device spread std(log hilo) per device:",
              {d: round(float(np.std([np.log(r['hilo']) for r in sel if r['device'] == d])), 3) for d in sorted({r['device'] for r in sel})})
    # per-device summary across datasets
    p("\nInspire2: Zenodo vs KU hilo/dphi/k4:")
    for dsn in ("zenodo", "kuleuven"):
        sel = [r for r in lb if r["device"].startswith("Inspire2") and r["dataset"] == dsn]
        if sel:
            p("  ", dsn, len(sel), "hilo %.2f dphi %.0f k4 %.2f" % (np.median([r["hilo"] for r in sel]), np.median([r["dphi_deg"] for r in sel]), np.median([r["k4"] for r in sel])))
    (POP / "report.txt").write_text("\n".join(OUT) + "\n")


if __name__ == "__main__":
    numerology()
    population()
