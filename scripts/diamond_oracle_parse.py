"""Parsers for Diamond `ncdread` text and `ncd2nmc -r` binary hard macros (#105).

Format notes: docs/lattice/machxo2/machxo2-diamond-oracle.md.
"""
import re


class FormatError(Exception):
    pass


# ---------------------------------------------------------------- ncdread ---
_COMP_RE = re.compile(r"^\s+NC_COMP:(\d+) - <(.*)>(?:, site = (\S+))?\s*$")
_PIN_RE = re.compile(r"^\s+pin (\d+) - (\S+): <(.*)>\s*$")
_PRIM_RE = re.compile(r"^\s+Primitive (\S+) = <(.*)>\s*$")
_HDR_RE = re.compile(r"^\s+vendor = (\S+), package = (\S+), performance = (\S+)")


def parse_ncdread(text):
    """-> {package, speed, comps:[{idx,name,site,config,pins:{pin:net},prims}]}."""
    out = {"package": None, "speed": None, "comps": []}
    lines = text.splitlines()
    i = 0
    cur = None
    while i < len(lines):
        ln = lines[i]
        m = _HDR_RE.match(ln)
        if m:
            out["package"], out["speed"] = m.group(2), m.group(3)
        m = _COMP_RE.match(ln)
        if m:
            cur = {"idx": int(m.group(1)), "name": m.group(2), "site": m.group(3),
                   "config": None, "pins": {}, "pin_index": {}, "prims": {}}
            if cur["idx"] != len(out["comps"]):
                raise FormatError(f"ncdread comp index gap at {cur['name']}")
            out["comps"].append(cur)
            i += 1
            continue
        s = ln.strip()
        if cur is not None and s.startswith("Config String: <"):
            parts = [s[len("Config String: <"):]]
            while not parts[-1].rstrip().endswith(">"):
                i += 1
                parts.append(lines[i].strip())
            cur["config"] = " ".join(" ".join(parts).rstrip()[:-1].split())
            i += 1
            continue
        m = _PIN_RE.match(ln)
        if cur is not None and m:
            cur["pins"][m.group(2)] = m.group(3)
            cur["pin_index"][m.group(2)] = int(m.group(1))
        m = _PRIM_RE.match(ln)
        if cur is not None and m:
            cur["prims"][m.group(1)] = m.group(2)
        if re.match(r"^\s+\d+ macdefs", ln):
            cur = None
        i += 1
    if not out["comps"] and " 0 comps" not in text:
        raise FormatError("ncdread: no components parsed")
    return out


def config_fields(cfg):
    """'K0::H0=~D REG0:#ON ...' -> {'K0': ':H0=~D', 'REG0': '#ON', ...}.

    Keys are split on the FIRST ':'; '#OFF' fields are kept (they are data)."""
    out = {}
    for tok in (cfg or "").split():
        k, _, v = tok.partition(":")
        out[k] = v
    return out


# -------------------------------------------------------------------- nmc ---
# Big-endian, unaligned.  Every field below is consumed; parse_nmc() dies unless
# the walk ends exactly at EOF.  Fields named unk_* are not understood; their
# observed values are recorded so a corpus survey can show they are constant.
class _Rd:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def _take(self, n):
        if self.p + n > len(self.d):
            raise FormatError(f"nmc: truncated at 0x{self.p:x} (+{n})")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self._take(1)[0]

    def u16(self):
        return int.from_bytes(self._take(2), "big")

    def u32(self):
        return int.from_bytes(self._take(4), "big")

    def i32(self):
        return int.from_bytes(self._take(4), "big", signed=True)

    def cstr(self):
        e = self.d.find(b"\0", self.p)
        if e < 0:
            raise FormatError(f"nmc: unterminated string at 0x{self.p:x}")
        s = self.d[self.p:e].decode("latin1")
        self.p = e + 1
        return s

    def lstr(self, n):
        return self._take(n).decode("latin1")

    def expect(self, what, got, want):
        if got != want:
            raise FormatError(f"nmc: {what} = {got!r}, expected {want!r} "
                              f"(at 0x{self.p:x})")


