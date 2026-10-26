#!/usr/bin/env python3.15t
"""Trace why a register of the lifted Verilog is constant: follow its D cone back to the leaves.

For each register named on the command line (or every `stuck at Zero` register of a Diamond
synthesis.log) print the cone's leaves: constants, undriven wires, inputs, blackbox outputs.
A cone whose only leaves are constants / undriven wires explains a stuck register; the first
undriven or hard-IP leaf is the lifter fault to chase (#127).

    python3.15t scripts/trace_stuck.py out/V07.v [--log tmp/rt/new/impl1/synthesis.log] [reg ...]
Log: tmp/logs/trace_stuck.log
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "trace_stuck.log"
_ID = re.compile(r"\\?[A-Za-z_][\w$]*")


def parse(text):
    """-> (driver expr per wire/reg, set of blackbox-driven wires, inputs)."""
    drv, bbox, inputs = {}, set(), set()
    for m in re.finditer(r"^\s*assign\s+(\S+)\s*=\s*(.*?);", text, re.M):
        drv[m.group(1)] = m.group(2)
    for m in re.finditer(r"(?<![<>=!])\b([\w$]+)\s*<=\s*([^;]+);", text):
        if m.group(2).strip() != "1'b0" or m.group(1) not in drv:
            drv[m.group(1)] = m.group(2)     # last non-reset assignment is the D input
    for m in re.finditer(r"^\s*wire\s+(\S+)\s*=\s*(.*?);", text, re.M):
        drv.setdefault(m.group(1), m.group(2))
    for m in re.finditer(r"^\s*input\s+wire\s+(\w+)", text, re.M):
        inputs.add(m.group(1))
    for m in re.finditer(r"^\s*(?:\w+)\s+(?:#\(.*?\)\s*)?\w+\s*\((.*?)\);", text, re.M | re.S):
        for o in re.finditer(r"\.(?:Q|DO\w*|CLK\w*|LOCK|PLLDATO\d|PLLACK|\w+)\(([\w$]+)\)", m.group(1)):
            bbox.add(o.group(1))
    return drv, bbox, inputs


def cone(reg, drv, inputs, limit=20000):
    seen, leaves, todo = set(), {}, [reg]
    while todo and len(seen) < limit:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        if n in ("1'b0", "1'b1", "NC", "GND"):
            leaves[n] = "const"
            continue
        e = drv.get(n)
        if e is None:
            leaves[n] = "input" if n in inputs else "UNDRIVEN"
            continue
        todo += [t for t in _ID.findall(re.sub(r"\d+'[bhd][0-9a-fA-F_]+", " ", e)) if t not in ("NC",)]
    return leaves, len(seen)


def main():
    v = Path(sys.argv[1]).read_text()
    args = sys.argv[2:]
    regs = []
    if "--log" in args:
        i = args.index("--log")
        t = Path(args[i + 1]).read_text(errors="replace")
        regs = sorted(set(re.findall(r"Register (\S+) is stuck at Zero", t)))
        args = args[:i] + args[i + 2:]
    regs += args
    drv, _bbox, inputs = parse(v)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for r in regs:
        key = re.sub(r"_\d{3,}$", "", r)      # LSE appends its instance index
        leaves, n = cone(key, drv, inputs)
        bad = sorted(k for k, t in leaves.items() if t == "UNDRIVEN")
        out.append(f"{r}: cone {n} nets, leaves {len(leaves)}, undriven {bad[:6]}, consts {sum(1 for t in leaves.values() if t == 'const')}")
    text = "\n".join(out)
    print(text)
    LOG.write_text(text + "\n")


if __name__ == "__main__":
    main()
