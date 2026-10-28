#!/usr/bin/env python3
"""Measure and greedily order routed fabric-test candidates.

The fan-in curve from ``fabric_coverage_plan.py`` is a ceiling for a perfect
packer, not achieved coverage. This script reads the ``top.config`` files the
toolchain actually produced and orders them by new configurable arcs per tile
type, breaking ties by new physical-instance arcs. It never discards candidates,
so a run of hundreds or thousands remains an anytime quick go/no-go suite.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

TILE = re.compile(r"^\.tile\s+(\S+)")
ARC = re.compile(r"^arc:\s+(\S+)\s+(\S+)")


def config_arcs(path):
    """Return ``(physical keys, tile-type keys)`` from one routed config."""
    physical, types = set(), set()
    tile = kind = None
    for line in Path(path).read_text().splitlines():
        match = TILE.match(line)
        if match:
            tile, _, kind = match.group(1).partition(":")
            continue
        match = ARC.match(line)
        if match and tile is not None:
            dest, source = match.groups()
            physical.add((tile, dest, source))
            types.add((kind, dest, source))
    return physical, types


def greedy_order(paths):
    """Greedy maximum-new-type-arc order, deterministic on input order."""
    candidates = [(Path(path), *config_arcs(path)) for path in paths]
    remaining = list(range(len(candidates)))
    seen_physical, seen_types = set(), set()
    ordered, steps = [], []
    while remaining:
        best = max(remaining, key=lambda i: (
            len(candidates[i][2] - seen_types),
            len(candidates[i][1] - seen_physical),
            -i))
        remaining.remove(best)
        path, physical, types = candidates[best]
        new_types = len(types - seen_types)
        new_physical = len(physical - seen_physical)
        seen_types.update(types)
        seen_physical.update(physical)
        ordered.append(path)
        steps.append({"config": str(path),
                      "type_new": new_types,
                      "type_total": len(seen_types),
                      "instance_new": new_physical,
                      "instance_total": len(seen_physical)})
    return ordered, steps


def inputs_digest(paths):
    digest = hashlib.sha256()
    for path in paths:
        path = Path(path)
        name = str(path).encode()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--json", type=Path,
                        help="write the reproducible ordered manifest here")
    args = parser.parse_args()
    missing = [str(path) for path in args.configs if not path.exists()]
    if missing:
        parser.error("missing config(s): " + ", ".join(missing))

    ordered, steps = greedy_order(args.configs)
    result = {"metric": "configurable routing arcs per tile type",
              "tie_breaker": "configurable routing arcs per physical instance",
              "input_sha256": inputs_digest(args.configs),
              "candidates": len(args.configs),
              "steps": steps}
    for index, step in enumerate(steps, 1):
        print(f"{index:4}  {step['config']}  +{step['type_new']:,} type  "
              f"+{step['instance_new']:,} physical")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + "\n")
        print(f"manifest: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
