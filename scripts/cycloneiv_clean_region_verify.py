#!/usr/bin/env python3.15t
"""Deterministic check of a model-proposed region name's `predicted_test` against the netlist (#189 crawl step 3).  No LLM.

  python3.15t scripts/cycloneiv_clean_region_verify.py --nl tmp/image_sim_dji_push/nl.pkl --blob 802.16-tx --model gpt-oss:20b [--write-blocks]
Inputs: tmp/cycloneiv_clean/regions/<blob>/{cell_region.json, <rid>.json, names/<model>/<rid>.json}, regions/patterns.json.
Output: regions/<blob>/verify_<model>.json (pass / fail / untestable per region + detail); log tmp/logs/cycloneiv_clean_region_verify.log.
--write-blocks: PASS on a DISCRIMINATING test -> boards/dji-m2001/blocks.json `blocks` as conf V (seeds = the region's cells); every other
named region -> blocks.json `proposed` (conf I, never V).  Discriminating = lfsr_poly / crc_poly / rom_shape cos|sin|bitrev|gf_log;
generic tests (fifo, counter, mac_chain, xor_taps, ramp, step, decay) only support conf I.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
RG = os.path.join(REPO, "tmp", "cycloneiv_clean", "regions")
log = logging.getLogger("region_verify")
DISCRIMINATING = {"lfsr_poly", "crc_poly", "rom_shape:cos", "rom_shape:sin", "rom_shape:bitrev", "rom_shape:gf_log"}
TONE_RMS = 0.02           # decision: cos/sin fit passes when RMS residual <= 2% of amplitude (quantised 12-bit tables fit ~0.05%)


def exps(poly):
    """'x^15+x^14+1' / 'x15+x+1' / '15,14,0' -> frozenset of exponents."""
    s = str(poly).replace(" ", "").replace("^", "").lower()
    if re.fullmatch(r"[\d,]+", s):
        return frozenset(int(t) for t in s.split(",") if t)
    out = set()
    for t in s.split("+"):
        if t == "1":
            out.add(0)
        elif t == "x":
            out.add(1)
        elif m := re.fullmatch(r"x(\d+)", t):
            out.add(int(m[1]))
    return frozenset(out)


def recip(e):
    n = max(e)
    return frozenset(n - k for k in e)


def same_poly(a, b):
    return bool(a and b) and (a == b or a == recip(b))


def signed(v, w):
    return v - (1 << w) if v >> (w - 1) & 1 else v


def reachable_words(m):
    """ROM words the read address can reach: address bits tied to a constant restrict the window."""
    init = list(m.get("init") or [])
    ab = m.get("raddr") or m.get("addr") or []
    fixed = {i: int(b[-1]) for i, b in enumerate(ab) if b in ("1'b0", "1'b1")}
    if not fixed:
        return init
    return [v for i, v in enumerate(init) if all(((i >> b) & 1) == val for b, val in fixed.items())]


def field_views(words, W):
    for f in sorted({W, 18, 16, 12, 9, 8} - {0}, reverse=True):
        if f > W or W % f:
            continue
        for j in range(W // f):
            raw = [(v >> (j * f)) & ((1 << f) - 1) for v in words]
            if len(set(raw)) >= 3:
                yield f"{'word' if f == W else f'field[{j * f + f - 1}:{j * f}]'}", f, raw


def tone_fit(x):
    """Least-squares A cos(2 pi k n / N + phi) + c with k refined around the FFT peak -> (rms_rel, A, period_words)."""
    n = len(x)
    t = np.arange(n)
    p = np.abs(np.fft.rfft(x - x.mean()))
    k0 = int(np.argmax(p[1:]) + 1)
    best = None
    for k in np.linspace(max(0.25, k0 - 1), k0 + 1, 81):
        M = np.column_stack([np.cos(2 * np.pi * k * t / n), np.sin(2 * np.pi * k * t / n), np.ones(n)])
        coef, *_ = np.linalg.lstsq(M, x, rcond=None)
        A = float(np.hypot(coef[0], coef[1]))
        if A == 0:
            continue
        rms = float(np.sqrt(np.mean((M @ coef - x) ** 2))) / A
        if best is None or rms < best[0]:
            best = (rms, A, n / k)
    return best


def rom_shape(words, W, A, want):
    res = []
    if not any(words):
        return False, "all-zero (RAM, not ROM)"
    if want == "bitrev":
        ok = all(words[i] == int(format(i, f"0{A}b")[::-1], 2) for i in range(len(words)))
        return ok, "bit-reversal permutation" if ok else "not a bit-reversal permutation"
    if want == "gf_log":
        m = max(words).bit_length()
        seq = words[:(1 << m) - 1]
        ok = 3 <= m <= 16 and sorted(seq) == list(range(1, 1 << m))
        return ok, f"permutation of 1..2^{m}-1" if ok else "not a GF log/antilog permutation"
    for name, f, raw in field_views(words, W):
        for sg in (False, True):
            x = np.array([signed(v, f) if sg else v for v in raw], dtype=float)
            if np.ptp(x) == 0 or len(x) < 16:
                continue
            tag = f"{name} {f}b {'signed' if sg else 'unsigned'}"
            d = np.diff(x)
            mono = bool(np.all(d >= 0) or np.all(d <= 0))
            if want in ("cos", "sin"):
                fit = tone_fit(x)
                if fit and fit[0] <= TONE_RMS:
                    return True, f"{tag}: tone fit rms {100 * fit[0]:.2f}% of A={fit[1]:.0f}, period {fit[2]:.1f} words"
                if fit:
                    res.append(f"{tag}: best tone rms {100 * fit[0]:.1f}%")
            elif want == "ramp":
                r = np.corrcoef(np.arange(len(x)), x)[0, 1]
                if abs(r) > 0.9995:
                    return True, f"{tag}: linear ramp r={r:.5f}"
            elif want == "step":
                if mono and len(set(raw)) <= 8:
                    return True, f"{tag}: monotone {len(set(raw))}-level step"
            elif want == "decay":
                a = np.abs(x)
                if np.all(np.diff(a) <= 0) and a[0] > 8 * max(a[-1], 1):
                    return True, f"{tag}: |x| monotone decay {a[0]:.0f}->{a[-1]:.0f}"
    return False, "; ".join(res[:4]) or f"no {want} shape in any field view"


class Verifier:
    def __init__(self, nl, blob):
        from lifters.cycloneiv_clean import patterns as PT
        self.nl, self.blob = nl, blob
        self.m9k = {(m["x"], m["y"]): m for m in nl.m9k}
        self.lut = {L["name"]: L for L in nl.luts}
        self.ff = {F["name"]: F for F in nl.ffs}
        self.pat = json.load(open(os.path.join(RG, "patterns.json")))
        self.cells = collections.defaultdict(set)
        for c, r in json.load(open(os.path.join(RG, blob, "cell_region.json"))).items():
            self.cells[r].add(c)
        self.D = PT.Design(nl)

    def facts(self, rid):
        return json.load(open(os.path.join(RG, self.blob, f"{rid}.json")))

    def groups(self, rid, kinds):
        cells = self.cells[rid]
        return [g for k in kinds for g in self.pat[k] if set(g["members"]) & cells]

    def roms(self, rid):
        return [self.m9k[(int(c.split("_")[1]), int(c.split("_")[2]))] for c in self.cells[rid] if c.startswith("m9k_")]

    def check(self, rid, test):
        """test: 'kind=value' -> (verdict, test_key, detail).  verdict in pass / fail / untestable."""
        if not test or "=" not in str(test):
            return "untestable", None, "no concrete predicted_test"
        if "|" in str(test):            # the menu echoed back = several guesses; scoring the best one would reward shotgun answers
            return "untestable", None, "several alternative tests given (not one concrete prediction)"
        kind, val = (s.strip() for s in str(test).split("=", 1))
        kind = kind.lower()
        if kind in ("lfsr_poly", "crc_poly"):
            want = exps(val)
            if len(want) < 2:
                return "untestable", kind, f"cannot parse polynomial {val!r}"
            gs = self.groups(rid, ("lfsr",) if kind == "lfsr_poly" else ("parallel",))
            if not gs:
                gs = self.groups(rid, ("lfsr", "parallel"))
            for g in gs:
                cands = [exps(g["poly"])] + [exps(m[0].split(" ")[0]) for m in g.get("match", [])]
                if any(same_poly(want, c) for c in cands):
                    if g.get("conf") == "low":     # degenerate / rank-deficient group (e.g. x5+1): structure, not a discriminating poly
                        return "pass", "lfsr_lowconf", f"low-confidence {g['kind']} n={g['n']} poly {g['poly']}"
                    return "pass", kind, f"{g['kind']} n={g['n']} poly {g['poly']} matches {val} (direct or reciprocal); members {g['members'][:3]}..."
            got = [g["poly"] for g in gs]
            return ("fail" if gs else "fail"), kind, f"region LFSR/CRC groups {got or 'none'} do not match {val}"
        if kind == "rom_shape":
            want = val.lower().split()[0].strip("'\"")
            if want in ("monotone", "exp", "exp_decay", "decay"):
                want = "decay"
            roms = [m for m in self.roms(rid) if any(m.get("init") or [])]
            if not roms:
                return "fail", f"rom_shape:{want}", "region has no M9K with non-zero init"
            det = []
            for m in roms:
                ok, d = rom_shape(reachable_words(m), int(m["W"]), int(m["A"]), want)
                det.append(f"M9K({m['x']},{m['y']}): {d}")
                if ok:
                    return "pass", f"rom_shape:{want}", det[-1]
            return "fail", f"rom_shape:{want}", " | ".join(det)
        if kind in ("counter_terminal", "counter"):
            fs = self.facts(rid)
            ctr = [c for c in fs["carry_chains"] if "counter" in c["kind"] or c["feedback"]]
            try:
                n = int(str(val).split()[0], 0)
            except ValueError:
                n = None
            if not ctr:
                return "fail", "counter", "no counter-shaped carry chain in region"
            if n is None:
                return "pass", "counter", f"{len(ctr)} counter chains (terminal value not checked)"
            fit = [c for c in ctr if c["len"] >= max(1, n.bit_length() - 1)]
            return ("pass" if fit else "fail"), "counter", f"counters {[c['len'] for c in ctr]} bits vs terminal {n} ({n.bit_length()} bits); terminal value itself not decoded"
        if kind in ("fifo", "ram_fifo", "fifo_depth"):
            cells = self.cells[rid]
            rams = [r for r in self.pat["m9k_addr"] if f"m9k_{r['xy'][0]}_{r['xy'][1]}" in cells and not r.get("rom")]
            cnt = [r for r in rams if "counter" in str(r.get("cls"))]
            return ("pass" if cnt else "fail"), "fifo", f"{len(cnt)}/{len(rams)} RAM tiles addressed by counters ({sorted({r['cls'] for r in rams})})"
        if kind in ("mac_chain", "mac", "multiplier"):
            fs = self.facts(rid)
            if not fs["mac"]:
                return "fail", "mac", "no MAC in region"
            chain = [m for m in fs["mac"] if any(k.startswith("mac") for op in m["operand_src"].values() for k in op)]
            return "pass", "mac", f"{len(fs['mac'])} MAC, {len(chain)} fed by another MAC"
        if kind in ("xor_taps", "xor"):
            fs = self.facts(rid)
            fn = {**fs["lut_functions"], **fs["output_cones"]["small_cone_functions"]}
            try:
                k = int(str(val).strip("[]").split(",")[0]) if "," not in str(val) else len(str(val).strip("[]").split(","))
            except ValueError:
                k = 2
            hit = {f: n for f, n in fn.items() if f.startswith("xor") and int(f[3:]) >= min(k, 2)}
            return ("pass" if hit else "fail"), "xor", f"xor functions present: {hit or 'none'}"
        if kind in ("sim_vector", "sim"):
            return "untestable", "sim", "region-only simulation not implemented in this pass"
        return "untestable", kind, f"unknown test kind {kind!r}"


def name_consistent(name, best):
    """Does the role word in the name agree with what the passing test proved?  None = nothing to compare."""
    n = str(name or "").lower()
    if best[0] != "pass" or best[1] is None:
        return None
    if best[1].startswith("lfsr"):
        return any(k in n for k in ("random", "scrambl", "prbs", "lfsr", "pilot", "whiten"))
    if best[1] == "crc_poly" or "CRC" in best[2]:
        return "crc" in n
    if best[1].startswith("rom_shape"):
        return any(k in n for k in ("rom", "twiddle", "table", "lut", "bitrev"))
    return None


def cell_seeds(cells):
    s = dict(ffs=[], luts=[], labs=[], m9k=[], mac=[], pads=[])
    for c in sorted(cells):
        if c.startswith("ff_"):
            s["ffs"].append(c)
        elif c.startswith("lc_"):
            s["luts"].append(c)
        elif c.startswith("m9k_"):
            s["m9k"].append([int(t) for t in c.split("_")[1:3]])
        elif c.startswith("mac_"):
            s["mac"].append([int(t) for t in c.split("_")[1:3]])
    return s


def write_blocks(board, verdicts, V):
    path = os.path.join(board, "blocks.json")
    bj = json.load(open(path))
    keep = [b for b in bj["blocks"] if not (str(b.get("evidence", "")).startswith("region-verify") and f"({V.blob}-r" in str(b.get("evidence", "")))]
    taken = {b["name"] for b in keep}
    prop = [p for p in bj.get("proposed", []) if p.get("blob") != V.blob]
    nv = 0
    for rid, r in sorted(verdicts.items()):
        name = r.get("name")
        if not name or name.endswith("unknown") or "glue" in name:
            continue
        if r["verdict"] == "pass" and r["test_key"] in DISCRIMINATING:
            # the V block is named by WHAT WAS VERIFIED (structure), not by the model's role guess; the role stays a proposal (conf I)
            fact = r["test_key"].replace("rom_shape:", "rom-").replace("_poly", "") + "-" + re.sub(r"[^0-9a-z+]", "", str(r["test"]).split("=", 1)[-1].lower())[:24]
            nm = f"802.16-{fact}-{rid.rsplit('-', 1)[-1]}"
            if nm in taken:
                continue
            taken.add(nm)
            keep.append(dict(name=nm, confidence="V", evidence=f"region-verify {r['test_key']}: {r['detail'][:200]} ({rid})",
                             note=f"crawl #189; region {rid}; role proposed by {r['model']}: {name} (I, see proposed)", seeds=cell_seeds(V.cells[rid])))
            prop.append(dict(name=name, confidence="I", blob=V.blob, region=rid, model=r["model"], model_confidence=r.get("confidence"),
                             verify="pass (structure only)", test=r.get("test"), detail=r["detail"][:200]))
            nv += 1
        else:
            prop.append(dict(name=name, confidence="I", blob=V.blob, region=rid, model=r["model"], model_confidence=r.get("confidence"),
                             verify=r["verdict"], test=r.get("test"), detail=r["detail"][:200]))
    bj["blocks"], bj["proposed"] = keep, prop
    json.dump(bj, open(path, "w"), indent=1)
    log.info("blocks.json: %d region-verify V blocks for %s, %d proposed (I) total", nv, V.blob, len(prop))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--blob", action="append", required=True)
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--board", default=os.path.join(REPO, "boards", "dji-m2001"))
    ap.add_argument("--write-blocks", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_region_verify.log"))])
    nl = pickle.load(open(a.nl, "rb"))
    mtag = a.model.replace(":", "_").replace("/", "_")
    for blob in a.blob:
        V = Verifier(nl, blob)
        nd = os.path.join(RG, blob, "names", mtag)
        out = {}
        for fn in sorted(os.listdir(nd)) if os.path.isdir(nd) else []:
            if not (fn.endswith(".json") and fn.startswith(blob)):
                continue
            rid = fn[:-5]
            resp = json.load(open(os.path.join(nd, fn)))
            ans = resp.get("answer") or {}
            test = ans.get("predicted_test")
            if isinstance(test, dict):
                test = ";".join(f"{k}={v}" for k, v in test.items())
            best = ("untestable", None, "no answer")
            for t in [x for x in str(test or "").split(";") if x.strip()] or [None]:
                v = V.check(rid, t)
                if v[0] == "pass" or best[0] != "pass" and v[0] == "fail" or best[2] == "no answer":
                    best = v
                if v[0] == "pass":
                    break
            out[rid] = dict(name=ans.get("name"), confidence=ans.get("confidence"), test=test, verdict=best[0], test_key=best[1],
                            detail=best[2], model=a.model, discriminating=best[1] in DISCRIMINATING,
                            name_consistent=name_consistent(ans.get("name"), best))
        json.dump(out, open(os.path.join(RG, blob, f"verify_{mtag}.json"), "w"), indent=1)
        c = collections.Counter(r["verdict"] for r in out.values())
        cd = sum(1 for r in out.values() if r["verdict"] == "pass" and r["discriminating"])
        log.info("%s %s: %d named; %s; discriminating pass %d", blob, a.model, len(out), dict(c), cd)
        for rid, r in out.items():
            if r["verdict"] == "pass":
                log.info("  PASS %s %s [%s] %s", rid, r["name"], r["test_key"], r["detail"][:160])
        if a.write_blocks:
            write_blocks(a.board, out, V)


if __name__ == "__main__":
    main()
