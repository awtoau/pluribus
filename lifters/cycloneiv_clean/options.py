"""Cyclone IV GX (EP4CGX150) option register: decoded map of the 160 bits, encoder / decoder and scoring.  Vendor-derived only (#169).

Data = options_table.json (written by scripts/cycloneiv_clean_options_build.py; every entry carries a `source`: asmdb group / list +
Ghidra function + pair ids).  Nothing below is a fitted constant: bit positions come from the table, which comes from the asmdb walk.
Layout (docs/cycloneiv-clean-options.md): sof tag 18 = 160 value bits + 160 flag bits; value bit i is also rbf frame-0 cells `rbf_cells`.
Classes: group (30 bits, 13 asmdb option groups, function decoded), forced (35), default (95): forced / default have no group and no setting
that changes them, so their function is unknown (counted as missing).
"""
import json
import os

N_BITS = 160
TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options_table.json")
_cache = {}


def table():
    if not _cache:
        with open(TABLE_PATH) as f:
            _cache.update(json.load(f))
    return _cache


def entries():
    return table()["entries"]


def groups():
    """{group name: [bit index, ...] in value order (LSB first)} of the 13 option groups."""
    out = {}
    for e in entries():
        if e["klass"] == "group":
            out.setdefault(e["name"], []).append(e["index"])
    return {k: [i for _, i in sorted((entries()[i]["bit_in_group"], i) for i in v)] for k, v in out.items()}


def classes():
    """{class: [bit index]} over group / forced / default / unlisted."""
    out = {}
    for e in entries():
        out.setdefault(e["klass"], []).append(e["index"])
    return out


def default_vector():
    """160 value bits of the vendor sfl sof (all 130 listed bits 1; group bits at their sfl values)."""
    return [e["vendor_value"] for e in entries()]


class Config:
    """Device options that reach the option register (QSF names in the table's `settings`).  Defaults = the base build of the pair runs."""
    __slots__ = ("user_clk", "release_clears", "init_done", "dev_clr", "dev_oe", "auto_restart", "crc_check", "crc_div", "crc_atom_div",
                 "nceo_regular_io", "oct_done", "passive_scheme", "tristate_spi", "as_clock", "pof_id")

    def __init__(self):
        self.user_clk = self.release_clears = self.init_done = self.dev_clr = self.dev_oe = False
        self.auto_restart = True            # QSF default ON (pair auto_restart_off flips bit 6)
        self.crc_check = False
        self.crc_div = 1                    # ERROR_CHECK_FREQUENCY_DIVISOR; only used when crc_check
        self.crc_atom_div = None            # oscillator_divider of a cycloneiv_crcblock atom, None = no atom
        self.nceo_regular_io = self.oct_done = self.passive_scheme = self.tristate_spi = False
        self.as_clock = "FREQ_40MHz"        # ACTIVE_SERIAL_CLOCK legal values: CLKUSR, FREQ_20MHz, FREQ_40MHz (assembler warning text)
        self.pof_id = 1                     # per part (vendor_value of bits 11..18); no QSF setting


def _on(v):
    return str(v).strip('"').upper() in ("ON", "TRUE", "YES", "1")


