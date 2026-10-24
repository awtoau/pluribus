#!/usr/bin/env python3
"""Compare pluribus' MachXO2 decode + lift against the Diamond oracle (#105).

Per target with an oracle.json (scripts/machxo2_diamond_oracle.py): native-decode
impl1/fuzz_impl1.bit, lift with lifters/machxo2_lift.py, compare:
  * sites: LUT INIT, slice enums (bits.db-default aware), lifted FF fields/nets
  * pips:  every Diamond route arc vs decoded config arcs / routing-graph arcs
  * nets:  every Diamond net vs the lift's DSU classes (split / merge)
  * gkey:  each config-arc endpoint a gkey() workaround rewrote, vs Diamond
Verdicts: MATCH / MISMATCH / LIFT_MISSING / ORACLE_ONLY (+ LIFT_ONLY for
config arcs no Diamond net uses).  Definitions: docs/machxo2-diamond-oracle.md.

Writes <out>/<target>/compare.json and <out>/_compare_summary.json.
Usage: python3.15t scripts/machxo2_oracle_compare.py [--workers N] [--only T ...]
Log:   tmp/logs/machxo2_oracle_compare.log
"""
import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(SCRIPTS))
import toolchain  # noqa: E402
import diamond_oracle_parse as P  # noqa: E402
from machxo2_diamond_oracle import REPO, _Log  # noqa: E402
import heavy_guard  # noqa: E402

os.environ.setdefault("TRELLIS_DBROOT", toolchain.trellis_dbroot())
from lifters import machxo2_lift as ML  # noqa: E402
import native_config  # noqa: E402

LOG_PATH = os.path.join(REPO, "tmp", "logs", "machxo2_oracle_compare.log")
DEVICE = "LCMXO2-1200"
# Diamond site/wire column -> prjtrellis routing-graph column (devices.json
# col_bias; verified per target: every Diamond slice site must hold a decoded slice).
COL_BIAS = 1
_log_lock = threading.Lock()


