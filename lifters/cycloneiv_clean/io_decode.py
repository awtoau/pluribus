"""Cyclone IV GX IO field decode: asmdb group structure (track A) x pair-build labels (track B).  Vendor-derived only (#168).

A = asmdb_walk (group -> absolute CFF / CRAM addresses per IO site), pkgpad (ball -> pad -> site).
B = scripts/cycloneiv_clean_io_pairs.py builds (diff of one assignment = exact bit labels; absolute bits read from the same builds).
Nothing here is typed by hand except FIELD_GROUPS (vendor group-type names, source below); every table entry carries `source`.
"""
import collections
import json
import os
import sys

import numpy as np

from . import asmdb_walk as W
from . import io as IO
from . import pkgpad as K
from . import plane as P

DECODE_PATH = os.path.join(P.REPO, "databases", "cycloneiv", "io_decode.json")
BUILDS = os.path.join(P.REPO, "tmp", "cycloneiv_clean", "io_pairs", "builds")
CFF_TAG = 5                    # top bits of a CFF-tagged asm address (io.ADDRESS_SPACES: 0b101)
# source: asmdb group types of the IO blocks (reference/ghidra/structs.tsv serializers + libdb_asmdb enum tables) bound to the pair
# setting by the libcomp_asm process_atom decompiles (docs/cycloneiv-clean-io.md: pin mode, standard, pull / bus-hold, slew, drive)
FIELD_GROUPS = {
    "standard": ("MIO_SELECT_IOST_DIRT",),
    "drive": ("MIO_SET_PULLUP_STRENGTH", "MIO_SET_PULLDOWN_STRENGTH"),
    "slew": ("MIO_SET_SLEW_RATE",),
    "pull-up": ("MIO_USE_PULL_UP",),
    "bus-hold": ("MIO_USE_BUS_HOLD",),
    "termination": ("MIO_TERMINATION_CONTROL_SELECT",),
    "direction": ("MIO_PIN_MODE",),
    "open-drain": ("MIO_PIN_MODE",),
    "registered-input": (),
    "registered-output": (),
    "registered-oe": (),
}
ANCHOR_GROUP = "MIO_SET_SLEW_RATE"      # anchor = lowest CFF bit of this group at the site (20 / 20 equal to the pair `location` anchors)


class Chain:
    """Walk + pad chain: ball -> (block type, site); site -> {group name: [CFF addresses in mux element order]} (+ CRAM)."""

    def __init__(self):
        sys.path.insert(0, os.path.join(P.REPO, "scripts"))
        import cycloneiv_clean_dirt as D
        self.walk = W.Walk()
        self.names = D.enum_tables()["arch_group_type"]
        self.cff, self.cram, self.gid = {}, {}, {}
        for gi, o in enumerate(self.walk.groups()):
            if o["btype"] not in (5, 6) or o["cls"] not in (5, 6, 7):
                continue
            nm = self.names.get(o["type"], str(o["type"]))
            key = (o["btype"], nm)
            self.gid.setdefault(key, []).append(gi)       # walk group index (LABLINE types have several group objects)
            n = len(o["bits"]) if o["cls"] == 7 else len(o["paths"])
            for s in range(n):
                for a in W._site_bits(self.walk, o, s):
                    if a >> 29 == CFF_TAG:
                        self.cff.setdefault((o["btype"], s), {}).setdefault(nm, []).append(a & 0x1FFFFFFF)
                    elif a < 0x80000000:
                        self.cram.setdefault((o["btype"], s), {}).setdefault(nm, []).append(a)
        pins, pads = K.pins(), K.pads()
        rank = K.pin_pad_rank(pins)
        site_pad = K.io_site_pads(pads)
        pad_site = {j: s for s, j in site_pad.items()}
        self.ball_site = {pins[i]["strs"][0]: pad_site.get(j) for i, j in rank.items()}
        self.site_pad = {s: (pads[j]["strs"][1], pads[j]["strs"][4]) for s, j in site_pad.items()}      # (X..Y..SUB_LOC.., function)

    def anchor(self, site):
        return min(self.cff[site][ANCHOR_GROUP])

    def owner(self, bit):
        """[(site, group name)] of every IO site group holding this CFF bit."""
        return [(s, n) for s, g in self.cff.items() for n, bs in g.items() if bit in bs]


