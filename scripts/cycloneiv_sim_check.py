"""Vendor simulation-library helpers for the Cyclone IV simulation checks (scripts/cycloneiv_lifted_sim_check.py).

vendor_models(names): cut the atoms a post-fit .vo uses from quartus eda/sim_lib/cycloneive_atoms.v
(the whole file does not compile in iverilog: its PLL model) + altera_primitives.v (dffeas).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import toolchain  # noqa: E402

SIMLIB = Path(str(toolchain.quartus_bin())).parent / "eda" / "sim_lib"


def vendor_models(names):
    """Cut the named modules (and the cycloneive_* modules they instantiate) from the vendor file."""
    src = (SIMLIB / "cycloneive_atoms.v").read_text(errors="replace")
    starts = {m.group(1): m.start() for m in re.finditer(r"^module\s+(\w+)", src, re.M)}
    out, seen, todo = [], set(), list(names)
    while todo:
        n = todo.pop()
        if n in seen or n not in starts:
            continue
        seen.add(n)
        body = src[starts[n]:src.index("endmodule", starts[n]) + len("endmodule")]
        out.append(body)
        todo += [m for m in re.findall(r"^\s*(cycloneive_\w+)\s", body, re.M) if m in starts]
    return "`timescale 1 ps/1 ps\n" + "\n\n".join(out) + "\n"
