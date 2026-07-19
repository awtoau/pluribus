#!/usr/bin/env python3
"""Verify the NATIVE gowin_unpack BSRAM decode against the bridge oracle.

Regression guard for issue #69.  `scripts/gowin_bsram_ports.py` is an external
bridge that reads the BSRAM site portmap directly from the static tile db and
canonicalises every wire through the same alias path `gowin_unpack.py` uses.
Before the #69 fix the native `.gwconfig` emitted BSRAM records with ZERO ports
(the placed name ``BSRAM0`` missed the static key ``BSRAM``); after it, the two
must agree wire-for-wire.

Runs under ANY python3 — it only reads the two artefacts, no apycula import.

Usage:
    gowin_bsram_verify.py --gwconfig tmp/gw/target.gwconfig --bridge tmp/gw/bridge.json
"""

import argparse
import json
import sys


def parse_gwconfig_bsram(path):
    """{(row, col): {port: node}} for every BSRAM hardip record."""
    out = {}
    with open(path) as fh:
        for line in fh:
            f = line.split()
            if len(f) < 4 or f[0] != "hardip" or f[3] != "BSRAM":
                continue
            row, col = int(f[1]), int(f[2])
            ports = {}
            for tok in f[4:]:
                if "=" not in tok or tok.startswith("bel="):
                    continue
                k, v = tok.split("=", 1)
                ports[k] = v
            out[(row, col)] = ports
    return out


def parse_bridge(path):
    """{(row, col): {port: node}} from the bridge JSON sidecar."""
    with open(path) as fh:
        blocks = json.load(fh)
    out = {}
    for b in blocks:
        ports = {}
        for port, wires in b["ports"].items():
            if len(wires) == 1:
                ports[port] = wires[0]
            else:
                for i, w in enumerate(wires):
                    ports[f"{port}{i}"] = w
        out[(b["row"], b["col"])] = ports
    return out


def compare(native, bridge):
    """Return a list of human-readable difference strings ([] == match)."""
    diffs = []
    if set(native) != set(bridge):
        diffs.append(f"site set differs: native={sorted(native)} "
                     f"bridge={sorted(bridge)}")
        return diffs
    for loc in sorted(native):
        n, b = native[loc], bridge[loc]
        for port in sorted(set(n) | set(b)):
            if port not in n:
                diffs.append(f"R{loc[0]+1}C{loc[1]+1} {port}: MISSING from native "
                             f"(bridge={b[port]})")
            elif port not in b:
                diffs.append(f"R{loc[0]+1}C{loc[1]+1} {port}: extra in native "
                             f"({n[port]})")
            elif n[port] != b[port]:
                diffs.append(f"R{loc[0]+1}C{loc[1]+1} {port}: native={n[port]} "
                             f"bridge={b[port]}")
    return diffs


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gwconfig", required=True, help="native decode output")
    ap.add_argument("--bridge", required=True, help="gowin_bsram_ports.py JSON")
    args = ap.parse_args()

    native = parse_gwconfig_bsram(args.gwconfig)
    bridge = parse_bridge(args.bridge)
    print(f"[gowin_bsram_verify] native: {len(native)} BSRAM site(s), "
          f"{sum(len(v) for v in native.values())} ports")
    print(f"[gowin_bsram_verify] bridge: {len(bridge)} BSRAM site(s), "
          f"{sum(len(v) for v in bridge.values())} ports")

    diffs = compare(native, bridge)
    if diffs:
        print(f"[gowin_bsram_verify] MISMATCH ({len(diffs)}):", file=sys.stderr)
        for d in diffs[:40]:
            print(f"  {d}", file=sys.stderr)
        if len(diffs) > 40:
            print(f"  ... and {len(diffs) - 40} more", file=sys.stderr)
        return 1
    print("[gowin_bsram_verify] MATCH — native decode == bridge oracle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
