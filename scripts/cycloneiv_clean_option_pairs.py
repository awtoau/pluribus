#!/usr/bin/env python3.15t
"""Option-register pair builds on EP4CGX150: which of the 160 option bits (sof tag 18) does each QSF device option change?  Black box:
quartus_map/fit/asm/cpf only (#169, docs/cycloneiv-clean-options.md).

Method (docs/recovery-process.md): a pair = base build + ONE global QSF assignment (or one JTAG primitive for the design pairs).
Two base designs (comb `min`, registered `reg`, different pin) so a context-dependent option shows up as a base disagreement.
The option register is one global 160-bit register, not an array of tiles: the grid sampling plan does not apply; the two bases are the area proxy.
Diffs: sof tag 18 (value + flag halves), tag 19 (USERCODE), rbf header frame 0 (first 75 B), tag 17 CRAM (cell list, for the JTAG interface).

  python3.15t scripts/cycloneiv_clean_option_pairs.py build [--jobs 12] [--only ID,ID]
  python3.15t scripts/cycloneiv_clean_option_pairs.py analyse      # -> databases/cycloneiv/option_pairs.json
Log: tmp/logs/cycloneiv_clean_option_pairs.log
"""
import argparse
import collections
import gzip
import json
import logging
import os
import shutil
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "option_pairs")
PAIRS_DB = os.path.join(REPO, "databases", "cycloneiv", "option_pairs.json")
IO_PINS = os.path.join(REPO, "tmp", "cycloneiv_clean", "io_pairs", "pins.json")
DEVICE = "EP4CGX150DF31C7"
# Quartus step backstops = io_pairs pilot (3x worst of 50 builds at 12 parallel jobs); stall guard 60 s in fz.run
LIMITS = {"quartus_map": 63, "quartus_fit": 75, "quartus_asm": 30, "quartus_cpf": 8}
JOB_GB_NAME = "quartus_chain_cyc4"
HEADER_BYTES = 75              # source: docs/cycloneiv-address-spaces.md 2.3, frame 0 = sync + 40 option lane bytes + CRC (rbf bytes 32..74)
SOF_TAG_OPTION, SOF_TAG_USERCODE, SOF_TAG_CRAM = 18, 19, 17
log = logging.getLogger("option_pairs")

BASES = {
    "min": ("output p, input a, input c, input e, output y", "assign p = a & c; assign y = a ^ c ^ e;", "A10"),
    "reg": ("output p, input a, input c, input e, output y", "reg r; always @(posedge c) r <= a ^ e; assign p = r; assign y = a ^ c ^ e;", "A12"),
}
# design pairs: one hard primitive added to the base design, its outputs folded into extra output `z` so it survives the optimizer
JTAG_OUTS = ("tmsutap", "tckutap", "tdiutap", "shiftuser", "clkdruser", "updateuser", "runidleuser", "usr1user")   # source: cycloneiv_atoms.v cycloneiv_jtag outputs
DESIGNS = {
    "jtag_user_in": "cycloneiv_jtag jt (.tdouser(a), .tdo(tdo_pin), .tms(), .tck(), .tdi());\nassign z = e;\n",
    "jtag_all_out": "wire " + ", ".join(f"o_{n}" for n in JTAG_OUTS) + ";\ncycloneiv_jtag jt (.tdo(tdo_pin), .tms(), .tck(), .tdi(), "
                    + ", ".join(f".{n}(o_{n})" for n in JTAG_OUTS) + ");\nassign z = " + " ^ ".join(f"o_{n}" for n in JTAG_OUTS) + ";\n",
    "jtag_all": "wire " + ", ".join(f"o_{n}" for n in JTAG_OUTS) + ";\ncycloneiv_jtag jt (.tdouser(a), .tdo(tdo_pin), .tms(), .tck(), .tdi(), "
                + ", ".join(f".{n}(o_{n})" for n in JTAG_OUTS) + ");\nassign z = " + " ^ ".join(f"o_{n}" for n in JTAG_OUTS) + ";\n",
}
DESIGNS["jtag_user_reg"] = "reg r; always @(posedge c) r <= a ^ e;\ncycloneiv_jtag jt (.tdouser(r), .tdo(tdo_pin), .tms(), .tck(), .tdi());\nassign z = e;\n"
DESIGNS["jtag_user_lut"] = "cycloneiv_jtag jt (.tdouser(a & c), .tdo(tdo_pin), .tms(), .tck(), .tdi());\nassign z = e;\n"
for _n in JTAG_OUTS:
    DESIGNS[f"jtag_out_{_n}"] = f"wire t; cycloneiv_jtag jt (.{_n}(t), .tdo(tdo_pin), .tms(), .tck(), .tdi());\nassign z = t;\n"
