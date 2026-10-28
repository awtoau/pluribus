"""Demand analysis: which routing-mux blocks does an image fire, and how much exact
block->wire coverage exists for THEM (not the whole device).

Orders the #141 work by what the target image actually needs: asm gives the fired blocks
exactly; the open work is only each fired block's output wire.

  python3.15t scripts/cycloneiv_image_demand.py --image <path.rbf|.bin>

Log: tmp/logs/cycloneiv_image_demand.log
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))

log = logging.getLogger("image_demand")


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(REPO / "tmp/logs/cycloneiv_image_demand.log")])
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    a = ap.parse_args()

    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    import cycloneiv_asm_decode as ad

    geom = cg.load(cg.die_of("EP4CGX150"))
    plane = cc.cram_plane(Path(a.image).read_bytes(), geom)
    log.info("plane: %d set bits", len(plane))
    dec = ad.Dec()
    gids, grec, block = dec.active(plane)
    log.info("fired groups: %d (distinct blocks %d, distinct source records %d)",
             len(gids), len(set(block.tolist())), len(set(grec.tolist())))

    # demand by record family (id regions; same bucketing as the ddb node table)
    fam = collections.Counter()
    for r in grec.tolist():
        fam[r // 9360 * 9360 if r < 449_321 else 449_321] += 1
    for name in ("phys_map", "li_map"):
        p = REPO / f"lifters/data/cycloneiv_ep4cgx150_{name}.json"
        if p.exists():
            log.info("%s: %d exact entries available (die-wide, keyed per class)",
                     name, len(json.loads(p.read_text())))
    log.info("top source-record regions by demand:")
    for base, n in fam.most_common(15):
        kind = "LE/LEB/LL region" if base < 449_321 else "wire region (H4+)"
        log.info("  base %8d  fired %7d  %s", base, n, kind)


if __name__ == "__main__":
    main()
