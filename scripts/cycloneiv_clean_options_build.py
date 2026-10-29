#!/usr/bin/env python3.15t
"""Build lifters/cycloneiv_clean/options_table.json: the decoded map of the 160 option-register bits of EP4CGX150 (#169).

Inputs (all vendor-derived, local): asmdb walk (groups, default / forced lists), vendor sfl sof tag 18, cff2rbf option table, Quartus enum names.
Hand-curated part = GROUP_SEM below: one row per option group, each row cites the Ghidra function (libcomp_asm) that writes it and the pair
ids that confirm it.  Pair builds: scripts/cycloneiv_clean_option_pairs.py.  Doc: docs/cycloneiv-clean-options.md.

  python3.15t scripts/cycloneiv_clean_options_build.py            # log: tmp/logs/cycloneiv_clean_options_build.log
"""
import json
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from lifters.cycloneiv_clean import asmdb_walk as W  # noqa: E402
from lifters.cycloneiv_clean import io as IO  # noqa: E402
from lifters.cycloneiv_clean import sofio  # noqa: E402
import cycloneiv_clean_dirt as D  # noqa: E402

OUT = os.path.join(REPO, "lifters", "cycloneiv_clean", "options_table.json")
PAIRS = os.path.join(REPO, "databases", "cycloneiv", "option_pairs.json")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_options_build.log")
N = 160
OPTION_TAG = 0x88000000
log = logging.getLogger("options_build")

