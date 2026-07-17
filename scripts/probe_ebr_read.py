#!/usr/bin/env python3
"""Probe a simulation VCD for the behavioural EBR read datapath.

The recovered design models each EBR as `ebr_<tag>_dout <= ebr_<tag>_mem[raddr]`
(emit_ebr).  This reads a sim VCD and reports, for the requested EBR dout /
read-address / read-clock signals, their value trace over time — the question
being whether, once the fabric read-address counter FFs power up (reg init 0),
the read output actually *sweeps the prefilled ramp* or stays flat/X because the
off-fabric control (ghost read-enable) never advances the counter.

Pure-Python 4-state VCD reader (no deps).  Logs to tmp/probe_ebr_read.log.

    python3.15t scripts/probe_ebr_read.py tmp/aw2_tb.vcd ebr_r6c7_dout
"""
import re
import sys
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_vcd(path, wanted):
    """Return {signame: [(time, value_str), ...]} for signals whose name
    contains any of `wanted`.  value_str is the raw 4-state VCD value."""
    id_to_names = {}          # vcd id char(s) -> [full names]
    want_ids = set()
    scope = []
    with open(path) as fh:
        # header: $var declarations
        for line in fh:
            line = line.strip()
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                if scope:
                    scope.pop()
            elif line.startswith("$var"):
                # $var wire 9 ! ebr_r6c7_dout [8:0] $end
                p = line.split()
                vid = p[3]
                name = p[4]
                full = ".".join(scope + [name])
                id_to_names.setdefault(vid, []).append(full)
                if any(w in name for w in wanted):
                    want_ids.add(vid)
            elif line.startswith("$enddefinitions"):
                break
        # body
        traces = {vid: [] for vid in want_ids}
        t = 0
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line[0] == "#":
                t = int(line[1:])
            elif line[0] in "01xzXZ":              # scalar
                vid = line[1:]
                if vid in want_ids:
                    traces[vid].append((t, line[0]))
            elif line[0] in "bB":                   # vector: bVALUE id
                val, vid = line[1:].split()
                if vid in want_ids:
                    traces[vid].append((t, val))
    out = {}
    for vid, tr in traces.items():
        for nm in id_to_names[vid]:
            out[nm] = tr
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: probe_ebr_read.py <vcd> <signal-substr> [more...]")
    vcd = sys.argv[1]
    wanted = sys.argv[2:]
    log = os.path.join(REPO, "tmp", "probe_ebr_read.log")
    traces = read_vcd(vcd, wanted)
    lines = []
    for nm in sorted(traces):
        tr = traces[nm]
        # collapse consecutive-equal values
        squashed = []
        for t, v in tr:
            if not squashed or squashed[-1][1] != v:
                squashed.append((t, v))
        vals = [v for _, v in squashed]
        distinct = sorted(set(vals))
        defined = [v for v in vals if not re.search(r"[xzXZ]", v)]
        lines.append(f"=== {nm} ===")
        lines.append(f"  changes={len(squashed)}  distinct_values={len(distinct)}  "
                     f"defined_changes={len(defined)}")
        # show the first ~24 distinct transitions
        for t, v in squashed[:24]:
            lines.append(f"    t={t:<10} {v}")
        if len(squashed) > 24:
            lines.append(f"    ... (+{len(squashed) - 24} more)")
        # ramp check: are the defined values monotonically stepping?
        if len(set(defined)) > 2:
            lines.append(f"  -> {len(set(defined))} distinct DEFINED values "
                         f"(datapath is sweeping, not flat)")
        elif defined:
            lines.append(f"  -> only {len(set(defined))} defined value(s) "
                         f"(flat / not sweeping)")
        else:
            lines.append("  -> no defined values (stays X/Z — off-fabric "
                         "control never advances it)")
        lines.append("")
    text = "\n".join(lines) if lines else "(no matching signals in VCD)"
    with open(log, "w") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
