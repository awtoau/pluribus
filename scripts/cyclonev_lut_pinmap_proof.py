#!/usr/bin/env python3
"""Ablation proof of the Quartus lut_mask <-> Mistral LUT_MASK mapping over the corpus.

Counts how many placed lcells match under the model in cyclonev_postfit_compare.py,
and under each single-feature ablation (an ablation that still matches everything
would mean that feature is unproven).  Needs a built corpus DB.

Usage: python3.15t scripts/cyclonev_lut_pinmap_proof.py
Log:   tmp/logs/cyclonev_lut_pinmap_proof.log
"""
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_postfit_compare as cmp  # noqa: E402  (sets the corpus DB path)
import db  # noqa: E402
import schema  # noqa: E402
from sqlalchemy import select  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_lut_pinmap_proof.log"


def check(q, raw, half, mode, used, mlab, abl):
    """cmp.lut_matches with one feature ablated."""
    if abl == "halves_swapped":
        half = "B" if half == "T" else "T"
    for v in range(64):
        if any((v >> k) & 1 for k, p in enumerate(cmp.PINS) if p not in used) \
                and abl != "unused_not_zero":
            continue
        bit = {p: (v >> k) & 1 for k, p in enumerate(cmp.PINS)}
        if half == "B" and abl != "no_B_cd_swap":
            bit["c"], bit["d"] = bit["d"], bit["c"]
        if mode in ("E_0", "E_1") and abl != "mode_ignored":
            x5 = int(mode[-1])
        elif mode in ("D_E", "D_F", "C_E", "C_F", "E_0", "E_1"):
            x5 = bit["e"]
        else:
            return None
        sw = x5 == 1 and abl != "no_hi_cd_swap"
        j2, j3 = (bit["d"], bit["c"]) if sw else (bit["c"], bit["d"])
        j = bit["a"] | bit["b"] << 1 | j2 << 2 | j3 << 3 | bit["f"] << 4 | x5 << 5
        if mlab and abl != "no_mlab_perm":
            j = cmp.MLAB_PERM[j]
        inv = abl != "no_output_inversion"
        if (((q >> v) & 1) == ((raw >> j) & 1)) == inv:
            return False
    return True


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    abls = ["model", "no_output_inversion", "halves_swapped", "no_B_cd_swap",
            "no_hi_cd_swap", "no_mlab_perm", "mode_ignored", "unused_not_zero"]
    res = {a: collections.Counter() for a in abls}
    with db.engine().connect() as conn:
        builds = list(conn.execute(select(schema.corpus_builds)
                                   .where(schema.corpus_builds.c.status == "ok")))
    n_dense = 0
    for b in builds:
        atoms, by_atom, _ = cmp.load_quartus(b.id)
        pc = cmp.CycloneVLift("5CEBA4U19C8").parse_config(str(REPO / b.out_dir / "decomp.bt"))
        for a in atoms.values():
            if a["type"] != "cyclonev_lcell_comb":
                continue
            blk = "MLAB" if a["loc_kind"] == "MLABCELL" else "LAB"
            x, y, alm, half = a["x"], a["y"], a["n"] // 6, cmp.HALF[(a["n"] // 3) % 2]
            kv = pc.settings.get((blk, x, y), {})
            raw_s = kv.get(("LUT_MASK", alm))
            if raw_s is None:
                continue
            used = {c["port"][4] for c in by_atom[a["id"]]
                    if c["port"].startswith("data") and c["port"] != "datag" and c["net"]}
            n_dense += len(used) == 6
            mode = kv.get((f"{half}MODE", alm)) or cmp.DEFAULT_MODE[half]
            q = int(a["params"]["lut_mask"].split("'h")[1], 16)
            hi, lo = raw_s.split(".")
            raw = int(hi, 16) << 32 | int(lo, 16)
            arith = "arith" if kv.get(("ARITH_SEL", alm)) == "ADDER" else "logic"
            for ab in abls:
                r = check(q, raw, half, mode, used, blk == "MLAB", ab)
                res[ab][(arith, {True: "match", False: "mismatch", None: "unmodelled"}[r])] += 1
    lines = [f"lcells with a LUT_MASK in the bitstream; {n_dense} use all 6 inputs"]
    for ab in abls:
        lines.append(f"{ab:22s} " + " ".join(f"{k[0]}.{k[1]}={v}" for k, v in sorted(res[ab].items())))
    LOG.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
