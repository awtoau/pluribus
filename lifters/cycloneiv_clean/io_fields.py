"""Cyclone IV GX per-site IO field decode: site CFF / CRAM bits -> direction, standard, drive, slew, pull, termination (#168).

Tables only: io_decode.json (`values` pair-build patterns, `unused` states, `cram_values`, `open_drain`) read through `Decoder`; the group widths and
the value <-> pattern law come from the vendor select code (io_encode.py).  A site whose bits equal no table state is MISSING with its raw
patterns; a field two states disagree on is `ambiguous` with every candidate listed; nothing is guessed.

Classes of a site:  fixed (device-fixed pad, pattern equal to every unused-pin build) | unused (equal to one or more RESERVE_ALL_UNUSED_PINS
states) | used (matches pair-build states) | MISSING.
"""
import collections

from . import io_decode as D

# source: io_decode.json default rows: the groups whose patterns change with standard / drive / direction (pair builds, docs/cycloneiv-clean-io.md)
JOINT = ("MIO_SELECT_IOST_DIRT", "MIO_SET_PULLDOWN_STRENGTH", "MIO_SET_PULLUP_STRENGTH", "MIO_USE_PCI_DIODE_CLAMP")     # one state per (standard, drive, direction)
# source: scripts/cycloneiv_clean_io_pairs.py KINDS (pair-build design kinds): CFF-identical kinds share a direction word
DIRECTION = {"in": "input", "regin": "input", "out": "output", "regout": "output", "bidir": "bidir-or-tristate", "tri": "bidir-or-tristate",
             "regoe": "bidir-or-tristate"}
BASE_STD = "2.5 V"          # source: scripts/cycloneiv_clean_io_pairs.py BASE_STD (named in every build)
STD_ROWS = ("standard", "drive", "termination")      # settings that change JOINT groups; slew / pull-up / bus-hold / open-drain are independent groups


def _w(pat):
    return len(pat)


