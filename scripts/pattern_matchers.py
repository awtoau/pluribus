#!/usr/bin/env python3.15t
"""Pattern matchers: propose candidate laws from evidence, predict, verify. Output = EXPECTATIONS, never claims.

Interface (every matcher):
  propose(evidence_set) -> [Candidate]     candidate patterns with an explicit scope
  predict(candidate, subject) -> dict      the expected value for one subject inside the scope
  verify(candidate, subject, observed) -> "confirmed" | "refuted" | "unobserved"

Deterministic matchers: BitLinearLaw (index -> address, linear in the index bits), PerColumnOffset
(coordinate map, per-column anchors), TileClassTranslate ((frame, v) offsets shared by >= 2 tiles of a
class). Statistical matchers are a SEPARATE base class (StatisticalMatcher); their expectations carry
the vote as confidence and can never reach a claim without a specimen.

register_expectations(conn, matcher, candidates, family, device, commit) writes expectations rows with
the matcher id + version; a pattern row is created per candidate (status open) so blast radius works.
Retired learner code (cycloneiv_route_learn / asm_tables / route_score / li_map / phys_trace, #142) was
reviewed for this interface only; nothing is imported from it.

  python3.15t scripts/pattern_matchers.py demo-m9k      # fit the x1 law from the M9K evidence rows in the DB, hold out, verify
Log: tmp/logs/pattern_matchers.log
"""
import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import and_, insert, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import evidence_io as E     # noqa: E402
from provenance import feedback as F        # noqa: E402
from provenance import tiers as T           # noqa: E402

log = logging.getLogger("pattern_matchers")


@dataclasses.dataclass
class Candidate:
    kind: str                 # bit-linear | per-column-offset | tile-translate | vote
    law: dict                 # parameters as data (JSON-able)
    scope: dict               # {space, kind, definition} where it applies
    subject: str              # subject_key template, e.g. "M9K:init:w1"
    parents: list             # evidence ids the law was fitted on
    fit: dict                 # {hits, total} on the training set
    predictions: dict = dataclasses.field(default_factory=dict)   # subject -> expected (filled by propose for the held-out set)

    @property
    def confidence(self):
        return self.fit["hits"] / self.fit["total"] if self.fit.get("total") else 0.0


class Matcher:
    id = "base-v0"
    kind = "deterministic"
    version = 0
    code_ref = "pattern_matchers:Matcher"

    def propose(self, evidence_set):
        raise NotImplementedError

    def predict(self, cand, subject):
        raise NotImplementedError

    def verify(self, cand, subject, observed):
        p = self.predict(cand, subject)
        if p is None:
            return "unobserved"
        return "confirmed" if p == observed else "refuted"


class StatisticalMatcher(Matcher):
    """Votes / fits over many builds. Expectations only; confidence = vote share; never a source."""
    kind = "statistical"


# ── BitLinearLaw: address = c0 + sum c_i * bit_i(index) (exact integer fit) ──────────────────

class BitLinearLaw(Matcher):
    """index -> (frame, v): each coordinate linear in the bits of the index. Covers the M9K x1 law:
    frame = 1111 + (w>>5); v = 2805 - 2*(w&15) - 2*((w>>3)&1) - ((w>>4)&1)  (all terms are bit-linear)."""
    id = "affine-v1"
    version = 1
    code_ref = "pattern_matchers:BitLinearLaw"

    def __init__(self, nbits=14):
        self.nbits = nbits

    def _design(self, idx):
        idx = np.asarray(idx, np.int64)
        return np.column_stack([np.ones(len(idx))] + [(idx >> b) & 1 for b in range(self.nbits)]).astype(np.float64)

    def fit(self, idx, coord):
        A = self._design(idx)
        c, *_ = np.linalg.lstsq(A, np.asarray(coord, np.float64), rcond=None)
        c = np.rint(c).astype(np.int64)
        hits = int((A @ c == np.asarray(coord)).sum())
        return c, hits

    def propose(self, evidence_set):
        """evidence_set: {"subject": str, "index_to_cell": {index: [frame, v]}, "parents": [evidence ids], "scope": {...}}."""
        m = evidence_set["index_to_cell"]
        idx = np.array(sorted(int(k) for k in m), np.int64)
        fr = np.array([m[str(i)][0] if str(i) in m else m[i][0] for i in idx])
        vv = np.array([m[str(i)][1] if str(i) in m else m[i][1] for i in idx])
        cf, hf = self.fit(idx, fr)
        cv, hv = self.fit(idx, vv)
        hits = int(((self._design(idx) @ cf == fr) & (self._design(idx) @ cv == vv)).sum())
        law = {"type": "bit-linear", "nbits": self.nbits, "frame": cf.tolist(), "v": cv.tolist(),
               "text": self.describe(cf, "frame") + "; " + self.describe(cv, "v"), "dims": 1}
        return [Candidate("bit-linear", law, evidence_set["scope"], evidence_set["subject"], evidence_set["parents"],
                          {"hits": hits, "total": int(len(idx))})]

    @staticmethod
    def describe(c, name):
        terms = [f"{int(c[0])}"] + [f"{'+' if int(k) > 0 else '-'}{abs(int(k))}*b{b}" for b, k in enumerate(c[1:]) if int(k)]
        return f"{name} = " + " ".join(terms)

    def predict(self, cand, subject):
        """subject: the index (int) -> [frame, v]."""
        i = int(subject)
        A = self._design([i])[0]
        return [int(A @ np.asarray(cand.law["frame"])), int(A @ np.asarray(cand.law["v"]))]


