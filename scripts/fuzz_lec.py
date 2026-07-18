#!/usr/bin/env python3
"""#37 LEC completeness harness (first slice) — recovered.v vs fuzz.v.

For every diamond-fuzz target this:

  1. CATEGORISES the source (`diamond-fuzz/targets/<t>/fuzz.v`) as
       - `logic`   : only LUT*/FF/CCU2D primitives (or pure RTL), and
       - `hard-ip` : instantiates a hard primitive (PLL/EBR/EFB/IO/OSC/…),
     which per #49 is compared by config enums, not by logic equivalence.

  2. Each `logic` target is first PRE-CLASSIFIED with fast DB-only checks
     (no emit, no yosys) — so the classification histogram always covers the
     whole corpus cheaply.  Targets that survive every check (all data pads
     resolved, directions agree) become equiv-CANDIDATES.

  3. Up to `--limit` candidates (--limit 0 = all) then get the real, expensive
     proof: emit the recovered structural Verilog (`verilog.py --top fuzz`)
     and run a yosys sequential-equivalence proof (equiv_make + equiv_induct
     + equiv_status, a SAT-backed induction) against the original `fuzz.v`.

     The two designs name their top-level ports differently — the source by
     signal name (clk/d/…), the recovered by physical pad label — so the
     port correspondence is rebuilt through the PIN NUMBER, the common key:
         source port --(fuzz.lpf LOCATE)--> pin  <--(pad_map)-- recovered pad
     The recovered ports (read from the EMITTED .v, since verilog.py sanitises
     labels) are renamed to the source names before equiv_make; unmatched
     resolved pads (e.g. a clock pad the fabric never wired to the FF) are
     dropped, and the source clock is bound to the recovered FF clock.

  4. Every non-pass is triaged into a specific root cause (the DEFECT MAP):
       edge-cib-unresolved-io  #57  recovered dropped the design's I/O pads
       db-gap-direction     #29/#57 pad resolved but wrong direction/enum
       hard-ip                 #49  logic LEC inapplicable (enum-compare)
       unsupported-primitive        source prim has no LEC cell model yet
       port-map-failed              correspondence unbuildable (not loaded, …)
       lifter-bug                   equiv RAN and diverged — real mismatch
       equiv-error                  yosys errored during the proof
       equiv-not-run                candidate deferred past --limit

     A control proof (source-vs-source) guards every real verdict: if the
     control does not prove EQUIVALENT the flow itself is suspect and the
     target's verdict is downgraded to `equiv-error` rather than trusted.

Outputs:
    tmp/fuzz_lec_defectmap.tsv   target, class, lec_result, root_cause, detail
    tmp/fuzz_lec.log             full run log
    stdout                       category counts + result/root-cause histogram

Usage:
    python3.15t scripts/fuzz_lec.py --db tmp/fuzz_rebuild.db
    python3.15t scripts/fuzz_lec.py --db tmp/fuzz_rebuild.db --limit 40
    python3.15t scripts/fuzz_lec.py --db tmp/fuzz_rebuild.db --targets 'lut4_*'

This is a FIRST SLICE: the edge-CIB decode gap (#57) leaves almost every
logic target with unresolved input pads, so most land in
`edge-cib-unresolved-io` — that attribution IS the deliverable, not a
failure of the harness.  See the closing summary for what the next slice
needs to widen the set that reaches a real equiv verdict.
"""

import argparse
import fnmatch
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS_DIR = REPO / "diamond-fuzz" / "targets"
PY = os.environ.get("PLURIBUS_PYTHON", "python3.15t")
LABEL_PREFIX = "FUZZ_"