def log(msg):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with _log_lock:
        print(f"{now}  {msg}", flush=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(f"{now}  {msg}\n")


# ----------------------------------------------------------- bits.db enums ---
def load_plc_enums(dbroot):
    """PLC .config_enum -> {name: (default, {option: frozenset(bits)})}."""
    path = os.path.join(dbroot, "MachXO2", "tiledata", "PLC", "bits.db")
    out, cur = {}, None
    with open(path) as fh:
        for ln in fh:
            t = ln.split()
            if not t:
                cur = None
                continue
            if t[0] == ".config_enum":
                cur = t[1]
                out[cur] = (t[2], {})
            elif t[0].startswith("."):
                cur = None
            elif cur:
                out[cur][1][t[0]] = frozenset(b for b in t[1:] if b != "-")
    return out


_MUX_CACHE = {}
_MUX_LOCK = threading.Lock()


def load_mux_bits(dbroot, ttype):
    """tiletype bits.db -> ({sink: [(source, bits)]}, [(sink, source)])."""
    with _MUX_LOCK:
        if ttype in _MUX_CACHE:
            return _MUX_CACHE[ttype]
    muxes, fixed, cur = {}, [], None
    with open(os.path.join(dbroot, "MachXO2", "tiledata", ttype, "bits.db")) as fh:
        for ln in fh:
            t = ln.split()
            if not t or t[0].startswith("#"):
                cur = None
            elif t[0] == ".mux":
                cur = t[1]
                muxes.setdefault(cur, [])
            elif t[0] == ".fixed_conn":
                fixed.append((t[1], t[2]))
                cur = None
            elif t[0].startswith("."):
                cur = None
            elif cur is not None:
                muxes[cur].append((t[0], tuple(b for b in t[1:] if b != "-")))
    with _MUX_LOCK:
        _MUX_CACHE[ttype] = (muxes, fixed)
    return muxes, fixed


# -------------------------------------------------------- LUT expressions ---
_TOK = re.compile(r"\s*([ABCD01]|[~*+@^()])")


def lut_eval(expr):
    """Diamond LUT equation ('(B@(A@~D))') -> 16-bit truth table int, bit A+2B+4C+8D.

    Precedence (low->high): + (or), @/^ (xor), * (and), ~ (not)."""
    toks = _TOK.findall(expr)
    if "".join(toks) != expr.replace(" ", ""):
        raise ValueError(f"unparsed LUT equation {expr!r}")
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def atom():
        t = take()
        if t == "~":
            return 0xFFFF ^ atom()
        if t == "(":
            v = orx()
            if take() != ")":
                raise ValueError(expr)
            return v
        if t in "01":
            return 0xFFFF if t == "1" else 0
        v = 0
        idx = "ABCD".index(t)
        for i in range(16):
            if (i >> idx) & 1:
                v |= 1 << i
        return v

    def andx():
        v = atom()
        while peek() == "*":
            take()
            v &= atom()
        return v

    def xorx():
        v = andx()
        while peek() in ("@", "^"):
            take()
            v ^= andx()
        return v

    def orx():
        v = xorx()
        while peek() == "+":
            take()
            v |= xorx()
        return v

    v = orx()
    if pos[0] != len(toks):
        raise ValueError(f"trailing tokens in {expr!r}")
    return v


LUT_INIT_DEFAULT = 0xFFFF   # PLC bits.db `.config SLICEA.K0.INIT 1111111111111111`


def init_int(s):
    """Decoded 'word: SLICEx.Kk.INIT' bit string (MSB first) -> int."""
    return int(s, 2)


# -------------------------------------------------------------- per worker ---
class Ctx:
    def __init__(self):
        self.L = ML.MachXO2Lift(DEVICE)
        self.rg = self.L.rg
        self.max_row = self.L.chip.get_max_row()
        self.max_col = self.L.chip.get_max_col()
        nat = self.L.chip._native
        dbroot = os.environ["TRELLIS_DBROOT"]
        # (src, sink) -> "pip" | "pip_nobits" (mux default, never in a .config)
        #                | "fixed"; rebuilt from bits.db like rgraph._build().
        self.garcs = {}
        for tname, (row, col) in nat.geom.tile_rc.items():
            muxes, fixed = load_mux_bits(dbroot, nat.geom.tile_type[tname])
            for sink, srcs in muxes.items():
                gk = nat.gl.globalise_net(row, col, sink)
                if gk is None:
                    continue
                for src, bits in srcs:
                    gs = nat.gl.globalise_net(row, col, src)
                    if gs is not None:
                        k = (tuple(gs), tuple(gk))
                        kind = "pip" if bits else "pip_nobits"
                        if self.garcs.get(k) != "pip":
                            self.garcs[k] = kind
            for sink, src in fixed:
                gk = nat.gl.globalise_net(row, col, sink)
                gs = nat.gl.globalise_net(row, col, src)
                if gk is not None and gs is not None:
                    self.garcs.setdefault((tuple(gs), tuple(gk)), "fixed")
        self.enums = load_plc_enums(dbroot)

    def glob(self, row, col, name):
        g = self.rg.globalise_net(row, col, name)
        return (g.loc.x, g.loc.y, g.id) if g.loc.x >= 0 and g.loc.y >= 0 else None

    def gkey_branch(self, row, col, name):
        """Which gkey() path a tile-local name takes (mirrors its conditions)."""
        L = self.L
        g = self.rg.globalise_net(row, col, name)
        if g.loc.x >= 0 and g.loc.y >= 0:
            if g.loc.y in (0, self.max_row):
                mv = L._VSPAN.match(self.rg.to_str(g.id))
                if mv and int(mv.group(1)) >= 2:
                    flip = "S" if mv.group(2) == "N" else "N"
                    crow = 1 if g.loc.y == 0 else self.max_row - 1
                    if L.wname_id(g.loc.x, crow, f"V{mv.group(1)}{flip}{mv.group(3)}") \
                            is not None:
                        return "vspan_edge_flip"
            return "plain"
        m = (L._SEG_EAST.match(name) or L._SEG_WEST.match(name)
             or L._SEG_NORTH.match(name) or L._SEG_SOUTH.match(name))
        if not m:
            if re.match(r"^(G|BRANCH|D)_", name):
                return "global_drop"       # chip-global clock net: no fabric key
            return "unresolved_drop"
        hops, d = int(m.group(1)), name[0]
        if d == "E" and col + hops > self.max_col and col == self.max_col:
            mh = re.match(r"^E\d+_H(\d+)([EW])(\d+)$", name)
            if mh and mh.group(1) != "06":
                return "h_right_flip"
        if d == "W" and col - hops < 0:
            if col == 0:
                mh = re.match(r"^W\d+_H(\d+)([EW])(\d+)$", name)
                if mh and mh.group(1) != "06":
                    return "h_left_flip"
            return "left_stub_drop"
        if (d == "E" and col + hops > self.max_col) or (d == "W" and col - hops < 0):
            return "walkback_hstub"   # off-die E/W name with no rule: generic walk-back
        mvs = re.match(r"^[NS]\d+_V(\d+)([NS])(\d+)$", name)
        if mvs and ((d == "N" and row - hops < 0)
                    or (d == "S" and row + hops > self.max_row)):
            over = (hops - row) if d == "N" else (row + hops - self.max_row)
            if over == 1:
                return "vspan_offdie_flip"
            return f"vspan_offdie_over{over}_walkback"
        return "walkback"


# PIO-internal wires: the lifter's pad node is JQ/JA, so these never enter its DSU.
_PAD_INTERNAL = re.compile(r"^(JPADD[IO][A-D](_PIO)?|PADD[IO][A-D]_PIO|JDI[A-D]|JPADDI\d)$")
_tls = threading.local()


def ctx():
    if not hasattr(_tls, "c"):
        _tls.c = Ctx()
    return _tls.c


_SPAN = re.compile(r"^([VH])(\d\d)([NSEW])(\d\d)(\d\d)$")
_OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}