# ── PerColumnOffset: coordinate map a(x) = b(x) + off(x), per column, anchors measured ────────

class PerColumnOffset(Matcher):
    """coord-map between two frame axes: offset per column from anchors; columns without an anchor get the
    nearest anchored column's offset on the same side of any non-LAB column (the '+1 after each M9K/DSP
    pair' rule is a prediction here, never a source)."""
    id = "per-column-offset-v1"
    version = 1
    code_ref = "pattern_matchers:PerColumnOffset"

    def propose(self, evidence_set):
        """evidence_set: {"anchors": {x: offset}, "columns": [x...], "col_kind": {x: kind}, "parents": [...], "subject": str, "scope": {...}}."""
        anchors = {int(k): int(v) for k, v in evidence_set["anchors"].items()}
        kinds = {int(k): v for k, v in evidence_set["col_kind"].items()}
        law = {"type": "per-column-offset", "anchors": anchors, "dims": 1,
               "rule": "offset of the nearest anchored column with no non-LAB column in between"}
        return [Candidate("per-column-offset", law, evidence_set["scope"], evidence_set["subject"], evidence_set["parents"],
                          {"hits": len(anchors), "total": len(anchors)}, predictions={
                              str(x): self._predict(x, anchors, kinds) for x in evidence_set["columns"] if x not in anchors})]

    @staticmethod
    def _predict(x, anchors, kinds):
        if kinds.get(x, "LAB") != "LAB":
            return None          # a non-LAB column is its own class; no prediction
        best = None
        for ax, off in anchors.items():
            lo, hi = sorted((ax, x))
            if any(kinds.get(c, "LAB") != "LAB" for c in range(lo + 1, hi)):
                continue
            d = abs(ax - x)
            if best is None or d < best[0]:
                best = (d, off)
        return None if best is None else best[1]

    def predict(self, cand, subject):
        x = int(subject)
        anchors = {int(k): v for k, v in cand.law["anchors"].items()}   # keys are strings after a JSON round trip
        if x in anchors:
            return anchors[x]
        return cand.predictions.get(str(x))


# ── TileClassTranslate: (frame, v) offsets shared by >= 2 tiles of a class ───────────────────

class TileClassTranslate(Matcher):
    """Per-tile measured relative bits agree at >= min_positions tiles -> class-wide expectation at every
    other tile of the class (edge rows / adjacent columns excluded: they are their own classes)."""
    id = "tile-translate-v1"
    version = 1
    code_ref = "pattern_matchers:TileClassTranslate"

    def __init__(self, min_positions=2):
        self.min_positions = min_positions

    def propose(self, evidence_set):
        """evidence_set: {"tiles": {(x, y): {pair_key: [[df, dv], ...]}}, "parents": {(x,y): [evidence ids]}, "class_scope": {...}, "subject": fmt}."""
        tiles = evidence_set["tiles"]
        if len(tiles) < self.min_positions:
            return []
        keys = set.intersection(*(set(t) for t in tiles.values()))
        out = []
        ref_tile = sorted(tiles)[0]
        for k in sorted(keys):
            offs = [tuple(map(tuple, tiles[t][k])) for t in tiles]
            agree = sum(1 for o in offs if o == offs[0])
            if agree < self.min_positions:
                continue
            law = {"type": "tile-translate", "frame": "FX[x] + rel", "v": "vy0 + vpitch*y + rel", "dims": 2,
                   "rel": [list(o) for o in offs[0]], "agree": agree, "positions": len(offs), "reference_tile": list(ref_tile)}
            sc = dict(evidence_set["class_scope"])
            sc["definition"] = dict(sc["definition"], offsets=[list(o) for o in offs[0]])
            out.append(Candidate("tile-translate", law, sc, evidence_set["subject"].format(key=k),
                                 [e for t in tiles for e in evidence_set["parents"].get(t, [])],
                                 {"hits": agree, "total": len(offs)}))
        return out

    def predict(self, cand, subject):
        """subject: (x, y, geom) -> sorted flat bit indices."""
        x, y, geom = subject
        nv = geom["bits_per_frame"]
        fx, vy = geom["FX"][str(x)], geom["vy0"] + geom["vpitch"] * y
        return sorted((fx + df) * nv + vy + dv for df, dv in cand.law["rel"])

    def verify(self, cand, subject, observed):
        p = self.predict(cand, subject)
        return "confirmed" if sorted(int(b) for b in observed) == p else "refuted"


