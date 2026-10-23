#!/usr/bin/env python3.15t
"""Cyclone V per-pad IO feature table from a Mistral `.bt` + the package table.

One row per GPIO pad (tile,bi) seen in routing/settings.  Board-agnostic: it
reports evidence (bank, ports used, settings, what each pad's net touches); the
hypotheses/classification live with the board, not here.

  python3.15t scripts/cyclonev_io_report.py --bt X.bt --out io_table.tsv [--package u19]

Log: tmp/logs/cyclonev_io_report.log.  Package table: <mistral>/data/e50f-pkg.txt
(derived from the mistral-cv binary location; override with --pkg-table).
"""
import argparse
import collections
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import toolchain  # noqa: E402
from db import die  # noqa: E402
from lifters.cyclonev_lift import CycloneVLift  # noqa: E402
from lifters import machxo2_lift as mx  # noqa: E402

BEL_BLOCKS = {"LAB", "MLAB", "DSP", "M10K", "HMC", "GPIO", "FPLL", "DQS16", "DLL",
              "CTRL", "TERM", "LVL", "CMUXVG", "CMUXHG", "CMUXCR", "CMUXVR", "CMUXHR"}
KEY_SETTINGS = ("DRIVE_STRENGTH", "VOD_LEVEL", "TERMINATION_MODE", "TERMINATION_CONTROL",
                "USE_DIFF_OUTPUT", "LVDS_BUFFER_USED", "USE_PSEUDO_DIFF_OUTPUT",
                "USE_OPEN_DRAIN", "USE_WEAK_PULLUP", "USE_BUS_HOLD", "SLEW_RATE_SLOW",
                "IOCSR_STD", "PLL_SELECT", "USE_PCI_DIODE_CLAMP", "USE_PREEMPHASIS",
                "USE_LVDS_TERMINATION", "TX_ENABLE_HC", "VOS_LEVEL", "ENABLE_SERDES_LOOPBACK")
_GPIO_NODE = re.compile(r"GPIO\.(\d+)\.(\d+)(?:\.(\d+))?:?(\S*)")
_SET = re.compile(r"^s GPIO\.(\d+)\.(\d+):(\w+?)(?:\.(\d+))? (\S+)(?: ; (\S+))?$")
_PKG = re.compile(r"^\s*\d+\s+\d+\s+(\w+)\s+(.*)$")


