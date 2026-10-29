#!/usr/bin/env python3.15t
"""Cyclone IV GX M9K specimens, RAW cram-plane diff (issue #141). No Dec.active, no asm decode.

Pair = two designs identical except ONE thing (init bit, a parameter, a pin...). Answer = set bits
only in one plane (cycloneiv_corpus.cram_plane keys), as (frame, v).  Design prefix gxm9k_*.

  python3.15t scripts/cycloneiv_m9k.py gen   <set> [--jobs N]     # write src/ + design.toml for a set
  python3.15t scripts/cycloneiv_m9k.py build <set> [--jobs N]     # Quartus (trimmed after each build)
  python3.15t scripts/cycloneiv_m9k.py diff  <set>                # raw diffs -> tmp/cycloneiv_m9k_<set>.json
Sets: see SETS.  Log tmp/logs/cycloneiv_m9k.log.  Binding rules: docs/recovery-process.md.
"""
import argparse
import datetime
import json
import logging
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_m9k")
CORPUS = REPO / "corpus" / "cycloneiv"
DEVICE = "EP4CGX150DF31C7"
SITE = "M9K_X23_Y40_N0"
COLS = (7, 23, 36, 52, 65, 81, 94, 110)
ROWS = (1, 2, 3, 10, 20, 30, 40, 50, 60, 70, 80, 88, 89, 90)
SITES2 = [f"M9K_X{x}_Y{y}_N0" for x in COLS for y in ROWS if f"M9K_X{x}_Y{y}_N0" != SITE]   # x9 random check at each
SITES9 = ["M9K_X7_Y40_N0", "M9K_X65_Y40_N0"]   # also get an x9 build
# one site per M9K column at y=40, plus two more rows in column 23
SITES = [f"M9K_X{x}_Y40_N0" for x in (7, 36, 52, 65, 81, 94, 110)] + ["M9K_X23_Y20_N0", "M9K_X23_Y60_N0"]
BITS = 2048          # bits per mem_init parameter; 5 per M9K (4096 data + parity 512 per 2 params, linear order)


def mem_init(ones, nparams=5):
    """ones: set of linear memory-bit indices (word*width + bit) -> mem_init0..4 parameter lines."""
    out = []
    for p in range(nparams):
        val = 0
        for i in ones:
            if p * BITS <= i < (p + 1) * BITS:
                val |= 1 << (i - p * BITS)
        out.append(f".mem_init{p}({BITS}'h{val:0{BITS // 4}x})")
    return out


def ram_design(width=1, depth=8192, mode="single_port", ones=(), site=SITE, extra=None, conns=None):
    """One cycloneiv_ram_block WYSIWYG at `site`.  extra = parameter overrides {name: verilog literal}."""
    aw = (depth - 1).bit_length()
    prm = {
        "operation_mode": f'"{mode}"', "ram_block_type": '"M9K"', "logical_ram_name": '"ram"',
        "port_a_logical_ram_depth": depth, "port_a_logical_ram_width": width,
        "port_a_first_address": 0, "port_a_last_address": depth - 1, "port_a_first_bit_number": 0,
        "port_a_data_width": width, "port_a_address_width": aw, "power_up_uninitialized": '"false"',
    }
    prm.update(extra or {})
    pl = ",\n    ".join(f".{k}({v})" for k, v in prm.items()) + ",\n    " + ",\n    ".join(mem_init(set(ones)))
    v = (f"module top(input clk, input we, input [{aw - 1}:0] addr, input [{width - 1}:0] d, "
         f"output [{width - 1}:0] q);\n"
         f"  cycloneiv_ram_block #(\n    {pl}\n  ) ram (\n"
         f"    .clk0(clk), .portawe(we), .portaaddr(addr), .portadatain(d), .portadataout(q));\n"
         "endmodule\n")
    qsf = [f"set_location_assignment {site} -to ram"]
    return v, qsf


def hw_design(width, depth, ones, site=SITE, extra=None):
    """Logical (word,bit) init through altsyncram + MIF: Quartus does the (word,bit)->mem_init mapping.
    ones: set of (word, bit).  Returns (verilog, qsf, mif_text)."""
    aw = (depth - 1).bit_length()
    prm = {"operation_mode": '"SINGLE_PORT"', "width_a": width, "widthad_a": aw, "numwords_a": depth,
           "ram_block_type": '"M9K"', "init_file": '"../src/init.mif"', "outdata_reg_a": '"UNREGISTERED"',
           "lpm_type": '"altsyncram"', "power_up_uninitialized": '"FALSE"'}
    prm.update(extra or {})
    pl = ",\n    ".join(f".{k}({v})" for k, v in prm.items())
    v = (f"module top(input clk, input we, input [{aw - 1}:0] addr, input [{width - 1}:0] d, "
         f"output [{width - 1}:0] q);\n"
         f"  altsyncram #(\n    {pl}\n  ) ram (\n"
         f"    .clock0(clk), .wren_a(we), .address_a(addr), .data_a(d), .q_a(q));\n"
         "endmodule\n")
    by = {}
    for w, b in ones:
        by[w] = by.get(w, 0) | (1 << b)
    mif = [f"WIDTH={width};", f"DEPTH={depth};", "ADDRESS_RADIX=HEX;", "DATA_RADIX=BIN;", "CONTENT BEGIN",
           f"[0..{depth - 1:X}] : {'0' * width};"]
    mif += [f"{w:X} : {by[w]:0{width}b};" for w in sorted(by)]
    mif.append("END;")
    return v, [f"set_location_assignment {site} -to ram"], "\n".join(mif) + "\n"


