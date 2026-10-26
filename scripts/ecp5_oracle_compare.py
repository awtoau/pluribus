#!/usr/bin/env python3
"""Compare pluribus' ECP5 decode + lift against the Diamond oracle (#109).

Per target with an oracle.json (scripts/ecp5_diamond_oracle.py): native-decode
the matching .bit, lift with lifters/ecp5_lift.py, compare:
  * sites:   LUT INIT, slice enums, lifted FF fields
  * pips:    every Diamond route arc vs decoded config arcs
  * nets:    every Diamond net vs the lift's DSU classes (split / merge)
  * conns:   every driver -> load-pin connection of every Diamond net
  * regclk:  every register's clock pin, with the first broken clock-tree arc
Verdicts: MATCH / MISMATCH / LIFT_MISSING / ORACLE_ONLY / LIFT_ONLY.  Every
non-MATCH is a fault (CLAUDE.md "Scoring faults").  Definitions and wire-name
normalisations: docs/ecp5-diamond-oracle.md.

Writes <out>/<target>/compare.json and <out>/_compare_summary.json.
Usage: python3.15t scripts/ecp5_oracle_compare.py [--workers N] [--only T ...]
Log:   tmp/logs/ecp5_oracle_compare.log
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
from ecp5_diamond_oracle import REPO, data_root  # noqa: E402
import heavy_guard  # noqa: E402

os.environ.setdefault("TRELLIS_DBROOT", toolchain.trellis_dbroot())
from lifters.ecp5_lift import ECP5Lift  # noqa: E402
import native_config  # noqa: E402

LOG_PATH = os.path.join(REPO, "tmp", "logs", "ecp5_oracle_compare.log")
SCHEMA_VERSION = 3
_log_lock = threading.Lock()


class _GuardLog:
    """logging-style adapter for heavy_guard.wait_available."""
    @staticmethod
    def info(fmt, *a):
        log("[guard] " + (fmt % a))


def log(msg):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with _log_lock:
        print(f"{now}  {msg}", flush=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(f"{now}  {msg}\n")


# ------------------------------------------------------------ bits.db ------
_PLC_CACHE = {}
_MUX_CACHE = {}
_CACHE_LOCK = threading.Lock()


def load_plc_enums(dbroot):
    """PLC2 .config_enum -> {name: (default, {option: frozenset(bits)})}."""
    with _CACHE_LOCK:
        if "e" in _PLC_CACHE:
            return _PLC_CACHE["e"]
    out, cur = {}, None
    with open(os.path.join(dbroot, "ECP5", "tiledata", "PLC2", "bits.db")) as fh:
        for ln in fh:
            t = ln.split()
            if not t:
                cur = None
            elif t[0] == ".config_enum":
                cur = t[1]
                out[cur] = (t[2], {})
            elif t[0].startswith("."):
                cur = None
            elif cur:
                out[cur][1][t[0]] = frozenset(b for b in t[1:] if b != "-")
    with _CACHE_LOCK:
        _PLC_CACHE["e"] = out
    return out


def load_mux_bits(dbroot, ttype):
    """tiletype bits.db -> ({sink: [(source, bits)]}, {sink: [source]} fixed)."""
    with _CACHE_LOCK:
        if ttype in _MUX_CACHE:
            return _MUX_CACHE[ttype]
    muxes, fixed, cur = {}, defaultdict(list), None
    with open(os.path.join(dbroot, "ECP5", "tiledata", ttype, "bits.db")) as fh:
        for ln in fh:
            t = ln.split()
            if not t or t[0].startswith("#"):
                cur = None
            elif t[0] == ".mux":
                cur = t[1]
                muxes.setdefault(cur, [])
            elif t[0] == ".fixed_conn":
                fixed[t[1]].append(t[2])
                cur = None
            elif t[0].startswith("."):
                cur = None
            elif cur is not None:
                muxes[cur].append((t[0], tuple(b for b in t[1:] if b != "-")))
    with _CACHE_LOCK:
        _MUX_CACHE[ttype] = (muxes, dict(fixed))
    return muxes, dict(fixed)


# LUT equations: shared with the MachXO2 comparison (same Diamond syntax).
_TOK = re.compile(r"\s*([ABCD01]|[~*+@^()])")


def lut_eval(expr):
    """Diamond LUT equation -> 16-bit truth table int, bit A+2B+4C+8D."""
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
        idx = "ABCD".index(t)
        return sum(1 << i for i in range(16) if (i >> idx) & 1)

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


LUT_INIT_DEFAULT = 0xFFFF       # PLC2 bits.db `.config SLICEA.K0.INIT 1111111111111111`

# ------------------------------------------------------- name handling -----
_GLOBAL_PFX = ("G_", "R_", "L_")
_SPAN = re.compile(r"^([VH])(\d\d)([NSEW])(\d\d)(\d\d)$")
_OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
_MUXCTRL = re.compile(r"^(CLK|LSR)(\d)_SLICE$")   # the pin only; bare CLK1 is the tile wire


# Clock-tree wire families (Diamond local names, digit-collapsed by the regexes).
_GFAM = {k: re.compile(v) for k, v in {
    "PADMUX": r"^JPADDI[A-D]_PIO$|^JPADDI$|^JINCK$",
    "JPCLKT": r"^JPCLKT\d+$",
    "DCC": r"^(CLKI|CLKO)_[TLR]DCC\d$|^[TLR]DCC\dCLKI$",
    "VPFS": r"^VPFS\d+$",
    "QPCLK": r"^(LL|LR|UL|UR)PCLK\d$",
    "HPFE": r"^HPFE\d+$",
    "HPRX": r"^HPRX\d+$", "VPTX": r"^VPTX\d+$", "HPBX": r"^HPBX\d+$"}.items()}


def gfams(local_name):
    """Clock-tree families a (prefix-stripped) wire name belongs to."""
    nm = strip_gpfx(local_name)
    return [k for k, rx in _GFAM.items() if rx.match(nm)]


def pat(nm):
    """Digit-collapsed wire family: HPBX0000 -> HPBX#."""
    return re.sub(r"\d+", "#", nm)


