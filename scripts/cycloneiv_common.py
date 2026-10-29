"""Neutral Cyclone IV helpers: .vo atom locations, node keys, LE bit access, tile classes, die geometry, split."""
import re
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402

LOC = re.compile(r"^([A-Z0-9]+)_X(\d+)_Y(\d+)_N(\d+)$")

# Window around the anchor, (frame, v) relative.  Wide on purpose: wire muxes may sit a tile away.
WF = (-40, 41)
WV = (-110, 41)

def atom_xyn(vo, name):
    a = vo.atoms.get(name)
    if a is None:
        # WYSIWYG registers: the RCF names a register after its q net (r0_2_q), the .vo after the instance
        alias = getattr(vo, "_q_alias", None)
        if alias is None:
            alias = {}
            for an, at in vo.atoms.items():
                if at["type"] == "dffeas":
                    for p, _b, _d, net, _i, _c in at["conns"]:
                        if p == "q" and net:
                            alias[net] = an
            vo._q_alias = alias
        a = vo.atoms.get(alias.get(name, ""))
    if a is None or not a.get("location"):
        return None
    m = LOC.match(a["location"])
    if not m:
        return None
    k, x, y, n = m.groups()
    return k, int(x), int(y), int(n)


def node_at(vo, node):
    """-> (x, y, key) for a dst/src node, or None when it has no fabric location."""
    if node[0] == "W":
        _, t, x, y, s, i = node
        return x, y, (t, s, i)
    if node[0] == "WB":
        _, t, x, y, s, path = node
        return x, y, (t, s, path)
    if node[0] == "SINK":
        loc = atom_xyn(vo, node[1])
        if loc is None:
            return None
        k, x, y, n = loc
        return x, y, (k, n, node[2])
    if node[0] == "DRV":
        loc = atom_xyn(vo, node[1])
        if loc is None:
            return None
        k, x, y, n = loc
        return x, y, ("DRV", k, n)
    raise ValueError(node)


# FF control pins pick one of two LAB lines by a per-LE select bit (LE-relative (frame, v), odd LEs mirrored).
FF_SEL = {"CLK": (4, 2), "ENA": (4, 2), "CLRN": (3, 2)}
FF_LAB_PORTS = set()   # empty: per-(LE, pin) groups replace the line mapping


def le_bit(plane, geom, x, y, le, df, dv):
    f0, v0 = geom.anchor(x, y)
    s = -1 if le % 2 else 1
    return plane[f0 + df, v0 + geom.DN[le] + s * dv]


def ff_lab_key(plane, geom, x, y, n, port):
    """FF control pin -> the LAB line dst it reads: ("LAB<port>", 0, j)."""
    j = int(le_bit(plane, geom, x, y, n // 2, *FF_SEL[port])) if port in FF_SEL else 0
    return ("LAB" + port, 0, j)


def instances(name, d, geom=None):
    """[(group, x, y, src_key)] for every routed edge of a design.  With geom, FF control pins are
    re-expressed as LAB line dsts (ff_lab_key) so the line source is learnt like a mux."""
    vo, out = d["vo"], []
    for net, edges in d["rcf"].items():
        for src, dst in edges:
            a, b = node_at(vo, src), node_at(vo, dst)
            if a is None or b is None:
                continue
            bx, by, bkey = b
            ax, ay, akey = a
            if geom is not None and bkey[0] == "FF" and bkey[2] in FF_LAB_PORTS:
                bkey = ff_lab_key(d["plane"], geom, bx, by, bkey[1], bkey[2])
            out.append((bkey, bx, by, akey + (ax - bx, ay - by)))
    out += pseudo_instances(d, geom)
    return out


# Pins the RCF does not route are still muxes with a code: constants and the carry input.
LE_PORTS = ("dataa", "datab", "datac", "datad")
FF_PORTS = ("d", "asdata", "clrn", "sclr", "sload", "ena")


def pseudo_instances(d, geom=None):
    """(group, x, y, src) for pins the .vo ties to a constant (CONST 0 / 1) and for the DATAC pin
    of carry-mode LEs (CIN): the mux code that selects them, learnt like any other source."""
    vo, out = d["vo"], []
    comb_of = {}
    for a in vo.atoms.values():
        loc = LOC.match(a.get("location") or "")
        if loc and a["type"] == "cycloneive_lcell_comb":
            for p, _b, _d, net, _i, _c in a["conns"]:
                if p == "combout" and net:
                    comb_of[vo.canon(net)] = (int(loc.group(2)), int(loc.group(3)), int(loc.group(4)))
    for a in vo.atoms.values():
        loc = LOC.match(a.get("location") or "")
        if not loc or a["type"] not in ("cycloneive_lcell_comb", "dffeas"):
            continue
        kind, x, y, n = loc.group(1), int(loc.group(2)), int(loc.group(3)), int(loc.group(4))
        if kind == "LCCOMB":
            for p, _b, _d, net, _i, const in a["conns"]:
                if p in LE_PORTS and net is None and const in ("0", "1"):
                    out.append((("LCCOMB", n, p.upper()), x, y, ("CONST", int(const), 0, 0, 0)))
            if a["params"].get("sum_lutc_input") == "cin":
                out.append((("LCCOMB", n, "DATAC"), x, y, ("CIN", 0, 0, 0, 0)))
        elif kind == "FF":
            for p, _b, _d, net, _i, const in a["conns"]:
                if p == "d" and net is not None and comb_of.get(vo.canon(net)) == (x, y, n - 1):
                    out.append((("FF", n, "DATAD"), x, y, ("LUTOUT", 0, 0, 0, 0)))
                if p in FF_PORTS and net is None and const in ("0", "1"):
                    key = ("FF", n, "DATAD" if p == "d" else p.upper())
                    if geom is not None and key[2] in FF_LAB_PORTS:
                        key = ff_lab_key(d["plane"], geom, x, y, n, key[2])
                    out.append((key, x, y, ("CONST", int(const), 0, 0, 0)))
    return out


def window(plane, geom, x, y):
    f0, v0 = geom.anchor(x, y)
    return plane.rect(f0 + WF[0], f0 + WF[1], v0 + WV[0], v0 + WV[1])


ROW_PHASE = 4   # R4 / C4 indices rotate with Y mod 4 (an R4 index occurs at one row phase only)


def tile_class(geom, x, y, col_phase=0, ktype=None):
    """Per column (LI/wire mux input order differs between LAB columns) and row phase."""
    col = f"{x}" if not col_phase else f"m{x % col_phase}"
    return f"{geom.col_kind(x)}{col}/{geom.row_kind(y)}/{y % ROW_PHASE}"


def one_geom(names):
    """The die geometry shared by every design (hard error on a mixed set)."""
    dies = {cg.die_of(cc.device_of(n)) for n in names}
    if len(dies) != 1:
        raise SystemExit(f"designs span dies {sorted(dies)}: pass a pattern for one die")
    return cg.load(dies.pop())


def split_of(name, split):
    if split == "all":
        return True
    h = zlib.crc32(name.encode()) & 1
    return h == (0 if split == "even" else 1)
