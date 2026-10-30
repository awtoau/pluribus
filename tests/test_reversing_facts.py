"""Proven reversing facts as regression tests: tool command -> expected value (#169).

Each test is one fact the tools must keep returning (source: reference/rules.tsv row / docs/reversing-errata.md id in the docstring).
Skips when the Quartus install (ELF libs) is missing; decompile-text facts also skip when the decompile cache is missing.
No vendor bodies, no hashes: names, addresses and small integers only.
"""
import contextlib
import io
import os
import re
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)

try:
    import toolchain
    QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
    HAVE = os.path.exists(os.path.join(QROOT, "linux64", "libcomp_asm.so"))
except Exception:     # noqa: BLE001
    HAVE = False
pytestmark = pytest.mark.skipif(not HAVE, reason="Quartus linux64 libs not installed")
CACHE = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "ghidra_out", "cache")
TSV = os.path.join(REPO, "reference", "ghidra")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("idx") / "index.db")
    os.environ["PLURIBUS_INDEX_DB"] = p
    import ghidra_index as X
    X.DB = p
    X.build({"libcomp_asm", "libcomp_asmcc", "libdb_asmdb", "libddb_dygr", "libcomp_asmram"})
    c = X.connect()
    yield c
    c.close()


def lib(name):
    import ghidra_dump as D
    return D.Lib(name)


def table(name, spec, typ, n=None):
    import ghidra_dump as D
    with contextlib.redirect_stdout(io.StringIO()):
        return D.dump_table(lib(name), spec, typ, n)


def tsv(name):
    return [l.rstrip("\n").split("\t") for l in open(os.path.join(TSV, name)) if l.strip() and not l.startswith("#")]


def cached(libname, vaddr):
    d = os.path.join(CACHE, libname)
    if not os.path.isdir(d):
        pytest.skip("decompile cache missing")
    f = [x for x in os.listdir(d) if x.startswith(f"{vaddr:x}_")]
    if not f:
        pytest.skip("function not in decompile cache")
    return open(os.path.join(d, f[0]), errors="replace").read()


def run_trace(*a):
    return subprocess.run([sys.executable, os.path.join(REPO, "scripts", "ghidra_trace.py"), "trace", *a],
                          capture_output=True, text=True, env=dict(os.environ, PLURIBUS_INDEX_DB=os.environ["PLURIBUS_INDEX_DB"])).stdout


# --- enums -------------------------------------------------------------------------------------------------------------------------
def test_enum_sizes():
    """enums.tsv: vendor debug-string tables (docs/ghidra-readable-index.md)."""
    n = {}
    for c in tsv("enums.tsv"):
        n[c[1]] = n.get(c[1], 0) + 1
    assert n["ASMDB_ARCH_GROUP_TYPE"] == 4663 and n["ASMDB_ARCH_GROUP_BLOCK_TYPE"] == 542
    assert n["ASMDB_DIRT_TYPE"] == 303 and n["DEV_ELEMENT_ENUM"] == 2715


def test_enum_names():
    e = {(c[1], int(c[2])): c[3] for c in tsv("enums.tsv")}
    assert e[("ASMDB_ARCH_GROUP_TYPE", 3)] == "LE_LUT_FUNCTION"
    assert e[("ASMDB_ARCH_GROUP_TYPE", 84)] == "IO_PIN_MODE"
    assert e[("ASMDB_ARCH_GROUP_TYPE", 161)] == "IO_SET_DRIVE_STRENGTH_YGR"


def test_block_type_ids():
    """L-007: block type ids used as PLACED keys."""
    b = {c[3]: int(c[2]) for c in tsv("enums.tsv") if c[1] == "ASMDB_ARCH_GROUP_BLOCK_TYPE"}
    assert (b["LAB"], b["MEAB"], b["MAC"], b["VIO"], b["FAST_PLL"], b["GENERAL_PLL"]) == (18, 39, 41, 6, 43, 45)