# ── mode / control specimens: altsyncram, every port wired in every design, ONE parameter differs ──────
MODE_BASE = {"operation_mode": "SINGLE_PORT", "width_a": 16, "widthad_a": 9, "numwords_a": 512, "width_b": 16,
             "widthad_b": 9, "numwords_b": 512, "width_byteena_a": 1, "ram_block_type": "M9K",
             "outdata_reg_a": "UNREGISTERED", "outdata_reg_b": "UNREGISTERED", "address_reg_b": "CLOCK0",
             "indata_aclr_a": "NONE", "wrcontrol_aclr_a": "NONE", "address_aclr_a": "NONE", "outdata_aclr_a": "NONE",
             "byteena_aclr_a": "NONE", "address_aclr_b": "NONE", "outdata_aclr_b": "NONE", "clock_enable_input_a": "NORMAL",
             "clock_enable_output_a": "NORMAL", "clock_enable_input_b": "NORMAL", "clock_enable_output_b": "NORMAL",
             "read_during_write_mode_port_a": "NEW_DATA_NO_NBE_READ", "read_during_write_mode_mixed_ports": "DONT_CARE",
             "power_up_uninitialized": "FALSE", "byte_size": 8, "lpm_type": "altsyncram", "init_file": "../src/init.mif",
             "indata_reg_b": "CLOCK0", "wrcontrol_wraddress_reg_b": "CLOCK0", "byteena_reg_b": "CLOCK0"}
DUAL_BASE = dict(MODE_BASE, operation_mode="DUAL_PORT")
BIDIR_BASE = dict(MODE_BASE, operation_mode="BIDIR_DUAL_PORT")
# (specimen name, base mode dict, override)
MODE_SPECS = [
    ("rom", MODE_BASE, {"operation_mode": "ROM"}),
    ("dual", MODE_BASE, {"operation_mode": "DUAL_PORT"}),
    ("bidir", MODE_BASE, {"operation_mode": "BIDIR_DUAL_PORT"}),
    ("outreg_a", MODE_BASE, {"outdata_reg_a": "CLOCK0"}),
    ("rdw_old", MODE_BASE, {"read_during_write_mode_port_a": "OLD_DATA"}),
    ("rdw_dontcare", MODE_BASE, {"read_during_write_mode_port_a": "DONT_CARE"}),
    ("cke_in_bypass", MODE_BASE, {"clock_enable_input_a": "BYPASS"}),
    ("cke_out_bypass", MODE_BASE, {"clock_enable_output_a": "BYPASS"}),
    ("byteena2", MODE_BASE, {"width_byteena_a": 2}),
    ("aclr_addr_a", MODE_BASE, {"address_aclr_a": "CLEAR0"}),
    ("aclr_out_a", MODE_BASE, {"outdata_aclr_a": "CLEAR0", "outdata_reg_a": "CLOCK0"}),
    ("aclr_in_a", MODE_BASE, {"indata_aclr_a": "CLEAR0"}),
    ("aclr_wr_a", MODE_BASE, {"wrcontrol_aclr_a": "CLEAR0"}),
    ("powerup_uninit", MODE_BASE, {"power_up_uninitialized": "TRUE"}),
    ("d_outreg_b", DUAL_BASE, {"outdata_reg_b": "CLOCK0"}),
    ("d_addrreg_b_c1", DUAL_BASE, {"address_reg_b": "CLOCK1"}),
    ("d_rdw_mixed_old", DUAL_BASE, {"read_during_write_mode_mixed_ports": "OLD_DATA"}),
    ("d_cke_out_b", DUAL_BASE, {"clock_enable_output_b": "BYPASS"}),
    ("d_aclr_out_b", DUAL_BASE, {"outdata_aclr_b": "CLEAR0", "outdata_reg_b": "CLOCK0"}),
    ("d_byteena2", DUAL_BASE, {"width_byteena_a": 2}),
    ("b_outreg_a", BIDIR_BASE, {"outdata_reg_a": "CLOCK0"}),
    ("b_outreg_b", BIDIR_BASE, {"outdata_reg_b": "CLOCK0"}),
    ("b_rdw_old", BIDIR_BASE, {"read_during_write_mode_port_a": "OLD_DATA"}),
]
MODE_BASES = {"s": MODE_BASE, "d": DUAL_BASE, "b": BIDIR_BASE}