# crc block (ASM_OPTION_REG_USE_ERROR_DETECT / SELECT_CRC_FREQUENCY_DIVIDER are atom-driven): oscillator_divider = CRC clock divisor
for _d in (1, 2, 4, 8, 16, 32, 64, 128, 256):
    DESIGNS[f"crcblock_div{_d}"] = ("wire ce, ro; cycloneiv_crcblock crc (.clk(c), .shiftnld(e), .ldsrc(a), .crcerror(ce), .regout(ro));\n"
                                    f"defparam crc.oscillator_divider = {_d};\nassign z = ce ^ ro;\n")
DESIGNS["crcblock_loc"] = ("wire ce, ro; cycloneiv_crcblock crc (.clk(c), .shiftnld(e), .ldsrc(a), .crcerror(ce), .regout(ro));\n"
                           "defparam crc.oscillator_divider = 1;\ndefparam crc.crc_deduce_error_location = \"true\";\nassign z = ce ^ ro;\n")
# source: libdb_acf.so setting-name strings (ACF names for the option classes in libcomp_asm ASM_OPTION_REG_*, docs/cycloneiv-clean-options.md);
# (id, qsf assignment name, value).  Names rejected by the fitter / ignored by this family are recorded, not hidden.
SETTINGS = (
    ("init_done_on", "ENABLE_INIT_DONE_OUTPUT", "ON"),
    ("user_clk_on", "USER_START_UP_CLOCK", "ON"),
    ("auto_restart_on", "AUTO_RESTART_CONFIGURATION", "ON"),
    ("release_clears_on", "RELEASE_CLEARS_BEFORE_TRI_STATES", "ON"),
    ("dev_reset_on", "ENABLE_DEVICE_WIDE_RESET", "ON"),
    ("dev_oe_on", "ENABLE_DEVICE_WIDE_OE", "ON"),
    ("crc_check_on", "CRC_ERROR_CHECKING", "ON"),
    ("stratix_crc_on", "STRATIX_CRC_ERROR_CHECKING", "ON"),
    ("ed_crc_on", "ENABLE_ED_CRC_CHECK", "ON"),
    ("crc_pin_on", "ENABLE_CRC_ERROR_PIN", "ON"),
    ("crc_div_2", "ERROR_CHECK_FREQUENCY_DIVISOR", "2"),
    ("crc_div_4", "ERROR_CHECK_FREQUENCY_DIVISOR", "4"),
    ("crc_div_8", "ERROR_CHECK_FREQUENCY_DIVISOR", "8"),
    ("crc_div_16", "ERROR_CHECK_FREQUENCY_DIVISOR", "16"),
    ("crc_div_32", "ERROR_CHECK_FREQUENCY_DIVISOR", "32"),
    ("crc_div_64", "ERROR_CHECK_FREQUENCY_DIVISOR", "64"),
    ("crc_div_128", "ERROR_CHECK_FREQUENCY_DIVISOR", "128"),
    ("crc_div_256", "ERROR_CHECK_FREQUENCY_DIVISOR", "256"),
    ("nceo_io", "CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION", '"USE AS REGULAR IO"'),
    ("nceo_out_on", "ENABLE_NCEO_OUTPUT", "ON"),
    ("nce_pin_on", "ENABLE_NCE_PIN", "ON"),
    ("jtag_bst_off", "ENABLE_JTAG_BST_SUPPORT", "OFF"),
    ("jtag_bst_on", "ENABLE_JTAG_BST_SUPPORT", "ON"),
    ("jtag_share_on", "ENABLE_JTAG_PIN_SHARING", "ON"),
    ("nconfig_core_on", "ENABLE_NCONFIG_FROM_CORE", "ON"),
    ("oct_done_on", "ENABLE_OCT_DONE", "ON"),
    ("cvp_confdone_on", "ENABLE_CVP_CONFDONE", "ON"),
    ("cvpcie_confdone_on", "ENABLE_CVPCIE_CONFDONE", "ON"),
    ("scrub_on", "INTERNAL_SCRUBBING", "ON"),
    ("pr_pins_on", "ENABLE_PR_PINS", "ON"),
    ("spi_check_on", "ENABLE_SPI_MODE_CHECK", "ON"),
    ("spi_tristate_on", "TRI_STATE_SPI_PINS", "ON"),
    ("spi_pullup_on", "EN_SPI_IO_WEAK_PULLUP", "ON"),
    ("scheme_ps", "CYCLONEIII_CONFIGURATION_SCHEME", '"PASSIVE SERIAL"'),
    ("scheme_fpp", "CYCLONEIII_CONFIGURATION_SCHEME", '"FAST PASSIVE PARALLEL"'),
    ("scheme_ap", "CYCLONEIII_CONFIGURATION_SCHEME", '"ACTIVE PARALLEL"'),
    ("scheme_as", "CYCLONEIII_CONFIGURATION_SCHEME", '"ACTIVE SERIAL"'),
    ("scheme_jtag", "CYCLONEIII_CONFIGURATION_SCHEME", '"INTERNAL CONFIGURATION"'),
    ("cfg_clk_div_2", "CONFIGURATION_CLOCK_DIVISOR", "2"),
    ("cfg_clk_div_4", "CONFIGURATION_CLOCK_DIVISOR", "4"),
    ("cfg_clk_freq_40", "CONFIGURATION_CLOCK_FREQUENCY", '"40 MHz"'),
    ("cfg_clk_freq_20", "CONFIGURATION_CLOCK_FREQUENCY", '"20 MHz"'),
    ("cfg_dev_epcs", "USE_CONFIGURATION_DEVICE", "ON"),
    ("cfg_dev_epcs128", "STRATIXII_CONFIGURATION_DEVICE", "EPCS128"),
    ("cfg_vccio_18", "CONFIGURATION_VCCIO_LEVEL", '"1.8V"'),
    ("cfg_vccio_33", "CONFIGURATION_VCCIO_LEVEL", '"3.3V"'),
    ("force_vccio_on", "FORCE_CONFIGURATION_VCCIO", "ON"),
    ("usercode_aabb", "STRATIX_JTAG_USER_CODE", "AABBCCDD"),
    ("checksum_usercode", "USE_CHECKSUM_AS_USERCODE", "ON"),
    ("bitstream_decomp_on", "ON_CHIP_BITSTREAM_DECOMPRESSION", "ON"),
    ("compress_on", "GENERATE_RBF_FILE", "ON"),
    ("pof_verify_prot", "POF_VERIFY_PROTECT", "ON"),
    ("security_bit_on", "SECURITY_BIT", "ON"),
    ("reserve_data0_io", "RESERVE_DATA0_AFTER_CONFIGURATION", '"USE AS REGULAR IO"'),
    ("reserve_dclk_io", "RESERVE_DCLK_AFTER_CONFIGURATION", '"USE AS REGULAR IO"'),
    ("reserve_asdo_io", "RESERVE_ASDO_AFTER_CONFIGURATION", '"USE AS REGULAR IO"'),
    ("reserve_flash_nce_io", "RESERVE_FLASH_NCE_AFTER_CONFIGURATION", '"USE AS REGULAR IO"'),
    ("reserve_unused_gnd", "RESERVE_ALL_UNUSED_PINS", '"AS OUTPUT DRIVING GROUND"'),
    ("boot_sel_on", "ENABLE_BOOT_SEL_PIN", "ON"),
    ("asmi_flash_loader_on", "ENABLE_ASMI_FOR_FLASH_LOADER", "ON"),
    ("ext_flash_fallback_on", "ENABLE_FALLBACK_TO_EXTERNAL_FLASH", "ON"),
    ("adv_seu_on", "ENABLE_ADV_SEU_DETECTION", "ON"),
    ("use_conf_done_on", "USE_CONF_DONE", "ON"),
    ("lowvolt_on", "ENABLE_LOW_VOLT_MODE", "ON"),
    ("as_clk_12_5", "ACTIVE_SERIAL_CLOCK", "FREQ_12_5MHz"),
    ("as_clk_20", "ACTIVE_SERIAL_CLOCK", "FREQ_20MHz"),
    ("as_clk_25", "ACTIVE_SERIAL_CLOCK", "FREQ_25MHz"),
    ("as_clk_40", "ACTIVE_SERIAL_CLOCK", "FREQ_40MHz"),
    ("as_clk_50", "ACTIVE_SERIAL_CLOCK", "FREQ_50MHz"),
    ("as_clk_100", "ACTIVE_SERIAL_CLOCK", "FREQ_100MHz"),
    ("as_clk_clkusr", "ACTIVE_SERIAL_CLOCK", "CLKUSR"),
)