def test_cdb_ram_flag_enum_89_names():
    """M-005: CDB_RAM_FLAG_ENUM name table lives in libatm_astr (astr_get_debug_string@0xd87034, array @0x185b800)."""
    rows = table("libatm_astr", "0x185b800", "ptr", 89)
    assert len(rows) == 89 and rows[0][1] == '"RAM_READ_DURING_WRITE"' and rows[88][1] == '"RAM_BY40"'
    assert all(r[1].startswith('"') for r in rows)


# --- group -> class -> writer chain (trace tool) -----------------------------------------------------------------------------------
def test_binding_le_lut_function(db):
    """D-002: LE_LUT_FUNCTION -> ASM_LE_LUT_FUNCTION::process_atom@0x16b05c via le_arch_groups@0x17ae44 case 3."""
    t = run_trace("LE_LUT_FUNCTION")
    assert "bound class ASM_LE_LUT_FUNCTION" in t and "0x16b05c" in t and "case 0x3" in t


def test_io_pin_mode_chain(db):
    """L-015: IO_PIN_MODE (84) -> ASM_IO_PIN_MODE::process_atom@0x19101c, virtual slot +0x18."""
    t = run_trace("IO_PIN_MODE")
    assert "0x19101c" in t and "+0x18\tASM_IO_PIN_MODE::process_atom\t0x19101c" in t


def test_le_lut_input_and_reg_out_bindings(db):
    """E-002 / R-001: LE_LUT_INPUT -> process_atom@0x16c464; LE_REG_OUT_YGR -> process_atom@0x16e66a (le_arch_groups case 0x13)."""
    assert "0x16c464" in run_trace("LE_LUT_INPUT")
    t = run_trace("LE_REG_OUT_YGR")
    assert "0x16e66a" in t and "case 0x13" in t


def test_lab_invert_writer(db):
    """F-012: LAB_INVERT -> ASM_LAB_INVERT::process_end_of_phase@0x158d76."""
    assert "0x158d76" in run_trace("LAB_INVERT")


def test_class_groups_table_size():
    """L-017: group-type -> class bindings."""
    import json
    t = json.load(open(os.path.join(REPO, "lifters", "cycloneiv_clean", "class_groups_table.json")))
    assert len(t) >= 1000 and all("source" in r for r in t)


def test_mux_select_overloads(db):
    """errata/defect: three mux_select overloads at 0x28526 (uint,uint,streams&), 0x28612 (+bool), 0x286c0 (vector)."""
    rows = {r[0]: r[1] for r in db.execute("select vaddr, name from functions where lib='libcomp_asmcc' and name like 'ASM_ARCH_GROUP::mux_select(%'")}
    assert "bool" in rows[0x28612] and "vector" in rows[0x286c0] and rows[0x28526].endswith("(unsigned int, unsigned int, ASMDB_SETTING_STREAMS&)")
    sig = {c[1]: c[3] for c in tsv("signatures.tsv") if c[0] == "libcomp_asmcc"}
    assert "uint value" in sig["28526"] and "bool value" in sig["28612"]


def test_set_bits_symbols(db):
    """address-spaces s2.1: ELF symbols silent_set_bits 0x1a240, set_bits 0x1aca0 (0x17e50 / 0x18000 are PLT stubs, E-U1)."""
    r = {n.split("(")[0]: v for v, n in db.execute("select vaddr, name from functions where lib='libcomp_asmcc' and name like 'ASM_BITFIELD::%set_bits%'")}
    assert r["ASM_BITFIELD::silent_set_bits"] == 0x1a240 and r["ASM_BITFIELD::set_bits"] == 0x1aca0


def test_dygr_and_asmdb_function_addresses(db):
    """T-001 / D-001: get_bits_from_source_to_dest@0x23bfe0 (libddb_dygr), calculate_bits_traditional@0x8e8a4 (libdb_asmdb)."""
    assert db.execute("select 1 from functions where lib='libddb_dygr' and vaddr=? and name like '%get_bits_from_source_to_dest%'", (0x23bfe0,)).fetchone()
    assert db.execute("select 1 from functions where lib='libdb_asmdb' and vaddr=? and name like '%calculate_bits_traditional%'", (0x8e8a4,)).fetchone()