def _props(r):
    """u32 count; per property: u16 type, u32 len + name, u8 1, value.
    type 2 = u8 (bool), 3 = i32, 5 = u32 len + string."""
    props = []
    for _ in range(r.u32()):
        ptype = r.u16()
        pname = r.lstr(r.u32())
        r.expect("prop flag", r.u8(), 1)
        if ptype == 2:
            val = r.u8()
        elif ptype == 3:
            val = r.i32()
        elif ptype == 5:
            val = r.lstr(r.u32())
        else:
            raise FormatError(f"nmc: property type {ptype} ({pname}) at 0x{r.p:x}")
        props.append((pname, val))
    return props


NMC_MAGIC = 0xF0A1
NMC_REC_MAGIC = (0xF0F00132, 0xB65D)


def parse_nmc(data, trace=None):
    """Parse an `ncd2nmc -r` hard macro.  -> dict, see docs/lattice/machxo2/machxo2-diamond-oracle.md.

    trace: optional list; (section, offset) pairs are appended for debugging."""
    r = _Rd(data)
    tr = trace.append if trace is not None else (lambda _x: None)
    m = {"unk": {}}
    r.expect("magic", r.u16(), NMC_MAGIC)
    vers = []
    for _ in range(3):
        r.expect("record magic", r.u32(), NMC_REC_MAGIC[0])
        r.expect("record magic2", r.u16(), NMC_REC_MAGIC[1])
        vers.append((r.u16(), r.u16()))
    m["versions"] = vers
    m["name"], m["arch"], m["device"], m["package"], m["speed"] = \
        (r.cstr() for _ in range(5))
    # One extra 0x00 here when the macro keeps no I/O comp (seen without -io).
    if data[r.p] == 0:
        m["unk"]["hdr_pad"] = r.u8()
    r.expect("hdr word", r.u16(), 0x0100)
    m["timestamp"] = r.u32()
    m["unk"]["hdr_u16"] = r.u16()
    ncomps = r.u32()
    comps = []
    for _ in range(ncomps):
        tr(("comp", r.p))
        c = {"name": r.cstr()}
        c["unk_a"] = r.i32()
        c["cls"] = r.u8()
        c["type"] = r.cstr()
        c["unk_b"] = r.u8()
        c["unk_c"] = r.i32()
        c["unk_d"] = r.u8()
        n = r.u32()
        c["config"] = r.lstr(n)
        r.expect("config NUL", r.u8(), 0)
        elems = []
        for _ in range(r.u16()):
            en = r.lstr(r.u16())
            r.expect("element NUL", r.u8(), 0)
            elems.append((en, r.i32()))      # i32 = logical prim index, -1 none
        c["elements"] = elems
        c["props"] = _props(r)
        comps.append(c)
    m["comps"] = comps

    sigs = []
    for _ in range(r.u32()):
        tr(("signal", r.p))
        s = {"name": r.cstr(), "id": r.u32()}
        s["unk_flags"] = (r.u8(), r.u8(), r.u8())
        pins = []
        for _ in range(r.u32()):
            comp = r.u32()
            px, py = r.i32(), r.i32()
            pin = r.cstr()
            idx = r.u32()
            pins.append({"comp": comp, "pin": pin, "idx": idx, "unk_xy": (px, py)})
        s["pins"] = pins
        s["unk_tail"] = r.u32()
        s["props"] = _props(r)
        sigs.append(s)
    m["signals"] = sigs

    tr(("ext", r.p))
    n_ext = r.u16()
    ext = [{"comp": r.u32(), "pin": r.cstr()} for _ in range(n_ext)]
    for e in ext:
        e["name"] = r.cstr()
        e["flags"] = r.u16()
    m["ext_pins"] = ext
    m["unk"]["post_ext_u32"] = r.u32()
    m["unk"]["post_ext_hash"] = r.u32()
    comment = r._take(64)
    m["comment"] = comment.split(b"\0", 1)[0].decode("latin1")
    if any(comment[len(m["comment"]):]):
        raise FormatError("nmc: non-zero bytes after comment string")
    m["unk"]["pre_hier_u32"] = r.u32()

    tr(("hier", r.p))
    hier = []
    for _ in range(r.u16()):
        h = {"name": r.lstr(r.u32()), "parent": r.i32(), "flags": r.u32()}
        h["children"] = [r.u32() for _ in range(r.u16())]
        hier.append(h)
    m["hierarchy"] = hier

    tr(("routes", r.p))
    routes = []
    for _ in range(r.u32()):
        narcs = r.u32()
        sig = r.u16()
        src = r.lstr(r.u32()).split()
        dst = r.lstr(r.u32()).split()
        if len(src) != narcs or len(dst) != narcs:
            raise FormatError(f"nmc: route for signal {sig}: {narcs} arcs but "
                              f"{len(src)} sources / {len(dst)} sinks")
        if sig >= len(sigs):
            raise FormatError(f"nmc: route signal index {sig} >= {len(sigs)}")
        routes.append({"signal": sig, "arcs": list(zip(src, dst))})
    m["routes"] = routes

    place = []
    for _ in range(ncomps):
        place.append((r.i32(), r.i32(), r.u8()))
    m["relplace"] = place
    if r.p != len(data):
        raise FormatError(f"nmc: {len(data) - r.p} trailing bytes at 0x{r.p:x}")
    return m