# group type name -> (ghidra function, driver, qsf settings, polarity, pair ids, note).  polarity: "inverted" = bit is the NOT of the setting,
# "direct" = bit equals the setting, "value" = multi-bit value (LSB = lowest bit index).  Ghidra vaddrs = libcomp_asm file vaddr (Ghidra shows +0x100000).
GROUP_SEM = {
    "OPTION_REG_USE_CLKUSR": ("ASM_OPTION_REG_USE_CLKUSR::process_end_of_phase @0x1caa60", "CDB_CHIP_DB_ENTRY::is_user_start_up_clock",
                              ["USER_START_UP_CLOCK"], "inverted", ["user_clk_on"], "user-supplied start-up clock (CLKUSR) used"),
    "OPTION_REG_RELEASE_CLEAR_BEFORE_TRI": ("ASM_OPTION_REG_RELEASE_CLEAR_BEFORE_TRI::process_end_of_phase @0x1caafc",
                                            "asmcc_get_bool_option ACF 0x4c6", ["RELEASE_CLEARS_BEFORE_TRI_STATES"], "inverted",
                                            ["release_clears_on"], "release device-wide clear before the tri-states"),
    "OPTION_REG_USE_INITDONE": ("ASM_OPTION_REG_USE_INITDONE::process_end_of_phase @0x1cac7a", "CDB_CHIP_DB_ENTRY::is_init_done",
                                ["ENABLE_INIT_DONE_OUTPUT"], "inverted", ["init_done_on"], "INIT_DONE output pin enabled"),
    "DEVICE_USE_GLOBAL_CLEAR": ("ASM_DEVICE_USE_GLOBAL_CLEAR::process_end_of_phase @0x18e112", "CDB_CHIP_DB_ENTRY::is_dev_clr",
                                ["ENABLE_DEVICE_WIDE_RESET"], "inverted", ["dev_reset_on"], "device-wide reset (DEV_CLRn) enabled"),
    "DEVICE_USE_GLOBAL_TRI": ("ASM_DEVICE_USE_GLOBAL_TRI::process_end_of_phase @0x18e158", "CDB_CHIP_DB_ENTRY::is_dev_oe",
                              ["ENABLE_DEVICE_WIDE_OE"], "inverted", ["dev_oe_on"], "device-wide output enable (DEV_OE) enabled"),
    "OPTION_REG_ENABLE_AUTO_RECONFIGURE": ("ASM_OPTION_REG_ENABLE_AUTO_RECONFIGURE::process_end_of_phase @0x1cab5a",
                                           "asmcc_get_bool_option ACF 0x4c7", ["AUTO_RESTART_CONFIGURATION"], "direct",
                                           ["auto_restart_on", "auto_restart_off"],
                                           "auto-restart configuration after error; default ON in the base build"),
    "OPTION_REG_USE_ERROR_DETECT": ("ASM_OPTION_REG_USE_ERROR_DETECT::process_atom @0x1cacc0 + process_end_of_phase @0x1cd832",
                                    "crcblock atom (m_value 1) / QSF option", ["CRC_ERROR_CHECKING", "cycloneiv_crcblock atom"], "value",
                                    ["crc_check_on", "crcblock_div1"],
                                    "bit 8 cleared by the QSF option or a crcblock atom; second bit (92) set only by the QSF option"),
    "OPTION_REG_SELECT_SPI_PIN_STATE": ("ASM_OPTION_REG_SELECT_SPI_PIN_STATE::process_end_of_phase @0x1cb268",
                                        "get_programming_mode / get_spi_flash_mode / is_tri_state_spi_pins",
                                        ["CYCLONEIII_CONFIGURATION_SCHEME", "TRI_STATE_SPI_PINS"], "value",
                                        ["scheme_ps", "scheme_fpp", "spi_tristate_on", "scheme_ps_tristate"],
                                        "2-bit SPI pin state: passive schemes 3; active serial 2; active serial + TRI_STATE_SPI_PINS 0"),
    "OPTION_REG_SET_POF_ID": ("ASM_OPTION_REG_SET_POF_ID::process_end_of_phase @0x1cbc2e", "DEV_PART_MANAGER::get_pof_id_of(part)",
                              [], "value", [], "8-bit POF id of the part (1 on every IV GX sfl sof); no QSF setting reaches it"),
    "OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER": ("ASM_OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER::process_atom @0x1caef6 + process_end_of_phase @0x1cbf96",
                                                "crcblock oscillator_divider / QSF divisor", ["ERROR_CHECK_FREQUENCY_DIVISOR",
                                                                                                "cycloneiv_crcblock oscillator_divider"], "value",
                                                ["crc_on_div_32", "crc_on_div_256", "crcblock_div2", "crcblock_div256"],
                                                "one-hot CRC clock divider: divisor 2^k sets bit 26+k (k 1..8); divisor 1 = all zero"),
    "OPTION_REG_USE_NCEO": ("ASM_OPTION_REG_USE_NCEO::process_end_of_phase @0x1cb48a", "CDB_CHIP_DB_ENTRY::get_nceo_reserved_mode != 5",
                            ["CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION"], "inverted", ["nceo_io"],
                            "nCEO pin kept as programming pin; 'USE AS REGULAR IO' sets the bit"),
    "OPTION_REG_WAIT_FOR_OCTDONE": ("ASM_OPTION_REG_WAIT_FOR_OCTDONE::process_end_of_phase @0x1cb4d6", "asmcc_get_bool_option ACF 0x4cd",
                                    ["ENABLE_OCT_DONE"], "inverted", ["oct_done_on"], "wait for OCT calibration done"),
    "OPTION_REG_EXTERNAL_CLK_SPI": ("ASM_OPTION_REG_EXTERNAL_CLK_SPI::process_end_of_phase @0x1cb676", "asmcc_get_enum_option ACF 0x3ed",
                                    ["ACTIVE_SERIAL_CLOCK"], "value", ["as_clk_20", "as_clk_40", "as_clk_clkusr"],
                                    "active-serial clock source via asmdb value map {262:3, 263:1, 264:0}: FREQ_20MHz 3, FREQ_40MHz 1 (default), CLKUSR 0"),
}


def wlist(w, names, bt):
    """option groups of the walk: [{type, name, cls, arch, bits (option indices), n}]"""
    out = []
    for g in w.groups():
        bits = g["bits"] if g["cls"] == 7 else [x for p in g["paths"] for r in p if r for x in w.mux(r)["bits"]]
        ob = [b & 0x77FFFFFF for b in bits if (b >> 27) == 0x11]
        if ob:
            out.append(dict(type=g["type"], name=names[g["type"]], block=bt.get(g["btype"], str(g["btype"])), cls=g["cls"],
                            arch=g.get("arch"), bits=ob))
    return out