# --- data tables ------------------------------------------------------------------------------------------------------------------
def test_lab_model_cuda_virtual_lab_line_table():
    """F-012: ASM_LAB_MODEL_CUDA ctor@0x165038 copies 9 VIRTUAL_LAB_LINE entries (20 B) from 0x3cd760; field1 masks = clk0 ce0 clk1 ce1 sload sclr aclr aclr sload2."""
    import ghidra_dump as D
    L = lib("libcomp_asm")
    import struct
    masks = [struct.unpack("<I", L.read(0x3cd760 + 20 * i + 4, 4))[0] for i in range(9)]
    assert masks == [4, 2, 4, 2, 0x40, 0x20, 8, 8, 0x40]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        D.ctor_tables(L, "ASM_LAB_MODEL_CUDA", 8)
    assert "table 0x3cd760" in out.getvalue()


def test_address_space_tags():
    """L-012: silent_set_bits tests tags in this order: literal 11, CFF 101, UNVM 1001, OPTION 10001, DPRIO 100001 (top bits); CRAM = bit31 clear."""
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    assert [(n, hex(m)) for n, m, _ in IO.ADDRESS_SPACES] == [("LITERAL", "0xc0000000"), ("CFF", "0xa0000000"), ("UNVM", "0x90000000"),
                                                             ("OPTION", "0x88000000"), ("DPRIO", "0x84000000")]
    s, i = IO.classify([0x12345, 0xA0000007, 0x90000003])
    assert list(s) == ["CRAM", "CFF", "UNVM"] and list(i) == [0x12345, 7, 3]


def test_pll_bandwidth_tables_are_plain_text():
    """P-005: BASIC_PLL / BANDWIDTH tables are plain-text ddb_stingray*.pll files in devinfo (no library needed)."""
    d = os.path.join(QROOT, "common", "devinfo", "cycloneivgx")
    f = os.path.join(d, "ddb_stingray_bandwidth_gpll.pll")
    if not os.path.exists(f):
        pytest.skip("devinfo missing")
    t = open(f, errors="replace").read()
    assert len(t) > 100 and re.search(r"[A-Za-z]", t) and len([x for x in os.listdir(d) if x.endswith(".pll")]) >= 10


# --- asmdb ------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def walk():
    try:
        from lifters.cycloneiv_clean.asmdb_walk import Walk
        return Walk()
    except FileNotFoundError:
        pytest.skip("asmdb ddb missing")


def test_asmdb_pool_order_consumes_body(walk):
    """docs/cycloneiv-clean-io.md pool order: the walk consumes the body exactly and class counts equal the ddb type table."""
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    assert walk.end == len(walk.b)
    assert len(walk.groups()) == 6312 and walk.class_counts()[17] == 8567


def test_le_lut_function_group_shape(walk):
    """D-002: LE_LUT_FUNCTION = one CALC group (class 5) in LAB (18), 16 sites, ENCODED mux of 16 bits."""
    g = [x for x in walk.groups() if x["type"] == 3]
    assert len(g) == 1 and g[0]["cls"] == 5 and g[0]["btype"] == 18 and len(g[0]["paths"]) == 16
    m = walk.mux(g[0]["paths"][0][0])
    assert m["cls"] == 15 and len(m["bits"]) == 16


def test_lab_block_info_ram_cols(walk):
    """D-001: calculate_bits_traditional W = m_num_ram_cols = 6154 for the LAB block info."""
    assert 6154 in {b["ram_cols"] for b in walk.block_infos()}


def test_mux_select_rules():
    """asmdb_select: SIMPLE = one-hot, ENCODED bit k = (value >> k) & 1 (ASMDB_*_MUX::select@0x8c4ac / 0x8c0ba)."""
    from lifters.cycloneiv_clean import asmdb_select as S
    assert S._simple([10, 11, 12], 1) == [(10, 0), (11, 1), (12, 0)]
    assert S._encoded([5, 6, 7], 5) == [(5, 1), (6, 0), (7, 1)]


