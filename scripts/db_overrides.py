#!/usr/bin/env python3
"""Pluribus-owned MachXO2 tile-DB corrections (issue #29).

The external prjtrellis MachXO2 tile database has a handful of decoder gaps.
Rather than hand-edit that database — which is outside pluribus's scope and
would be lost on any re-clone/rebuild — pluribus carries the corrections here
and the native decoder (`native_tile_decode.get_tile_type`) applies them on top
of the freshly-parsed base tiledata. Each correction is backed by corpus
evidence gathered across the diamond-fuzz set; see issue #29.

Format:
    {family: {tiletype: {"enum_options": {enum_name: {option: "F1B33 F1B34"}}}}}

An option's bit string (space-separated `[!]F<frame>B<bit>` tokens, same syntax
as bits.db) REPLACES that option's bit group when the option already exists, or
ADDS the option when it does not. Only the named options are touched; every
other option, word, and mux in the tile is left exactly as the base DB has it.
"""

# family -> tiletype -> {"enum_options": {enum: {option: bit-token string}}}
OVERRIDES = {
    "MachXO2": {
        # EBR1 mode + position (corrects #29 gap 1 and #62 gap 2).
        # MODE = F0B13 F1B8 F1B20 F1B21 F1B22 (set in every active EBR1 tile);
        # FIFO8KB adds F1B0.  DP8KC and PDPW8KC encode identically, so the
        # decoder cannot tell them apart.
        # F1B32..F1B35 is a 4-bit position code (EBR 3..9 left to right on
        # LCMXO2-1200), not a mode field: the earlier F1B33+F1B34 / F1B32 rules
        # held only for the two sites the fuzz corpus used (V07 bitstream:
        # 5 of 7 blocks left MODE undecoded).  Carries no configuration.
        "EBR1": {"enum_options": {
            "EBR.MODE": {
                "DP8KC":   "F0B13 F1B8 F1B20 F1B21 F1B22",
                "FIFO8KB": "F0B13 F1B0 F1B8 F1B20 F1B21 F1B22",
                "PDPW8KC": "F0B13 F1B8 F1B20 F1B21 F1B22",
            },
            "EBR.SITE_ID": {
                str(v): " ".join(("" if v >> i & 1 else "!") + f"F1B{32 + i}" for i in range(4))
                for v in range(1, 16)
            },
        }},
        # Item 5 — CIB_CFG2 F3B0: EFB_ENABLE flag (issue #62).
        # F3B0 is set whenever any EFB peripheral (I2C, SPI, TC, UFM) is
        # instantiated; clear in designs with no EFB.  Confirmed across all
        # three corpus bitstreams (V02/V4/V07 all have EFB/SPI) and all 31
        # EFB fuzz targets.  Not set by SYSCONFIG LPF preferences — those
        # live in the CTRL0 register outside the tile CRAM.
        # Not in CIB_CFG2/bits.db — genuinely uncatalogued.
        "CIB_CFG2": {"enum_options": {
            "EFB.ENABLE": {"ENABLED": "F3B0"},
        }},
        # Gap 4 — PIC_B0 FAILSAFE_RCV. A standalone failsafe-receiver bit set
        # alone (no BASE_TYPE companion) in 31 corpus targets (EFB/syscfg/cfgspi)
        # was dropped. It is PIOC=F4B39 / PIOD=F5B39 (not PIOA/PIOB as #29 first
        # supposed). Modeled as a BASE_TYPE option so the most-bits tie-break
        # keeps real multi-bit standards winning where both are present.
        "PIC_B0": {"enum_options": {
            "PIOC.BASE_TYPE": {"FAILSAFE_RCV": "F4B39"},
            "PIOD.BASE_TYPE": {"FAILSAFE_RCV": "F5B39"},
        }},
    },
}


def apply_overrides(tt, family, tiletype, bitgroup):
    """Mutate a freshly-parsed TileType in place with the #29 corrections.

    `bitgroup` is `native_tile_decode._bitgroup` (a token list -> frozenset of
    cbits), passed in to reuse the exact base parser and avoid a circular import.
    A no-op for any tile type without an override.
    """
    ov = OVERRIDES.get(family, {}).get(tiletype)
    if not ov:
        return
    for enum_name, opts in ov.get("enum_options", {}).items():
        entry = tt.enums.get(enum_name)
        if entry is None:
            defval, options = None, {}
        else:
            defval, options = entry[0], dict(entry[1])
        for opt, bits in opts.items():
            options[opt] = bitgroup(bits.split())
        tt.enums[enum_name] = (defval, options)
