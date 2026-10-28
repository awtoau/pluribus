"""Cyclone IV corpus loader: CRAM as a (frame, v) bit plane, RCF routing edges, post-fit .vo atoms.

- CRAM plane: frame index as in cycloneiv_fuzz_analyze (header frame = 0); v = vertical position
  within a frame (cycloneiv_le_model.v_of: lane 7 first).  Periphery frames included.
- RCF: every net's routing tree as edges (src node -> dst node).  Node forms:
    ("W", type, x, y, s, i)        routing element TYPE:XxYySsIi
    ("WB", type, x, y, s, path)    block-port element TYPE:XxYySsB:path
    ("DRV", net)                   the net's driving atom (resolved via the .vo)
    ("SINK", atom, port)           a sink pin; port = route_port when given (the physical pin)
"""
import os
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


HAS_MODE = os.environ.get("PLURIBUS_PLANE_HAS", "auto")
HAS_DENSE_MIN = 1 << 16


class SparsePlane:
    """Set CRAM bits as a sorted int32 array of frame * NV + v (a dense plane is 38 MiB per
    EP4CGX150 design, the set bits ~1 MB).  shape = (frames, NV)."""

    def __init__(self, keys, nfr, nv):
        self.keys = keys
        self.shape = (nfr, nv)

    def dense(self):
        """Cached bool bitmap of frame * NV + v, plus one trailing False slot (39 MB on EP4CGX150)."""
        d = self.__dict__.get("_dense")
        if d is None:
            nf, nv = self.shape
            d = np.zeros(nf * nv + 1, bool)
            d[self.keys] = True
            self._dense = d
        return d

    def has(self, f, v):
        """bool array: is (f, v) set; f, v integer arrays (out of range = False).
        PLURIBUS_PLANE_HAS = searchsorted | dense | auto (default: dense for >= 65536 queries; both
        paths return identical results, #145)."""
        f, v = np.asarray(f), np.asarray(v)
        mode = HAS_MODE
        if mode == "dense" or (mode == "auto" and f.size >= HAS_DENSE_MIN):
            nf, nv = self.shape
            ok = (f >= 0) & (f < nf) & (v >= 0) & (v < nv)
            return self.dense()[np.where(ok, f * nv + v, nf * nv)]
        return self._has_searchsorted(f, v)

    def _has_searchsorted(self, f, v):
        nf, nv = self.shape
        ok = (f >= 0) & (f < nf) & (v >= 0) & (v < nv)
        if not len(self.keys):
            return ok & False
        k = np.where(ok, f * nv + v, -1)
        i = np.minimum(np.searchsorted(self.keys, k), len(self.keys) - 1)
        return ok & (self.keys[i] == k)

    def flat_index(self, f, v):
        """int index into dense() per (f, v); out of range -> the trailing False slot.  Cache the result
        when the same (f, v) arrays are queried against many planes (Dec.active)."""
        nf, nv = self.shape
        f, v = np.asarray(f), np.asarray(v)
        ok = (f >= 0) & (f < nf) & (v >= 0) & (v < nv)
        dt = np.int32 if nf * nv + 1 < 2**31 else np.int64
        return np.where(ok, f.astype(dt) * dt(nv) + v.astype(dt), dt(nf * nv))

    def __getitem__(self, fv):
        f, v = fv
        return bool(self.has(np.array([f]), np.array([v]))[0])

    def rect(self, fa, fb, va, vb):
        """bool [fb-fa, vb-va] of the rectangle; out-of-range parts are False."""
        nf, nv = self.shape
        out = np.zeros((fb - fa, vb - va), dtype=bool)
        f0, f1 = max(fa, 0), min(fb, nf)
        v0, v1 = max(va, 0), min(vb, nv)
        if f0 >= f1 or v0 >= v1:
            return out
        fs = np.arange(f0, f1, dtype=np.int64)
        lo = np.searchsorted(self.keys, fs * nv + v0)
        hi = np.searchsorted(self.keys, fs * nv + v1)
        for fi, l, h in zip(range(f0, f1), lo, hi):
            if h > l:
                out[fi - fa, self.keys[l:h] - fi * nv - va] = True
        return out

    def __len__(self):
        return len(self.keys)

    def sum(self):
        return len(self.keys)


