#!/usr/bin/env python3
"""Compare a Quartus post-fit netlist (postfit_* tables) with our lift of the same bitstream.

Per placed atom, at the same physical location (docs/cyclonev-postfit-oracle.md):
  lut_mask / lut_mask_arith  Quartus lut_mask vs Mistral LUT_MASK under the proven ALM mapping
  ff.present, ff.<port>      register exists; driver of d/clk/clrn/ena/sclr/sload
  conn.<port>                LUT data input / obuf input: driving atom, Quartus vs lifted nets
  pin                        package pin + direction vs lifter pad_map
Verdicts: MATCH | MISMATCH | LIFT_MISSING | QUARTUS_ONLY | LIFT_ONLY | UNMODELLED
(UNMODELLED = ALM mode the LUT mapping does not cover yet, e.g. BMODE F_1).

Usage: python3.15t scripts/cyclonev_postfit_compare.py <design> [...]   # re-run on built designs
Called by scripts/cyclonev_corpus_build.py as compare_build(build_id, design_dir).
"""
import collections
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "corpus" / "cyclonev" / "corpus.db"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import db  # noqa: E402
from lifters.cyclonev_lift import CVNode, CycloneVLift  # noqa: E402

PINS = "abcdef"
# MLAB LUT bits are stored permuted (nextpnr mistral/lab.cc permute_mlab_init; confirmed
# by the corpus: MLAB halves only match with it applied).
MLAB_PERM = [0, 1, 4, 5, 8, 9, 12, 13, 29, 28, 25, 24, 21, 20, 17, 16,
             2, 3, 6, 7, 10, 11, 14, 15, 31, 30, 27, 26, 23, 22, 19, 18,
             32, 33, 36, 37, 40, 41, 44, 45, 61, 60, 57, 56, 53, 52, 49, 48,
             34, 35, 38, 39, 42, 43, 46, 47, 63, 62, 59, 58, 55, 54, 51, 50]
HALF = ("T", "B")              # Quartus lcell (N//3)%2 -> Mistral half (TMODE / BMODE)
DEFAULT_MODE = {"T": "D_E", "B": "C_E"}
FF_SLOT = {1: "0", 2: "1"}     # Quartus FF N%3 -> Mistral FF{T,B}<0|1|1L>
FF_PORTS = ("d", "clk", "clrn", "ena", "sclr", "sload")


def lab_pin(half, mode, port):
    """Mistral LAB input pin carrying lcell input data<port> (corpus-derived, see doc).
    T: c->C d->D; B: c->D d->C; in E_x/F_x modes d comes from that half's E/F pin."""
    h = "0" if half == "T" else "1"
    if port in "ab":
        return port.upper()
    if port == "c":
        return "C" if half == "T" else "D"
    if port == "d":
        if mode[0] in "EF":
            return mode[0] + h
        return "D" if half == "T" else "C"
    return port.upper() + h


def lut_raw_pos(v, half, mode, used):
    """Raw LUT_MASK bit for Quartus input vector v (bit k = data<PINS[k]>), or None if v
    is unreachable (an unused/gnd input set to 1)."""
    if any((v >> k) & 1 for k, p in enumerate(PINS) if p not in used):
        return None
    bit = {p: (v >> k) & 1 for k, p in enumerate(PINS)}
    if half == "B":                       # bottom half sees datac/datad swapped
        bit["c"], bit["d"] = bit["d"], bit["c"]
    if mode in ("E_0", "E_1"):
        x5 = int(mode[-1])
    elif mode in ("D_E", "D_F", "C_E", "C_F"):
        x5 = bit["e"]
    else:
        return "unmodelled"
    j2, j3 = (bit["c"], bit["d"]) if x5 == 0 else (bit["d"], bit["c"])
    return bit["a"] | bit["b"] << 1 | j2 << 2 | j3 << 3 | bit["f"] << 4 | x5 << 5


