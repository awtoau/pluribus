"""Cyclone IV corpus loader: CRAM as a (frame, v) bit plane, RCF routing edges, post-fit .vo atoms.

- CRAM plane: frame index as in cycloneiv_fuzz_analyze (header frame = 0); v = vertical position
  within a frame (cycloneiv_le_model.v_of: lane 7 first).  Periphery frames included.
- RCF: every net's routing tree as edges (src node -> dst node).  Node forms:
    ("W", type, x, y, s, i)        routing element TYPE:XxYySsIi
    ("WB", type, x, y, s, path)    block-port element TYPE:XxYySsB:path
    ("DRV", net)                   the net's driving atom (resolved via the .vo)
    ("SINK", atom, port)           a sink pin; port = route_port when given (the physical pin)
"""
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_decompress as cd  # noqa: E402
import cycloneiv_le_model as lm  # noqa: E402
import cyclonev_vo_parse as vp  # noqa: E402

vp.OUT_PORTS.update({
    "cycloneive_lcell_comb": {"combout", "cout"},
    "cycloneive_io_ibuf": {"o"},
    "cycloneive_io_obuf": {"o", "obar"},
    "cycloneive_clkctrl": {"outclk"},
})

ELEM = re.compile(r"^([A-Z0-9_]+):X(\d+)Y(\d+)S(\d+)(?:I(\d+)|B:(.*))$")


def elem_node(s):
    m = ELEM.match(s.strip())
    if not m:
        raise ValueError(f"unparsed RCF element {s!r}")
    t, x, y, sub, i, path = m.groups()
    if i is not None:
        return ("W", t, int(x), int(y), int(sub), int(i))
    return ("WB", t, int(x), int(y), int(sub), path)


def parse_rcf(path):
    """{net: [(src, dst), ...]}.  Hard error on any line outside the known grammar."""
    nets = {}
    cur = None
    labels = {}
    prev = None
    in_section = False
    for raw in Path(path).read_text().split("\n"):
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("section "):
            in_section = True
            continue
        if in_section:
            if ln == "}":
                in_section = False
            continue
        if ln.startswith("signal_name = "):
            net = ln[len("signal_name = "):].rstrip("{").strip()
            cur = nets.setdefault(net, [])
            labels = {}
            prev = ("DRV", net)
            continue
        if ln == "}":
            cur = None
            continue
        if cur is None:
            raise ValueError(f"{path}: line outside a signal: {ln!r}")
        body = ln.rstrip(";")
        if body.startswith("branch_point = "):
            lab = body[len("branch_point = "):]
            prev = labels[lab]
        elif body.startswith("label = "):
            lab, el = (s.strip() for s in body[len("label = "):].split(",", 1))
            node = elem_node(el)
            labels[lab] = node
            cur.append((prev, node))
            prev = node
        elif body.startswith("dest = "):
            m = re.match(r"dest = \( (.*), (\w+(?:\[\d+\])?) \)(?:, route_port = (\w+(?:\[\d+\])?))?$", body)
            if not m:
                raise ValueError(f"{path}: unparsed dest {ln!r}")
            atom, port, rport = m.groups()
            cur.append((prev, ("SINK", atom, rport or port)))
            prev = ("DRV", net)
        else:
            node = elem_node(body)
            cur.append((prev, node))
            prev = node
    return nets


def cram_plane(rbf_bytes, geom=None):
    """bool array [frame, v] of every configuration bit (frames 1.. incl. periphery)."""
    info = {}
    u = cd.decompress(rbf_bytes, info)
    f, r, n = info["frame"], info["periphery_frames"], info["cram_frames"]
    nfr = r + n
    vmap = vmap_for(f, tuple(geom.lane_bytes) if geom else (lm.TOP,) + (lm.LANE,) * 7)
    plane = np.zeros((nfr, len(vmap)), dtype=bool)
    for fr in range(1, nfr):
        base = cd.PREAMBLE + fr * f
        width = f if fr < r else f - 2     # periphery frames carry no CRC
        chunk = np.frombuffer(u[base:base + width], dtype=np.uint8)
        idx = np.nonzero(np.unpackbits(chunk, bitorder="little"))[0]
        plane[fr, vmap[idx]] = True
    return plane


@lru_cache(maxsize=None)
def vmap_for(f, lane_bytes):
    """frame bit -> v (lane-major, lane 7 first).  Bits outside the lane model (lane tails,
    periphery CRC bytes) get v >= sum(lane_bytes)."""
    vmap = np.full(f * 8, -1, dtype=np.int64)
    extra = sum(lane_bytes)
    for b in range(f * 8):
        byte, lane = divmod(b, 8)
        order = 7 - lane
        if byte < lane_bytes[order]:
            vmap[b] = sum(lane_bytes[:order]) + byte
        else:
            vmap[b] = extra
            extra += 1
    return vmap


def device_of(name):
    import tomllib
    t = tomllib.loads((CORPUS / name / "design.toml").read_text())
    return t.get("device", "EP4CE6E22C8")


def geom_of(name):
    import cycloneiv_geom as cg
    return cg.load(cg.die_of(device_of(name)))


def top_module_only(path):
    """Filtered .vo; GX atoms (cycloneiv_*) renamed to the E names (cycloneive_*): same cells."""
    import cycloneiv_fuzz_analyze as fa
    p = fa.top_module_only(path)
    t = p.read_text()
    t2 = re.sub(r"\bcycloneiv_", "cycloneive_", t)
    if t2 != t:
        p.write_text(t2)
    return p


@lru_cache(maxsize=None)
def load_vo(name):
    return vp.Vo().parse(top_module_only(CORPUS / name / "postfit.vo"))


def load(name):
    d = CORPUS / name
    return {"name": name, "plane": cram_plane((d / "bitstream.rbf").read_bytes(), geom_of(name)),
            "rcf": parse_rcf(d / "routing.rcf"), "vo": load_vo(name)}


def designs(pattern="*"):
    import fnmatch
    return sorted(p.name for p in CORPUS.iterdir()
                  if fnmatch.fnmatch(p.name, pattern) and (p / "routing.rcf").exists()
                  and (p / "bitstream.rbf").exists())
