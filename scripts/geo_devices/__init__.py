"""Device adapters for the geo explorer (docs/geo-adapters.md): one module per family."""
import importlib

FAMILIES = ("cycloneiv", "machxo2", "ecp5", "gowin")


def adapter(family):
    if family not in FAMILIES:
        raise SystemExit(f"geo_devices: no adapter for family {family!r} (have {', '.join(FAMILIES)})")
    return importlib.import_module(f"geo_devices.{family}")