# second-level pairs (id, assignments, reference id): the reference carries the context assignment, the pair adds ONE more
CHAINS = (
    ("auto_restart_off", (("AUTO_RESTART_CONFIGURATION", "OFF"),), "BASE"),
    ("usercode_chk_off", (("USE_CHECKSUM_AS_USERCODE", "OFF"),), "BASE"),
    ("usercode_chk_off_aabb", (("USE_CHECKSUM_AS_USERCODE", "OFF"), ("STRATIX_JTAG_USER_CODE", "AABBCCDD")), "usercode_chk_off"),
    ("usercode_chk_off_jtagcode", (("USE_CHECKSUM_AS_USERCODE", "OFF"), ("JTAG_USER_CODE", "AABBCCDD")), "usercode_chk_off"),
    ("usercode_chk_off_cyc3", (("USE_CHECKSUM_AS_USERCODE", "OFF"), ("CYCLONEIII_JTAG_USER_CODE", "AABBCCDD")), "usercode_chk_off"),
    ("crc_on_div_32", (("CRC_ERROR_CHECKING", "ON"), ("ERROR_CHECK_FREQUENCY_DIVISOR", "32")), "crc_check_on"),
    ("crc_on_div_256", (("CRC_ERROR_CHECKING", "ON"), ("ERROR_CHECK_FREQUENCY_DIVISOR", "256")), "crc_check_on"),
    ("crc_on_ed_check", (("CRC_ERROR_CHECKING", "ON"), ("ENABLE_ED_CRC_CHECK", "ON")), "crc_check_on"),
    ("scheme_ps_tristate", (("CYCLONEIII_CONFIGURATION_SCHEME", '"PASSIVE SERIAL"'), ("TRI_STATE_SPI_PINS", "ON")), "scheme_ps"),
)