def _plane_setup(rbf_bytes, geom):
    info = {}
    u = cd.decompress(rbf_bytes, info)
    f, r, n = info["frame"], info["periphery_frames"], info["cram_frames"]
    vmap = vmap_for(f, tuple(geom.lane_bytes) if geom else (lm.TOP,) + (lm.LANE,) * 7,
                    tuple(map(tuple, geom.lane_swaps)) if geom else ())
    return u, f, r, r + n, vmap


def cram_plane(rbf_bytes, geom=None):
    """SparsePlane of every configuration bit (frames 1.. incl. periphery).  Keys from the nonzero
    bytes only (a plane is ~2-9 % set); PLURIBUS_DECODE=scalar uses cram_plane_scalar."""
    if os.environ.get("PLURIBUS_DECODE") == "scalar":
        return cram_plane_scalar(rbf_bytes, geom)
    u, f, r, nfr, vmap = _plane_setup(rbf_bytes, geom)
    nv = len(vmap)
    arr = np.frombuffer(u, np.uint8, count=(nfr - 1) * f, offset=cd.PREAMBLE + f).reshape(nfr - 1, f)
    row, col = np.nonzero(arr)
    fr = row + 1
    keep = col < np.where(fr < r, f, f - 2)    # CRAM frames carry a 2-byte CRC, periphery frames none
    row, col, fr = row[keep], col[keep], fr[keep]
    bits = (arr[row, col][:, None] >> np.arange(8, dtype=np.uint8)) & 1
    bi, bb = np.nonzero(bits)
    keys = np.sort(fr[bi].astype(np.int64) * nv + vmap[col[bi] * 8 + bb]) if len(bi) else np.zeros(0, np.int64)
    return SparsePlane(keys, nfr, nv)


def cram_plane_scalar(rbf_bytes, geom=None):
    """Reference per-frame unpackbits build (identical keys)."""
    u, f, r, nfr, vmap = _plane_setup(rbf_bytes, geom)
    nv = len(vmap)
    parts = []
    for fr in range(1, nfr):
        base = cd.PREAMBLE + fr * f
        width = f if fr < r else f - 2     # periphery frames carry no CRC
        chunk = np.frombuffer(u[base:base + width], dtype=np.uint8)
        idx = np.nonzero(np.unpackbits(chunk, bitorder="little"))[0]
        if len(idx):
            parts.append(fr * nv + vmap[idx])
    keys = np.sort(np.concatenate(parts)).astype(np.int64) if parts else np.zeros(0, dtype=np.int64)
    return SparsePlane(keys, nfr, nv)


@lru_cache(maxsize=None)
def vmap_for(f, lane_bytes, swaps=()):
    """frame bit -> v (lane-major, lane 7 first).  Bits outside the lane model (lane tails,
    periphery CRC bytes) get v >= sum(lane_bytes).  swaps = ((v, byte, lane), ...): the raw bit
    (byte, lane) takes position v and the bit that held v takes its column (EP4CE6: LE bits at
    the lane joins live in the lane tail bytes)."""
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
    where = {int(v): b for b, v in enumerate(vmap)}
    for v, byte, lane in swaps:
        b_new = byte * 8 + lane
        b_old = where[v]
        vmap[b_old], vmap[b_new] = vmap[b_new], v
        where[int(vmap[b_old])], where[v] = b_old, b_new
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


def load_plane_only(name):
    """SparsePlane of a design without parsing its RCF / .vo."""
    return cram_plane((CORPUS / name / "bitstream.rbf").read_bytes(), geom_of(name))
