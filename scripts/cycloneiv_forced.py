#!/usr/bin/env python3.15t
"""Cyclone IV GX single-hop specimens, RAW cram-plane diff (issue #141). No Dec.active, no asm decode.

Pair = identical cells + placement + pins; specimen has the one net, base leaves the sink pin open.
Diff = set bits only in one plane (cycloneiv_corpus.cram_plane keys).  Optional forced route:
a design may carry src/force.rcf, fed to the fitter via ROUTING_BACK_ANNOTATION_MODE/FILE.

  python3.15t scripts/cycloneiv_forced.py tier --jobs 6      # Tier 0/1 smallest pairs + diff report
Log tmp/logs/cycloneiv_forced.log
"""
import argparse
import datetime
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_forced")
CORPUS = REPO / "corpus" / "cycloneiv"
DEVICE = "EP4CGX150DF31C7"
CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{mask}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
        "    {name} ({ports});\n")
PORTS = ("dataa", "datab", "datac", "datad")


def verilog(cells, nets):
    """cells: [(name, mask, {port: net})]; nets: wires; the last cell's combout is output y."""
    v = "module top(output y);\n" + "".join(f"  wire {n};\n" for n in nets)
    for i, (nm, mask, conns) in enumerate(cells):
        ports = [f".{p}({n})" for p, n in conns.items()] + [f".combout({'y' if i == len(cells) - 1 else nm + '_o'})"]
        v += CELL.format(mask=mask, name=nm, ports=", ".join(ports))
    return v + "endmodule\n"


def write_design(name, v, qsf, purpose, rcf=None):
    d = CORPUS / name
    if (d / "routing.rcf").exists():
        return
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(v)
    q = list(qsf)
    if rcf:
        (d / "src" / "force.rcf").write_text(rcf)
        q = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
             "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + q
    q += ["set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "{purpose}"\nexercises = {fz.toml_list(["routing", "forced"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


def lc(x, y, n):
    return f"LCCOMB_X{x}_Y{y}_N{n}"


def tier_designs():
    out = {}
    pin = "set_location_assignment PIN_B9 -to y"
    # Tier 0: one cell, combout -> own dataa (loop) vs dataa open
    for kind in ("s", "b"):
        out[f"gxt0_{kind}"] = ("module top(output y);\n  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), "
                               '.sum_lutc_input("datac"), .dont_touch("on"))\n    u0 ('
                               + (".dataa(y), " if kind == "s" else "") + ".combout(y));\nendmodule\n",
                               [f"set_location_assignment {lc(10, 10, 0)} -to u0", pin], "tier0 self-loop")
    # Tier 1: u0 (N0) -> u1.<port>, base leaves it open; sources N0,N2,N4 -> sink N6 etc via varied args
    for port in PORTS:
        for src in (0, 2, 4):
            for kind in ("s", "b"):
                conns = {port: "u0_o"} if kind == "s" else {}
                v = ("module top(output y);\n  wire u0_o;\n"
                     '  cycloneiv_lcell_comb #(.lut_mask(16\'h0000), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                     "    u0 (.combout(u0_o));\n"
                     '  cycloneiv_lcell_comb #(.lut_mask(16\'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                     f"    u1 ({''.join(f'.{p}({n}), ' for p, n in conns.items())}.combout(y));\nendmodule\n")
                out[f"gxt1_{port[-1]}_n{src}_{kind}"] = (
                    v, [f"set_location_assignment {lc(10, 10, src)} -to u0",
                        f"set_location_assignment {lc(10, 10, 6)} -to u1", pin],
                    f"tier1 u0@N{src} -> u1.{port}")
    return out


def bits(name):
    return set(cc.load_plane_only(name).keys.tolist())


def diff(a, b):
    A, B = bits(a), bits(b)
    return sorted(A - B), sorted(B - A)


def build_all(names, jobs):
    def one(n):
        f = fz.build_one(n)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        return n, f
    with ThreadPoolExecutor(jobs) as ex:
        return dict(ex.map(one, names))


def tier(jobs):
    ds = tier_designs()
    for n, (v, q, p) in ds.items():
        write_design(n, v, q, p)
    res = build_all([n for n in ds if not (CORPUS / n / "routing.rcf").exists()], jobs)
    for n, f in res.items():
        if f:
            log.info("BUILD FAIL %s at %s", n, f)
    rep = {}
    for n in sorted(ds):
        if n.endswith("_s") and (CORPUS / n / "routing.rcf").exists():
            b = n[:-2] + "_b"
            if not (CORPUS / b / "routing.rcf").exists():
                continue
            on, off = diff(n, b)
            rep[n] = {"only_spec": on, "only_base": off}
            log.info("%s: only-spec %d only-base %d", n, len(on), len(off))
    (REPO / "tmp" / "cycloneiv_forced_tier.json").write_text(json.dumps(rep))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("tier",))
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fz.log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_forced.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
        fz.log.addHandler(h)
    tier(a.jobs)


if __name__ == "__main__":
    main()