def vendor_tag18():
    import gzip
    import struct
    d = gzip.decompress(open(sofio.programmer_sof("sfl_ep4cgx150.sof"), "rb").read())
    p = 12
    while p < len(d):
        t, ln = struct.unpack_from("<HI", d, p)
        if t == 18:
            return np.unpackbits(np.frombuffer(d[p + 6:p + 6 + ln], np.uint8), bitorder="little")
        p += 6 + ln
    raise ValueError("no tag 18")


def rbf_cells():
    """tag-18 bit index (0..319) -> [(frame, byte, bit)] rbf cells (cff2rbf option table, quartus_cpf bit planes)."""
    t = np.load(IO.CFF_TABLE_PATH)["option"]
    out = {}
    for f, b, k in zip(*np.nonzero(t >= 0)):
        out.setdefault(int(t[f, b, k]), []).append([int(f), int(b), int(k)])
    return out


def pair_evidence():
    """option bit -> sorted pair ids whose spec build flipped it (min and reg base agree, else the id is marked)."""
    if not os.path.exists(PAIRS):
        return {}, {}
    d = json.load(open(PAIRS))
    ev, rows = {}, {}
    for r in d["rows"]:
        if r["status"] != "ok":
            continue
        rows.setdefault(r["id"], {})[r["base"]] = r["opt_value"]
        for b in r["opt_value"]:
            ev.setdefault(b, set()).add(r["id"])
    return {k: sorted(v) for k, v in ev.items()}, rows


# the 15 JTAG classes of libcomp_asm (docs/cycloneiv-address-spaces.md 4) -> asmdb group type name ("" = no group type: class is not a bit writer)
JTAG_CLASSES = (
    ("ASM_JTAG_PIA", ""), ("ASM_JTAG_PIA_TO_CORE_CTL", "JTAG_PIA_TO_CORECTL"), ("ASM_JTAG_PIA_TO_TCKCORE", "JTAG_PIA_TO_TCKCORE"),
    ("ASM_JTAG_PIA_TO_TDICORE", "JTAG_PIA_TO_TDICORE"), ("ASM_JTAG_PIA_TO_TMSCORE", "JTAG_PIA_TO_TMSCORE"),
    ("ASM_JTAG_PIA_TO_TDOUSER", "JTAG_PIA_TO_TDOUSER"), ("ASM_JTAG_PIA_TO_TDOUTAP", "JTAG_PIA_TO_TDOUTAP"),
    ("ASM_JTAG_TCKCORE_INVERT", "JTAG_TCKCORE_INVERT"), ("ASM_JTAG_TDICORE_INVERT", "JTAG_TDICORE_INVERT"),
    ("ASM_JTAG_TMSCORE_INVERT", "JTAG_TMSCORE_INVERT"), ("ASM_JTAG_TDOUSER_INVERT", "JTAG_TDOUSER_INVERT"),
    ("ASM_JTAG_TDOUTAP_INVERT", "JTAG_TDOUTAP_INVERT"), ("ASM_JTAG_CORECTL_INVERT", "JTAG_CORECTL_INVERT"),
    ("ASM_JTAG_ENABLE_BST_SUPPORT", "JTAG_ENABLE_BST_SUPPORT"), ("ASM_JTAG_WRITE_USER_CODE", "JTAG_WRITE_USER_CODE"),
)