def mode_design(prm, site=SITE):
    p = dict(prm)
    mode = p["operation_mode"]
    pl = ",\n    ".join(f".{k}({v if isinstance(v, int) else chr(34) + v + chr(34)})" for k, v in p.items())
    wa, wb = p["width_a"], p["width_b"]
    ports = [".clock0(clk)", ".clocken0(ce0)", ".address_a(aa)"]
    out = {"qa": "0", "qb": "0"}
    if mode in ("SINGLE_PORT", "BIDIR_DUAL_PORT"):
        ports += [".wren_a(wea)", ".data_a(da)"]
    if mode in ("SINGLE_PORT", "ROM", "BIDIR_DUAL_PORT"):
        ports += [".q_a(qa_w)"]
        out["qa"] = "qa_w"
    if mode == "DUAL_PORT":
        ports += [".wren_a(wea)", ".data_a(da)"]
    if mode in ("DUAL_PORT", "BIDIR_DUAL_PORT"):
        ports += [".address_b(ab)", ".q_b(qb_w)"]
        out["qb"] = "qb_w"
    if mode == "BIDIR_DUAL_PORT":
        ports += [".wren_b(web)", ".data_b(db)"]
    if "CLOCK1" in p.values():
        ports += [".clock1(clk1)"]
    if "CLEAR0" in p.values():
        ports += [".aclr0(ac0)"]
    if p["width_byteena_a"] > 1:
        ports += [".byteena_a(bea)"]
    v = (f"module top(input clk, input clk1, input ce0, input ce1, input ac0, input wea, input web, "
         f"input [{p['widthad_a'] - 1}:0] aa, input [{p['widthad_b'] - 1}:0] ab, input [{wa - 1}:0] da, "
         f"input [{wb - 1}:0] db, input [{max(p['width_byteena_a'], 1) - 1}:0] bea, "
         f"output [{wa - 1}:0] qa, output [{wb - 1}:0] qb);\n"
         f"  wire [{wa - 1}:0] qa_w; wire [{wb - 1}:0] qb_w;\n"
         f"  assign qa = {out['qa']}; assign qb = {out['qb']};\n"
         f"  altsyncram #(\n    {pl}\n  ) ram (\n    {', '.join(ports)});\nendmodule\n")
    return v, [f"set_location_assignment {site} -to ram"]


def mode_mif(p):
    return (f"WIDTH={p['width_a']};\nDEPTH={p['numwords_a']};\nADDRESS_RADIX=HEX;\nDATA_RADIX=BIN;\nCONTENT BEGIN\n"
            f"[0..{p['numwords_a'] - 1:X}] : {'0' * p['width_a']};\nEND;\n")


def mode_pairs(site=SITE):
    out = []
    for nm, base, ov in MODE_SPECS:
        bk = next(k for k, v in MODE_BASES.items() if v is base)
        out.append((f"gxm9k_m_base_{bk}", f"gxm9k_m_{nm}", {"mode": base, "site": site, "width": 16},
                    {"mode": dict(base, **ov), "site": site, "width": 16}, f"mode change {nm}"))
    return out


# ── mode2: cycloneiv_ram_block directly, EVERY port wired to the same top-level nets in every design, one parameter differs ──
WY_BASE = {"operation_mode": "single_port", "ram_block_type": "M9K", "logical_ram_name": "ram", "port_a_logical_ram_depth": 512,
           "port_a_logical_ram_width": 16, "port_a_first_address": 0, "port_a_last_address": 511, "port_a_first_bit_number": 0,
           "port_a_data_width": 16, "port_a_address_width": 9, "power_up_uninitialized": "false",
           "port_a_byte_enable_mask_width": 1}
WY_OUT = dict(WY_BASE, port_a_data_out_clock="clock0")
# (name, base dict, override, extra qsf lines)
WY_SPECS = [
    ("null_rename", WY_BASE, {"logical_ram_name": "ram2"}, []),
    ("null_seed", WY_BASE, {}, ["set_global_assignment -name SEED 2"]),
    ("outclk", WY_BASE, {"port_a_data_out_clock": "clock0"}, []),
    ("outclr", WY_OUT, {"port_a_data_out_clear": "clear0"}, []),
    ("addrclr", WY_BASE, {"port_a_address_clear": "clear0"}, []),
    ("rdw_old", WY_BASE, {"port_a_read_during_write_mode": "old_data"}, []),
    ("byteena", WY_BASE, {"port_a_byte_enable_mask_width": 2, "port_a_byte_size": 8, "port_a_byte_enable_clock": "clock0"}, []),
    ("cke_in_none", WY_BASE, {"clk0_input_clock_enable": "none"}, []),
    ("cke_core_none", WY_BASE, {"clk0_core_clock_enable": "none"}, []),
    ("cke_out_none", WY_OUT, {"clk0_output_clock_enable": "none"}, []),
    ("cke_in_ena0", WY_BASE, {"clk0_input_clock_enable": "ena0"}, []),
    ("cke_core_ena0", WY_BASE, {"clk0_core_clock_enable": "ena0"}, []),
    ("cke_out_ena0", WY_OUT, {"clk0_output_clock_enable": "ena0"}, []),
    ("wrclk", WY_BASE, {"port_a_write_enable_clock": "clock0"}, []),
    ("powerup", WY_BASE, {"power_up_uninitialized": "true"}, []),
]
WY_BANDS = {"frames": None}


