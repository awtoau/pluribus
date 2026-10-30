#!/usr/bin/env python3.15t
"""Annotated copy of an existing flat / RTL Verilog file from the annotation table (#165).  Does not touch emit.py / rtl.py.

  python3.15t scripts/cycloneiv_clean_annotate_emit.py IN.v [--out tmp/annotated/IN.v] [--image image]
Per named block (tag V / I / H; U skipped): a header comment of at most 3 lines (id + tag + name, claim, evidence) placed before the first line
that names one of its members; blocks whose members never appear (RTL rewrote the names) get the header in an index at the top.
Members with an alias are renamed everywhere (lc_ / I_lc_ / co_ forms and the m9k_X_Y_* / mac_X_Y_* bus names follow the alias).
Unnamed logic stays flat under physical ids.  Writes OUT, OUT.names.tsv (alias <-> physical) and OUT.blocks.tsv (block -> line).
Local output (commercial RE).  Log: tmp/logs/cycloneiv_clean_annotate.log.
"""
import argparse
import logging
import os
import re
import sys
import time

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_annotate as A  # noqa: E402

log = logging.getLogger("annotate_emit")
TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
BUS = re.compile(r"^((?:m9k|mac)_\d+_\d+)(_[a-z]+)?$")
CLAIM_MAX = 150


def header(b):
    """<= 3 comment lines."""
    claim = b["claim"] if len(b["claim"]) <= CLAIM_MAX else b["claim"][:CLAIM_MAX - 3] + "..."
    return [f"// [{b['block_id']} {b['tag']}] {b['name']} ({b['n_members']} members)", f"// {claim}", f"// evidence: {b['evidence']}"]


class Resolver:
    def __init__(self, blocks, mem):
        self.owner, self.alias, self.tok = {}, {}, {}
        for b in blocks:
            if b["tag"] == "U":
                continue
            for m in mem[b["block_id"]]:
                o = m["obj_id"]
                self.owner[o] = b["block_id"]
                if m["alias"]:
                    self.alias[o] = m["alias"]
                self.tok[o] = (o, "", "")
                if o.startswith("lc_"):
                    self.tok["I_" + o] = (o, "I_", "")
                    self.tok["co_" + o[3:]] = (o, "co_", "")

    def __call__(self, t):
        """token -> (physical, prefix, suffix) or None."""
        v = self.tok.get(t)
        if v or t[:4] not in ("m9k_", "mac_"):
            return v
        m = BUS.match(t)
        return (m.group(1), "", m.group(2) or "") if m and m.group(1) in self.owner else None

    def rename(self, line):
        def f(m):
            r = self(m.group(0))
            a = r and self.alias.get(r[0])
            return r[1] + a + r[2] if a else m.group(0)
        return TOK.sub(f, line)


def anchors(path, res, want):
    """block_id -> first line number (0-based) naming a member."""
    found = {}
    with open(path, errors="replace") as f:
        for n, line in enumerate(f):
            for t in TOK.findall(line):
                r = res(t)
                if r:
                    b = res.owner[r[0]]
                    if b not in found:
                        found[b] = n
            if len(found) == want:
                break
    return found


def annotate(path, out, blocks, mem):
    res = Resolver(blocks, mem)
    named = [b for b in blocks if b["tag"] != "U"]
    by_id = {b["block_id"]: b for b in named}
    found = anchors(path, res, len(named))
    at = {}
    for bid, n in sorted(found.items(), key=lambda kv: (kv[1], kv[0])):
        at.setdefault(n, []).append(bid)
    loose = [b for b in named if b["block_id"] not in found]
    renames = 0
    with open(path, errors="replace") as f, open(out, "w") as w:
        if loose:
            w.write(f"// annotation index: {len(loose)} named blocks whose members do not appear by physical id in this file\n")
            for b in loose:
                w.write("\n".join(header(b)) + "\n")
        for n, line in enumerate(f):
            for bid in at.get(n, ()):
                w.write("\n".join(header(by_id[bid])) + "\n")
            if res.alias:
                new = res.rename(line)
                renames += new != line
                line = new
            w.write(line)
    with open(out + ".names.tsv", "w") as w:
        w.write("alias\tphysical\n")
        for o, a in sorted(res.alias.items(), key=lambda kv: kv[1]):
            w.write(f"{a}\t{o}\n")
    with open(out + ".blocks.tsv", "w") as w:
        w.write("block\ttag\tname\tline\n")
        for b in named:
            w.write(f"{b['block_id']}\t{b['tag']}\t{b['name']}\t{found[b['block_id']] + 1 if b['block_id'] in found else 'index'}\n")
    return dict(named_blocks=len(named), anchored=len(found), index_only=len(loose), aliases=len(res.alias), renamed_lines=renames)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out")
    ap.add_argument("--image", default="image")
    a = ap.parse_args()
    out = a.out or os.path.join(REPO, "tmp", "annotated", os.path.basename(a.input))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.makedirs(os.path.dirname(A.LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(A.LOG)])
    t0 = time.time()
    blocks, mem = A.load_all(A.get_engine(), a.image)
    rep = annotate(a.input, out, blocks, mem)
    log.info("annotated %s -> %s in %.1fs: %s", a.input, out, time.time() - t0, rep)


if __name__ == "__main__":
    main()
