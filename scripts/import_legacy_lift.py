#!/usr/bin/env python3.15t
"""Import a legacy per-bitstream pluribus database into the per-family database, as OPEN imported claims.

  PLURIBUS_SQLITE_PATH=databases/<family>/<name>.db python3.15t scripts/import_legacy_lift.py \\
      --old <old.db> --family machxo2 [--label L ...] [--dry-run]
  PLURIBUS_SQLITE_PATH=... python3.15t scripts/import_legacy_lift.py --validate --label L [--ingest report.json]

Design: docs/legacy-import.md. The old file is read with sqlite3 directly (old schema, schema.init never runs
on it). Lift tables are copied column-by-column (missing columns -> NULL, dropped columns listed); the old
efb_ports / ebr_ports / cv_hard_cells become hard_cells + hard_cell_ports; reachability* / ff_cones are
not copied (re-run reach.py --replace + reach2.py). Every imported object becomes a claim with its original
provenance as tier (vendor-decoded for lifter output, measured for board-sourced names/pads), status open,
pattern `decoder:<family>:<kind>` (so a refutation fans out within that decode kind), plus a lift_provenance
row; annotations with a non-confirmed confidence become EXPECTATIONS (matcher human-annotation-v1).
Integrity gate: per-table row counts old == new, recorded as a gate run (member legacy:<label>, not required).
--validate: lift_summary change detector (new DB vs counts from the old file) as a gate run; --ingest adds an
external gate report ({"category": {"matched", "missing", "extra", "wrong", "matched_cells"?, "wrong_cells"?,
"missing_cells"?}}) whose per-object lists confirm / refute the imported claims through the feedback loop.
Log: tmp/logs/import_legacy_lift.log
"""
import argparse
import collections
import datetime
import hashlib
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import and_, delete, insert, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import corpus as C          # noqa: E402
from provenance import evidence_io as E     # noqa: E402
from provenance import feedback as F        # noqa: E402

log = logging.getLogger("import_legacy_lift")

# tables copied by name (bitstream-scoped); order respects nothing (no FKs between them)
COPY_TABLES = ("nets", "luts", "ffs", "alu_cells", "net_fanout", "pad_map", "arcs", "clock_domains",
               "clock_domain_summary", "const_nets", "net_stats", "lut_symbolic", "ebr_buses", "cone_hashes",
               "cdc_synchronisers", "ebr_init", "ebr_init_blocks", "efb_config", "net_names", "cell_names",
               "spi_registers", "open_questions", "hard_cells", "hard_cell_ports", "tiles", "netlist_patterns")
SKIP_TABLES = {"reachability", "reachability_rev", "pad_ff_influence", "ff_cones",            # derived: reach.py / reach2.py
               "critical_paths", "dominators", "ff_d_functions", "hpbx_branches", "mux_cells",  # retired
               "patterns", "shift_reg_bits", "anlogic_tiles", "device_fingerprints"}
BLOCK_KIND = {"machxo2": "EBR", "ecp5": "EBR", "gowin": "BSRAM", "anlogic": "BRAM"}
CONFIRMED = ("confirmed",)


def now():
    return datetime.datetime.now().astimezone()


