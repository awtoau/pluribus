#!/usr/bin/env python3.15t
"""EP4CGX150 cells set in ANY held bitstream -> dense bitmap (databases/cycloneiv/ever_set.npy, packed bits).

  python3.15t scripts/cycloneiv_ever_set.py [--extra IMAGE ...]
Designs = every corpus/cycloneiv build with a bitstream.rbf on a GX150 plane (6191 frames x 6368) + the third-party
.rbf under sources/cycloneiv-corpus + --extra images.
The inventory reads the bitmap: unknown cells set in none = "projected unused" (triage sub-line of unknown, not a claim).
Threads only, one memory lease per job.  Log tmp/logs/cycloneiv_ever_set.log.  Issue #141.
"""
import argparse
import hashlib
import logging
import sys
import tomllib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
log = logging.getLogger("ever_set")
NFR, NV = 6191, 6368
OUT = REPO / "databases" / "cycloneiv" / "ever_set.npy"


def candidates(extra):
    out = []
    for d in sorted((REPO / "corpus" / "cycloneiv").iterdir()):
        rbf = d / "bitstream.rbf"
        if rbf.exists():
            try:
                dev = tomllib.loads((d / "design.toml").read_text()).get("device", "")
            except Exception:
                continue
            if dev.startswith("EP4CGX150"):
                out.append(("build", d.name, rbf))
    for p in sorted((REPO / "sources" / "cycloneiv-corpus").glob("*/*.rbf")):
        out.append(("image", p.parent.name + "/" + p.name, p))
    for e in extra:
        out.append(("image", Path(e).name, Path(e)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_ever_set.log"), logging.StreamHandler()])
    import build_pool
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of("EP4CGX150"))
    seen = np.zeros(NFR * NV, np.uint8)
    cands = candidates(a.extra)
    log.info("%d candidate bitstreams", len(cands))

    def one(c):
        kind, name, path = c
        try:
            plane = cc.cram_plane(path.read_bytes(), g)
        except Exception as e:      # other device / not a Cyclone IV stream
            return kind, name, None, str(e)[:60]
        if plane.shape != (NFR, NV):
            return kind, name, None, f"plane {plane.shape}"
        seen[plane.keys] = 1        # idempotent write of 1: threads may race harmlessly
        return kind, name, len(plane.keys), ""

    res = build_pool.map_adaptive(one, cands, per_job_gb=1.0)
    used = [(k, n) for k, n, cnt, why in res if cnt is not None]
    skipped = [(k, n, why) for k, n, cnt, why in res if cnt is None]
    n_img = sum(k == "image" for k, _ in used)
    bm = np.packbits(seen.astype(bool))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.save(OUT, bm)
    digest = hashlib.sha256(bm.tobytes()).hexdigest()
    meta = {"n_designs": len(used), "n_builds": len(used) - n_img, "n_images": n_img, "cells_set_in_some": int(seen.sum()),
            "cells_set_in_none": int(NFR * NV - seen.sum()), "bitmap_sha256": digest,
            "designs_sha256": hashlib.sha256("\n".join(sorted(f"{k}:{n}" for k, n in used)).encode()).hexdigest(),
            "skipped": len(skipped), "skipped_examples": skipped[:5]}
    log.info("%s", meta)
    import db
    import schema as S
    from provenance import evidence_io as E
    S.init()
    with db.engine().begin() as conn:
        from sqlalchemy import delete
        conn.execute(delete(S.evidence).where(S.evidence.c.name == "ever-set-bitmap"))
        E.ensure_family(conn, "cycloneiv")
        E.record_decode(conn, "cycloneiv", "EP4CGX150", "ever-set-bitmap", {"file": meta}, E.git_head(REPO),
                        "scripts/cycloneiv_ever_set.py", generator="scripts/cycloneiv_ever_set.py", kind="derived-table",
                        n_objects=meta["cells_set_in_none"])


if __name__ == "__main__":
    main()
