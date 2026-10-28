"""Evidence write path + bit-set packing. Specimen tools record HERE, never to JSON files.

  record_specimen(conn, family, device, name, base, only_spec, only_base, meta, source_ref,
                  generator, commit, bits_per_frame, kind="specimen-pair", stable=None)
  record_absence(conn, family, device, name, scope_id, record, commit)
  pack(indices) / unpack(blob)      sorted flat indices <-> delta-LEB128 bytes
  canonical_hash(pairs)             sha256 of the canonical pair set (round-trip check)
  read_json_pairs(path, bits_per_frame)  the two legacy JSON shapes -> canonical pairs (migration only)

Bit sets: sorted flat indices (frame * bits_per_frame + v), delta-encoded LEB128 varints.
Why: lossless, dialect-neutral (BLOB), ~1 byte per bit for dense sets vs 8-14 in JSON, and
the same bytes are the git-tracked export (base64), so one encoding, one hash.
"""
import base64
import datetime
import hashlib
import json
import os

import numpy as np
from sqlalchemy import insert, select, and_

import db
import schema as S
from provenance import tiers

ENCODING = "dvarint:flat"


def pack(indices):
    idx = np.unique(np.asarray(list(indices), np.int64))
    if idx.size and idx[0] < 0:
        db.die("negative bit index")
    out = bytearray()
    prev = 0
    for v in idx.tolist():
        d = v - prev
        prev = v
        while True:
            b = d & 0x7F
            d >>= 7
            if d:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
    return bytes(out)


def unpack(blob):
    if not blob:
        return np.zeros(0, np.int64)
    out, cur, shift, prev = [], 0, 0, 0
    for b in blob:
        cur |= (b & 0x7F) << shift
        if b & 0x80:
            shift += 7
        else:
            prev += cur
            out.append(prev)
            cur, shift = 0, 0
    return np.asarray(out, np.int64)


def to_flat(cells, bits_per_frame):
    """[[frame, v], ...] or [flat, ...] -> sorted unique flat int64."""
    if not cells:
        return np.zeros(0, np.int64)
    a = np.asarray(cells, np.int64)
    if a.ndim == 2:
        a = a[:, 0] * bits_per_frame + a[:, 1]
    return np.unique(a)


def canonical_hash(pairs):
    """pairs: {name: {"base": str|None, "only_spec": [flat...], "only_base": [flat...], "meta": {...}}}."""
    h = hashlib.sha256()
    for name in sorted(pairs):
        p = pairs[name]
        rec = {"name": name, "base": p.get("base"),
               "only_spec": [int(x) for x in np.unique(np.asarray(p["only_spec"], np.int64)).tolist()],
               "only_base": [int(x) for x in np.unique(np.asarray(p["only_base"], np.int64)).tolist()],
               "meta": p.get("meta") or {}}
        h.update(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode())
        h.update(b"\n")
    return h.hexdigest()


def read_json_pairs(path, bits_per_frame):
    """Legacy evidence JSON -> canonical pairs. Two shapes:
    forced:  {name: {src, snk, hop, [rcf], on: [flat], off: [flat]}}  or {name: {only_spec, only_base}}
    m9k:     {name: {base, only_base: [[f,v]], only_spec: [[f,v]]}}
    Everything that is not a bit list is kept verbatim in meta (lossless)."""
    d = json.loads(open(path).read())
    pairs = {}
    for name, r in d.items():
        if not isinstance(r, dict):
            return None   # a map / table file (width, cells, masked...), not pairs
        if "on" in r or "off" in r:
            spec, base_bits = r.get("on", []), r.get("off", [])
            meta = {k: v for k, v in r.items() if k not in ("on", "off")}
            base = None
        elif "only_spec" in r or "only_base" in r:
            spec, base_bits = r.get("only_spec", []), r.get("only_base", [])
            meta = {k: v for k, v in r.items() if k not in ("only_spec", "only_base", "base")}
            base = r.get("base")
        else:
            return None   # not a pair file (a map / table): caller decides
        pairs[name] = {"base": base, "only_spec": to_flat(spec, bits_per_frame).tolist(),
                       "only_base": to_flat(base_bits, bits_per_frame).tolist(), "meta": meta}
    return pairs


def ensure_family(conn, family):
    """families row for `family` (FK target of every evidence row); one family per database."""
    tiers.check(family, tuple(tiers.FAMILIES), "family")
    if conn.execute(select(S.families.c.id).where(S.families.c.id == family)).fetchone() is None:
        conn.execute(insert(S.families).values(id=family, **tiers.FAMILIES[family]))