def strip_gpfx(nm):
    return nm[2:] if nm.startswith(_GLOBAL_PFX) else nm


class Ctx:
    """Per worker thread, per device."""

    def __init__(self, device):
        self.dbroot = os.environ["TRELLIS_DBROOT"]
        self.L = ECP5Lift(device, dbroot=self.dbroot)
        self.rg = self.L.rg
        self.max_row, self.max_col = self.L.max_row, self.L.max_col
        self.enums = load_plc_enums(self.dbroot)
        self._tt = {}
        self._tp = {}

    def tile_types(self, r, c):
        k = (r, c)
        if k not in self._tt:
            self._tt[k] = [t.info.type for t in self.L.chip.get_tiles_by_position(r, c)]
        return self._tt[k]

    def rkey(self, row, col, name):
        """Raw graph identity (x, y, name) of a tile-local name; chip-globals that
        prjtrellis parks at (0,0) keep the referencing tile instead."""
        g = self.rg.globalise_net(row, col, name)
        if g.loc.x < 0 or g.loc.y < 0:
            return None
        nm = self.rg.to_str(g.id)
        if nm.startswith("G_") and (g.loc.x, g.loc.y) == (0, 0) and (col, row) != (0, 0):
            return (col, row, nm)
        return (g.loc.x, g.loc.y, nm)

    def tile_pips(self, r, c):
        """{(src raw key, sink raw key): kind} over every tile type at (r, c);
        kind pip | pip_nobits | fixed.  Pips are listed in the tile whose local
        names (E1_H02E0001, ...) reach the wire, which is not always its home."""
        k = (r, c)
        if k in self._tp:
            return self._tp[k]
        out = {}
        for tt in self.tile_types(r, c):
            muxes, fixed = load_mux_bits(self.dbroot, tt)
            for sink, srcs in muxes.items():
                kd = self.rkey(r, c, sink)
                if kd is None:
                    continue
                for src, bits in srcs:
                    ks = self.rkey(r, c, src)
                    if ks is not None:
                        kind = "pip" if bits else "pip_nobits"
                        if out.get((ks, kd)) != "pip":
                            out[(ks, kd)] = kind
            for sink, srcs in fixed.items():
                kd = self.rkey(r, c, sink)
                for src in srcs:
                    ks = self.rkey(r, c, src)
                    if kd is not None and ks is not None:
                        out.setdefault((ks, kd), "fixed")
        self._tp[k] = out
        return out

    def span_alias(self, r, c, nm):
        """Diamond names a die-edge-truncated span by the segment on its own tile
        (V02N0400 at R1); prjtrellis only has the canonical segment."""
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
            g = self.rg.globalise_net(r, c, alias)
            if g.loc.x >= 0 and g.loc.y >= 0 and \
                    self.L.wname_id(g.loc.x, g.loc.y, self.rg.to_str(g.id)) is not None:
                return alias, f"segment_alias_{vh}{span}{d}_{s:02d}->{t:02d}"
        return None


_tls = threading.local()


def ctx(device):
    if not hasattr(_tls, "c"):
        _tls.c = {}
    if device not in _tls.c:
        _tls.c = {device: Ctx(device)}      # one device per thread at a time (memory)
    return _tls.c[device]


