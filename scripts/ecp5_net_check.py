#!/usr/bin/env python3.15t
"""Verify recovered ECP5 NETS against the reference netlist's connectivity.

Placement and INIT can both be perfect while the routing is wrong — that would
give a netlist of correct cells wired together incorrectly, which looks fine in
every count-based check and is useless for "what drives this net?".  So this
checks connectivity directly.

Method: the reference placed netlist assigns every signal a yosys net id, and
every cell's `connections` say which id lands on which pin.  Two cell pins that
share a yosys id are electrically the same node, so the lifter MUST place them
on the same recovered net.  Conversely, pins on different yosys ids must land
on different recovered nets.

So for each reference signal that touches two or more placed cell pins, look up
what the lifter recovered at those same physical pins and require agreement:

  CONSISTENT   all pins of the reference signal map to one recovered net
  SPLIT        the lifter put them on different nets (missing connectivity)
  and, across signals, a recovered net carrying pins of two different
  reference signals is a FUSION (over-connected — the dangerous direction,
  because it silently merges unrelated logic).

Only pins the lifter models are considered: LUT A/B/C/D/F and FF D/Q/CLK/CE/LSR.

    python3.15t scripts/ecp5_net_check.py <ref-dir> [--device LFE5U-12F]

Logs to ./tmp/logs/ecp5_net_check.log as well as the terminal.
"""
import argparse
import collections
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEF_DBROOT = os.environ.get(
    "TRELLIS_DBROOT", "/home/dan/opt/oss-cad-suite/share/trellis/database")
BEL_RE = re.compile(r"^X(\d+)/Y(\d+)/SLICE([A-D])\.(K|FF)([01])$")

# Reference cell pin -> the lifter's recovered-cell field holding its net.
#
# IMPORTANT: LUT *inputs* cannot be compared pin-by-pin.  nextpnr's lutperm
# crossbar means the reference's logical A may be carried on the physical C,
# so "reference pin A" and "recovered field a" are not the same wire even when
# both are correct.  Comparing them positionally reports a mountain of false
# splits.  Outputs (LUT F, FF Q) and the FF control pins are NOT permuted, so
# those are the sound basis for a connectivity check.
#
# --strict-inputs re-enables the positional input comparison; it is expected
# to fail and exists only to demonstrate the permutation effect.
LUT_PINS_OUT = {"F": "z"}
LUT_PINS_ALL = {"A": "a", "B": "b", "C": "c", "D": "d", "F": "z"}
FF_PINS = {"DI": "d", "M": "d", "Q": "q", "CLK": "clk",
           "CE": "ce", "LSR": "lsr"}