# ── VoteMatcher (statistical): majority over designs, confidence = share ─────────────────────

class VoteMatcher(StatisticalMatcher):
    id = "vote-v1"
    version = 1
    code_ref = "pattern_matchers:VoteMatcher"

    def propose(self, evidence_set):
        """evidence_set: {"votes": {subject: {value_json: count}}, "parents": [...], "scope": {...}}."""
        out = []
        for subj, counts in evidence_set["votes"].items():
            total = sum(counts.values())
            best, n = max(counts.items(), key=lambda kv: kv[1])
            out.append(Candidate("vote", {"type": "vote", "value": json.loads(best), "votes": n, "total": total, "dims": 0},
                                 evidence_set["scope"], subj, evidence_set["parents"], {"hits": n, "total": total}))
        return out

    def predict(self, cand, subject):
        return cand.law["value"]


MATCHERS = {m.id: m for m in (BitLinearLaw(), PerColumnOffset(), TileClassTranslate(), VoteMatcher())}


# ── registration: expectations only ─────────────────────────────────────────────────────────

def register_expectations(conn, matcher, candidates, family, device, commit, pattern_prefix=None, checked_by=None):
    """Write one claim_patterns row (status open) + one expectations row per candidate. Never a claim."""
    from provenance import scopes as SC
    T.check(matcher.kind, T.MATCHER_KINDS, "matcher kind")
    if conn.execute(select(S.matchers.c.id).where(S.matchers.c.id == matcher.id)).fetchone() is None:
        conn.execute(insert(S.matchers).values(id=matcher.id, kind=matcher.kind, name=matcher.__class__.__name__,
                                               version=matcher.version, code_ref=matcher.code_ref, created_commit=commit))
    ids = []
    for i, c in enumerate(candidates):
        pid = f"{pattern_prefix or c.kind}-{c.subject.replace(':', '_').replace('*', 'x')}-v{matcher.version}"
        if conn.execute(select(S.claim_patterns.c.id).where(S.claim_patterns.c.id == pid)).fetchone() is None:
            conn.execute(insert(S.claim_patterns).values(
                id=pid, family=family, device=device, matcher_id=matcher.id, space=c.scope["space"],
                description=f"{c.kind} law for {c.subject} ({matcher.id})", law=dict(c.law, checked_by=checked_by),
                status="open", created_commit=commit, updated_at=F.now()))
            for ev in dict.fromkeys(c.parents):
                conn.execute(insert(S.pattern_evidence).values(pattern_id=pid, evidence_id=ev, role="parent"))
            F.event(conn, "created", commit, pattern_id=pid, detail={"matcher": matcher.id, "fit": c.fit})
        key = SC.canonical(c.scope["space"], c.scope["kind"], c.scope["definition"])
        sid = conn.execute(select(S.scopes.c.id).where(and_(S.scopes.c.family == family, S.scopes.c.device == device,
                                                            S.scopes.c.scope_key == key))).fetchone()
        if sid is None:
            n = c.scope.get("n_objects") or (SC.count(c.scope["kind"], c.scope["definition"]) if c.scope["kind"] in ("formula", "all", "keys", "cells") else 0)
            sid = [conn.execute(insert(S.scopes).values(family=family, device=device, space=c.scope["space"], kind=c.scope["kind"],
                                                        definition=c.scope["definition"], scope_key=key, n_objects=int(n))).inserted_primary_key[0]]
        dup = conn.execute(select(S.expectations.c.id).where(and_(
            S.expectations.c.family == family, S.expectations.c.device == device, S.expectations.c.space == c.scope["space"],
            S.expectations.c.subject_key == c.subject, S.expectations.c.scope_id == sid[0], S.expectations.c.matcher_id == matcher.id))).fetchone()
        if dup:
            ids.append(dup[0])
            continue
        eid = conn.execute(insert(S.expectations).values(
            family=family, device=device, space=c.scope["space"], subject_key=c.subject, scope_id=sid[0], matcher_id=matcher.id,
            pattern_id=pid, expected={"law": c.law, "predictions": c.predictions}, confidence=c.confidence,
            confidence_basis=f"fit {c.fit['hits']}/{c.fit['total']} on parents; {matcher.kind} matcher {matcher.id}",
            supporting_evidence=list(dict.fromkeys(c.parents)), status="open",
            n_objects=int(c.scope.get("n_objects") or 0), created_commit=commit, updated_at=F.now())).inserted_primary_key[0]
        F.event(conn, "predicted", commit, expectation_id=eid, pattern_id=pid, detail={"matcher": matcher.id})
        ids.append(eid)
    return ids


