#!/usr/bin/env python3.15t
"""Rebuild the DERIVED provenance tables of ONE family from its evidence rows + artefacts (docs/provenance-schema.md).

  python3.15t scripts/claims_register.py --family cycloneiv [--device EP4CGX150]
  python3.15t scripts/claims_register.py --family cycloneiv --import-json DIR [--verify-json]   # one-shot legacy migration
  python3.15t scripts/claims_register.py --family ecp5 | machxo2 | gowin | cyclonev

Evidence rows are PRIMARY data (written by the specimen tools through provenance.evidence_io) and are
never wiped. Everything else (scopes' claims, patterns, expectations, unknowns, conflicts, events,
corpus, ledger) is derived and rebuilt from scratch every run. One database per family
(PLURIBUS_SQLITE_PATH); the script dies if the file holds another family.
--import-json DIR: migrate legacy pair JSONs (and derived map/table JSONs, verbatim) into evidence rows.
--verify-json: round-trip check (pair count + canonical hash) of every JSON in DIR against the rows.
Log: tmp/logs/claims_register.log
"""
import argparse
import ast
import datetime
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import and_, delete, insert, select, update

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import corpus as C          # noqa: E402
from provenance import evidence_io as E     # noqa: E402
from provenance import feedback as F        # noqa: E402
from provenance import queries as Q         # noqa: E402
from provenance import scopes as SC         # noqa: E402
from provenance import tiers as T           # noqa: E402

log = logging.getLogger("claims_register")

FAMILIES = T.FAMILIES
SPACES = {
    "bit": "flat index frame*bits_per_frame+v; subject_key names the meaning, e.g. LOCAL_LINE:src0:snk2:DATAD",
    "tile-bit": "<tile_type>:<frame>:<bit> (Lattice/Gowin tile databases)",
    "pip": "<sink_wire><-<source_wire> within a tile",
    "mux-input": "<class>|<block key>|<group select> -> driver record / wire",
    "cell-param": "<cell kind>:<param>[:<index>] e.g. M9K:init:w1:17",
    "coord-map": "<from>-><to>:<column> e.g. asm->plane:x37",
    "stream-option": "header:<bit>",
    "port-map": "<block>:<port> -> wire",
    "net-attr": "<net>:<attr>",
}
# Derived tables, wiped every run. NOT evidence / evidence_scopes / scopes (evidence is primary; scopes are
# keyed canonically and reused).
DERIVED_TABLES = (S.coverage_ledger, S.gate_results, S.gate_runs, S.done_criteria, S.corpus_members,
                  S.lift_provenance, S.audits, S.unknowns, S.expectations, S.claim_conflicts,
                  S.claim_events, S.claim_evidence, S.claims, S.pattern_evidence, S.claim_patterns,
                  S.matchers, S.address_spaces, S.devices)
EV_DIR = REPO / "evidence" / "cycloneiv"
NV = 6368
DK_LUT = None   # filled from cycloneiv_le_locate when available


def git_head():
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def now():
    return datetime.datetime.now().astimezone()


class Reg:
    """Thin writer: scope cache, claim/expectation/unknown inserts with vocabulary checks."""

    def __init__(self, conn, family, device, commit, geom=None):
        self.conn, self.family, self.device, self.commit, self.geom = conn, family, device, commit, geom
        self._scopes = {}

    def scope(self, space, kind, definition, label=None, parent=None, n=None):
        key = SC.canonical(space, kind, definition)
        if key in self._scopes:
            return self._scopes[key]
        row = self.conn.execute(select(S.scopes.c.id).where(and_(
            S.scopes.c.family == self.family, S.scopes.c.device == self.device, S.scopes.c.scope_key == key))).fetchone()
        if row:
            self._scopes[key] = row[0]
            return row[0]
        if n is None:
            n = SC.count(kind, definition, self.geom) if kind not in ("formula", "all") else SC.count(kind, definition)
        sid = self.conn.execute(insert(S.scopes).values(
            family=self.family, device=self.device, space=space, kind=kind, definition=definition,
            scope_key=key, n_objects=int(n), parent=parent, label=label)).inserted_primary_key[0]
        self._scopes[key] = sid
        return sid

    def matcher(self, mid, kind, name, version, code_ref, parameters=None, training=None):
        T.check(kind, T.MATCHER_KINDS, "matcher kind")
        self.conn.execute(insert(S.matchers).values(
            id=mid, kind=kind, name=name, version=version, code_ref=code_ref, parameters=parameters,
            training_evidence=training, created_commit=self.commit))
        return mid

    def pattern(self, pid, space, description, law, matcher_id=None, scope_id=None, parents=(), status="open"):
        T.check(status, T.STATUSES, "status")
        self.conn.execute(insert(S.claim_patterns).values(
            id=pid, family=self.family, device=self.device, matcher_id=matcher_id, space=space,
            description=description, law=law, scope_id=scope_id, status=status, created_commit=self.commit,
            updated_at=now()))
        for ev in parents:
            self.conn.execute(insert(S.pattern_evidence).values(pattern_id=pid, evidence_id=ev, role="parent"))
        F.event(self.conn, "created", self.commit, pattern_id=pid, detail={"parents": len(parents)})
        return pid

    def claim(self, space, subject, scope_id, meaning, tier, status="open", pattern=None, evidence=(),
              n=None, cls=None, basis=None, confirmations=0):
        T.check(tier, T.TIERS, "tier")
        T.check(status, T.STATUSES, "status")
        T.check(space, T.SPACES, "space")
        if n is None:
            n = self.conn.execute(select(S.scopes.c.n_objects).where(S.scopes.c.id == scope_id)).fetchone()[0]
        dup = self.conn.execute(select(S.claims.c.id, S.claims.c.confirmations).where(and_(
            S.claims.c.family == self.family, S.claims.c.device == self.device, S.claims.c.space == space,
            S.claims.c.subject_key == subject, S.claims.c.scope_id == scope_id))).fetchone()
        if dup:   # same subject, same scope, measured again: a confirmation, never a second claim
            for ev in evidence:
                self.conn.execute(insert(S.claim_evidence).values(claim_id=dup[0], evidence_id=ev, role="confirm"))
                F.event(self.conn, "confirmed", self.commit, claim_id=dup[0], evidence_id=ev, detail={"scope_id": scope_id})
            self.conn.execute(update(S.claims).where(S.claims.c.id == dup[0]).values(
                confirmations=dup[1] + len(evidence), updated_at=now()))
            return dup[0]
        cid = self.conn.execute(insert(S.claims).values(
            family=self.family, device=self.device, space=space, subject_key=subject, scope_id=scope_id,
            meaning=meaning, tier=tier, status=status, pattern_id=pattern, n_objects=int(n),
            inventory_class=cls, confidence_basis=basis, confirmations=confirmations,
            created_commit=self.commit, updated_at=now())).inserted_primary_key[0]
        for ev in evidence:
            self.conn.execute(insert(S.claim_evidence).values(claim_id=cid, evidence_id=ev, role="direct"))
        F.event(self.conn, "created", self.commit, claim_id=cid, pattern_id=pattern,
                evidence_id=evidence[0] if evidence else None)
        return cid

    def expect(self, space, subject, scope_id, matcher_id, expected, pattern=None, confidence=None, basis=None,
               support=(), n=None):
        T.check(space, T.SPACES, "space")
        if n is None:
            n = self.conn.execute(select(S.scopes.c.n_objects).where(S.scopes.c.id == scope_id)).fetchone()[0]
        eid = self.conn.execute(insert(S.expectations).values(
            family=self.family, device=self.device, space=space, subject_key=subject, scope_id=scope_id,
            matcher_id=matcher_id, pattern_id=pattern, expected=expected, confidence=confidence,
            confidence_basis=basis, supporting_evidence=list(support), status="open", n_objects=int(n),
            created_commit=self.commit, updated_at=now())).inserted_primary_key[0]
        F.event(self.conn, "predicted", self.commit, expectation_id=eid, pattern_id=pattern)
        return eid

    def unknown(self, space, scope_id, reason, subject=None, n=None, cls=None, note=None, absence=None):
        T.check(reason, T.UNKNOWN_REASONS, "unknown reason")
        if n is None:
            n = self.conn.execute(select(S.scopes.c.n_objects).where(S.scopes.c.id == scope_id)).fetchone()[0]
        return self.conn.execute(insert(S.unknowns).values(
            family=self.family, device=self.device, space=space, subject_key=subject, scope_id=scope_id,
            reason=reason, status="open", absence_evidence=absence, inventory_class=cls, n_objects=int(n),
            note=note, created_commit=self.commit, updated_at=now())).inserted_primary_key[0]