def _rows(pairs):
    return [r for r in pairs["rows"] if r["status"] == "ok"]


def cross_check(chain, pairs):
    """Per field: bit-level matched / missing / extra / wrong between A (group bits) and B (pair-diff bits), summed over sites.

    Per site and field: B = union of CFF diff bits over every row of that setting; A = union of the field's group bits.
    matched = B & A; missing = A - B (group bits no tried value toggled); extra = B - A, classed as `coupled` (another group of the
    same site), `foreign` (a group of another site) or `unowned`; wrong = 0 by construction (every B-only bit is counted extra).
    Sites without an A site (dedicated clock pads) count as unmapped.
    """
    out = {}
    own = {s: {b: n for n, bs in g.items() for b in bs} for s, g in chain.cff.items()}
    foreign = {}
    for r in _rows(pairs):
        s = chain.ball_site.get(r["pin"])
        out.setdefault(r["setting"], {"B": collections.defaultdict(set), "unmapped": set()})
        if s is None:
            out[r["setting"]]["unmapped"].add(r["pin"])
            continue
        out[r["setting"]]["B"][r["pin"]].update(r["cff"])
    res = {}
    for field, d in sorted(out.items()):
        c = collections.Counter(matched=0, missing=0, extra=0, wrong=0, extra_coupled=0, extra_foreign=0, extra_unowned=0)
        coupled, owners = collections.Counter(), {}
        for pin, B in d["B"].items():
            s = chain.ball_site[pin]
            A = {b for n in FIELD_GROUPS[field] for b in chain.cff[s].get(n, [])}
            c["matched"] += len(B & A)
            c["missing"] += len(A - B)
            for b in B - A:
                c["extra"] += 1
                if b in own[s]:
                    c["extra_coupled"] += 1
                    coupled[own[s][b]] += 1
                elif chain.owner(b):
                    c["extra_foreign"] += 1
                    foreign.setdefault((pin, s), set()).update(o[0] for o in chain.owner(b))
                else:
                    c["extra_unowned"] += 1
        tot = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
        res[field] = {**c, "sites": len(d["B"]), "unmapped_sites": sorted(d["unmapped"]),
                      "headline": f"{c['matched']} / {tot}" if tot else "0 / 0", "coupled_groups": dict(coupled)}
    res["_foreign_owner_sites"] = {f"{pin}": {"site": list(s), "owners": sorted(o)} for (pin, s), o in foreign.items()}
    return res


def _build(pairs, pin, bid):
    f = os.path.join(BUILDS, f"{pin}_{pairs['sample'][pin]['site']}", bid, "result.npz")
    return np.load(f) if os.path.exists(f) else None


