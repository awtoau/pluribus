"""Adapter-independent payload pieces: geographic position numbers (4b), board pin names (4c), pin-order patterns (4d).
Row layout is geo_data.PIN_COLS; all functions take the finished rows (tile / cell filled)."""
import re
import tomllib
from pathlib import Path

F = {c: i for i, c in enumerate(["ball", "pad", "bank", "side", "x", "y", "z", "site", "type", "names", "ibis", "role", "bonded",
                                 "usage", "src", "conflicts", "expected", "tile", "pair", "cell"])}
EDGES = ("top", "bottom", "left", "right")
BOARD_COLS = "pin row col pio dir label function confidence chip_ref chip_pin chip_signal net_in net_out note".split()


# ---- 4b: position numbers -------------------------------------------------------------------
def die_edge(x, y, nx, ny, side=None):
    cand = [e for e, on in (("top", y == ny - 1), ("bottom", y == 0), ("left", x == 0), ("right", x == nx - 1)) if on]
    return side if side in cand else (cand[0] if cand else None)


def geo_positions(pk, grid, rows, nx, ny):
    """-> per pin {pkg: {...}, die: {...} | None}.  Counts exclude the pin itself and include the edge pin / edge tile."""
    out = []
    if pk["layout"] == "bga-matrix":
        nr, nc = len(grid["letters"]), grid["cols"]
        occ = {}
        for r in rows:
            occ[r[F["cell"]]] = 1
        has = lambda rr, cc: (rr * nc + cc) in occ
        corners = {(0, 0): (0, 0), (0, nc - 1): (0, nc - 1), (nr - 1, 0): (nr - 1, 0), (nr - 1, nc - 1): (nr - 1, nc - 1)}
        for r in rows:
            cl = r[F["cell"]]
            rr, cc = divmod(cl, nc)
            cn = min(corners, key=lambda k: abs(k[0] - rr) + abs(k[1] - cc))
            out.append(dict(pkg=dict(k="m", r=rr, nr=nr, c=cc, nc=nc, l=sum(has(rr, q) for q in range(cc)), rt=sum(has(rr, q) for q in range(cc + 1, nc)),
                                     u=sum(has(q, cc) for q in range(rr)), d=sum(has(q, cc) for q in range(rr + 1, nr)),
                                     ring=min(rr, cc, nr - 1 - rr, nc - 1 - cc), corner=f"{grid['letters'][cn[0]]}{cn[1] + 1}",
                                     cdr=abs(cn[0] - rr), cdc=abs(cn[1] - cc))))
    else:
        n, ps = pk["n_pins"], pk["per_side"]
        for r in rows:
            p = r[F["cell"]]
            out.append(dict(pkg=dict(k="p", side=pk["sides"][p // ps], i=p % ps, n=ps, around=p, total=n)))
    for g, r in zip(out, rows):
        t = r[F["tile"]]
        if t < 0:
            g["die"] = None
            continue
        x, y = divmod(t, ny)
        g["die"] = dict(x=x, y=y, edge=die_edge(x, y, nx, ny, r[F["side"]]), l=x, r=nx - 1 - x, t=ny - 1 - y, b=y)
    return out


# ---- 4c: board pin names --------------------------------------------------------------------
def load_board(board_dir, package):
    """-> ({pin: dict(name, names, sig, net, dir, desc, conf)}, source dict) from the board's pin TSV (boards/README.md).
    Header: the '# pin<ws>row<ws>...' comment line if present, else BOARD_COLS.  Unnamed (empty, '?', 'pin<N>') -> no name."""
    bd = Path(board_dir)
    cfg = tomllib.loads((bd / "board.toml").read_text())
    if cfg["board"].get("package") != package:
        return {}, None
    path = bd / cfg["files"]["pins_tsv"]
    cols, out = BOARD_COLS, {}
    for ln in path.read_text().splitlines():
        if ln.startswith("#"):
            c = ln[1:].split()
            if len(c) >= 6 and c[0] == "pin":
                cols = c
            continue
        v = ln.split("\t")
        if len(v) < 2 or not v[0].strip().isdigit():
            continue
        d = dict(zip(cols, v + [""] * (len(cols) - len(v))))
        pin = d["pin"].strip()
        g = lambda k: (d.get(k) or "").strip()      # noqa: E731
        label = g("label")
        label = "" if label in ("", "?") or re.fullmatch(r"pin\d+", label) else label
        sig = ".".join(x for x in (g("chip_ref"), g("chip_signal")) if x and x != "?")
        net = g("net_in") or g("net_out")
        out[pin] = dict(name=label, names=[x for x in (label, sig, net) if x], sig=sig if "." in sig else "", net=net, dir=g("dir"),
                        desc=g("function") or g("note"), conf=g("confidence"))
    return out, dict(file=path.name, cols=cols)


# ---- 4d: patterns ---------------------------------------------------------------------------
def _ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    """Rank correlation with average ranks; None when undefined (< 3 points or no variance)."""
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    sa = sum((x - ma) ** 2 for x in ra)
    sb = sum((x - mb) ** 2 for x in rb)
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sa * sb) ** .5


def pkg_uv(pk, grid, row):
    """Unit-square position of a pin in the default frame: perimeter = top view, matrix = Bottom view (A1 top-left); die = top surface."""
    cl = row[F["cell"]]
    if pk["layout"] == "bga-matrix":
        nc, nr = grid["cols"], len(grid["letters"])
        return ((cl % nc + .5) / nc, (cl // nc + .5) / nr)
    ps = pk["per_side"]
    side, k = pk["sides"][cl // ps], cl % ps
    f = (k + .5) / ps
    return {"left": (0.0, f), "bottom": (f, 1.0), "right": (1.0, 1 - f), "top": (1 - f, 0.0)}[side]


def pattern(pk, grid, rows, nx, ny, tile_pins):
    """-> dict(edges=[...], banks=[...], tile_bank={tile: [bank, mixed]}).  See docs/geo-explorer.md (Pattern panel)."""
    by = {e: [] for e in EDGES}
    for i, r in enumerate(rows):
        t = r[F["tile"]]
        if t < 0:
            continue
        x, y = divmod(t, ny)
        e = die_edge(x, y, nx, ny, r[F["side"]])
        if e:
            u, v = pkg_uv(pk, grid, r)
            horiz = e in ("top", "bottom")
            by[e].append((i, u if horiz else v, (x + .5) / nx if horiz else (ny - 1 - y + .5) / ny))
    edges = []
    for e in EDGES:
        pts = by[e]
        horiz = e in ("top", "bottom")
        axis = "left-to-right" if horiz else "top-to-bottom"
        cross = [0] * len(pts)
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                da, db = pts[a][1] - pts[b][1], pts[a][2] - pts[b][2]
                if da * db < 0:
                    cross[a] += 1
                    cross[b] += 1
        rho = spearman([p[1] for p in pts], [p[2] for p in pts])
        ncross = sum(cross) // 2
        if not pts:
            s = f"{e} die edge: no pins with a die site."
        elif rho is None:
            s = f"{e} die edge: {len(pts)} pin{'s' if len(pts) != 1 else ''} with a site, too few or too uniform for an order ({ncross} crossings)."
        else:
            kind = "in the same order as" if rho >= .8 else "in the reverse order of" if rho <= -.8 else "in no clear order against"
            s = f"{e} die edge: pins run {axis} {kind} the die tiles, correlation {rho:+.2f}, {ncross} crossings ({len(pts)} pins)."
        edges.append(dict(edge=e, n=len(pts), rho=None if rho is None else round(rho, 3), crossings=ncross, axis=axis, sentence=s,
                          pts=[[p[0], round(p[1], 4), round(p[2], 4), c] for p, c in zip(pts, cross)]))
    # per bank: balls, with site, die-edge tile ranges, package extent
    banks = []
    for b in sorted({r[F["bank"]] for r in rows if r[F["bank"]]}, key=lambda s: (len(s), s)):
        mem = [(i, r) for i, r in enumerate(rows) if r[F["bank"]] == b]
        die = {}
        for i, r in mem:
            t = r[F["tile"]]
            if t < 0:
                continue
            x, y = divmod(t, ny)
            e = die_edge(x, y, nx, ny, r[F["side"]])
            c = x if e in ("top", "bottom") else y
            lo, hi = die.get(e, (c, c))
            die[e] = (min(lo, c), max(hi, c))
        if pk["layout"] == "bga-matrix":
            nc = grid["cols"]
            rr = [r[F["cell"]] // nc for _, r in mem]
            cc = [r[F["cell"]] % nc for _, r in mem]
            ext = f"rows {grid['letters'][min(rr)]}-{grid['letters'][max(rr)]}, columns {min(cc) + 1}-{max(cc) + 1}"
        else:
            cl = [r[F["cell"]] for _, r in mem]
            ext = f"pins {min(cl) + 1}-{max(cl) + 1} ({', '.join(sorted({pk['sides'][c // pk['per_side']] for c in cl}))})"
        banks.append(dict(bank=b, balls=len(mem), with_site=sum(r[F["tile"]] >= 0 for _, r in mem),
                          die={e: list(v) for e, v in die.items()}, pkg=ext))
    tb = {}
    for t, pins in tile_pins.items():
        cnt = {}
        for i in pins:
            b = rows[i][F["bank"]]
            if b:
                cnt[b] = cnt.get(b, 0) + 1
        if cnt:
            top = max(cnt, key=lambda k: (cnt[k], k))
            tb[str(t)] = [top, int(len(cnt) > 1)]
    return dict(frame=dict(pkg="top view" if pk["layout"] == "perimeter" else "Bottom view (A1 top-left)", die="top surface"),
                edges=edges, banks=banks, tile_bank=tb)