def old_tables(old):
    return {r[0]: [c[1] for c in old.execute(f'PRAGMA table_info("{r[0]}")')]
            for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def rows_of(old, table, cols, bs_id):
    sel = ", ".join(f'"{c}"' for c in cols)
    return [dict(zip(cols, r)) for r in old.execute(f'SELECT {sel} FROM "{table}" WHERE bitstream=?', (bs_id,))]


def copy_table(old, conn, table, ocols, old_bs, new_bs, dropped):
    t = S.metadata.tables[table]
    ncols = {c.name for c in t.columns}
    use = [c for c in ocols if c in ncols and c not in ("id", "bitstream")]
    for c in ocols:
        if c not in ncols and c not in ("id", "bitstream"):
            dropped[table].add(c)
    n = 0
    buf = []
    for r in rows_of(old, table, use, old_bs):
        for c in use:
            if isinstance(t.c[c].type, S.JSON) and isinstance(r[c], str):
                try:
                    r[c] = json.loads(r[c])
                except ValueError:
                    pass
        r["bitstream"] = new_bs
        buf.append(r)
        if len(buf) >= 5000:
            conn.execute(insert(t), buf)
            n += len(buf)
            buf = []
    if buf:
        conn.execute(insert(t), buf)
        n += len(buf)
    return n


def copy_hard_blocks(old, conn, otabs, family, old_bs, new_bs):
    """efb_ports / ebr_ports / cv_hard_cells (old shapes) -> hard_cells + hard_cell_ports."""
    cells, ports = {}, []
    if "efb_ports" in otabs:
        for r in rows_of(old, "efb_ports", ["port_name", "net", "direction"], old_bs):
            cells.setdefault("EFB", {"cell": "EFB", "kind": "EFB", "params": None})
            ports.append(dict(cell="EFB", port=r["port_name"], direction=r["direction"], role=None, net=r["net"]))
    if "ebr_ports" in otabs:
        kind = BLOCK_KIND.get(family, "BRAM")
        for r in rows_of(old, "ebr_ports", ["block", "port", "role", "net"], old_bs):
            cells.setdefault(r["block"], {"cell": r["block"], "kind": kind, "params": None})
            ports.append(dict(cell=r["block"], port=r["port"], direction=None, role=r["role"], net=r["net"]))
    if "cv_hard_cells" in otabs:
        for r in rows_of(old, "cv_hard_cells", ["cell", "kind", "data"], old_bs):
            d = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            cells[r["cell"]] = {"cell": r["cell"], "kind": r["kind"], "params": d}
    if cells:
        conn.execute(insert(S.hard_cells), [dict(c, bitstream=new_bs) for c in cells.values()])
    if ports:
        conn.execute(insert(S.hard_cell_ports), [dict(p, bitstream=new_bs) for p in ports])
    return len(cells), len(ports)


def import_label(old, old_path, family, label, commit, dry):
    otabs = old_tables(old)
    brow = old.execute("SELECT * FROM bitstreams WHERE label=?", (label,)).fetchone()
    if brow is None:
        db.die(f"label {label!r} not in {old_path}")
    bcols = otabs["bitstreams"]
    b = dict(zip(bcols, brow))
    old_bs = b["id"]
    counts_old = {}
    for t in list(COPY_TABLES) + ["efb_ports", "ebr_ports", "cv_hard_cells"]:
        if t in otabs:
            counts_old[t] = old.execute(f'SELECT COUNT(*) FROM "{t}" WHERE bitstream=?', (old_bs,)).fetchone()[0]
    log.info("%s: old row counts %s", label, {k: v for k, v in counts_old.items() if v})
    if dry:
        return None
    sha = hashlib.sha256(Path(old_path).read_bytes()).hexdigest()
    dropped = collections.defaultdict(set)
    with db.engine().begin() as conn:
        E.ensure_family(conn, family)
        ex = conn.execute(select(S.bitstreams.c.id).where(S.bitstreams.c.label == label)).fetchone()
        if ex:   # always-rebuild: the label's rows (cascade), its imported claims and the previous import evidence
            conn.execute(delete(S.bitstreams).where(S.bitstreams.c.id == ex[0]))
            for t in (S.claims, S.expectations, S.unknowns):
                conn.execute(delete(t).where(and_(t.c.family == family, t.c.subject_key.like(f"{label}:%"))))
            conn.execute(delete(S.evidence).where(and_(S.evidence.c.family == family, S.evidence.c.name == f"legacy import {label}")))
        new_bs = conn.execute(insert(S.bitstreams).values(
            label=label, filename=b.get("filename") or "", device=b.get("device") or "", package=b.get("package") or "",
            family=family, toolchain=b.get("toolchain") or b.get("diamond_version"),
            loaded_at=now())).inserted_primary_key[0]
        counts_new = {}
        for t in COPY_TABLES:
            if t in otabs:
                counts_new[t] = copy_table(old, conn, t, otabs[t], old_bs, new_bs, dropped)
        n_cells, n_ports = copy_hard_blocks(old, conn, otabs, family, old_bs, new_bs)
        if n_cells:
            counts_new["hard_cells"] = counts_new.get("hard_cells", 0) + n_cells
            counts_new["hard_cell_ports"] = counts_new.get("hard_cell_ports", 0) + n_ports
        ev = conn.execute(insert(S.evidence).values(
            kind="vendor-decode", family=family, device=b.get("device") or "", name=f"legacy import {label}",
            source_ref=os.path.relpath(old_path, REPO) if str(old_path).startswith(str(REPO)) else Path(old_path).name,
            sha256=sha, generator="scripts/import_legacy_lift.py", tool_version=b.get("diamond_version") or b.get("toolchain"),
            result={"old_tables": {t: c for t, c in otabs.items()}, "counts_old": counts_old, "counts_new": counts_new,
                    "dropped_columns": {t: sorted(c) for t, c in dropped.items()}, "label": label},
            n_objects=sum(counts_new.values()), commit=commit, created_at=now())).inserted_primary_key[0]
        n_claims, n_exp = register_claims(conn, old, otabs, family, label, b, old_bs, new_bs, ev, commit)
        integrity_gate(conn, family, label, b, counts_old, counts_new, commit)
    log.info("%s: imported %s; dropped columns %s; claims %d, expectations %d, evidence %d",
             label, counts_new, {t: sorted(c) for t, c in dropped.items()}, n_claims, n_exp, ev)
    return new_bs


# ── claims ──────────────────────────────────────────────────────────────────────────────────

def _scope(conn, family, device, space, what, n):
    from provenance import scopes as SC
    d = {"matcher": "legacy-import", "what": what, "n_objects": int(n)}
    key = SC.canonical(space, "formula", d)
    r = conn.execute(select(S.scopes.c.id).where(and_(S.scopes.c.family == family, S.scopes.c.device == device,
                                                      S.scopes.c.scope_key == key))).fetchone()
    if r:
        conn.execute(S.scopes.update().where(S.scopes.c.id == r[0]).values(n_objects=int(n)))
        return r[0]
    return conn.execute(insert(S.scopes).values(family=family, device=device, space=space, kind="formula", definition=d,
                                                scope_key=key, n_objects=int(n), label=what)).inserted_primary_key[0]


def _pattern(conn, family, device, pid, kind, commit):
    if conn.execute(select(S.claim_patterns.c.id).where(S.claim_patterns.c.id == pid)).fetchone() is None:
        if conn.execute(select(S.matchers.c.id).where(S.matchers.c.id == "lifter-v1")).fetchone() is None:
            conn.execute(insert(S.matchers).values(id="lifter-v1", kind="deterministic", name="family lifter (device-db decode)",
                                                   version=1, code_ref=f"lifters/{family}_lift.py", created_commit=commit))
        conn.execute(insert(S.claim_patterns).values(
            id=pid, family=family, device=device, matcher_id="lifter-v1", space="cell-param" if kind in ("lut", "ff") else "pip" if kind == "arc" else "port-map",
            description=f"{family} lifter decode of {kind} objects (imported legacy lift)", law={"decoder": f"lifters/{family}_lift.py", "kind": kind, "dims": 0},
            status="open", created_commit=commit, updated_at=now()))


def register_claims(conn, old, otabs, family, label, b, old_bs, new_bs, ev, commit):
    device = b.get("device") or ""
    basis = f"imported legacy lift ({Path(str(b.get('filename'))).name}); decoder lifters/{family}_lift.py"
    claims, prov, events, expectations, unknowns = [], [], [], [], []

    def add(space, subject, meaning, tier, kind, scope_id, obj_kind, obj_key, pid=None, basis_=basis):
        claims.append(dict(family=family, device=device, space=space, subject_key=f"{label}:{subject}", scope_id=scope_id,
                           meaning=meaning, tier=tier, status="open", pattern_id=pid, n_objects=1, confidence_basis=basis_,
                           created_commit=commit, updated_at=now(), _obj=(obj_kind, obj_key)))

    # LUTs, FFs, arcs, pads, hard-cell ports: vendor-decoded (pattern per decode kind)
    luts = rows_of(old, "luts", [c for c in otabs["luts"] if c not in ("id", "bitstream")], old_bs) if "luts" in otabs else []
    ffs = rows_of(old, "ffs", [c for c in otabs["ffs"] if c not in ("id", "bitstream")], old_bs) if "ffs" in otabs else []
    arcs = rows_of(old, "arcs", ["tile_row", "tile_col", "sink_wire", "source_wire", "sink_net", "source_net"], old_bs) if "arcs" in otabs else []
    pads = rows_of(old, "pad_map", [c for c in otabs["pad_map"] if c not in ("id", "bitstream")], old_bs) if "pad_map" in otabs else []
    hports = [dict(r._mapping) for r in conn.execute(select(S.hard_cell_ports).where(S.hard_cell_ports.c.bitstream == new_bs))]
    for kind, n in (("lut", len(luts)), ("ff", len(ffs)), ("arc", len(arcs)), ("pad", len(pads)), ("hardport", len(hports))):
        if n:
            _pattern(conn, family, device, f"decoder:{family}:{kind}", kind, commit)
    sc = {k: _scope(conn, family, device, sp, f"{label}:{k}", n) for k, sp, n in
          (("lut", "cell-param", len(luts)), ("ff", "cell-param", len(ffs)), ("arc", "pip", len(arcs)),
           ("pad", "port-map", len(pads)), ("hardport", "port-map", len(hports))) if n}
    for r in luts:
        add("cell-param", f"LUT:{r['cell']}:init", {k: r.get(k) for k in ("init", "a", "b", "c", "d", "e", "f", "z", "fn")},
            "vendor-decoded", "lut", sc["lut"], "lut", r["cell"], f"decoder:{family}:lut")
    for r in ffs:
        if r.get("d_fault"):
            unknowns.append(dict(family=family, device=device, space="cell-param", subject_key=f"{label}:FF:{r['cell']}:d",
                                 scope_id=sc["ff"], reason="unasked", status="open", n_objects=1,
                                 note=f"d_fault={r['d_fault']} in the legacy lift", created_commit=commit, updated_at=now()))
        add("cell-param", f"FF:{r['cell']}", {k: r.get(k) for k in ("clk", "ce", "d", "q", "lsr", "dtype", "d_fault")},
            "vendor-decoded", "ff", sc["ff"], "ff", r["cell"], f"decoder:{family}:ff")
    for r in arcs:
        add("pip", f"{r['sink_wire']}<-{r['source_wire']}@{r['tile_row']},{r['tile_col']}",
            {"sink_net": r["sink_net"], "source_net": r["source_net"]}, "vendor-decoded", "arc", sc["arc"], "arc",
            f"{r['tile_row']},{r['tile_col']}:{r['sink_wire']}", f"decoder:{family}:arc")
    for r in pads:
        board = r.get("chip_signal") not in (None, "", "?") or r.get("chip_ref") not in (None, "", "?")
        add("port-map", f"PAD:{r['pin']}", {k: r.get(k) for k in ("label", "direction", "net_in", "net_out", "chip_ref", "chip_pin", "chip_signal", "conn_class")},
            "measured" if board else "vendor-decoded", "pad", sc["pad"], "pad", str(r["pin"]), None if board else f"decoder:{family}:pad",
            basis_=("board pins TSV (measured on the board)" if board else basis))
    for r in hports:
        add("port-map", f"{r['cell']}:{r['port']}", {"net": r["net"], "direction": r["direction"], "role": r["role"]},
            "vendor-decoded", "hardport", sc["hardport"], "hard-cell", f"{r['cell']}:{r['port']}", f"decoder:{family}:hardport")
    # names: confirmed -> measured claims; anything else -> expectations (human annotation)
    names = rows_of(old, "net_names", [c for c in otabs["net_names"] if c not in ("id", "bitstream")], old_bs) if "net_names" in otabs else []
    cnames = rows_of(old, "cell_names", [c for c in otabs["cell_names"] if c not in ("id", "bitstream")], old_bs) if "cell_names" in otabs else []
    n_conf = sum(1 for r in names if r.get("confidence") in CONFIRMED)
    if n_conf:
        sc["name"] = _scope(conn, family, device, "net-attr", f"{label}:net-name", n_conf)
    n_ann = len(names) - n_conf + len(cnames)
    if n_ann:
        sc["annot"] = _scope(conn, family, device, "net-attr", f"{label}:annotation", n_ann)
        if conn.execute(select(S.matchers.c.id).where(S.matchers.c.id == "human-annotation-v1")).fetchone() is None:
            conn.execute(insert(S.matchers).values(id="human-annotation-v1", kind="statistical", name="human annotation (estimate / inferred / guess)",
                                                   version=1, code_ref="annotate.py", created_commit=commit))
    for r in names:
        if r.get("confidence") in CONFIRMED:
            add("net-attr", f"{r['net']}:name", {"name": r["name"], "description": r.get("description"), "source": r.get("source")},
                "measured", "name", sc["name"], "net", r["net"], None, basis_=f"net annotation source={r.get('source')} confidence=confirmed")
        else:
            expectations.append(dict(family=family, device=device, space="net-attr", subject_key=f"{label}:{r['net']}:name", scope_id=sc["annot"],
                                     matcher_id="human-annotation-v1", expected={"name": r["name"], "description": r.get("description")},
                                     confidence={"estimate": 0.6, "inferred": 0.5, "guess": 0.3, "speculative": 0.2}.get(r.get("confidence"), 0.3),
                                     confidence_basis=f"annotation confidence={r.get('confidence')} source={r.get('source')}",
                                     supporting_evidence=[ev], status="open", n_objects=1, created_commit=commit, updated_at=now()))
    for r in cnames:
        expectations.append(dict(family=family, device=device, space="net-attr", subject_key=f"{label}:cell:{r['cell']}:name", scope_id=sc["annot"],
                                 matcher_id="human-annotation-v1", expected={"name": r["name"], "description": r.get("description")},
                                 confidence={"estimate": 0.6, "inferred": 0.5, "guess": 0.3}.get(r.get("confidence"), 0.3),
                                 confidence_basis=f"cell annotation confidence={r.get('confidence')}", supporting_evidence=[ev],
                                 status="open", n_objects=1, created_commit=commit, updated_at=now()))
    # bulk writes
    objs = [c.pop("_obj") for c in claims]
    for i in range(0, len(claims), 2000):
        conn.execute(insert(S.claims), claims[i:i + 2000])
    ids = [r[0] for r in conn.execute(select(S.claims.c.id).where(and_(S.claims.c.family == family, S.claims.c.subject_key.like(f"{label}:%")))
                                      .order_by(S.claims.c.id))]
    assert len(ids) == len(claims), (len(ids), len(claims))
    conn.execute(insert(S.claim_evidence), [dict(claim_id=cid, evidence_id=ev, role="direct") for cid in ids]) if ids else None
    conn.execute(insert(S.claim_events), [dict(claim_id=cid, pattern_id=c["pattern_id"], event="created", evidence_id=ev, commit=commit, ts=now(),
                                               detail={"imported": label}) for cid, c in zip(ids, claims)]) if ids else None
    conn.execute(insert(S.lift_provenance), [dict(bitstream=new_bs, object_kind=ok, object_key=key, min_tier=c["tier"], min_status="open",
                                                  claim_ids=[cid]) for cid, c, (ok, key) in zip(ids, claims, objs)]) if ids else None
    if expectations:
        for i in range(0, len(expectations), 2000):
            conn.execute(insert(S.expectations), expectations[i:i + 2000])
    if unknowns:
        conn.execute(insert(S.unknowns), unknowns)
    return len(claims), len(expectations)


def integrity_gate(conn, family, label, b, counts_old, counts_new, commit):
    """Per-table old vs new counts -> gate run (member legacy:<label>, kind roundtrip, not required)."""
    C.ensure_member(conn, family, f"legacy:{label}", "roundtrip", commit, device=b.get("device"), gate_script="scripts/import_legacy_lift.py",
                    required=False, expected={"headline": 100, "wrong": 0, "note": "import integrity, not a design oracle"})
    merged = {}
    for t, n_old in counts_old.items():
        tt = {"efb_ports": "hard_cell_ports", "ebr_ports": "hard_cell_ports", "cv_hard_cells": "hard_cells"}.get(t, t)
        merged[tt] = merged.get(tt, 0) + n_old
    res = {}
    for t, n_old in merged.items():
        n_new = counts_new.get(t, 0)
        res[t] = {"matched": min(n_old, n_new), "missing": max(0, n_old - n_new), "extra": max(0, n_new - n_old), "wrong": 0}
    C.record_gate_run(conn, family, "scripts/import_legacy_lift.py", commit, {f"legacy:{label}": res},
                      params={"label": label, "check": "import-integrity"})


# ── validation ──────────────────────────────────────────────────────────────────────────────

def legacy_summary(old_path, label):
    """lift_summary-style counts straight from the old file (it cannot be opened by lift_summary)."""
    import lift_summary as LS
    old = sqlite3.connect(f"file:{Path(old_path).resolve()}?mode=ro", uri=True)
    tabs = old_tables(old)
    bs = old.execute("SELECT id FROM bitstreams WHERE label=?", (label,)).fetchone()[0]
    s = {"label": label}
    for t in LS.COUNT_TABLES:
        s[f"n_{t}"] = old.execute(f'SELECT COUNT(*) FROM "{t}" WHERE bitstream=?', (bs,)).fetchone()[0] if t in tabs else 0
    s["n_efb_ports"] = old.execute("SELECT COUNT(*) FROM efb_ports WHERE bitstream=?", (bs,)).fetchone()[0] if "efb_ports" in tabs else 0
    s["n_ebr_ports"] = old.execute("SELECT COUNT(*) FROM ebr_ports WHERE bitstream=?", (bs,)).fetchone()[0] if "ebr_ports" in tabs else 0
    s["n_patterns"] = old.execute("SELECT COUNT(*) FROM patterns WHERE bitstream=?", (bs,)).fetchone()[0] if "patterns" in tabs else 0
    for d in ("in", "out"):
        s[f"efb_{d}"] = old.execute("SELECT COUNT(*) FROM efb_ports WHERE bitstream=? AND direction=?", (bs, d)).fetchone()[0] if "efb_ports" in tabs else 0
    s["n_ffs_d_unresolved"] = old.execute("SELECT COUNT(*) FROM ffs WHERE bitstream=? AND d_fault IS NOT NULL", (bs,)).fetchone()[0] if "d_fault" in tabs.get("ffs", []) else 0
    s["n_ffs_d_const"] = old.execute("SELECT COUNT(*) FROM ffs WHERE bitstream=? AND d LIKE '1''b%'", (bs,)).fetchone()[0]
    old.close()
    return s


def validate(old_path, family, label, ingest, commit):
    import lift_summary as LS
    new = LS.summarise(label)
    keys = [k for k in new if k.startswith("n_") or k in ("efb_in", "efb_out")]
    res = {}
    if old_path:
        legacy = legacy_summary(old_path, label)
        same = [k for k in keys if k in legacy and legacy[k] == new[k]]
        diff = [k for k in keys if k in legacy and legacy[k] != new[k]]
        for k in diff:
            log.info("lift_summary CHANGED %-24s old %s -> new %s", k, legacy[k], new[k])
        res["lift_summary"] = {"matched": len(same), "missing": 0, "extra": 0, "wrong": len(diff)}
        # the derived tables are rebuilt by reach/reach2, not imported: their absence is reported, not scored
        log.info("lift_summary: %d fields equal, %d differ (%s)", len(same), len(diff), diff)
    confirms, refutes = [], []
    if ingest:
        rep = json.loads(Path(ingest).read_text())
        for cat, c in rep.items():
            res[cat] = {k: int(c.get(k, 0)) for k in ("matched", "missing", "extra", "wrong")}
            confirms += [(cat, x) for x in c.get("matched_cells", [])]
            refutes += [(cat, x) for x in c.get("wrong_cells", []) + c.get("missing_cells", [])]
    with db.engine().begin() as conn:
        b = conn.execute(select(S.bitstreams).where(S.bitstreams.c.label == label)).fetchone()
        if b is None:
            db.die(f"label {label!r} not imported yet")
        C.ensure_member(conn, family, f"legacy:{label}", "roundtrip", commit, device=b.device, gate_script="scripts/import_legacy_lift.py",
                        required=False)
        run = C.record_gate_run(conn, family, "scripts/import_legacy_lift.py --validate", commit, {f"legacy:{label}": res},
                                params={"label": label, "ingest": ingest})
        if confirms or refutes:
            ev = conn.execute(insert(S.evidence).values(kind="oracle-compare", family=family, device=b.device, name=f"ingested gate report {label}",
                                                        source_ref=str(ingest), generator="external", result=res, n_objects=len(confirms) + len(refutes),
                                                        commit=commit, created_at=now())).inserted_primary_key[0]
            def claim_of(cat, cell):
                subj = {"lut_init": f"{label}:LUT:{cell}:init", "registers": f"{label}:FF:{cell}"}.get(cat, f"{label}:{cell}")
                r = conn.execute(select(S.claims.c.id).where(and_(S.claims.c.family == family, S.claims.c.subject_key == subj))).fetchone()
                return r[0] if r else None
            n_c = n_r = 0
            for cat, cell in confirms:
                cid = claim_of(cat, cell)
                if cid:
                    F.confirm(conn, cid, ev, commit)
                    n_c += 1
            for cat, cell in refutes:
                cid = claim_of(cat, cell)
                if cid:
                    F.refute(conn, cid, ev, commit)
                    n_r += 1
            log.info("ingest: %d claims confirmed, %d refuted (fan-out through decoder patterns)", n_c, n_r)
    log.info("validation gate run %d: %s", run, res)
    return res


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/import_legacy_lift.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", help="legacy database file (read-only)")
    ap.add_argument("--family", required=True)
    ap.add_argument("--label", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--ingest", default=None, help="external gate report JSON (see module doc)")
    a = ap.parse_args()
    commit = E.git_head(REPO)
    S.init()
    if a.validate:
        for label in a.label or []:
            validate(a.old, a.family, label, a.ingest, commit)
        return 0
    if not a.old:
        ap.error("--old is required for an import")
    old = sqlite3.connect(f"file:{Path(a.old).resolve()}?mode=ro", uri=True)
    labels = a.label or [r[0] for r in old.execute("SELECT label FROM bitstreams ORDER BY label")]
    for label in labels:
        import_label(old, a.old, a.family, label, commit, a.dry_run)
    old.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