def wy_design(prm, extra_qsf, site=SITE):
    pl = ",\n    ".join(f".{k}({v if isinstance(v, int) else chr(34) + v + chr(34)})" for k, v in prm.items())
    vals = list(prm.values())
    ports = [".clk0(clk)", ".ena0(ce0)", ".portaaddr(aa)", ".portadatain(da)", ".portadataout(qa)",
             f".portabyteenamasks(bea[{prm['port_a_byte_enable_mask_width'] - 1}:0])"]
    if prm["operation_mode"] != "rom":
        ports.append(".portawe(we)")
    if "clear0" in vals:
        ports.append(".clr0(ac0)")
    v = ("module top(input clk, input ce0, input ac0, input we, input [8:0] aa, input [15:0] da, input [1:0] bea, output [15:0] qa);\n"
         f"  cycloneiv_ram_block #(\n    {pl}\n  ) ram (\n    {', '.join(ports)});\nendmodule\n")
    return v, [f"set_location_assignment {site} -to ram"] + list(extra_qsf)


def wy_pairs(site=SITE):
    out = []
    st = "" if site == SITE else "_" + site.replace("M9K_", "").lower()
    for nm, base, ov, xq in WY_SPECS:
        bk = "o" if base is WY_OUT else "s"
        out.append((f"gxm9k_w{st}_base_{bk}", f"gxm9k_w{st}_{nm}", {"wy": base, "site": site, "width": 16, "xq": []},
                    {"wy": dict(base, **ov), "site": site, "width": 16, "xq": xq}, f"wysiwyg knob {nm}"))
    return out


