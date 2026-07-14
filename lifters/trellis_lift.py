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
"""


def TrellisLift(family, device, **kwargs):
    """Instantiate a lifter for the given Trellis family and device string.

    family: "machxo2" | "ecp5"  (case-insensitive)
    device: e.g. "LCMXO2-1200", "LFE5U-12F"
    """
    fam = family.lower()
    if fam == "machxo2":
        from lifters.machxo2_lift import MachXO2Lift
        return MachXO2Lift(device, **kwargs)
    elif fam == "ecp5":
        from lifters.ecp5_lift import ECP5Lift
        return ECP5Lift(device, **kwargs)
    else:
        raise ValueError(
            f"Unknown Trellis family {family!r}. "
            f"Supported: machxo2, ecp5. "
            f"To add a new family, create lifters/<family>_lift.py and "
            f"register it here."
        )