def verify_all(matcher, cand, held_out):
    """held_out: {subject: observed}. -> {"confirmed": n, "refuted": n, "unobserved": n, "refutations": [subjects]}"""
    out = {"confirmed": 0, "refuted": 0, "unobserved": 0, "refutations": []}
    for subj, obs in held_out.items():
        v = matcher.verify(cand, subj, obs)
        out[v] += 1
        if v == "refuted":
            out["refutations"].append(subj)
    return out


# ── demo: M9K x1 law from the DB's evidence rows ───────────────────────────────────────────

def m9k_index_map_from_evidence(conn, family, device, width):
    """bincode<w>d pairs -> {index: [frame, v]}: bit k of the index is set in specimen k's diff."""
    rows = conn.execute(select(S.evidence.c.name, S.evidence.c.bits_spec, S.evidence.c.result).where(and_(
        S.evidence.c.family == family, S.evidence.c.device == device, S.evidence.c.kind == "specimen-pair",
        S.evidence.c.source_ref.like(f"%m9k_bincode{width}d.json")))).fetchall()
    if not rows:
        return None, []
    nv = rows[0][2]["bits_per_frame"]
    bitsets = {}
    for name, blob, _r in rows:
        k = int(name.rsplit("_k", 1)[1])
        bitsets[k] = set(E.unpack(blob).tolist())
    cells = set.union(*bitsets.values())
    out = {}
    for c in cells:
        idx = sum(1 << k for k, s in bitsets.items() if c in s)
        out[str(idx)] = [int(c // nv), int(c % nv)]
    return out, [name for name, _, _ in rows]


def demo_m9k(args):
    S.init()
    with db.engine().connect() as conn:
        m, names = m9k_index_map_from_evidence(conn, "cycloneiv", "EP4CGX150", 1)
        if m is None:
            db.die("no M9K bincode evidence rows in this DB (run claims_register.py --family cycloneiv)")
        ev_ids = [r[0] for r in conn.execute(select(S.evidence.c.id).where(S.evidence.c.name.in_(names)))]
    idx = sorted(int(k) for k in m)
    rng = np.random.default_rng(1)
    hold = set(rng.choice(idx, size=max(1, len(idx) // 5), replace=False).tolist())
    train = {str(i): m[str(i)] for i in idx if i not in hold}
    mt = BitLinearLaw()
    cands = mt.propose({"subject": "M9K:init:w1", "index_to_cell": train, "parents": ev_ids,
                        "scope": {"space": "cell-param", "kind": "keys", "definition": {"keys": ["M9K:init:w1"]}}})
    c = cands[0]
    res = verify_all(mt, c, {i: m[str(i)] for i in hold})
    log.info("law: %s", c.law["text"])
    log.info("train fit %s; held-out %d: %s", c.fit, len(hold), {k: v for k, v in res.items() if k != "refutations"})
    print(json.dumps({"law": c.law["text"], "fit": c.fit, "held_out": res}, indent=1))
    return 0 if res["refuted"] == 0 else 1


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/pattern_matchers.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["demo-m9k"])
    a = ap.parse_args()
    return demo_m9k(a)


if __name__ == "__main__":
    sys.exit(main())