def write_design(name, v, qsf, purpose, mif=None):
    d = CORPUS / name
    if (d / "bitstream.rbf").exists():
        return
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(v)
    if mif is not None:
        (d / "src" / "init.mif").write_text(mif)
    q = list(qsf) + ([] if any("-name SEED" in x for x in qsf) else ["set_global_assignment -name SEED 1"]) + [
        'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "{purpose}"\nexercises = {fz.toml_list(["m9k"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


def sets():
    """{set: [(base, specimen, design-kwargs-base, design-kwargs-specimen, purpose)]}"""
    s = {}
    p0 = []
    for r in range(4):                      # r0 = first build, r1..r3 = rebuilds of the same pair
        p0.append((f"gxm9k_p0_base_r{r}", f"gxm9k_p0_w0b0_r{r}", {}, {"ones": {0}}, "word0 bit0 init 1"))
    s["p0"] = p0
    return s


DEPTH = {1: 8192, 2: 4096, 4: 2048, 8: 1024, 9: 1024, 16: 512, 18: 512, 32: 256, 36: 256}


def data_pairs(width, items, site=SITE, tag="d"):
    """Shared all-zero base + one specimen per (word, bit); init bit at linear index word*width+bit."""
    depth = DEPTH[width]
    base = f"gxm9k_{tag}{width}_base"
    out = [(base, f"gxm9k_{tag}{width}_w{w}b{b}", {"width": width, "depth": depth, "site": site},
            {"width": width, "depth": depth, "site": site, "ones": {w * width + b}}, f"init word {w} bit {b}")
           for w, b in items]
    return out


def bin_pairs(width, site=SITE):
    """Binary-coded init: specimen k sets cell c iff bit k of (c+1) is set; shared all-zero base."""
    n = DEPTH[width] * width
    nb = n.bit_length()          # codes 1..n
    st = "" if site == SITE else "_" + site.replace("M9K_", "").lower()
    base = f"gxm9k_b{width}{st}_base"
    kw = {"width": width, "depth": DEPTH[width], "site": site}
    return [(base, f"gxm9k_b{width}{st}_k{k}", dict(kw),
             dict(kw, ones={c for c in range(n) if ((c + 1) >> k) & 1}), f"bincode bit {k}") for k in range(nb)]


def hw_probe_items(width):
    """words 0,1 x bit indices 0 and powers of two below width, plus the top bit."""
    bs = sorted({0, width - 1} | {1 << i for i in range(6) if (1 << i) < width})
    return [(w, b) for w in (0, 1) for b in bs]


def hw_pairs(width, items, site=SITE, tag="h"):
    """Logical (word,bit) init through altsyncram+MIF; shared all-zero base."""
    depth = DEPTH[width]
    kb = {"width": width, "depth": depth, "site": site, "hw": True}
    return [(f"gxm9k_{tag}{width}_base", f"gxm9k_{tag}{width}_w{w}b{b}", dict(kb), dict(kb, ones={(w, b)}),
             f"logical word {w} bit {b} (altsyncram MIF)") for w, b in items]


def hw_rand_ones(width, seed, n=150):
    import random
    r = random.Random(seed)
    return set((r.randrange(DEPTH[width]), r.randrange(width)) for _ in range(n))


def hw_rand_pairs(width, seed, site=SITE, tag="h"):
    kb = {"width": width, "depth": DEPTH[width], "site": site, "hw": True}
    return [(f"gxm9k_{tag}{width}_base", f"gxm9k_{tag}R{width}_s{seed}", dict(kb),
             dict(kb, ones=hw_rand_ones(width, seed)), f"150 random logical (word,bit) seed {seed}")]


def hw_bin_pairs(width, site=SITE, tag="h"):
    """Binary-coded logical init: specimen k sets (word,bit) iff bit k of (word*width+bit+1) is set."""
    n = DEPTH[width] * width
    kb = {"width": width, "depth": DEPTH[width], "site": site, "hw": True}
    return [(f"gxm9k_{tag}b{width}_base", f"gxm9k_{tag}b{width}_k{k}", dict(kb),
             dict(kb, ones={divmod(c, width) for c in range(n) if ((c + 1) >> k) & 1}), f"hw bincode bit {k}")
            for k in range(n.bit_length())]


def rand_ones(width, seed):
    import random
    n = DEPTH[width] * width
    return set(random.Random(seed).sample(range(n), n // 2))


def rand_pairs(width, seed, site=SITE):
    kw = {"width": width, "depth": DEPTH[width], "site": site}
    st = "" if site == SITE else "_" + site.replace("M9K_", "").lower()
    return [(f"gxm9k_b{width}{st}_base", f"gxm9k_r{width}{st}_s{seed}", dict(kw), dict(kw, ones=rand_ones(width, seed)),
             f"random half-filled init seed {seed}")]


def predict(width, sp):
    """Predicted only_spec set from the located-cell map; None if the pair is not predictable."""
    mp = REPO / "tmp" / f"cycloneiv_m9k_map{width}.json"
    m = re.match(rf"gxm9k_hR{width}_s(\d+)$", sp)
    if m:
        mp = REPO / "tmp" / f"cycloneiv_m9k_hmap{width}.json"
        if not mp.exists():
            return None
        cells = {int(k): tuple(v) for k, v in json.loads(mp.read_text())["cells"].items()}
        return {cells[w * width + b] for w, b in hw_rand_ones(width, int(m[1]))}
    if not mp.exists():
        return None
    cells = {int(k): tuple(v) for k, v in json.loads(mp.read_text())["cells"].items()}
    m = re.match(rf"gxm9k_d{width}_w(\d+)b(\d+)$", sp)
    if m:
        return {cells[int(m[1]) * width + int(m[2])]}
    m = re.match(rf"gxm9k_r{width}_s(\d+)$", sp)
    if m:
        return {cells[c] for c in rand_ones(width, int(m[1]))}
    return None


def bin_decode(width, rep):
    """rep: {spec: {only_spec: [(f, v)]}} -> {code: (f, v)} + leftovers.  v >= 6344: lane tail / CRC bytes, masked."""
    n = DEPTH[width] * width
    code = {}
    for sp, r in rep.items():
        k = int(sp.rsplit("_k", 1)[1])
        for f, v in r["only_spec"]:
            code[(f, v)] = code.get((f, v), 0) | (1 << k)
        assert not r["only_base"], f"{sp}: bits only in base {r['only_base'][:4]}"
    cells, masked, bad = {}, [], []
    for (f, v), c in code.items():
        if v >= 6344:
            masked.append((f, v, c))
        elif 1 <= c <= n and c - 1 not in cells:
            cells[c - 1] = (f, v)
        else:
            bad.append((f, v, c))
    return cells, masked, bad


def bits(name):
    return set(cc.load_plane_only(name).keys.tolist())


def fv(k):
    return divmod(k, 6368)


def trim(n):
    for sub in ("quartus/db", "quartus/incremental_db"):
        shutil.rmtree(CORPUS / n / sub, ignore_errors=True)
    (CORPUS / n / "quartus" / "build.rbf").unlink(missing_ok=True)


def prune(n):
    """Diff recorded: drop bitstream + postfit + logs, keep rcf/toml/src."""
    d = CORPUS / n
    for f in ("bitstream.rbf", "postfit.vo", "fit.rpt", "build.pin"):
        (d / f).unlink(missing_ok=True)
    shutil.rmtree(d / "quartus", ignore_errors=True)
    shutil.rmtree(d / "logs", ignore_errors=True)


def build(names, jobs):
    def one(n):
        f = fz.build_one(n)
        trim(n)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        return n, f
    import build_pool
    return dict(build_pool.map_adaptive(one, names, per_job_gb=1.2, max_workers=jobs or None))


def fit_laws():
    """Bit-linear fits (pattern_matchers.BitLinearLaw) of the hardware cell maps, held-out checked."""
    import numpy as np
    import pattern_matchers as pm
    L = lambda n: {int(k): tuple(v) for k, v in json.loads((REPO / "tmp" / n).read_text())["cells"].items()}  # noqa: E731
    h9 = L("cycloneiv_m9k_hmap9.json")
    out = {}
    for name, cells in (("x9-parity", {c // 9: v for c, v in h9.items() if c % 9 == 8}),):
        idx = sorted(cells)
        hold = set(np.random.default_rng(1).choice(idx, size=len(idx) // 5, replace=False).tolist())
        mt = pm.BitLinearLaw(nbits=10)
        cand = mt.propose({"subject": f"M9K:{name}", "index_to_cell": {str(i): list(cells[i]) for i in idx if i not in hold},
                           "parents": [], "scope": {}})[0]
        miss = sum(1 for i in hold if mt.predict(cand, i) != list(cells[i]))
        out[name] = {"law": cand.law["text"], "train": cand.fit, "held_out": len(hold), "held_out_miss": miss}
    return out


def register():
    """Evidence rows into the family database (idempotent): new pair JSONs as specimen-pairs, maps and laws as derived tables."""
    import dbtools
    import schema as S
    from provenance import evidence_io as E
    import db
    S.init()
    commit = E.git_head(REPO)
    gen = "scripts/cycloneiv_m9k.py"
    n = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for pth in sorted((REPO / "tmp").glob("cycloneiv_m9k_*.json")):
            rel = pth.relative_to(REPO)
            d = json.loads(pth.read_text())
            if "cells" in d and "width" in d:
                E.record_decode(conn, "cycloneiv", "EP4CGX150", pth.name, {"file": d}, commit, str(rel), generator=gen,
                                kind="derived-table", n_objects=len(d["cells"]))
                n += 1
            elif E.import_json_file(conn, str(pth), "cycloneiv", "EP4CGX150", 6368, commit, gen, str(REPO)) is not None:
                n += 1
        conn.execute(S.evidence.delete().where(S.evidence.c.name.in_(["m9k-hw-laws", "m9k-site-offsets"])))   # recomputed rows
        so = site_offsets()
        E.record_decode(conn, "cycloneiv", "EP4CGX150", "m9k-site-offsets", {"file": so}, commit, "scripts/cycloneiv_m9k.py site_offsets",
                        generator=gen, kind="derived-table", n_objects=len(so))
        conn.execute(S.evidence.delete().where(S.evidence.c.name == "m9k-control-cells"))
        cc_ = control_cells()
        E.record_decode(conn, "cycloneiv", "EP4CGX150", "m9k-control-cells", {"file": cc_}, commit, "scripts/cycloneiv_m9k.py control_cells",
                        generator=gen, kind="derived-table", n_objects=len({c for v in cc_["cells_by_knob"].values() for c in v["set"] + v["clear"]}))
        log.info("control cells %s", cc_)
        laws = fit_laws()
        E.record_decode(conn, "cycloneiv", "EP4CGX150", "m9k-hw-laws", {"file": laws}, commit, "scripts/cycloneiv_m9k.py fit_laws",
                        generator=gen, kind="derived-table", n_objects=len(laws))
    log.info("registered %d files into %s; laws %s", n, dbtools.family_db("cycloneiv"), laws)


def stab(frac=0.1, seed=7):
    """Rebuild ~frac of the hardware-map specimens under a new name; raw diff vs the recorded base must be identical."""
    import random
    reps = {}
    for pth in sorted((REPO / "tmp").glob("cycloneiv_m9k_hw*.json")):
        reps.update(json.loads(pth.read_text()))
    names = sorted(reps)
    pick = random.Random(seed).sample(names, max(1, int(len(names) * frac)))
    for n in pick:
        d = CORPUS / (n + "_rb")
        (d / "src").mkdir(parents=True, exist_ok=True)
        for f in (CORPUS / n / "src").iterdir():
            shutil.copy(f, d / "src" / f.name)
        shutil.copy(CORPUS / n / "design.toml", d / "design.toml")
    res = build([n + "_rb" for n in pick if not (CORPUS / (n + "_rb") / "bitstream.rbf").exists()], 0)
    same = 0
    for n in pick:
        b = bits(reps[n]["base"])
        got = [fv(k) for k in sorted(bits(n + "_rb") - b)]
        ok = got == [tuple(x) for x in reps[n]["only_spec"]]
        same += ok
        prune(n + "_rb")
        log.info("STAB %s: identical=%s", n, ok)
    log.info("STAB %d / %d rebuilt specimens identical (fail %s)", same, len(pick), [k for k, v in res.items() if v])
    return same, len(pick)


def site_offsets():
    """Per site: predict the random-init diff from the X23Y40 map + ONE (frame,v) offset; log exact / mismatching sites."""
    res = {}
    for pth in sorted((REPO / "tmp").glob("cycloneiv_m9k_rand*d_x*.json")):
        m = re.match(r"cycloneiv_m9k_rand(\d+)d_(x\d+_y\d+)_n\d+\.json", pth.name)
        w, site = int(m[1]), m[2]
        mp = REPO / "tmp" / f"cycloneiv_m9k_map{w}.json"
        cells = {int(k): tuple(v) for k, v in json.loads(mp.read_text())["cells"].items()}
        for sp, r in json.loads(pth.read_text()).items():
            seed = int(sp.rsplit("_s", 1)[1])
            pred = sorted(cells[c] for c in rand_ones(w, seed))
            got = sorted(tuple(x) for x in r["only_spec"] if x[1] < 6344)
            if not got or r["only_base"]:
                res[f"{site}_x{w}"] = {"exact": False, "note": "empty diff or base-only bits", "n_got": len(got)}
                continue
            df, dv = got[0][0] - pred[0][0], got[0][1] - pred[0][1]
            mine = set((f + df, v + dv) for f, v in pred)
            res[f"{site}_x{w}"] = {"exact": mine == set(got), "offset": [df, dv], "n": len(got),
                                   "missing": len(mine - set(got)), "extra": len(set(got) - mine)}
            log.info("SITE %s x%d: %s", site, w, res[f"{site}_x{w}"])
    return res


CFG_FRAMES = (1103, 1108, 1109, 1110, 1111)    # frames (X23 column) where the isolated control bits sit; others in the band are routing


def control_cells():
    """Knob bits replicated at the 3 mode2 sites: {knob: {"set": [(f,v)], "clear": [(f,v)]}} in X23Y40 coordinates, plus sites."""
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of("EP4CGX150"))
    sites = {"x23_y40": (23, 40), "x65_y40": (65, 40), "x7_y60": (7, 60)}
    reps = {}
    for key in sites:
        suf = "" if key == "x23_y40" else "_" + key + "_n0"
        reps[key] = json.loads((REPO / "tmp" / f"cycloneiv_m9k_mode216d{suf}.json").read_text())

    def cfg(rep, dfv, which):
        df, dv = dfv
        return {(f - df, v - dv) for f, v in map(tuple, rep[which]) if f - df in CFG_FRAMES and 2752 <= v - dv < 2822}
    out = {}
    for nm, *_ in WY_SPECS:
        if nm.startswith("null"):
            continue
        sets = {w: None for w in ("only_spec", "only_base")}
        for w in sets:
            for key, (x, y) in sites.items():
                st = "" if key == "x23_y40" else "_" + key + "_n0"
                off = (g.FX[x] - g.FX[23], g.vpitch * (y - 40))
                c = cfg(reps[key][f"gxm9k_w{st}_{nm}"], off, w)
                sets[w] = c if sets[w] is None else sets[w] & c
        if sets["only_spec"] or sets["only_base"]:
            out[nm] = {"set": sorted(sets["only_spec"]), "clear": sorted(sets["only_base"])}
    return {"cells_by_knob": out, "sites": sorted(sites.values())}


def group_key(pr, setname, tag):
    """(json file, width, map file | None) a pair belongs to."""
    b, sp, kb = pr[0], pr[1], pr[2]
    w = kb["width"]
    site = kb.get("site", SITE)
    st = "" if site == SITE else "_" + site.replace("M9K_", "").lower()
    if setname in ("rand", "bincode", "data", "p0", "mode", "mode2", "sites", "sites2"):
        kind = "rand" if setname in ("sites", "sites2") else setname
    else:
        kind = "hwbin" if re.search(r"_k\d+$", sp) else "hwrand" if "R" in sp.split("_")[1] else "hwprobe"
    fname = f"cycloneiv_m9k_{kind}{w}{tag if not kb.get('hw') else 'h'}{st}.json"
    hw = "h" if kb.get("hw") else ""
    mapname = f"cycloneiv_m9k_{hw}map{w}{st}.json" if kind in ("bincode", "hwbin") else None
    return fname, w, mapname


def diff_group(pairs, out, width, mapname, keep):
    rep = json.loads(out.read_text()) if out.exists() else {}
    cache = {}
    for i, (b, sp, *_) in enumerate(pairs):
        if sp in rep:
            continue
        if b not in cache:
            cache[b] = bits(b)
        A, B = cache[b], bits(sp)
        rep[sp] = {"base": b, "only_base": [fv(k) for k in sorted(A - B)],
                   "only_spec": [fv(k) for k in sorted(B - A)]}
        pr = predict(width, sp)
        if pr is not None:
            got = {tuple(x) for x in rep[sp]["only_spec"]}
            rep[sp]["predicted_hit"] = bool(got == pr and not rep[sp]["only_base"])
            rep[sp]["pred_missing"], rep[sp]["pred_extra"] = len(pr - got), len(got - pr)
            log.info("PREDICT %s: hit=%s missing %d extra %d (of %d)", sp, rep[sp]["predicted_hit"],
                     len(pr - got), len(got - pr), len(pr))
        log.info("%s vs %s: only-base %s only-spec %s", b, sp, rep[sp]["only_base"][:8], rep[sp]["only_spec"][:8])
        if i >= keep:
            prune(sp)
    out.write_text(json.dumps(rep))
    if mapname:
        cells, masked, bad = bin_decode(width, rep)
        n = DEPTH[width] * width
        log.info("%s: %d / %d cells located, masked CRC/tail %d, unattributed %d %s", mapname, len(cells), n,
                 len(masked), len(bad), bad[:6])
        (REPO / "tmp" / mapname).write_text(json.dumps(
            {"width": width, "cells": {str(c): fvv for c, fvv in sorted(cells.items())},
             "masked": masked, "unattributed": bad}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["gen", "build", "diff", "register", "stab", "offsets"])
    ap.add_argument("set", help="named set, or 'data'")
    ap.add_argument("--jobs", type=int, default=0, help="0 = pool default (cores-2)")
    ap.add_argument("--width", type=int, default=1)
    ap.add_argument("--items", default="", help="data set: word:bit,word:bit,...")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--tag", default="")
    ap.add_argument("--keep", type=int, default=0, help="diff: keep bitstreams of the first N specimens")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_m9k.log"),
                                  logging.StreamHandler()])
    if a.cmd == "offsets":
        site_offsets()
        return
    if a.cmd == "stab":
        stab()
        return
    if a.cmd == "register":
        register()
        return
    tag = a.tag or ("h" if a.set.startswith("hw") else "d")
    if a.set == "rand":
        pairs = rand_pairs(a.width, int(a.items), a.site)
    elif a.set == "hwprobe":
        pairs = hw_pairs(a.width, hw_probe_items(a.width), a.site, tag)
    elif a.set == "hwrand":
        pairs = hw_rand_pairs(a.width, int(a.items), a.site, tag)
    elif a.set == "hwall":
        pairs = [x for w in (1, 2, 4, 8, 9, 16, 18, 32, 36)
                 for x in hw_bin_pairs(w, a.site, tag) + hw_rand_pairs(w, 1, a.site, tag) + hw_rand_pairs(w, 2, a.site, tag)
                 + hw_pairs(w, hw_probe_items(w), a.site, tag)]
    elif a.set == "mode":
        pairs = mode_pairs(a.site)
    elif a.set == "mode2":
        pairs = wy_pairs(a.site)
    elif a.set == "sites2":
        pairs = [x for site in SITES2 for x in rand_pairs(9, 1, site)]
    elif a.set == "sites":
        pairs = [x for site in SITES for w in ((1, 9) if site in SITES9 else (1,)) for x in rand_pairs(w, 1, site)]
    elif a.set == "hwbin":
        pairs = hw_bin_pairs(a.width, a.site, tag)
    elif a.set == "bincode":
        pairs = bin_pairs(a.width, a.site)
    elif a.set == "data":
        pairs = data_pairs(a.width, [tuple(map(int, i.split(":"))) for i in a.items.split(",")], a.site, tag)
    else:
        pairs = sets()[a.set]
    names = list(dict.fromkeys(n for p in pairs for n in p[:2]))
    if a.cmd in ("gen", "build"):
        for b, sp, kb, ks, purpose in pairs:
            for nm, kw, pu in ((b, kb, purpose + " (base)"), (sp, ks, purpose)):
                if kw.get("wy"):
                    write_design(nm, *wy_design(kw["wy"], kw["xq"], kw["site"]), pu)
                elif kw.get("mode"):
                    write_design(nm, *mode_design(kw["mode"], kw["site"]), pu, mode_mif(kw["mode"]))
                elif kw.get("hw"):
                    v, q, mif = hw_design(kw["width"], kw["depth"], kw.get("ones", ()), kw.get("site", SITE))
                    write_design(nm, v, q, pu, mif)
                else:
                    write_design(nm, *ram_design(**kw), pu)
    if a.cmd == "build":
        todo = [n for n in names if not (CORPUS / n / "bitstream.rbf").exists()]
        res = build(todo, a.jobs)
        log.info("built %d, failed %s", len(todo), [n for n, f in res.items() if f])
    if a.cmd == "diff":
        groups = {}
        for pr in pairs:
            groups.setdefault(group_key(pr, a.set, tag), []).append(pr)
        for (fname, width, mapname), gp in groups.items():
            diff_group(gp, REPO / "tmp" / fname, width, mapname, a.keep)


if __name__ == "__main__":
    main()