# ── categorisation ───────────────────────────────────────────────────────
# Fabric logic primitives — a target using ONLY these (or pure RTL) is
# `logic`; anything else is `hard-ip` (PLL/EBR/EFB/IO/OSC/DCC/… — #49).
LOGIC_PRIMS = {f"LUT{i}" for i in range(1, 7)} | {
    "FD1S3AX", "FD1S3BX", "FD1S3DX", "FD1S3IX", "FD1S3JX",
    "FD1P3AX", "FD1P3BX", "FD1P3DX", "FD1P3IX", "FD1P3JX",
    "CCU2D",
}
# Source primitives we have an exact LEC cell model for (below).  A `logic`
# target that instantiates a logic primitive OUTSIDE this set is reported as
# `unsupported-primitive` rather than risking a false verdict from a guessed
# model.  Pure-RTL targets (no instantiation) need no model.
MODELLED_PRIMS = {f"LUT{i}" for i in range(1, 7)} | {"FD1S3AX"}

_VERILOG_KEYWORDS = {
    "BLOCK", "IOBUF", "LOCATE", "FREQUENCY", "PORT", "COMP", "SITE",
}
_INST_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{1,})\s*(?:#\s*\(|[A-Za-z_])")
_LOCATE_RE = re.compile(r'LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"(\d+)"')
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b(?:\s+(?:wire|reg|logic))?"
    r"(?:\s*\[[^\]]*\])?\s*(\w+)")
_EDGE_RE = re.compile(r"\b(?:pos|neg)edge\s+(\w+)")
_PROVEN_RE = re.compile(r"(\d+)\s+are proven and\s+(\d+)\s+are unproven")
# recovered.v port lines: `output wire NAME,  // pin NN net ...`  and the
# ghost-clock line `input  wire NAME   // clock — …`.  The emitted identifier
# (NAME) is authoritative for yosys — pad_map.label may differ because
# verilog.py sanitises characters like '?' out of the port name.
_REC_PAD_RE = re.compile(
    r"^\s*(input|output|inout)\s+wire\s+(\w+)\s*,?\s*//\s*pin\s+(\d+)\b")
_REC_CLK_RE = re.compile(r"^\s*input\s+wire\s+(\w+)\s+//\s*clock\b")


def parse_recovered_ports(vtext):
    """Ports actually emitted in a recovered.v.

    Returns (pads, clocks): pads = {pin: {'name','dir'}} (dir in
    input/output/inout), clocks = [ghost-clock port names].
    """
    pads, clocks = {}, []
    for line in vtext.splitlines():
        m = _REC_PAD_RE.match(line)
        if m:
            pads[int(m.group(3))] = {"name": m.group(2), "dir": m.group(1)}
            continue
        m = _REC_CLK_RE.match(line)
        if m:
            clocks.append(m.group(1))
    return pads, clocks


# ── source parsing ───────────────────────────────────────────────────────
def parse_prims(vtext):
    """Uppercase module instantiations in a fuzz.v (the primitive set)."""
    prims = set()
    for line in vtext.splitlines():
        m = _INST_RE.match(line)
        if m and m.group(1) not in _VERILOG_KEYWORDS:
            prims.add(m.group(1))
    return prims


def classify_source(prims):
    """('logic'|'hard-ip', sorted list of hard primitives)."""
    hard = sorted(prims - LOGIC_PRIMS)
    return ("hard-ip" if hard else "logic"), hard


def parse_module_ports(vtext, top="fuzz"):
    """{port_name: 'input'|'output'|'inout'} from the ANSI module header."""
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\s*\((.*?)\)\s*;",
                  vtext, re.S)
    ports = {}
    if not m:
        return ports
    for frag in m.group(1).split(","):
        pm = _PORT_DECL_RE.search(frag)
        if pm:
            ports[pm.group(2)] = pm.group(1)
    return ports


def parse_clocks(vtext):
    """Signals used on a clock edge — the source's clock ports."""
    return set(_EDGE_RE.findall(vtext))


def parse_lpf_pins(lpf_path):
    """{port_name: pin_number} from a fuzz.lpf LOCATE COMP … SITE …."""
    pins = {}
    if lpf_path.is_file():
        for name, pin in _LOCATE_RE.findall(lpf_path.read_text()):
            pins[name] = int(pin)
    return pins


