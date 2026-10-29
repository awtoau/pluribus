from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fabric_coverage_select import config_arcs, greedy_order  # noqa: E402
from fabric_test_bridge import read_manifest                 # noqa: E402
from fabric_test_gen import coverage_variant                 # noqa: E402


def write_config(path, tiles):
    lines = []
    for tile, kind, arcs in tiles:
        lines.append(f".tile {tile}:{kind}")
        lines.extend(f"arc: {dest} {source}" for dest, source in arcs)
    path.write_text("\n".join(lines) + "\n")


def test_greedy_prefers_new_type_arcs_then_physical(tmp_path):
    repeated = tmp_path / "repeated.config"
    diverse = tmp_path / "diverse.config"
    physical = tmp_path / "physical.config"
    write_config(repeated, [("R1C1", "PLC2", [("D0", "S0")])])
    write_config(diverse, [("R1C2", "PLC2", [("D0", "S0"), ("D1", "S1")])])
    write_config(physical, [("R2C2", "PLC2", [("D0", "S0")])])

    ordered, steps = greedy_order([repeated, physical, diverse])
    assert ordered == [diverse, repeated, physical]
    assert steps[0]["type_new"] == 2
    assert steps[1]["type_new"] == 0
    assert steps[1]["instance_new"] == 1
    physical_keys, type_keys = config_arcs(diverse)
    assert ("R1C2", "D1", "S1") in physical_keys
    assert ("PLC2", "D1", "S1") in type_keys


def test_variant_schedule_and_extended_manifest(tmp_path):
    assert coverage_variant(0) == (1, 0x9E3779B9, 3)
    assert coverage_variant(1) == (2, 0x3C6EF372, 4)
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text(
        "# device=LFE5U-12F blocks=185 cycles=262144\n"
        "fabric_test_00\t0x1\t0x2\t7\t0x1234\t3\n")
    designs, meta = read_manifest(manifest)
    assert meta["blocks"] == "185"
    assert designs[0]["placement_seed"] == "7"
    assert designs[0]["topology_seed"] == "0x1234"
    assert designs[0]["tree_fanin"] == "3"