def span_alias(C, r, c, nm):
    """Diamond span wire named by a non-canonical segment (V02N0400 at R1, where
    prjtrellis only has V02N0401) -> (hop-prefixed local alias, label) or None.
    Segment s -> t is a hop of t-s tiles in the wire's own direction."""
    m = _SPAN.match(nm)
    if not m:
        return None
    vh, span, d, idx, s = m.group(1), m.group(2), m.group(3), m.group(4), int(m.group(5))
    for t in range(0, int(span) + 1):
        k = t - s
        if k == 0:
            continue
        cand = f"{vh}{span}{d}{idx}{t:02d}"
        alias = f"{d if k > 0 else _OPP[d]}{abs(k)}_{cand}"
        g = C.glob(r, c, alias)
        if g and C.L.wname_id(g[0], g[1], g[2]) is not None:
            return alias, f"segment_alias_{vh}{span}{d}_{s:02d}->{t:02d}"
    return None


def dwire(w):
    """Diamond absolute wire -> (graph row, graph col, name)."""
    r, c, nm = P.split_wire(w)
    return r, c - COL_BIAS, nm


# ------------------------------------------------------------- comparison ---
def compare_target(target, targets_dir, out_root):
    C = ctx()
    L = C.L
    od = os.path.join(out_root, target)
    with open(os.path.join(od, "oracle.json")) as fh:
        O = json.load(fh)
    bit = os.path.join(targets_dir, target, "impl1", "fuzz_impl1.bit")
    text, _pb, _bram = native_config.config_from_file(
        bit, device=DEVICE, db_root=os.environ["TRELLIS_DBROOT"])
    cfg_path = os.path.join(od, "decoded.config")
    with open(cfg_path, "w") as fh:
        fh.write(text)
    pc = L.parse_config(cfg_path)
    design = L.recover_netlist(pc)
    dsu = design.dsu

    res = {"target": target, "schema_version": 1, "sites": [], "pips": Counter(),
           "pip_detail": defaultdict(Counter), "nets": [], "net_verdicts": Counter(),
           "normalisation": Counter(), "gkey": [], "lift_only_arcs": [],
           "wire_classes_missing": Counter()}
    norm = res["normalisation"]

    # ---- wire mapping ------------------------------------------------------
    wcache = {}

    def wmap(w):
        """Diamond wire -> dict(raw graph key, gkey, dsu key, exists)."""
        if w in wcache:
            return wcache[w]
        r, c, nm = dwire(w)
        info = {"exists": False, "raw": None, "dsu": None}
        ongrid = 0 <= r <= C.max_row and 0 <= c <= C.max_col
        if ongrid and L.wname_id(c, r, nm) is None:
            for pfx in ("G_", "BRANCH_", "D_"):   # prjtrellis global-net prefixes
                if L.wname_id(c, r, pfx + nm) is not None:
                    norm[f"prefix_{pfx}"] += 1
                    nm = pfx + nm
                    break
        if ongrid and L.wname_id(c, r, nm) is None:
            alias = span_alias(C, r, c, nm)
            if alias:
                norm[alias[1]] += 1
                g = C.glob(r, c, alias[0])
                info = {"exists": True, "raw": g, "dsu": L.gkey(r, c, alias[0]),
                        "alias": alias[0]}
                wcache[w] = info
                return info
        if ongrid and L.wname_id(c, r, nm) is not None:
            info["exists"] = True
            g = C.glob(r, c, nm)
            info["raw"] = g
            if g != (c, r, nm):
                norm["diamond_name_not_canonical"] += 1
            dn = nm
            if nm.endswith("_SLICE") and L.wname_id(c, r, nm[:-6]) is not None:
                dn = nm[:-6]       # lift remap(): bel pin X_SLICE -> fabric X
                norm["strip_SLICE"] += 1
            info["dsu"] = L.gkey(r, c, dn)
        else:
            res["wire_classes_missing"][re.sub(r"\d", "#", nm)] += 1
            for dc in (1, -1):
                if 0 <= c + dc <= C.max_col and 0 <= r <= C.max_row \
                        and L.wname_id(c + dc, r, nm) is not None:
                    norm[f"exists_only_at_col_offset_{dc:+d}"] += 1
                    break
        wcache[w] = info
        return info

    # ---- decoded config arcs ----------------------------------------------
    cfg_raw = {}        # (raw src, raw sink) -> (r, c, sink, source)
    sink_srcs = defaultdict(set)
    for (r, c, sink, src) in pc.arcs:
        ks, kd = C.glob(r, c, src), C.glob(r, c, sink)
        if ks and kd:
            cfg_raw[(ks, kd)] = (r, c, sink, src)
            sink_srcs[kd].add(ks)

    # ---- pips ---------------------------------------------------------------
    d_arcs = set()
    for n in O["nets"]:
        for a, b in n["arcs"]:
            ia, ib = wmap(a), wmap(b)
            cls = (re.sub(r"\d", "#", P.split_wire(a)[2]) + ">"
                   + re.sub(r"\d", "#", P.split_wire(b)[2]))
            if not (ia["exists"] and ib["exists"]):
                v, why = "ORACLE_ONLY", "wire_not_in_graph"
            else:
                d_arcs.add((ia["raw"], ib["raw"]))
                kind = C.garcs.get((ia["raw"], ib["raw"]))
                if kind in ("pip", "pip_nobits"):
                    if (ia["raw"], ib["raw"]) in cfg_raw:
                        v, why = "MATCH", "pip_decoded"
                    elif sink_srcs.get(ib["raw"]):
                        v, why = "MISMATCH", "sink_driven_by_other_pip"
                    elif kind == "pip_nobits":
                        # mux default: no bits, so no .config line by design
                        same = (ia["dsu"] in dsu.p and ib["dsu"] in dsu.p
                                and dsu.find(ia["dsu"]) == dsu.find(ib["dsu"]))
                        bn = P.split_wire(b)[2]
                        if same:
                            v, why = "MATCH", "pip_nobits_same_dsu"
                        elif re.match(r"^DI\d$", bn):
                            v, why = "MATCH", "F_to_DI_modelled_by_ff_d_source"
                        elif _PAD_INTERNAL.match(bn) or \
                                _PAD_INTERNAL.match(P.split_wire(a)[2]):
                            v, why = "ORACLE_ONLY", "pad_internal_outside_lift_model"
                        else:
                            v, why = "LIFT_MISSING", "pip_nobits_not_unioned"
                    else:
                        v, why = "LIFT_MISSING", "pip_not_decoded"
                elif kind == "fixed":
                    if ia["dsu"] in dsu.p and ib["dsu"] in dsu.p:
                        same = dsu.find(ia["dsu"]) == dsu.find(ib["dsu"])
                        v, why = ("MATCH", "fixed_same_dsu") if same else \
                            ("LIFT_MISSING", "fixed_not_unioned")
                    elif ia["dsu"] is not None and ia["dsu"] == ib["dsu"]:
                        v, why = "MATCH", "fixed_same_key"
                    else:
                        v, why = "ORACLE_ONLY", "fixed_outside_lift_dsu"
                else:
                    v, why = "ORACLE_ONLY", "arc_not_in_graph"
            res["pips"][v] += 1
            res["pip_detail"][f"{v}:{why}"][cls] += 1
    for (ks, kd), arc in cfg_raw.items():
        if (ks, kd) not in d_arcs:
            res["pips"]["LIFT_ONLY"] += 1
            glb = re.match(r"^(G|BRANCH|L|R)_", arc[3]) or re.match(r"^(G|BRANCH|L|R)_", arc[2])
            res["pip_detail"]["LIFT_ONLY:" + ("global_clock_name" if glb else "fabric")][
                re.sub(r"\d", "#", arc[3]) + ">" + re.sub(r"\d", "#", arc[2])] += 1
            if len(res["lift_only_arcs"]) < 50:
                res["lift_only_arcs"].append(list(arc))

    # ---- nets ---------------------------------------------------------------
    root_nets = defaultdict(set)
    net_roots = {}
    for n in O["nets"]:
        roots = set()
        mapped = 0
        for w in n["wires"]:
            i = wmap(w)
            if i["exists"]:
                mapped += 1
                if i["dsu"] is not None and i["dsu"] in dsu.p:
                    roots.add(dsu.find(i["dsu"]))
        net_roots[n["name"]] = (roots, mapped)
        for rt in roots:
            root_nets[rt].add(n["name"])
    for n in O["nets"]:
        roots, mapped = net_roots[n["name"]]
        merged = sorted({x for rt in roots for x in root_nets[rt]} - {n["name"]})
        if not n["wires"]:
            v = "ORACLE_ONLY"           # unrouted in Diamond (none in corpus)
        elif mapped == 0:
            v = "ORACLE_ONLY"
        elif not roots:
            v = "LIFT_MISSING"
        elif len(roots) > 1 or merged:
            v = "MISMATCH"
        else:
            v = "MATCH"
        res["net_verdicts"][v] += 1
        rec = {"net": n["name"], "verdict": v, "lift_classes": len(roots),
               "merged_with": merged[:10],
               "lift_nets": sorted({design.net_name.get(rt, "?") for rt in roots})[:10]}
        if v != "MATCH":
            rec["unmapped_wires"] = [w for w in n["wires"] if not wmap(w)["exists"]][:20]
        res["nets"].append(rec)
    dnet_to_lift = {}
    for name, (roots, _m) in net_roots.items():
        if len(roots) == 1:
            dnet_to_lift[name] = design.net_name.get(next(iter(roots)))

    # ---- sites --------------------------------------------------------------
    luts = {lt["name"]: lt for lt in design.luts}
    ffs = {ff["name"]: ff for ff in design.ffs}
    for comp in O["comps"]:
        if comp["type"] != "SLICE":
            continue
        ms = re.match(r"^R(\d+)C(\d+)([A-D])$", comp["site"] or "")
        r, c, sl = int(ms.group(1)), int(ms.group(2)) - COL_BIAS, ms.group(3)
        si = "ABCD".index(sl)
        f = P.config_fields(comp["config"])
        tenum = pc.enums.get((r, c), {})
        fields = []

        def fld(name, verdict, diamond, ours):
            fields.append({"field": name, "verdict": verdict,
                           "diamond": diamond, "pluribus": ours})

        if pc.tile_type.get((r, c)) != "PLC":
            fld("tile", "MISMATCH", comp["site"], pc.tile_type.get((r, c)))
            res["sites"].append({"comp": comp["name"], "site": comp["site"],
                                 "fields": fields})
            continue

        def enum_cmp(label, ename, dval):
            if ename not in C.enums:
                fld(label, "ORACLE_ONLY", dval, f"no enum {ename}")
                return
            default, opts = C.enums[ename]
            ours = tenum.get(ename, default)
            if dval not in opts:
                fld(label, "ORACLE_ONLY", dval, ours)
            elif opts[dval] == opts.get(ours):
                fld(label, "MATCH", dval, ours)
            else:
                fld(label, "MISMATCH", dval, ours)

        enum_cmp("MODE", f"SLICE{sl}.MODE", f.get("MODE", "LOGIC"))
        has_ff = f.get("REGMODE", "#OFF") != "#OFF"
        if has_ff:
            enum_cmp("REGMODE", f"SLICE{sl}.REGMODE", f["REGMODE"])
            enum_cmp("GSR", f"SLICE{sl}.GSR", f["GSR"])
            enum_cmp("CEMUX", f"SLICE{sl}.CEMUX", f["CEMUX"])
            enum_cmp("CLKMUX", f"CLK{si}.CLKMUX", f["CLKMUX"])
            enum_cmp("SRMODE", f"LSR{si}.SRMODE", f["SRMODE"])
            enum_cmp("LSRONMUX", f"LSR{si}.LSRONMUX", f["LSRONMUX"])
            if f.get("LSRMUX", "#OFF") != "#OFF":
                enum_cmp("LSRMUX", f"LSR{si}.LSRMUX", f["LSRMUX"])
        if f.get("MODE") == "CCU2":
            cc = f.get("CCU2", "")
            inj = dict(kv.split("=") for kv in cc.split(":")[2].split(",") if kv) \
                if cc.count(":") >= 2 else {}
            for k in (0, 1):
                enum_cmp(f"CCU2.INJECT1_{k}", f"SLICE{sl}.CCU2.INJECT1_{k}",
                         inj.get(f"INJECT1_{k}", "NO"))
        # LUTs
        ccu = re.match(r"^:S0=0x([0-9a-fA-F]+),S1=0x([0-9a-fA-F]+)", f.get("CCU2", ""))
        for k in (0, 1):
            dec = pc.lut_init.get((r, c, sl, str(k)))
            if ccu:
                want = int(ccu.group(1 + k), 16)
            elif f.get(f"K{k}", "#OFF").startswith(f":H{k}="):
                want = lut_eval(f[f"K{k}"][len(f":H{k}="):])
            else:
                want = None
            if want is None:
                v = "MATCH" if dec is None or init_int(dec) == 0 else "LIFT_ONLY"
                fld(f"K{k}.INIT", v, "#OFF", dec)
                continue
            # No word in the .config = bits.db default for SLICEx.Kk.INIT (all 1s).
            got = init_int(dec) if dec is not None else LUT_INIT_DEFAULT
            fld(f"K{k}.INIT", "MATCH" if got == want else "MISMATCH",
                f"0x{want:04X}", f"0x{got:04X}" + ("" if dec is not None else " (default)"))
            # lifted cell (constant LUTs are folded, CCU2 emitted differently)
            if not ccu and want not in (0, 0xFFFF):
                lt = luts.get(f"lut_r{r}c{c}_{sl}k{k}")
                fld(f"K{k}.lift", "LIFT_MISSING" if lt is None else
                    ("MATCH" if init_int(lt["init"]) == want else "MISMATCH"),
                    f"0x{want:04X}", None if lt is None else f"0x{init_int(lt['init']):04X}")
        # FFs as lifted
        for j in (0, 1):
            reg = f.get(f"REG{j}", "#OFF")
            if reg == "#OFF":
                continue
            regset = "SET" if "REGSET=SET" in reg else "RESET"
            sd = "0" if "SD=0" in reg else "1"
            enum_cmp(f"REG{j}.REGSET", f"SLICE{sl}.REG{j}.REGSET", regset)
            enum_cmp(f"REG{j}.SD", f"SLICE{sl}.REG{j}.SD", sd)
            ff = ffs.get(f"ff_r{r}c{c}_{sl}{j}")
            if ff is None:
                fld(f"FF{j}.lift", "LIFT_MISSING", "present", None)
                continue
            fld(f"FF{j}.lift.regset", "MATCH" if ff["regset"] == regset else "MISMATCH",
                regset, ff["regset"])
            fld(f"FF{j}.lift.sd", "MATCH" if ff["sd"] == sd else "MISMATCH", sd, ff["sd"])
            fld(f"FF{j}.lift.srmode", "MATCH" if ff["srmode"] == f["SRMODE"] else "MISMATCH",
                f["SRMODE"], ff["srmode"])
            fld(f"FF{j}.lift.gsr", "MATCH" if ff["gsr"] == f["GSR"] else "MISMATCH",
                f["GSR"], ff["gsr"])
            # D: an unresolved D (tied-0 fallback) is a missing connection.  SD=0 has
            # a Diamond M pin to compare; SD=1 (F->DI) has no routed D wire.
            dnet = comp["pins"].get(f"M{j}") if sd == "0" else None
            if ff.get("d_fault"):
                v = "LIFT_MISSING"
            elif sd == "0" and dnet is None:
                v = "LIFT_ONLY"
            elif sd == "0" and dnet not in dnet_to_lift:
                v = "ORACLE_ONLY"
            elif sd == "0":
                v = "MATCH" if dnet_to_lift[dnet] == ff["d"] else "MISMATCH"
            else:
                v = "MATCH"
            fld(f"FF{j}.lift.d", v, dnet, ff["d"] + (f" [{ff['d_fault']}]" if ff.get("d_fault") else ""))
            for pin, key, const in (("CLK", "clk", "1'b0"), ("CE", "ce", "1'b1"),
                                    ("LSR", "lsr", "1'b0")):
                dnet = comp["pins"].get(pin)
                ours = ff[key]
                if dnet is None:
                    v = "MATCH" if ours == const else "LIFT_ONLY"
                elif dnet not in dnet_to_lift:
                    v = "ORACLE_ONLY"
                else:
                    v = "MATCH" if dnet_to_lift[dnet] == ours else "MISMATCH"
                fld(f"FF{j}.lift.{key}", v, dnet, ours)
        res["sites"].append({"comp": comp["name"], "site": comp["site"],
                             "fields": fields})

    # ---- gkey workarounds ---------------------------------------------------
    split_nets = {n["net"] for n in res["nets"] if n["lift_classes"] > 1}
    dwire_net = {}
    for n in O["nets"]:
        for w in n["wires"]:
            i = wmap(w)
            if i["raw"]:
                dwire_net[i["raw"]] = n["name"]
    for (r, c, sink, src) in pc.arcs:
        for end, nm, other in (("sink", sink, src), ("source", src, sink)):
            br = C.gkey_branch(r, c, nm)
            if br == "plain":
                continue
            raw = C.glob(r, c, nm)
            gk = L.gkey(r, c, nm)
            ok = C.glob(r, c, other)
            onet = dwire_net.get(ok)
            raw_net = dwire_net.get(raw)
            gk_net = dwire_net.get(tuple(gk)) if gk else None
            if gk is None:
                v = "DISAGREE" if raw_net or onet else "INCONCLUSIVE"
                why = ("dropped arc is on Diamond net " + str(onet or raw_net)) \
                    if v == "DISAGREE" else "no Diamond net uses this pip"
            elif onet is None:
                v, why = "INCONCLUSIVE", "Diamond does not route the other end"
            elif gk_net == onet:
                v, why = "AGREE", "rewritten wire is on the same Diamond net"
            elif gk_net is None and onet in split_nets:
                v, why = "DISAGREE", (f"rewritten key unused by Diamond; Diamond net "
                                      f"{onet} is split in the lift")
            elif gk_net is None:
                v, why = "INCONCLUSIVE", "rewritten wire not used by Diamond; net intact"
            else:
                v, why = "DISAGREE", f"rewritten wire is on Diamond net {gk_net}"
            res["gkey"].append({"branch": br, "tile": [r, c], "end": end, "name": nm,
                                "other": other, "raw": raw, "gkey": gk,
                                "diamond_net_other": onet,
                                "diamond_net_rewritten": gk_net,
                                "verdict": v, "why": why})

    # ---- roll-up ------------------------------------------------------------
    fc = Counter()
    for s in res["sites"]:
        for fd in s["fields"]:
            fc[f"{fd['field'].replace('0', '#').replace('1', '#')}:{fd['verdict']}"] += 1
    res["site_field_verdicts"] = dict(fc)
    res["gkey_verdicts"] = dict(Counter(f"{g['branch']}:{g['verdict']}" for g in res["gkey"]))
    res["pips"] = dict(res["pips"])
    res["pip_detail"] = {k: dict(v) for k, v in res["pip_detail"].items()}
    res["net_verdicts"] = dict(res["net_verdicts"])
    res["normalisation"] = dict(norm)
    res["wire_classes_missing"] = dict(res["wire_classes_missing"])
    res["lift"] = {"luts": len(design.luts), "ffs": len(design.ffs),
                   "nets": len(design.all_nets), "config_arcs": len(pc.arcs)}
    tmp = os.path.join(od, "compare.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True, default=list)
    os.replace(tmp, os.path.join(od, "compare.json"))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--targets-dir",
                    default=os.path.join(REPO, "diamond-fuzz", "targets"))
    ap.add_argument("--out",
                    default=os.path.join(REPO, "corpus", "machxo2", "diamond-fuzz"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    targets = args.only or sorted(
        t for t in os.listdir(args.out)
        if os.path.exists(os.path.join(args.out, t, "oracle.json")))
    log(f"[compare] {len(targets)} targets, {args.workers} workers")
    q = queue.Queue()
    for t in targets:
        q.put(t)
    results, lock, stop = [], threading.Lock(), threading.Event()

    def worker():
        while True:
            try:
                t = q.get_nowait()
            except queue.Empty:
                return
            heavy_guard.wait_available(_Log, "compare")
            try:
                r = compare_target(t, args.targets_dir, args.out)
                r = {"target": t, "status": "ok", **{k: r[k] for k in (
                    "pips", "pip_detail", "net_verdicts", "site_field_verdicts",
                    "gkey_verdicts", "normalisation", "wire_classes_missing")}}
            except (Exception, SystemExit) as e:  # noqa: BLE001 -- db.die() exits; recorded per target
                r = {"target": t, "status": "failed", "error": f"{type(e).__name__}: {e}"}
                log(f"[fail] {t}: {r['error']}")
            with lock:
                results.append(r)
                if len(results) % 250 == 0:
                    log(f"[compare] {len(results)}/{len(targets)}")

    t0 = time.monotonic()
    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    with heavy_guard.heavy_lock("machxo2_oracle_compare", _Log):
        for th in ths:
            th.start()
        for th in ths:
            th.join()

    summ = {"targets": len(results),
            "status": dict(Counter(r["status"] for r in results)),
            "failed": sorted((r["target"], r["error"]) for r in results
                             if r["status"] == "failed")}
    for key in ("pips", "net_verdicts", "site_field_verdicts", "gkey_verdicts",
                "normalisation", "wire_classes_missing"):
        acc = Counter()
        for r in results:
            acc.update(r.get(key, {}))
        summ[key] = dict(sorted(acc.items()))
    det = defaultdict(Counter)
    for r in results:
        for k, v in r.get("pip_detail", {}).items():
            det[k].update(v)
    summ["pip_detail"] = {k: dict(v.most_common(25)) for k, v in sorted(det.items())}
    # targets per non-MATCH verdict, for follow-up
    by = defaultdict(list)
    for r in results:
        for key in ("net_verdicts", "gkey_verdicts", "site_field_verdicts"):
            for k, v in r.get(key, {}).items():
                if not (k.endswith("MATCH") and not k.endswith("MISMATCH")) \
                        and not k.endswith("AGREE") or k.endswith("DISAGREE"):
                    by[f"{key}/{k}"].append(r["target"])
    summ["example_targets"] = {k: sorted(v)[:15] for k, v in sorted(by.items())}
    with open(os.path.join(args.out, "_compare_summary.json"), "w") as fh:
        json.dump(summ, fh, indent=1)
    log(f"[compare] done in {time.monotonic() - t0:.1f}s: {summ['status']}")
    for key in ("pips", "net_verdicts", "gkey_verdicts", "site_field_verdicts"):
        log(f"[compare] {key}: {summ[key]}")
    # Headline: a missing/extra connection is a fault as bad as a wrong one.
    sf = summ["site_field_verdicts"]
    clk = {k.split(":")[1]: v for k, v in sf.items() if k.startswith("FF#.lift.clk:")}
    summ["headline"] = {}
    ffd = {k.split(":")[1]: v for k, v in sf.items() if k.startswith("FF#.lift.d:")}
    for label, c in (("pips", summ["pips"]), ("nets", summ["net_verdicts"]),
                     ("register clock nets", clk), ("register D nets", ffd)):
        tot, ok = sum(c.values()), c.get("MATCH", 0)
        summ["headline"][label] = {"match": ok, "total": tot, "faults": tot - ok,
                                   "rate_pct": round(100.0 * ok / tot, 1) if tot else None}
        log(f"[compare] HEADLINE {label}: {ok}/{tot} = {100.0 * ok / tot:.1f}%  "
            f"faults (every non-MATCH) = {tot - ok}")
    with open(os.path.join(args.out, "_compare_summary.json"), "w") as fh:
        json.dump(summ, fh, indent=1)


if __name__ == "__main__":
    main()
