#!/usr/bin/env python3.15t
"""Native Cyclone V decode vs Quartus post-fit netlist: LUTs, registers, pins/IO, DSP/M10K (claim 1, non-routing fields).

Per field: matched / missing / extra / wrong. Headline = matched / (matched + missing + extra + wrong).
Quartus side: postfit_atoms / postfit_conns (corpus.db, read-only). Native side: Model.settings() / Model.routes().
Mapping rules used here (ALM address function, T/B halves, FF slot numbering) are the ones proven in
docs/cyclonev-postfit-oracle.md; their re-derivation from split A only is scripts/cyclonev_native_verify.py lutmap.
"""
import collections
import json

from cyclonev_decode import fmt_ram

PINS = "abcdef"
HALF = ("T", "B")
DEFAULT_MODE = {"T": "D_E", "B": "C_E"}
FF_SLOT = {1: "0", 2: "1"}
MLAB_PERM = [0, 1, 4, 5, 8, 9, 12, 13, 29, 28, 25, 24, 21, 20, 17, 16,
             2, 3, 6, 7, 10, 11, 14, 15, 31, 30, 27, 26, 23, 22, 19, 18,
             32, 33, 36, 37, 40, 41, 44, 45, 61, 60, 57, 56, 53, 52, 49, 48,
             34, 35, 38, 39, 42, 43, 46, 47, 63, 62, 59, 58, 55, 54, 51, 50]


def lut_raw_pos(v, half, mode, used, perm=None):
    """Raw LUT_MASK bit index for Quartus input vector v, None if unreachable, 'unmodelled' for F_x modes."""
    if any((v >> k) & 1 for k, p in enumerate(PINS) if p not in used):
        return None
    bit = {p: (v >> k) & 1 for k, p in enumerate(PINS)}
    if half == "B":
        bit["c"], bit["d"] = bit["d"], bit["c"]
    if mode in ("E_0", "E_1", "F_0", "F_1"):
        x5 = int(mode[-1])
    elif mode in ("D_E", "D_F", "C_E", "C_F"):
        x5 = bit["e"]
    else:
        return "unmodelled"
    j2, j3 = (bit["c"], bit["d"]) if x5 == 0 else (bit["d"], bit["c"])
    return bit["a"] | bit["b"] << 1 | j2 << 2 | j3 << 3 | bit["f"] << 4 | x5 << 5


def lut_matches(q_mask, raw, half, mode, used, mlab):
    for v in range(64):
        j = lut_raw_pos(v, half, mode, used)
        if j is None:
            continue
        if j == "unmodelled":
            return None
        if mlab:
            j = MLAB_PERM[j]
        if ((q_mask >> v) & 1) == ((raw >> j) & 1):      # raw bits are the inverted function
            return False
    return True


def load_build(conn, bid):
    atoms = {}
    for aid, name, typ, loc, lk, x, y, n, params in conn.execute(
            "select id, name, type, location, loc_kind, x, y, n, params from postfit_atoms where build=?", (bid,)):
        atoms[aid] = dict(id=aid, name=name, type=typ, location=loc, loc_kind=lk, x=x, y=y, n=n,
                          params=json.loads(params))
    by_atom = collections.defaultdict(list)
    for aid, port, net, inv, const, direction in conn.execute(
            "select atom, port, net, inverted, const, direction from postfit_conns where build=?", (bid,)):
        by_atom[aid].append(dict(port=port, net=net, inverted=bool(inv), const=const, direction=direction))
    return atoms, by_atom


def settings_index(settings):
    S = collections.defaultdict(dict)
    for st in settings:
        S[(st[0], st[1][0], st[1][1])][(st[2], st[3])] = st[5] if st[4] != "r" else fmt_ram(st[6], st[5])
    return S


class Tally:
    def __init__(self):
        self.c = collections.defaultdict(collections.Counter)
        self.detail = collections.defaultdict(list)

    def add(self, field, verdict, info=None):
        self.c[field][verdict] += 1
        if verdict not in ("matched", "excluded") and info is not None and len(self.detail[field]) < 12:
            self.detail[field].append((verdict, info))