# ── common ───────────────────────────────────────────────────────────────────

def wipe(conn, family):
    """Always-rebuild of the DERIVED tables. One family per database (check_single_family), so tables
    without a family column (matchers, link tables, claim_events) are emptied outright. Evidence stays."""
    for t in DERIVED_TABLES:
        if "family" in t.c:
            conn.execute(delete(t).where(t.c.family == family))
        else:
            conn.execute(delete(t))
    # families row stays: evidence / scopes reference it


def check_single_family(conn, family):
    others = [r[0] for r in conn.execute(select(S.families.c.id)) if r[0] != family]
    if others:
        db.die(f"this database already holds family {others}; one database per family "
               f"(databases/README.md) — point PLURIBUS_SQLITE_PATH at the {family} file")


def ensure_family(conn, family):
    f = FAMILIES[family]
    if conn.execute(select(S.families.c.id).where(S.families.c.id == family)).fetchone():
        conn.execute(update(S.families).where(S.families.c.id == family).values(**f))
    else:
        conn.execute(insert(S.families).values(id=family, **f))
    for sp, g in SPACES.items():
        conn.execute(insert(S.address_spaces).values(family=family, space=sp, key_grammar=g))


def ledger_from_claims(conn, family, device, commit):
    cov = Q.coverage(conn, family, device)
    rows = [dict(family=family, device=device, commit=commit, ts=now(), inventory_class=k[0], tier=k[1],
                 status=k[2], n_objects=n, denominator="die_bits", source="claims") for k, n in cov.items()]
    if rows:
        conn.execute(insert(S.coverage_ledger), rows)
    return rows


# ── Cyclone IV ───────────────────────────────────────────────────────────────

def _geom(device):
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(device))
    return dict(bits_per_frame=NV, frames=None, FX={str(k): v for k, v in g.FX.items()},
                col_kind={str(k): v for k, v in g.kind.items()}, vy0=g.vy0, vpitch=g.vpitch, ymax=g.ymax,
                DN={str(k): v for k, v in g.DN.items()}, xmax=max(g.FX))


def _ledger_class(cid):
    led = _ledger_latest()
    return next((c for c in led["classes"] if c["id"] == cid), None) if led else None


def _ledger_latest():
    p = REPO / "docs" / "coverage-history.jsonl"
    if not p.exists():
        return None
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    return max(rows, key=lambda r: r["ts"]) if rows else None


def _adjacent_columns(geom):
    """LAB columns next to a non-LAB column (M9K/MUL/IO): outside the interior pattern scope."""
    kinds = {int(k): v for k, v in geom["col_kind"].items()}
    xs = sorted(kinds)
    adj = set()
    for x in xs:
        if kinds[x] != "LAB":
            continue
        for nb in (x - 1, x + 1):
            if nb not in kinds or kinds[nb] != "LAB":
                adj.add(x)
    return sorted(adj)


def import_json_dir(conn, device, commit, json_dir):
    """One-shot legacy migration: pair JSONs -> specimen-pair rows; map / table JSONs -> derived-table rows (verbatim)."""
    migrated = {}
    for p in sorted(Path(json_dir).glob("*.json")):
        gen = "scripts/cycloneiv_m9k.py" if "_m9k_" in p.name else "scripts/cycloneiv_forced.py"
        rel = os.path.relpath(p, REPO)
        r = E.import_json_file(conn, str(p), "cycloneiv", device, NV, commit, gen, str(REPO))
        if r is None:
            d = json.loads(p.read_text())
            E.record_decode(conn, "cycloneiv", device, p.name, {"file": d}, commit, rel, generator=gen,
                            kind="derived-table", n_objects=len(d.get("cells", d)))
            log.info("evidence %-42s derived table stored verbatim", p.name)
            continue
        migrated[p.name] = r
        log.info("evidence %-42s %4d pairs  json %s  db %s  %s", p.name, r[0], r[1][:10], r[2][:10],
                 "OK" if r[1] == r[2] else "MISMATCH")
    return migrated


