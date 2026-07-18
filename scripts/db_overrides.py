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
        # Gap 1 — EBR.MODE bit-address bug. The mode-select was keyed on F1B35,
        # which is set in 0 of 631 corpus EBR blocks; F1B33 AND F1B34 are set in
        # every active block. With F1B35 the enum never matched and MODE (plus 6
        # width bits) dropped as unknown. Width bits unchanged; only the two
        # mode-select bits corrected.
        "EBR1": {"enum_options": {"EBR.MODE": {
            "DP8KC":   "F0B13 F1B8 F1B20 F1B21 F1B22 F1B33 F1B34",
            "FIFO8KB": "F0B13 F1B0 F1B8 F1B20 F1B21 F1B22 F1B33 F1B34",
            "PDPW8KC": "F0B13 F1B8 F1B20 F1B21 F1B22 F1B33 F1B34",
        }}},
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
