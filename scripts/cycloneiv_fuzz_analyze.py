#!/usr/bin/env python3.15t
"""Recover LE LUT-mask and FF power-up bits from the corpus/cycloneiv fuzz builds; score against
the post-fit .vo (oracle) as matched / missing / extra / wrong.

- Bit address: (frame, bit), frame = index in the file from the header frame (0); bit = byte*8 +
  LSB-first bit within the frame.  CRAM frames from cycloneiv_decompress (CRC bytes excluded).
- LUT: per site, map vo lut_mask bit k -> the CRAM bit equal (or inverse) to it in every TRAIN
  build (one-hot masks); score on HELD-OUT builds (one-cold + specials).
- extra = bits that differ between the site's builds but no mask bit explains.
- FF power_up: bit(s) that flip between ff_low_<x> and ff_high_<x>; derived on _base, scored on
  the other control variants.

  python3.15t scripts/cycloneiv_fuzz_analyze.py [--json out.json]
Log: tmp/logs/cycloneiv_fuzz_analyze.log
"""
import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_decompress as cd  # noqa: E402
import cyclonev_vo_parse as vp  # noqa: E402

vp.OUT_PORTS.update({
    "cycloneive_lcell_comb": {"combout", "cout"},
    "cycloneive_io_ibuf": {"o"},
    "cycloneive_io_obuf": {"o", "obar"},
    "cycloneive_clkctrl": {"outclk"},
})
log = logging.getLogger("cycloneiv_fuzz_analyze")


def load(name):
    d = CORPUS / name
    raw = (d / "bitstream.rbf").read_bytes()
    info = {}
    u = cd.decompress(raw, info)
    f, r, n = info["frame"], info["periphery_frames"], info["cram_frames"]
    ones = set()
    for fr in range(1, r + n):
        base = cd.PREAMBLE + fr * f
        width = f if fr < r else f - 2
        chunk = u[base:base + width]
        for i, b in enumerate(chunk):
            if b:
                for j in range(8):
                    if b >> j & 1:
                        ones.add((fr, i * 8 + j))
    vo = vp.Vo().parse(top_module_only(d / "postfit.vo"))
    return name, {"ones": ones, "vo": vo, "geom": (f, r, n)}


def top_module_only(path):
    """Cyclone IV .vo extras the Cyclone V parser rejects: the SDF annotate line, the
    `hard_block` instance and module (config pins only).  Every other line still goes through
    the strict parser.  Filtered copy -> tmp/cycloneiv/vo/<design>.vo."""
    out, skip = [], False
    lines = path.read_text().split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("initial $sdf_annotate("):
            i += 1
            continue
        if ln.startswith("hard_block auto_generated_inst("):
            while not lines[i].rstrip().endswith(");"):
                i += 1
            i += 1
            continue
        if ln.startswith("module hard_block"):
            skip = True
        if not skip:
            out.append(ln)
        if skip and ln.strip() == "endmodule":
            skip = False
        i += 1
    dst = REPO / "tmp" / "cycloneiv" / "vo" / (path.parent.name + ".vo")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out))
    return dst


def lut_atom(vo, site):
    for nm, a in vo.atoms.items():
        if a["type"] == "cycloneive_lcell_comb" and a["location"] == site:
            return nm, a
    return None, None


def mask_of(a):
    return int(a["params"]["lut_mask"].split("'h")[1], 16)


def inputs_of(a):
    return tuple(sorted((p, vo_net) for p, _b, dirn, vo_net, _i, _c in a["conns"] if dirn == "in"))


def lut_site(builds, tag, site):
    names = sorted(n for n in builds if n.startswith(f"lut_{tag}_"))
    rows = {}
    for n in names:
        nm, a = lut_atom(builds[n]["vo"], site)
        if a is None:
            log.info("  %s: no LUT at %s in .vo (placement not honoured)", n, site)
            continue
        rows[n] = (mask_of(a), inputs_of(a), builds[n]["ones"])
    req = {n: int(n.rsplit("_", 1)[1], 16) for n in rows}
    train = [n for n in rows if bin(req[n]).count("1") == 1]
    test = [n for n in rows if n not in train]
    if not train or not test:
        log.info("  %s: %d train / %d test builds: nothing to score", site, len(train), len(test))
        return {"site": site, "builds": len(rows), "train": len(train), "test": len(test), "score": None}
    inmaps = {rows[n][1] for n in rows}
    vary = set().union(*(rows[n][2] for n in rows)) - set.intersection(*(rows[n][2] for n in rows))
    bitmap = {}
    for k in range(16):
        hits = []
        for c in vary:
            v = [(c in rows[n][2]) for n in train]
            m = [bool(rows[n][0] >> k & 1) for n in train]
            if v == m:
                hits.append((c, False))
            elif v == [not x for x in m]:
                hits.append((c, True))
        bitmap[k] = hits
    explained = {c for h in bitmap.values() for c, _ in h}
    score = {"matched": 0, "missing": 0, "wrong": 0, "extra": 0}
    for n in test:
        m, _, ones = rows[n]
        for k in range(16):
            if len(bitmap[k]) != 1:
                score["missing"] += 1
                continue
            c, inv = bitmap[k][0]
            pred = (c in ones) != inv
            score["matched" if pred == bool(m >> k & 1) else "wrong"] += 1
        # extra: a varying bit no mask bit explains, set differently from its value in train[0]
        ref = rows[train[0]][2]
        score["extra"] += sum(1 for c in vary - explained if (c in ones) != (c in ref))
    vo_ne_req = sum(1 for n in rows if rows[n][0] != req[n])
    return {"site": site, "builds": len(rows), "train": len(train), "test": len(test),
            "input_maps": len(inmaps), "vo_mask_differs_from_requested": vo_ne_req,
            "varying_bits": len(vary), "unexplained_varying_bits": len(vary - explained),
            "bitmap": {k: [[c[0], c[1], inv] for c, inv in h] for k, h in bitmap.items()},
            "score": score}


