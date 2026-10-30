#!/usr/bin/env python3.15t
"""Specimen builds for the Cyclone IV GX hard blocks: MAC (embedded multiplier), PLL, M9K feature pairs (#169).

  python3.15t scripts/cycloneiv_clean_hardblocks_build.py gen   <set>
  python3.15t scripts/cycloneiv_clean_hardblocks_build.py build <set> [--jobs N]     # detached: setsid, log tmp/logs/cycloneiv_clean_hardblocks_build.log
Sets: mac, pll, m9k.  Design prefix gxhb_.  ONE feature per pair; every pair shares the base's top-level ports and (for M9K) the site.
Quartus steps, stall guard (60 s) and overall limits come from cycloneiv_fuzz.build_one (OVERALL_GX_S: 3x worst measured step).
"""
import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_fuzz as fz  # noqa: E402
import cycloneiv_m9k as m9  # noqa: E402

log = logging.getLogger("hb_build")
CORPUS = REPO / "corpus" / "cycloneiv"

# --- MAC: altmult_add, one multiplier per block unless stated; one parameter differs per specimen
MAC_BASE = {"number_of_multipliers": 1, "width_a": 18, "width_b": 18, "width_result": 36, "representation_a": "UNSIGNED",
            "representation_b": "UNSIGNED", "input_register_a0": "UNREGISTERED", "input_register_b0": "UNREGISTERED",
            "multiplier_register0": "UNREGISTERED", "output_register": "UNREGISTERED", "signed_register_a": "UNREGISTERED",
            "signed_register_b": "UNREGISTERED", "port_signa": "PORT_UNUSED", "port_signb": "PORT_UNUSED"}
MAC_SPECS = [
    ("signed_a", {"representation_a": "SIGNED"}),
    ("signed_b", {"representation_b": "SIGNED"}),
    ("signed_ab", {"representation_a": "SIGNED", "representation_b": "SIGNED"}),
    ("in_a_reg", {"input_register_a0": "CLOCK0"}),
    ("in_b_reg", {"input_register_b0": "CLOCK0"}),
    ("mult_reg", {"multiplier_register0": "CLOCK0"}),
    ("out_reg", {"output_register": "CLOCK0"}),
    ("w9", {"width_a": 9, "width_b": 9, "width_result": 18}),
    ("w10", {"width_a": 10, "width_b": 10, "width_result": 20}),
    ("w9x18", {"width_a": 9, "width_b": 18, "width_result": 27}),
    ("w36", {"width_a": 36, "width_b": 36, "width_result": 72}),
    ("dyn_signa", {"port_signa": "PORT_USED"}),
    ("dyn_signb", {"port_signb": "PORT_USED"}),
    ("two_mult_w9", {"number_of_multipliers": 2, "width_a": 9, "width_b": 9, "width_result": 18}),
    ("w9_in_reg", {"width_a": 9, "width_b": 9, "width_result": 18, "input_register_a0": "CLOCK0", "input_register_b0": "CLOCK0"}),
]
MAC_NULL = [("null_seed", {})]


def mac_design(prm, seed=1):
    n, wa, wb, wr = prm["number_of_multipliers"], prm["width_a"], prm["width_b"], prm["width_result"]
    pl = ",\n    ".join(f".{k}({v if isinstance(v, int) else chr(34) + v + chr(34)})" for k, v in prm.items())
    pl += ',\n    .intended_device_family("Cyclone IV GX"),\n    .lpm_type("altmult_add")'
    ports = [".clock0(clk)", ".ena0(1'b1)", ".aclr0(1'b0)"]
    dec = []
    for i in range(n):
        ports += [f".dataa({{{'da' if i == 0 else 'da2'}}})" if n > 1 else ".dataa(da)",
                  f".datab({{{'db' if i == 0 else 'db2'}}})" if n > 1 else ".datab(db)"]
    if n > 1:
        ports = [".clock0(clk)", ".ena0(1'b1)", ".aclr0(1'b0)", ".dataa({da2, da})", ".datab({db2, db})"]
    if prm["port_signa"] == "PORT_USED":
        ports.append(".signa(sa)")
    if prm["port_signb"] == "PORT_USED":
        ports.append(".signb(sb)")
    ports.append(f".result(r)")
    v = (f"module top(input clk, input sa, input sb, input [{wa - 1}:0] da, input [{wb - 1}:0] db, "
         f"input [{wa - 1}:0] da2, input [{wb - 1}:0] db2, output [{wr * n - 1}:0] r);\n"
         f"  altmult_add #(\n    {pl}\n  ) mac (\n    {', '.join(ports)});\nendmodule\n")
    return v, [f"set_global_assignment -name SEED {seed}"]