# --- decompile-text facts (cache) --------------------------------------------------------------------------------------------------
def test_io_direction_mux_values_0_to_6():
    """L-015: ASM_IO_PIN_MODE::process_atom passes exactly the mux values 0..6 to ASM_ARCH_GROUP::mux_select."""
    t = cached("libcomp_asm", 0x19101c)
    vals = {int(m, 0) for m in re.findall(r"mux_select\(\w+,\w+,(?:\(\w+ \*\))?(0x[0-9a-f]+|\d+)[,)]", t)}
    assert vals == set(range(7))


def test_le_reg_out_ygr_value_is_registered_plus_one():
    """R-001: ASM_LE_REG_OUT_YGR value = is_registered() + 1 (2 registered, 1 combinational)."""
    t = cached("libcomp_asm", 0x16e66a)
    assert "CDB_ATOM_OTERM::is_registered" in t and re.search(r"\(cVar\d != '\\0'\) \+ 1", t)


# --- transcript-mined verified facts (reference/ghidra/mined.tsv) -------------------------------------------------------------------
def _mined(kind):
    return [c for c in tsv("mined.tsv") if c[0] == kind and len(c) > 5 and c[5].startswith("yes")]


def test_mined_functions_exist_at_their_vaddr():
    """mined `function` rows verified 'yes: nm': the exact demangled name (without args) sits at the ELF vaddr in that lib."""
    import ghidra_index as X
    import sqlite3
    rows = [c for c in _mined("function") if "nm" in c[5] and re.match(r"0x[0-9a-f]+ \S+", c[2])]
    assert len(rows) >= 90
    byl = {}
    for c in rows:
        byl.setdefault(c[1], []).append(c)
    bad = []
    for l, cs in byl.items():
        if not os.path.exists(X.lib_path(l)):
            continue
        db = sqlite3.connect(":memory:")
        db.executescript(X.SCHEMA)
        X.load_elf(db, l)
        for c in cs:
            va, nm = c[2].split(" ", 1)
            names = {n.split("(")[0] for (n,) in db.execute("select name from functions where vaddr=?", (int(va, 16),))}
            if nm.split("(")[0] not in names:
                bad.append((l, c[2], sorted(names)[:2]))
    assert not bad, bad


def test_mined_astr_ram_flag_table_size():
    """mined table row: CDB_RAM_FLAG_ENUM translator table is pointer[89] (0x2c8 bytes)."""
    L = lib("libatm_astr")
    sz = [s[1] for s in L.syms if s[0] == 0x185b800][0]
    assert sz == 0x2c8


def test_mined_stingray_lab_model_shares_cuda_handler():
    """ledger F-016 (mined table row): LAB model jump table 0x3cd61c: entries 8 and 42 (families 0xe and 0x30) hold the same target."""
    import struct
    L = lib("libcomp_asm")
    t = [struct.unpack("<i", L.read(0x3cd61c + 4 * i, 4))[0] for i in range(50)]
    assert t[8] == t[42] and t[3] == t[46] and t[40] == t[49]


def test_mined_signal_polarity_class():
    """errata E-U2: look_up_signal_polarity@0x1563ae is ASM_SINGLE_LAB_MODEL_BASE."""
    import ghidra_index as X
    db = sqlite3.connect(":memory:")
    db.executescript(X.SCHEMA)
    X.load_elf(db, "libcomp_asm")
    assert db.execute("select cls from functions where vaddr=?", (0x1563ae,)).fetchone()[0] == "ASM_SINGLE_LAB_MODEL_BASE"


def test_mined_pgmio_ghidra_form_is_another_function():
    """errata E-U4: libpgm_pgmio ELF 0x43be30 = reverse_address_counter_frames, ELF 0x53be30 = __tcf_0 (Ghidra form 0x53be30 = ELF 0x43be30)."""
    import ghidra_index as X
    db = sqlite3.connect(":memory:")
    db.executescript(X.SCHEMA)
    X.load_elf(db, "libpgm_pgmio")
    assert "reverse_address_counter_frames" in db.execute("select name from functions where vaddr=?", (0x43be30,)).fetchone()[0]
    assert db.execute("select name from functions where vaddr=?", (0x53be30,)).fetchone()[0].startswith("__tcf_0")