# ── recovered-side (DB) queries ──────────────────────────────────────────
def recovered_logic_summary(con, bid):
    """Compact recovered-fabric description for a FAIL defect-map detail."""
    luts = [f"{fn}" for (fn,) in con.execute(
        "SELECT fn FROM luts WHERE bitstream=? AND fn IS NOT NULL", (bid,))]
    nff = con.execute("SELECT count(*) FROM ffs WHERE bitstream=?",
                      (bid,)).fetchone()[0]
    parts = []
    if luts:
        parts.append("LUT fn=" + "|".join(sorted(set(luts))))
    parts.append(f"{nff} FF")
    return "; ".join(parts)


def resolved_pads(con, bid):
    """{pin: {'label','direction','net_in','net_out'}} for resolved pads."""
    out = {}
    for pin, label, direction, ni, no in con.execute(
            "SELECT pin,label,direction,net_in,net_out FROM pad_map "
            "WHERE bitstream=? AND (net_in IS NOT NULL OR net_out IS NOT NULL)",
            (bid,)):
        out[pin] = {"label": label, "direction": direction,
                    "net_in": ni, "net_out": no}
    return out


# ── yosys equivalence ────────────────────────────────────────────────────
CELLS_LIB = r"""// Minimal Lattice primitive models for LEC (source/gold side only).
// LUTs use the exact Lattice INIT convention: A is the LSB of the address,
// Z = init[{D,C,B,A}].  GSR (global set/reset) is not modelled.
module LUT1(input A, output Z); parameter [1:0]  init=0; assign Z=init[A]; endmodule
module LUT2(input A,B, output Z); parameter [3:0]  init=0; assign Z=init[{B,A}]; endmodule
module LUT3(input A,B,C, output Z); parameter [7:0]  init=0; assign Z=init[{C,B,A}]; endmodule
module LUT4(input A,B,C,D, output Z); parameter [15:0] init=0; assign Z=init[{D,C,B,A}]; endmodule
module LUT5(input A,B,C,D,E, output Z); parameter [31:0] init=0; assign Z=init[{E,D,C,B,A}]; endmodule
module LUT6(input A,B,C,D,E,F, output Z); parameter [63:0] init=0; assign Z=init[{F,E,D,C,B,A}]; endmodule
module FD1S3AX(input D, CK, output reg Q); always @(posedge CK) Q<=D; endmodule
"""


def _write_cells_lib(tmp):
    path = tmp / "fuzz_lec_cells.v"
    path.write_text(CELLS_LIB)
    return path


def _yosys_script(gold_files, gate_file, renames, deletes, top="fuzz"):
    """equiv_induct of recovered (gate) vs source (gold).

    The gate is read FIRST so its port renames run on a fresh selection
    (a selection does not survive `design -stash`).  Renamed OLD names must
    reference the recovered port identifiers; deletes drop resolved pads that
    no source port maps to (e.g. a clock pad the fabric never wired to the FF).
    """
    s = [f"read_verilog -sv {gate_file}",
         f"hierarchy -top {top}", "proc"]
    if renames:
        s.append(f"select -module {top}")
        s += [f"rename {old} {new}" for old, new in renames]
        s.append("select -clear")
    s += [f"delete {top}/w:{w}" for w in deletes]
    s += ["flatten", "opt_clean", f"rename {top} gate", "design -stash gate"]
    s += ["read_verilog -sv " + " ".join(str(f) for f in gold_files),
          f"hierarchy -top {top}", "proc", "flatten", "opt_clean",
          f"rename {top} gold", "design -stash gold"]
    s += ["design -copy-from gold -as gold gold",
          "design -copy-from gate -as gate gate",
          "equiv_make gold gate equiv", "hierarchy -top equiv",
          "equiv_induct", "equiv_status"]
    return "; ".join(s)


