#!/usr/bin/env python3.15t
"""Cyclone V native decoder: device tables (bit positions, routing muxes, geometry).

Bootstrap source = Mistral's plain-text `data/` tree + `libmistral/cv-rpats.cc` + `cvd-<die>.cc`
(no mistral-cv binary). Verification against Quartus oracles: docs/altera/cycloneV/cyclonev-native-decoder.md.
Derived cache: tmp/cyclonev_native/<die>.pkl (rebuilt when TABLES_VERSION or a source mtime changes).

Env: PLURIBUS_MISTRAL_ROOT (default /mnt/2tb/git/mistral).
"""
import concurrent.futures
import logging
import lzma
import os
import pickle
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

TABLES_VERSION = 5
MISTRAL_ROOT = os.environ.get("PLURIBUS_MISTRAL_ROOT", "/mnt/2tb/git/mistral")
CACHE_DIR = os.path.join(REPO, "tmp", "cyclonev_native")
log = logging.getLogger("cyclonev_native_tables")

# Fixed-block order = libmistral fixed_infos FB_* layout (generator pram.cc get_fixed_blocks).
FIXED_BLOCKS = [("fpll", 8), ("cmuxc", 4), ("cmuxv", 2), ("cmuxh", 2), ("dll", 4), ("hssi", 4),
                ("cbuf", 8), ("lvl", 17), ("pma3", 4), ("serpar", 10), ("term", 4), ("hip", 2),
                ("hmc", 2)]
HPS_DIES = ("sx50f", "sx120f")


class TableError(Exception):
    pass


def _data(name):
    return os.path.join(MISTRAL_ROOT, "data", name)