def verilog(base, jtag=None):
    ports, body, _ = BASES[base]
    if jtag:
        ports += ", output z" + (", output tdo_pin" if jtag.startswith("jtag") else "")
    return f"module top({ports});\n  {body}\n  {DESIGNS[jtag] if jtag else ''}endmodule\n"


def build_id(base, sid):
    return f"{base}.{sid}"


def jobs_list(only=None):
    """[(build id, base, assignments ((name, value), ...) or None, design kind or None)]"""
    out = []
    for base in BASES:
        out.append((build_id(base, "BASE"), base, None, None))
        for sid, name, val in SETTINGS:
            out.append((build_id(base, sid), base, ((name, val),), None))
        for sid, assigns, _ in CHAINS:
            out.append((build_id(base, sid), base, assigns, None))
        for jk in DESIGNS:
            out.append((build_id(base, jk), base, None, jk))
    return [j for j in out if not only or j[0].split(".", 1)[1] in only or j[0].split(".", 1)[1] == "BASE"]


def read_sections(path):
    d = open(path, "rb").read()
    if d[:2] == b"\x1f\x8b":
        d = gzip.decompress(d)
    p, sec = 12, {}
    while p < len(d):
        t, ln = struct.unpack_from("<HI", d, p)
        sec[t] = (p + 6, ln)
        p += 6 + ln
    return d, sec


def extract(sof, rbf, dest):
    d, sec = read_sections(sof)
    o, ln = sec[SOF_TAG_OPTION]
    opt = np.unpackbits(np.frombuffer(d[o:o + ln], np.uint8), bitorder="little")
    o, ln = sec[SOF_TAG_USERCODE]
    t19 = np.frombuffer(d[o:o + ln], np.uint8)
    o, ln = sec[SOF_TAG_CRAM]
    cram = np.frombuffer(d[o + 12:o + ln], np.uint8)
    hdr = np.fromfile(rbf, np.uint8, count=HEADER_BYTES)
    np.savez_compressed(dest, opt=opt, t19=t19, cram=cram, hdr=hdr)