def run_equiv(gold_files, gate_file, renames, deletes, top="fuzz"):
    """Return (verdict, proven, unproven, log_text).

    verdict: 'PASS' | 'FAIL' | 'ERROR'.
    """
    script = _yosys_script(gold_files, gate_file, renames, deletes, top)
    res = subprocess.run(["yosys", "-p", script],
                         capture_output=True, text=True, cwd=str(REPO))
    log = res.stdout + res.stderr
    proven = unproven = None
    for ln in log.splitlines():
        m = _PROVEN_RE.search(ln)
        if m:
            proven, unproven = int(m.group(1)), int(m.group(2))
    if res.returncode != 0 or proven is None:
        return "ERROR", proven, unproven, log
    if unproven == 0 and proven > 0:
        return "PASS", proven, unproven, log
    if unproven == 0 and proven == 0:
        # nothing to prove (no shared outputs) — treat as inconclusive error
        return "ERROR", proven, unproven, log
    return "FAIL", proven, unproven, log


# ── correspondence + per-target LEC ──────────────────────────────────────
class Result:
    __slots__ = ("target", "cls", "lec", "root", "detail")

    def __init__(self, target, cls, lec, root, detail):
        self.target, self.cls, self.lec = target, cls, lec
        self.root, self.detail = root, detail

    def row(self):
        return "\t".join((self.target, self.cls, self.lec,
                          self.root, self.detail))


class Candidate:
    """A logic target that passed every fast DB pre-check — all data pads
    resolved with matching direction — and is worth a real yosys equiv."""
    __slots__ = ("target", "label", "bid", "data_ports", "pins", "src_clocks")

    def __init__(self, target, label, bid, data_ports, pins, src_clocks):
        self.target, self.label, self.bid = target, label, bid
        self.data_ports, self.pins, self.src_clocks = data_ports, pins, src_clocks


def pre_classify(target, con, lab2id):
    """Fast DB-only triage (NO verilog.py emit, NO yosys).

    Returns (Result, None) for a target already decided by structural checks
    (unsupported primitive / not loaded / #57 unresolved IO / #29 direction),
    or (None, Candidate) for one that warrants a real equiv proof.
    """
    tdir = TARGETS_DIR / target
    vtext = (tdir / "fuzz.v").read_text()
    ports = parse_module_ports(vtext)
    clocks = parse_clocks(vtext)
    prims = parse_prims(vtext)

    unmodelled = sorted((prims & LOGIC_PRIMS) - MODELLED_PRIMS)
    if unmodelled:
        return Result(target, "logic", "SKIP", "unsupported-primitive",
                      "source prim(s) without a LEC model: "
                      + ",".join(unmodelled)), None

    label = LABEL_PREFIX + target
    bid = lab2id.get(label)
    if bid is None:
        return Result(target, "logic", "ERROR", "port-map-failed",
                      "no DB label (target not loaded)"), None

    pins = parse_lpf_pins(tdir / "fuzz.lpf")
    if not pins or not ports:
        return Result(target, "logic", "ERROR", "port-map-failed",
                      "missing fuzz.lpf pins or module ports"), None

    pads = resolved_pads(con, bid)
    data_ports = {p: d for p, d in ports.items() if p not in clocks}
    src_clocks = [p for p in ports if p in clocks]

    # 1) every data port's pin must be resolved (the #57 wall)
    unresolved = sorted(p for p in data_ports if pins.get(p) not in pads)
    if unresolved:
        miss = ", ".join(f"{p}@pin{pins.get(p)}" for p in unresolved)
        return Result(target, "logic", "BLOCKED", "edge-cib-unresolved-io",
                      f"{len(unresolved)}/{len(data_ports)} data pad(s) "
                      f"unresolved: {miss}"), None

    # 2) direction agreement on the resolved data pads
    dir_bad = []
    for p, want in data_ports.items():
        pad = pads[pins[p]]
        # source output -> recovered pad must drive out (net_out set);
        # source input  -> recovered pad must accept in (net_in set)
        ok = (pad["direction"] == "out" if want == "output"
              else pad["direction"] in ("in", "bidir"))
        if not ok:
            dir_bad.append(f"{p}:{want}!=pad:{pad['direction']}")
    if dir_bad:
        return Result(target, "logic", "BLOCKED", "db-gap-direction",
                      "direction mismatch: " + ", ".join(dir_bad)), None

    if len(src_clocks) > 1:
        return Result(target, "logic", "ERROR", "port-map-failed",
                      f"{len(src_clocks)} source clocks (expect <=1)"), None

    return None, Candidate(target, label, bid, data_ports, pins, src_clocks)