# --- PLL: altpll megafunction, one parameter differs per specimen
PLL_BASE = {"operation_mode": "NORMAL", "pll_type": "AUTO", "compensate_clock": "CLK0", "inclk0_input_frequency": 20000,
            "clk0_multiply_by": 2, "clk0_divide_by": 1, "clk0_phase_shift": "0", "clk0_duty_cycle": 50, "bandwidth_type": "AUTO"}
PLL_SPECS = [
    ("m3", {"clk0_multiply_by": 3}),
    ("m4", {"clk0_multiply_by": 4}),
    ("m5", {"clk0_multiply_by": 5}),
    ("m8", {"clk0_multiply_by": 8}),
    ("d2", {"clk0_divide_by": 2, "clk0_multiply_by": 2}),
    ("d3", {"clk0_divide_by": 3, "clk0_multiply_by": 2}),
    ("m4d2", {"clk0_multiply_by": 4, "clk0_divide_by": 2}),
    ("m6d3", {"clk0_multiply_by": 6, "clk0_divide_by": 3}),
    ("ph90", {"clk0_phase_shift": "1250"}),
    ("ph180", {"clk0_phase_shift": "2500"}),
    ("duty25", {"clk0_duty_cycle": 25}),
    ("duty75", {"clk0_duty_cycle": 75}),
    ("bw_low", {"bandwidth_type": "LOW"}),
    ("bw_high", {"bandwidth_type": "HIGH"}),
    ("freq25", {"inclk0_input_frequency": 40000}),
    ("freq10", {"inclk0_input_frequency": 10000, "clk0_multiply_by": 2}),
    ("c1", {"clk1_multiply_by": 1, "clk1_divide_by": 2}),
    ("c1m3", {"clk1_multiply_by": 3, "clk1_divide_by": 1}),
    ("src_bypass", {"operation_mode": "SOURCE_SYNCHRONOUS"}),
    ("no_comp", {"operation_mode": "NO_COMPENSATION", "compensate_clock": "UNUSED"}),
    ("zdb", {"operation_mode": "ZERO_DELAY_BUFFER", "compensate_clock": "CLK0"}),
    ("lvds", {"operation_mode": "LVDS", "compensate_clock": "LVDSCLK"}),
]


def pll_design(prm, seed=1):
    pl = ",\n    ".join(f".{k}({v if isinstance(v, int) else chr(34) + v + chr(34)})" for k, v in prm.items())
    pl += ',\n    .intended_device_family("Cyclone IV GX"),\n    .lpm_type("altpll")'
    nclk = 1 + max([int(k[3]) for k in prm if k.startswith("clk") and k.endswith("multiply_by")] + [0])
    outs = " ".join(f"reg q{i}; always @(posedge c[{i}]) q{i} <= ~q{i};" for i in range(nclk))
    v = ("module top(input clk, output [%d:0] q, output l);\n  wire [4:0] c;\n  %s\n  assign q = {%s};\n"
         "  altpll #(\n    %s\n  ) pll (\n    .inclk({1'b0, clk}), .clk(c), .locked(l));\nendmodule\n"
         % (nclk - 1, outs, ", ".join(f"q{i}" for i in reversed(range(nclk))), pl))
    return v, [f"set_global_assignment -name SEED {seed}"]


# --- PLL_6 / PLL_7 (MPLL: no compensation, c0 only) and fabric control ports (areset, pfdena, clkswitch, scan), one port per specimen (#175)
MP_BASE = dict(PLL_BASE, operation_mode="NO_COMPENSATION", compensate_clock="UNUSED")
MP_PORTS = {
    "ar": ({"port_areset": "PORT_USED"}, ["ar"], ".areset(ar)"),
    "pfd": ({"port_pfdena": "PORT_USED"}, ["pf"], ".pfdena(pf)"),
    "sw": ({"port_clkswitch": "PORT_USED", "switch_over_type": "MANUAL", "inclk1_input_frequency": 20000}, ["clk1", "sw"], ".clkswitch(sw)"),
    "scan": ({"port_scanclk": "PORT_USED", "port_scanclkena": "PORT_USED", "port_scandata": "PORT_USED", "port_configupdate": "PORT_USED"},
             ["sck", "sce", "sda", "cfg"], ".scanclk(sck), .scanclkena(sce), .scandata(sda), .configupdate(cfg)"),
}


