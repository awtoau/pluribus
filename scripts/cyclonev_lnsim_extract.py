#!/usr/bin/env python3.15t
"""Extract the plain vendor RAM/MLAB simulation modules the sim gate needs (cyclonev_atoms.v + altera_lnsim.sv).

- Whole-file parse of altera_lnsim.sv fails in iverilog -g2012 (line 32252, unrelated modules); 30k+ lines.
- Roots + their transitive module dependencies are copied verbatim; nothing is edited.
- Output: tmp/simcheck/lnsim_extract.sv (derived; rebuilt whenever missing or the roots change).
Usage: python3.15t scripts/cyclonev_lnsim_extract.py [root ...]
Log: tmp/logs/cyclonev_lnsim_extract.log
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SIMLIB = Path("/mnt/2tb/opt/altera/quartus-25.1/quartus/eda/sim_lib")
SRCS = [SIMLIB / "cyclonev_atoms.v", SIMLIB / "altera_lnsim.sv"]
OUT = REPO / "tmp" / "simcheck" / "lnsim_extract.sv"
LOG = REPO / "tmp" / "logs" / "cyclonev_lnsim_extract.log"
DEFAULT_ROOTS = ["cyclonev_ram_block", "cyclonev_mlab_cell"]


def modules(text):
    """{name: (start, end)} for every `module ... endmodule` pair (primitives included)."""
    out = {}
    for m in re.finditer(r"^\s*(module|primitive|package)\s+(\w+)", text, re.M):
        end = re.compile(r"^\s*end" + m.group(1), re.M).search(text, m.end())
        out[m.group(2)] = (m.start(), end.end())
    return out


def extract(roots=None, out=OUT, log=print):
    roots = roots or DEFAULT_ROOTS
    text = "\n".join(p.read_text() for p in SRCS)     # atoms first: a cell wraps a generic_* core in lnsim
    mods = modules(text)
    need, todo = [], list(roots)
    while todo:
        n = todo.pop()
        if n in need:
            continue
        if n not in mods:
            raise SystemExit(f"module {n} not in {[p.name for p in SRCS]}")
        need.append(n)
        body = text[mods[n][0]:mods[n][1]]
        for dep in mods:
            if dep != n and re.search(rf"\b{re.escape(dep)}\b", body):
                todo.append(dep)
        for pkg in re.findall(r"import\s+(\w+)::", body):
            todo.append(pkg)
    # packages first (import order), then `define lines the extracted text uses
    pk = [n for n in need if re.match(r"\s*package", text[mods[n][0]:mods[n][1]])]
    body = "\n".join(text[mods[n][0]:mods[n][1]] for n in pk + sorted(set(need) - set(pk)))
    defs = {m.group(1): m.group(0) for m in re.finditer(r"^`define (\w+)[^\n]*", text, re.M)}
    used = [defs[k] for k in sorted(defs) if re.search(r"`" + k + r"\b", body)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("`timescale 1 ps / 1 ps\n" + "\n".join(used) + "\n" + body + "\n")
    log(f"extracted {len(need)} modules from {[p.name for p in SRCS]}: {' '.join(sorted(need))}")
    return out


if __name__ == "__main__":
    LOG.parent.mkdir(parents=True, exist_ok=True)

    def lg(msg):
        print(msg)
        with open(LOG, "a") as fh:
            fh.write(msg + "\n")
    extract(sys.argv[1:] or None, log=lg)