def register_cycloneiv(conn, device, commit):
    geom = _geom(device)
    sha_geom = hashlib.sha256((REPO / "lifters/data/cycloneiv_ep4cgx150_geom.json").read_bytes()).hexdigest()
    conn.execute(insert(S.devices).values(
        family="cycloneiv", name=device, die="ep4cgx150", packages=None, die_bits=39425016, geometry=geom,
        source_ref=f"lifters/data/cycloneiv_ep4cgx150_geom.json sha256:{sha_geom[:12]}"))
    R = Reg(conn, "cycloneiv", device, commit, geom)
    conn.execute(update(S.address_spaces).where(and_(S.address_spaces.c.family == "cycloneiv",
                                                     S.address_spaces.c.space == "bit")).values(n_objects=39425016))

    # matchers (the laws are data; code refs point at scripts/pattern_matchers.py)
    R.matcher("class-generalise-v1", "deterministic", "class-wide generalisation from >=2 agreeing positions", 1,
              "pattern_matchers:TileClassTranslate", {"min_positions": 2})
    R.matcher("affine-v1", "deterministic", "affine address law fitted on measured parents", 1,
              "pattern_matchers:AffineLaw")
    R.matcher("tile-translate-v1", "deterministic", "tile-class translation by (frame, v) offset", 1,
              "pattern_matchers:TileClassTranslate")
    R.matcher("vote-v1", "statistical", "voted / learnt over many builds (phys_map, li_map, asm_names)", 1,
              "pattern_matchers:VoteMatcher", {"source": "cycloneiv_phys_trace / cycloneiv_li_map / cycloneiv_asm_tables"})
    R.matcher("vendor-ddb-v1", "deterministic", "routing.ddb / asm.ddb decode (group k == edge k)", 1,
              "cycloneiv_ddb_map", {"rule": "group k == edge k"})
    R.matcher("llm-proposer-v1", "llm-proposed", "Claude-API proposer (candidates only; checked before registration)", 1,
              "pattern_proposer_llm:propose")

    # ── evidence rows (primary data; legacy JSON arrives only through --import-json) ─────────
    maps, tables = {}, {}
    for r in conn.execute(select(S.evidence.c.name, S.evidence.c.result).where(and_(
            S.evidence.c.family == "cycloneiv", S.evidence.c.device == device, S.evidence.c.kind == "derived-table"))):
        d = r[1]["file"]
        (maps if "cells" in d else tables)[r[0]] = d
    n_ev = conn.execute(select(__import__("sqlalchemy").func.count()).select_from(S.evidence).where(and_(
        S.evidence.c.family == "cycloneiv", S.evidence.c.kind == "specimen-pair"))).scalar()
    log.info("cycloneiv: %d specimen-pair evidence rows, %d derived tables in the DB", n_ev, len(maps) + len(tables))
    ev_by_file = {}
    for r in conn.execute(select(S.evidence.c.id, S.evidence.c.name, S.evidence.c.source_ref, S.evidence.c.result,
                                 S.evidence.c.bits_spec, S.evidence.c.bits_base)
                          .where(and_(S.evidence.c.family == "cycloneiv", S.evidence.c.kind == "specimen-pair"))):
        ev_by_file.setdefault(os.path.basename(r[1 + 1]), {})[r[1]] = dict(id=r[0], result=r[3], spec=r[4], base=r[5])

    # ── LOCAL_LINE: 4 LABs measured; ll-translate-v1; expectations interior; unknowns edges ──
    labs = {"cycloneiv_forced_lab.json": (10, 10), "cycloneiv_forced_lab_58x30.json": (58, 30),
            "cycloneiv_forced_lab_37x60.json": (37, 60), "cycloneiv_forced_lab_100x75.json": (100, 75)}
    rel_by_lab, lab_ev = {}, {}
    for fn, (lx, ly) in labs.items():
        rows = ev_by_file.get(fn, {})
        if not rows:
            continue
        fx, vy = geom["FX"][str(lx)], geom["vy0"] + geom["vpitch"] * ly
        rel = {}
        for name, r in rows.items():
            m = r["result"]["meta"]
            on = E.unpack(r["spec"])
            offs = sorted(set((int(b // NV - fx), int(b % NV - vy)) for b in on.tolist()))
            key = (m["src"], m["snk"], m["hop"][4] if m.get("hop") else None)
            rel[key] = (offs, r["id"], m)
        rel_by_lab[(lx, ly)] = rel
        lab_ev[(lx, ly)] = [r["id"] for r in rows.values()]
        for (src, snk, port), (offs, evid, m) in rel.items():
            sid = R.scope("bit", "tile", {"x": lx, "y": ly, "offsets": offs}, label=f"LAB X{lx}Y{ly} LOCAL_LINE {src}->{snk}")
            R.claim("bit", f"LOCAL_LINE:src{src}:snk{snk}:{port}", sid, {"bits_rel": offs, "hop": m.get("hop"),
                    "set_iff": "this hop is routed"}, "measured", "confirmed", evidence=[evid], cls="3",
                    basis="raw diff, base vs specimen, one hop", confirmations=1)
    if (10, 10) in rel_by_lab:
        parent = rel_by_lab[(10, 10)]
        agree = {lab: sum(1 for k in parent if k in rel and rel[k][0] == parent[k][0]) for lab, rel in rel_by_lab.items()}
        adj = _adjacent_columns(geom)
        interior = {"col_kind": "LAB", "y_range": [2, geom["ymax"] - 2], "x_not": adj, "count_only": True}
        edge_rows = {"col_kind": "LAB", "y_in": [1, geom["ymax"] - 1], "count_only": True}
        edge_cols = {"col_kind": "LAB", "x_in": adj, "count_only": True}
        universe = sorted({o for offs, _, _ in parent.values() for o in offs})
        pid = R.pattern("ll-translate-v1", "bit", "LOCAL_LINE sink-mux bits translate by (FX[x], vy0+vpitch*y) to every LAB",
                        {"frame": "FX[x] + rel", "v": "vy0 + vpitch*y + rel", "dims": 2,
                         "agreement": {f"X{x}Y{y}": n for (x, y), n in agree.items()}, "pairs": len(parent)},
                        matcher_id="tile-translate-v1",
                        scope_id=R.scope("bit", "tile-class", dict(interior, offsets=universe), label="interior LABs"),
                        parents=[e for lab in lab_ev for e in lab_ev[lab]],
                        status="confirmed")
        for (src, snk, port), (offs, evid, m) in parent.items():
            sid = R.scope("bit", "tile-class", dict(interior, offsets=offs), label=f"interior LABs LOCAL_LINE {src}->{snk}")
            R.expect("bit", f"LOCAL_LINE:src{src}:snk{snk}:{port}", sid, "tile-translate-v1",
                     {"bits_rel": offs}, pattern=pid, confidence=min(agree.values()) / len(parent),
                     basis=f"identical at {len(rel_by_lab)} LABs ({agree})", support=[evid])
        # confirmations: the 3 held-out LABs agree with X10Y10 -> pattern confirmations
        conn.execute(update(S.claim_patterns).where(S.claim_patterns.c.id == pid).values(
            confirmations=sum(1 for lab in rel_by_lab if lab != (10, 10))))
        R.unknown("bit", R.scope("bit", "tile-class", dict(edge_rows, offsets=universe), label="LAB edge rows y1/y90"),
                  "unasked", subject="LOCAL_LINE:*", cls="3", note="outside ll-translate-v1 parent scope (edge rule)")
        R.unknown("bit", R.scope("bit", "tile-class", dict(edge_cols, offsets=universe), label="LAB columns adjacent to M9K/MUL/IO"),
                  "unasked", subject="LOCAL_LINE:*", cls="3", note="outside ll-translate-v1 parent scope (column anomaly)")

    tab = tables.get("cycloneiv_forced_lab_table.json")
    if tab and (10, 10) in rel_by_lab:
        # derived role table of the X10Y10 grid (C/D/P/Q bit roles per pair): kept verbatim as a claim meaning
        sid = R.scope("bit", "tile", {"x": 10, "y": 10, "offsets": sorted({o for offs, _, _ in rel_by_lab[(10, 10)].values() for o in offs})},
                      label="LAB X10Y10 LOCAL_LINE role table")
        R.claim("bit", "LOCAL_LINE:role-table", sid, {"table": tab, "derived_from": "cycloneiv_forced_lab.json"}, "measured", "confirmed",
                evidence=lab_ev.get((10, 10), [])[:1], cls="3", basis="bit roles C/D/P/Q over the 240-pair grid", confirmations=1)

    # ── other forced files (tier 0/1, gxnb neighbour grids): measured, cells scope ───────────
    for fn, rows in ev_by_file.items():
        if fn in labs:
            continue
        subject_root = "tier" if "tier" in fn else "LE_BUFFER->LI"
        for name, r in rows.items():
            on = E.unpack(r["spec"]).tolist()
            if not on:
                continue
            m = r["result"]["meta"]
            sid = R.scope("bit", "cells", {"flat": on}, label=name)
            R.claim("bit", f"{subject_root}:{name}", sid, {"meta": m, "set_iff": "this hop is routed"},
                    "measured", "confirmed", evidence=[r["id"]], cls="3", basis="raw diff", confirmations=1)

    # ── M9K init maps (one site), x1 law pattern, expectations, unknowns ──────────────────────
    site = {"x": 23, "y": 40, "n": 0, "name": "M9K_X23_Y40_N0"}
    m9k_widths = {}
    for fn, d in maps.items():
        w = int(d["width"])
        cells = {int(k): v for k, v in d["cells"].items()}
        flat = [int(f) * NV + int(v) for f, v in cells.values()]
        ev_ids = [r["id"] for r in ev_by_file.get(f"cycloneiv_m9k_bincode{w}d.json", {}).values()]
        confirms = [r["id"] for g in (f"cycloneiv_m9k_rand{w}d.json", "cycloneiv_m9k_data1d.json" if w == 1 else "")
                    if g for r in ev_by_file.get(g, {}).values()]
        sid = R.scope("cell-param", "cells", {"flat": sorted(flat)}, label=f"{site['name']} init x{w}")
        cid = R.claim("cell-param", f"M9K:init:w{w}", sid,
                      {"site": site, "map": d, "index": "mem_init linear index (generator), not hardware (word,bit)"},
                      "measured", "confirmed", evidence=ev_ids, cls="4b",
                      basis=f"binary-coded init specimens, every cell located, 0 unattributed; {len(confirms)} round-trip confirmations",
                      confirmations=len(confirms))
        for e in confirms:
            conn.execute(insert(S.claim_evidence).values(claim_id=cid, evidence_id=e, role="confirm"))
            F.event(conn, "confirmed", commit, claim_id=cid, evidence_id=e, detail={"scope_id": sid})
        m9k_widths[w] = (cid, cells, ev_ids)
    if 1 in m9k_widths:
        cid, cells, ev_ids = m9k_widths[1]
        law = lambda w: (1111 + (w >> 5), 2805 - 2 * (w & 15) - 2 * ((w >> 3) & 1) - ((w >> 4) & 1))  # noqa: E731
        hits = sum(1 for k, (f, v) in cells.items() if law(k) == (f, v))
        n_m9k_cols = sum(1 for k in geom["col_kind"].values() if k == "M9K")
        other_sites = n_m9k_cols * (geom["ymax"] - 1) - 1
        pid = R.pattern("m9k-init-x1-law-v1", "cell-param",
                        "x1 init cell law fitted from the X23Y40 map: frame = 1111 + (w>>5); v = 2805 - 2*(w&15) - 2*((w>>3)&1) - ((w>>4)&1)",
                        {"frame": "1111 + (w>>5)", "v": "2805 - 2*(w&15) - 2*((w>>3)&1) - ((w>>4)&1)", "dims": 1,
                         "fit_hits": hits, "fit_total": len(cells), "site_anchor": site}, matcher_id="affine-v1",
                        parents=ev_ids, status="open")
        parent_4b = None
        if led4b := _ledger_class("4b"):
            parent_4b = R.scope("bit", "formula", {"matcher": "inventory", "inventory_class": "4b", "n_objects": led4b["die_bits"] - 9216},
                                label=led4b["name"])
        sid = R.scope("cell-param", "formula", {"matcher": "affine-v1", "law": "m9k-init-x1-law-v1",
                                                "sites": "every other M9K site (per-site frame/v anchor unknown)",
                                                "n_objects": other_sites * len(cells)}, label="other M9K sites x1 init", parent=parent_4b)
        R.expect("cell-param", "M9K:init:w1", sid, "affine-v1", {"law": "m9k-init-x1-law-v1", "relative_to_site_anchor": True},
                 pattern=pid, confidence=hits / len(cells), basis=f"law reproduces {hits}/{len(cells)} cells at the one measured site; no second site yet",
                 support=ev_ids)
        same = [w for w in (2, 4, 8) if w in m9k_widths and m9k_widths[w][1] == cells]
        diff = [w for w in (9, 16) if w in m9k_widths and m9k_widths[w][1] != cells]
        log.info("M9K index->cell map identical to x1 at widths %s, different at %s", same, diff)
    for w in (18, 32, 36):
        sid = R.scope("cell-param", "keys", {"keys": [f"M9K:init:w{w}"]}, label=f"M9K init x{w}", n=9216)
        R.unknown("cell-param", sid, "unasked", subject=f"M9K:init:w{w}", cls="4b", note="width not yet specimened")
    sid = R.scope("cell-param", "keys", {"keys": [f"M9K:init:w{w}:hw-word-bit" for w in (2, 4, 8, 9, 16)]},
                  label="M9K hardware (word,bit)->cell, widths > 1", n=5 * 9216)
    R.unknown("cell-param", sid, "unasked", subject="M9K:init:hw-word-bit", cls="4b",
              note="only generator index -> cell proven for widths > 1")

    # ── phys_map / li_map (voted + specimen entries) ──────────────────────────────────────────
    pm_path = REPO / "lifters/data/cycloneiv_ep4cgx150_phys_map.json"
    if pm_path.exists():
        pm = json.loads(pm_path.read_text())
        sha = hashlib.sha256(pm_path.read_bytes()).hexdigest()
        ev_vote = E.record_decode(conn, "cycloneiv", device, "phys_map voted tables", {"designs": len(pm.get("designs", [])),
                                  "stats": pm.get("stats"), "sha256": sha}, commit, "lifters/data/cycloneiv_ep4cgx150_phys_map.json",
                                  generator="scripts/cycloneiv_phys_trace.py", kind="vendor-decode")
        R.pattern("class-generalise-v1", "mux-input", "class-wide entry from 2-3 agreeing specimen positions (phys_map provenance=specimen)",
                  {"min_positions": 2, "dims": 2}, matcher_id="class-generalise-v1", status="confirmed")
        prov = pm.get("provenance", {})
        for table, space_sub in (("wires_tile", "wire"), ("lis_tile", "li")):
            for key, val in pm.get(table, {}).items():
                sid = R.scope("mux-input", "keys", {"keys": [f"{table}:{key}"]}, n=1)
                R.claim("mux-input", f"{space_sub}:{key}", sid, {"value": val, "table": table}, "measured", "open",
                        cls="2a", basis="specimen at one tile (per-tile override)")
        for table, space_sub in (("wires", "wire"), ("lis", "li")):
            for key, val in pm.get(table, {}).items():
                sid = R.scope("mux-input", "keys", {"keys": [f"{table}:{key}"]}, n=1)
                if prov.get(table, {}).get(key) == "specimen":
                    R.claim("mux-input", f"{space_sub}:{key}", sid, {"value": val, "table": table}, "pattern-predicted",
                            "confirmed", pattern="class-generalise-v1", cls="2a", basis=">=2 positions agree, class-wide")
                else:
                    R.claim("mux-input", f"{space_sub}:{key}", sid, {"value": val, "table": table}, "statistical", "open",
                            evidence=[ev_vote], cls="2a", basis=f"vote {val}")
        for key, val in pm.get("defaults", {}).items():
            sid = R.scope("mux-input", "keys", {"keys": [f"defaults:{key}"]}, n=1)
            R.claim("mux-input", f"default:{key}", sid, {"value": val}, "statistical", "open", evidence=[ev_vote], cls="2a",
                    basis="voted default")
        for key, val in pm.get("cells", {}).items():
            sid = R.scope("mux-input", "keys", {"keys": [f"cells:{key}"]}, n=1)
            R.claim("mux-input", f"cell:{key}", sid, {"value": val, "votes": pm.get("cell_votes", {}).get(key)},
                    "statistical", "open", evidence=[ev_vote], cls="2a", basis=f"votes {pm.get('cell_votes', {}).get(key)}")
        unres = pm.get("unresolved", [])
        if unres:
            sid = R.scope("mux-input", "keys", {"keys": [f"unresolved:{u['class']}:{u['key']}" for u in unres]}, n=len(unres))
            R.unknown("mux-input", sid, "unasked", subject="phys_map:unresolved", cls="2b",
                      note=f"{len(unres)} class keys with no resolved driver ({pm.get('stats')})")
    li_path = REPO / "lifters/data/cycloneiv_ep4cgx150_li_map.json"
    if li_path.exists():
        li = json.loads(li_path.read_text())
        ev_li = E.record_decode(conn, "cycloneiv", device, "li_map learnt", {"stats": li.get("stats"), "designs": len(li.get("designs", []))},
                                commit, "lifters/data/cycloneiv_ep4cgx150_li_map.json", generator="scripts/cycloneiv_li_map.py")
        for key, val in li.get("lis", {}).items():
            sid = R.scope("mux-input", "keys", {"keys": [f"li_map:{key}"]}, n=1)
            R.claim("mux-input", f"li:{key}", sid, {"value": val}, "statistical", "open", evidence=[ev_li], cls="2a",
                    basis="li_map resolved")
        amb = int(li.get("stats", {}).get("ambiguous", 0))
        if amb:
            sid = R.scope("mux-input", "formula", {"matcher": "vote-v1", "n_objects": amb, "what": "li_map ambiguous keys"})
            R.unknown("mux-input", sid, "unasked", subject="li_map:ambiguous", cls="2b", note=f"{amb} ambiguous LI keys")

    # ── ddb map: vendor-decoded rule, conflict on the LI band ─────────────────────────────────
    ddb = REPO / "lifters/data/cycloneiv_ep4cgx150_ddb_map.npz"
    if ddb.exists():
        z = np.load(ddb)
        n_blocks = int(len(z["block"]))
        ev_ddb = E.record_decode(conn, "cycloneiv", device, "routing.ddb fan-out decode", {"blocks": n_blocks, "meta": str(z["meta"])[:400]},
                                 commit, "lifters/data/cycloneiv_ep4cgx150_ddb_map.npz", generator="scripts/cycloneiv_ddb_map.py",
                                 n_objects=n_blocks)
        pid = R.pattern("ddb-group-eq-edge-v1", "mux-input", "asm group k == routing.ddb edge k (block -> destination record)",
                        {"rule": "group k == edge k", "dims": 1}, matcher_id="vendor-ddb-v1", parents=[ev_ddb], status="confirmed")
        sid_w = R.scope("mux-input", "formula", {"matcher": "vendor-ddb-v1", "n_objects": n_blocks, "subset": "wire destinations"})
        c_w = R.claim("mux-input", "ddb:block->dest:wires", sid_w, {"rule": "group k == edge k", "npz": "lifters/data/cycloneiv_ep4cgx150_ddb_map.npz"},
                      "vendor-decoded", "confirmed", pattern=pid, evidence=[ev_ddb], cls="2b",
                      basis="3,479/3,490 wire destinations agree with specimens")
        sid_li = R.scope("mux-input", "keys", {"keys": ["ddb:block->dest:LI-band:6-class-keys"]}, n=1073)
        c_li = R.claim("mux-input", "ddb:block->dest:LI", sid_li, {"rule": "group k == edge k", "band": "LI"}, "vendor-decoded", "open",
                       pattern=pid, evidence=[ev_ddb], cls="2b", basis="1,073 LI destinations disagree with specimen on 6 class keys")
        c_sp = R.claim("mux-input", "ddb:block->dest:LI", R.scope("mux-input", "keys", {"keys": ["specimen:LI-band:6-class-keys"]}, n=1073),
                       {"source": "specimen LI drivers (phys_map lis)"}, "measured", "open", cls="2a", basis="specimen LI band, 6 class keys")
        F.conflict(conn, c_li, c_sp, commit, detail={"band": "LI", "class_keys": 6, "wrong": 1073})

    # ── inventory classes (n_objects from the latest real ledger line) ────────────────────────
    led = _ledger_latest()
    if led:
        cls = {c["id"]: c for c in led["classes"]}
        ev_lut = E.record_decode(conn, "cycloneiv", device, "LUT INIT oracle compare (301 designs)",
                                 {"designs": 301, "bits": 5354496, "matched": 5354496, "missing": 0, "wrong": 0,
                                  "oracle": "Quartus post-fit .vo lut_mask"}, commit, "docs/cycloneiv-bitstream.md",
                                 generator="scripts/cycloneiv_lut_check.py", n_objects=5354496, kind="oracle-compare")
        R.matcher("lut-anchor-v1", "deterministic", "LUT INIT anchor law (DK offsets from LE anchor)", 1, "cycloneiv_le_locate:DK")
        R.matcher("afx-mirror-v1", "statistical", "asm column base from vote peaks (afx_map)", 1, "cycloneiv_asm_decode:afx_map")
        p_lut = R.pattern("lut-anchor-v1", "bit", "LUT INIT bits at anchor + DK offsets, every LE of every LAB", {"dims": 2, "DK": "cycloneiv_le_locate.DK"},
                          matcher_id="lut-anchor-v1", status="oracle-verified")
        p_afx = R.pattern("afx-mirror-v1", "coord-map", "asm frame axis -> plane frame per column (vote peaks; 32 columns != FX)",
                          {"dims": 1, "moved_columns": 32}, matcher_id="afx-mirror-v1", status="open")
        p_leu = R.pattern("le-used-v1", "bit", "LE-used bit at (FX-8, vy - sign)", {"dims": 2, "misses": "14/1018 on one design"},
                          matcher_id="lut-anchor-v1", status="suspect")
        R.matcher("clock-polarity-fit-v1", "statistical", "greedy LAB clock-polarity fit (Jaccard 0.85)", 1, "cycloneiv_route_learn")

        def cls_scope(cid_, label):
            return R.scope("bit", "formula", {"matcher": "inventory", "inventory_class": cid_, "n_objects": cls[cid_]["die_bits"]}, label=label)
        R.claim("bit", "LUT:INIT", cls_scope("1a", cls["1a"]["name"]), {"law": "lut-anchor-v1"}, "pattern-predicted", "oracle-verified",
                pattern=p_lut, evidence=[ev_lut], cls="1a", basis="301 designs, 5,354,496 bits matched 100 %")
        R.claim("bit", "LE:used", cls_scope("1b", cls["1b"]["name"]), {"law": "le-used-v1"}, "pattern-predicted", "suspect", pattern=p_leu,
                cls="1b", basis="14/1,018 misses on one design = unacted refutations")
        R.claim("bit", "LAB:clock-polarity", cls_scope("1c", cls["1c"]["name"]), {"fit": "greedy"}, "statistical", "open", cls="1c",
                basis="Jaccard 0.85 over 5,442 clock lines")
        afx_claim = R.claim("coord-map", "asm->plane:columns", R.scope("coord-map", "keys", {"keys": [f"asm->plane:x{x}" for x in range(118)]}, n=118),
                            {"source": "afx_map"}, "statistical", "open", pattern=p_afx, cls="2a", basis="vote peaks; 32 columns differ from FX")
        for k in ("2a", "2b"):
            R.claim("bit", f"asm:cells:{k}", cls_scope(k, cls[k]["name"]), {"source": "asm.ddb groups", "depends_on": [afx_claim]},
                    "statistical", "open", cls=k, basis="bits vendor-decoded; placement rests on afx_map (weakest link = statistical)")
        hdr = next(c for c in led["classes"] if c["id"] == "5a")
        R.claim("stream-option", "header:sync+crc16", R.scope("stream-option", "keys", {"keys": ["header:sync", "header:crc16"]}, n=hdr["verified"]),
                {"meaning": "sync word + CRC-16"}, "measured", "oracle-verified", cls="5a", basis="recomputed")
        R.claim("stream-option", "header:constant", R.scope("stream-option", "keys", {"keys": ["header:flag", "header:length", "header:family", "header:lanes5-7", "header:0xff-fill"]}, n=hdr["evidence"]),
                {"meaning": "flag/length/family/lanes/fill"}, "vendor-decoded", "confirmed", cls="5a", basis="docs/cycloneiv-bitstream.md Format")
        R.unknown("stream-option", R.scope("stream-option", "keys", {"keys": ["header:option-bits"]}, n=hdr["unknown"]), "unasked",
                  subject="header:option-bits", cls="5a", note="159 option bits set by quartus_cpf; option sweep not done")
        R.claim("bit", "frame:crc16", cls_scope("5b", cls["5b"]["name"]), {"meaning": "CRC-16 per CRAM frame"}, "measured", "oracle-verified",
                cls="5b", basis="recomputed 70/70 vendor pairs")
        R.claim("bit", "stream:pre/postamble", cls_scope("5d", cls["5d"]["name"]), {"meaning": "0xFF fill"}, "measured", "confirmed", cls="5d")
        for k in ("4a", "4b", "4c", "4d", "4e", "5c", "6"):
            n_bits = cls[k]["die_bits"] - (9216 if k == "4b" else 0)   # 4b minus the one measured M9K x1 init site
            R.unknown("bit", R.scope("bit", "formula", {"matcher": "inventory", "inventory_class": k, "n_objects": n_bits}, label=cls[k]["name"]),
                      "unasked", subject=f"class:{k}", cls=k, n=n_bits, note=cls[k]["name"])

    # ── corpus: third-party images (not required: no oracle) ──────────────────────────────────
    man = REPO / "sources/cycloneiv-corpus/manifest.json"
    if man.exists():
        for e in json.loads(man.read_text()).get("entries", []):
            mid = C.ensure_member(conn, "cycloneiv", e["name"], "third-party-image", commit, device=e.get("device"),
                                  source_ref=f"sources/cycloneiv-corpus/{e['name']}", sha256=e.get("sha256"),
                                  gate_script="scripts/cycloneiv_corpus_fetch.py --analyze", required=False,
                                  expected={"decodes": True, "crc_ok": True})
            a = e.get("analysis") or {}
            if a:
                E.record_decode(conn, "cycloneiv", device if (e.get("device") or "").startswith("EP4CGX1") else (e.get("device") or "?"),
                                e["name"], {"analysis": a}, commit, f"sources/cycloneiv-corpus/{e['name']}", kind="image-hit",
                                generator="scripts/cycloneiv_corpus_fetch.py", n_objects=int(a.get("set_bits", 0) or 0))
    import cycloneiv_declare_gate
    log.info("cycloneiv: %d required gate members declared", cycloneiv_declare_gate.declare(conn, commit))
    C.ensure_criterion(conn, "cycloneiv")


# ── Lattice (ECP5 / MachXO2) ────────────────────────────────────────────────

def _tile_types(fam_dir):
    d = REPO / "device-db" / fam_dir / "tiledata"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def _lattice_common(conn, family, fam_dir, devices_list, commit):
    devs = json.loads((REPO / "device-db/devices.json").read_text())["families"][fam_dir]["devices"]
    for name in devices_list:
        d = devs.get(name) or {}
        pk = d.get("packages")
        conn.execute(insert(S.devices).values(family=family, name=name, die=name,
                                              packages=(list(pk.keys()) if isinstance(pk, dict) else pk) or None,
                                              geometry={"frames": d.get("frames"), "bits_per_frame": d.get("bits_per_frame")},
                                              source_ref="device-db/devices.json"))
    R = Reg(conn, family, devices_list[0], commit)
    R.matcher("trellis-tiledb-v1", "deterministic", "prjtrellis tile database (vendored device-db/)", 1, "lifters/trellis_lift.py")
    ev = E.record_decode(conn, family, devices_list[0], f"device-db/{fam_dir} tile database", {"tile_types": len(_tile_types(fam_dir))},
                         commit, f"device-db/{fam_dir}/tiledata", generator="prjtrellis fuzzers (+ scripts/db_overrides.py)")
    pid = R.pattern("trellis-tiledb-v1", "tile-bit", "every bit meaning read from the vendored tile DB", {"dims": 0}, matcher_id="trellis-tiledb-v1",
                    parents=[ev], status="oracle-verified")
    for tt in _tile_types(fam_dir):
        sid = R.scope("tile-bit", "keys", {"keys": [f"tiletype:{tt}"]}, label=tt, n=1)
        R.claim("tile-bit", f"tiletype:{tt}", sid, {"db": f"device-db/{fam_dir}/tiledata/{tt}/bits.db"}, "vendor-decoded", "open", pattern=pid,
                evidence=[ev], basis="vendored tile DB; status per type is set by the gate (oracle-verified where the corpus covers it)")
    return R


def register_ecp5(conn, commit):
    R = _lattice_common(conn, "ecp5", "ECP5", ["LFE5U-25F", "LFE5U-45F", "LFE5U-85F"], commit)
    base = REPO / "tests/baselines/ecp5_oracle.json"
    if base.exists():
        b = json.loads(base.read_text())
        results = {}
        for t, cats in b["targets"].items():
            dev = t.split("_")[0] if t.startswith("LFE5") else None
            C.ensure_member(conn, "ecp5", t, "oracle-build", commit, device=dev, source_ref=f"corpus/ecp5/diamond-oracle/{t}",
                            gate_script="scripts/ecp5_gate.py", required=True)
            results[t] = cats
        run = C.record_gate_run(conn, "ecp5", "scripts/ecp5_gate.py", b["meta"]["commit"], results,
                                code_stamp=b["meta"].get("conditions"), params={"baseline": "tests/baselines/ecp5_oracle.json",
                                                                                "date": b["meta"]["date"]}, summary=b["totals"])
        log.info("ecp5: %d corpus members from the baseline, gate run %d recorded", len(results), run)
    return R


def register_machxo2(conn, commit):
    R = _lattice_common(conn, "machxo2", "MachXO2", ["LCMXO2-1200"], commit)
    sets = {"old": "corpus/machxo2/diamond-fuzz", "constructs": "corpus/machxo2/constructs",
            "coverage": "corpus/machxo2/coverage", "globals": "corpus/machxo2/globals"}
    for name, rel in sets.items():
        d = REPO / rel
        n = sum(1 for p in d.iterdir() if p.is_dir()) if d.is_dir() else 0
        C.ensure_member(conn, "machxo2", name, "oracle-build", commit, device="LCMXO2-1200", source_ref=rel,
                        gate_script="scripts/machxo2_gate.py", required=True, expected={"headline": 100, "wrong": 0, "designs": n})
    # latest gate summaries if a tag exists under tmp/ocmp (disposable; the run is recorded here when present)
    ocmp = REPO / "tmp/ocmp"
    if ocmp.is_dir():
        sys.path.insert(0, str(REPO / "scripts"))
        import machxo2_gate as G
        tags = sorted((p for p in ocmp.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if tags:
            tag = tags[-1]
            results = G.gate_results(G.load(tag.name))
            results = {k: v for k, v in results.items() if k in sets}
            if results:
                C.record_gate_run(conn, "machxo2", "scripts/machxo2_gate.py", commit, results, params={"tag": tag.name},
                                  summary={"note": "per-set aggregate from tmp/ocmp; per-design results live in corpus/machxo2/*/_compare_summary.json"})
                log.info("machxo2: gate run from tmp/ocmp/%s (%d sets)", tag.name, len(results))
    return R


def register_gowin(conn, commit):
    conn.execute(insert(S.devices).values(family="gowin", name="GW1N-2", die="GW1N-2", source_ref="boards/fnirsi-gw1n2"))
    conn.execute(insert(S.devices).values(family="gowin", name="GW1N-1", die="GW1N-1", source_ref="boards/tangnano-gw1n1"))
    R = Reg(conn, "gowin", "GW1N-1", commit)
    R.matcher("apycula-chipdb-v1", "deterministic", "apycula chipdb (license-free build)", 1, "lifters/gowin_lift.py")
    ev = E.record_decode(conn, "gowin", "GW1N-1", "apycula chipdb", {"source": "apycula"}, commit, "lifters/gowin_lift.py",
                         generator="apycula")
    pid = R.pattern("apycula-chipdb-v1", "tile-bit", "tile bit meanings from the apycula chipdb", {"dims": 0}, matcher_id="apycula-chipdb-v1",
                    parents=[ev], status="open")
    R.claim("tile-bit", "chipdb:GW1N-1", R.scope("tile-bit", "all", {"n": 0}, n=0), {"db": "apycula GW1N-1"}, "vendor-decoded", "open",
            pattern=pid, evidence=[ev], basis="LEC-gated (scripts/gowin_lec.py)")
    src = (REPO / "scripts/gowin_lec.py").read_text()
    tree = ast.parse(src)
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DESIGNS" for t in node.targets):
            for el in node.value.elts:
                if isinstance(el, ast.Call) and el.args and isinstance(el.args[0], ast.Constant):
                    names.append(el.args[0].value)
    for n in names:
        C.ensure_member(conn, "gowin", n, "lec", commit, device="GW1N-1", source_ref="scripts/gowin_lec.py DESIGNS",
                        gate_script="scripts/gowin_lec.py", required=True, expected={"equivalent": True})
    C.ensure_criterion(conn, "gowin")
    log.info("gowin: %d LEC corpus members", len(names))
    return R


def register_cyclonev(conn, commit):
    builds = [dict(r._mapping) for r in conn.execute(select(S.corpus_builds).where(S.corpus_builds.c.family == "cyclonev"))]
    devs = sorted({b["device"] for b in builds}) or ["5CEBA4U19C8"]
    for d in devs:
        conn.execute(insert(S.devices).values(family="cyclonev", name=d, die=None, source_ref="corpus_builds"))
    R = Reg(conn, "cyclonev", devs[0], commit)
    R.matcher("mistral-cvdb-v1", "deterministic", "Mistral generator inputs (cv_* tables)", 1, "lifters/cyclonev_lift.py")
    for b in builds:
        C.ensure_member(conn, "cyclonev", b["design"], "oracle-build", commit, device=b["device"], build_id=b["id"],
                        source_ref=b["out_dir"], gate_script="scripts/cyclonev_postfit_compare.py", required=(b["status"] == "ok"))
    cmp_rows = conn.execute(select(S.gate_verdicts.c.build, S.gate_verdicts.c.field, S.gate_verdicts.c.verdict)).fetchall()
    if cmp_rows:
        by = {}
        bid2name = {b["id"]: b["design"] for b in builds}
        vm = {"MATCH": "matched", "MISMATCH": "wrong", "LIFT_MISSING": "missing", "QUARTUS_ONLY": "missing"}
        for bid, field, verdict in cmp_rows:
            cat = field.split(".")[0]
            c = by.setdefault(bid2name.get(bid, str(bid)), {}).setdefault(cat, {"matched": 0, "missing": 0, "extra": 0, "wrong": 0})
            c[vm.get(verdict, "wrong")] += 1
        C.record_gate_run(conn, "cyclonev", "scripts/cyclonev_postfit_compare.py", commit, by)
    C.ensure_criterion(conn, "cyclonev")
    log.info("cyclonev: %d corpus members from corpus_builds, %d compare rows", len(builds), len(cmp_rows))
    return R


# ── main ─────────────────────────────────────────────────────────────────────

def verify_json(conn, device, json_dir):
    """Round-trip every migrated JSON: pair count + canonical hash of file == of DB rows."""
    ok = True
    print(f"{'file':44s} {'pairs':>6s} {'json sha256':>12s} {'db sha256':>12s}  verdict")
    for p in sorted(Path(json_dir).glob("*.json")):
        pairs = E.read_json_pairs(str(p), NV)
        if pairs is None:
            d = json.loads(p.read_text())
            m = conn.execute(select(S.evidence.c.result).where(and_(S.evidence.c.family == "cycloneiv", S.evidence.c.kind == "derived-table",
                                                                   S.evidence.c.name == p.name))).fetchone()
            canon = lambda o: hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()  # noqa: E731
            hj = canon(d)
            hd = canon(m[0]["file"]) if m else "-"
            good = hj == hd
            ok &= good
            print(f"{p.name:44s} {'claim':>6s} {hj[:12]:>12s} {hd[:12]:>12s}  {'OK' if good else 'MISMATCH'}")
            continue
        rel = os.path.relpath(p, REPO)
        back = E.pairs_from_db(conn, "cycloneiv", device, rel)
        hj, hd = E.canonical_hash(pairs), E.canonical_hash(back)
        good = hj == hd and len(pairs) == len(back)
        ok &= good
        print(f"{p.name:44s} {len(pairs):6d} {hj[:12]:>12s} {hd[:12]:>12s}  {'OK' if good else 'MISMATCH'}")
    return ok


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/claims_register.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", required=True, choices=sorted(FAMILIES))
    ap.add_argument("--device", default=None)
    ap.add_argument("--import-json", default=None, metavar="DIR", help="one-shot: migrate legacy evidence JSONs into evidence rows")
    ap.add_argument("--verify-json", action="store_true", help="round-trip check of every JSON in --import-json DIR")
    a = ap.parse_args()
    commit = git_head()
    S.init()
    with db.engine().begin() as conn:
        check_single_family(conn, a.family)
        wipe(conn, a.family)
        ensure_family(conn, a.family)
        if a.import_json:
            if a.family != "cycloneiv":
                db.die("--import-json is wired for cycloneiv evidence JSON shapes only")
            import_json_dir(conn, a.device or "EP4CGX150", commit, a.import_json)
        if a.family == "cycloneiv":
            dev = a.device or "EP4CGX150"
            register_cycloneiv(conn, dev, commit)
        elif a.family == "ecp5":
            dev = "LFE5U-25F"
            register_ecp5(conn, commit)
        elif a.family == "machxo2":
            dev = "LCMXO2-1200"
            register_machxo2(conn, commit)
        elif a.family == "gowin":
            dev = "GW1N-1"
            register_gowin(conn, commit)
        elif a.family == "cyclonev":
            dev = None
            register_cyclonev(conn, commit)
        else:
            db.die(f"no register path for {a.family}")
        for d in [r[0] for r in conn.execute(select(S.devices.c.name).where(S.devices.c.family == a.family))]:
            ledger_from_claims(conn, a.family, d, commit)
        from sqlalchemy import func
        for t in (S.evidence, S.scopes, S.claims, S.claim_patterns, S.expectations, S.unknowns, S.claim_conflicts,
                  S.audits, S.corpus_members, S.gate_runs, S.gate_results, S.coverage_ledger):
            stmt = select(func.count()).select_from(t)
            if "family" in t.c:
                stmt = stmt.where(t.c.family == a.family)
            log.info("%-16s %8d", t.name, conn.execute(stmt).scalar())
    if a.verify_json:
        if not a.import_json:
            db.die("--verify-json needs --import-json DIR (the files to compare against)")
        with db.engine().connect() as conn:
            ok = verify_json(conn, a.device or "EP4CGX150", a.import_json)
        print("VERIFY", "OK: every file round-trips" if ok else "FAILED: do not remove any JSON")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