def test_clkbuf_input_select_writers(db):
    """ledger B-010 / B-011: the clock buffer input select writer, its bit-3 helper and the gid -> index map sit at these ELF vaddrs (nm -C verified)."""
    for vaddr, frag in ((0x2fd9f8, "ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom"),
                        (0x2f9adc, "ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::second_pll_feeds_clock_mux"),
                        (0x2fcc58, "ASM_CLOCKSPINE_MODEL::resolve_clock_buffer_index_for_blk_type"),
                        (0x1a3ea8, "ASM_PLL_INPUT::process_atom"), (0x1a25ba, "ASM_PLL_FEEDBACK_SELECT::process_atom")):
        row = db.execute("select name from functions where vaddr=?", (vaddr,)).fetchone()
        assert row and frag in row[0], hex(vaddr)


def test_clkbuf_select_group_is_30_sites_of_4_bits(walk):
    """ledger B-010: CLKBUF_CLK_INPUT_SELECT_CYCLONEII = one STD group of block 73, 30 sites, ENCODED mux of 4 bits (value 7 = none, bit 3 = second PLL)."""
    import cycloneiv_clean_dirt as D
    gt = D.enum_tables()["arch_group_type"]
    g = [g for g in walk.groups() if g["btype"] == 73 and gt.get(g["type"]) == "CLKBUF_CLK_INPUT_SELECT_CYCLONEII"]
    assert len(g) == 1 and len(g[0]["paths"]) == 30 and len(walk.mux(g[0]["paths"][0][0])["bits"]) == 4


def test_pll_dirt_tables():
    """ledger P-002 / B-011: PLL_k = icd of the dirt coordinate map (PLL_1 at X0Y13 ... PLL_4 at X117Y90); CLKMUX_PLL_SOURCE = 5 runs of 6 sites (icd 1 8 4 2 3)."""
    from lifters.cycloneiv_clean import pll
    t = pll.pll_tiles()
    assert {k: v[2] for k, v in t.items()} == {1: (0, 13), 5: (0, 14), 6: (0, 43), 7: (0, 48), 8: (0, 76), 2: (0, 77), 3: (117, 1), 4: (117, 90)}
    s = pll.clkmux_pll_source()
    assert [s[g] for g in range(0, 30, 6)] == [1, 8, 4, 2, 3] and all(len({s[g + k] for k in range(6)}) == 1 for g in range(0, 30, 6))


def test_pll_interface_ports():
    """ledger P-009: the vendor block interface PLL1 carries the control ports on these BLOCK_INPUT_MUX indices (PLL3 / PLL4: PHASESTEP on 16)."""
    from lifters.cycloneiv_clean import blockiface as B
    pn, de = B.input_port_names(), {v: k for k, v in B.dev_enums().items()}
    ifs = {d["name"]: d for d in B.load() if d["type"] == 1}

    def ports(n):
        return {m["index"]: pn.get(c["port"]) for m in ifs[n]["nodes"] for c in m["conns"] if de.get(c["enum"]) in ("PLL", "CLKBUFBLOCK")}
    p1 = ports("PLL1")
    assert {p1[i] for i in (0, 1, 3, 10, 24, 25, 27)} == {"CLKSWITCH", "SCANCLK", "CONFIGUPDATE", "SCANCLKENA", "SCANDATA", "PFDENA", "ARESET"}
    assert p1[17] == "PHASESTEP" and ports("PLL3")[16] == "PHASESTEP"


def test_pll_limits_are_periods_in_ps():
    """ledger P-010: vendor PLL limits are periods (769 ps = 1300 MHz, 1666 ps = 600 MHz VCO); the GPLL table of speed grade 7 and 8 is identical."""
    from lifters.cycloneiv_clean import pll
    a, b = pll.limits("GPLL", 7), pll.limits("GPLL", 8)
    assert a == b and a["vco"][1] == (769, 1666) and a["vco"][2] == (1538, 3333) and a["input"] == (2116, 200000)
    assert pll.limits("MPLL", 7)["vco"][1] == (625, 1666)
