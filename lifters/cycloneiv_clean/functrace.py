"""Generic hard-block functional-trace core over a recovered `emit.Netlist` (#165, #177, #179).

Not a new decoder: read-only on the netlist patterns.py/emit.py already produced. Two pieces:
  (a) a signal-graph walk that, from any named pin of any instance (hard block or fabric), finds the
      ULTIMATE source (walking backward through FF stages and LAB-logic cones) or every ultimate sink
      (walking forward through the same), classifying each endpoint by KIND: const, pad, a named
      hard-block instance of some TYPE, or plain fabric logic (handed to patterns.py's own detectors,
      never re-classified here);
  (b) a chain-detection pass: given a TypeSpec naming one hard-block type's instance list and its named
      pins, find which instances connect operand<-output directly (no fabric logic between) or through
      one hop of fabric logic (adder/accumulator stage) and report connected components.

Reuses patterns.Design for every leaf/cone primitive (comb/support/fan/leaf-kind): this module adds
hard-block pin access and multi-hop forward/backward walking on top, it does not reimplement LUT-cone
algebra. scripts/cycloneiv_clean_spi_trace.py's `Net` class and scripts/cycloneiv_clean_af3_engine.py's
`cone()` each hand-built a narrower version of the same walk for one specific block (the SPI shift
register, the AF3 engine's FF domain) before this module existed; this is the shared shape extracted
from both, generalised over "any named pin of any instance", not a MAC-specific tool.

Cyclone-IV-specific by construction (see docs/altera/cycloneIV/cycloneiv-clean-mac-trace.md "Cross-family
scoping" for what would need to change for ECP5/MachXO2/Gowin/Cyclone V): the KIND vocabulary is this
family's `emit.py` signal-name convention (lc_/ff_/co_/pad_/m9k_/mac_/u_, patterns.LEAF_PREFIX) and the
TypeSpec pin-name lists below (MAC DATAA/DATAB, M9K addr/data) are this family's control-decode field
names. No Cyclone-IV pin name is hardcoded in the walk CORE (`trace_source`/`trace_sinks`/`chain_groups`)
itself — only in the TYPE_SPECS table a caller passes in; a future family only needs its own TypeSpec
and, if its Netlist shape differs from emit.py's (list-of-dict luts/ffs/ios + typed hard-block lists),
a thin adapter producing that shape (see the doc section for why this is NOT merely a new dict today).
"""
import collections

from . import patterns as PT

CONSTV = PT.CONSTV
LEAF_PREFIX = PT.LEAF_PREFIX


def _strip_inv(s):
    """emit.py wraps an inverted control pin as '(~sig)' (string, not a netlist node): unwrap for
    classification. The inversion itself is a fact about the EDGE, not the source, so it is dropped
    here; callers that need polarity read it from the original field before calling into functrace."""
    if s is None:
        return s
    s = s.strip()
    if s.startswith("(~") and s.endswith(")"):
        return s[2:-1]
    if s.startswith("~"):
        return s[1:]
    return s


class TypeSpec:
    """Describes one hard-block type's instance list and named pins, generically over `nl.<attr>`.

    `pins`: {pin_name: "scalar" | "list"} — scalar pins read `inst[pin_name]` (a signal-name string or
    None); list pins read `inst[pin_name]` (a list of signal-name strings, e.g. MAC `a`/`b` operand buses
    or M9K `addr`/`data` buses). `out_prefix`: the emit.py signal-name prefix this type's own output uses
    (e.g. "mac_" -> `mac_<x>_<y>_r[i]`, "m9k_" -> `m9k_<x>_<y>_o[i]`) so the forward walk and the
    same-type chain test can recognise "this signal IS one of this type's own outputs", not just any
    m9k_/mac_ leaf.
    """
    def __init__(self, name, list_attr, pins, out_prefix, id_fn, modelled_fn=None):
        self.name, self.list_attr, self.pins, self.out_prefix = name, list_attr, pins, out_prefix
        self.id_fn = id_fn                                  # inst -> hashable id (e.g. (x, y) or (x, y, inst))
        self.modelled_fn = modelled_fn or (lambda inst: True)

    def instances(self, nl):
        return [m for m in getattr(nl, self.list_attr) if self.modelled_fn(m)]

    def operand_signals(self, inst):
        """[(pin_name, index_or_None, signal)] of every operand/control pin actually wired (skips None)."""
        out = []
        for name, kind in self.pins.items():
            v = inst.get(name)
            if v is None:
                continue
            if kind == "list":
                for i, s in enumerate(v):
                    s = _strip_inv(s)
                    if s is not None and s not in ("",):
                        out.append((name, i, s))
            else:
                s = _strip_inv(v)
                if s is not None and s not in ("",):
                    out.append((name, None, s))
        return out