def load_package(path, pkg):
    """ball -> dict(gpio=(x,y,bi)|None, ioblock, ded, func, type) for one package section."""
    out, on = {}, False
    for ln in open(path):
        if re.match(r"^[a-z0-9]+ width:", ln):
            on = ln.startswith(pkg + " ")
            continue
        if not on:
            continue
        m = _PKG.match(ln)
        if not m:
            continue
        ball, rest = m.groups()
        d = {"gpio": None, "ioblock": "", "ded": "", "func": "", "type": ""}
        for tok in rest.split():
            if tok.startswith("gpio:"):
                x, y, bi = tok[5:].split(".")
                d["gpio"] = (int(x), int(y), int(bi))
            elif tok.startswith("ioblock:"):
                d["ioblock"] = tok[8:]
            elif tok.startswith("dedicated_programming_pad:"):
                d["ded"] = tok.split(":")[1]
            elif tok.startswith("f:"):
                d["func"] = tok[2:]
            elif tok.startswith("t:"):
                d["type"] = tok[2:]
        out[ball] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--package", default="u19")
    ap.add_argument("--device", default="5CEBA4U19C8")
    ap.add_argument("--pkg-table")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_io_report.log"))])
    log = logging.getLogger("io_report")

    pkgtab = a.pkg_table or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(toolchain.mistral_cv()))),
        "data", "e50f-pkg.txt")
    if not os.path.exists(pkgtab):
        die(f"package table not found: {pkgtab}")
    pkg = load_package(pkgtab, a.package)
    by_tile = {v["gpio"]: b for b, v in pkg.items() if v["gpio"]}
    log.info("package %s: %d balls, %d with gpio", a.package, len(pkg), len(by_tile))

    lift = CycloneVLift(a.device)
    pc = lift.parse_config(a.bt)
    d = lift.recover_netlist(pc)
    find, nname = d.dsu.find, d.net_name

    # net class -> bel sink / source endpoints
    sinks = collections.defaultdict(list)
    srcs = collections.defaultdict(list)
    for s, t in pc.arcs:
        if t.block in BEL_BLOCKS:
            sinks[find(t)].append(t)
        if s.block in BEL_BLOCKS:
            srcs[find(s)].append(s)

    def hist(nodes, skip=None):
        c = collections.Counter(n.block + (":" + n.port if n.block in ("LAB", "MLAB", "DSP", "M10K", "HMC") and n.port else "")
                                for n in nodes if n != skip)
        return ",".join(f"{k}={v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))

    # LUT consumers per net: real = INIT depends on that pin, vacuous = routed but ignored
    real_use, vac_use, lut_out = collections.defaultdict(list), collections.defaultdict(int), {}
    for lt in d.luts:
        dep = mx.lut_dependence(lt["init"])
        lut_out[lt["name"]] = lt.get("z")
        for pin in "abcde":
            nn = lt.get(pin)
            if nn:
                if pin in dep:
                    real_use[nn].append(lt)
                else:
                    vac_use[nn] += 1
    by_in = real_use

    def cone(nets, depth=4):
        seen, frontier, n_lut = set(nets), set(nets), set()
        for _ in range(depth):
            nxt = set()
            for nn in frontier:
                for lt in by_in.get(nn, []):
                    if lt["name"] not in n_lut:
                        n_lut.add(lt["name"])
                        z = lt.get("z")
                        if z and z not in seen:
                            seen.add(z)
                            nxt.add(z)
            frontier = nxt
        return len(n_lut)

    pads = {}

    def pad(x, y, bi):
        return pads.setdefault((x, y, bi), {
            "ports": collections.defaultdict(int), "in_nets": set(), "out_nets": set(),
            "in_sink": collections.Counter(), "out_src": collections.Counter(),
            "in_fan": 0, "out_fan": 0, "clk_srcs": set(), "settings": {}, "ball": None,
            "hmc": 0, "dqs": set()})

    for s, t in pc.arcs:
        for node, other, is_src in ((s, t, True), (t, s, False)):
            if node.block != "GPIO" or node.bi is None:
                continue
            p = pad(node.x, node.y, node.bi)
            p["ports"][node.port] += 1
            root = find(node)
            if node.port in ("DATAIN", "BSLIPMAX") and is_src:
                p["in_nets"].add(nname.get(root))
                for n in sinks.get(root, []):
                    if n.block != "GPIO" or (n.x, n.y, n.bi) != (node.x, node.y, node.bi):
                        p["in_sink"][n.block + (":" + n.port if n.block in ("LAB", "MLAB", "DSP", "M10K", "HMC") and n.port else "")] += 1
            elif node.port == "DATAOUT" and not is_src:
                p["out_nets"].add(nname.get(root))
                for n in srcs.get(root, []):
                    if n.block != "GPIO":
                        p["out_src"][n.block + (":" + n.port if n.block in ("LAB", "MLAB", "DSP", "M10K", "HMC") and n.port else "")] += 1
            elif node.port in ("CLKIN", "CLKOUT") and not is_src:
                p["clk_srcs"].add(other.block)

    hmc_pins = collections.defaultdict(int)
    dqs_pins = collections.defaultdict(set)
    inv = collections.defaultdict(list)
    for ln in open(a.bt):
        if ln.startswith("s GPIO"):
            m = _SET.match(ln.rstrip("\n"))
            if m:
                x, y, name, bi, val, ball = m.groups()
                if bi is not None:
                    pad(int(x), int(y), int(bi))["settings"][name] = val
                else:                       # tile-wide setting: attach to every bi later
                    inv[(int(x), int(y))].append((name, val))
        elif " ; " in ln and ln[0] in "rsi":
            ball = ln.split(" ; ", 1)[1].strip().split()[0]
            if "HMC." in ln:
                hmc_pins[ball] += 1
            elif "DQS16." in ln:
                mm = re.search(r"DQS16\.(\d+\.\d+)", ln)
                dqs_pins[ball].add(mm.group(1))
    for (x, y, bi), p in pads.items():
        for name, val in inv.get((x, y), []):
            p["settings"].setdefault(name, val)
        p["ball"] = pc.pin_annotations.get(("GPIO", x, y, bi)) or by_tile.get((x, y, bi))
        p["ball_src"] = "mistral-bt" if pc.pin_annotations.get(("GPIO", x, y, bi)) else (
            "pkg-table" if by_tile.get((x, y, bi)) else "")
        if p["ball"] and by_tile.get((x, y, bi)) and by_tile[(x, y, bi)] != p["ball"]:
            log.warning("ball mismatch tile %s: bt=%s pkg=%s", (x, y, bi), p["ball"],
                        by_tile[(x, y, bi)])

    cols = ["ball", "ball_src", "bank", "ded_pad", "x", "y", "bi", "ports", "dir", "registered",
            "oe_used", "lut_real", "lut_vacuous", "cone4", "in_nets", "out_nets", "in_sinks", "out_sources", "clk_from",
            "hmc_lines", "dqs16", "settings"]
    n = 0
    with open(a.out, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for (x, y, bi), p in sorted(pads.items(), key=lambda kv: (kv[1]["ball"] or "~", kv[0])):
            b = pkg.get(p["ball"] or "", {})
            ports = p["ports"]
            has_in = "DATAIN" in ports
            has_out = "DATAOUT" in ports
            direction = ("bidir" if has_in and has_out and "OEIN" in ports else
                         "in" if has_in and not has_out else
                         "out" if has_out and not has_in else
                         "in+out" if has_in and has_out else "unknown")
            reg = ",".join(k for k in ("CLKIN", "CLKOUT", "CEIN", "CEOUT", "ACLR", "SCLR") if k in ports)
            st = ";".join(f"{k}={v}" for k, v in sorted(p["settings"].items())
                          if k in KEY_SETTINGS)
            row = [p["ball"] or "", p["ball_src"], b.get("ioblock", ""), b.get("ded", ""),
                   x, y, bi, ",".join(f"{k}:{v}" for k, v in sorted(ports.items())),
                   direction, reg, "OEIN" in ports,
                   sum(len(real_use.get(n, [])) for n in p["in_nets"] if n),
                   sum(vac_use.get(n, 0) for n in p["in_nets"] if n),
                   cone([n for n in p["in_nets"] if n]),
                   ",".join(sorted(str(i) for i in p["in_nets"])),
                   ",".join(sorted(str(i) for i in p["out_nets"])),
                   ",".join(f"{k}={v}" for k, v in p["in_sink"].most_common(8)),
                   ",".join(f"{k}={v}" for k, v in p["out_src"].most_common(8)),
                   ",".join(sorted(p["clk_srcs"])), hmc_pins.get(p["ball"], 0),
                   ",".join(sorted(dqs_pins.get(p["ball"], []))), st]
            fh.write("\t".join(str(c) for c in row) + "\n")
            n += 1
    log.info("wrote %d pads -> %s (%d with ball, %d via pkg-table only)", n, a.out,
             sum(1 for p in pads.values() if p["ball"]),
             sum(1 for p in pads.values() if p["ball_src"] == "pkg-table"))


if __name__ == "__main__":
    main()