def pllmp_design(port=None, seed=1, areset_reg=False):
    prm, pins, conn = MP_PORTS[port] if port else ({}, [], "")
    prm = dict(MP_BASE, **prm)
    pl = ",\n    ".join(f".{k}({v if isinstance(v, int) else chr(34) + v + chr(34)})" for k, v in prm.items())
    pl += ',\n    .intended_device_family("Cyclone IV GX"),\n    .lpm_type("altpll")'
    ins = "".join(f", input {p}" for p in pins)
    inclk = "{clk1, clk}" if "clk1" in pins else "{1'b0, clk}"
    v = (f"module top(input clk{ins}, output q0, output l);\n  wire [4:0] c;\n  reg q0r; always @(posedge c[0]) q0r <= ~q0r;\n  assign q0 = q0r;\n"
         f"  altpll #(\n    {pl}\n  ) pll (\n    .inclk({inclk}), .clk(c), .locked(l){', ' + conn if conn else ''});\nendmodule\n")
    return v, [f"set_global_assignment -name SEED {seed}"]


def specs(which):
    """[(base name, specimen name, (verilog, qsf), purpose)]"""
    out = []
    if which == "mac":
        for nm, ov in MAC_SPECS + MAC_NULL:
            base = MAC_BASE
            if nm in ("w9_in_reg",):
                base = dict(MAC_BASE, width_a=9, width_b=9, width_result=18)
            out.append(("gxhb_mac_base" if base is MAC_BASE else "gxhb_mac_base_w9", f"gxhb_mac_{nm}",
                        mac_design(base), mac_design(dict(base, **ov), seed=2 if nm == "null_seed" else 1), f"mac {nm}"))
    elif which == "macpin":
        # fixed MAC site per pair (placement otherwise moves between builds); A/B = two MAC columns
        for tag, x, y in (("a", 103, 87), ("b", 43, 87)):
            loc = [f"set_location_assignment DSPMULT_X{x}_Y{y}_N0 -to mac|auto_generated|ded_mult1|mac_mult2",
                   f"set_location_assignment DSPOUT_X{x}_Y{y}_N2 -to mac|auto_generated|ded_mult1|mac_out3"]
            for nm, ov in MAC_SPECS + MAC_NULL:
                if nm in ("two_mult_w9", "w36", "w9x18", "w9_in_reg"):
                    continue
                vb = mac_design(MAC_BASE)
                vs = mac_design(dict(MAC_BASE, **ov), seed=2 if nm == "null_seed" else 1)
                out.append((f"gxhb_macp{tag}_base", f"gxhb_macp{tag}_{nm}", (vb[0], vb[1] + loc), (vs[0], vs[1] + loc), f"mac {nm} pinned {tag}"))
    elif which == "pllsite":
        for k in range(1, 9):
            out.append(("gxhb_pll_base", f"gxhb_pllsite_{k}", pll_design(PLL_BASE),
                        (pll_design(PLL_BASE)[0], pll_design(PLL_BASE)[1] + [f"set_location_assignment PLL_{k} -to pll|auto_generated|pll1"]), f"pll at PLL_{k}"))
    elif which == "pllmp":
        loc = lambda k: [f"set_location_assignment PLL_{k} -to pll|auto_generated|pll1"]      # noqa: E731
        vb = pllmp_design()
        for k in (6, 7):
            out.append(("gxhb_pllmp_base", f"gxhb_pllmp_site{k}", (vb[0], vb[1] + loc(1)), (vb[0], vb[1] + loc(k)), f"mpll at PLL_{k}"))
        for port in MP_PORTS:
            vp = pllmp_design(port)
            out.append(("gxhb_pllmp_base", f"gxhb_pllmp_{port}", (vb[0], vb[1] + loc(1)), (vp[0], vp[1] + loc(1)), f"pll port {port}"))
    elif which == "pll":
        for nm, ov in PLL_SPECS:
            out.append(("gxhb_pll_base", f"gxhb_pll_{nm}", pll_design(PLL_BASE), pll_design(dict(PLL_BASE, **ov)), f"pll {nm}"))
        out.append(("gxhb_pll_base", "gxhb_pll_null_seed", pll_design(PLL_BASE), pll_design(PLL_BASE, seed=2), "pll null seed"))
    return out


def write_all(which):
    names = []
    for base, sp, vb, vs, purpose in specs(which):
        for nm, (v, q), pu in ((base, vb, purpose + " (base)"), (sp, vs, purpose)):
            m9.write_design(nm, v, q, pu)
            names.append(nm)
    return list(dict.fromkeys(names))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["gen", "build"])
    ap.add_argument("set", choices=["mac", "macpin", "pll", "pllsite", "pllmp"])
    ap.add_argument("--jobs", type=int, default=12)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_clean_hardblocks_build.log"), logging.StreamHandler()])
    names = write_all(a.set)
    if a.cmd == "build":
        todo = [n for n in names if not (CORPUS / n / "bitstream.rbf").exists()]
        res = m9.build(todo, min(a.jobs, 12))
        log.info("built %d, failed %s", len(todo), {n: f for n, f in res.items() if f})


if __name__ == "__main__":
    main()