def build_one(d, base, assign, jtag, pins):
    import cycloneiv_fuzz as fz
    import heavy_guard
    import toolchain
    res = os.path.join(d, "result.npz")
    if os.path.exists(res):
        return "cached"
    shutil.rmtree(d, ignore_errors=True)
    q = os.path.join(d, "quartus")
    os.makedirs(os.path.join(d, "src"))
    os.makedirs(q)
    open(os.path.join(d, "src", "top.v"), "w").write(verilog(base, jtag))
    p = BASES[base][2]
    qsf = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
           "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
           'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
           "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1", f"set_location_assignment PIN_{p} -to p"]
    qsf += [f"set_location_assignment PIN_{v} -to {k}" for k, v in pins.items()]
    qsf += [f"set_global_assignment -name {n} {v}" for n, v in (assign or ())]
    open(os.path.join(q, "build.qsf"), "w").write("\n".join(qsf) + "\n")
    open(os.path.join(q, "build.qpf"), "w").write('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    with heavy_guard.lease(heavy_guard.JOB_GB[JOB_GB_NAME], "option_pairs_build", log):
        for step, cmd in steps:
            if not fz.run(step, cmd, Path(q), Path(d) / "logs", LIMITS):
                shutil.rmtree(q, ignore_errors=True)
                open(os.path.join(d, "FAILED"), "w").write(step)
                return f"FAILED {step}"
    extract(os.path.join(q, "build.sof"), os.path.join(q, "build.rbf"), res)
    shutil.rmtree(q, ignore_errors=True)
    return "ok"


def aux_pins(p):
    """4 aux pins in bank 3 (never the test pin); fixed so every build of a base shares them."""
    pins = json.load(open(IO_PINS))
    cand = sorted(k for k, v in pins.items() if v["bank"] == 3 and k != p)
    return dict(zip(("a", "c", "e", "y", "z"), cand[:5]))


def cmd_build(a):
    only = set(a.only.split(",")) if a.only else None
    jobs = jobs_list(only)
    log.info("builds %d, jobs %d, limits %s", len(jobs), a.jobs, LIMITS)
    done = collections.Counter()

    def run(j):
        bid, base, assign, jtag = j
        try:
            r = build_one(os.path.join(OUT, "builds", bid), base, assign, jtag, aux_pins(BASES[base][2]))
        except Exception as e:      # one broken build must not stop the batch; recorded failed
            r = f"FAILED exception {e!r}"
        done[r.split()[0]] += 1
        log.info("%s: %s  [%s]", bid, r, dict(done))
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    log.info("done: %s", dict(collections.Counter(r.split()[0] + (" " + r.split()[1] if r.startswith("FAILED") else "") for r in res)))


def load(bid):
    f = os.path.join(OUT, "builds", bid, "result.npz")
    if not os.path.exists(f):
        return None
    z = np.load(f)
    return {k: z[k] for k in z.files}


def fail_reason(bid):
    d = os.path.join(OUT, "builds", bid)
    step = open(os.path.join(d, "FAILED")).read() if os.path.exists(os.path.join(d, "FAILED")) else None
    if not step:
        return None
    lg = os.path.join(d, "logs", f"{step}.log")
    err = [ln.strip() for ln in open(lg, errors="replace") if ln.startswith("Error")] if os.path.exists(lg) else []
    return dict(step=step, error=(err[0][:200] if err else ""))


def cmd_analyse(a):
    rows = []
    for bid, base, assign, jtag in jobs_list():
        sid = bid.split(".", 1)[1]
        if sid == "BASE":
            continue
        ref = next((c[2] for c in CHAINS if c[0] == sid), "BASE")
        b, s = load(build_id(base, ref)), load(bid)
        row = dict(id=sid, base=base, ref=ref, assign=[list(x) for x in assign] if assign else None, jtag=jtag)
        if s is None or b is None:
            row.update(status="no-build", reason=fail_reason(bid))
        else:
            ob, os_ = b["opt"], s["opt"]
            cd = np.nonzero(np.unpackbits(b["cram"] ^ s["cram"], bitorder="little"))[0]
            row.update(status="ok", opt_value=np.nonzero(ob[:160] != os_[:160])[0].tolist(),
                       opt_flag=(np.nonzero(ob[160:] != os_[160:])[0]).tolist(),
                       t19=bool((b["t19"] != s["t19"]).any()), t19_new=s["t19"].tolist() if (b["t19"] != s["t19"]).any() else None,
                       hdr_bits=np.nonzero(np.unpackbits(b["hdr"] ^ s["hdr"], bitorder="little"))[0].tolist(),
                       cram_n=int(len(cd)), cram_cells=cd[:2000].tolist())
        rows.append(row)
    res = dict(rows=rows, bases={k: v[2] for k, v in BASES.items()})
    os.makedirs(os.path.dirname(PAIRS_DB), exist_ok=True)
    json.dump(res, open(PAIRS_DB, "w"))
    ok = [r for r in rows if r["status"] == "ok"]
    chg = [r for r in ok if r["opt_value"] or r["opt_flag"] or r["t19"]]
    log.info("analysed %d rows: ok %d, no-build %d, option/usercode changed %d; wrote %s", len(rows), len(ok), len(rows) - len(ok), len(chg), PAIRS_DB)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--jobs", type=int, default=12)       # source: task cap, <= 12 jobs; memory lease gates admission
    b.add_argument("--only")
    sub.add_parser("analyse")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_option_pairs.log")), logging.StreamHandler()])
    {"build": cmd_build, "analyse": cmd_analyse}[a.cmd](a)


if __name__ == "__main__":
    main()