def ff_power_up(builds):
    variants = sorted(n[len("ff_low_"):] for n in builds if n.startswith("ff_low_") and
                      f"ff_high_{n[len('ff_low_'):]}" in builds)
    diffs = {v: builds[f"ff_low_{v}"]["ones"] ^ builds[f"ff_high_{v}"]["ones"] for v in variants}
    out = {"variants": variants, "diff_sizes": {v: len(d) for v, d in diffs.items()}}
    if "base" not in diffs:
        return out
    derived = diffs["base"]
    out["derived_bits"] = sorted(derived)
    score = {"matched": 0, "missing": 0, "wrong": 0, "extra": 0}
    for v in variants:
        if v == "base":
            continue
        for pu in ("low", "high"):
            vo = builds[f"ff_{pu}_{v}"]["vo"]
            ff = next(a for a in vo.atoms.values() if a["type"] == "dffeas")
            truth = ff["params"].get("power_up", "low") == "high"
            ones = builds[f"ff_{pu}_{v}"]["ones"]
            ref_low = builds["ff_low_base"]["ones"]
            if not derived:
                score["missing"] += 1
                continue
            # predicted high when every derived bit differs from the low-base value
            pred = all((c in ones) != (c in ref_low) for c in derived)
            same = all((c in ones) == (c in ref_low) for c in derived)
            if not pred and not same:
                score["wrong"] += 1
            else:
                score["matched" if pred == truth else "wrong"] += 1
        score["extra"] += len(diffs[v] - derived)
    out["score"] = score
    return out


def ff_controls(builds):
    """Bits each control adds vs ff_low_base (routing + LE/LAB config, not yet separated)."""
    base = builds.get("ff_low_base")
    if not base:
        return {}
    return {n: {"set": len(builds[n]["ones"] - base["ones"]), "cleared": len(base["ones"] - builds[n]["ones"]),
                "frames": sorted({c[0] for c in builds[n]["ones"] ^ base["ones"]})}
            for n in sorted(builds) if n.startswith("ff_low_") and n != "ff_low_base"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(REPO / "tmp" / "cycloneiv" / "fuzz_analysis.json"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_fuzz_analyze.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    names = sorted(p.name for p in CORPUS.iterdir() if (p / "bitstream.rbf").exists())
    with ThreadPoolExecutor(a.workers) as ex:
        builds = dict(ex.map(load, names))
    log.info("%d builds loaded; geometry %s", len(builds), {b["geom"] for b in builds.values()})
    import cycloneiv_fuzz as fz
    res = {"lut": [], "ff_power_up": ff_power_up(builds), "ff_controls": ff_controls(builds)}
    for site, tag in fz.LUT_SITES:
        r = lut_site(builds, tag, site)
        res["lut"].append(r)
        s = r["score"]
        if s is None:
            continue
        tot = sum(s.values())
        log.info("LUT %s: %d builds (train %d one-hot, test %d), input maps %d, vo mask != requested %d",
                 site, r["builds"], r["train"], r["test"], r["input_maps"], r["vo_mask_differs_from_requested"])
        log.info("  held-out mask bits: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.1f%%",
                 s["matched"], s["matched"], s["missing"], s["extra"], s["wrong"], 100 * s["matched"] / max(tot, 1))
        log.info("  varying bits %d, unexplained %d; map k -> (frame, bit, inverted): %s", r["varying_bits"],
                 r["unexplained_varying_bits"], {k: v for k, v in r["bitmap"].items()})
    p = res["ff_power_up"]
    log.info("FF power_up: diff sizes %s; derived bits %s", p.get("diff_sizes"), p.get("derived_bits"))
    if "score" in p:
        s = p["score"]
        log.info("  held-out power_up: matched %d / (matched %d + missing %d + extra %d + wrong %d)",
                 s["matched"], s["matched"], s["missing"], s["extra"], s["wrong"])
    for n, c in res["ff_controls"].items():
        log.info("FF control %-16s vs base: +%d -%d bits in frames %s", n, c["set"], c["cleared"], c["frames"])
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(res, indent=1, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