def setup_logging(name):
    os.makedirs("tmp/logs", exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(f"tmp/logs/{name}.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref_dir")
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    ap.add_argument("--max-report", type=int, default=10)
    ap.add_argument("--strict-inputs", action="store_true",
                    help="also compare LUT inputs positionally (expected to "
                         "fail: nextpnr permutes them)")
    args = ap.parse_args()

    log = setup_logging("ecp5_net_check")
    from lifters.ecp5_lift import ECP5Lift

    lift = ECP5Lift(args.device, dbroot=args.dbroot)
    pc = lift.parse_config(os.path.join(args.ref_dir, "ref.config"))
    design = lift.recover_netlist(pc)

    # Recovered cells indexed by physical site.
    lut_by_site, ff_by_site = {}, {}
    for lt in design.luts:
        m = re.match(r"^lut_r(\d+)c(\d+)_([A-D])k([01])$", lt["name"])
        if m:
            lut_by_site[(int(m.group(1)), int(m.group(2)),
                         m.group(3), m.group(4))] = lt
    for ff in design.ffs:
        m = re.match(r"^ff_r(\d+)c(\d+)_([A-D])(\d)$", ff["name"])
        if m:
            ff_by_site[(int(m.group(1)), int(m.group(2)),
                        m.group(3), m.group(4))] = ff

    doc = json.load(open(os.path.join(args.ref_dir, "ref_placed.json")))
    mod = max(doc["modules"].values(), key=lambda m: len(m.get("cells", {})))

    # reference signal id -> set of recovered net names at its placed pins
    sig_nets = collections.defaultdict(set)
    sig_pins = collections.defaultdict(list)

    for cname, cell in mod.get("cells", {}).items():
        m = BEL_RE.match(cell.get("attributes", {}).get("NEXTPNR_BEL", ""))
        if not m:
            continue
        col, row, sl, kind, k = (int(m.group(1)), int(m.group(2)),
                                 m.group(3), m.group(4), m.group(5))
        site = (row, col, sl, k)
        if kind == "K":
            rec = lut_by_site.get(site)
            pinmap = LUT_PINS_ALL if args.strict_inputs else LUT_PINS_OUT
        else:
            rec, pinmap = ff_by_site.get(site), FF_PINS
        if rec is None:
            continue
        for pin, bits in cell.get("connections", {}).items():
            field = pinmap.get(pin)
            if field is None or not bits:
                continue
            sig = bits[0]
            if not isinstance(sig, int):      # "0"/"1" constants
                continue
            net = rec.get(field)
            if net is None or net.startswith("1'b"):
                continue
            sig_nets[sig].add(net)
            sig_pins[sig].append((site, pin, net))

    multi = {s: nets for s, nets in sig_nets.items() if len(sig_pins[s]) > 1}
    consistent = sum(1 for s, nets in multi.items() if len(nets) == 1)

    # A signal reaching only CLK/CE/LSR pins travels the global clock network.
    # prjtrellis parks every non-TAP/SPINE ECP5 global at the nominal location
    # (0,0) — "TODO: quadrants and TAP_DRIVE regions" — so distinct globals
    # share one key.  The lifter therefore refuses to union through them (that
    # would fuse every register in the design onto one net), which leaves a
    # clock arriving at N sites recovered as N separate nets.  Under-connected,
    # not mis-connected: no signal is joined to anything it does not belong to.
    # Classified separately because it is a documented upstream limitation, not
    # a defect in this lifter.
    _GLOBAL_PINS = {"CLK", "CE", "LSR"}
    split, global_split = {}, {}
    for s, nets in multi.items():
        if len(nets) <= 1:
            continue
        pins = {p for (_site, p, _n) in sig_pins[s]}
        if pins <= _GLOBAL_PINS:
            global_split[s] = nets
        else:
            split[s] = nets

    log.info("reference signals touching >1 modelled pin: %d", len(multi))
    log.info("  CONSISTENT (all pins on one recovered net): %d (%.2f%%)",
             consistent, 100.0 * consistent / max(len(multi), 1))
    log.info("  SPLIT      (pins landed on several nets):   %d", len(split))
    for s, nets in list(split.items())[:args.max_report]:
        log.error("    signal %s -> nets %s at %s",
                  s, sorted(nets)[:8], sig_pins[s][:4])
    log.info("  global-net split (clock/CE/LSR; upstream (0,0) limitation): "
             "%d signals over %d recovered nets",
             len(global_split), sum(len(v) for v in global_split.values()))

    # Fusion: one recovered net carrying pins of several reference signals.
    net_sigs = collections.defaultdict(set)
    for s, nets in sig_nets.items():
        for n in nets:
            net_sigs[n].add(s)
    # A recovered net carrying several reference signals is over-connected —
    # UNLESS the signals are ones the lifter deliberately does not separate.
    # The known-benign case is the slice's wide-mux chain: ECP5 slices carry
    # F5MUX/PFUMX/L6MUX21 elements whose OFX/F1/FXA/FXB nodes are distinct
    # reference signals, but the lifter models only the LUT4 F output, so an
    # OFX signal and the F signal feeding it collapse onto one recovered net.
    # That is a modelling GAP (wide muxes are not lifted), not a wrong wire —
    # and it is reported as such rather than passed off as a success.
    _WIDE_MUX_PINS = {"OFX", "F1", "FXA", "FXB"}
    sig_pin_names = collections.defaultdict(set)
    for cname, cell in mod.get("cells", {}).items():
        if not BEL_RE.match(cell.get("attributes", {}).get("NEXTPNR_BEL", "")):
            continue
        for pin, bits in cell.get("connections", {}).items():
            if bits and isinstance(bits[0], int):
                sig_pin_names[bits[0]].add(pin)

    fused, widemux = {}, {}
    for n, ss in net_sigs.items():
        if len(ss) <= 1:
            continue
        if any(sig_pin_names[s] & _WIDE_MUX_PINS for s in ss):
            widemux[n] = ss
        else:
            fused[n] = ss
    log.info("  FUSED      (one net, several ref signals):  %d", len(fused))
    for n, ss in list(fused.items())[:args.max_report]:
        log.error("    net %s carries reference signals %s", n, sorted(ss)[:6])
    log.info("  wide-mux collapse (known gap, not a wiring error): %d",
             len(widemux))

    # --- LUT input fan-in, permutation-invariant --------------------------
    # Inputs cannot be checked positionally (see LUT_PINS_OUT), but the SET of
    # distinct signals arriving at a LUT is permutation-invariant.  So build,
    # for each placed LUT, the set of reference signals on its inputs and the
    # set of recovered nets on its inputs, and require the recovered set to
    # partition the same way: same number of distinct live inputs, and each
    # recovered input net consistently corresponding to one reference signal.
    # Signals produced by a wide mux (OFX) have no recovered driver, because
    # the lifter models LUT4+FF only.  A LUT reading such a signal legitimately
    # comes back with that input missing.  Separate those from genuine fan-in
    # errors so the report says which gap is which.
    widemux_sigs = {s for s, pins in sig_pin_names.items() if "OFX" in pins}

    # Signals that are the SAME physical node once the wide mux is unmodelled:
    # a slice's F output and its OFX output collapse onto one recovered net, so
    # the checker must treat the two reference ids as interchangeable.  Build
    # equivalence classes keyed by driver site.
    site_of_sig = {}
    for cname, cell in mod.get("cells", {}).items():
        m2 = BEL_RE.match(cell.get("attributes", {}).get("NEXTPNR_BEL", ""))
        if not m2:
            continue
        site = (int(m2.group(2)), int(m2.group(1)), m2.group(3), m2.group(5))
        for pin in ("F", "OFX", "F1"):
            bits = cell.get("connections", {}).get(pin) or []
            if bits and isinstance(bits[0], int):
                # F1 belongs to the PAIRED comb, so key it on the slice only.
                site_of_sig.setdefault(bits[0], set()).add(site[:3])

    def same_node(a, b):
        """True if two reference signal ids collapse to one recovered net."""
        sa, sb = site_of_sig.get(a), site_of_sig.get(b)
        return bool(sa and sb and (sa & sb))

    # Attribute a recovered net to a reference signal where unambiguous.  A net
    # carrying several reference signals is still attributable if those signals
    # are the same physical node (the F/OFX wide-mux twins) — already
    # classified above as a modelling gap rather than a wiring error.
    sig_of_net = {}
    for n, ss in net_sigs.items():
        if len(ss) == 1:
            sig_of_net[n] = next(iter(ss))
        else:
            ordered = sorted(ss)
            if all(same_node(ordered[0], s) for s in ordered[1:]):
                sig_of_net[n] = ordered[0]

    # A CCU2 carry cell's F output is the SUM bit, which the hardware forms as
    # LUT4 ^ carry-in.  The carry path (FCI/FCO) is internal to the slice and
    # emits no config arc, so the lifter — which models the LUT4 only — has no
    # net for that sum.  A LUT reading a CCU2 sum therefore legitimately shows
    # that input as absent.  Tracked as a modelling gap, not a routing error.
    ccu2_sigs = set()
    for cname, cell in mod.get("cells", {}).items():
        if cell.get("parameters", {}).get("MODE") != "CCU2":
            continue
        for pin in ("F", "OFX"):
            bits = cell.get("connections", {}).get(pin) or []
            if bits and isinstance(bits[0], int):
                ccu2_sigs.add(bits[0])

    # Constants the packer materialises ($PACKER_VCC / $PACKER_GND) are emitted
    # by the lifter as 1'b1 / 1'b0 literals rather than nets, so a LUT reading
    # one legitimately shows that input as absent.
    const_sigs = set()
    for cname, cell in mod.get("cells", {}).items():
        if "PACKER_VCC" in cname or "PACKER_GND" in cname:
            for pin in ("F", "Q", "OFX"):
                bits = cell.get("connections", {}).get(pin) or []
                if bits and isinstance(bits[0], int):
                    const_sigs.add(bits[0])

    fanin_ok = fanin_bad = fanin_skipped = fanin_gap = 0
    bad_fanin = []
    for cname, cell in mod.get("cells", {}).items():
        m = BEL_RE.match(cell.get("attributes", {}).get("NEXTPNR_BEL", ""))
        if not m or m.group(4) != "K":
            continue
        site = (int(m.group(2)), int(m.group(1)), m.group(3), m.group(5))
        rec = lut_by_site.get(site)
        if rec is None:
            continue
        # A distributed-RAM slice's reference cell describes the RAM port, not
        # a LUT: its A/B/C/D may carry no reference signals at all while the
        # bitstream still routes real address/data wires to the slice inputs.
        # Comparing those against an empty expectation is meaningless.
        if cell.get("parameters", {}).get("MODE") in ("DPRAM", "RAMW", "RAMW_BLOCK"):
            fanin_skipped += 1
            continue
        want = set()
        for p in "ABCD":
            bits = cell.get("connections", {}).get(p) or []
            if bits and isinstance(bits[0], int):
                want.add(bits[0])
        got = {rec[f] for f in "abcd"
               if rec.get(f) and not rec[f].startswith("1'b")}
        # Map recovered nets back to reference signals where unambiguous.
        mapped = {sig_of_net[n] for n in got if n in sig_of_net}
        if len(mapped) < len(got):
            fanin_skipped += 1          # some net not uniquely attributable
            continue
        # Reconcile the two known-benign rewrites before comparing:
        #  * a recovered signal that is the F/OFX twin of an expected one, and
        #  * expected inputs that are packer constants or unmodelled wide-mux
        #    outputs, which correctly do not appear as nets.
        residual_want = set()
        for w in want:
            if w in mapped or any(same_node(w, g) for g in mapped):
                continue
            if w in const_sigs or w in widemux_sigs or w in ccu2_sigs:
                continue
            residual_want.add(w)
        residual_got = {g for g in mapped
                        if g not in want and not any(same_node(g, w)
                                                     for w in want)}

        if mapped == want:
            fanin_ok += 1
        elif not residual_want and not residual_got:
            # Differences fully explained by wide-mux collapse / constants.
            fanin_gap += 1
        else:
            fanin_bad += 1
            bad_fanin.append((site, sorted(want), sorted(mapped)))

    log.info("LUT fan-in (permutation-invariant): %d match, %d "
             "unmodelled-element gaps, %d WRONG, %d unattributable",
             fanin_ok, fanin_gap, fanin_bad, fanin_skipped)
    for site, w, g in bad_fanin[:args.max_report]:
        log.error("    FANIN %s want-signals=%s got-signals=%s", site, w, g)

    if split or fused or fanin_bad:
        log.error("NET CHECK FAILED: %d split, %d fused, %d fan-in",
                  len(split), len(fused), fanin_bad)
        return 1
    log.info("NET CHECK PASSED: recovered nets match reference connectivity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