def jtag_section(w, names):
    """Per JTAG class: asmdb group present on this die, bit address space and count; DB_ILLEGAL marker groups carry no bit."""
    tid = {v: k for k, v in names.items()}
    out = []
    pairs = os.path.join(REPO, "tmp", "cycloneiv_clean", "option_pairs", "builds")
    for cls, gname in JTAG_CLASSES:
        row = dict(klass=cls, group=gname or None, in_asmdb=False, space=None, n_bits=0, bits=[], measured=None)
        for g in w.groups():
            if gname and g["type"] == tid.get(gname):
                bits = g["bits"] if g["cls"] == 7 else [x for p in g["paths"] for r in p if r for x in w.mux(r)["bits"]]
                illegal = [b for b in bits if b >= 0xFFFFFFFA]
                real = [b for b in bits if b < 0x80000000]
                row.update(in_asmdb=True, group_class=g["cls"], space="DB_ILLEGAL marker (writing it is an internal error)" if illegal else "CRAM",
                           n_bits=len(real), bits=sorted(set(real)))
        out.append(row)
    # measured: group bits set in the jtag builds (tdouser driven) vs the base build
    if os.path.isdir(pairs):
        def cram(b):
            return np.load(os.path.join(pairs, b, "result.npz"))["cram"]
        base = cram("min.BASE")
        for row in out:
            if row["bits"]:
                m = {}
                for d in ("jtag_user_in", "jtag_user_lut", "jtag_user_reg", "jtag_all"):
                    c = cram("min." + d)
                    m[d] = sum(int((c[a >> 3] >> (a & 7)) & 1) - int((base[a >> 3] >> (a & 7)) & 1) for a in row["bits"])
                row["measured"] = dict(bits_set_vs_base=m, builds="tdouser driven from pin / LUT / register; ports of the cycloneiv_jtag atom")
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    w = W.Walk()
    tabs = D.enum_tables()
    groups = wlist(w, tabs["arch_group_type"], tabs["block_type"])
    v18 = vendor_tag18()
    cells = rbf_cells()
    ev, _ = pair_evidence()
    default = sorted(b & 0x77FFFFFF for b in w.default_bits if (b >> 27) == 0x11)
    forced = sorted(b & 0x77FFFFFF for b in w.forced_bits if (b >> 27) == 0x11)
    assert len(w.default_bits) and all(x < N for x in default + forced)
    by_bit = {}
    for g in groups:
        for k, b in enumerate(g["bits"]):
            by_bit[b] = (g, k)
    ents = []
    for i in range(N):
        e = dict(index=i, sof_value_bit=i, sof_flag_bit=N + i, vendor_value=int(v18[i]), vendor_flag=int(v18[N + i]),
                 rbf_cells=cells.get(i, []), rbf_cells_flag=cells.get(N + i, []), pairs=ev.get(i, []))
        if i in by_bit:
            g, k = by_bit[i]
            sem = GROUP_SEM[g["name"]]
            e.update(klass="group", name=g["name"], group_type=g["type"], group_class=g["cls"], group_arch=g["arch"], group_bits=g["bits"],
                     bit_in_group=k, function=sem[5], polarity=sem[3], settings=sem[2], ghidra=sem[0], driver=sem[1], group_pairs=sem[4],
                     status="named, confirmed by pairs" if ev.get(i) else "named (decompile + asmdb), no setting reaches it",
                     source=f"asmdb group {g['type']} {g['name']} (libdb_asmdb enum); {sem[0]}; pairs {','.join(ev.get(i, [])[:6]) or 'none'}")
        elif i in forced:
            e.update(klass="forced", name=None, function=None, status="unknown: forced-list bit, no group, no setting changes it",
                     source="asmdb forced-bit list (ASMDB_DIE::add_forced_bit); value 1, flag 1 = set via ASM_BITFIELD::set_bits")
        elif i in default:
            e.update(klass="default", name=None, function=None, status="unknown: default-list bit, no group, no setting changes it",
                     source="asmdb default-bit list (ASMDB_DIE::add_default_bit); value 1, flag 0 = set via ASM_BITFIELD::silent_set_bits")
        else:
            e.update(klass="unlisted", name=None, function=None, status="unknown: in no list and no group",
                     source="asmdb: absent from default list, forced list and every option group")
        ents.append(e)
    cnt = {}
    for e in ents:
        cnt[e["klass"]] = cnt.get(e["klass"], 0) + 1
    res = dict(
        source="scripts/cycloneiv_clean_options_build.py; asmdb walk + vendor sfl sof tag 18 + cff2rbf option table + pair builds",
        n_bits=N, class_counts=cnt, entries=ents, jtag=jtag_section(w, tabs["arch_group_type"]),
        flag_semantics=dict(
            text="sof tag 18 bits 160..319 = ASM_BITFIELD shadow buffer: 1 where the bit was written by set_bits (forced list, option groups), 0 where only silent_set_bits wrote it (default list)",
            source="libcomp_asmcc ASM_BITFIELD::set_bits @0x118000 (value + written mask + shadow) vs silent_set_bits @0x117e50 (value only), docs/cycloneiv-address-spaces.md 3.2"))
    json.dump(res, open(OUT, "w"), indent=1)
    log.info("wrote %s: %s", OUT, cnt)


if __name__ == "__main__":
    main()