def run_candidate(cand, con, tmp, cells_lib, log):
    """Emit recovered.v and run the real yosys equiv proof -> Result."""
    target, label, bid = cand.target, cand.label, cand.bid
    data_ports, pins, src_clocks = cand.data_ports, cand.pins, cand.src_clocks
    tdir = TARGETS_DIR / target

    # emit recovered.v (gate), then build the correspondence from the ACTUAL
    # emitted port identifiers — verilog.py sanitises pad labels (e.g. drops
    # '?'), so pad_map.label is not necessarily the yosys-visible port name.
    gate_v = tmp / f"lec_{target}.v"
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=str(con_path))
    emit = subprocess.run(
        [PY, "verilog.py", "--bitstream", label, "--out", str(gate_v),
         "--top", "fuzz"], capture_output=True, text=True, cwd=str(REPO),
        env=env)
    if emit.returncode != 0 or not gate_v.exists():
        tail = (emit.stderr.strip().splitlines() or ["(no stderr)"])[-1]
        return Result(target, "logic", "ERROR", "equiv-error",
                      f"verilog.py emit failed: {tail}")
    rec_pads, rec_clocks = parse_recovered_ports(gate_v.read_text())

    renames = []
    clock_note = ""
    # 3) clock correspondence (map the source clock to the recovered FF clock)
    if src_clocks:
        sclk = src_clocks[0]
        cpin = pins.get(sclk)
        if len(rec_clocks) == 1:
            renames.append((rec_clocks[0], sclk))
            at = ("pad resolved as data" if cpin in rec_pads
                  else "pad unresolved")
            clock_note = (f"clk pin{cpin} {at}; FF driven by ghost clock "
                          f"{rec_clocks[0]} (clock route not recovered)")
        elif not rec_clocks and cpin in rec_pads:
            renames.append((rec_pads[cpin]["name"], sclk))
            clock_note = f"clk recovered at pin{cpin}"
        else:
            return Result(target, "logic", "ERROR", "port-map-failed",
                          f"clock not bindable ({len(rec_clocks)} ghost clocks, "
                          f"clk pin{cpin} "
                          f"{'present' if cpin in rec_pads else 'absent'})")

    # 4) data-port renames (recovered emitted port -> source name)
    kept = set()
    names_seen = set()
    for p in data_ports:
        rp = rec_pads.get(pins[p])
        if rp is None:
            return Result(target, "logic", "BLOCKED", "edge-cib-unresolved-io",
                          f"{p}@pin{pins[p]} resolved in DB but not emitted "
                          f"as a recovered port")
        name = rp["name"]
        if name in names_seen:
            return Result(target, "logic", "ERROR", "port-map-failed",
                          f"ambiguous recovered port '{name}' shared by pins")
        names_seen.add(name)
        renames.append((name, p))
    for old, _new in renames:
        kept.add(old)

    # gate ports we did not map -> delete (dangling resolved pads, e.g. the
    # clock pad the fabric never routed to the FF).
    gate_ports = {pd["name"] for pd in rec_pads.values()} | set(rec_clocks)
    deletes = sorted(gate_ports - kept)

    src_v = tdir / "fuzz.v"
    gold_files = [cells_lib, src_v]

    # control: source vs source must prove EQUIVALENT, else the flow is
    # suspect and any real FAIL is untrustworthy.
    ctl_verdict, cp, cu, ctl_log = run_equiv(gold_files, src_v, [], [])
    log.write(f"\n=== {target}: control equiv(src,src) = {ctl_verdict} "
              f"({cp} proven / {cu} unproven) ===\n")
    if ctl_verdict != "PASS":
        return Result(target, "logic", "ERROR", "equiv-error",
                      f"self-control did not prove (got {ctl_verdict}); "
                      f"flow/cell-lib suspect")

    verdict, proven, unproven, elog = run_equiv(
        gold_files, gate_v, renames, deletes)
    log.write(f"=== {target}: equiv(recovered,src) = {verdict} "
              f"({proven} proven / {unproven} unproven) ===\n")
    log.write(elog)

    ren = ", ".join(f"{o}->{n}" for o, n in renames)
    base = f"renamed [{ren}]; deleted [{', '.join(deletes) or '-'}]"
    if clock_note:
        base += f"; {clock_note}"
    if verdict == "PASS":
        return Result(target, "logic", "PASS", "",
                      f"equiv proven ({proven} cells); {base}")
    if verdict == "FAIL":
        rec = recovered_logic_summary(con, bid)
        return Result(target, "logic", "FAIL", "lifter-bug",
                      f"equiv diverged ({unproven} unproven / {proven} proven)"
                      f" — recovered [{rec}] != source; {base}")
    err = next((l for l in elog.splitlines() if "ERROR" in l), "")
    return Result(target, "logic", "ERROR", "equiv-error",
                  f"yosys equiv error: {err[:120]}; {base}")