# source: lifters/cycloneiv_clean/emit.py Builder._mac / Builder._hard (field names written there, read-only here)
MAC_SPEC = TypeSpec(
    "mac", "mac",
    pins={"a": "list", "b": "list", "sign": "list", "clk": "scalar", "ena": "scalar", "aclr": "scalar"},
    out_prefix="mac_", id_fn=lambda m: (m["x"], m["y"]),
)
# source: emit.py Builder._m9k / _m9k_tdp / _close (the field set _close itself scans for dangling refs)
M9K_SPEC = TypeSpec(
    "m9k", "m9k",
    pins={"addr": "list", "data": "list", "we": "scalar", "clk": "scalar", "be": "list",
          "raddr": "list", "data_b": "list", "addr_b": "list", "we_b": "scalar",
          "ce": "scalar", "ce_core": "scalar", "ce_b": "scalar", "ce_core_b": "scalar", "clk_b": "scalar", "clk_o": "scalar"},
    out_prefix="m9k_", id_fn=lambda m: (m["x"], m["y"]), modelled_fn=lambda m: m.get("modelled"),
)
TYPE_SPECS = {"mac": MAC_SPEC, "m9k": M9K_SPEC}


def _leaf_kind(design, sig):
    """(kind, detail) of a leaf signal (one patterns.Design.comb()/support() already stopped at): const /
    pad / a hard-block output (m9k/mac, with (x, y) and bit index when the name encodes one) / ff / src."""
    if sig in CONSTV:
        return ("const", CONSTV[sig])
    pfx = sig.split("_", 1)[0]
    kind = LEAF_PREFIX.get(pfx, "other")
    if kind == "pad":
        return ("pad", sig[4:])
    if kind in ("m9k", "mac"):
        # m9k_<x>_<y>_o[<i>] / mac_<x>_<y>_r[<i>]
        try:
            rest = sig[len(kind) + 1:]
            xy, idx = rest.split("_o[") if kind == "m9k" else rest.split("_r[")
            x, y = xy.split("_")
            return (kind, (int(x), int(y), int(idx.rstrip("]"))))
        except Exception:
            return (kind, sig)
    if kind == "ff":
        return ("ff", sig)
    return ("src", sig)