def _read_text(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rt") as f:
            return f.read()
    with open(path, "r") as f:
        return f.read()


def rkey(t, x, y, z):
    return (t << 24) | (x << 17) | (y << 10) | z


# ---- patterns (cv-rpats.cc) ----------------------------------------------------------------

def _array(text, name):
    m = re.search(name + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\n\};", text, re.S)
    if not m:
        raise TableError(f"cv-rpats.cc: array {name} not found")
    return m.group(1)


def parse_patterns():
    text = open(os.path.join(MISTRAL_ROOT, "libmistral", "cv-rpats.cc")).read()
    vals = np.array([int(t, 16) for t in re.findall(r"0x[0-9a-fA-F]+", _array(text, "rmux_vals"))], np.uint32)
    vhash = np.array([int(t) for t in re.findall(r"-?\d+", _array(text, "rmux_vhash"))], np.int16)
    xy = np.array([int(t) for t in re.findall(r"\d+", _array(text, "rmux_xy"))], np.uint8)
    pats = []
    for row in re.findall(r"\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(0x[0-9a-fA-F]+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}",
                          _array(text, "rmux_patterns")):
        b, span, hd, df, oxy, ov, ovh = row
        pats.append(dict(bits=int(b), span=int(span), hashdiv=int(hd), defv=int(df, 16),
                         o_xy=int(oxy), o_vals=int(ov), o_vhash=int(ovh)))
    if len(pats) != 74 or len(vals) != 622 or len(vhash) != 1688 or len(xy) != 2 * 780:
        raise TableError(f"cv-rpats.cc counts off: pats={len(pats)} vals={len(vals)} vhash={len(vhash)} xy={len(xy)}")
    return pats, vals, vhash, xy


# ---- routes (data/<die>-r.txt.xz) -------------------------------------------------------------

def _parse_routes_chunk(lines, width, tmap, spans):
    dest, pat, fw, span, src = [], [], [], [], []
    for line in lines:
        toks = line.split(" ")
        d = toks[0].split(".")
        dest.append(rkey(tmap[d[0]], int(d[1]), int(d[2]), int(d[3])))
        t0 = toks[1]
        if t0 == "-":
            p, f, sp, rest = 0xfe, 0, 1, toks[2:]
        else:
            pt, _, pos = t0.partition(":")
            if "." in pt:
                p = 70 + int(pt.partition(".")[2])
            else:
                p = int(pt)
            px, _, py = pos.partition("_")
            f, sp, rest = int(px) + int(py) * width, spans[p], toks[2:]
        row = [0] * sp
        for tok in rest:
            if not tok:
                continue
            s, _, n = tok.partition(":")
            n = n.split(".")
            k = int(s)
            if k < sp:  # generator reads only slots < span (pattern 0xfe: slot 0 only)
                row[k] = rkey(tmap[n[0]], int(n[1]), int(n[2]), int(n[3]))
        pat.append(p)
        fw.append(f)
        span.append(sp)
        src.extend(row)
    return (np.array(dest, np.uint32), np.array(pat, np.uint8), np.array(fw, np.uint32),
            np.array(span, np.uint8), np.array(src, np.uint32))


def parse_routes(die, width, pats, workers=8):
    text = _read_text(_data(f"{die}-r.txt.xz"))
    lines = text.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    lines = [l.rstrip("\r") for l in lines]
    names = sorted(set(re.findall(r"(?:^|[ :])([A-Za-z_][A-Za-z_0-9]*)\.\d+\.\d+\.\d+", text, re.M)))
    tmap = {n: i for i, n in enumerate(names)}
    spans = [p["span"] for p in pats]
    # sources-only types missed by the sample are caught by KeyError -> widen and retry
    while True:
        try:
            chunk = 40000
            parts = [lines[i:i + chunk] for i in range(0, len(lines), chunk)]
            with concurrent.futures.ThreadPoolExecutor(workers) as ex:
                res = list(ex.map(lambda c: _parse_routes_chunk(c, width, tmap, spans), parts))
            break
        except KeyError as e:
            nm = e.args[0]
            tmap[nm] = len(tmap)
            names.append(nm)
            log.info("route node type %s found late", nm)
    out = {k: np.concatenate([r[i] for r in res]) for i, k in enumerate(("dest", "pat", "fw", "span", "src"))}
    out["src_off"] = np.concatenate([[0], np.cumsum(out["span"].astype(np.int64))[:-1]]).astype(np.int64)
    out["type_names"] = names
    return out


# ---- other plain-text tables ------------------------------------------------------------------

def parse_node(tok, tmap):
    t, x, y, z = tok.split(".")
    if t not in tmap:
        tmap[t] = len(tmap)
    return rkey(tmap[t], int(x), int(y), int(z))


def parse_pnode(tok):
    head, has_port, port = tok.partition(":")
    hp = head.split(".")
    bt, x, y = hp[0], int(hp[1]), int(hp[2])
    bi = int(hp[3]) if len(hp) > 3 else -1
    pt, pi = None, -1
    if has_port:
        pp = port.split(".")
        pt = pp[0].upper()
        pi = int(pp[1]) if len(pp) > 1 else -1
    return (bt, x, y, pt, bi, pi)


def parse_p2r(die, tmap):
    rows, cur = [], None
    for line in _read_text(_data(f"{die}-p2r.txt")).split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        toks = line.split()
        if not line.startswith(" "):
            cur = (toks[0], int(toks[1]), int(toks[2]))
            continue
        port, inst, bit = toks[0], toks[1], toks[2]
        minst, mbit = inst != ".", bit != "."
        ninst = int(inst) if minst else 1
        nbit = int(bit) if mbit else 1
        k = 3
        for i in range(ninst):
            for b in range(nbit):
                tk = toks[k]
                k += 1
                if tk == "-":
                    continue
                rows.append(((cur[0], cur[1], cur[2], port.upper(), i if minst else -1, b if mbit else -1),
                             parse_node(tk, tmap)))
    return rows


def parse_p2p(die):
    rows = []
    for line in _read_text(_data(f"{die}-p2p.txt")).split("\n"):
        toks = line.split()
        if toks:
            rows.append((parse_pnode(toks[0]), parse_pnode(toks[1])))
    return rows


def parse_inv(die, width, tmap):
    rows = []
    for line in _read_text(_data(f"{die}-inv.txt")).split("\n"):
        toks = line.split()
        if not toks:
            continue
        x, _, y = toks[1].partition(".")
        d = toks[2] if len(toks) > 2 else None
        rows.append((parse_node(toks[0], tmap), int(x) + int(y) * width, d))
    return rows


def parse_ones(die, width):
    out = []
    for line in _read_text(_data(f"{die}-1.txt")).split("\n"):
        if line.strip():
            x, _, y = line.strip().partition(".")
            out.append(int(x) + int(y) * width)
    return out


def parse_pram(die):
    data = {}
    for line in _read_text(_data(f"{die}-pram.txt")).split("\n"):
        toks = line.split()
        if not toks:
            continue
        strip, _, rng = toks[0].partition(".")
        start, _, end = rng.partition("-")
        block = toks[1]
        x, _, y = toks[2].partition(".")
        rest = toks[3:]
        inst, var = 0, 0
        if rest and rest[0].isdigit():
            inst = int(rest.pop(0))
        elif rest and rest[0] == "-":
            rest.pop(0)
        if rest and rest[0].isdigit():
            var = int(rest.pop(0))
        data.setdefault(block, []).append(dict(strip=int(strip), start=int(start), count=int(end) - int(start) + 1,
                                              pos=(int(x), int(y)), inst=inst, var=var))
    return data


def fixed_and_dqs16(pram):
    fixed = []
    for key, count in FIXED_BLOCKS:
        k = key
        if key == "hmc":
            k = "hmcphy40" if "hmcphy40" in pram else "hmcphy24"
        ents = pram.get(k, [])
        got = sorted(((e["pos"], e["start"] | (e["strip"] << 16) | (e["inst"] << 24) | (e["var"] << 25))
                      for e in ents), key=lambda t: t[0][0] << 7 | t[0][1])
        got += [(None, 0xFFFFFFFF)] * (count - len(got))
        fixed.append(got)
    blk = pram["dqs16"]
    dq = []
    for i, b in enumerate(blk):
        if b["inst"] == 0:
            first = i == 0 or blk[i - 1]["pos"] != b["pos"]
            dq.append((b["pos"], (1 << 24 if b["var"] else 0) | (1 << 23) | (1 << 22 if first else 0)
                       | (b["strip"] << 16) | b["start"]))
    dq.sort(key=lambda t: t[0][0] << 7 | t[0][1])
    return fixed, dq


def parse_iob(die, pram):
    prami = {}
    for e in pram["gpio"]:
        prami[e["pos"]] = e["start"] | (e["strip"] << 16) | (e["var"] << 25)
    rows = []
    for line in _read_text(_data(f"{die}-iob.txt")).split("\n"):
        toks = line.split()
        if not toks:
            continue
        x, y, idx = (int(v) for v in toks[1].split("."))
        serdes = len(toks) > 4 and toks[4] == "serdes"
        pr = (1 << 24 if serdes else 0) | prami.get((x, y), 0)
        rows.append(dict(pos=(x, y), idx=idx, btype=toks[2], slot=int(toks[3]), pram=pr))
    return rows


def parse_model(name):
    """models.txt -> (variant, die, pkg, idcode)."""
    variants = {}
    model = None
    for line in _read_text(_data("models.txt")).split("\n"):
        t = line.split()
        if not t:
            continue
        if t[0] == "variant":
            kv = dict(x.split(":", 1) for x in t[2:])
            variants[t[1]] = kv
        elif t[0] == "model" and t[1] == name:
            model = dict(x.split(":", 1) for x in t[2:])
    if model is None:
        raise TableError(f"model {name} not in models.txt")
    v = variants[model["v"]]
    return dict(name=name, variant=model["v"], die=v["die"], pkg=model["pkg"], idcode=int(v["idcode"], 16))


def parse_pkg(die, pkg):
    pins = {}
    cur = None
    for line in _read_text(_data(f"{die}-pkg.txt")).split("\n"):
        if not line.strip():
            continue
        t = line.split()
        if line[0] != " ":
            cur = t[0]
            continue
        if cur != pkg:
            continue
        for f in t[3:]:
            if f.startswith("gpio:"):
                x, y, i = (int(v) for v in f[5:].split("."))
                pins[(x, y, i)] = t[2]
    return pins


def parse_dcram(die, width):
    out = []
    for line in _read_text(_data("pma3-cram.txt")).split("\n"):
        t = line.split()
        if t and t[0] == die:
            out.extend(int(a) + int(b) * width for a, b in (v.split(".") for v in t[2:20]))
    return out


def parse_bel_spans(die):
    text = open(os.path.join(MISTRAL_ROOT, "libmistral", f"cvd-{die}.cc")).read()
    m = re.search(r"bel_spans_info\[\]\s*=\s*\{(.*?)\};", text, re.S)
    nums = [int(t, 0) for t in re.findall(r"0x[0-9a-fA-F]+|\d+", m.group(1))]
    spans, i = [], 0
    while nums[i] != 0xFF:
        xs, xe, n = nums[i:i + 3]
        i += 3
        ys = [(nums[i + 2 * k], nums[i + 2 * k + 1]) for k in range(n)]
        i += 2 * n
        spans.append((xs, xe, ys))
    return spans


def block_muxes():
    import cyclonev_db_import_blockmux as bm
    quiet = logging.getLogger("cyclonev_native_tables.blockmux")
    quiet.setLevel(logging.WARNING)
    rows, _ = bm.build_all_rows(MISTRAL_ROOT, quiet)
    return rows


# ---- assembly ------------------------------------------------------------------------------

def build(model_name, workers=8):
    import cyclonev_db_import as cvd
    mdl = parse_model(model_name)
    die = mdl["die"]
    if die in HPS_DIES:
        raise TableError(f"die {die} has an HPS: not supported by the native decoder yet")
    g = cvd.parse_cvd_file(os.path.join(MISTRAL_ROOT, "libmistral", f"cvd-{die}.cc"))
    width = g["cram_sx"]
    pats, vals, vhash, xy = parse_patterns()
    log.info("%s: routes ...", die)
    routes = parse_routes(die, width, pats, workers)
    tmap = {n: i for i, n in enumerate(routes["type_names"])}
    p2r = parse_p2r(die, tmap)
    p2p = parse_p2p(die)
    inv = parse_inv(die, width, tmap)
    routes["type_names"] = [n for n, _ in sorted(tmap.items(), key=lambda kv: kv[1])]
    pram = parse_pram(die)
    fixed, dq = fixed_and_dqs16(pram)
    iob = parse_iob(die, pram)
    spans = parse_bel_spans(die)
    ttype = {}
    pos = {"T_LAB": [], "T_MLAB": [], "T_M10K": [], "T_DSP": []}
    for xs, xe, yspans in spans:
        for x in range(xs, xe + 1):
            tp = g["column_types"][x]
            for ys, ye in yspans:
                for y in range(ys, ye + 1):
                    if tp == "T_DSP" and (y - ys) & 1:
                        ttype[(x, y)] = "T_DSP2"
                    else:
                        ttype[(x, y)] = tp
                        pos[tp].append((x, y))
    return dict(version=TABLES_VERSION, model=mdl, die=die, geom=g, patterns=pats, rvals=vals, rvhash=vhash, rxy=xy,
                routes=routes, p2r=p2r, p2p=p2p, inv=inv, ones=parse_ones(die, width), fixed=fixed, dqs16=dq, iob=iob, tile_types=ttype, pos=pos,
                pins=parse_pkg(die, mdl["pkg"]), dcram=parse_dcram(die, width), muxes=block_muxes())


def _sources(model_name):
    die = parse_model(model_name)["die"]
    fs = [_data(f"{die}-r.txt.xz"), _data("models.txt"), os.path.join(MISTRAL_ROOT, "libmistral", "cv-rpats.cc"),
          os.path.abspath(__file__)]
    return [(f, os.path.getmtime(f)) for f in fs]


def load(model_name="5CEBA4U19C8", workers=8):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{model_name}.pkl")
    src = _sources(model_name)
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            t = pickle.load(f)
        if t.get("version") == TABLES_VERSION and t.get("src") == src:
            return t
    t = build(model_name, workers)
    t["src"] = src
    tmp = cache + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(t, f, protocol=4)
    os.replace(tmp, cache)
    return t


if __name__ == "__main__":
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_native_tables.log"))])
    import time
    import heavy_guard
    heavy_guard.wait_available(log, "cyclonev_native_tables build")
    t0 = time.time()
    tb = load(sys.argv[1] if len(sys.argv) > 1 else "5CEBA4U19C8")
    r = tb["routes"]
    log.info("%s: muxes=%d src=%d p2r=%d p2p=%d inv=%d bmux=%d (%.1fs)", tb["die"], len(r["dest"]), len(r["src"]),
             len(tb["p2r"]), len(tb["p2p"]), len(tb["inv"]), len(tb["muxes"]), time.time() - t0)