# ── driver ───────────────────────────────────────────────────────────────
con_path = None  # set in main(), consumed by run_candidate for verilog.py env


def enumerate_targets(pattern):
    for d in sorted(os.listdir(TARGETS_DIR)):
        if pattern and not fnmatch.fnmatch(d, pattern):
            continue
        if (TARGETS_DIR / d / "fuzz.v").is_file():
            yield d


def main():
    global con_path
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="tmp/fuzz_rebuild.db",
                    help="fuzz SQLite DB (default: tmp/fuzz_rebuild.db)")
    ap.add_argument("--limit", type=int, default=40,
                    help="max equiv-candidates to run the (expensive) yosys "
                         "proof on; 0 = all. Structural classification always "
                         "covers the whole corpus (default: 40)")
    ap.add_argument("--targets", metavar="GLOB",
                    help="only categorise/LEC targets matching this glob")
    ap.add_argument("--out", default="tmp/fuzz_lec_defectmap.tsv",
                    help="defect-map TSV output path")
    ap.add_argument("--log", default="tmp/fuzz_lec.log",
                    help="full run log path")
    args = ap.parse_args()

    con_path = (REPO / args.db) if not os.path.isabs(args.db) else Path(args.db)
    if not con_path.exists():
        sys.exit(f"ERROR: DB not found: {con_path}")
    (REPO / "tmp").mkdir(exist_ok=True)
    log = open(REPO / args.log if not os.path.isabs(args.log) else args.log,
               "w")
    log.write(f"# fuzz_lec run {datetime.now().isoformat()}  db={con_path}\n")

    con = sqlite3.connect(str(con_path))
    lab2id = {lab: i for i, lab in con.execute(
        "SELECT id,label FROM bitstreams")}

    tmp = REPO / "tmp"
    cells_lib = _write_cells_lib(tmp)

    # 1) categorise everything
    logic, hardip = [], []
    hard_prim_hist = {}
    for t in enumerate_targets(args.targets):
        prims = parse_prims((TARGETS_DIR / t / "fuzz.v").read_text())
        cls, hard = classify_source(prims)
        if cls == "logic":
            logic.append(t)
        else:
            hardip.append((t, hard))
            for h in hard:
                hard_prim_hist[h] = hard_prim_hist.get(h, 0) + 1

    print(f"Categorised {len(logic) + len(hardip)} targets "
          f"(with fuzz.v){' matching ' + args.targets if args.targets else ''}:")
    print(f"  logic   : {len(logic)}")
    print(f"  hard-ip : {len(hardip)}")
    if hard_prim_hist:
        top_hard = sorted(hard_prim_hist.items(), key=lambda x: -x[1])[:8]
        print("  hard-ip by primitive (top): "
              + ", ".join(f"{k}={v}" for k, v in top_hard))

    # 2) fast DB-only pre-classification of EVERY logic target (no emit, no
    #    yosys) — this gives the complete classification histogram cheaply.
    results = []
    candidates = []
    for t in logic:
        r, cand = pre_classify(t, con, lab2id)
        if cand is not None:
            candidates.append(cand)
        else:
            results.append(r)

    # record the hard-ip targets in the defect map too (enum-compare, #49)
    for t, hard in hardip:
        results.append(Result(t, "hard-ip", "SKIP", "hard-ip",
                              "logic LEC N/A — compare by config enums (#49): "
                              + ",".join(hard)))

    print(f"\n{len(candidates)} logic target(s) are equiv-candidates "
          f"(all data pads resolved); the rest are pre-classified structurally.")

    # 3) run the real (expensive) yosys equiv on up to --limit candidates.
    run = candidates if args.limit <= 0 else candidates[:args.limit]
    deferred = candidates[len(run):]
    print(f"Running yosys equiv on {len(run)} of {len(candidates)} "
          f"candidate(s) (--limit {args.limit})…")
    for i, cand in enumerate(run, 1):
        r = run_candidate(cand, con, tmp, cells_lib, log)
        results.append(r)
        print(f"  [{i:>3}/{len(run)}] {cand.target:<30} {r.lec:<8} {r.root}",
              flush=True)
    for cand in deferred:
        results.append(Result(cand.target, "logic", "CANDIDATE",
                              "equiv-not-run",
                              "all data pads resolved; equiv deferred (--limit)"))

    # 4) defect map TSV
    out_path = (REPO / args.out) if not os.path.isabs(args.out) else Path(args.out)
    with open(out_path, "w") as fh:
        fh.write("target\tclass\tlec_result\troot_cause\tdetail\n")
        for r in sorted(results, key=lambda r: (r.cls, r.lec, r.target)):
            fh.write(r.row() + "\n")

    # 4) histograms
    lec_hist, root_hist = {}, {}
    logic_results = [r for r in results if r.cls == "logic"]
    for r in logic_results:
        lec_hist[r.lec] = lec_hist.get(r.lec, 0) + 1
        root_hist[r.root or "(pass)"] = root_hist.get(r.root or "(pass)", 0) + 1

    print(f"\n=== LOGIC-subset LEC summary ({len(logic_results)} targets) ===")
    for k in ("PASS", "FAIL", "BLOCKED", "SKIP", "CANDIDATE", "ERROR"):
        if k in lec_hist:
            print(f"  {k:<10} {lec_hist[k]}")
    print("  root cause:")
    for k, v in sorted(root_hist.items(), key=lambda x: -x[1]):
        print(f"    {v:>4}  {k}")

    reached = [r for r in logic_results if r.lec in ("PASS", "FAIL")]
    npass = sum(1 for r in reached if r.lec == "PASS")
    print(f"\nReached a real yosys equiv verdict: {len(reached)} of "
          f"{len(candidates)} candidate(s) run  (PASS={npass}, "
          f"FAIL={len(reached) - npass})")
    for r in reached[:12]:
        print(f"  {r.target}: {r.lec} — {r.detail}")
    if len(reached) > 12:
        print(f"  … and {len(reached) - 12} more (see {args.out})")

    print(f"\nDefect map : {out_path}")
    print(f"Full log   : {log.name}")
    log.close()
    con.close()


if __name__ == "__main__":
    main()