def value_table(chain, pairs):
    """Decoded table: (setting, value, base kind) -> per CFF group the modal absolute bit pattern over sites (mux element order,
    element i = value bit i: slew 0 / 1 / 2 = 00 / 10 / 01).  Entries: primary groups of the field and every group whose pattern
    differs from the base build's; `default` rows = the base builds.  Each entry has `source` (pair build ids, walk group ids)."""
    cache = {}

    def cff(pin, bid):
        if (pin, bid) not in cache:
            z = _build(pairs, pin, bid)
            cache[(pin, bid)] = None if z is None else z["cff"]
        return cache[(pin, bid)]
    pat = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))      # key -> (group, n) -> pattern -> sites
    srcs = collections.defaultdict(set)
    for r in _rows(pairs):
        s = chain.ball_site.get(r["pin"])
        if s is None:
            continue
        for role, bid, key in (("spec", r["spec"], (r["setting"], r["value"], r["base"].split(".")[0])),
                               ("base", r["base"], ("default", "", r["base"].split(".")[0]))):
            a = cff(r["pin"], bid)
            if a is None:
                continue
            srcs[key].add(bid)
            for name, bits in chain.cff[s].items():
                pat[key][(name, len(bits))][("".join(str(int(a[b])) for b in bits), (r["pin"], s))] += 1
    table = []
    default = {k[2]: k for k in pat if k[0] == "default"}
    for key in sorted(pat):
        for (name, n), cnt in sorted(pat[key].items()):
            by = collections.defaultdict(list)
            for (p, (pin, s)), _ in cnt.items():
                by[p].append(f"{pin}:{s[0]}.{s[1]}")
            modal = max(by, key=lambda p: len(by[p]))
            primary = key[0] != "default" and name in FIELD_GROUPS.get(key[0], ())
            dk = default[key[2]]
            dmodal = None
            if (name, n) in pat[dk]:
                d = collections.defaultdict(list)
                for (p, ps), _ in pat[dk][(name, n)].items():
                    d[p].append(ps)
                dmodal = max(d, key=lambda p: len(d[p]))
            if key[0] != "default" and not primary and modal == dmodal:
                continue
            sites = sum(len(v) for v in by.values())
            table.append({"setting": key[0], "value": key[1], "base_kind": key[2], "group": name, "n_elem": n, "primary": primary,
                          "pattern": modal, "sites_agree": len(by[modal]), "sites": sites,
                          "deviants": {p: v for p, v in by.items() if p != modal},
                          "source": {"pairs": sorted(srcs[key]), "groups": sorted({g for bt in (5, 6) for g in chain.gid.get((bt, name), [])})}})
    return table


def cram_fields(chain, pairs, settings=("direction", "open-drain", "registered-input", "registered-output", "registered-oe")):
    """IO CRAM groups hit by each CRAM-effect setting: groups with the same nonzero hit count at every mapped site (LABLINE routing
    groups vary with placement and drop out).  CRAM address = sof tag 17 bit index (little-endian bit order)."""
    res = {}
    for st in settings:
        hits = collections.defaultdict(dict)
        npins = set()
        for r in _rows(pairs):
            s = chain.ball_site.get(r["pin"])
            if r["setting"] != st or s is None:
                continue
            zb, zs = _build(pairs, r["pin"], r["base"]), _build(pairs, r["pin"], r["spec"])
            if zb is None or zs is None:
                continue
            npins.add((r["pin"], r["base"]))
            d = set(np.nonzero(np.unpackbits(zb["cram"] ^ zs["cram"], bitorder="little"))[0].tolist())
            for name, bits in chain.cram.get(s, {}).items():
                h = sorted(d & set(bits))
                if h:
                    hits[name][(r["pin"], r["base"])] = h
        keep = {}
        for name, h in hits.items():
            if len(h) == len(npins) and len({len(v) for v in h.values()}) == 1:
                keep[name] = {"bits_per_site": len(next(iter(h.values()))), "sites": len(h)}
        res[st] = {"builds": len(npins), "groups": dict(sorted(keep.items()))}
    return res