# ------------------------------------------------------------ comparison ---
def compare_target(target, out_root):
    od = os.path.join(out_root, target)
    with open(os.path.join(od, "oracle.json")) as fh:
        O = json.load(fh)
    if not O.get("bit"):
        raise RuntimeError("no .bit for this target")
    device = O["device"]
    C = ctx(device)
    L = C.L
    text, _pb, _bram = native_config.config_from_file(
        O["bit"], device=device, db_root=os.environ["TRELLIS_DBROOT"])
    cfg_path = os.path.join(od, "decoded.config")
    with open(cfg_path, "w") as fh:
        fh.write(text)
    pc = L.parse_config(cfg_path)
    design = L.recover_netlist(pc)
    dsu = design.dsu

    res = {"target": target, "schema_version": SCHEMA_VERSION, "device": device,
           "sites": [], "pips": Counter(), "pip_detail": defaultdict(Counter),
           "nets": [], "net_verdicts": Counter(), "conns": Counter(),
           "conn_detail": defaultdict(Counter), "regclk": [], "regclk_verdicts": Counter(),
           "clock_family": defaultdict(lambda: Counter()),
           "clock_join": defaultdict(Counter), "normalisation": Counter(),
           "wire_classes_missing": Counter(), "lift_only_arcs": [],
           "lift_global_drop": defaultdict(Counter), "clock_shapes": Counter()}
    norm = res["normalisation"]

    # ---- wire mapping ------------------------------------------------------
    wcache = {}

    def wmap(w):
        """Diamond wire -> {exists, name (graph-local), pfx, raw, dsu, kind}."""
        if w in wcache:
            return wcache[w]
        r, c, nm = P.split_wire(w)
        info = {"exists": False, "name": nm, "raw": None, "dsu": None, "r": r, "c": c,
                "dnm": nm, "glob": False}
        ongrid = 0 <= r <= C.max_row and 0 <= c <= C.max_col
        if ongrid:
            found = None
            for pfx in ("",) + _GLOBAL_PFX:
                if L.wname_id(c, r, pfx + nm) is not None:
                    found = pfx + nm
                    if pfx:
                        norm[f"prefix_{pfx}"] += 1
                        info["glob"] = True
                    break
            if found is None:
                alias = C.span_alias(r, c, nm)
                if alias:
                    norm[alias[1]] += 1
                    found = alias[0]
                    info["alias"] = True
            if found is not None:
                info["exists"] = True
                info["name"] = found
                info["raw"] = C.rkey(r, c, found)
                dn = found
                m = _MUXCTRL.match(nm)
                if m and (r, c, f"MUX{m.group(1)}{m.group(2)}") in L._prefer_mux_nodes \
                        and L.wname_id(c, r, f"MUX{m.group(1)}{m.group(2)}") is not None:
                    dn = f"MUX{m.group(1)}{m.group(2)}"
                    norm["ctrl_pin_to_MUX_node"] += 1
                else:
                    for suf in ("_SLICE", "_PIO"):
                        if dn.endswith(suf) and L.wname_id(c, r, dn[:-len(suf)]) is not None:
                            dn = dn[:-len(suf)]
                            norm["strip_" + suf] += 1
                            break
                info["dnm"] = dn
                mdi = re.match(r"^DI(\d)$", dn)
                if mdi and L.wname_id(c, r, f"F{mdi.group(1)}") is not None:
                    # the lifter reads a register's D from the paired LUT's F
                    # (ff_d_source); DI never enters its DSU
                    dn = f"F{mdi.group(1)}"
                    norm["DI_to_F_via_ff_d_source"] += 1
                info["dsu"] = L.gkey(r, c, dn)
                if info["dsu"] is None:
                    info["dropped"] = True      # chip-global name: lift refuses to union
        if not info["exists"]:
            # clock-tree wires Diamond names at a tile prjtrellis has no wire at: resolve
            # through the lifter's canonical clock node (DSU only; pips stay not-in-graph)
            ck = L.clock_key(r, c, "G_" + nm) if ongrid and hasattr(L, "clock_key") else None
            if ck is not None:
                info["dsu"] = ck
                info["clock_node"] = True
                norm["clock_node"] += 1
            res["wire_classes_missing"][pat(nm)] += 1
        wcache[w] = info
        return info

    # ---- decoded config arcs ----------------------------------------------
    cfg_arcs = pc.arcs
    cfg_used = [False] * len(cfg_arcs)
    cfg_by_sink = defaultdict(list)         # (r, c, sink) -> [idx]
    cfg_by_tile = defaultdict(list)         # (r, c) -> [idx]
    cfg_name_pool = defaultdict(list)       # (stripped src, stripped sink) -> [idx]
    for i, (r, c, sink, src) in enumerate(cfg_arcs):
        cfg_by_sink[(r, c, sink)].append(i)
        cfg_by_tile[(r, c)].append(i)
        cfg_name_pool[(strip_gpfx(src), strip_gpfx(sink))].append(i)
    cfg_keys_cache = {}

    def cfg_keys(rc):
        if rc not in cfg_keys_cache:
            cfg_keys_cache[rc] = [(C.rkey(rc[0], rc[1], cfg_arcs[i][3]),
                                   C.rkey(rc[0], rc[1], cfg_arcs[i][2]), i)
                                  for i in cfg_by_tile.get(rc, [])]
        return cfg_keys_cache[rc]

    # ---- pips ---------------------------------------------------------------
    def family(a, b):
        return pat(strip_gpfx(wmap(a)["name"])) + ">" + pat(strip_gpfx(wmap(b)["name"]))

    arc_verdict = {}        # (a, b) -> (verdict, why)
    arc_cfg = {}            # (a, b) -> matched decoded arc index
    for n in O["nets"]:
        for a, b in n["arcs"]:
            ia, ib = wmap(a), wmap(b)
            fam = family(a, b)
            is_glob = ia["glob"] or ib["glob"] or bool(ia.get("dropped") or ib.get("dropped"))
            sp = (strip_gpfx(P.split_wire(a)[2]), strip_gpfx(P.split_wire(b)[2]))

            def by_name(a=a, b=b, sp=sp):
                pool = [i for i in cfg_name_pool.get(sp, []) if not cfg_used[i]]
                if pool:
                    cfg_used[pool[0]] = True
                    arc_cfg[(a, b)] = pool[0]
                    return True
                return False
            if not (ia["exists"] and ib["exists"]):
                # unlocated: the wire has no name at its Diamond tile.  Global tree
                # wires (HPRX/VPTX/DCC/PCLK...) are named at a tile prjtrellis does
                # not use; match by name pair only.
                if by_name():
                    v, why = "MATCH", "global_name_pair_only"
                elif (ia.get("clock_node") or ib.get("clock_node")) and ia["dsu"] is not None \
                        and ib["dsu"] is not None and ia["dsu"] in dsu.p and ib["dsu"] in dsu.p \
                        and dsu.find(ia["dsu"]) == dsu.find(ib["dsu"]):
                    # clock-tree wire the graph has no name for: the lift's rules join them
                    v, why = "MATCH", "clock_node_same_dsu"
                else:
                    v, why = "ORACLE_ONLY", ("wire_not_in_graph"
                                             if not (ia["exists"] or ib["exists"])
                                             else "one_wire_not_in_graph")
            else:
                match_idx = None
                kind = None
                if is_glob:
                    # global names are not unique per tile: match by local names in
                    # the sink's tile
                    for i in cfg_by_sink.get((ib["r"], ib["c"], ib["name"]), []):
                        if strip_gpfx(cfg_arcs[i][3]) == strip_gpfx(ia["name"]) \
                                and not cfg_used[i]:
                            match_idx = i
                            break
                else:
                    for rc in {(ib["r"], ib["c"]), (ia["r"], ia["c"])}:
                        for ks, kd, i in cfg_keys(rc):
                            if ks == ia["raw"] and kd == ib["raw"]:
                                match_idx = i
                                break
                        if match_idx is not None:
                            break
                        kind = kind or C.tile_pips(*rc).get((ia["raw"], ib["raw"]))
                if match_idx is not None:
                    cfg_used[match_idx] = True
                    arc_cfg[(a, b)] = match_idx
                    v, why = "MATCH", "pip_decoded" + ("_global_name" if is_glob else "")
                elif is_glob and by_name():
                    v, why = "MATCH", "global_name_pair_only"
                elif kind in ("pip", "pip_nobits"):
                    other = cfg_by_sink.get((ib["r"], ib["c"], ib["name"]))
                    if other:
                        v, why = "MISMATCH", "sink_driven_by_other_pip"
                    elif kind == "pip_nobits":
                        same = (ia["dsu"] is not None and ib["dsu"] is not None
                                and ia["dsu"] in dsu.p and ib["dsu"] in dsu.p
                                and dsu.find(ia["dsu"]) == dsu.find(ib["dsu"]))
                        if same:
                            v, why = "MATCH", "pip_nobits_same_dsu"
                        elif re.match(r"^DI\d$", ib["dnm"]):
                            v, why = "MATCH", "F_to_DI_modelled_by_ff_d_source"
                        else:
                            v, why = "LIFT_MISSING", "pip_nobits_not_unioned"
                    else:
                        v, why = "LIFT_MISSING", "pip_not_decoded"
                elif kind == "fixed":
                    if re.match(r"^F\d$", ia["dnm"]) and re.match(r"^DI\d$", ib["dnm"]):
                        v, why = "MATCH", "F_to_DI_modelled_by_ff_d_source"
                    elif ia["dsu"] is not None and ib["dsu"] is not None and \
                            ia["dsu"] in dsu.p and ib["dsu"] in dsu.p:
                        same = dsu.find(ia["dsu"]) == dsu.find(ib["dsu"])
                        v, why = ("MATCH", "fixed_same_dsu") if same else \
                            ("LIFT_MISSING", "fixed_not_unioned")
                    elif ia["dsu"] is not None and ia["dsu"] == ib["dsu"]:
                        v, why = "MATCH", "fixed_same_key"
                    else:
                        v, why = "ORACLE_ONLY", "fixed_outside_lift_dsu"
                else:
                    v, why = "ORACLE_ONLY", "arc_not_in_graph"
            arc_verdict[(a, b)] = (v, why)
            res["pips"][v] += 1
            res["pip_detail"][f"{v}:{why}"][fam] += 1
    for i, (r, c, sink, src) in enumerate(cfg_arcs):
        if cfg_used[i]:
            continue
        res["pips"]["LIFT_ONLY"] += 1
        glb = src.startswith(_GLOBAL_PFX) or sink.startswith(_GLOBAL_PFX)
        res["pip_detail"]["LIFT_ONLY:" + ("global_name" if glb else "fabric")][
            pat(src) + ">" + pat(sink)] += 1
        if len(res["lift_only_arcs"]) < 50:
            res["lift_only_arcs"].append([r, c, sink, src])

    # ---- what the lift drops: decoded arcs whose endpoint gkey() is None ----
    for (r, c, sink, src) in cfg_arcs:
        tt = pc.tile_type.get((r, c), "?")
        for end, nm in (("sink", sink), ("source", src)):
            if L.gkey(r, c, nm) is None:
                g = C.rkey(r, c, nm)
                why = "offgrid" if g is None else (
                    "parked_0_0" if nm.startswith("G_") else "other")
                res["lift_global_drop"][f"{why}:{pat(nm)}"][tt] += 1

    # ---- nets, connections, clock paths ------------------------------------
    root_nets = defaultdict(set)
    net_roots = {}
    net_tree = {}
    for n in O["nets"]:
        roots = set()
        mapped = 0
        for w in n["wires"]:
            i = wmap(w)
            if i["exists"] or i.get("clock_node"):
                mapped += 1
                if i["dsu"] is not None and i["dsu"] in dsu.p:
                    roots.add(dsu.find(i["dsu"]))
        net_roots[n["name"]] = (roots, mapped)
        for rt in roots:
            root_nets[rt].add(n["name"])
        parent = {}
        for a, b in n["arcs"]:
            parent.setdefault(b, a)
        srcs = {a for a, _b in n["arcs"]}
        sinks = {b for _a, b in n["arcs"]}
        net_tree[n["name"]] = (parent, sorted(srcs - sinks), sorted(sinks - srcs))
    for n in O["nets"]:
        roots, mapped = net_roots[n["name"]]
        merged = sorted({x for rt in roots for x in root_nets[rt]} - {n["name"]})
        if not n["wires"] or mapped == 0:
            v = "ORACLE_ONLY"
        elif not roots:
            v = "LIFT_MISSING"
        elif len(roots) > 1 or merged:
            v = "MISMATCH"
        else:
            v = "MATCH"
        res["net_verdicts"][v] += 1
        rec = {"net": n["name"], "verdict": v, "lift_classes": len(roots),
               "merged_with": merged[:10], "clock": "PAR_CLOCKSIGNAL" in n["props"]}
        if v != "MATCH":
            rec["unmapped_wires"] = [w for w in n["wires"] if not wmap(w)["exists"]][:20]
        res["nets"].append(rec)

    # Diamond nets carrying a clock-tree wire, per family.  intact = lift MATCH AND every
    # family wire is a DSU node (an unmapped wire is invisible to the MATCH verdict).
    vmap_ = {r_["net"]: r_["verdict"] for r_ in res["nets"]}
    gn = defaultdict(lambda: {"nets": 0, "intact": 0, "split": 0})
    for n in O["nets"]:
        if "PAR_CLOCKSIGNAL" not in n["props"]:
            continue            # data nets also touch pad-mux wires; only clock nets count here
        byfam = defaultdict(list)
        for w in n["wires"]:
            for fk in gfams(P.split_wire(w)[2]):
                byfam[fk].append(w)
        for fk, ws in byfam.items():
            ok = vmap_[n["name"]] == "MATCH" and all(
                wmap(w)["dsu"] is not None and wmap(w)["dsu"] in dsu.p for w in ws)
            gn[fk]["nets"] += 1
            gn[fk]["intact"] += ok
            gn[fk]["split"] += vmap_[n["name"]] == "MISMATCH"
    res["global_nets"] = {k: dict(v) for k, v in gn.items()}
    res["global_regclk"] = defaultdict(Counter)

    def link_ok(a, b):
        ia, ib = wmap(a), wmap(b)
        if not (ia["exists"] and ib["exists"]):
            return False, "wire_not_in_graph"
        ka, kb = ia["dsu"], ib["dsu"]
        if ka is None or kb is None:
            return False, "dropped_global"
        if ka not in dsu.p or kb not in dsu.p:
            return False, "not_in_lift"
        if dsu.find(ka) != dsu.find(kb):
            return False, "split"
        return True, "ok"


    def arc_reason(a, b):
        """Why the lift keeps / loses one Diamond clock-path arc."""
        v, why = arc_verdict.get((a, b), ("ORACLE_ONLY", "no_verdict"))
        ci = arc_cfg.get((a, b))
        if ci is not None:
            r, c, sink, src = cfg_arcs[ci]
            if L.gkey(r, c, sink) is None or L.gkey(r, c, src) is None:
                return "dropped_global"
            return "ok"
        if v == "MATCH":
            return "ok"
        return "not_decoded" if why != "wire_not_in_graph" else "not_decoded_unlocated"

    def join_reason(e1, e2):
        """Wire shared by consecutive arcs e1 (into it) and e2 (out of it): does
        the lift give both arcs the same node key?"""
        c1, c2 = arc_cfg.get(e1), arc_cfg.get(e2)
        if c1 is None or c2 is None:
            return "ok"
        r1, cc1, sink1, _s1 = cfg_arcs[c1]
        r2, cc2, _k2, src2 = cfg_arcs[c2]
        k1, k2 = L.gkey(r1, cc1, sink1), L.gkey(r2, cc2, src2)
        if k1 is None or k2 is None:
            return "ok"        # reported as dropped_global on the arc itself
        return "ok" if k1 == k2 else "unlinked_join"

    conn_of = {}            # (net, leaf wire) -> (verdict, why)
    for n in O["nets"]:
        parent, roots_w, leaves = net_tree[n["name"]]
        clock = "PAR_CLOCKSIGNAL" in n["props"]
        if not n["arcs"]:
            continue
        rw = roots_w[0] if roots_w else None
        for leaf in leaves:
            il = wmap(leaf)
            ir = wmap(rw) if rw else None
            if ir is None or not (il["exists"] and ir["exists"]):
                v, why = "ORACLE_ONLY", "endpoint_not_in_graph"
            elif il["dsu"] is None or ir["dsu"] is None:
                v, why = "LIFT_MISSING", "endpoint_dropped_global"
            elif il["dsu"] not in dsu.p or ir["dsu"] not in dsu.p:
                v, why = "LIFT_MISSING", "endpoint_not_in_lift"
            elif dsu.find(il["dsu"]) == dsu.find(ir["dsu"]):
                v, why = "MATCH", "same_class"
            else:
                v, why = "MISMATCH", "split"
            conn_of[(n["name"], leaf)] = (v, why)
            res["conns"][v] += 1
            res["conn_detail"][f"{'clock' if clock else 'data'}:{v}:{why}"][pat(P.split_wire(leaf)[2])] += 1
        if clock and leaves:
            # clock-tree shape: driver -> one leaf, as a family chain
            chain, w = [], leaves[0]
            while w in parent:
                chain.append(pat(strip_gpfx(wmap(w)["name"])))
                w = parent[w]
            chain.append(pat(strip_gpfx(wmap(w)["name"])))
            res["clock_shapes"][" < ".join(chain[::-1][:14])] += 1

    # ---- sites --------------------------------------------------------------
    luts = {lt["name"]: lt for lt in design.luts}
    ffs = {ff["name"]: ff for ff in design.ffs}
    dnet_to_lift = {}
    for name, (roots, _m) in net_roots.items():
        if len(roots) == 1:
            dnet_to_lift[name] = design.net_name.get(next(iter(roots)))
    net_by_name = {n["name"]: n for n in O["nets"]}
    site_count = Counter(c["type"] for c in O["comps"])
    for comp in O["comps"]:
        if comp["type"] != "SLICE":
            continue
        ms = re.match(r"^R(\d+)C(\d+)([A-D])$", comp["site"] or "")
        r, c, sl = int(ms.group(1)), int(ms.group(2)), ms.group(3)
        si = "ABCD".index(sl)
        f = P.config_fields(comp["config"])
        tenum = pc.enums.get((r, c), {})
        fields = []

        def fld(name, verdict, diamond, ours):
            fields.append({"field": name, "verdict": verdict,
                           "diamond": diamond, "pluribus": ours})

        # several tiles share a position (PLC2 + TAP_DRIVE): pc.tile_type keeps the last one
        if "PLC2" not in C.tile_types(r, c):
            fld("tile", "MISMATCH", comp["site"], C.tile_types(r, c))
            res["sites"].append({"comp": comp["name"], "site": comp["site"], "fields": fields})
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

        mode = f.get("MODE", "LOGIC")
        enum_cmp("MODE", f"SLICE{sl}.MODE", mode)
        has_ff = any(f.get(f"REG{j}", "#OFF") != "#OFF" for j in (0, 1))
        if has_ff:
            enum_cmp("GSR", f"SLICE{sl}.GSR", f.get("GSR", "DISABLED"))
            enum_cmp("CEMUX", f"SLICE{sl}.CEMUX", f.get("CEMUX", "1"))

            def ctrl_src(mux):
                s = [a[3] for a in pc.arcs if (a[0], a[1], a[2]) == (r, c, f"{mux}{si}")]
                return s[0] if len(s) == 1 else None
            cs = ctrl_src("MUXCLK")
            if cs is None:
                fld("CLKMUX", "ORACLE_ONLY", f.get("CLKMUX"), "no MUXCLK arc in .config")
            else:
                enum_cmp("CLKMUX", f"{cs}.CLKMUX", f.get("CLKMUX", "CLK"))
            ls = ctrl_src("MUXLSR")
            if ls is None and comp["pins"].get("LSR") is None:
                fld("SRMODE", "NOT_COMPARED", f.get("SRMODE"), "LSR unused: no mux arc to read")
            elif ls is None:
                fld("SRMODE", "ORACLE_ONLY", f.get("SRMODE"), "no MUXLSR arc in .config")
            else:
                enum_cmp("SRMODE", f"{ls}.SRMODE", f.get("SRMODE", "LSR_OVER_CE"))
                if f.get("LSRMUX") in ("LSR", "INV"):
                    enum_cmp("LSRMUX", f"{ls}.LSRMUX", f["LSRMUX"])
        # LUTs
        ccu = re.match(r"^:S0=0x([0-9a-fA-F]+),S1=0x([0-9a-fA-F]+)", f.get("CCU2", ""))
        ram = mode in ("DPRAM", "RAMW")
        for k in (0, 1):
            dec = pc.lut_init.get((r, c, sl, str(k)))
            if ram:
                fld(f"K{k}.INIT", "NOT_COMPARED", "RAM contents", dec)
                continue
            if ccu:
                want = int(ccu.group(1 + k), 16)
            elif f.get(f"K{k}", "#OFF").startswith(f":H{k}="):
                want = lut_eval(f[f"K{k}"][len(f":H{k}="):])
            else:
                want = None
            if want is None:
                v = "MATCH" if dec is None or int(dec, 2) == 0 else "LIFT_ONLY"
                fld(f"K{k}.INIT", v, "#OFF", dec)
                continue
            got = int(dec, 2) if dec is not None else LUT_INIT_DEFAULT
            fld(f"K{k}.INIT", "MATCH" if got == want else "MISMATCH",
                f"0x{want:04X}", f"0x{got:04X}" + ("" if dec is not None else " (default)"))
            if not ccu and want not in (0, 0xFFFF):
                lt = luts.get(f"lut_r{r}c{c}_{sl}k{k}")
                fld(f"K{k}.lift", "LIFT_MISSING" if lt is None else
                    ("MATCH" if int(lt["init"], 2) == want else "MISMATCH"),
                    f"0x{want:04X}", None if lt is None else f"0x{int(lt['init'], 2):04X}")
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
            else:
                fld(f"FF{j}.lift.regset", "MATCH" if ff["regset"] == regset else "MISMATCH",
                    regset, ff["regset"])
                fld(f"FF{j}.lift.sd", "MATCH" if ff["sd"] == sd else "MISMATCH", sd, ff["sd"])
                fld(f"FF{j}.lift.gsr", "MATCH" if ff["gsr"] == f.get("GSR") else "MISMATCH",
                    f.get("GSR"), ff["gsr"])
                for pin, key, const in (("CE", "ce", "1'b1"), ("LSR", "lsr", "1'b0")):
                    dnet = comp["pins"].get(pin)
                    ours = ff[key]
                    if dnet is None:
                        v = "MATCH" if ours == const else "LIFT_ONLY"
                    elif dnet not in dnet_to_lift:
                        v = "ORACLE_ONLY"
                    else:
                        v = "MATCH" if dnet_to_lift[dnet] == ours else "MISMATCH"
                    fld(f"FF{j}.lift.{key}", v, dnet, ours)
            # ---- register clock: the metric this oracle exists for ----------
            dnet = comp["pins"].get("CLK")
            leaf = f"R{r}C{c}_CLK{si}_SLICE"
            rec = {"comp": comp["name"], "reg": j, "net": dnet, "tile": f"R{r}C{c}",
                   "lift_clk": None if ff is None else ff["clk"]}
            if dnet is None or (dnet, leaf) not in conn_of:
                v, why = "ORACLE_ONLY", "clock_pin_not_on_a_routed_net"
            elif ff is None:
                v, why = "LIFT_MISSING", "register_not_lifted"
            else:
                cv, cwhy = conn_of[(dnet, leaf)]
                if cv == "MATCH" and ff["clk"] != "1'b0":
                    v, why = "MATCH", "driver_to_clk_pin_connected"
                elif ff["clk"] == "1'b0":
                    v, why = "LIFT_MISSING", f"clk_resolved_to_constant({cwhy})"
                elif cv == "MATCH":
                    v, why = "MISMATCH", "ff_clk_net_differs_from_dsu_class"
                else:
                    v, why = "MISMATCH", f"clk_net_not_connected_to_driver({cwhy})"
            # clock path, leaf side up: per arc and per join, what the lift keeps
            if dnet is not None and (dnet, leaf) in conn_of:
                parent, _r, _l = net_tree[dnet]
                path, w = [], leaf
                while w in parent:
                    path.append((parent[w], w))
                    w = parent[w]
                brk, seen_f, seen_b = [], set(), set()
                prev = None
                for (pa, pb) in path:
                    fam = family(pa, pb)
                    why2 = arc_reason(pa, pb)
                    res["clock_family"][fam]["arcs_on_register_paths"] += 1
                    if fam not in seen_f:
                        seen_f.add(fam)
                        res["clock_family"][fam]["registers_through"] += 1
                    if why2 != "ok":
                        res["clock_family"][fam]["arc_" + why2] += 1
                        brk.append(f"{fam}:{why2}")
                        if (fam, why2) not in seen_b:
                            seen_b.add((fam, why2))
                            res["clock_family"][fam]["registers_broken_" + why2] += 1
                    if prev is not None:
                        jk = join_reason((pa, pb), prev)     # upstream arc, downstream arc
                        if jk != "ok":
                            jf = f"{fam} | {family(*prev)}"
                            res["clock_join"][jf][jk] += 1
                            brk.append(f"join {jf}:{jk}")
                    prev = (pa, pb)
                rec["broken_arcs"] = brk
            rec["verdict"], rec["why"] = v, why
            if dnet is not None and (dnet, leaf) in conn_of:
                pf = set()
                for pa, pb in path:
                    pf.update(gfams(P.split_wire(pa)[2]) + gfams(P.split_wire(pb)[2]))
                for fk in pf:
                    res["global_regclk"][fk]["through"] += 1
                    res["global_regclk"][fk]["broken"] += v != "MATCH"
            res["regclk"].append(rec)
            res["regclk_verdicts"][v] += 1
            fld(f"FF{j}.regclk", v, dnet, rec["lift_clk"])
        res["sites"].append({"comp": comp["name"], "site": comp["site"], "fields": fields})

    # ---- roll-up ------------------------------------------------------------
    fc = Counter()
    for s in res["sites"]:
        for fd in s["fields"]:
            fc[f"{re.sub(r'[01]', '#', fd['field'])}:{fd['verdict']}"] += 1
    res["site_field_verdicts"] = dict(fc)
    res["comp_types"] = dict(site_count)
    for k in ("pips", "net_verdicts", "conns", "regclk_verdicts", "normalisation",
              "wire_classes_missing", "clock_shapes"):
        res[k] = dict(res[k])
    for k in ("pip_detail", "conn_detail", "clock_family", "clock_join", "lift_global_drop",
          "global_regclk"):
        res[k] = {kk: dict(v) for kk, v in res[k].items()}
    res["lift"] = {"luts": len(design.luts), "ffs": len(design.ffs),
                   "nets": len(design.all_nets), "config_arcs": len(pc.arcs),
                   "skipped_arcs": design.skipped_arcs}
    tmp = os.path.join(od, "compare.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True, default=list)
    os.replace(tmp, os.path.join(od, "compare.json"))
    return res


def cached(target, out_root):
    """compare.json of this schema newer than the oracle (and the Diamond NCD): reuse."""
    od = os.path.join(out_root, target)
    cj, oj = os.path.join(od, "compare.json"), os.path.join(od, "oracle.json")
    if not os.path.exists(cj) or os.path.getmtime(cj) < os.path.getmtime(oj):
        return None
    try:
        with open(cj) as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        return None
    return r if r.get("schema_version") == SCHEMA_VERSION else None


SUMMARY_KEYS = ("pips", "net_verdicts", "conns", "regclk_verdicts",
                "site_field_verdicts", "normalisation", "wire_classes_missing",
                "clock_shapes", "comp_types")


def headline(summ):
    """Per category: matched / (matched + every non-MATCH), raw fault count, and
    the per-verdict split.  NOT_COMPARED site fields are reported, not scored."""
    out = {}
    for cat, key in (("pips", "pips"), ("nets", "net_verdicts"),
                     ("connections", "conns"), ("register clocks", "regclk_verdicts")):
        d = summ.get(key, {})
        tot = sum(d.values())
        m = d.get("MATCH", 0)
        out[cat] = {"matched": m, "total": tot, "rate_pct": round(100.0 * m / tot, 1) if tot else None,
                    "faults": tot - m, "by_verdict": dict(sorted(d.items()))}
    groups = defaultdict(Counter)
    notcmp = Counter()
    for k, n in summ.get("site_field_verdicts", {}).items():
        field, _, v = k.rpartition(":")
        if field.endswith("regclk"):
            continue
        if v == "NOT_COMPARED":
            notcmp[field] += n
            continue
        if field.startswith("K#.INIT") or field == "K#.lift":
            g = "LUT INIT"
        elif field.startswith("FF#.lift"):
            g = "lifted FF " + field.split(".")[-1]
        elif field.startswith("REG#"):
            g = "register config " + field.split(".")[-1]
        else:
            g = "slice " + field
        groups[g][v] += n
    sites = Counter()
    for g, d in groups.items():
        sites.update(d)
    tot = sum(sites.values())
    out["sites"] = {"matched": sites.get("MATCH", 0), "total": tot,
                    "rate_pct": round(100.0 * sites.get("MATCH", 0) / tot, 1) if tot else None,
                    "faults": tot - sites.get("MATCH", 0), "by_verdict": dict(sorted(sites.items())),
                    "not_compared": dict(notcmp),
                    "by_field": {g: dict(sorted(d.items())) for g, d in sorted(groups.items())}}
    return out


@heavy_guard.locked("ecp5_oracle_compare")
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true",
                    help="recompute the headline from _compare_summary.json and print it")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--device", help="only targets whose device contains this (12F, 25F, ...): "
                    "one device per process keeps RSS bounded; a final run without --force re-aggregates")
    ap.add_argument("--force", action="store_true", help="recompute even if compare.json is current")
    args = ap.parse_args()
    root = os.path.abspath(args.data_root or data_root())
    args.out = os.path.abspath(args.out or os.path.join(root, "corpus", "ecp5", "diamond-oracle"))
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    if args.report:
        sp = os.path.join(args.out, "_compare_summary.json")
        with open(sp) as fh:
            summ = json.load(fh)
        summ["headline"] = headline(summ)
        with open(sp, "w") as fh:
            json.dump(summ, fh, indent=1)
        print(json.dumps(summ["headline"], indent=1))
        return
    targets = args.only or sorted(
        t for t in os.listdir(args.out)
        if os.path.exists(os.path.join(args.out, t, "oracle.json")))
    # one device at a time per worker keeps ECP5Lift instances few: group by device
    dev_of = {}
    for t in targets:
        with open(os.path.join(args.out, t, "oracle.json")) as fh:
            dev_of[t] = json.load(fh)["device"]
    if args.device:
        targets = [t for t in targets if args.device in dev_of[t]]
    targets.sort(key=lambda t: (dev_of[t], t))
    log(f"[compare] {len(targets)} targets, {args.workers} workers, out={args.out}")
    q = queue.Queue()
    for t in targets:
        q.put(t)
    results, lock, stop = [], threading.Lock(), threading.Event()
    lock85 = threading.Lock()

    def worker():
        last = 0.0
        while True:
            try:
                t = q.get_nowait()
            except queue.Empty:
                return
            if heavy_guard.available_gb() < heavy_guard.MIN_AVAILABLE_GB:
                _tls.__dict__.pop("c", None)    # idle workers must not hold the memory they wait on
            heavy_guard.wait_available(_GuardLog, f"compare {t}")
            try:
                r = None if args.force else cached(t, args.out)
                if r is None:
                    if dev_of[t].endswith("85F"):
                        with lock85:        # 85F lifts run one at a time (coordinator)
                            r = compare_target(t, args.out)
                    else:
                        r = compare_target(t, args.out)
                r = {"target": t, "status": "ok", "device": r["device"],
                     **{k: r[k] for k in SUMMARY_KEYS + (
                         "pip_detail", "conn_detail", "clock_family", "clock_join",
                         "lift_global_drop", "global_nets", "global_regclk")}}
            except (Exception, SystemExit) as e:  # noqa: BLE001 -- db.die() exits; recorded per target
                r = {"target": t, "status": "failed", "error": f"{type(e).__name__}: {e}"}
                log(f"[fail] {t}: {r['error']}")
            with lock:
                results.append(r)
                if len(results) % 25 == 0:
                    log(f"[compare] {len(results)}/{len(targets)}")

    t0 = time.monotonic()
    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()

    summ = {"targets": len(results),
            "status": dict(Counter(r["status"] for r in results)),
            "failed": sorted((r["target"], r["error"]) for r in results
                             if r["status"] == "failed")}
    ok = [r for r in results if r["status"] == "ok"]
    for key in SUMMARY_KEYS:
        acc = Counter()
        for r in ok:
            acc.update(r.get(key, {}))
        summ[key] = dict(sorted(acc.items()))
    for key in ("pip_detail", "conn_detail", "clock_family", "clock_join", "lift_global_drop",
                "global_nets", "global_regclk"):
        det = defaultdict(Counter)
        for r in ok:
            for k, v in r.get(key, {}).items():
                det[k].update(v)
        summ[key] = {k: dict(v.most_common(60)) for k, v in sorted(det.items())}
    by = defaultdict(list)
    for r in ok:
        for key in ("net_verdicts", "regclk_verdicts", "conns"):
            for k in r.get(key, {}):
                if k != "MATCH":
                    by[f"{key}/{k}"].append(r["target"])
    summ["example_targets"] = {k: sorted(v)[:15] for k, v in sorted(by.items())}
    summ["headline"] = headline(summ)
    with open(os.path.join(args.out, "_compare_summary.json"), "w") as fh:
        json.dump(summ, fh, indent=1)
    for cat, h in summ["headline"].items():
        log(f"[compare] HEADLINE {cat}: {h['matched']} / {h['total']} matched "
            f"({h['rate_pct']}%), {h['faults']} faults {h['by_verdict']}")
    for key in ("global_nets", "global_regclk"):
        for k, v in summ[key].items():
            log(f"[compare] {key} {k}: {v}")
    log(f"[compare] done in {time.monotonic() - t0:.1f}s: {summ['status']}")
    for key in ("pips", "net_verdicts", "conns", "regclk_verdicts", "site_field_verdicts"):
        log(f"[compare] {key}: {summ[key]}")


if __name__ == "__main__":
    main()
