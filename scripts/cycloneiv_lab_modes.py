#!/usr/bin/env python3.15t
"""Cyclone IV LAB core feature specimens (item A of #141): RAW cram-plane diff, no decoder in the loop.

Pair = identical cells/placement/masks; specimen adds ONE thing, base leaves it out.  Diff = set bits
only in one plane.  Evidence goes to databases/cycloneiv/gx150.db (kind specimen-pair, source_ref
lab_modes:<group>).  Design prefix gxlm_.  Groups (smallest first):
  pprobe   forced LOCAL_LINE I x sink port (A-D) legality probe, 1 sink, X10Y10
  ports    every (source LE, sink LE, port A-D) with the LL/port forced, per LAB
  (later groups: modes, buf, flags - see docs/cycloneiv-specimens.md "LAB core checklist")

  gen <group> | build <group> | diff <group> | run <group> (= gen+build+diff per pair) | compare <group>
Log tmp/logs/cycloneiv_lab_modes.log
"""
import argparse
import logging
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "databases" / "cycloneiv" / "gx150.db"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_forced as cf  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402

log = logging.getLogger("cycloneiv_lab_modes")
CORPUS = cf.CORPUS
DEVICE = cf.DEVICE
EV_DEVICE = "EP4CGX150"   # device string of the evidence rows
GENERATOR = "scripts/cycloneiv_lab_modes.py"
LABS = [(10, 10), (58, 30), (37, 60), (100, 75)]
SRC_REF = "lab_modes:"
KEEP_FULL = 4            # full bitstreams kept for the first N pairs of a group
DISK_FLOOR_GB = 12.0
LL_OF_SRC = None         # {src N: LOCAL_LINE I}, read from the existing same-LAB grid evidence

CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{mask}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
        "    {name} ({ports});\n")


def ll_of_src():
    global LL_OF_SRC
    if LL_OF_SRC is None:
        import evidence_io_bridge as B
        t = B.specimen_table("cycloneiv", EV_DEVICE, "evidence/cycloneiv/cycloneiv_forced_lab.json")
        LL_OF_SRC = {v["src"]: v["hop"][3] for v in t.values()}
        if len(LL_OF_SRC) != 16:
            sys.exit("same-LAB grid evidence missing (need src -> LOCAL_LINE I)")
    return LL_OF_SRC


def rcf_for(lab, ll, port):
    return ("section global_data {\n\trcf_written_by = \"Quartus Prime 25.1 Build 1129\";\n"
            f"\tdevice = {DEVICE};\n}}\n\nsignal_name = u0_o {{\n\tLOCAL_LINE:X{lab[0]}Y{lab[1]}S0I{ll};\n"
            f"\tdest = ( u1, DATA{port} ), route_port = DATA{port};\n}}\n")


def verilog(src_mask, snk_mask, conn):
    """u0 (source, no inputs) -> u1 (sink), y = u1.combout; conn = '' for the base."""
    return ("module top(output y);\n  wire u0_o;\n"
            + CELL.format(mask=src_mask, name="u0", ports=".combout(u0_o)")
            + CELL.format(mask=snk_mask, name="u1", ports=(conn + ".combout(y)"))
            + "endmodule\n")


def lc(lab, n):
    return cf.lc(lab[0], lab[1], n)


def port_pair(lab, src, snk, port, ll=None):
    """(name, spec verilog, base verilog, qsf, rcf, meta): u0@N<src> -> u1@N<snk>.DATA<port>, LL forced."""
    ll = ll_of_src()[src] if ll is None else ll
    name = f"gxlm_p{port}_{lab[0]}x{lab[1]}_{src:02d}_{snk:02d}_i{ll:02d}"
    q = [f"set_location_assignment {lc(lab, src)} -to u0", f"set_location_assignment {lc(lab, snk)} -to u1",
         "set_location_assignment PIN_B9 -to y"]
    meta = {"group": "ports", "lab": list(lab), "src": src, "snk": snk, "port": port, "ll": ll}
    return (name, verilog("0000", "FFFF", f".data{port.lower()}(u0_o), "), verilog("0000", "FFFF", ""),
            q, rcf_for(lab, ll, port), meta)


def group_pairs(group):
    if group == "pprobe":     # legality: every (LL I, port) once, sink fixed at N2 (N4 for source N2)
        lab = LABS[0]
        return [port_pair(lab, s, 4 if s == 2 else 2, p) for s in range(0, 32, 2) for p in "ABCD"]
    if group.startswith("ports"):   # portsX10Y10 etc: all src x snk x port at one LAB (src != snk)
        m = re.fullmatch(r"ports(\d+)x(\d+)", group)
        lab = (int(m.group(1)), int(m.group(2)))
        return [port_pair(lab, s, k, p) for s in range(0, 32, 2) for k in range(0, 32, 2) if s != k for p in "ABCD"]
    sys.exit(f"unknown group {group}")