def trace_source(design, sig, ff_hops=64):
    """Walk `sig` backward through LAB-logic cones and (up to `ff_hops`) FF stages to its ultimate
    source(s). Returns a dict: kind in {const, pad, m9k, mac, lab_logic, ff_untraced, mixed}, and:
      - const/pad/m9k/mac: `detail` (value / ball / (x,y,bit)), `hops` (FF stages crossed)
      - lab_logic: the cone did not resolve to a single hard-block/pad/const leaf within `ff_hops` FF
        stages (e.g. an adder/counter feeds it) — `leaves` names every leaf reached, for the caller to
        hand to patterns.py's own detectors (this module does not re-run them)
      - ff_untraced: hit the hop limit still inside FF stages
    `sig` itself may be a hard-block output name (e.g. starting a trace FROM a MAC's own output).
    """
    if sig in CONSTV:
        return dict(kind="const", detail=CONSTV[sig], hops=0)
    k0, d0 = _leaf_kind(design, sig)
    if k0 in ("pad", "m9k", "mac"):
        return dict(kind=k0, detail=d0, hops=0)
    leaves = design.support(sig, hops=0)
    resolved, hops = set(), 0
    cur = leaves
    while True:
        kinds = {_leaf_kind(design, s)[0] for s in cur}
        non_ff = {s for s in cur if _leaf_kind(design, s)[0] != "ff"}
        if kinds <= {"const"}:
            return dict(kind="const", detail=0, hops=hops)
        if len(non_ff) == len(cur) or hops >= ff_hops:
            break
        hops += 1
        nxt = set(non_ff)
        for s in cur - non_ff:
            F = design.ff.get(s)
            if F is None or F.get("d") is None:
                nxt.add(s)
                continue
            nxt |= design.support(F["d"], 0)
        cur = nxt
    useful = {s for s in cur if _leaf_kind(design, s)[0] not in ("const",)}
    if len(useful) == 1:
        s = next(iter(useful))
        k, d = _leaf_kind(design, s)
        if k in ("pad", "m9k", "mac"):
            return dict(kind=k, detail=d, hops=hops)
        if k == "ff":
            return dict(kind="ff_untraced", detail=s, hops=hops)
    kinds = {_leaf_kind(design, s)[0] for s in useful}
    if kinds and kinds <= {"ff"}:
        return dict(kind="ff_untraced", detail=sorted(useful), hops=hops)
    # mixed cone (the common real case: a word-select mux picks one M9K/MAC output bit among other
    # FF/LUT leaves, e.g. address/select bits) -- report lab_logic with WHICH hard-block kinds appear
    # in the cone (has_m9k / has_mac), the same test patterns.mac_roms() already uses via
    # Design.support(leaf, hops=1): "any leaf starts with m9k_/mac_", not "the cone IS purely one".
    leaf_kinds = {s: _leaf_kind(design, s)[0] for s in useful}
    return dict(kind="lab_logic", leaves=sorted(useful), hops=hops,
                has_m9k=sorted({s for s, k in leaf_kinds.items() if k == "m9k"}),
                has_mac=sorted({s for s, k in leaf_kinds.items() if k == "mac"}))


def _build_fanout(nl):
    """signal name -> [(kind, instance_id_or_name, pin_name, index)] of every consumer (lut pin, FF
    control, IO driver/oe, M9K operand, MAC operand). Built once per Design for the forward walk."""
    fanout = collections.defaultdict(list)
    for L in nl.luts:
        for i, p in enumerate(L["pins"]):
            if p:
                fanout[p].append(("lc", L["name"], "pins", i))
    for F in nl.ffs:
        for k in ("d", "clk", "ena", "aclr", "sclr", "sload", "asdata"):
            s = F.get(k)
            if s:
                fanout[s].append(("ff", F["name"], k, None))
    for io in nl.ios:
        for k in ("drv", "oe"):
            s = io.get(k)
            if s:
                fanout[s].append(("io", io.get("ball"), k, None))
    for spec in TYPE_SPECS.values():
        for inst in spec.instances(nl):
            iid = spec.id_fn(inst)
            for name, idx, s in spec.operand_signals(inst):
                fanout[s].append((spec.name, iid, name, idx))
    return fanout


