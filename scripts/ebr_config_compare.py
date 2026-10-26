#!/usr/bin/env python3.15t
"""Compare the EBR blocks of two decoded .config files (original vs Diamond rebuild), issue #127.

Placement and write index differ between builds, so blocks are matched as a multiset of
(EBR0/EBR1/EBR2 tile settings without SITE_ID/WID, INIT digest).  Reports matched / missing /
extra blocks and, for each unmatched block, the differing setting lines.

    python3.15t scripts/ebr_config_compare.py ORIG.config NEW.config
Log: tmp/logs/ebr_config_compare.log
"""
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "ebr_config_compare.log"
_SKIP = ("EBR.SITE_ID", "EBR.WID")


def parse(path):
    """-> list of (signature frozenset, init digest, label)."""
    tiles, cur, bram, mode, idx = {}, None, {}, None, None
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        m = re.match(r"\.tile EBR_R(\d+)C(\d+):(EBR\w*)", s)
        if m:
            cur = (int(m.group(1)), int(m.group(2)), m.group(3))
            tiles[cur] = []
            mode = "tile"
            continue
        if s.startswith(".tile"):
            cur, mode = None, "tile"
            continue
        mb = re.match(r"\.bram_init (\d+)", s)
        if mb:
            idx, mode = int(mb.group(1)), "bram"
            bram[idx] = []
            continue
        if s.startswith(".efb_block"):
            mode = "efb"
            continue
        if mode == "bram" and s:
            bram[idx].extend(s.split())
        elif mode == "tile" and cur and s.startswith(("enum:", "word:", "unknown:")):
            tiles[cur].append(s)
    out = []
    for (r, c, t), lines in sorted(tiles.items()):
        if not t.startswith("EBR1"):
            continue
        sig = []
        for d, kind in ((-1, "E0"), (0, "E1"), (1, "E2")):
            for k, l in tiles.items():
                if k[0] == r and k[1] == c + d:
                    sig += [f"{kind} {x}" for x in l if not x.split()[1].startswith(_SKIP)]
        wid = next((int(x.split()[-1], 2) for x in lines if x.startswith("word: EBR.WID")), 0)
        words = bram.get(wid)
        dig = hashlib.sha1(" ".join(words).encode()).hexdigest()[:10] if words and any(
            int(w, 16) for w in words) else "blank"
        out.append((frozenset(sig), dig, f"R{r}C{c}"))
    return out


def main():
    a, b = parse(sys.argv[1]), parse(sys.argv[2])
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ca, cb = Counter((s, d) for s, d, _ in a), Counter((s, d) for s, d, _ in b)
    both = ca & cb
    rep = [f"EBR blocks: orig {len(a)}, rebuilt {len(b)}, matched {sum(both.values())} "
           f"missing {sum((ca - cb).values())} extra {sum((cb - ca).values())}"]
    miss, extra = ca - cb, cb - ca
    for (s, d), n in miss.items():
        lab = next(l for ss, dd, l in a if (ss, dd) == (s, d))
        rep.append(f"  MISSING {lab} init={d}")
        best = max(extra, key=lambda k: len(k[0] & s), default=None)
        if best:
            rep.append(f"    only in orig: {sorted(s - best[0])}")
            rep.append(f"    only in new : {sorted(best[0] - s)}  init={best[1]}")
    text = "\n".join(rep)
    print(text)
    LOG.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
