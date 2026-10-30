#!/usr/bin/env python3.15t
"""Generic ROM-word disassembler / field statistics for candidate microcode tables (#165).  No image data in this file.

  python3.15t scripts/cycloneiv_clean_microcode_disasm.py --words W.hex --format F.json [--base 0] [--start A --end B] [--stats] [--list]
  python3.15t scripts/cycloneiv_clean_microcode_disasm.py --selftest
Words file: one hex word per line or whitespace separated (address = index + --base).  Format JSON:
  {"width": 18, "fields": [{"name": "op", "hi": 15, "lo": 12}, ...], "opfield": "op",
   "ops": {"1": {"mn": "SET", "show": ["a", "b"]}, ...}, "target": ["tgt"], "source": "where the format came from"}
  ops key = decimal or 0x value of the op field; unlisted op values print as OP<n> with all fields.
--stats: constant fields, per-field value histograms, op histogram, and for each `target` field the fraction of values that land inside the
  program span and on a word that follows a different op (entry-point plausibility); no ISA is assumed.
Log: tmp/logs/cycloneiv_clean_microcode_disasm.log
"""
import argparse
import collections
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_microcode_disasm.log")
log = logging.getLogger("microcode_disasm")


def load_words(path):
    return [int(t, 16) for t in open(path).read().split()]


def split(word, fmt):
    return {f["name"]: (word >> f["lo"]) & ((1 << (f["hi"] - f["lo"] + 1)) - 1) for f in fmt["fields"]}


def pack(vals, fmt):
    w = 0
    for f in fmt["fields"]:
        w |= (vals.get(f["name"], 0) & ((1 << (f["hi"] - f["lo"] + 1)) - 1)) << f["lo"]
    return w


def _op_entry(fmt, v):
    ops = fmt.get("ops", {})
    for k, e in ops.items():
        if int(k, 0) == v:
            return e
    return None


def disasm_word(word, fmt):
    fv = split(word, fmt)
    of = fmt.get("opfield")
    if not of:
        return " ".join(f"{k}={v:#x}" for k, v in fv.items())
    e = _op_entry(fmt, fv[of])
    if e is None:
        return f"OP{fv[of]:<2d} " + " ".join(f"{k}={v:#x}" for k, v in fv.items() if k != of)
    return f"{e['mn']:<6s}" + " ".join(f"{k}={fv[k]:#x}" for k in e.get("show", [k for k in fv if k != of]))


def listing(words, fmt, base=0, start=None, end=None):
    out = []
    w = fmt.get("width", 18)
    nd = (w + 3) // 4
    for i, x in enumerate(words):
        a = base + i
        if (start is not None and a < start) or (end is not None and a > end):
            continue
        out.append(f"{a:04x}  {x:0{nd}x}  {disasm_word(x, fmt)}")
    return out


def stats(words, fmt, base=0, start=None, end=None):
    sel = [(base + i, x) for i, x in enumerate(words) if (start is None or base + i >= start) and (end is None or base + i <= end)]
    res = {"words": len(sel), "span": [sel[0][0], sel[-1][0]] if sel else None, "fields": {}, "targets": {}}
    for f in fmt["fields"]:
        c = collections.Counter(split(x, fmt)[f["name"]] for _, x in sel)
        res["fields"][f["name"]] = {"distinct": len(c), "constant": len(c) == 1, "top": c.most_common(8)}
    of = fmt.get("opfield")
    if of:
        res["ops"] = sorted(collections.Counter(split(x, fmt)[of] for _, x in sel).items())
    addrs = {a for a, _ in sel}
    prev_op = {}
    if of:
        for k, (a, x) in enumerate(sel[1:], 1):
            prev_op[a] = split(sel[k - 1][1], fmt)[of]
    for tf in fmt.get("target", []):
        vals = [split(x, fmt)[tf] for _, x in sel]
        inside = [v for v in vals if v in addrs]
        res["targets"][tf] = {"n": len(vals), "inside_span": len(inside), "distinct": len(set(vals))}
    return res


def selftest():
    fmt = {"width": 12, "opfield": "op", "target": ["tgt"],
           "fields": [{"name": "op", "hi": 11, "lo": 8}, {"name": "tgt", "hi": 7, "lo": 0}, {"name": "cnt", "hi": 7, "lo": 0}],
           "ops": {"0": {"mn": "NOP", "show": []}, "1": {"mn": "LOOP", "show": ["cnt"]}, "2": {"mn": "JMP", "show": ["tgt"]}}}
    prog = [(1, {"cnt": 3}), (0, {}), (2, {"tgt": 0})]
    words = [pack(dict(v, op=o), fmt) for o, v in prog]
    assert words == [0x103, 0x000, 0x200], words
    lst = listing(words, fmt)
    assert lst[0].split()[2] == "LOOP" and "cnt=0x3" in lst[0] and lst[2].split()[2] == "JMP" and "tgt=0x0" in lst[2], lst
    st = stats(words, fmt)
    assert st["ops"] == [(0, 1), (1, 1), (2, 1)] and st["targets"]["tgt"]["inside_span"] == 2, st
    assert not st["fields"]["op"]["constant"]
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words")
    ap.add_argument("--format")
    ap.add_argument("--base", type=int, default=0)
    ap.add_argument("--start", type=lambda s: int(s, 0))
    ap.add_argument("--end", type=lambda s: int(s, 0))
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    if a.selftest:
        return selftest()
    if not (a.words and a.format):
        raise SystemExit("--words and --format required")
    words, fmt = load_words(a.words), json.load(open(a.format))
    if a.stats:
        log.info(json.dumps(stats(words, fmt, a.base, a.start, a.end), indent=1))
    if a.list or not a.stats:
        for line in listing(words, fmt, a.base, a.start, a.end):
            log.info(line)


if __name__ == "__main__":
    sys.exit(main())