def score_logic(m, tb, atoms, by_atom, links, tally):
    S = settings_index(m.settings())
    tt = tb["tile_types"]
    tn = tb["routes"]["type_names"]
    seen_alm, arith_q = set(), set()
    for a in atoms.values():
        if a["type"] != "cyclonev_lcell_comb":
            continue
        blk = "MLAB" if a["loc_kind"] == "MLABCELL" else "LAB"
        x, y, alm, half = a["x"], a["y"], a["n"] // 6, HALF[(a["n"] // 3) % 2]
        seen_alm.add((blk, x, y, alm))
        conns = by_atom[a["id"]]
        if any(c["port"] in ("sumout", "cout", "cin") and c["net"] for c in conns):
            arith_q.add((blk, x, y, alm))
        if a["name"].startswith("~QUARTUS_CREATED_GND"):
            tally.add("lut_mask", "excluded")
            continue
        used = {c["port"][4] for c in conns if c["port"].startswith("data") and c["port"] != "datag" and c["net"]}
        q_mask = int(a["params"]["lut_mask"].split("'h")[1], 16)
        st = S.get((blk, x, y), {})
        raw_s = st.get(("LUT_MASK", alm))
        arith = st.get(("ARITH_SEL", alm)) == "ADDER"
        mode = st.get(("%sMODE" % half, alm)) or DEFAULT_MODE[half]
        field = "lut_mask_arith" if arith else "lut_mask"
        raw = 0 if raw_s is None else int(raw_s.replace(".", ""), 16)
        ok = lut_matches(q_mask, raw, half, mode, used, blk == "MLAB")
        if ok is None:
            tally.add(field, "missing", (a["name"], "unmodelled mode " + mode))
        elif ok:
            tally.add(field, "matched")
        else:
            tally.add(field, "missing" if raw_s is None else "wrong", (a["name"], raw_s, "%016x" % q_mask, mode))
    for (blk, x, y), kv in S.items():
        if blk in ("LAB", "MLAB"):
            for (mux, idx), val in kv.items():
                if mux == "LUT_MASK" and (blk, x, y, idx) not in seen_alm:
                    tally.add("lut_mask", "extra", (blk, x, y, idx, val))
    native_arith = {(blk, x, y, idx) for (blk, x, y), kv in S.items() if blk in ("LAB", "MLAB")
                    for (mux, idx), val in kv.items() if mux == "ARITH_SEL" and val == "ADDER"}
    for k in arith_q | native_arith:
        both = k in arith_q and k in native_arith
        tally.add("arith_sel", "matched" if both else "missing" if k in arith_q else "extra", k)

    # registers: present = a DFF select of REG and a used output (GIN/LD source) of that slot
    used_src = collections.defaultdict(set)
    for s, _d in links:
        used_src[((s >> 17) & 0x7F, (s >> 10) & 0x7F)].add((tn[s >> 24], s & 0x3FF))
    native_ff = {}
    for (x, y), srcs in used_src.items():
        tp = tt.get((x, y))
        if tp not in ("T_LAB", "T_MLAB"):
            continue
        blk = "LAB" if tp == "T_LAB" else "MLAB"
        st = S.get((blk, x, y), {})
        for t, z in srcs:
            if t == "GIN":
                alm, k = z // 4, z % 4
                half, slot, nm = (("T", "0", "TDFF0"), ("T", "1", "TDFF1"), ("B", "0", "BDFF0"), ("B", "1", "BDFF1"))[k]
            elif t == "LD":
                alm, k = z // 2, z % 2
                half, slot, nm = (("T", "1", "TDFF1L"), ("B", "1", "BDFF1L"))[k]
            else:
                continue
            if st.get((nm, alm), "REG") == "REG":
                native_ff[(blk, x, y, alm, half, slot)] = st
    q_ff = {}
    for a in atoms.values():
        if a["type"] == "dffeas":
            x, y, alm = a["x"], a["y"], a["n"] // 6
            half, slot = HALF[(a["n"] // 3) % 2], FF_SLOT[a["n"] % 3]
            blk = "MLAB" if tt.get((x, y)) == "T_MLAB" else "LAB"
            q_ff[(blk, x, y, alm, half, slot)] = a
    for hyp, slots_ in (("own-s1", ("1",)), ("own-s0", ("0",))):
        fb = dict(native_ff)
        for (blk, x, y), kv in S.items():
            if blk not in ("LAB", "MLAB"):
                continue
            for (nm_, alm), v in kv.items():
                if nm_ in ("T_FEEDBACK_SEL", "B_FEEDBACK_SEL") and int(v) == 1:
                    h = nm_[0]
                    for slot_ in slots_:
                        fb.setdefault((blk, x, y, alm, h, slot_), kv)
        for k in set(q_ff) | set(fb):
            tally.add("ff.present+feedback[%s]" % hyp, "matched" if k in q_ff and k in fb else
                      "missing" if k in q_ff else "extra", k)
    for k in set(q_ff) | set(native_ff):
        if k in q_ff and k in native_ff:
            tally.add("ff.present", "matched")
        elif k in q_ff:
            tally.add("ff.present", "missing", (k, q_ff[k]["name"]))
        else:
            tally.add("ff.present", "extra", k)
    for k, a in q_ff.items():
        if k not in native_ff:
            continue
        blk, x, y, alm, half, slot = k
        st = native_ff[k]
        conns = {c["port"]: c for c in by_atom[a["id"]]}
        oth = "B" if half == "T" else "T"
        for hname, hh in (("same", half), ("other", oth), ("slot-rule", half if slot == "0" else oth)):
            sl = "[slot%s]" % slot
            csel = st.get(("%sCLK_SEL" % hh, alm), "OFF")
            tally.add("ff.clk_sel[%s-half]" % hname, "missing" if csel == "OFF" else "matched", (k, a["name"]))
            if csel != "OFF":
                kk = csel[-1]
                q_inv = bool(conns.get("clk", {}).get("inverted"))
                lab = S.get((blk, x, y), {})
                inv_named = int(lab.get(("CLK%s_INV" % kk, -1), 0)) == 1
                inv_other = lab.get(("CLK%s_SEL" % kk, -1)) == "CLKB"
                for nm_, pred in (("as_named", inv_named), ("swapped", inv_other)):
                    tally.add("ff.clk_inv[%s-half,clk%s,%s]" % (hname, kk, nm_), "matched" if pred == q_inv else "wrong",
                              (k, a["name"], q_inv, pred))

            def used(port):
                c = conns.get(port)
                return bool(c and c["net"] and c["const"] is None)
            sclr_dis = int(st.get(("%sSCLR_DIS" % hh, alm), 0)) == 1
            tally.add("ff.sclr_used[%s-half]%s" % (hname, sl), "matched" if used("sclr") == (not sclr_dis) else "wrong",
                      (k, a["name"], used("sclr")))
            sload = int(st.get(("%sSLOAD_EN" % hh, alm), 0)) == 1
            tally.add("ff.sload_used[%s-half]%s" % (hname, sl), "matched" if used("sload") == sload else "wrong",
                      (k, a["name"], used("sload")))

    # pins / IO config
    pin_atoms = {a["location"][4:]: a for a in atoms.values() if a["type"] == "pin"}
    native_pin = {}
    for s, d in links:
        for key, role in ((s, "in"), (d, "out")):
            p = m.rnode_to_pnode(key)
            pin = m.pin_pnode(p) if p else None
            if pin:
                native_pin.setdefault(pin, set()).add(role)
    dmap = {"input": "in", "output": "out", "inout": "bidir"}
    for label, a in pin_atoms.items():
        qd = dmap[a["params"]["direction"]]
        roles = native_pin.get(label)
        nd = None if not roles else ("bidir" if len(roles) == 2 else next(iter(roles)))
        if nd is None:
            tally.add("pin.used_dir", "missing", (label, qd))
        else:
            tally.add("pin.used_dir", "matched" if nd == qd else "wrong", (label, qd, nd))
    for label in set(native_pin) - set(pin_atoms):
        tally.add("pin.used_dir", "extra", label)
    pos_of = {v: k for k, v in m.pins.items()}
    net_label = {}
    for label, pa in pin_atoms.items():
        for c in by_atom[pa["id"]]:
            if c["net"]:
                net_label[c["net"]] = label
    for a in atoms.values():
        if a["type"] not in ("cyclonev_io_obuf", "cyclonev_io_ibuf"):
            continue
        cs = {c["port"]: c for c in by_atom[a["id"]]}
        port = "o" if a["type"] == "cyclonev_io_obuf" else "i"
        label = net_label.get((cs.get(port) or {}).get("net"))
        if label is None or label not in pos_of:
            continue
        x, y, idx = pos_of[label]
        st = S.get(("GPIO", x, y), {})
        for qparam, nm_ in (("bus_hold", "USE_BUS_HOLD"), ("open_drain_output", "USE_OPEN_DRAIN")):
            if qparam in a["params"]:
                q = a["params"][qparam] == "true"
                n = int(st.get((nm_, idx), 0)) == 1
                tally.add("io." + qparam, "matched" if q == n else "wrong", (label, q, n))

    # DSP / M10K
    active = collections.defaultdict(set)
    for (blk, x, y), kv in S.items():
        if blk in ("DSP", "M10K"):
            active[blk].add((x, y))
    q_dsp = {(a["x"], a["y"]): a for a in atoms.values() if a["type"] == "cyclonev_mac"}
    for pos in set(q_dsp) | active["DSP"]:
        both = pos in q_dsp and pos in active["DSP"]
        tally.add("dsp.present", "matched" if both else "missing" if pos in q_dsp else "extra", pos)
    modemap = {"m9x9": "M9X9", "m27x27": "M27X27", "m18x18_full": None}
    for pos, a in q_dsp.items():
        om = a["params"].get("operation_mode")
        if om not in modemap:
            continue
        want = modemap[om]
        got = S.get(("DSP", pos[0], pos[1]), {}).get(("MODE", -1))
        tally.add("dsp.mode", "matched" if got == want or (want is None and got in (None, "M18X19")) else "wrong",
                  (pos, om, got))
    q_pos = {(a["x"], a["y"]) for a in atoms.values() if a["type"] == "cyclonev_ram_block"}
    for pos in q_pos | active["M10K"]:
        both = pos in q_pos and pos in active["M10K"]
        tally.add("m10k.present", "matched" if both else "missing" if pos in q_pos else "extra", pos)


def headline(c):
    t = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
    return c["matched"] / t if t else float("nan")