def git_head(repo=None):
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record_specimen(conn, family, device, name, base, only_spec, only_base, meta, source_ref, generator,
                    commit, bits_per_frame, kind="specimen-pair", stable=None, tool_version=None,
                    build_base=None, build_spec=None, sha256=None):
    """One evidence row per specimen pair. Idempotent on (family, device, kind, name, source_ref)."""
    tiers.check(kind, tiers.EVIDENCE_KINDS, "evidence kind")
    spec = to_flat(only_spec, bits_per_frame)
    bas = to_flat(only_base, bits_per_frame)
    existing = conn.execute(select(S.evidence.c.id).where(and_(
        S.evidence.c.family == family, S.evidence.c.device == device, S.evidence.c.kind == kind,
        S.evidence.c.name == name, S.evidence.c.source_ref == source_ref))).fetchone()
    if existing:
        return existing[0]
    result = {"base": base, "meta": meta or {}, "n_spec": int(spec.size), "n_base": int(bas.size),
              "bits_per_frame": bits_per_frame}
    return conn.execute(insert(S.evidence).values(
        kind=kind, family=family, device=device, name=name, source_ref=source_ref, sha256=sha256,
        generator=generator, build_base=build_base, build_spec=build_spec, tool_version=tool_version,
        stable=stable, result=result, bits_spec=pack(spec), bits_base=pack(bas),
        bit_encoding=f"{ENCODING}:{bits_per_frame}", n_objects=int(spec.size + bas.size),
        commit=commit, created_at=datetime.datetime.now().astimezone())).inserted_primary_key[0]


def record_absence(conn, family, device, name, record, commit, source_ref="absence", generator=None):
    """Evidence of absence (one row per bit SET, never per bit): record = {bits, builds, forced, settings, corpus, static}."""
    for k in ("bits", "builds", "forced", "settings", "corpus", "static"):
        if k not in record:
            db.die(f"absence record lacks {k!r}")
    return conn.execute(insert(S.evidence).values(
        kind="absence", family=family, device=device, name=name, source_ref=source_ref, generator=generator,
        result=record, n_objects=int(record.get("n_objects", 0)), commit=commit,
        created_at=datetime.datetime.now().astimezone())).inserted_primary_key[0]


def record_decode(conn, family, device, name, digest, commit, source_ref, generator=None, n_objects=0,
                  kind="vendor-decode"):
    """A decoder run over a vendor DB / oracle compare / image hit: result = its digest."""
    tiers.check(kind, tiers.EVIDENCE_KINDS, "evidence kind")
    existing = conn.execute(select(S.evidence.c.id).where(and_(
        S.evidence.c.family == family, S.evidence.c.device == device, S.evidence.c.kind == kind,
        S.evidence.c.name == name, S.evidence.c.source_ref == source_ref))).fetchone()
    if existing:
        return existing[0]
    return conn.execute(insert(S.evidence).values(
        kind=kind, family=family, device=device, name=name, source_ref=source_ref, generator=generator,
        result=digest, n_objects=n_objects, commit=commit,
        created_at=datetime.datetime.now().astimezone())).inserted_primary_key[0]


def pairs_from_db(conn, family, device, source_ref):
    """Reconstruct the canonical pairs of one legacy file from its evidence rows (round-trip check)."""
    pairs = {}
    for r in conn.execute(select(S.evidence).where(and_(
            S.evidence.c.family == family, S.evidence.c.device == device,
            S.evidence.c.source_ref == source_ref, S.evidence.c.kind == "specimen-pair"))):
        r = dict(r._mapping)
        pairs[r["name"]] = {"base": r["result"].get("base"), "only_spec": unpack(r["bits_spec"]).tolist(),
                            "only_base": unpack(r["bits_base"]).tolist(), "meta": r["result"].get("meta") or {}}
    return pairs


def import_json_file(conn, path, family, device, bits_per_frame, commit, generator, repo_root):
    """Migrate one legacy pair JSON into evidence rows; returns (n_rows, json_hash, db_hash)."""
    pairs = read_json_pairs(path, bits_per_frame)
    if pairs is None:
        return None
    rel = os.path.relpath(path, repo_root)
    sha = _sha256_file(path)
    for name, p in pairs.items():
        record_specimen(conn, family, device, name, p["base"], p["only_spec"], p["only_base"], p["meta"],
                        rel, generator, commit, bits_per_frame, sha256=sha)
    back = pairs_from_db(conn, family, device, rel)
    return len(pairs), canonical_hash(pairs), canonical_hash(back)


def b64(blob):
    return base64.b64encode(blob or b"").decode()


def unb64(s):
    return base64.b64decode(s) if s else b""
