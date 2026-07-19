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
  "ecp5"      device init only; recovery raises NotImplementedError (issue #9)
  "gowin"     GW1N first slice (lifters/gowin_lift.py) — LUT4 + DFF recovery
              from a `.gwconfig` text config decoded by scripts/gowin_unpack.py.
              Not a Trellis family, but shares the lifter interface so load.py's
              generic core (nets/FFs/LUTs/net_fanout/arcs) drives it unchanged.
"""


def TrellisLift(family, device, **kwargs):
    """Instantiate a lifter for the given family and device string.

    family: "machxo2" | "ecp5" | "gowin"  (case-insensitive)
    device: e.g. "LCMXO2-1200", "LFE5U-12F", "GW1N-1"
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
    else:
        raise ValueError(
            f"Unknown family {family!r}. "
            f"Supported: machxo2, ecp5, gowin. "
            f"To add a new family, create lifters/<family>_lift.py and "
            f"register it here."
        )