def config_from_qsf(assigns, design=None):
    """((qsf name, value), ...) + optional design kind -> Config.  Unknown names change nothing (listed in the doc as no-effect)."""
    c = Config()
    for name, val in assigns or ():
        v = str(val).strip('"')
        if name == "USER_START_UP_CLOCK":
            c.user_clk = _on(v)
        elif name == "RELEASE_CLEARS_BEFORE_TRI_STATES":
            c.release_clears = _on(v)
        elif name == "ENABLE_INIT_DONE_OUTPUT":
            c.init_done = _on(v)
        elif name == "ENABLE_DEVICE_WIDE_RESET":
            c.dev_clr = _on(v)
        elif name == "ENABLE_DEVICE_WIDE_OE":
            c.dev_oe = _on(v)
        elif name == "AUTO_RESTART_CONFIGURATION":
            c.auto_restart = _on(v)
        elif name in ("CRC_ERROR_CHECKING", "STRATIX_CRC_ERROR_CHECKING"):
            c.crc_check = _on(v)
        elif name == "ERROR_CHECK_FREQUENCY_DIVISOR":
            c.crc_div = int(v)
        elif name == "CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION":
            c.nceo_regular_io = v.upper() == "USE AS REGULAR IO"
        elif name == "ENABLE_OCT_DONE":
            c.oct_done = _on(v)
        elif name == "CYCLONEIII_CONFIGURATION_SCHEME":
            c.passive_scheme = v.upper() in ("PASSIVE SERIAL", "FAST PASSIVE PARALLEL")
        elif name == "TRI_STATE_SPI_PINS":
            c.tristate_spi = _on(v)
        elif name == "ACTIVE_SERIAL_CLOCK" and v in ("CLKUSR", "FREQ_20MHz", "FREQ_40MHz"):
            c.as_clock = v
    if design and design.startswith("crcblock_div"):
        c.crc_atom_div = int(design[len("crcblock_div"):])
    elif design == "crcblock_loc":
        c.crc_atom_div = 1
    return c


def _put(v, bits, value):
    for k, i in enumerate(bits):
        v[i] = (value >> k) & 1


def encode(c):
    """Config -> 160 value bits.  Group bits from the decoded rules; the 130 listed bits and the POF id come from the vendor sof (value 1 / table)."""
    g = groups()
    v = default_vector()
    inv = {"OPTION_REG_USE_CLKUSR": c.user_clk, "OPTION_REG_RELEASE_CLEAR_BEFORE_TRI": c.release_clears, "OPTION_REG_USE_INITDONE": c.init_done,
           "DEVICE_USE_GLOBAL_CLEAR": c.dev_clr, "DEVICE_USE_GLOBAL_TRI": c.dev_oe, "OPTION_REG_USE_NCEO": not c.nceo_regular_io,
           "OPTION_REG_WAIT_FOR_OCTDONE": c.oct_done}
    for name, on in inv.items():                       # polarity "inverted" in the table: bit = NOT setting
        _put(v, g[name], 0 if on else 1)
    _put(v, g["OPTION_REG_ENABLE_AUTO_RECONFIGURE"], int(c.auto_restart))      # polarity "direct"
    det = g["OPTION_REG_USE_ERROR_DETECT"]
    v[det[0]] = 0 if (c.crc_check or c.crc_atom_div) else 1
    v[det[1]] = 1 if c.crc_check else 0
    div = c.crc_atom_div if c.crc_atom_div else (c.crc_div if c.crc_check else 1)
    _put(v, g["OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER"], 0 if div <= 1 else 1 << (div.bit_length() - 2))   # one-hot: 2^k -> bit k-1
    _put(v, g["OPTION_REG_SELECT_SPI_PIN_STATE"], 3 if c.passive_scheme else (0 if c.tristate_spi else 2))
    _put(v, g["OPTION_REG_EXTERNAL_CLK_SPI"], {"FREQ_20MHz": 3, "FREQ_40MHz": 1, "CLKUSR": 0}[c.as_clock])
    _put(v, g["OPTION_REG_SET_POF_ID"], c.pof_id)
    return v


def decode(value_bits):
    """160 value bits -> {group name: decoded value} for the 13 groups (raw integer, LSB = lowest bit index)."""
    return {name: sum(int(value_bits[i]) << k for k, i in enumerate(bits)) for name, bits in groups().items()}


def score(observed, predicted):
    """Per class counts of one build: matched (equal), wrong (differ).  Both 160-bit value vectors."""
    out = {k: dict(matched=0, wrong=0) for k in classes()}
    for k, idx in classes().items():
        for i in idx:
            out[k]["matched" if observed[i] == predicted[i] else "wrong"] += 1
    return out


def flip_score(base_obs, spec_obs, base_pred, spec_pred):
    """Pair-level flips: matched (flipped in both), missing (observed flip not predicted), extra (predicted flip not observed)."""
    o = {i for i in range(N_BITS) if base_obs[i] != spec_obs[i]}
    p = {i for i in range(N_BITS) if base_pred[i] != spec_pred[i]}
    return dict(matched=len(o & p), missing=len(o - p), extra=len(p - o))