def double_groups(chain, pairs):
    """CFF bits with a second rbf cell group (io.Cff.count > 4) that change in a pair diff: per bit, rows in which each group's cells
    changed together with the sof bit (g1 = first group, g2 = second group), plus the A owner group of the bit."""
    cff = IO.Cff()
    res = {}
    for r in _rows(pairs):
        s = chain.ball_site.get(r["pin"])
        for b in r["cff"]:
            if cff.count[b] <= 4:
                continue
            zb, zs = _build(pairs, r["pin"], r["base"]), _build(pairs, r["pin"], r["spec"])
            fr = lambda z: z["peri"][P.RBF_HEADER:].reshape(-1, P.RBF_FRAME_BYTES)
            cells = cff.cells[cff.first[b]:cff.first[b] + cff.count[b]]
            ch = [int(((fr(zb)[f, y] >> k) & 1) != ((fr(zs)[f, y] >> k) & 1)) for f, y, k in cells[[0, 4]]]
            d = res.setdefault(b, {"rows": 0, "g1_changed": 0, "g2_changed": 0, "owner": [o[1] for o in chain.owner(b)],
                                   "g1_frame_byte": [int(cells[0][0]), int(cells[0][1])], "g2_frame_byte": [int(cells[4][0]), int(cells[4][1])]})
            d["rows"] += 1
            d["g1_changed"] += ch[0]
            d["g2_changed"] += ch[1]
    return {str(b): v for b, v in sorted(res.items())}


OD_DIR = os.path.join(P.REPO, "tmp", "cycloneiv_clean", "io_od")      # scripts/cycloneiv_clean_io_od.py builds


def open_drain(chain, pairs):
    """Constant-0 tri-state (`od`) vs the plain output base (`out`, 2.5 V) of the same pin: CFF bits that differ, by group.
    Entries carry the build ids as source.  Empty when the od builds are missing."""
    out = []
    for pin in sorted(os.listdir(OD_DIR)) if os.path.isdir(OD_DIR) else []:
        f = os.path.join(OD_DIR, pin, "od", "result.npz")
        base = _build(pairs, pin, "out.STD=2.5_V") if pin in pairs["sample"] else None
        s = chain.ball_site.get(pin)
        if not os.path.exists(f) or base is None or s is None:
            continue
        od = np.load(f)["cff"]
        own = {b: n for n, bs in chain.cff[s].items() for b in bs}
        out.append({"pin": pin, "site": list(s), "diff": {str(b): own.get(int(b)) for b in np.nonzero(od != base["cff"])[0]},
                    "pin_mode_pattern": {"out": "".join(str(int(base["cff"][b])) for b in chain.cff[s]["MIO_PIN_MODE"]),
                                         "od": "".join(str(int(od[b])) for b in chain.cff[s]["MIO_PIN_MODE"])},
                    "source": {"pairs": [f"io_od/{pin}/od", "out.STD=2.5_V"], "groups": sorted(chain.gid[(s[0], "MIO_PIN_MODE")])}})
    return out


def decode(chain=None, pairs=None):
    chain = chain or Chain()
    pairs = pairs or IO.io_pairs()
    anchors = {p: chain.anchor(chain.ball_site[p]) for p in pairs["location"] if chain.ball_site.get(p)}
    return {"cross_check": cross_check(chain, pairs), "values": value_table(chain, pairs), "cram_fields": cram_fields(chain, pairs),
            "open_drain": open_drain(chain, pairs), "double_groups": double_groups(chain, pairs),
            "anchor": {"rule": f"lowest CFF bit of {ANCHOR_GROUP} at the site",
                       "equal_to_pair_location": sum(1 for p, a in anchors.items() if a == pairs["location"][p][0]), "sites": len(anchors)}}


def write(path=DECODE_PATH):
    t = decode()
    json.dump(t, open(path, "w"), indent=0, sort_keys=True)
    return t


def encode(chain, table, ball, setting, value, base_kind):
    """{CFF address: bit} for one pin: the modal pattern of each table group laid on the site's A addresses (n_elem must match)."""
    s = chain.ball_site[ball]
    out = {}
    for e in table["values"]:
        if (e["setting"], e["value"], e["base_kind"]) == (setting, value, base_kind):
            bits = chain.cff[s].get(e["group"], [])
            if len(bits) == e["n_elem"]:
                out.update({b: int(c) for b, c in zip(bits, e["pattern"])})
    return out


if __name__ == "__main__":
    t = write()
    print(json.dumps(t["cross_check"], indent=1, sort_keys=True))