def lut_matches(q_mask, raw, half, mode, used, mlab):
    """True/False, or None when the mode is not modelled.  Raw bits are inverted."""
    for v in range(64):
        j = lut_raw_pos(v, half, mode, used)
        if j is None:
            continue
        if j == "unmodelled":
            return None
        if mlab:
            j = MLAB_PERM[j]
        if ((q_mask >> v) & 1) == ((raw >> j) & 1):
            return False
    return True


def load_quartus(bid):
    import schema
    from sqlalchemy import select
    ta, tc = schema.postfit_atoms, schema.postfit_conns
    with db.engine().connect() as conn:
        atoms = {r.id: dict(r._mapping) for r in conn.execute(select(ta).where(ta.c.build == bid))}
        conns = [dict(r._mapping) for r in conn.execute(select(tc).where(tc.c.build == bid))]
    by_atom = collections.defaultdict(list)
    driver = {}
    for c in conns:
        by_atom[c["atom"]].append(c)
        if c["direction"] == "out" and c["net"]:
            driver[c["net"]] = atoms[c["atom"]]["name"]
    return atoms, by_atom, driver


def compare_build(bid, ddir):
    import schema
    from sqlalchemy import delete, insert
    atoms, by_atom, q_driver = load_quartus(bid)
    lift = CycloneVLift("5CEBA4U19C8")
    pc = lift.parse_config(str(Path(ddir) / "decomp.bt"))
    d = lift.recover_netlist(pc)
    dsu = d.dsu
    rows = []

    def row(atom, loc, field, qv, lv, verdict):
        rows.append(dict(build=bid, atom=atom, location=loc, field=field,
                         quartus_value=None if qv is None else str(qv),
                         lifted_value=None if lv is None else str(lv), verdict=verdict))

    def setting(blk, x, y, mux, idx):
        return pc.settings.get((blk, x, y), {}).get((mux, idx))

    # ── bridge: Quartus atom name by physical place ──────────────────────
    by_place = {}
    label_to_ibuf, label_to_pin = {}, {}
    pin_net_to_label = {}
    for a in atoms.values():
        if a["type"] == "pin":
            label = a["location"][len("PIN_"):]
            label_to_pin[label] = a
            for c in by_atom[a["id"]]:
                pin_net_to_label[c["net"]] = label
    for a in atoms.values():
        if a["loc_kind"] in ("LABCELL", "MLABCELL"):
            by_place[("lut", a["x"], a["y"], a["n"] // 6, HALF[(a["n"] // 3) % 2])] = a["name"]
        elif a["loc_kind"] == "FF":
            by_place[("ff", a["x"], a["y"], a["n"] // 6, HALF[(a["n"] // 3) % 2],
                      FF_SLOT[a["n"] % 3])] = a["name"]
        elif a["type"] == "cyclonev_io_ibuf":
            for c in by_atom[a["id"]]:
                if c["port"] == "i" and c["net"] in pin_net_to_label:
                    label_to_ibuf[pin_net_to_label[c["net"]]] = a["name"]
        elif a["loc_kind"] in ("DSP", "M10K"):
            by_place[(a["loc_kind"], a["x"], a["y"])] = a["name"]

    # Pins reached through the HMC I/O path: the lifter counts but drops these pin
    # comments (n_pin_comments_non_gpio), so read them from the .bt here.
    hmc_pin = {}
    for ln in open(Path(ddir) / "decomp.bt"):
        if ln.startswith("r HMC.") and " ; " in ln:
            hmc_pin[ln.split()[1]] = ln.rsplit(" ; ", 1)[1].strip()
    dsts = {dst for _s, dst in pc.arcs}
    roots_src = collections.defaultdict(set)   # DSU root -> primary source nodes
    for s, _dst in pc.arcs:
        if s not in dsts:
            roots_src[dsu.find(s)].add(s)

    def bridge(node):
        """Quartus atom name for a Mistral primary-source node, or 'unbridged:<node>'."""
        if node.block in ("LAB", "MLAB") and node.port and node.port.startswith("FF"):
            half, rest = node.port[2], node.port[3:]       # FFT1L -> "T", "1L"
            sel = setting(node.block, node.x, node.y, f"{half}DFF{rest}", node.bi)
            if sel == "NLUT":
                key = ("lut", node.x, node.y, node.bi, half)
            else:
                key = ("ff", node.x, node.y, node.bi, half, rest[0])
            return by_place.get(key, f"unbridged:{node.to_string()}")
        if node.block == "GPIO" and node.port == "DATAIN":
            label = pc.pin_annotations.get(("GPIO", node.x, node.y, node.bi))
            if label in label_to_ibuf:
                return label_to_ibuf[label]
        if node.block == "HMC" and hmc_pin.get(node.to_string()) in label_to_ibuf:
            return label_to_ibuf[hmc_pin[node.to_string()]]
        if node.block in ("DSP", "M10K"):
            name = by_place.get((node.block, node.x, node.y))
            if name:
                return name
        return f"unbridged:{node.to_string()}"

    def lifted_driver(node):
        if node not in dsu.p:
            return None
        srcs = roots_src.get(dsu.find(node), set())
        if not srcs:
            return "no-source"
        return "|".join(sorted({bridge(s) for s in srcs}))

    def q_drv(c):
        if c["const"] is not None:
            return f"const:{c['const']}"
        return q_driver.get(c["net"], f"undriven:{c['net']}")

    def conn_verdict(qv, lv):
        if lv is None:
            return "LIFT_MISSING"
        return "MATCH" if qv == lv else "MISMATCH"

    # ── LUTs ──────────────────────────────────────────────────────────────
    seen_alm_halves = set()
    for a in atoms.values():
        if a["type"] != "cyclonev_lcell_comb":
            continue
        blk = "MLAB" if a["loc_kind"] == "MLABCELL" else "LAB"
        x, y, alm, half = a["x"], a["y"], a["n"] // 6, HALF[(a["n"] // 3) % 2]
        seen_alm_halves.add((blk, x, y, alm))
        used = {c["port"][4] for c in by_atom[a["id"]]
                if c["port"].startswith("data") and c["port"] != "datag" and c["net"]}
        q_mask = int(a["params"]["lut_mask"].split("'h")[1], 16)
        raw_s = setting(blk, x, y, "LUT_MASK", alm)
        arith = setting(blk, x, y, "ARITH_SEL", alm) == "ADDER"
        field = "lut_mask_arith" if arith else "lut_mask"
        mode = setting(blk, x, y, f"{half}MODE", alm) or DEFAULT_MODE[half]
        qv = f"{q_mask:016x} used={''.join(sorted(used))} half={half} mode={mode}"
        if raw_s is None:
            row(a["name"], a["location"], field, qv, None, "LIFT_MISSING")
        else:
            hi, lo = raw_s.split(".")
            raw = int(hi, 16) << 32 | int(lo, 16)
            ok = lut_matches(q_mask, raw, half, mode, used, blk == "MLAB")
            row(a["name"], a["location"], field, qv, raw_s,
                "UNMODELLED" if ok is None else "MATCH" if ok else "MISMATCH")
        # data-input connectivity
        fb = setting(blk, x, y, f"{half}_FEEDBACK_SEL", alm)
        for c in by_atom[a["id"]]:
            if not c["port"].startswith("data") or c["port"] == "datag" or c["net"] is None:
                continue
            pin = lab_pin(half, mode, c["port"][4])
            node = CVNode(blk, x, y, alm, pin, None)
            qv = q_drv(c)
            lv = lifted_driver(node)
            if lv is not None and fb is not None and qv != lv:
                lv += f" ({half}_FEEDBACK_SEL={fb})"
            pre = "conn_arith" if arith else "conn"
            row(a["name"], a["location"], f"{pre}.{c['port']}", qv, lv, conn_verdict(qv, lv))
    for (blk, x, y), kv in pc.settings.items():
        if blk not in ("LAB", "MLAB"):
            continue
        for (mux, idx), val in kv.items():
            if mux == "LUT_MASK" and (blk, x, y, idx) not in seen_alm_halves:
                row(None, f"{blk}.{x:03d}.{y:03d}.{idx}", "lut_mask", None, val, "LIFT_ONLY")

    # ── registers ─────────────────────────────────────────────────────────
    lifted_ffs = {f["name"] for f in d.ffs}
    for a in atoms.values():
        if a["type"] != "dffeas":
            continue
        x, y, alm = a["x"], a["y"], a["n"] // 6
        half, slot = HALF[(a["n"] // 3) % 2], FF_SLOT[a["n"] % 3]
        blk = "MLAB" if ("MLAB", x, y) in pc.settings else "LAB"
        ports = [f"FF{half}{slot}"] + ([f"FF{half}1L"] if slot == "1" else [])
        names = {f"ff_{blk.lower()}_r{x}c{y}_a{alm}_{p.lower()}" for p in ports}
        hit = sorted(names & lifted_ffs)
        row(a["name"], a["location"], "ff.present", "/".join(ports),
            hit[0] if hit else None, "MATCH" if hit else "LIFT_MISSING")
        conns = {c["port"]: c for c in by_atom[a["id"]]}
        for p in FF_PORTS:
            qv = q_drv(conns[p]) if p in conns else None
            # The lifter leaves Cyclone V FF d/clk/ce/lsr unresolved (None), and has no
            # sclr/sload field at all.
            row(a["name"], a["location"], f"ff.{p}", qv, None, "LIFT_MISSING")

    # ── I/O ───────────────────────────────────────────────────────────────
    pads = {p["label"]: p for p in d.pads}
    dir_map = {"input": "in", "output": "out", "inout": "bidir"}
    for label, a in label_to_pin.items():
        qv = f"{label}:{dir_map[a['params']['direction']]}"
        p = pads.get(label)
        if p is None:
            row(a["name"], a["location"], "pin", qv, None, "LIFT_MISSING")
        else:
            lv = f"{label}:{p['direction']}"
            row(a["name"], a["location"], "pin", qv, lv, "MATCH" if qv == lv else "MISMATCH")
    for label, p in pads.items():
        if label not in label_to_pin:
            row(None, label, "pin", None, f"{label}:{p['direction']}", "LIFT_ONLY")
    for a in atoms.values():
        if a["type"] != "cyclonev_io_obuf":
            continue
        cs = {c["port"]: c for c in by_atom[a["id"]]}
        label = pin_net_to_label.get(cs["o"]["net"]) if "o" in cs else None
        qv = q_drv(cs["i"])
        p = pads.get(label)
        lv = None
        if p is not None and p["net_out"] is not None:
            nodes = [n for n in dsu.p if n.block == "GPIO" and n.port == "DATAOUT"
                     and pc.pin_annotations.get(("GPIO", n.x, n.y, n.bi)) == label]
            lv = lifted_driver(nodes[0]) if nodes else None
        row(a["name"], a["location"], "conn.obuf.i", qv, lv, conn_verdict(qv, lv))

    # ── hard blocks with no lifted model ─────────────────────────────────
    for a in atoms.values():
        if a["type"] in ("cyclonev_mac", "cyclonev_ram_block", "cyclonev_clkena"):
            row(a["name"], a["location"], f"block.{a['type']}", a["type"], None, "QUARTUS_ONLY")

    t = schema.postfit_compare
    with db.engine().begin() as conn:
        conn.execute(delete(t).where(t.c.build == bid))
        if rows:
            conn.execute(insert(t), rows)
    summary = collections.defaultdict(collections.Counter)
    for r in rows:
        summary[r["field"]][r["verdict"]] += 1
    return {f: dict(c) for f, c in sorted(summary.items())}


def main():
    import schema
    from sqlalchemy import select
    schema.init()
    t = schema.postfit_builds
    with db.engine().connect() as conn:
        builds = {r.design: r for r in conn.execute(select(t))}
    for name in sys.argv[1:] or sorted(builds):
        b = builds[name]
        s = compare_build(b.id, REPO / b.out_dir)
        print(name)
        for f, c in s.items():
            print(f"  {f:22s} " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))


if __name__ == "__main__":
    main()
