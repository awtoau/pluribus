"""Parametric Trellis lifter — family-dispatch entry point.

Returns a family-specific lifter instance via TrellisLift(family, device).
The returned object exposes the same interface regardless of family:
  parse_config(path)           → ParsedConfig
  recover_netlist(pc)          → Design
  arc_endpoint_sets(pc)        → (set, set)
  load_efb_fixed_conns()       → dict
  apply_efb_fixed_conns(...)
  pad_fabric_node(row, col, pio, direction)
  bels_of(row, col)

Supported families:
  "machxo2"   fully implemented (lifters/machxo2_lift.py)
  "ecp5"      implemented (lifters/ecp5_lift.py) — LUT4/FF/routing/pad recovery,
              round-trip verified against nextpnr placement.  A sibling class
              rather than a family flag on MachXO2Lift on purpose: the MachXO2
              gkey() carries tile-database workarounds that are wrong for ECP5.
              Shared machinery (DSU/ParsedConfig/Design/ff_d_source) is imported.
  "gowin"     GW1N first slice (lifters/gowin_lift.py) — LUT4 + DFF recovery
              from a `.gwconfig` text config decoded by scripts/gowin_unpack.py.
              Not a Trellis family, but shares the lifter interface so load.py's
              generic core (nets/FFs/LUTs/net_fanout/arcs) drives it unchanged.
  "anlogic"   Anlogic EG4 / eagle_s20 (lifters/anlogic_lift.py) — tile grid +
              LUT4-init recovery from a `.anloconfig` decoded by
              scripts/anlogic_unpack.py against the Tang-Dynasty fuse DB
              (scripts/anlogic_dbdecode.py).  Routing/mux decode is future work.
  "cyclonev"  Altera/Intel Cyclone V, e50f die only / 5CEBA4U19C8
              (lifters/cyclonev_lift.py) — LUT/FF/routing recovery from a
              Mistral (Ravenslofty/mistral) `.bt` decompile text dump, the
              only available reference decoder for this vendor (no
              prjtrellis equivalent).  Not a Lattice family at all — a
              completely different fabric (ALM/LAB, not PFU/slice) sharing
              only the lifter interface.  M10K/DSP content decode, HPS, and
              ALM arithmetic/carry mode are out of scope (upstream-Mistral
              unknowns or deferred, not pluribus gaps).  ALM-half cells are
              genuine LUT5s (5 inputs, 32-bit truth table) recovered onto
              the shared `Design.luts`/`luts` table, which carries a 5th
              input column `e` and a 32-char init for this family.
"""


def TrellisLift(family, device, **kwargs):
    """Instantiate a lifter for the given family and device string.

    family: "machxo2" | "ecp5" | "gowin" | "anlogic" | "cyclonev"  (case-insensitive)
    device: e.g. "LCMXO2-1200", "LFE5U-12F", "GW1N-1", "5CEBA4U19C8"
    """
    fam = family.lower()
    if fam == "machxo2":
        from lifters.machxo2_lift import MachXO2Lift
        return MachXO2Lift(device, **kwargs)
    elif fam == "ecp5":
        from lifters.ecp5_lift import ECP5Lift
        return ECP5Lift(device, **kwargs)
    elif fam == "gowin":
        from lifters.gowin_lift import GowinLift
        return GowinLift(device, **kwargs)
    elif fam == "anlogic":
        from lifters.anlogic_lift import AnlogicLift
        return AnlogicLift(device, **kwargs)
    elif fam == "cyclonev":
        from lifters.cyclonev_lift import CycloneVLift
        return CycloneVLift(device, **kwargs)
    else:
        raise ValueError(
            f"Unknown family {family!r}. "
            f"Supported: machxo2, ecp5, gowin, anlogic, cyclonev. "
            f"To add a new family, create lifters/<family>_lift.py and "
            f"register it here."
        )