def write_pair(pr):
    name, vs, vb, q, rcf, meta = pr
    for kind, v in (("s", vs), ("b", vb)):
        d = CORPUS / f"{name}_{kind}"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(v)
        qq = list(q)
        if kind == "s" and rcf:
            (d / "src" / "force.rcf").write_text(rcf)
            qq = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
                  "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + qq
        qq += ["set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
        (d / "design.toml").write_text(
            f'top = "top"\npurpose = "lab_modes {meta["group"]} {kind}"\nexercises = {fz.toml_list(["lab", "forced"])}\n'
            f"qsf = {fz.toml_list(qq)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
            f'tool_version = "25.1"\nbuilt = "{__import__("datetime").date.today().isoformat()}"\n')


def prune(n, full):
    d = CORPUS / n
    shutil.rmtree(d / "quartus", ignore_errors=True)
    shutil.rmtree(d / "logs", ignore_errors=True)
    for f in ("postfit.vo", "fit.rpt", "build.pin") + (() if full else ("bitstream.rbf",)):
        (d / f).unlink(missing_ok=True)


def rcf_hop_of(name):
    """(LOCAL_LINE I, port) in the post-fit RCF for u0_o, or None."""
    p = CORPUS / f"{name}_s" / "routing.rcf"
    if not p.exists():
        return None
    m = re.search(r"signal_name = u0_o \{\s*(\w+):X(\d+)Y(\d+)S0I(\d+);\s*dest = \( u1, \w+ \), route_port = (\w+);",
                  p.read_text())
    return None if not m else [m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)]


def build_diff_record(pr, idx, record=True):
    """Build base + specimen, raw-diff, record the evidence row, prune.  Returns the meta."""
    from provenance import evidence_io as E
    import db
    name, _vs, _vb, _q, _rcf, meta = pr
    full = idx < KEEP_FULL
    for k in ("b", "s"):
        f = fz.build_one(f"{name}_{k}")
        if f:
            log.info("%s_%s: FAIL at %s", name, k, f)
            return {**meta, "status": "build-fail", "step": f}
    on, off = cf.diff(f"{name}_s", f"{name}_b")
    hop = rcf_hop_of(name)
    honoured = bool(hop and hop[3] == meta.get("ll") and hop[4] == f"DATA{meta.get('port')}") if "port" in meta else None
    meta = {**meta, "hop": hop, "forced_honoured": honoured, "status": "ok"}
    nv = cc.load_plane_only(f"{name}_b").shape[1]
    for k in ("s", "b"):
        prune(f"{name}_{k}", full)
    if record:
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            E.record_specimen(conn, "cycloneiv", EV_DEVICE, name, f"{name}_b", on, off, meta, SRC_REF + meta["group"],
                              GENERATOR, E.git_head(REPO), nv, tool_version="25.1")
    log.info("%s: on %d off %d hop %s honoured %s", name, len(on), len(off), hop, honoured)
    return {**meta, "on": on, "off": off}


def run(group, jobs, todo_only=True):
    import build_pool
    import db
    from sqlalchemy import select
    import schema as S
    prs = group_pairs(group)
    with db.engine().connect() as conn:
        done = {r[0] for r in conn.execute(select(S.evidence.c.name).where(
            S.evidence.c.source_ref == SRC_REF + (prs[0][5]["group"]), S.evidence.c.family == "cycloneiv"))}
    todo = [(i, p) for i, p in enumerate(prs) if p[0] not in done]
    log.info("group %s: %d pairs, %d to do", group, len(prs), len(todo))
    for _i, p in todo:
        write_pair(p)
    if shutil.disk_usage(REPO).free / 2**30 < DISK_FLOOR_GB:
        sys.exit("disk floor")
    res = build_pool.map_adaptive(lambda ip: build_diff_record(ip[1], ip[0]), todo, per_job_gb=2.5,
                                  max_workers=jobs or None, disk_floor_gb=DISK_FLOOR_GB)
    bad = [r for r in res if r.get("status") != "ok"]
    ok = [r for r in res if r.get("status") == "ok"]
    hon = sum(1 for r in ok if r.get("forced_honoured"))
    log.info("group %s: %d ok, %d failed, forced honoured %d / %d", group, len(ok), len(bad), hon, len(ok))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("gen", "run", "show"))
    ap.add_argument("group")
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    for lg in (log, fz.log):
        lg.setLevel(logging.INFO)
        for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_lab_modes.log"), logging.StreamHandler()):
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)
    if a.cmd == "gen":
        for p in group_pairs(a.group):
            write_pair(p)
    elif a.cmd == "run":
        run(a.group, a.jobs)


if __name__ == "__main__":
    main()