class Decoder:
    def __init__(self, table):
        self.t = table
        dflt = collections.defaultdict(lambda: collections.defaultdict(dict))            # kind -> iost width -> {name: pattern}
        rows = collections.defaultdict(list)
        for v in table["values"]:
            if v["setting"] == "default":
                if v["group"] == "MIO_SELECT_IOST_DIRT":
                    for w in (3, 4):
                        if v["n_elem"] == w:
                            dflt[v["base_kind"]][w][v["group"]] = v["pattern"]
                else:
                    for w in (3, 4):
                        dflt[v["base_kind"]][w][v["group"]] = v["pattern"]
            else:
                rows[(v["setting"], v["value"], v["base_kind"])].append(v)
        self.default = dflt
        self.rows = rows
        self.states = []            # used states: {labels, kind, width, vec(JOINT)}
        for kind, byw in dflt.items():
            for w, vec in byw.items():
                if "MIO_SELECT_IOST_DIRT" in vec:
                    self.states.append({"labels": {"standard": BASE_STD, "drive": "default", "termination": "none"}, "kind": kind, "width": w,
                                        "vec": {g: vec[g] for g in JOINT}, "src": f"default.{kind}"})
        for (st, val, kind), rs in rows.items():
            if st not in STD_ROWS:
                continue
            for w in (3, 4):
                base = dflt.get(kind, {}).get(w)
                if not base:
                    continue
                vec = dict(base)
                for r in rs:
                    if r["group"] == "MIO_SELECT_IOST_DIRT" and r["n_elem"] != w:
                        continue
                    vec[r["group"]] = r["pattern"]
                if len(vec.get("MIO_SELECT_IOST_DIRT", "")) != w:
                    continue
                lab = {"standard": BASE_STD, "drive": "default", "termination": "none"}
                lab[st] = val
                self.states.append({"labels": lab, "kind": kind, "width": w, "vec": {g: vec[g] for g in JOINT}, "src": f"{st}={val}.{kind}"})
        self.slew = collections.defaultdict(set)
        for (st, val, kind), rs in rows.items():
            if st == "slew":
                for r in rs:
                    if r["primary"]:
                        self.slew[r["pattern"]].add(val)
        self.bool_on = {st: {r["pattern"] for (s2, _, _), rs in rows.items() if s2 == st for r in rs if r["primary"]} for st in ("pull-up", "bus-hold")}
        self.bool_off = {st: {v["pattern"] for v in table["values"] if v["setting"] == "default" and v["group"] == g}
                         for st, g in (("pull-up", "MIO_USE_PULL_UP"), ("bus-hold", "MIO_USE_BUS_HOLD"))}
        od = table.get("open_drain") or []
        self.od_on = {o["pin_mode_pattern"]["od"] for o in od}
        self.od_off = {o["pin_mode_pattern"]["out"] for o in od}
        self.unused = table.get("unused", {}).get("states", [])
        self.fixed = {tuple(map(int, k.split("."))): v["vector"] for k, v in table.get("unused", {}).get("fixed", {}).items()}
        self.cram = collections.defaultdict(lambda: collections.defaultdict(lambda: {"base": set(), "spec": set()}))
        for e in table.get("cram_values", []):
            self.cram[e["setting"]][e["group"]][e["role"]].update(e["patterns"])
        # every standard built per direction word (the candidates a matching state can exclude or not)
        self.std_built = collections.defaultdict(set)
        for (st, val, kind) in rows:
            if st == "standard":
                self.std_built[kind].add(val)
        for kind in dflt:
            self.std_built[kind].add(BASE_STD)
        self.iost_of = collections.defaultdict(set)         # standard -> IOST patterns it produced (any kind)
        for (st, val, kind), rs in rows.items():
            if st == "standard":
                self.iost_of[val].update(r["pattern"] for r in rs if r["group"] == "MIO_SELECT_IOST_DIRT")
        self.iost_of[BASE_STD].update(v["pattern"] for v in table["values"] if v["setting"] == "default" and v["group"] == "MIO_SELECT_IOST_DIRT")

    def _field(self, cands, default_label=None):
        c = sorted(cands)
        if len(c) == 1:
            return {"status": "default" if c[0] == default_label else "decoded", "value": c[0]}
        return {"status": "ambiguous_MISSING", "candidates": c}

    def meaning(self, site, vec):
        """Integer values of the IOST / strength groups (io_encode law) and the dirt-table entries that carry them (io_dirt): data, not a decode claim."""
        from . import io_dirt as T
        from . import io_encode as E
        blk = {5: "HIO", 6: "VIO"}.get(site[0])
        tb = T.tables()
        out = {}
        iost = vec.get("MIO_SELECT_IOST_DIRT")
        if iost:
            v = E.value_of(iost)
            out["iost_value"] = v
            out["iost_dirt_standards"] = sorted(k for k, x in tb[("MIO_SELECT_IOST_DIRT", blk)] if x == v)
        for g, key in (("MIO_SET_PULLDOWN_STRENGTH", "pulldown_value"), ("MIO_SET_PULLUP_STRENGTH", "pullup_value")):
            if vec.get(g):
                v = E.value_of(vec[g])
                out[key] = v
                out[key + "_dirt_levels"] = sorted(k for k, x in tb[(g, blk)] if x == v)
        return out

    def decode(self, site, vec, cram=None):
        """vec = {group name: pattern string} of the site's CFF groups; cram = {group name: pattern} of its CRAM groups (or None)."""
        out = {"site": list(site), "raw": dict(vec)}
        try:
            out["meaning"] = self.meaning(site, vec)
        except (FileNotFoundError, KeyError):
            pass
        w = len(vec.get("MIO_SELECT_IOST_DIRT", ""))
        state = {k: vec[k] for k in D.STATE_NAMES if k in vec}          # groups outside the state vector (duty cycle, PLL select, ...) are zero in every build
        if site in self.fixed and self.fixed[site] == state:
            out["class"] = "fixed"
            return out
        un = [u for u in self.unused if u["iost_width"] == w and u["vector"] == state]
        if un:
            out["class"] = "unused"
            out["unused_options"] = sorted(u["option"] for u in un)
            out["unused_status"] = "decoded" if len(un) == 1 else "ambiguous_MISSING"
            return out
        joint = {g: vec.get(g) for g in JOINT}
        hits = [s for s in self.states if s["width"] == w and s["vec"] == joint]
        if not hits:
            out["class"] = "MISSING"
            out["why"] = "joint IOST / strength / clamp groups equal no pair-build or unused state"
            return out
        out["class"] = "used"
        kinds = sorted({s["kind"] for s in hits})
        dirs = sorted({DIRECTION[k] for k in kinds})
        out["direction"] = self._field(dirs)
        std = {s["labels"]["standard"] for s in hits}
        out["standard"] = self._field(std, BASE_STD)
        iost = vec.get("MIO_SELECT_IOST_DIRT")
        unbuilt = sorted(x for x in self.t_all_standards() - set().union(*(self.std_built[k] for k in kinds)) if iost in self.iost_of[x])
        if unbuilt:
            out["standard"]["unbuilt_for_kind"] = unbuilt
            if out["standard"]["status"] != "ambiguous_MISSING":
                out["standard"] = {"status": "ambiguous_MISSING", "candidates": sorted(std), "unbuilt_for_kind": unbuilt}
        out["drive"] = self._field({s["labels"]["drive"] for s in hits}, "default")
        out["termination"] = self._field({s["labels"]["termination"] for s in hits}, "none")
        sl = vec.get("MIO_SET_SLEW_RATE")
        v = self.slew.get(sl)
        if dirs == ["input"]:
            out["slew"] = {"status": "not_applicable_input", "pattern": sl}
        elif v:
            out["slew"] = {"status": "decoded", "value": sorted(v)[0] if len(v) == 1 else sorted(v), "pattern": sl}
        else:
            out["slew"] = {"status": "MISSING", "pattern": sl}
        for st, g in (("pull-up", "MIO_USE_PULL_UP"), ("bus-hold", "MIO_USE_BUS_HOLD")):
            p = vec.get(g)
            out[st] = {"status": "decoded", "value": "ON"} if p in self.bool_on[st] else \
                {"status": "default", "value": "OFF"} if p in self.bool_off[st] else {"status": "MISSING", "pattern": p}
        p = vec.get("MIO_PIN_MODE")
        out["open-drain"] = {"status": "decoded", "value": "ON"} if p in self.od_on else \
            {"status": "default", "value": "OFF"} if p in self.od_off else {"status": "MISSING", "pattern": p}
        if cram is not None:
            for st in ("registered-input", "registered-output", "registered-oe"):
                out[st] = self._reg(st, cram)
        return out

    def t_all_standards(self):
        return set().union(*self.std_built.values())

    def _reg(self, st, cram):
        gs = self.cram.get(st)
        if not gs:
            return {"status": "MISSING", "why": "no CRAM groups tabulated"}
        on = all(cram.get(g) in e["spec"] for g, e in gs.items())
        off = all(cram.get(g) in e["base"] for g, e in gs.items())
        if on and not off:
            return {"status": "decoded", "value": "ON"}
        if off and not on:
            return {"status": "decoded", "value": "OFF"}
        return {"status": "MISSING", "why": "CRAM groups equal both or neither of the tabulated patterns"}