# Diamond's placement grid: y = (max_row - row) * site_slots + site_index.
# MachXO2 uses 14 slots per row, ECP5 20 (docs/lattice/ecp5/ecp5-diamond-oracle.md).
SITE_SLOTS = 14
_WIRE_RE = re.compile(r"^R(-?\d+)C(-?\d+)_(\S+)$")
_SITE_RE = re.compile(r"^R(\d+)C(\d+)([A-D])$")
_SLICE_PIN_RE = re.compile(r"^(A|B|C|D|M|F|Q|DI)([01])$")
_REF_RE = re.compile(r"Using component <(.*)> as the reference component")
_DELETED_RE = re.compile(r"^\s*Deleted (component|signal|sigpin) <([^>]*)>")


def slice_pin_wire(letter, pin):
    """Slice-relative pin (Q1 on slice C) -> tile wire (Q5), or None."""
    m = _SLICE_PIN_RE.match(pin)
    if not m:
        return None
    return f"{m.group(1)}{2 * 'ABCD'.index(letter) + int(m.group(2))}"


def split_wire(w):
    m = _WIRE_RE.match(w)
    if not m:
        raise FormatError(f"nmc: wire without R/C prefix: {w}")
    return int(m.group(1)), int(m.group(2)), m.group(3)


def build_oracle(ncdr, macro, n2n_log, max_row, pinmap=None, site_slots=SITE_SLOTS,
                 unique_votes=False):
    """Merge ncdread + parsed nmc into the oracle dict; absolute coordinates.

    max_row: device's last row (Diamond numbering).  pinmap: iodb package pins
    {pin: {row, col, pio}} (prjtrellis 0-based col) used only as a cross-check.
    site_slots: placement-grid slots per row (MachXO2 14, ECP5 20).
    unique_votes: anchor votes only from pins whose slice-pin wire name occurs once
    among the net's pins and once among its wires (ECP5: high-fanout nets repeat
    A0_SLICE etc. in many tiles, so a name match alone is ambiguous)."""
    warn = []
    checks = {}
    ncomps = {c["name"]: c for c in ncdr["comps"]}
    mcomps = macro["comps"]
    names = [c["name"] for c in mcomps]

    # -- comps: every ncdread comp must be in the macro, same config ----------
    missing = sorted(set(ncomps) - set(names))
    extra = sorted(set(names) - set(ncomps))
    checks["comps_ncdread"] = len(ncomps)
    checks["comps_missing_in_nmc"] = missing
    checks["comps_extra_in_nmc"] = extra
    for n in missing:
        warn.append(f"comp_missing_in_nmc: {n}")
    cfg_mismatch = []
    for c in mcomps:
        nc = ncomps.get(c["name"])
        if nc is None:
            continue
        a = {k: v for k, v in config_fields(nc["config"]).items() if v != "#OFF"}
        b = config_fields(c["config"])
        if a != b:
            cfg_mismatch.append(c["name"])
            warn.append(f"config_mismatch: {c['name']}")
    checks["config_mismatch"] = cfg_mismatch

    # -- placement: comp0 absolute, others relative to comp0 -----------------
    x0, y0, _ = macro["relplace"][0]
    tiles = []
    for i, (x, y, placed) in enumerate(macro["relplace"]):
        ax, ay = (x, y) if i == 0 else (x0 + x, y0 + y)
        tiles.append((max_row - ay // site_slots, ax, ay % site_slots, placed))
    place_bad = []
    n_checked = 0
    pio_cols = {}       # "edge:dcol-iodbcol:slot-pio" -> count (pads vs iodb)
    for c, (row, col, slot, _p) in zip(mcomps, tiles):
        site = (ncomps.get(c["name"]) or {}).get("site") or ""
        ms = _SITE_RE.match(site)
        if ms:
            n_checked += 1
            want = (int(ms.group(1)), int(ms.group(2)), "ABCD".index(ms.group(3)))
            if (row, col, slot) != want:
                place_bad.append(c["name"])
                warn.append(f"relplace_mismatch: {c['name']} {site} got "
                            f"R{row}C{col}/{slot} want R{want[0]}C{want[1]}/{want[2]}")
        elif pinmap and site in pinmap:
            n_checked += 1
            pm = pinmap[site]
            edge = ("T" if pm["row"] == 0 else "B" if pm["row"] == max_row
                    else "L" if pm["col"] == 0 else "R")
            k = f"{edge}:{col - pm['col']}:{slot}-{pm['pio']}"
            pio_cols[k] = pio_cols.get(k, 0) + 1
            if row != pm["row"]:
                place_bad.append(c["name"])
                warn.append(f"relplace_mismatch: {c['name']} pin {site} got "
                            f"R{row}C{col} iodb row {pm['row']}")
    checks["relplace_checked"] = n_checked
    checks["relplace_mismatch"] = place_bad
    checks["pio_dcol_vs_iodb"] = pio_cols

    # -- anchor: the reference comp's tile ------------------------------------
    m = _REF_RE.search(n2n_log)
    if not m:
        raise FormatError("ncd2nmc log names no reference component")
    ref = m.group(1)
    ri = names.index(ref)
    anchor = (tiles[ri][0], tiles[ri][1])
    # Independent check: slice pin wires in the routes vs ncdread sites.
    votes = {}
    sigs = macro["signals"]
    route_by_sig = {rt["signal"]: rt for rt in macro["routes"]}
    for si, s in enumerate(sigs):
        rt = route_by_sig.get(si)
        if rt is None:
            continue
        wires = {w for a in rt["arcs"] for w in a}
        pin_tw = []
        for p in s["pins"]:
            site = (ncomps.get(mcomps[p["comp"]]["name"]) or {}).get("site") or ""
            ms = _SITE_RE.match(site)
            tw = slice_pin_wire(ms.group(3), p["pin"]) if ms else None
            pin_tw.append((ms, tw))
        if unique_votes:
            wcount = {}
            pcount = {}
            for w in wires:
                nm = split_wire(w)[2]
                wcount[nm] = wcount.get(nm, 0) + 1
            for _ms, tw in pin_tw:
                if tw is not None:
                    pcount[tw] = pcount.get(tw, 0) + 1
        for ms, tw in pin_tw:
            if tw is None:
                continue
            if unique_votes and (pcount[tw] != 1 or wcount.get(tw + "_SLICE") != 1):
                continue
            for w in wires:
                dr, dc, nm = split_wire(w)
                if nm == tw + "_SLICE":
                    key = (int(ms.group(1)) - dr, int(ms.group(2)) - dc)
                    votes[key] = votes.get(key, 0) + 1
    # Routes are relative to the ref comp's ROUTING tile, which for non-slice
    # refs (DCMA, edge pads) can sit a column off its placement-grid tile, so
    # the slice-pin majority wins when there is one.
    checks["anchor_votes"] = {f"R{k[0]}C{k[1]}": v for k, v in votes.items()}
    checks["anchor_relplace"] = f"R{anchor[0]}C{anchor[1]}"
    if votes:
        best = max(votes, key=votes.get)
        if votes[best] * 2 <= sum(votes.values()):
            raise FormatError(f"no majority anchor: {checks['anchor_votes']}")
        if best != anchor:
            warn.append(f"anchor_relplace_differs: ref {ref} relplace "
                        f"R{anchor[0]}C{anchor[1]} slice-pins R{best[0]}C{best[1]}")
        if len(votes) > 1:
            warn.append(f"anchor_minority_votes: {checks['anchor_votes']}")
        anchor = best
    checks["anchor_source"] = "slice_pins" if votes else "relplace"

    def absw(w):
        dr, dc, nm = split_wire(w)
        return f"R{anchor[0] + dr}C{anchor[1] + dc}_{nm}"

    # -- nets --------------------------------------------------------------
    nets = []
    pin_net = {}
    for si, s in enumerate(sigs):
        rt = route_by_sig.get(si)
        arcs = [[absw(a), absw(b)] for a, b in rt["arcs"]] if rt else []
        sinks = [b for _a, b in arcs]
        if len(set(sinks)) != len(sinks):
            warn.append(f"route_multi_driver: {s['name']}")
        pins = [{"comp": mcomps[p["comp"]]["name"], "pin": p["pin"]} for p in s["pins"]]
        for p in pins:
            pin_net[(p["comp"], p["pin"])] = s["name"]
        nets.append({"name": s["name"], "props": dict(s["props"]), "pins": pins,
                     "routed": rt is not None, "arcs": arcs,
                     "wires": sorted({w for a in arcs for w in a})})
    # every ncdread pin-net must be in the macro
    pn_missing = []
    pn_total = 0
    for c in ncdr["comps"]:
        for pin, net in c["pins"].items():
            pn_total += 1
            if pin_net.get((c["name"], pin)) != net:
                pn_missing.append(f"{c['name']}.{pin}={net}")
    checks["pin_nets_ncdread"] = pn_total
    checks["pin_nets_missing_in_nmc"] = pn_missing
    for x in pn_missing:
        warn.append(f"pin_net_missing_in_nmc: {x}")
    deleted = [f"{k} {n}" for k, n in _DELETED_RE.findall(n2n_log)]
    checks["ncd2nmc_deleted"] = deleted
    for d in deleted:
        warn.append(f"ncd2nmc_deleted: {d}")

    comps = []
    for c, t in zip(mcomps, tiles):
        nc = ncomps.get(c["name"]) or {}
        comps.append({"name": c["name"], "type": c["type"], "site": nc.get("site"),
                      "tile": f"R{t[0]}C{t[1]}", "slot": t[2],
                      "config": nc.get("config") or c["config"],
                      "pins": nc.get("pins", {}), "prims": nc.get("prims", {}),
                      "props": dict(c["props"])})
    return {"device": macro["device"], "package": macro["package"],
            "speed": macro["speed"], "reference_comp": ref,
            "anchor": f"R{anchor[0]}C{anchor[1]}", "comps": comps, "nets": nets,
            "checks": checks, "warnings": warn}