def trace_sinks(design, fanout, sig, ff_hops=64):
    """Walk every consumer of `sig` forward through LAB-logic (LUT pins feeding only a buffer/inverter
    whose own output has no further fabric use beyond one more LUT is still 'lab_logic' here; this
    module does not try to re-detect adders going forward, only report who ultimately reads the value)
    and FF stages, to each ultimate sink. Returns a list of dicts like trace_source's, plus `kind` may
    also be `unused` (no consumer at all)."""
    seen, out, cur = set(), [], [(sig, 0)]
    while cur:
        s, hops = cur.pop()
        if s in seen:
            continue
        seen.add(s)
        cons = fanout.get(s, [])
        if not cons:
            if s != sig:
                out.append(dict(kind="dead_end", detail=s, hops=hops))
            continue
        for kind, iid, pin, idx in cons:
            if kind in TYPE_SPECS:
                out.append(dict(kind=kind, detail=iid, pin=pin, index=idx, hops=hops))
            elif kind == "io":
                out.append(dict(kind="pad", detail=iid, hops=hops))
            elif kind == "ff":
                if hops >= ff_hops:
                    out.append(dict(kind="ff_untraced", detail=iid, hops=hops))
                else:
                    cur.append((f"ff_{iid[3:]}" if iid.startswith("ff_") else iid, hops))
                    # the FF's own output signal name is `iid` already (nl.ffs name == "ff_x_y_le")
                    cur[-1] = (iid, hops + 1)
            else:   # "lc": a LUT pin reads this signal; follow the LUT's own output forward too
                lut_out = iid
                cur.append((lut_out, hops))
    if not out:
        out = [dict(kind="unused", detail=None, hops=0)]
    return out


def chain_groups(nl, spec, ff_hops=1):
    """Connected components of same-type instances linked operand<-output directly, or through <= one
    FF/LAB-logic hop (an adder/accumulator stage between two MAC outputs, e.g.). Returns
    (edges, groups): edges = [(src_id, dst_id, via)] where via is 'direct' or 'lab_logic'/'ff';
    groups = list of sorted-id lists (size >= 1; singletons are "no chain found")."""
    design = PT.Design(nl).prepare() if hasattr(PT.Design, "prepare") else _prepared(nl)
    insts = spec.instances(nl)
    by_id = {spec.id_fn(m): m for m in insts}
    edge_via = {}   # (src, dst) -> best via ("direct" beats "ff" beats "lab_logic"); one bit is enough
    VIA_RANK = {"direct": 2, "ff": 1, "lab_logic": 0}
    for inst in insts:
        dst = spec.id_fn(inst)
        for name, idx, s in spec.operand_signals(inst):
            if name == spec.out_prefix.rstrip("_"):
                continue
            tr = trace_source(design, s, ff_hops=ff_hops)
            if tr["kind"] == spec.name:
                src = (tr["detail"][0], tr["detail"][1]) if isinstance(tr["detail"], tuple) else tr["detail"]
                if src in by_id and src != dst:
                    via = "direct" if tr["hops"] == 0 else "ff"
                    k = (src, dst)
                    if VIA_RANK[via] > VIA_RANK.get(edge_via.get(k), -1):
                        edge_via[k] = via
            elif tr["kind"] == "lab_logic":
                hits = {l for l in tr["leaves"] if _leaf_kind(design, l)[0] == spec.name}
                for l in hits:
                    _, d = _leaf_kind(design, l)
                    src = (d[0], d[1]) if isinstance(d, tuple) else d
                    if src in by_id and src != dst:
                        k = (src, dst)
                        if VIA_RANK["lab_logic"] > VIA_RANK.get(edge_via.get(k), -1):
                            edge_via[k] = "lab_logic"
    # one edge per connected (src, dst) pair, regardless of how many operand bits hit it -- an edge
    # is "this instance connects to that one", not "N of its data bits happen to come from it"
    edges = [(src, dst, via) for (src, dst), via in edge_via.items()]
    uf = {i: i for i in by_id}

    def find(x):
        while uf[x] != x:
            x = uf[x]
        return x
    for a, b, _via in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            uf[ra] = rb
    comp = collections.defaultdict(list)
    for i in by_id:
        comp[find(i)].append(i)
    groups = sorted((sorted(v) for v in comp.values()), key=lambda g: (-len(g), g))
    return edges, groups


def _prepared(nl):
    """patterns.Design has no public prepare(); build the SCC/affine caches a plain Design() skips.
    functrace only needs comb()/support()/fan/ff/lut, all available unprepared, so this is a no-op
    fallback kept for forward compatibility if prepare() is added later."""
    return PT.Design(nl)
